#!/usr/bin/env python3
"""Graph analyses that need the connections between cases, not counts per judge.

    python card_details.py          (re-run once: card_summary.csv now carries the judge and the articles)
    python graph_analytics.py       all four analyses
    python graph_analytics.py --only batches,pairs

1. Hidden batches. Every court numbers the first material of every case in one sequence per year: the case identifier
   (УИД) 66RS0001-01-2024-001234-56 is item 1234 of 2024 at court 66RS0001, and keeps that number when the case moves to
   another court. Cases under the same article whose identifiers fall close together AND which reached trial close
   together in time are a probable coordinated operation, or one case split into several (CPC art. 154). Batches are
   bounded windows, not chains: a batch never spans more than --window identifier numbers, so it cannot absorb a court's
   whole series. Each batch gets an approximate scan-statistic p-value against tracked cases falling at random in that
   court's sequence. Members with no OVD-Info record, and numbers inside a batch that we never saw, are leads.

2. Prosecutor-judge pairings. For every judge and prosecutor who meet in court, the number of cases they shared is
   compared with what each one's caseload predicts if prosecutors and judges met at random, within the same court,
   the same group of articles and the same year (sum of independent hypergeometric variables; exact). P-values are
   corrected for the number of pairs tested (Benjamini-Hochberg). A significant pair met more often than the
   caseloads explain; it does not show why (specialised divisions, rotas or steering).

3. Procedural signatures. Each case page's events become a short sequence (R registered, J to judge, D decision on
   the case, P preliminary hearing, H hearing, h hearing postponed, E custody extended, S sentence). For each judge
   with --min-cases cases in one group of articles, the share of cases following that judge's most common sequence is compared with judges
   at the same court on the same group of articles (permutation test). This controls for how a court's clerks log
   events. A significant judge runs cases on a template more uniform than colleagues at the same court.

   NOT RUN BY DEFAULT: in the October 2026 census data only about 5% of case pages name a prosecutor (the rest show
   'Информация скрыта' or the office), too few for the test. Run with --only pairs when better data exist.

4. Proximity to listed judges (internal only; NOT RUN BY DEFAULT, it depends on the prosecutor network in 2). Personalised PageRank from the judges whose name matches a sanctions
   listing, over the judge-prosecutor network weighted by shared cases. It ranks other judges by how close they sit
   to listed judges in that network: a documentation priority list, not an accusation. Never publish it.

Reads   work/cards/card_summary.csv, card_events.csv, card_parties.csv; work/courts.csv; work/matches.csv;
        work/analysis/not_in_ovd.csv and judge_dossier.csv when present.
Writes  work/analysis/graph/: batches.csv, batch_members.csv, batch_gaps.csv, pairings.csv, signatures_judges.csv,
        signatures_top.csv, proximity_INTERNAL.csv, graph_findings.md. All under work/: never commit or publish.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import math
import random
import re
from pathlib import Path

from courtlink.common import LOG, load_config, read_csv, setup_logging, write_csv
from courtlink.judges import judge_key, parse_judge

POLITICAL = {"207.3", "280.3", "280.4", "284.1", "284.2", "330.1", "354.1", "280.1", "205.2", "280", "282", "282.1",
             "282.2", "282.3", "282.4", "275", "275.1", "276", "205.5", "205.1", "205.3", "205.4", "212.1", "148",
             "128.1", "329", "207.2", "278", "279", "205"}
SPEECH = {"207.3", "280.3", "280.4", "284.1", "284.2", "330.1", "354.1", "280.1", "207.2", "148", "128.1", "329",
          "212.1", "280", "282"}
ORGANISATION = {"282.1", "282.2", "282.3", "282.4"}
UID_RE = re.compile(r"^(\d{2}[A-ZА-Я]{2}\d{4})-(\d{2})-(\d{4})-(\d{6})-(\d{2})$")
LOOKALIKE = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")
DOCKET_RE = re.compile(r"^(\d+(?:-\d+)?)-(\d+)/(\d{4})$")


# ---------------------------------------------------------------- shared
def base_articles(s: str) -> set[str]:
    return {a.split("(")[0] for a in (s or "").split(";") if a}


def group_of(arts: set[str]) -> str:
    """The most serious group present: security > terror speech (205.2) > organisation > speech."""
    if arts & (POLITICAL - SPEECH - ORGANISATION - {"205.2"}):
        return "security"
    if "205.2" in arts:
        return "terror_speech"
    if arts & ORGANISATION:
        return "organisation"
    return "speech" if arts & SPEECH else ""


def parse_uid(uid: str):
    m = UID_RE.match((uid or "").strip().upper().translate(LOOKALIKE))
    return (m.group(1), m.group(2), m.group(3), int(m.group(4))) if m else None


def day(s: str):
    try:
        return dt.date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def bh(ps: list[float], m_tests: int | None = None) -> list[float]:
    """Benjamini-Hochberg q-values. m_tests may exceed len(ps) when untested pairs have p = 1."""
    m = m_tests or len(ps)
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    q, prev = [1.0] * len(ps), 1.0
    for rank in range(len(ps), 0, -1):
        i = order[rank - 1]
        prev = min(prev, ps[i] * m / rank)
        q[i] = min(1.0, prev)
    return q


def load(W: Path) -> dict:
    """Cases keyed by (court_id, docket_key), political articles only, plus events, prosecutors and OVD-Info status."""
    cards = W / "cards"
    summ = read_csv(cards / "card_summary.csv")
    if summ and "judge" not in summ[0]:
        raise SystemExit("card_summary.csv has no judge column: re-run `python card_details.py` (offline, a few minutes)")
    courts = {r["court_id"]: r for r in read_csv(W / "courts.csv")} if (W / "courts.csv").exists() else {}
    in_ovd = set()
    if (W / "matches.csv").exists():
        in_ovd = {(r["court_id"], r["docket_key"]) for r in read_csv(W / "matches.csv") if r.get("docket_key")}
    not_ovd = set()
    p = W / "analysis" / "not_in_ovd.csv"
    if p.exists():
        from courtlink.dockets import docket_key
        not_ovd = {(r["court_id"], docket_key(r["docket"])) for r in read_csv(p)}
    cases = {}
    for r in summ:
        arts = base_articles(r.get("articles", ""))
        if not arts & POLITICAL:
            continue
        k = (r["court_id"], r["docket_key"])
        j = parse_judge(r.get("judge", ""))
        c = courts.get(r["court_id"], {})
        cases[k] = {**r, "arts": arts, "group": group_of(arts), "jkey": judge_key(r["court_id"], j) if j else "",
                    "court_name": c.get("name", r["court_id"]), "region": c.get("iso", ""),
                    "ovd": "in OVD-Info" if k in in_ovd else "not in OVD-Info (census)" if k in not_ovd else "not matched"}
    events = collections.defaultdict(list)
    for e in read_csv(cards / "card_events.csv"):
        k = (e["court_id"], e["docket_key"])
        if k in cases:
            events[k].append(e)
    for v in events.values():
        v.sort(key=lambda e: int(e.get("n") or 0))
    prosecutors = collections.defaultdict(set)
    names = {}
    for p_ in read_csv(cards / "card_parties.csv"):
        k = (p_["court_id"], p_["docket_key"])
        if k in cases and p_.get("role_class") == "prosecutor" and p_.get("name"):
            for nm in re.split(r"[,;]", p_["name"]):
                pk, disp = prosecutor_key(nm, cases[k]["region"])
                if pk:
                    prosecutors[k].add(pk)
                    names.setdefault(pk, disp)
    all_uids = {parse_uid(r.get("uid", "")) for r in summ} - {None}
    return {"cases": cases, "events": events, "prosecutors": prosecutors, "pnames": names, "all_uids": all_uids}


PROS_FULL = re.compile(r"([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+(?:вич|вна|ич|кызы|оглы))\b")
PROS_INIT = re.compile(r"([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ])\.\s*([А-ЯЁ])\.?")


def prosecutor_key(raw: str, region: str) -> tuple[str, str]:
    """'помощник прокурора Иванова И.И.' -> ('RU-XX:иванова_ии', 'Иванова И.И.'). Offices without a name -> ('', '')."""
    s = re.sub(r"\s+", " ", raw or "").strip()
    m = PROS_FULL.search(s) or PROS_INIT.search(s)
    if not m:
        return "", ""
    sur, a, b = m.group(1), m.group(2)[0], m.group(3)[0]
    return f"{region}:{sur.lower()}_{a.lower()}{b.lower()}", f"{sur} {a}.{b}."


# ---------------------------------------------------------------- 1. hidden batches
def scan_p(k: int, m: int, w: int, N: int) -> float:
    """Approximate P(some window of w consecutive numbers out of N holds >= k of m random tracked cases)."""
    if m < k or N <= 0:
        return 1.0
    q = min(1.0, w / N)
    tail = sum(math.comb(m, i) * q ** i * (1 - q) ** (m - i) for i in range(k, m + 1))
    return min(1.0, tail * max(1.0, N / w))


def find_batches(cases: dict, all_uids: set, window: int = 20, days: int = 45, min_size: int = 2) -> tuple[list, list, list]:
    by_uid = {}
    for k, c in cases.items():
        u = parse_uid(c.get("uid", ""))
        if not u:
            continue
        cur = by_uid.get(u)
        if cur is None or (c.get("received") or "") > (cur[1].get("received") or ""):
            by_uid[u] = (k, c)  # a refiled or transferred case: keep the latest registration
    seqs = collections.defaultdict(list)
    for u, (k, c) in by_uid.items():
        seqs[u[:3]].append((u[3], k, c))
    span_of = collections.defaultdict(int)
    for u in all_uids:
        span_of[u[:3]] = max(span_of[u[:3]], u[3])
    batches, members, gaps = [], [], []
    for (owner, typ, year), items in seqs.items():
        items.sort(key=lambda x: x[0])
        N, m = span_of[(owner, typ, year)], len(items)
        used = set()
        for i in range(len(items)):
            if i in used:
                continue
            b, bi = [items[i]], [i]
            j = i + 1
            while j < len(items) and items[j][0] - b[0][0] <= window:
                cand = items[j]
                if j in used:
                    j += 1
                    continue
                rec = [day(x[2].get("received")) for x in b if day(x[2].get("received"))]
                rc = day(cand[2].get("received"))
                close = not rec or not rc or min(abs((rc - r).days) for r in rec) <= days
                if close and any(cand[2]["arts"] & x[2]["arts"] for x in b):
                    b.append(cand); bi.append(j)
                j += 1
            if len(b) >= min_size:
                used.update(bi)
                bid = f"{owner}-{typ}-{year}-{b[0][0]:06d}..{b[-1][0]:06d}"
                w = b[-1][0] - b[0][0] + 1
                shared = set.intersection(*[x[2]["arts"] for x in b])
                recd = sorted(d for d in (day(x[2].get("received")) for x in b) if d)
                order = same_order(b)
                seen = {x[0] for x in b}
                missing = [n for n in range(b[0][0], b[-1][0] + 1) if n not in seen
                           and (owner, typ, year, n) not in all_uids]
                batches.append({"batch": bid, "court_code": owner, "year": year, "cases": len(b), "span": w,
                                "tracked_cases_that_year": m, "highest_number_seen": N,
                                "p_approx": round(scan_p(len(b), m, w, N), 6),
                                "shared_articles": ";".join(sorted(shared)) or "(overlapping)",
                                "courts": len({x[1][0] for x in b}), "judges": len({x[2]["jkey"] for x in b if x[2]["jkey"]}),
                                "trial_received_from": recd[0].isoformat() if recd else "",
                                "trial_received_to": recd[-1].isoformat() if recd else "",
                                "dockets_in_same_order": order,
                                "in_ovd": sum(x[2]["ovd"] == "in OVD-Info" for x in b),
                                "not_in_ovd": sum(x[2]["ovd"] != "in OVD-Info" for x in b),
                                "numbers_never_seen": len(missing)})
                for n_, k, c in b:
                    members.append({"batch": bid, "uid": c.get("uid", ""), "number": n_, "court_id": k[0],
                                    "court": c["court_name"], "docket_key": k[1], "received": c.get("received", ""),
                                    "articles": c.get("articles", ""), "judge": c.get("judge", ""), "ovd": c["ovd"],
                                    "card_url": c.get("card_url", "")})
                for n_ in missing:
                    gaps.append({"batch": bid, "uid_prefix": f"{owner}-{typ}-{year}-{n_:06d}", "court_code": owner,
                                 "note": "number inside the batch with no tracked case seen: look it up"})
    q = bh([b_["p_approx"] for b_ in batches])
    for b_, qq in zip(batches, q):
        b_["q"] = round(qq, 6)
    qb = {b_["batch"]: b_["q"] for b_ in batches}
    for r in members + gaps:  # filter on batch_q < 0.05 for leads
        r["batch_q"] = qb[r["batch"]]
    batches.sort(key=lambda b_: (b_["q"], -b_["cases"]))
    return batches, members, gaps


def same_order(b: list) -> str:
    """'yes' if trial dockets at each court follow the identifier order, 'no' if not, '' if it cannot be told."""
    by_court = collections.defaultdict(list)
    for n_, k, _c in b:
        m = DOCKET_RE.match(k[1] or "")
        if m:
            by_court[(k[0], m.group(1), m.group(3))].append((n_, int(m.group(2))))
    pairs = [v for v in by_court.values() if len(v) >= 2]
    if not pairs:
        return ""
    for v in pairs:
        v.sort()
        if any(v[i][1] > v[i + 1][1] for i in range(len(v) - 1)):
            return "no"
    return "yes"


# ---------------------------------------------------------------- 2. prosecutor-judge pairings
def hyper_pmf(N: int, K: int, n: int) -> list[float]:
    """pmf of X ~ Hypergeometric(population N, successes K, draws n) on 0..min(K, n)."""
    tot = math.comb(N, n)
    return [math.comb(K, x) * math.comb(N - K, n - x) / tot for x in range(min(K, n) + 1)]


def conv_tail(pmfs: list[list[float]], o: int) -> float:
    dist = [1.0]
    for p in pmfs:
        nd = [0.0] * (len(dist) + len(p) - 1)
        for i, a in enumerate(dist):
            if a:
                for j, b in enumerate(p):
                    nd[i + j] += a * b
        dist = nd
    return max(0.0, min(1.0, sum(dist[o:])))


def pairings(cases: dict, prosecutors: dict, pnames: dict, min_obs: int = 3) -> list[dict]:
    strata = collections.defaultdict(list)
    for k, c in cases.items():
        if c["jkey"] and prosecutors.get(k) and c["group"]:
            strata[(k[0], c["group"], (c.get("received") or "")[:4])].append(k)
    obs = collections.Counter()
    pmfs = collections.defaultdict(list)
    exp = collections.Counter()
    where = collections.defaultdict(set)
    for s, ks in strata.items():
        N = len(ks)
        nj = collections.Counter(cases[k]["jkey"] for k in ks)
        mi = collections.Counter(p for k in ks for p in prosecutors[k])
        for k in ks:
            for p in prosecutors[k]:
                obs[(cases[k]["jkey"], p)] += 1
        for j, n in nj.items():
            for p, m in mi.items():
                pmfs[(j, p)].append(hyper_pmf(N, m, n))
                exp[(j, p)] += m * n / N
                where[(j, p)].add(s[0])
    n_tests = len(exp)
    jname = {c["jkey"]: (c.get("judge", ""), c["court_name"]) for c in cases.values() if c["jkey"]}
    rows = []
    for jp, e in exp.items():
        o = obs[jp]
        p = conv_tail(pmfs[jp], o) if o >= min_obs else 1.0
        rows.append({"judge_key": jp[0], "judge": jname[jp[0]][0], "court": jname[jp[0]][1], "prosecutor_key": jp[1],
                     "prosecutor": pnames.get(jp[1], ""), "shared_cases": o, "expected": round(e, 2),
                     "ratio": round(o / e, 2) if e else "", "p": p})
    q = bh([r["p"] for r in rows], n_tests)
    for r, qq in zip(rows, q):
        r["q"] = round(qq, 6)
        r["p"] = round(r["p"], 8)
        r["significant"] = int(r["q"] < 0.05 and r["shared_cases"] >= min_obs)
    rows.sort(key=lambda r: (r["q"], -r["shared_cases"]))
    return rows


# ---------------------------------------------------------------- 3. procedural signatures
def token(e: dict) -> str:
    cls = e.get("event_class", "")
    if e.get("sentence") == "1":
        return "S"
    if e.get("custody_extended") == "1":
        return "E"
    if cls == "hearing":
        return "h" if e.get("postponed") == "1" else "H"
    if cls == "preliminary":
        return "p" if e.get("postponed") == "1" else "P"
    return {"registered": "R", "to_judge": "J", "decision_on_case": "D", "sentence_read": "S"}.get(cls, "")


def signature(evs: list[dict]) -> str:
    """Events up to the first sentence, as tokens; runs of the same token collapse to token + count (3 means 3 or more)."""
    toks = []
    for e in evs:
        t = token(e)
        if t:
            toks.append(t)
            if t == "S":
                break
    out = []
    for t in toks:
        if out and out[-1][0] == t:
            out[-1][1] += 1
        else:
            out.append([t, 1])
    return " ".join(t if n == 1 else f"{t}{min(n, 3)}" for t, n in out)


def modal_share(sigs: list[str]) -> tuple[str, float]:
    c = collections.Counter(sigs).most_common(1)[0]
    return c[0], c[1] / len(sigs)


def judge_to_sentence_days(evs: list[dict]):
    """Days from the case reaching the judge to the sentence, from the logged event dates; None if either is missing."""
    j = next((day(e.get("date")) for e in evs if e.get("event_class") == "to_judge" and day(e.get("date"))), None)
    s = next((day(e.get("date")) for e in evs if (e.get("sentence") == "1" or e.get("event_class") == "sentence_read")
              and day(e.get("date"))), None)
    return (s - j).days if j and s and s >= j else None


def duration_cols(ks: list, events: dict, prefix: str = "") -> dict:
    """Median days judge->sentence, and the share over 90 days: a trial longer than 90 days with a defendant in custody
    needs a custody extension (CPC art. 255), so long cases with no logged hearing or extension point to gaps in logging."""
    d = sorted(x for x in (judge_to_sentence_days(events.get(k, [])) for k in ks) if x is not None)
    if not d:
        return {f"{prefix}median_days_to_sentence": "", f"{prefix}share_over_90_days": ""}
    return {f"{prefix}median_days_to_sentence": d[len(d) // 2], f"{prefix}share_over_90_days": round(sum(x > 90 for x in d) / len(d), 3)}


def signatures(cases: dict, events: dict, min_cases: int = 10, perms: int = 1000, seed: int = 7) -> tuple[list, list]:
    sig = {k: signature(events.get(k, [])) for k in cases}
    sig = {k: s for k, s in sig.items() if s and "S" in s.split(" ")[-1]}  # decided cases with a sentence logged
    top = collections.Counter(sig.values())
    single = collections.Counter(s for k, s in sig.items() if cases[k].get("single_hearing_trial") == "1")
    members = collections.defaultdict(list)
    for k, s_ in sig.items():
        members[s_].append(k)
    top_rows = [{"signature": s_, "cases": n, "share": round(n / len(sig), 4), "single_hearing_cases": single.get(s_, 0),
                 **duration_cols(members[s_], events)} for s_, n in top.most_common(40)] if sig else []
    strata = collections.defaultdict(list)
    for k in sig:
        if cases[k]["jkey"] and cases[k]["group"]:
            strata[(k[0], cases[k]["group"])].append(k)
    by_judge = collections.defaultdict(list)  # unit: one judge on one group of articles at one court
    for s, ks in strata.items():
        for k in ks:
            by_judge[(cases[k]["jkey"], s[1])].append(k)
    judges = [j for j, ks in by_judge.items() if len(ks) >= min_cases]
    obs = {j: modal_share([sig[k] for k in by_judge[j]]) for j in judges}
    ge = collections.Counter()
    rng = random.Random(seed)
    for _ in range(perms):  # shuffle which judge decided which case, within court x article group
        lab = {}
        for ks in strata.values():
            js = [cases[k]["jkey"] for k in ks]
            rng.shuffle(js)
            lab.update(zip(ks, js))
        perm = collections.defaultdict(list)
        for k, j in lab.items():
            perm[(j, cases[k]["group"])].append(sig[k])
        for j in judges:
            if modal_share(perm[j])[1] >= obs[j][1]:
                ge[j] += 1
    rows = []
    for j in judges:
        ks = by_judge[j]
        c0 = cases[ks[0]]
        peers = [sig[k] for k in strata[(ks[0][0], j[1])] if cases[k]["jkey"] != j[0]]
        rows.append({"judge_key": j[0], "judge": c0.get("judge", ""), "court": c0["court_name"], "articles": j[1], "cases": len(ks),
                     "modal_signature": obs[j][0], "modal_share": round(obs[j][1], 3),
                     "court_peers_modal_share": round(modal_share(peers)[1], 3) if peers else "",
                     "distinct_signatures": len(set(sig[k] for k in ks)),
                     "single_hearing_share": round(sum(cases[k].get("single_hearing_trial") == "1" for k in ks) / len(ks), 3),
                     **duration_cols([k for k in ks if sig[k] == obs[j][0]], events, "modal_"),
                     "p": (ge[j] + 1) / (perms + 1)})
    q = bh([r["p"] for r in rows])
    for r, qq in zip(rows, q):
        r["q"] = round(qq, 4)
        r["p"] = round(r["p"], 4)
        r["more_uniform_than_colleagues"] = int(r["q"] < 0.05)
    rows.sort(key=lambda r: (r["q"], -r["modal_share"]))
    return rows, top_rows


# ---------------------------------------------------------------- 4. proximity to listed judges (internal)
def ppr(edges: dict, seeds: set, alpha: float = 0.15, iters: int = 100) -> dict:
    """Personalised PageRank on an undirected weighted graph {(a, b): w}; restart to seeds."""
    nbr = collections.defaultdict(dict)
    for (a, b), w in edges.items():
        nbr[a][b] = nbr[a].get(b, 0) + w
        nbr[b][a] = nbr[b].get(a, 0) + w
    seeds = {s for s in seeds if s in nbr}
    if not seeds:
        return {}
    r0 = {s: 1 / len(seeds) for s in seeds}
    r = dict(r0)
    deg = {a: sum(v.values()) for a, v in nbr.items()}
    for _ in range(iters):
        nr = collections.defaultdict(float)
        for a, ra in r.items():
            for b, w in nbr[a].items():
                nr[b] += (1 - alpha) * ra * w / deg[a]
        for s, v in r0.items():
            nr[s] += alpha * v
        r = nr
    return dict(r)


def proximity(cases: dict, prosecutors: dict, seeds: set, court_weight: float = 0.5) -> list[dict]:
    edges = collections.Counter()
    for k, c in cases.items():
        if not c["jkey"]:
            continue
        for p in prosecutors.get(k, ()):
            edges[(c["jkey"], "P:" + p)] += 1
        edges[(c["jkey"], "C:" + k[0])] += court_weight
    sc = ppr(edges, seeds)
    deg = collections.Counter()
    for (a, _b), w in edges.items():
        deg[a] += w
    info = {c["jkey"]: (c.get("judge", ""), c["court_name"]) for c in cases.values() if c["jkey"]}
    n_cases = collections.Counter(c["jkey"] for c in cases.values() if c["jkey"])
    rows = [{"judge_key": j, "judge": info[j][0], "court": info[j][1], "cases": n_cases[j], "score": round(s, 6),
             "score_per_case": round(s / deg[j], 8) if deg[j] else "", "is_seed": int(j in seeds)}
            for j, s in sc.items() if j in info]
    rows.sort(key=lambda r: -r["score"])
    return rows


def seeds_from_dossier(W: Path) -> set:
    p = W / "analysis" / "judge_dossier.csv"
    if not p.exists():
        return set()
    from urllib.parse import unquote
    return {unquote(r["post_id"]) for r in read_csv(p) if r.get("sanctions_status", "").startswith("sanctioned")}


# ---------------------------------------------------------------- report
def write_md(path: Path, B, P, S, T, X, n_cases: int, args) -> None:
    sigB = [b for b in B if b["q"] < 0.05]
    L = ["# Graph analyses", "", f"{n_cases} cases under the tracked articles with a case page read. Rules: see the module docstring.", "",
         f"## 1. Hidden batches (window {args.window} identifier numbers, trial receipt within {args.days} days, a shared article)", "",
         f"- Batches of 2 or more: **{len(B)}**; significant after correction (q < 0.05): **{len(sigB)}**; "
         f"cases in significant batches: **{sum(b['cases'] for b in sigB)}**.",
         f"- In significant batches: members with no OVD-Info record **{sum(b['not_in_ovd'] for b in sigB)}**; "
         f"identifier numbers inside a batch never seen **{sum(b['numbers_never_seen'] for b in sigB)}**; "
         f"batches split across courts **{sum(b['courts'] > 1 for b in sigB)}**; with trial dockets in identifier order "
         f"**{sum(b['dockets_in_same_order'] == 'yes' for b in sigB)}**.", "",
         "| batch | cases | span | p | q | articles | courts | judges | in OVD-Info | not | never seen |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {b['batch']} | {b['cases']} | {b['span']} | {b['p_approx']:.2g} | {b['q']:.2g} | {b['shared_articles']} | {b['courts']} | "
          f"{b['judges']} | {b['in_ovd']} | {b['not_in_ovd']} | {b['numbers_never_seen']} |" for b in B[:25]]
    sigP = [r for r in P if r["significant"]]
    if "pairs" not in args.only:
        L += ["", "## 2. Prosecutor-judge pairings: not run (courts name the prosecutor on about 5% of case pages)"]
    else:
      L += ["", "## 2. Prosecutor-judge pairings (within court x article group x year)", "",
          f"- Pairs tested: **{len(P)}**; met significantly more often than caseloads explain (q < 0.05, 3+ cases): **{len(sigP)}**.", "",
          "| judge | court | prosecutor | shared | expected | ratio | q |", "|---|---|---|---|---|---|---|"]
      L += [f"| {r['judge']} | {r['court']} | {r['prosecutor']} | {r['shared_cases']} | {r['expected']} | {r['ratio']} | {r['q']:.2g} |" for r in sigP[:25]]
    sigS = [r for r in S if r["more_uniform_than_colleagues"]]
    L += ["", f"## 3. Procedural signatures (judges with {args.min_cases}+ decided cases; {args.perms} permutations within court x article group)", "",
          f"- Judges tested: **{len(S)}**; more uniform than colleagues at the same court (q < 0.05): **{len(sigS)}**.", "",
          "| judge | court | articles | cases | modal signature | share | peers | median days to sentence (modal) | over 90 days | q |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['judge']} | {r['court']} | {r['articles']} | {r['cases']} | `{r['modal_signature']}` | {r['modal_share']:.0%} | "
          f"{r['court_peers_modal_share'] if r['court_peers_modal_share'] == '' else format(r['court_peers_modal_share'], '.0%')} | "
          f"{r['modal_median_days_to_sentence']} | {r['modal_share_over_90_days']} | {r['q']:.2g} |" for r in S[:25]]
    L += ["", "Most common signatures (R registered, J to judge, D decision on the case, P/p preliminary held/postponed, "
          "H/h hearing held/postponed, E custody extended, S sentence; a digit = that many, 3 = 3 or more):", "",
          "| signature | cases | share | of which single-hearing | median days judge to sentence | over 90 days |", "|---|---|---|---|---|---|"]
    L += [f"| `{t['signature']}` | {t['cases']} | {t['share']:.1%} | {t['single_hearing_cases']} | {t['median_days_to_sentence']} | "
          f"{t['share_over_90_days']} |" for t in T[:15]]
    if "proximity" in args.only:
      L += ["", "## 4. Proximity to listed judges: INTERNAL, never publish", "",
          f"- Seeds (judges whose name matches a listing): **{sum(r['is_seed'] for r in X)}**. Ranking in proximity_INTERNAL.csv."]
    path.write_text("\n".join(L) + "\n", "utf-8")


def diagnose(D: dict, W: Path) -> None:
    """Coverage of the inputs each analysis needs, and why listed judges may not be found. No defendant data printed."""
    C = D["cases"]
    n = len(C) or 1
    cnt = lambda f: sum(1 for c in C.values() if f(c))  # noqa: E731
    print(f"cases under tracked articles: {len(C)}")
    print(f"  with a parsable case identifier (UID): {cnt(lambda c: parse_uid(c.get('uid', '')))} ({cnt(lambda c: parse_uid(c.get('uid', ''))) / n:.0%})")
    print(f"  with a judge name on the page:          {cnt(lambda c: c.get('judge'))} ({cnt(lambda c: c.get('judge')) / n:.0%})")
    print(f"  with a judge key (name parsed):         {cnt(lambda c: c['jkey'])} ({cnt(lambda c: c['jkey']) / n:.0%})")
    print(f"  with a named prosecutor parsed:         {sum(1 for k in C if D['prosecutors'].get(k))} ({sum(1 for k in C if D['prosecutors'].get(k)) / n:.0%})")
    print(f"  with events: {sum(1 for k in C if D['events'].get(k))}; distinct prosecutors: {len(D['pnames'])}")
    raw = collections.Counter()
    pp = W / "cards" / "card_parties.csv"
    if pp.exists():
        for p_ in read_csv(pp):
            if p_.get("role_class") == "prosecutor":
                raw["prosecutor rows"] += 1
                raw["with a name" if p_.get("name") else "no name"] += 1
                if p_.get("name") and not prosecutor_key(p_["name"], "")[0] and raw["shown"] < 8:
                    raw["shown"] += 1
                    print(f"    prosecutor name not parsed: {p_['name'][:80]!r}")
    print(f"  prosecutor party rows: {dict(raw)}")
    by_court = collections.Counter(c["court_name"] for c in C.values() if not c["jkey"])
    print(f"  cases without a judge key, top courts: {by_court.most_common(5)}")
    seeds = seeds_from_dossier(W)
    keys = {c["jkey"] for c in C.values() if c["jkey"]}
    print(f"listed-judge seeds in judge_dossier.csv: {len(seeds)}; found among case judge keys: {len(seeds & keys)}")
    for sd in sorted(seeds - keys)[:10]:
        court = sd.split(":")[0]
        near = sorted(k for k in keys if k.split(":")[0] == court)[:5]
        print(f"    seed {sd!r} not found; judge keys at that court: {near}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--only", default="batches,sequences",
                    help="analyses to run. pairs and proximity are off by default: on the census data courts name the "
                         "prosecutor on about 5%% of case pages ('Информация скрыта' or the office only), too few to test")
    ap.add_argument("--window", type=int, default=20, help="largest identifier span of one batch")
    ap.add_argument("--days", type=int, default=45, help="largest gap in trial receipt between batch members")
    ap.add_argument("--min-cases", type=int, default=10)
    ap.add_argument("--perms", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--diagnose", action="store_true", help="print input coverage and seed matching, then stop")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    W = Path(cfg["_work"])
    D = load(W)
    if a.diagnose:
        diagnose(D, W)
        return
    out = W / "analysis" / "graph"
    only = set(a.only.split(","))
    B = M = G = P = S = T = X = []
    if "batches" in only:
        B, M, G = find_batches(D["cases"], D["all_uids"], a.window, a.days)
        write_csv(out / "batches.csv", B); write_csv(out / "batch_members.csv", M); write_csv(out / "batch_gaps.csv", G)
        LOG.info("batches: %d (q<0.05: %d)", len(B), sum(b["q"] < 0.05 for b in B))
    if "pairs" in only:
        P = pairings(D["cases"], D["prosecutors"], D["pnames"])
        write_csv(out / "pairings.csv", P)
        LOG.info("pairings tested: %d, significant: %d", len(P), sum(r["significant"] for r in P))
    if "sequences" in only:
        S, T = signatures(D["cases"], D["events"], a.min_cases, a.perms, a.seed)
        write_csv(out / "signatures_judges.csv", S); write_csv(out / "signatures_top.csv", T)
        LOG.info("judges tested: %d, more uniform than colleagues: %d", len(S), sum(r["more_uniform_than_colleagues"] for r in S))
    if "proximity" in only:
        seeds = seeds_from_dossier(W)
        X = proximity(D["cases"], D["prosecutors"], seeds)
        write_csv(out / "proximity_INTERNAL.csv", X)
        LOG.info("proximity: %d seeds found in the network, %d judges ranked", sum(r["is_seed"] for r in X), len(X))
    write_md(out / "graph_findings.md", B, P, S, T, X, len(D["cases"]), a)
    LOG.info("wrote %s", out)


if __name__ == "__main__":
    main()
