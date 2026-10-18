#!/usr/bin/env python3
"""How much of the court record OVD-Info covers: defendants prosecuted under articles that are political by
construction, counted on court sites, against the defendants OVD-Info has a record for.

    python coverage_gap.py                 after census_sweep.py political + census.py
    python coverage_gap.py --years 2022-2025

Unit: defendant in a first-instance registration (census.csv n_defendants), registration year from the docket.
A court defendant counts as covered by OVD-Info when
  (a) the registration is docket-linked to an OVD-Info record (ovd_linked), or
  (b) census.py found an OVD-Info record in the same region, with the same surname and first initial, carrying one of
      the registration's articles (ovd_named).
Name matching misses some true matches (spelling, transliteration, maiden names). Its recall is measured on the
docket-linked registrations, where the answer is known, and coverage is reported raw and recall-corrected.
OVD-Info records with names withheld cannot be name-matched; their number per region and article is reported as the
upper bound they could add.

Writes work/analysis/coverage_{region,article,year}.csv and work/analysis/coverage.md (aggregates only, no names).
"""
from __future__ import annotations

import argparse
import collections
import math
from pathlib import Path

from courtlink.common import LOG, load_config, read_csv, setup_logging, work_path, write_csv
from courtlink.constants import CENSUS_ARTICLES

MIN_RECALL_N, MIN_RECALL = 20, 0.2  # below these the recall correction is not applied (columns left blank)


def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def reg_year(r: dict) -> int | None:
    y = r.get("docket_key", "").rsplit("/", 1)[-1]
    if y.isdigit():
        return int(y)
    return int(r["received"][:4]) if r.get("received", "")[:4].isdigit() else None


def article_of(r: dict, arts: list[str]) -> str:
    have = set(filter(None, (r.get("articles", "") + ";" + r.get("article_queried", "")).split(";")))
    return next((a for a in arts if a in have), "")


def complete_searches(log: list[dict]) -> set[tuple[str, str, str]]:
    """(court, srv, article) whose census search ran to the end (census_sweep.py political)."""
    return {(r["court_id"], r["srv"], r["query"].split()[0]) for r in log
            if r.get("mode") == "political" and r.get("state") in ("results", "empty")}


def merge_same_case(rows: list[dict], uids: dict) -> tuple[list[dict], int]:
    """One case registered more than once (sent to another court, or returned to the prosecutor and filed again)
    shares its case UID: keep the latest registration and carry over whatever OVD-Info link any of them had."""
    groups = collections.defaultdict(list)
    for i, r in enumerate(rows):
        groups[uids.get((r["court_id"], r["docket"])) or f"_{i}"].append(r)
    out, merged = [], 0
    for g in groups.values():
        base = dict(max(g, key=lambda r: r.get("received", "")))
        for k in ("n", "linked", "named", "covered"):
            base[k] = max(r[k] for r in g)
        base["hidden"] = min(base["n"], min(r["hidden"] for r in g))
        merged += len(g) - 1
        out.append(base)
    return out, merged


