#!/usr/bin/env python3
"""Do judges at the same court sentence political defendants differently?

    python judge_severity.py                     after sentences.py, 06_judges.py
    python judge_severity.py --perms 20000

Data: OVD-Info records linked to a first-instance registration with a card judge (judge_edges.csv), with the sentence
parsed by sentences.py. Two outcomes:
  term       log of the custodial term in months, custodial sentences only
  custody    1 if the sentence was custodial, 0 if suspended, fine, labour or restriction (acquittals and medical
             measures excluded)
Each outcome is adjusted for the most specific article, the decision year and the court (least squares with fixed
effects), so a judge is compared with colleagues at the same court, not with harsher or milder regions. The
unit of analysis is the registration: co-defendants share one judge and one hearing, so their adjusted values are
averaged first.

Judge effects
  Empirical Bayes (normal-normal, method of moments): a judge's mean residual is shrunk toward the court-wide zero in
  proportion to how few registrations it rests on. For the term outcome, exp(effect) is a multiplicative factor
  ("sentences about 1.3 times as long as the article and year predict").
Test
  Within each court, residuals are permuted across that court's judges (case counts kept), so the null is "at this court,
  which judge sat makes no difference". Statistic: between-judge sum of squares summed over courts. Courts need
  >= 2 judges with >= 2 registrations each.

Writes work/analysis/judge_severity_{term,custody}.csv and work/analysis/severity.md.
"""
from __future__ import annotations

import argparse
import re
import collections
import math
from pathlib import Path

import numpy as np

from courtlink import english as en
from courtlink.common import LOG, load_config, read_csv, setup_logging, work_path, write_csv
from courtlink.constants import PRIORITY

NONCUSTODIAL = {"suspended", "fine", "forced_labour", "correctional_labour", "restriction", "compulsory_works"}


def main_article(arts: str) -> str:
    a = [x for x in arts.replace(",", ";").split(";") if x]
    return next((p for p in PRIORITY if p in a), a[0] if a else "?")


def residualise(y: np.ndarray, groups: list[list[str]]) -> np.ndarray:
    """OLS residuals of y on one-hot fixed effects (one reference level per factor)."""
    cols = [np.ones(len(y))]
    for g in groups:
        levels = sorted(set(g))
        for lv in levels[1:]:
            cols.append(np.array([1.0 if v == lv else 0.0 for v in g]))
    X = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ beta


def eb_shrink(units: list[dict]) -> tuple[list[dict], float, float]:
    """units: one per registration with 'judge', 'r' (residual). Returns per-judge rows, tau^2, sigma^2."""
    by = collections.defaultdict(list)
    for u in units:
        by[u["judge"]].append(u["r"])
    js = [(j, np.array(v)) for j, v in by.items()]
    # residual variance within judges (pooled), so the judge differences being estimated do not inflate it
    ss = sum(float(((v - v.mean()) ** 2).sum()) for _, v in js)
    dfree = sum(len(v) for _, v in js) - len(js)
    sigma2 = ss / dfree if dfree > 0 else 1.0
    means = np.array([v.mean() for _, v in js]); ns = np.array([len(v) for _, v in js])
    # method of moments: var(judge means) = tau^2 + mean(sigma^2 / n_j)
    tau2 = max(float(np.var(means, ddof=1) - np.mean(sigma2 / ns)) if len(js) > 1 else 0.0, 0.0)
    out = []
    for (j, v), m, n in zip(js, means, ns):
        w = tau2 / (tau2 + sigma2 / n) if tau2 > 0 else 0.0
        post_mean = w * m
        sd = math.sqrt(1 / (1 / tau2 + n / sigma2)) if tau2 > 0 else 0.0
        out.append({"judge": j, "registrations": int(n), "raw_mean": float(m), "shrunk": float(post_mean),
                    "ci95_low": float(post_mean - 1.96 * sd), "ci95_high": float(post_mean + 1.96 * sd),
                    "flag": ("above" if post_mean - 1.96 * sd > 0 else "below" if post_mean + 1.96 * sd < 0 else "") if tau2 > 0 else ""})
    return out, tau2, sigma2


def within_court_test(units: list[dict], perms: int, seed: int = 5) -> tuple[float | None, int]:
    by_court = collections.defaultdict(lambda: collections.defaultdict(list))
    for u in units:
        by_court[u["court"]][u["judge"]].append(u["r"])
    courts = []
    for c, js in by_court.items():
        js = {j: v for j, v in js.items() if len(v) >= 2}
        if len(js) >= 2:
            labels = np.concatenate([[i] * len(v) for i, v in enumerate(js.values())])
            vals = np.concatenate([np.array(v) for v in js.values()])
            courts.append((labels, vals))
    if not courts:
        return None, 0
    rng = np.random.default_rng(seed)

    def stat(lv):
        s = 0.0
        for labels, vals in lv:
            mu = vals.mean()
            for k in np.unique(labels):
                x = vals[labels == k]
                s += len(x) * (x.mean() - mu) ** 2
        return s
    obs = stat(courts)
    ge = 0
    for _ in range(perms):
        if stat([(rng.permutation(labels), vals) for labels, vals in courts]) >= obs - 1e-12:
            ge += 1
    return (ge + 1) / (perms + 1), len(courts)


def reg_key(e: dict, rid: str):
    """Registration identity: UID, else court + docket, else the hearing (never merges empty dockets at one court)."""
    if e.get("uid"):
        return e["uid"]
    if e.get("docket"):
        return (e["court_id"], e["docket"])
    return e.get("hearing_id") or rid


