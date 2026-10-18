#!/usr/bin/env python3
"""Court census from pages already downloaded. No network, no captchas.

Every article search the sweep ran returned the court's FULL list of cases under that article, not just
OVD-Info's. Those pages sit in work/cache. This script parses them all into one census of court cases:

    work/census.csv     one row per court case: court, docket, registration date, judge, decision date,
                        outcome class, articles, number of defendants, whether an OVD-Info record is
                        linked, and the fingerprint of the page it came from.

Defendant names are NOT written: only a count. The census feeds kg_build.py and kg_analytics.py
(coverage gaps, assignment concentration, judge outcome profiles).

    python census.py

OVD-Info name check (in memory only): for each court case the script counts how many of its defendants have the same
surname and first initial as an OVD-Info record in the same region that carries one of the case's articles
(`ovd_named`). Names are compared, never written. coverage_gap.py turns this into OVD-Info coverage estimates.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from courtlink.common import LOG, court_id_from_url, load_config, parse_date, read_csv, setup_logging, work_path, write_csv
from courtlink.parsers import extract_names, hidden_names, parse_results
from courtlink.translit import skeleton

ART_RE = re.compile(r"ст\.?\s*(\d{2,3}(?:\.\d{1,2})?)", re.I)
# "ст.354.1 ч.3" or "ч.3 ст.354.1" (parts separate e.g. speech from memorial desecration in 354.1)
PART_AFTER = re.compile(r"ст\.?\s*(\d{2,3}(?:\.\d{1,2})?)\s*,?\s*ч\.?\s*(\d)", re.I)
PART_BEFORE = re.compile(r"ч\.?\s*(\d)\s*,?\s*ст\.?\s*(\d{2,3}(?:\.\d{1,2})?)", re.I)


def article_parts(info: str) -> str:
    parts = {(a, p) for a, p in PART_AFTER.findall(info or "")} | {(a, p) for p, a in PART_BEFORE.findall(info or "")}
    return ";".join(f"{a}({p})" for a, p in sorted(parts))
FIELDS = ["court_id", "court_name", "court_type", "region_iso", "srv", "docket", "docket_key", "received", "judge",
          "decision_date", "decision", "outcome_class", "articles", "article_parts", "article_queried", "n_defendants",
          "ovd_linked", "ovd_linked_n", "ovd_named", "names_hidden", "case_url", "source_url", "source_sha256", "fetched_at"]


def _outcome_class():
    from courtlink.outcomes import outcome_class
    return outcome_class


MULTI_REGION = {"military_district", "appellate", "cassation"}  # courts whose defendants come from several regions


def name_key(last: str, first: str) -> tuple[str, str]:
    return skeleton(last), skeleton(first)[:1]


def ovd_index(cases: list[dict]) -> dict:
    """(iso, surname skeleton, first initial) -> {record_id: (articles, persecution start year or None)}.
    Anonymous records (no name) are not indexed."""
    idx = collections.defaultdict(dict)
    for c in cases:
        if not c.get("last_name"):
            continue
        arts = frozenset(filter(None, c.get("articles", "").split(";")))
        sy = c.get("started_date", "")[:4]
        lasts = [c["last_name"]] + [x for x in c.get("cyr_last_candidates", "").split(";") if x]
        for iso in list(filter(None, (x.strip() for x in c.get("iso", "").split(",")))) + ["*"]:
            for ln in lasts:  # "*" = any region: district military courts try defendants from many regions
                idx[(iso, *name_key(ln, c.get("first_name", "")))][c.get("record_id", id(c))] = (arts, int(sy) if sy.isdigit() else None)
    return idx


def name_match(idx: dict, iso: str, name: str, row_arts: set, reg_year: int | None, linked_elsewhere: set) -> str:
    """The single OVD-Info record a court defendant matches, or '' when none or more than one does.
    Match = same region, surname skeleton and first initial, a shared article, the persecution starting no later than
    the registration year and at most 5 years before it, and the record not docket-linked to another registration.
    Requiring exactly one candidate keeps common surnames (several OVD-Info records of one name) from inflating
    coverage; such defendants are counted as not matched."""
    cands = []
    for rid, (arts, sy) in idx.get((iso, *court_name_key(name)), {}).items():
        if not (arts & row_arts) or rid in linked_elsewhere:
            continue
        if sy is not None and reg_year is not None and not (reg_year - 5 <= sy <= reg_year):
            continue
        cands.append(rid)
    return cands[0] if len(cands) == 1 else ""


def court_name_key(n: str) -> tuple[str, str]:
    toks = n.replace(".", ". ").split()
    return name_key(toks[0] if toks else "", toks[1] if len(toks) > 1 else "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    oc = _outcome_class()
    courts = {c["court_id"]: c for c in read_csv(work_path(cfg, "courts.csv"))} if work_path(cfg, "courts.csv").exists() else {}
    mp = work_path(cfg, "matches.csv")
    linked_n = collections.Counter()  # (court, docket) -> OVD-Info records docket-linked to it
    rec_link = collections.defaultdict(set)  # record -> registrations it is linked to
    for m in (read_csv(mp) if mp.exists() else []):
        linked_n[(m["court_id"], m["docket_key"])] += 1
        rec_link[m["record_id"]].add((m["court_id"], m["docket_key"]))
    first_delo = str(cfg["sudrf"]["instances"]["criminal_first"]["delo_id"])
    cp = work_path(cfg, "cases.csv")
    oidx = ovd_index(read_csv(cp)) if cp.exists() else {}
    cache = Path(cfg["_work"]) / "cache"
    rows, stats = {}, collections.Counter()
    for meta_p in sorted(cache.glob("*.json")):
        try:
            meta = json.loads(meta_p.read_text("utf-8"))
        except Exception:
            continue
        url = meta.get("url", "")
        q = {k.lower(): v for k, v in parse_qsl(urlsplit(url).query, keep_blank_values=True)}
        if q.get("name_op") != "r" or meta.get("status") != 200:
            continue
        if q.get("delo_id", first_delo) != first_delo:  # appeal or other instance: not part of the first-instance census
            stats["other_instance_pages"] += 1
            continue
        if "page" in q and "u1_defendant__law_articless" not in q:
            stats["unattributable_pages"] += 1  # a bare page-N link cached before the fix: rerun the sweep to refetch
            continue
        stats["result_pages"] += 1
        body = (cache / (meta_p.stem + ".body")).read_bytes().decode(meta.get("encoding") or "utf-8", errors="replace")
        cid = court_id_from_url(url)
        c = courts.get(cid, {})
        art_q = q.get("u1_defendant__law_articless", "")
        for r in parse_results(body, url):
            key = (cid, q.get("srv_num", "1"), r["docket_key"])
            info = r.get("info") or r.get("row_text", "")
            arts = sorted(set(ART_RE.findall(info)), key=lambda x: [int(p) for p in x.split(".")])
            names = extract_names(info)
            n_hidden = hidden_names(info)
            row_arts = set(arts) | ({art_q} if art_q else set())
            ry = r["docket_key"].rsplit("/", 1)[-1]
            ry = int(ry) if ry.isdigit() else None
            here = (cid, r["docket_key"])
            elsewhere = {rid for rid, regs in rec_link.items() if here not in regs}
            scope = "*" if c.get("court_type") in MULTI_REGION else c.get("iso", "")
            hits = [name_match(oidx, scope, n, row_arts, ry, elsewhere) for n in names]
            named = len({h for h in hits if h})
            prev = rows.get(key)
            row = {"court_id": cid, "court_name": c.get("name", ""), "court_type": c.get("court_type", ""),
                   "region_iso": c.get("iso", ""), "srv": q.get("srv_num", "1"), "docket": r.get("docket", ""),
                   "docket_key": r["docket_key"], "received": parse_date(r.get("received", "")) or "",
                   "judge": r.get("judge", ""), "decision_date": parse_date(r.get("decision_date", "")) or "",
                   "decision": r.get("decision", ""), "outcome_class": oc(r.get("decision", "")) if r.get("decision") else "pending",
                   "articles": ";".join(arts), "article_parts": article_parts(info), "article_queried": art_q,
                   "n_defendants": max(1, len(names) + n_hidden), "names_hidden": n_hidden, "ovd_named": named,
                   "ovd_linked": "1" if linked_n.get(here) else "", "ovd_linked_n": linked_n.get(here, 0),
                   "case_url": r.get("case_url", ""), "source_url": url, "source_sha256": meta.get("sha256", ""),
                   "fetched_at": meta.get("fetched_at", "")}
            if prev:  # keep the most recent page's view; merge queried articles
                stats["duplicates"] += 1
                row["article_queried"] = ";".join(sorted(set(filter(None, (prev["article_queried"] + ";" + art_q).split(";")))))
                if prev["fetched_at"] > row["fetched_at"]:
                    row = {**prev, "article_queried": row["article_queried"]}
            rows[key] = row
    out = sorted(rows.values(), key=lambda r: (r["court_id"], r["docket_key"]))
    write_csv(work_path(cfg, "census.csv"), out, FIELDS)
    n_link = sum(1 for r in out if r["ovd_linked"])
    if stats["unattributable_pages"]:
        LOG.warning("%d cached later result pages carry no search parameters and were skipped; rerun "
                    "`census_sweep.py political --redo-multipage` (and baseline) to refetch them", stats["unattributable_pages"])
    LOG.info("result pages: %d  court cases: %d  courts: %d  judges: %d  linked to OVD-Info: %d  not in OVD-Info: %d",
             stats["result_pages"], len(out), len({r["court_id"] for r in out}),
             len({(r["court_id"], r["judge"]) for r in out if r["judge"]}), n_link, len(out) - n_link)


if __name__ == "__main__":
    main()
