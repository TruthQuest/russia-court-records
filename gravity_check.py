#!/usr/bin/env python3
"""Is the missing 'exit' (dismissal) the law or the courts? Outcomes by article part, so the comparison can be made where
dismissal is legally available.

    python gravity_check.py

Reads   work/cards/card_people.csv (one row per defendant: articles with parts, result class), work/cards/card_summary.csv,
        work/courts.csv
Writes  work/analysis/gravity_check.md and gravity_by_part.csv

1. Per article part (a defendant counts under every part charged; 'most serious' column = only charge or the heaviest
   listed first on the page): decided defendants, convicted, dismissed (incl. court fine), acquitted. Classify each
   part's gravity by its maximum penalty (UK RF art. 15) yourself or with a lawyer: the script does not guess it.
   Defendants charged ONLY with parts where dismissal is legally possible are the fair comparison with the national rate.
2. Military-court cases: how many include 205.2, and how many have 205.2 as the ONLY tracked article.
No names are read or written.
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

from courtlink.common import load_config, read_csv, write_csv

DECIDED = {"guilty": "convicted", "acquitted": "acquitted", "dismissed": "dismissed", "court_fine": "dismissed"}
MILITARY = re.compile(r"(?:ovs|fvs)--|окружн\w* военн|флотск\w* военн", re.I)


def parts(s: str) -> list[str]:
    return [a.strip() for a in (s or "").split(";") if a.strip()]


COMPARE = ("205.2", "280", "282", "282.2", "354.1")


def _year(d: str) -> str:
    m = re.search(r"(20\d\d)", d or "")
    return m.group(1) if m else "?"


def _norm(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "").strip())
    t = re.sub(r"\d{2}\.\d{2}\.\d{4}", "<date>", t)
    return t[:120]


def extra_checks(people, summ, is_mil, events=None) -> list[str]:
    """Review round 3: (a) outcomes by DECISION year for the five articles with national figures (national tables count by
    year of decision, so 2023 decisions are the like-for-like comparison); (b) the recorded grounds of every dismissal and
    compulsory-medical outcome (which exits were actually used; names are not in this field, texts are truncated);
    (c) identifier continuity: how often one case identifier (УИД) spans several registrations, and whether those
    registrations agree on defendants and articles."""
    L = ["", "## (a) Outcomes by decision year, articles with national figures (dismissed / decided; only-charge in brackets)", "",
         "| article | frame | " + " | ".join(str(y) for y in range(2022, 2027)) + " |", "|---|---|" + "---|" * 5]
    cnt = collections.defaultdict(collections.Counter)
    for p in people:
        out = DECIDED.get(p.get("result_class", ""))
        if not out:
            continue
        arts = {a.split("(")[0] for a in parts(p.get("articles", ""))}
        fr = "military" if is_mil(p["court_id"]) else "district/regional"
        y = _year(p.get("date", ""))
        for a in COMPARE:
            if a in arts:
                k = (a, fr, y)
                cnt[k]["dec"] += 1
                cnt[k]["dis"] += out == "dismissed"
                if arts == {a}:
                    cnt[k]["odec"] += 1
                    cnt[k]["odis"] += out == "dismissed"
    for a in COMPARE:
        for fr in ("military", "district/regional"):
            cells = [cnt[(a, fr, str(y))] for y in range(2022, 2027)]
            if sum(c["dec"] for c in cells):
                L.append(f"| {a} | {fr} | " + " | ".join(f"{c['dis']}/{c['dec']} ({c['odis']}/{c['odec']})" for c in cells) + " |")
    L += ["", "## (b) Recorded grounds: dismissals and compulsory medical measures", "",
          "| class | frame | result text (normalised) | defendants |", "|---|---|---|---|"]
    g = collections.Counter()
    ev = collections.defaultdict(list)
    for e in events or []:
        ev[(e["court_id"], e["docket_key"])].append(e)
    for p in people:
        rc = p.get("result_class", "")
        if rc in ("dismissed", "court_fine", "medical"):
            fr = "military" if is_mil(p["court_id"]) else "district/regional"
            basis = sorted({_norm(e.get("basis", "")) for e in ev.get((p["court_id"], p["docket_key"]), [])
                            if e.get("basis") and re.search(r"прекращ|медицин|штраф|освоб", (e.get("result", "") + " " + e.get("basis", "")), re.I)})
            g[(rc, fr, _norm(p.get("result", "")) + (" ; basis: " + "; ".join(basis)[:200] if basis else ""))] += 1
    L += [f"| {rc} | {fr} | {t} | {n} |" for (rc, fr, t), n in sorted(g.items(), key=lambda x: (x[0][0], x[0][1], -x[1]))]
    by_uid = collections.defaultdict(list)
    for s_ in summ:
        if s_.get("uid"):
            by_uid[s_["uid"]].append(s_)
    multi = {u: v for u, v in by_uid.items() if len(v) > 1}
    cross = sum(len({r["court_id"] for r in v}) > 1 for v in multi.values())
    ppl = sum(len({r.get("people", "") for r in v}) > 1 for v in multi.values())
    art = sum(len({frozenset(a.split("(")[0] for a in parts(r.get("articles", ""))) for r in v}) > 1 for v in multi.values())
    yrs = collections.Counter()
    for u in by_uid:
        m = re.search(r"-(20\d\d)-", u)
        yrs[m.group(1) if m else "?"] += 1
    L += ["", "## (c) Case identifier (УИД) continuity", "",
          f"Registrations with an identifier: {sum(len(v) for v in by_uid.values())}; distinct identifiers: {len(by_uid)}; "
          f"identifiers on more than one registration: {len(multi)} (of which at more than one court: {cross}).",
          f"Among those, registrations that disagree on the number of defendants: {ppl}; on the set of articles: {art}.",
          f"Registrations without an identifier: {sum(not s_.get('uid') for s_ in summ)}.",
          "Identifiers by year embedded in the identifier: " + ", ".join(f"{y}: {n}" for y, n in sorted(yrs.items()))]
    # (d) trials in absentia (CPC 247(5)): any mention on the defendant row or the case's events
    ABS = re.compile(r"заочн", re.I)
    abs_cases = {k for k, es in ev.items() if any(ABS.search(" ".join(str(e.get(f, "")) for f in ("event", "result", "basis"))) for e in es)}
    tab = collections.defaultdict(collections.Counter)
    for p in people:
        out = DECIDED.get(p.get("result_class", ""))
        if not out:
            continue
        absent = (p["court_id"], p["docket_key"]) in abs_cases or bool(ABS.search(p.get("result", "")))
        ps = set(parts(p.get("articles", "")))
        fr = "military" if is_mil(p["court_id"]) else "district/regional"
        for a_ in ps:
            k = (a_, fr, "absent" if absent else "present")
            tab[k]["dec"] += 1
            tab[k]["dis"] += out == "dismissed"
            if len(ps) == 1:
                tab[k]["odec"] += 1
                tab[k]["odis"] += out == "dismissed"
    L += ["", "## (d) Trials in absentia ('заочн' on the case page): dismissed / decided (only-charge in brackets)", "",
          f"Cases with an in-absentia mention: {len(abs_cases)}.", "",
          "| article part | frame | in absentia | present |", "|---|---|---|---|"]
    keys = sorted({(a_, fr) for (a_, fr, _) in tab}, key=lambda k: -(tab[(k[0], k[1], "absent")]["dec"] + tab[(k[0], k[1], "present")]["dec"]))
    for a_, fr in keys:
        A, Pr = tab[(a_, fr, "absent")], tab[(a_, fr, "present")]
        if A["dec"] + Pr["dec"] >= 5:
            L.append(f"| {a_} | {fr} | {A['dis']}/{A['dec']} ({A['odis']}/{A['odec']}) | {Pr['dis']}/{Pr['dec']} ({Pr['odis']}/{Pr['odec']}) |")
    # (e) the like-for-like test: 2023 decisions, only charge, present in court, five articles with national figures
    L += ["", "## (e) Like-for-like with national 2023: decisions in 2023, one article only, defendant present", "",
          "| article | dismissed | decided |", "|---|---|---|"]
    lk = collections.Counter()
    for p in people:
        out = DECIDED.get(p.get("result_class", ""))
        if not out or _year(p.get("date", "")) != "2023":
            continue
        arts = {a_.split("(")[0] for a_ in parts(p.get("articles", ""))}
        if len(arts) != 1 or (p["court_id"], p["docket_key"]) in abs_cases or ABS.search(p.get("result", "")):
            continue
        a_ = next(iter(arts))
        if a_ in COMPARE:
            lk[(a_, "dec")] += 1
            lk[(a_, "dis")] += out == "dismissed"
    L += [f"| {a_} | {lk[(a_, 'dis')]} | {lk[(a_, 'dec')]} |" for a_ in COMPARE]
    print("\n".join(L))
    return L


def main() -> None:
    cfg = load_config(None)
    W = Path(cfg["_work"])
    people = read_csv(W / "cards" / "card_people.csv")
    summ = read_csv(W / "cards" / "card_summary.csv")
    courts = {r["court_id"]: r for r in read_csv(W / "courts.csv")} if (W / "courts.csv").exists() else {}

    def is_mil(cid):
        c = courts.get(cid, {})
        return bool(MILITARY.search(cid) or MILITARY.search(c.get("name", "")) or "Military" in c.get("court_type", ""))

    frame_tot = collections.defaultdict(collections.Counter)  # per frame: decided, medical (compulsory treatment), per defendant
    for p in people:
        fr = "military" if is_mil(p["court_id"]) else "district/regional"
        if p.get("result_class") == "medical":
            frame_tot[fr]["medical"] += 1
            if "205.2" in {a.split("(")[0] for a in parts(p.get("articles", ""))}:
                frame_tot[fr]["medical_205.2"] += 1
        elif DECIDED.get(p.get("result_class", "")):
            frame_tot[fr]["decided"] += 1
            if "205.2" in {a.split("(")[0] for a in parts(p.get("articles", ""))}:
                frame_tot[fr]["decided_205.2"] += 1
    by_part = collections.defaultdict(lambda: collections.Counter())
    only = collections.defaultdict(lambda: collections.Counter())  # defendants charged with exactly one article part
    for p in people:
        out = DECIDED.get(p.get("result_class", ""))
        if not out:
            continue
        ps = parts(p.get("articles", ""))
        frame = "military" if is_mil(p["court_id"]) else "district/regional"
        for a in set(ps):
            by_part[(a, frame)]["decided"] += 1
            by_part[(a, frame)][out] += 1
        if len(set(ps)) == 1:
            only[(ps[0], frame)]["decided"] += 1
            only[(ps[0], frame)][out] += 1
    rows = []
    for (a, frame), c in sorted(by_part.items(), key=lambda x: (-x[1]["decided"], x[0])):
        o = only.get((a, frame), collections.Counter())
        rows.append({"article_part": a, "frame": frame, "decided": c["decided"], "convicted": c["convicted"], "dismissed": c["dismissed"],
                     "acquitted": c["acquitted"], "dismissed_share": round(c["dismissed"] / c["decided"], 4) if c["decided"] else "",
                     "only_charge_decided": o["decided"], "only_charge_dismissed": o["dismissed"], "gravity": ""})
    out_dir = W / "analysis"
    write_csv(out_dir / "gravity_by_part.csv", rows)

    mil = [s for s in summ if is_mil(s["court_id"])]
    arts = lambda s: {a.split("(")[0] for a in parts(s.get("articles", ""))}  # noqa: E731
    with_2052 = [s for s in mil if "205.2" in arts(s)]
    only_2052 = [s for s in with_2052 if arts(s) == {"205.2"}]

    L = ["# Dismissal by article part (decided defendants on case pages read)", "",
         "Compulsory psychiatric treatment (not counted as decided): " + "; ".join(
             f"{fr}: {c['medical']} defendants (205.2: {c['medical_205.2']}), against {c['decided']} decided (205.2: {c['decided_205.2']})"
             for fr, c in sorted(frame_tot.items())), "",
         f"Military-court case pages: {len(mil)}; including 205.2: {len(with_2052)}; with 205.2 as the only article: {len(only_2052)}.", "",
         "Fill the gravity column (UK RF art. 15: small up to 3 years, medium up to 5, grave up to 10, especially grave above) "
         "from the maximum penalty in force, then compare dismissal where reconciliation, court fine or active repentance is available.", "",
         "| article part | frame | decided | convicted | dismissed | acquitted | dismissed share | only charge: decided | only charge: dismissed |",
         "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['article_part']} | {r['frame']} | {r['decided']} | {r['convicted']} | {r['dismissed']} | {r['acquitted']} | "
          f"{r['dismissed_share']} | {r['only_charge_decided']} | {r['only_charge_dismissed']} |" for r in rows if r["decided"] >= 5]
    evp = W / "cards" / "card_events.csv"
    L += extra_checks(people, summ, is_mil, read_csv(evp) if evp.exists() else [])
    (out_dir / "gravity_check.md").write_text("\n".join(L) + "\n", "utf-8")
    print("\n".join(L[:5]))
    print(f"-> {out_dir / 'gravity_check.md'} and gravity_by_part.csv ({len(rows)} rows)")


if __name__ == "__main__":
    main()