def analyse(edges, sentences, judges_lbl, perms):
    S = {s["record_id"]: s for s in sentences}

    def ymd(d: str) -> str:
        d = d or ""
        return f"{d[6:10]}-{d[3:5]}-{d[:2]}" if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", d) else d[:10]

    # one row per record: a record can have several first-instance hearings (retrial, return to the prosecutor,
    # links at two courts); the sentence belongs to the latest decision
    best = {}
    for e in edges:
        if e.get("instance", "criminal_first") != "criminal_first" or e["record_id"] not in S or not e.get("judge_id"):
            continue
        d = ymd(e.get("decision_date", "")) or ymd(e.get("verdict_date", ""))
        if e["record_id"] not in best or d > best[e["record_id"]][0]:
            best[e["record_id"]] = (d, e)
    rows = []
    for rid, (d, e) in best.items():
        s = S[rid]
        if s.get("in_absentia") == "1":
            continue  # sentences passed in absentia are not comparable
        rows.append({"record": rid, "judge": e["judge_id"], "court": e["court_id"],
                     "reg": reg_key(e, rid),
                     "art": main_article(e.get("articles", "")), "year": d[:4] or "?",
                     "kind": s["first_kind"], "months": float(s["first_months"]) if s.get("first_months") else None})
    res = {}
    for outcome in ("term", "custody"):
        if outcome == "term":
            rs = [r for r in rows if r["kind"] == "custodial" and r["months"]]
            y = np.array([math.log(r["months"]) for r in rs])
        else:
            rs = [r for r in rows if r["kind"] == "custodial" or r["kind"] in NONCUSTODIAL]
            y = np.array([1.0 if r["kind"] == "custodial" else 0.0 for r in rs])
        if len(rs) < 10:
            res[outcome] = {"n_defendants": len(rs), "note": "fewer than 10 sentences"}
            continue
        # court fixed effects: judges are compared with colleagues at their own court, not with other regions
        resid = residualise(y, [[r["art"] for r in rs], [r["year"] for r in rs], [r["court"] for r in rs]])
        agg = collections.defaultdict(list)
        for r, e in zip(rs, resid):
            agg[(r["reg"], r["judge"], r["court"])].append(e)
        units = [{"judge": j, "court": c, "r": float(np.mean(v)), "n": len(v)} for (reg, j, c), v in agg.items()]
        judges, tau2, sigma2 = eb_shrink(units)
        p, n_courts = within_court_test(units, perms)
        court_of = {u["judge"]: u["court"] for u in units}
        for jr in judges:
            jr["court"] = court_of[jr["judge"]]
            jr["judgeEn"] = judges_lbl.get(jr["judge"], jr["judge"])
            if outcome == "term":
                jr["factor"] = round(math.exp(jr["shrunk"]), 3)          # conservative (shrunk)
                jr["raw_factor"] = round(math.exp(jr["raw_mean"]), 3)    # unshrunk, for comparison
        res[outcome] = {"n_defendants": len(rs), "n_registrations": len(units), "n_judges": len(judges),
                        "tau": math.sqrt(tau2), "sigma": math.sqrt(sigma2), "p_within_court": p,
                        "courts_tested": n_courts, "judges": sorted(judges, key=lambda x: -x["shrunk"])}
    return res


def fmt(j: dict, outcome: str) -> str:
    return (f"x{j['factor']} shrunk, x{j['raw_factor']} raw" if outcome == "term" else f"{j['shrunk']:+.2f} share")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config"); ap.add_argument("--perms", type=int, default=10000)
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    sp = work_path(cfg, "sentences.csv")
    if not sp.exists():
        raise SystemExit("run sentences.py first")
    jl = {}
    jp = work_path(cfg, "judges.csv")
    if jp.exists():
        for j in read_csv(jp):
            jl[j["judge_id"]] = f"{en.press(j.get('display', ''))}, {en.court(j.get('court_name', ''))}"
    R = analyse(read_csv(work_path(cfg, "judge_edges.csv")), read_csv(sp), jl, a.perms)
    out = Path(cfg["_work"]) / "analysis"; out.mkdir(parents=True, exist_ok=True)
    L = ["# Sentencing by judge, within courts", ""]
    for k, r in R.items():
        if "judges" not in r:
            L.append(f"- **{k}**: {r['note']} ({r['n_defendants']}).")
            continue
        write_csv(out / f"judge_severity_{k}.csv", r["judges"])
        what = "custodial term (log months)" if k == "term" else "custodial vs non-custodial (share)"
        p = f"{r['p_within_court']:.3f}" if r["p_within_court"] is not None else "n/a (no court with 2+ judges with 2+ registrations)"
        L.append(f"- **{what}**: {r['n_defendants']} defendants in {r['n_registrations']} registrations, {r['n_judges']} judges. "
                 f"Between-judge spread (tau) {r['tau']:.3f} against residual spread {r['sigma']:.3f}. Within-court permutation "
                 f"test over {r['courts_tested']} courts: p = {p}.")
        flagged = [j for j in r["judges"] if j["flag"]]
        if flagged:
            L.append("  Judges whose 95% interval excludes the article-and-year expectation: " + "; ".join(
                f"{j['judgeEn']} ({j['registrations']} reg., {fmt(j, k)})"
                for j in flagged[:12]) + ".")
    L += ["", "Judge effects are shrunk toward zero (empirical Bayes); a judge with two cases cannot be flagged on noise. "
          "Sentences come from OVD-Info's text as parsed by sentences.py: check its precision (sentences.py --sample) first."]
    (out / "severity.md").write_text("\n".join(L) + "\n", "utf-8")
    LOG.info("\n".join(L))


if __name__ == "__main__":
    main()
