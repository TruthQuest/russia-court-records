#!/usr/bin/env python3
"""Step 2. For each case, an ordered list of courts to search -> work/candidates.csv.

Order: courts named in the narrative, then courts implied by docket prefix + articles + city,
then the regional court as a fallback. Moscow 01-/02- dockets go to mos-gorsud.ru.

Cases with a 1- docket but no city and no named court get every district court of their region
("region_scan"), ordered by how many located OVD cases each court already serves. sweep.py searches
each court once per article, so the extra cost scales with courts, not cases. Not capped.
"""
from __future__ import annotations

import argparse
import collections

from rapidfuzz import fuzz

from courtlink.common import LOG, load_config, read_csv, setup_logging, work_path, write_csv
from courtlink.translit import skeleton

STRIP = {"district", "city", "regional", "court", "of", "the", "krai", "oblast", "republic",
         "garrison", "military", "inter", "interdistrict", "municipal", "supreme"}


def mention_key(m: str) -> str:
    toks = [t for t in skeleton(m).split() if t not in {skeleton(x) for x in STRIP}]
    return " ".join(toks)


def city_match(stem: str, court: dict) -> bool:
    toks = court["name_skel"].split()
    stems = stem.split()
    return bool(stems) and all(any(t.startswith(st) for t in toks) for st in stems)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    cc = cfg["candidates"]
    mil_arts, gar_arts = set(cc["military_articles"]), set(cc["garrison_articles"])
    cap = int(cc["max_courts_per_case"])

    cases = read_csv(work_path(cfg, "cases.csv"))
    courts = read_csv(work_path(cfg, "courts.csv"))
    by_subj = collections.defaultdict(list)
    for c in courts:
        by_subj[c["subj"]].append(c)
    military = [c for c in courts if c["court_type"] == "military_district"]

    # court volume prior: located OVD cases whose city points at each district court
    volume = collections.Counter()
    for case in cases:
        if case["city_stem"]:
            for s in filter(None, case["subj"].split(";")):
                for c in by_subj.get(s, []):
                    if c["court_type"] == "district" and city_match(case["city_stem"], c):
                        volume[c["court_id"]] += 1

    out, stats = [], collections.Counter()
    for case in cases:
        cands: list[tuple[dict, str, str]] = []  # (court, instance, reason)
        seen = set()

        def add(court: dict, reason: str, instance: str = "criminal_first") -> None:
            k = (court.get("court_id"), instance)
            if k not in seen:
                seen.add(k)
                cands.append((court, instance, reason))

        arts = set(filter(None, case["articles"].split(";")))
        is_mil, is_gar = bool(arts & mil_arts), bool(arts & gar_arts)
        lvl = case["level_hint"]
        subjs = [s for s in case["subj"].split(";") if s]
        local = [c for s in subjs for c in by_subj.get(s, [])]

        if lvl.startswith("mosgorsud") or ("RU-MOW" in case["iso"] and not case["docket"] and not is_mil):
            add({"court_id": "mosgorsud", "name": "mos-gorsud.ru", "court_type": "mosgorsud",
                 "url": cfg["mosgorsud"]["base"]}, f"moscow:{lvl or 'no-docket'}")

        for m in filter(None, case["court_mentions"].split(" || ")):
            mk = mention_key(m)
            if len(mk) < 4:
                continue
            pool = local or courts
            scored = sorted(((fuzz.partial_ratio(mk, c["name_skel"]), c) for c in pool), key=lambda x: -x[0])
            for sc, c in scored[:2]:
                if sc >= 85:
                    add(c, f"named_in_text:{m[:60]}")

        regional = [c for c in local if c["court_type"] == "regional"]
        districts = [c for c in local if c["court_type"] == "district" and city_match(case["city_stem"], c)]
        garrisons = [c for c in local if c["court_type"] == "garrison"]

        if lvl == "magistrate":
            stats["magistrate_manual"] += 1  # magistrate courts: manual lookup (08_manual.py)
        elif lvl == "regional_appeal":
            for c in regional:
                add(c, "appeal_docket", "criminal_appeal")
        elif lvl == "regional_or_military":
            first, second = (military, regional) if is_mil else (regional, military)
            for c in first + second:
                add(c, "prefix_2" + (":military_article" if is_mil else ""))
        elif not lvl and is_mil:
            for c in military + regional + districts:
                add(c, "no_docket:military_article")
        elif lvl == "district" or not lvl:
            if is_gar:
                for c in garrisons:
                    add(c, "garrison_article")
            for c in districts:
                add(c, "city_district_court")
            if lvl == "district" and not districts and not any(r.startswith("named_in_text") for _, _, r in cands):
                scan = sorted((c for c in local if c["court_type"] == "district"),
                              key=lambda c: (-volume[c["court_id"]], c["name"]))
                for c in scan:
                    add(c, "region_scan:no_city")
                if scan:
                    stats["region_scan_cases"] += 1
            for c in regional:
                add(c, "regional_fallback")
        if not cands:
            stats["no_candidates"] += 1
        keep = [x for i, x in enumerate(cands) if i < cap or x[2].startswith("region_scan")]
        for rank, (c, inst, why) in enumerate(keep):
            out.append({"record_id": case["record_id"], "rank": rank, "court_id": c.get("court_id", ""),
                        "court_name": c.get("name", ""), "court_type": c.get("court_type", ""),
                        "url": c.get("url", ""), "srv": c.get("srv", "1") or "1",
                        "sudrf_code": c.get("sudrf_code", ""), "instance": inst, "reason": why})
        stats["n_cand:" + (str(len(keep)) if len(keep) <= cap else f">{cap}")] += 1
    write_csv(work_path(cfg, "candidates.csv"), out)
    for k, v in sorted(stats.items()):
        LOG.info("%-20s %6d", k, v)


if __name__ == "__main__":
    main()
