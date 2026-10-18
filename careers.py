#!/usr/bin/env python3
"""Are judges who try political cases promoted faster?

    python careers.py                    after census.py (political + baseline sweeps) and appointments.py
    python careers.py --moves leadership elevation --boot 2000

Population: every judge the census shows sitting at a court (political and baseline searches), one row per judge per
year from the first to the last year they are observed, stopping at the first promotion. Promotion = a decree
appointing them chair or deputy chair (leadership) or judge of a higher-level court (elevation), linked to the judge
by the previous post's court, surname (decree accusative -> nominative) and initials. Ambiguous links are dropped and
counted.

Exposure in year t uses cases up to the end of year t-1 only (a decree cannot reward cases not yet heard):
  exposed        at least one registration under a political article
  log_caseload   log(1 + all criminal registrations so far), so busy judges are not mistaken for political ones
Tests
  1. Promotion rate per 100 judge-years, exposed vs not: rate ratio with an exact conditional (binomial) test.
  2. Discrete-time logistic hazard: promotion ~ exposed + log_caseload + regional_court + linear year trend, with a
     court-clustered bootstrap interval for the exposure odds ratio.
Limits: judges appear only from the census start; earlier careers are unseen (left truncation). Promotion is a
decree, not a reward: the test shows association with exposure, not motive.

Writes work/analysis/careers_panel.csv, careers_events.csv and careers.md.
"""
from __future__ import annotations

import argparse
import collections
import math
from pathlib import Path

import numpy as np
from scipy import stats as st

from courtlink.common import LOG, load_config, read_csv, setup_logging, work_path, write_csv
from courtlink.decrees import name_key
from courtlink.judges import judge_key, parse_judge
from courtlink.translit import skeleton
from kg_analytics import POLITICAL


def reg_year(r):
    y = r.get("docket_key", "").rsplit("/", 1)[-1]
    return int(y) if y.isdigit() else None


def build(census, courts, appts, moves, end_year, only_courts=None):
    level = {c["court_id"]: c["court_type"] for c in courts}
    J = collections.defaultdict(lambda: {"court": "", "years": collections.Counter(), "pol": collections.Counter(), "p": None})
    for r in census:
        j = parse_judge(r.get("judge", ""))
        y = reg_year(r)
        if not j or y is None or (only_courts is not None and r["court_id"] not in only_courts):
            continue
        k = judge_key(r["court_id"], j)
        x = J[k]
        x["court"], x["p"] = r["court_id"], j
        x["years"][y] += 1
        arts = set(filter(None, (r.get("articles", "") + ";" + r.get("article_queried", "")).split(";")))
        if arts & set(POLITICAL):
            x["pol"][y] += 1
    # index judges by (court, surname skeleton, i1, i2)
    idx = collections.defaultdict(list)
    for k, x in J.items():
        p = x["p"]
        idx[(x["court"], skeleton(p["surname"]), skeleton(p["i1"])[:1], skeleton(p["i2"])[:1])].append(k)
    events, stats = {}, collections.Counter()
    ev_rows = []
    for a in appts:
        if a["move"] not in moves or not a.get("prev_court_id") or not a.get("decree_date"):
            continue
        if a.get("prev_role") == a.get("position") and a.get("prev_court_id") == a.get("court_id"):
            stats["reappointment_same_post"] += 1  # a chair reappointed chair of the same court is not a promotion
            continue
        cands = set()
        for nom in a["surname_nom"].split(";"):
            s, i1, i2 = name_key(nom, a["first"], a["patronymic"])
            cands |= set(idx.get((a["prev_court_id"], s, i1, i2), []))
        if not cands:
            stats["appointment_not_in_census"] += 1
            continue
        if len(cands) > 1:
            stats["ambiguous"] += 1
            continue
        k = cands.pop()
        y = int(a["decree_date"][:4])
        if k not in events or y < events[k][0]:
            events[k] = (y, a["move"])
        stats["linked"] += 1
        ev_rows.append({"judge": k, "year": y, "move": a["move"], "decree_no": a["decree_no"], "new_court": a["court_text"]})
    panel = []
    for k, x in J.items():
        ys = sorted(x["years"])
        if not ys:
            continue
        first, last = ys[0], min(max(ys), end_year)
        ev = events.get(k)
        if ev and ev[0] < first:
            stats["promoted_before_first_observed"] += 1
            ev = None
        if ev and ev[0] <= last + 1:
            stop = ev[0]  # the promotion year often has no cases left at the old court
        else:
            if ev:
                stats["promoted_after_observation_gap"] += 1
            ev, stop = None, last
        cum_pol = cum_all = 0
        for t in range(first, stop + 1):
            panel.append({"judge": k, "court": x["court"], "year": t, "exposed": int(cum_pol > 0), "cum_political": cum_pol,
                          "log_caseload": round(math.log1p(cum_all), 4),
                          "regional": int(level.get(x["court"], "") in ("regional", "military_district")),
                          "event": int(bool(ev) and t == ev[0])})
            cum_pol += x["pol"].get(t, 0); cum_all += x["years"].get(t, 0)
    return panel, ev_rows, stats