def analyse(census: list[dict], cases: list[dict], arts: list[str], y1: int, y2: int, complete=None,
            exclude_parts=(), uids=None) -> dict:
    """complete: set from complete_searches(); None = use every census row (tests, or --all-cache).
    uids: {(court_id, docket_key): case UID} from census_cards.py; registrations sharing a UID are one case.
    exclude_parts: article parts left out of the coverage tables (still listed in not_in_ovd.csv for gap_acts.py)."""
    rows, dropped = [], 0
    for r in census:
        a, y = article_of(r, arts), reg_year(r)
        if not a or y is None or not (y1 <= y <= y2):
            continue
        if complete is not None:
            queried = set(filter(None, r.get("article_queried", "").split(";")))
            if not any((r["court_id"], r.get("srv") or "1", q) in complete for q in queried & set(arts)):
                dropped += 1  # page from a targeted OVD-Info sweep or an unfinished search: not a full count
                continue
        n = max(1, int(r.get("n_defendants") or 1))
        # OVD-Info records docket-linked to this registration (older census files only have the 0/1 flag)
        ln = int(r.get("ovd_linked_n") or (1 if r.get("ovd_linked") == "1" else 0))
        ln = min(n, ln)
        named = min(n, int(r.get("ovd_named") or 0))
        ct = r.get("court_type", "")
        level = {"military_district": "district military", "regional": "regional", "district": "district"}.get(ct, ct or "?")
        iso = r.get("region_iso", "") + (" (military court)" if ct == "military_district" else "")
        rows.append({"court_id": r.get("court_id", ""), "court_name": r.get("court_name", ""), "docket": r.get("docket_key", ""),
                     "received": r.get("received", ""), "outcome": r.get("outcome_class", ""), "case_url": r.get("case_url", ""),
                     "iso": iso, "level": level, "art": a, "year": y, "n": n, "linked": ln, "named": named,
                     "part": next((f"{a} part {x.split('(')[1].rstrip(')')}" for x in r.get("article_parts", "").split(";")
                                   if x.startswith(a + "(")), f"{a} part not listed"),
                     "covered": max(ln, named), "hidden": min(n, int(r.get("names_hidden") or 0))})
    rows, merged = merge_same_case(rows, uids or {})
    all_rows = rows
    rows = [r for r in rows if r["part"] not in set(exclude_parts)]
    excluded = {p: sum(r["n"] for r in all_rows if r["part"] == p) for p in exclude_parts}
    # recall of name matching, on registrations whose OVD-Info link is known from the docket
    # recall: of the defendants known (by docket link) to have an OVD-Info record, how many does the name check find
    lk = [r for r in rows if r["linked"]]
    recall_n = sum(r["linked"] for r in lk)
    recall_k = sum(min(r["named"], r["linked"]) for r in lk)
    recall = recall_k / recall_n if recall_n else None
    usable = recall is not None and recall_n >= MIN_RECALL_N and recall >= MIN_RECALL
    anon = collections.Counter()
    for c in cases:
        if c.get("last_name"):
            continue
        for iso in filter(None, (x.strip() for x in c.get("iso", "").split(","))):
            for a in set(filter(None, c.get("articles", "").split(";"))) & set(arts):
                anon[(iso, a)] += 1

    def table(names, key):
        agg = collections.defaultdict(lambda: {"court_defendants": 0, "covered": 0, "linked": 0, "named_only": 0,
                                               "names_withheld": 0, "names_shown": 0, "covered_shown": 0,
                                               "linked_shown": 0, "named_only_shown": 0})
        for r in rows:
            g = agg[tuple(r[k] for k in key)]
            g["court_defendants"] += r["n"]; g["covered"] += r["covered"]
            g["linked"] += r["linked"]
            g["named_only"] += max(0, r["named"] - r["linked"])
            g["names_withheld"] += r["hidden"]
            if not r["hidden"]:  # registrations where the court shows every name: the name check can work
                g["names_shown"] += r["n"]; g["covered_shown"] += r["covered"]
                g["linked_shown"] += r["linked"]; g["named_only_shown"] += max(0, r["named"] - r["linked"])
        out = []
        for k, g in agg.items():
            n, cov = g["court_defendants"], g["covered"]
            lo, hi = wilson(cov, n)
            # recall-corrected: name-only matches scaled up by 1/recall (never above the court count)
            corr = min(n, g["linked"] + g["named_only"] / recall) if usable else None
            ns = g["names_shown"]
            corr_s = min(ns, g["linked_shown"] + g["named_only_shown"] / recall) if (usable and ns) else None
            out.append({**dict(zip(names, k)), **g, "coverage": round(cov / n, 3), "ci95_low": round(lo, 3),
                        "ci95_high": round(hi, 3),
                        "coverage_recall_corrected": round(corr / n, 3) if corr is not None else "",
                        "not_in_ovd_estimate": round(n - corr, 1) if corr is not None else "",
                        "coverage_names_shown": round(g["covered_shown"] / ns, 3) if ns else "",
                        "coverage_names_shown_corrected": round(corr_s / ns, 3) if corr_s is not None else ""})
        return sorted(out, key=lambda r: -r["court_defendants"])

    reg_art = table(["iso", "article"], ["iso", "art"])
    for r in reg_art:
        r["ovd_records_name_withheld"] = anon.get((r["iso"], r["article"]), 0)
    tot_n = sum(r["n"] for r in rows)
    tot_hidden = sum(r["hidden"] for r in rows)
    tot_c = sum(r["covered"] for r in rows)
    gaps = [{"region": r["iso"], "court_id": r["court_id"], "court": r["court_name"], "docket": r["docket"], "article": r["part"],
             "received": r["received"], "outcome": r["outcome"], "defendants": r["n"], "with_ovd_record": r["covered"],
             "case_url": r["case_url"]} for r in all_rows if r["covered"] < r["n"]]
    return {"rows": len(rows), "dropped_incomplete": dropped, "gaps": sorted(gaps, key=lambda g: (g["region"], g["court"], g["docket"])), "level": table(["court_level"], ["level"]),
            "article_part": table(["article_part"], ["part"]),
            "defendants": tot_n, "covered": tot_c, "recall": recall, "recall_n": recall_n,
            "recall_usable": usable, "names_withheld": tot_hidden, "excluded": excluded, "merged_same_case": merged,
            "uids_known": bool(uids),
            "region": table(["iso"], ["iso"]), "article": table(["article"], ["art"]), "year": table(["year"], ["year"]), "region_article": reg_art}


