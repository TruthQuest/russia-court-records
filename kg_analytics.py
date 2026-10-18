#!/usr/bin/env python3
"""Analytics over the CourtLink knowledge graph.

    python kg_analytics.py

Runs every query in kg/queries/*.rq against work/kg/*.ttl (rdflib, in memory; the same queries run unchanged
in Stardog or GraphDB), writes the results to work/kg/results/, then computes four analyses that need the court
census (census.py) as a denominator:

  1. OVD-Info blind spot   political-article cases on court sites with no OVD-Info record (closed world over
                           the census: 'not linked here', to be checked by OVD-Info, not 'unknown to OVD-Info').
  2. Assignment            Russian courts must distribute cases automatically. For each court, are political
                           cases spread across its criminal judges the way its other criminal cases are, year by year? Monte
                           Carlo test of the observed judge distribution against that court's own baseline,
                           Benjamini-Hochberg across courts.
  3. Judge outcomes        share of a judge's political registrations with a terminal result that did not end in a verdict, with
                           empirical-Bayes shrinkage (beta-binomial) so a judge with 3 cases is not ranked on noise.
  4. Speed                 median days from registration to decision, political vs other cases, per judge.

Writes work/kg/findings.json (used by export_html.py) and CSVs in work/kg/results/.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import statistics
from datetime import date
from pathlib import Path

import numpy as np
from rdflib import Graph, URIRef

CLNS = "https://traceoriginresearch.com/ontology/courtlink#"
from scipy import stats as st

from courtlink.common import LOG, load_config, setup_logging

POLITICAL = ["207.3", "280.3", "280.4", "284.1", "284.2", "330.1", "354.1", "280.1", "205.2", "280", "282",
             "282.1", "282.2", "282.3", "282.4", "275", "275.1", "276", "205.5", "205.1", "205.3", "205.4",
             "212.1", "148", "128.1", "329", "207.2", "278", "279"]
# 319 (insulting a public official) is left out: on court sites it is overwhelmingly ordinary insults to police,
# and counting it put St Petersburg district courts at the top of every "political" table.


def run(g: Graph, q: str) -> list[dict]:
    q = q.replace("POLITICAL", ", ".join(f'"{a}"' for a in POLITICAL))
    res = g.query(q)
    return [{str(v): (str(r[v]) if r[v] is not None else "") for v in res.vars} for r in res]


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        if not rows:
            f.write("")
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def bh(p: list[float]) -> list[float]:
    n = len(p)
    order = sorted(range(n), key=lambda i: p[i])
    q, prev = [0.0] * n, 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, p[i] * n / rank)
        q[i] = prev
    return q


def assignment_test(rows, min_political=8, min_baseline=20, sims=20000, seed=7):
    """rows: court, courtEn, reg, post, judgeEn, docket, political.

    Stratified by docket year, so a judge is only expected to receive cases in years in which the census shows them
    sitting at that court. Expected political cases per judge = sum over years of (political cases that year) x (judge's
    share of that year's non-political cases; uniform over active judges when the year's baseline is thin).
    The null distribution sums independent multinomial draws per year."""
    rng = np.random.default_rng(seed)
    by = collections.defaultdict(list)
    label = {}
    for r in rows:
        by[(r["court"], r["courtEn"])].append(r)
        label[r["post"]] = r.get("judgeEn", r["post"])
    year = lambda r: (r.get("docket", "").rsplit("/", 1)[-1] or "?")
    out = []
    for (court, name), rs in by.items():
        judges = sorted({r["post"] for r in rs})
        idx = {j: i for i, j in enumerate(judges)}
        pol = collections.Counter(r["post"] for r in rs if r["political"] == "1")
        n = sum(pol.values())
        if n < min_political or len(judges) < 2:
            continue
        strata, base_total, thin_years = [], 0, 0
        for y in sorted({year(r) for r in rs if r["political"] == "1"}):
            ry = [r for r in rs if year(r) == y]
            active = sorted({r["post"] for r in ry})
            base = collections.Counter(r["post"] for r in ry if r["political"] != "1")
            n_y = sum(1 for r in ry if r["political"] == "1")
            base_total += sum(base.values())
            thin = sum(base.values()) < 10
            thin_years += thin
            w = np.zeros(len(judges))
            for jdg in active:
                w[idx[jdg]] = 1.0 if thin else base[jdg] + 0.5
            strata.append((n_y, w / w.sum()))
        weak = base_total < min_baseline or thin_years * 2 > len(strata)
        exp = sum(n_y * p for n_y, p in strata)
        obs = np.array([pol[j] for j in judges], dtype=float)

        def g_of(x):
            m = (x > 0) & (exp > 0)
            return 2 * float(np.sum(x[m] * np.log(x[m] / exp[m])))
        g_obs = g_of(obs)
        draws = sum(rng.multinomial(n_y, p, size=sims).astype(float) for n_y, p in strata)
        with np.errstate(divide="ignore", invalid="ignore"):
            g_sim = 2 * np.nansum(np.where((draws > 0) & (exp > 0), draws * np.log(draws / exp), 0.0), axis=1)
        pval = (1 + int(np.sum(g_sim >= g_obs - 1e-9))) / (sims + 1)
        top = max(judges, key=lambda j: pol[j])
        out.append({"court": court, "courtEn": name, "political_cases": n, "baseline_cases": base_total,
                    "judges": len(judges), "years": len(strata),
                    "baseline": "thin baseline, indicative only" if weak else "court's other criminal cases, same docket years",
                    "weak": weak, "top_judge": label.get(top, top), "top_share": pol[top] / n,
                    "top_expected_share": float(exp[idx[top]] / n), "p_value": pval,
                    "dist": [{"judge": label.get(j, j), "political": pol[j], "expected": float(exp[i]),
                              "baseline": sum(1 for r in rs if r["post"] == j and r["political"] != "1")}
                             for i, j in enumerate(judges)]})
    q = bh([r["p_value"] for r in out])
    for r, qq in zip(out, q):
        r["q_value"] = qq
    return sorted(out, key=lambda r: r["p_value"])


def judge_outcomes(load_rows, min_decided=5):
    """Empirical-Bayes non-verdict rate per judicial post over TERMINAL results of political registrations
    (verdict, dismissal, court fine, compulsory medical measures). Non-terminal steps are excluded."""
    js = []
    for r in load_rows:
        decided = int(float(r["terminal"]))
        nonv = decided - int(float(r["verdicts"]))
        if decided > 0:
            js.append((r, decided, nonv))
    if len(js) < 5:
        return {"prior": None, "judges": []}
    rates = np.array([k / n for _, n, k in js]); ns = np.array([n for _, n, _ in js])
    m = float(np.sum(rates * ns) / np.sum(ns))
    v = float(np.average((rates - m) ** 2, weights=ns))
    nbar = float(np.mean(ns))
    s2 = max(v - m * (1 - m) / nbar, 1e-4)  # between-judge variance (method of moments)
    kappa = max(m * (1 - m) / s2 - 1, 2.0)
    a0, b0 = max(m * kappa, 0.5), max((1 - m) * kappa, 0.5)
    out = []
    for r, n, k in js:
        if n < min_decided:
            continue
        a, b = a0 + k, b0 + n - k
        lo, hi = st.beta.ppf([0.05, 0.95], a, b)
        out.append({"judge": r["post"], "judgeEn": r["judgeEn"], "courtEn": r["courtEn"], "decided": n, "non_verdict": k,
                    "raw_rate": k / n, "shrunk_rate": a / (a + b), "ci90_low": float(lo), "ci90_high": float(hi),
                    "flag": "below pool" if hi < m else ("above pool" if lo > m else "")})
    return {"prior": {"pooled_rate": m, "a": a0, "b": b0}, "judges": sorted(out, key=lambda x: x["shrunk_rate"])}


def speed(rows):
    by = collections.defaultdict(lambda: {"pol": [], "oth": [], "name": "", "court": ""})
    for r in rows:
        try:
            d = (date.fromisoformat(r["decided"][:10]) - date.fromisoformat(r["registered"][:10])).days
        except ValueError:
            continue
        if d < 0 or d > 2000:
            continue
        x = by[r["post"]]
        x["name"], x["court"] = r["judgeEn"], r["court"]
        (x["pol"] if r["political"] == "1" else x["oth"]).append(d)
    out = []
    for j, x in by.items():
        if len(x["pol"]) >= 3:
            out.append({"judge": j, "judgeEn": x["name"], "court": x["court"], "n_political": len(x["pol"]),
                        "median_days_political": statistics.median(x["pol"]),
                        "n_other": len(x["oth"]),
                        "median_days_other": statistics.median(x["oth"]) if len(x["oth"]) >= 3 else None})
    return sorted(out, key=lambda r: r["median_days_political"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--sims", type=int, default=20000)
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    kg = Path(cfg["_work"]) / "kg"
    g = Graph()
    for f in ("courtlink.ttl", "courtlink-data.ttl"):
        g.parse(kg / f)
    LOG.info("graph loaded: %d triples", len(g))
    qdir = Path(__file__).parent / "kg" / "queries"
    res = {}
    for q in sorted(qdir.glob("*.rq")):
        res[q.stem] = run(g, q.read_text("utf-8"))
        write(kg / "results" / f"{q.stem}.csv", res[q.stem])
        LOG.info("%-24s %6d rows", q.stem, len(res[q.stem]))

    # the census is what supplies registration dates and unlinked cases; linked-only graphs have neither
    has_census = bool(next(g.triples((None, URIRef(CLNS + "registeredOn"), None)), None))
    gap = {"courts": len({r["court"] for r in res["ovd_gap"]}),
           "political_cases": sum(int(float(r["cases"])) for r in res["ovd_gap"]),
           "linked": sum(int(float(r["linkedCases"])) for r in res["ovd_gap"]),
           "unlinked_cases": len(res["ovd_gap_cases"]),
           "unlinked_defendants": sum(int(float(r["nd"] or 1)) for r in res["ovd_gap_cases"]),
           "by_article": [], "by_court": []}
    art = collections.defaultdict(lambda: [0, 0, ""])
    crt = collections.defaultdict(lambda: [0, 0])
    for r in res["ovd_gap"]:
        art[r["art"]][0] += int(float(r["cases"])); art[r["art"]][1] += int(float(r["linkedCases"])); art[r["art"]][2] = r["artEn"]
        crt[r["courtEn"]][0] += int(float(r["cases"])); crt[r["courtEn"]][1] += int(float(r["linkedCases"]))
    gap["by_article"] = [{"art": k, "artEn": v[2], "cases": v[0], "linked": v[1]} for k, v in sorted(art.items(), key=lambda x: -x[1][0])]
    gap["by_court"] = [{"court": k, "cases": v[0], "linked": v[1]} for k, v in sorted(crt.items(), key=lambda x: -x[1][0])][:25]

    assign = assignment_test(res["assignment"], sims=a.sims) if has_census else []
    outcomes = judge_outcomes(res["outcome_political"])
    sp = speed(res["durations"])
    classes = {r["k"]: int(r["n"]) for r in run(g, """PREFIX cl: <https://traceoriginresearch.com/ontology/courtlink#>
        SELECT ?k (COUNT(DISTINCT ?x) AS ?n) WHERE { ?x a ?c . FILTER(STRSTARTS(STR(?c), STR(cl:)))
        BIND(STRAFTER(STR(?c), "#") AS ?k) } GROUP BY ?k""")}
    held = set(g.objects(None, URIRef(CLNS + "heldAt")))
    first = set(g.objects(None, URIRef(CLNS + "firstRegisteredAt")))
    classes["CourtHolding"] = len(held)
    classes["CourtOriginOnly"] = len(first - held)
    classes["Person"] = len(set(g.subjects(URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"), URIRef("http://xmlns.com/foaf/0.1/Person"))))
    findings = {"has_census": has_census, "triples": len(g), "classes": classes, "political_articles": POLITICAL,
                "ovd_gap": gap, "assignment": assign, "judge_outcomes": outcomes, "speed": sp,
                "split": res["clusters"], "same_judge": res["same_person"],
                "reregistered": res["proceedings_reregistered"]}
    (kg / "findings.json").write_text(json.dumps(findings, ensure_ascii=False, indent=1), "utf-8")
    write(kg / "results" / "assignment_test.csv", [{k: v for k, v in r.items() if k != "dist"} for r in assign])
    write(kg / "results" / "judge_outcomes_shrunk.csv", outcomes["judges"])
    write(kg / "results" / "judge_speed.csv", sp)
    sig = [r for r in assign if r["q_value"] < 0.05]
    LOG.info("census present: %s | political cases on court sites: %d, not linked to OVD-Info: %d (%d defendants) | "
             "courts tested for assignment: %d, concentrated (q<0.05): %d | judges with outcome estimate: %d",
             has_census, gap["political_cases"], gap["unlinked_cases"], gap["unlinked_defendants"], len(assign), len(sig),
             len(outcomes["judges"]))
    if not has_census:
        LOG.info("no census in the graph: run `python census.py` then `python kg_build.py` for the blind-spot, "
                 "assignment and speed analyses")


if __name__ == "__main__":
    main()
