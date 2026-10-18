#!/usr/bin/env python3
"""Run the analysis queries over your graph + the court layer + what the reasoner inferred.

    python graph/run_queries.py                 all queries in graph/queries/
    python graph/run_queries.py 05 09           only those
    python graph/run_queries.py --sparql my.rq  any query of your own against the same graph

Loads work/graph/joined.nt and work/graph/inferred.ttl (from reason.py). If inferred.ttl is missing, the SPARQL
fallbacks in graph/rules/ are applied instead (same rules; no transitive closure for clusters).
Writes work/graph/results/<query>.csv and work/graph/findings.md (aggregates only, no names).
Some result CSVs carry OVD-Info case labels, which contain defendants' names: keep work/ private.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import date
from pathlib import Path

from rdflib import Graph

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from courtlink.common import load_config  # noqa: E402

HERE = Path(__file__).resolve().parent


def table(rows, cols, n=15):
    if not rows:
        print("   (no rows)"); return
    w = {c: min(48, max(len(c), *(len(str(r.get(c, ""))) for r in rows[:n]))) for c in cols}
    print("   " + "  ".join(c.ljust(w[c]) for c in cols))
    for r in rows[:n]:
        print("   " + "  ".join(str(r.get(c, ""))[:48].ljust(w[c]) for c in cols))
    if len(rows) > n:
        print(f"   ... {len(rows) - n} more")


def run(g, path):
    res = g.query(Path(path).read_text("utf-8"))
    cols = [str(v) for v in res.vars]
    rows = [{c: ("" if r[i] is None else str(r[i])) for i, c in enumerate(cols)} for r in res]
    return cols, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*"); ap.add_argument("--config"); ap.add_argument("--sparql")
    a = ap.parse_args()
    cfg = load_config(a.config)
    gdir = Path(cfg["_work"]) / "graph"
    g = Graph()
    g.parse(gdir / "joined.nt", format="nt")
    inf = gdir / "inferred.ttl"
    if inf.exists():
        g.parse(inf); print(f"graph: {len(g)} triples (joined + Pellet inferences)")
    else:
        for r in sorted((HERE / "rules").glob("*.rq")):
            g += g.query(r.read_text("utf-8")).graph
        print(f"graph: {len(g)} triples (joined + SPARQL fallback rules; run reason.py for full OWL/SWRL inference)")
    for r in sorted((HERE / "closed").glob("*.rq")):  # closed-world rules: after inference, never inside OWL
        g += g.query(r.read_text("utf-8")).graph
    out = gdir / "results"; out.mkdir(exist_ok=True)
    if a.sparql:
        cols, rows = run(g, a.sparql); table(rows, cols, 50); return
    results = {}
    for q in sorted((HERE / "queries").glob("*.rq")):
        if a.only and not any(q.name.startswith(x) for x in a.only):
            continue
        cols, rows = run(g, q)
        results[q.stem] = rows
        with open(out / f"{q.stem}.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=cols); wr.writeheader(); wr.writerows(rows)
        print(f"\n== {q.stem}  ({len(rows)} rows)")
        show = [c for c in cols if c not in ("case", "p", "post", "caseLabel", "reg")]
        table(rows, show)
    if not a.only:
        findings(results, gdir / "findings.md")


def days(a, b):
    try:
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    except ValueError:
        return None


def findings(R, path):
    L = ["# CourtLink x persecution graph: findings (aggregates only)", ""]
    r1 = R.get("01_one_case_many_registrations", [])
    if r1:
        L.append(f"- **One OVD-Info case, several court registrations:** {len(r1)} OVD-Info cases are held by the courts as more than one "
                 f"registration (largest: {max(int(r['registrations']) for r in r1)} registrations, "
                 f"{max(int(r['judges']) for r in r1)} judges).")
    r2 = R.get("02_court_cluster_vs_ovd_cases", [])
    if r2:
        L.append(f"- **Separate OVD-Info cases registered side by side:** {sum(int(r['pairs']) for r in r2)} pairs of registrations at "
                 f"{len({r['courtEn'] for r in r2})} courts have dockets 1 to 5 apart in the same year and share an article, but OVD-Info "
                 f"records them under different cases (pairs only, no chaining). By court:")
    for r in r2:
        L.append(f"  - {r['courtEn']}, {r['docketYear']}: {r['pairs']} pairs, {r['ovdCases']} OVD-Info cases "
                 f"({r['dockets']}); persecutions began {r['firstStart'][:10]} to {r['lastStart'][:10]}.")
    r3 = R.get("03_codefendants_not_yet_linked", [])
    if r3:
        miss = sum(int(r["ovdDefendants"]) - int(r["linked"]) for r in r3)
        L.append(f"- **Co-defendants still to locate:** {len(r3)} linked OVD-Info cases have {miss} co-defendants with no court registration yet.")
    r4 = R.get("04_forum_geography", [])
    if r4:
        tot = sum(int(r["persecutions"]) for r in r4)
        mil = sum(int(r["persecutions"]) for r in r4 if r["level"] == "MilitaryDistrictCourt")
        L.append(f"- **Tried outside the region of prosecution:** {tot} linked persecutions, {mil} of them by district military courts.")
    r5 = R.get("05_posts_applying_incompatible_articles", [])
    if r5:
        regs = sum(int(r["registrations"]) for r in r5); after = sum(int(r["afterECtHR"]) for r in r5)
        L.append(f"- **ICCPR:** {len(r5)} judicial posts presided over {regs} registrations under articles your graph classes as facially "
                 f"incompatible with the ICCPR; {after} of those decisions came after the ECtHR jurisdiction cutoff recorded in the graph.")
    r10 = R.get("10_after_ecthr_by_character", [])
    if r10:
        L.append("- **Decided after the ECtHR cutoff, by article character:** " +
                 "; ".join(f"{r['character']}: {r['afterCutoff']} of {r['decided']}" for r in r10) + ".")
    r6 = R.get("06_facial_character_by_court_level", [])
    if r6:
        L.append("- **Facial character by court level:** " + "; ".join(f"{r['character']} at {r['level']}: {r['registrations']}" for r in r6) + ".")
    r7 = R.get("07_detained_without_terminal_result", [])
    if r7:
        L.append(f"- **Imprisoned with no terminal result posted:** {len(r7)} persecutions.")
    r8 = R.get("08_long_court_phase", [])
    if r8:
        L.append(f"- **Proceedings older than their docket by 2+ years:** {len(r8)} registrations "
                 f"({len({r['uid'] for r in r8})} proceedings).")
    r9 = R.get("09_time_to_judgment", [])
    if r9:
        by = {}
        for r in r9:
            d = days(r["start"], r["decided"])
            if d is not None and d >= 0:
                by.setdefault(r["level"], []).append(d)
        line = ("- **Persecution start to first-instance decision (median days, terminal results, exact start dates only, one value per registration):** " +
                "; ".join(f"{k}: {statistics.median(v):.0f} (n={len(v)})" for k, v in sorted(by.items())) + ".")
        if by.get("MilitaryDistrictCourt") and by.get("DistrictCourt"):
            try:
                from scipy.stats import mannwhitneyu
                u = mannwhitneyu(by["MilitaryDistrictCourt"], by["DistrictCourt"], alternative="two-sided")
                line += f" Military against district: Mann-Whitney p = {u.pvalue:.3f}."
            except ImportError:
                pass
        L.append(line)
    Path(path).write_text("\n".join(L) + "\n", "utf-8")
    print("\n" + "\n".join(L))
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