def pct(x) -> str:
    return f"{x:.0%}" if x != "" and x is not None else "n/a"


def write_md(R: dict, path: Path, y1: int, y2: int) -> None:
    lo, hi = wilson(R["covered"], R["defendants"])
    L = ["# OVD-Info coverage of political-article prosecutions on court sites", "",
         f"Registrations {y1}-{y2} under articles that are political by construction; unit = defendant.", ""]
    if not R["defendants"]:
        L.append("No census rows under these articles yet: run `census_sweep.py political` and `census.py`.")
    else:
        rec = (f"{R['recall']:.0%} (on {R['recall_n']} docket-linked defendants)" if R["recall"] is not None
               else "not measurable (no docket-linked registrations)")
        L += [f"- {R['merged_same_case']} registrations were the same case registered again (same case UID: sent to "
              "another court, or returned to the prosecutor and filed again) and are counted once."
              if R.get("uids_known") else "- Case UIDs not fetched (run census_cards.py): a case registered twice "
              "(sent to another court, or returned to the prosecutor) is counted twice."]
        L += [f"- Left out of every table below: {p} ({n} defendants). Its judgments are mostly Holocaust denial or "
              "Nazi praise, which OVD-Info does not count as political prosecution; see gap_acts.csv."
              for p, n in R.get("excluded", {}).items()]
        L += [f"- Only searches the census sweep ran to the end are counted; {R['dropped_incomplete']} registrations from "
              "targeted or unfinished searches were left out (they over-represent courts where OVD-Info already has cases).",
              f"- Court defendants: **{R['defendants']}**; with an OVD-Info record: **{R['covered']}** "
              f"({R['covered'] / R['defendants']:.0%}, 95% CI {lo:.0%} to {hi:.0%}).",
              f"- The court withholds the defendant's name for **{R['names_withheld']}** of them (\"<Информация скрыта>\"): those can only be "
              "found by docket number, so they are shown separately below (\"where names shown\") as well as in the totals.",
              f"- Name-match recall: {rec}. " + ("Coverage scaled for missed name matches is in the tables." if R["recall_usable"]
                 else f"Too few docket-linked defendants (or recall below {MIN_RECALL:.0%}) to correct for missed matches: "
                      "the raw coverage is a lower bound and the corrected column is left blank."),
              "- 'Not in OVD-Info' means no record found here: a list for OVD-Info to check, not a finding that they "
              "are unknown to OVD-Info. Records with names withheld are listed per region and article as the most they could add.",
              "", "| Article | Court defendants | Names withheld | Covered | Coverage | Recall-corrected | Where names shown (corrected) |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r['article']} | {r['court_defendants']} | {r['names_withheld']} | {r['covered']} | {r['coverage']:.0%} | {pct(r['coverage_recall_corrected'])} | {pct(r['coverage_names_shown_corrected'])} |"
              for r in R["article"]]
        L += ["", "| Article and part | Court defendants | Names withheld | Covered | Coverage | Recall-corrected | Where names shown (corrected) |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r['article_part']} | {r['court_defendants']} | {r['names_withheld']} | {r['covered']} | {r['coverage']:.0%} | {pct(r['coverage_recall_corrected'])} | {pct(r['coverage_names_shown_corrected'])} |"
              for r in sorted(R["article_part"], key=lambda x: x["article_part"])]
        L += ["", "| Registration year | Court defendants | Covered | Coverage | Recall-corrected |", "|---|---|---|---|---|"]
        L += [f"| {r['year']} | {r['court_defendants']} | {r['covered']} | {r['coverage']:.0%} | {pct(r['coverage_recall_corrected'])} |"
              for r in sorted(R["year"], key=lambda x: x["year"])]
        L += ["", "| Court level | Court defendants | Names withheld | Covered | Coverage | Recall-corrected | Where names shown (corrected) |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r['court_level']} | {r['court_defendants']} | {r['names_withheld']} | {r['covered']} | {r['coverage']:.0%} | {pct(r['coverage_recall_corrected'])} | {pct(r['coverage_names_shown_corrected'])} |"
              for r in R["level"]]
        L += ["", "| Region | Court defendants | Covered | Coverage (95% CI) | Recall-corrected |", "|---|---|---|---|---|"]
        L += [f"| {r['iso']} | {r['court_defendants']} | {r['covered']} | {r['coverage']:.0%} ({r['ci95_low']:.0%} to "
              f"{r['ci95_high']:.0%}) | {pct(r['coverage_recall_corrected'])} |" for r in R["region"][:40]]
        L += ["", "Defendants in one registration are not independent (one OVD-Info case often covers all of them), so the "
              "intervals are narrower than a registration-clustered interval would be. The registrations with defendants not "
              "found in OVD-Info are listed (court, docket, link; no names) in not_in_ovd.csv, for OVD-Info to check. A name match requires exactly one OVD-Info "
              "record of that surname and initial in the region with a shared article and a plausible start year, so common "
              "surnames count as not matched: coverage errs low, not high."]
    path.write_text("\n".join(L) + "\n", "utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--articles", nargs="*", default=CENSUS_ARTICLES)
    ap.add_argument("--years", default="2022-2026")
    ap.add_argument("--all-cache", action="store_true",
                    help="count every cached results page, including targeted sweeps (biased toward courts with OVD-Info cases)")
    ap.add_argument("--exclude-parts", nargs="*", default=["354.1 part 2"],
                    help="article parts left out of the coverage tables (default: '354.1 part 2'; pass nothing to keep all)")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    y1, y2 = (int(x) for x in a.years.split("-"))
    census = read_csv(work_path(cfg, "census.csv"))
    lp = work_path(cfg, "census_log.csv")
    complete = None if a.all_cache else complete_searches(read_csv(lp) if lp.exists() else [])
    cp = work_path(cfg, "cases.csv")
    up = work_path(cfg, "census_uids.csv")
    uids = {(u["court_id"], u["docket_key"]): u["uid"] for u in read_csv(up) if u.get("uid")} if up.exists() else None
    R = analyse(census, read_csv(cp) if cp.exists() else [], a.articles, y1, y2, complete, a.exclude_parts, uids)
    out = Path(cfg["_work"]) / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    for k in ("region", "article", "year", "region_article", "level", "article_part"):
        write_csv(out / f"coverage_{k}.csv", R[k])
    write_csv(out / "not_in_ovd.csv", R["gaps"])
    write_md(R, out / "coverage.md", y1, y2)
    LOG.info("court defendants %d, covered %d, name-match recall %s -> %s", R["defendants"], R["covered"],
             f"{R['recall']:.2f}" if R["recall"] is not None else "n/a", out / "coverage.md")


if __name__ == "__main__":
    main()