def logit(X, y, iters=50, ridge=1e-6):
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, X.T @ (y - p) - ridge * b)
        b += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b


def design(panel):
    yrs = np.array([r["year"] for r in panel], dtype=float)
    X = np.column_stack([np.ones(len(panel)), [r["exposed"] for r in panel], [r["log_caseload"] for r in panel],
                         [r["regional"] for r in panel], yrs - yrs.mean() if len(yrs) else yrs])
    return X, np.array([r["event"] for r in panel], dtype=float)


def analyse(panel, boot=1000, seed=9):
    ex = [r for r in panel if r["exposed"]]; un = [r for r in panel if not r["exposed"]]
    e1, e0 = sum(r["event"] for r in ex), sum(r["event"] for r in un)
    t1, t0 = len(ex), len(un)
    out = {"judges": len({r["judge"] for r in panel}), "judge_years": len(panel), "events": e1 + e0,
           "exposed": {"judge_years": t1, "events": e1, "per100": 100 * e1 / t1 if t1 else None},
           "unexposed": {"judge_years": t0, "events": e0, "per100": 100 * e0 / t0 if t0 else None}}
    if t1 and t0 and (e1 + e0):
        out["rate_ratio"] = (e1 / t1) / (e0 / t0) if e0 else math.inf
        out["rate_ratio_p"] = st.binomtest(e1, e1 + e0, t1 / (t1 + t0)).pvalue
    if out["events"] >= 10 and t1 and t0:
        X, y = design(panel)
        b = logit(X, y)
        out["or_exposed"] = math.exp(b[1])
        rng = np.random.default_rng(seed)
        by = collections.defaultdict(list)
        for i, r in enumerate(panel):
            by[r["court"]].append(i)
        courts = list(by)
        bs = []
        for _ in range(boot):
            ids = np.concatenate([by[c] for c in rng.choice(courts, size=len(courts), replace=True)])
            Xb, yb = X[ids], y[ids]
            if yb.sum() == 0 or Xb[:, 1].min() == Xb[:, 1].max():
                continue
            bs.append(logit(Xb, yb)[1])
        if len(bs) > boot * 0.5:
            lo, hi = np.percentile(bs, [2.5, 97.5])
            out["or_ci95"] = [math.exp(lo), math.exp(hi)]
            out["boot_draws"] = len(bs)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--moves", nargs="*", default=["leadership", "elevation"])
    ap.add_argument("--end-year", type=int, default=2026)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--all-courts", action="store_true",
                    help="include courts without a baseline sweep (their caseload term counts political cases only)")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    ap_p = work_path(cfg, "appointments.csv")
    if not ap_p.exists():
        raise SystemExit("run appointments.py first")
    only = None
    lp = work_path(cfg, "census_log.csv")
    if not a.all_courts:
        only = {r["court_id"] for r in (read_csv(lp) if lp.exists() else []) if r["mode"] == "baseline" and r["state"] in ("results", "empty")}
        if not only:
            raise SystemExit("no baseline sweep found: run `census_sweep.py baseline` first, or pass --all-courts "
                             "(then judges are compared only by political caseload, and the caseload control is weak)")
    panel, ev, stats = build(read_csv(work_path(cfg, "census.csv")), read_csv(work_path(cfg, "courts.csv")),
                             read_csv(ap_p), set(a.moves), a.end_year, only)
    R = analyse(panel, a.boot)
    out = Path(cfg["_work"]) / "analysis"; out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "careers_panel.csv", panel)
    write_csv(out / "careers_events.csv", ev)
    L = ["# Political cases and promotion", "",
         f"- Judges: {R['judges']} ({R['judge_years']} judge-years); promotions linked: {R['events']} "
         f"({dict(stats)}).",
         f"- Exposed (a political case before the year): {R['exposed']['events']} promotions in {R['exposed']['judge_years']} "
         f"judge-years; not exposed: {R['unexposed']['events']} in {R['unexposed']['judge_years']}."]
    if "rate_ratio" in R:
        L.append(f"- Rate ratio {R['rate_ratio']:.2f}, exact conditional test p = {R['rate_ratio_p']:.3f}.")
    if "or_exposed" in R:
        ci = f" (court-clustered bootstrap 95% CI {R['or_ci95'][0]:.2f} to {R['or_ci95'][1]:.2f})" if "or_ci95" in R else ""
        L.append(f"- Discrete-time hazard, adjusted for caseload, court level and year: odds ratio for exposure "
                 f"{R['or_exposed']:.2f}{ci}.")
    else:
        L.append("- Fewer than 10 linked promotions, or no unexposed judges: the hazard model is not fitted. The baseline "
                 "sweep (census_sweep.py baseline) supplies judges without political cases.")
    L += ["", "Association, not motive: chairs are appointed from experienced judges, and experience correlates with "
          "being assigned sensitive cases. The caseload term absorbs part of this; seniority before the census start "
          "is not observed."]
    (out / "careers.md").write_text("\n".join(L) + "\n", "utf-8")
    LOG.info("\n".join(L))


if __name__ == "__main__":
    main()
