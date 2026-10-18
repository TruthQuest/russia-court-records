#!/usr/bin/env python3
"""Build a shareable Excel workbook from the pipeline outputs, for OVD-Info.

    python export_xlsx.py --out courtlink_for_ovd.xlsx [--coverage coverage.csv]

Reads work/hearings.csv, work/judge_edges.csv, work/cases.csv (region, anonymity flag only).
Contains NO defendant names: rows join to OVD-Info data on record_id. Judges are public officials
named on public court pages. Court card links can show defendants' names, including people
OVD-Info lists as anonymous; those rows are flagged.
"""
from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from courtlink import english as en
from courtlink.common import load_config, read_csv, work_path
from courtlink.judges import judge_key, parse_judge, person_key

ANON_RE = re.compile(r"anonym|wished to remain|name withheld|unknown", re.I)
UID_PARTS = re.compile(r"^(\w{8})-\d{2}-(\d{4})-(\d{6})")
OUTCOME_EN = {"verdict": "Verdict", "pending": "Pending (no result posted)", "compulsory_medical": "Compulsory psychiatric treatment",
              "transferred": "Transferred to another court", "returned_to_prosecutor": "Returned to prosecutor",
              "court_fine_dismissal": "Dismissed with court fine", "dismissed": "Dismissed",
              "joined_to_other_case": "Joined to another case", "other": "Other"}
TYPE_EN = {"district": "District/city court", "regional": "Regional-level court", "military_district": "District military court",
           "garrison": "Garrison military court"}
F = "Arial"
HEAD = PatternFill("solid", start_color="1F3A5F")
FLAG = PatternFill("solid", start_color="FCE4D6")


def sheet(wb, title, header, rows, widths, note=None):
    ws = wb.create_sheet(title)
    r0 = 1
    if note:
        ws.cell(1, 1, note).font = Font(name=F, italic=True, size=9, color="555555")
        r0 = 3
    for j, h in enumerate(header, 1):
        c = ws.cell(r0, j, h)
        c.font = Font(name=F, bold=True, color="FFFFFF", size=10)
        c.fill = HEAD
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for i, row in enumerate(rows, r0 + 1):
        for j, v in enumerate(row, 1):
            ws.cell(i, j, v).font = Font(name=F, size=10)
    for j, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(r0 + 1, 1)
    ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(header))}{r0 + max(len(rows), 1)}"
    return ws, r0


def clusters(hearings, arts, cfg=None):
    """uid -> co-registration cluster id, using the one rule shared with the graph and the report
    (courtlink/clusters.py). Reads the graph's work/kg/clusters.csv when present."""
    from pathlib import Path as _P
    from courtlink.clusters import DEFAULT_GAP, cluster as rule
    from courtlink.dockets import docket_key as dkey
    key = lambda h: (h["court_id"], "1", dkey(h["docket"]) or h["docket"])
    cp = _P(cfg["_work"]) / "kg" / "clusters.csv" if cfg else None
    if cp and cp.exists():
        by_reg = {(r["court_id"], r["srv"], r["docket_key"]): r["cluster_id"] for r in read_csv(cp)}
    else:
        regs = {}
        for h in hearings:
            k = key(h)
            d = regs.setdefault(k, {"court_id": k[0], "srv": k[1], "docket_key": k[2], "articles": set(), "received": ""})
            d["articles"] |= arts.get(h["record_id"], set())
        by_reg = rule(regs, DEFAULT_GAP)
    return {h["uid"]: by_reg[key(h)] for h in hearings if h.get("uid") and key(h) in by_reg}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config"); ap.add_argument("--out", default="courtlink_for_ovd.xlsx")
    ap.add_argument("--coverage", help="optional CSV: region,docketed,searched,matched")
    a = ap.parse_args()
    cfg = load_config(a.config)
    H = read_csv(work_path(cfg, "hearings.csv"))
    E = read_csv(work_path(cfg, "judge_edges.csv")) if work_path(cfg, "judge_edges.csv").exists() else []
    C = {c["record_id"]: c for c in read_csv(work_path(cfg, "cases.csv"))}
    arts = {e["record_id"]: set(filter(None, e.get("articles", "").split(";"))) for e in E}
    for rid, c in C.items():
        arts.setdefault(rid, set(filter(None, c.get("articles", "").split(";"))))
    anon = {rid for rid, c in C.items() if c.get("anonymous") == "1" or ANON_RE.search(c.get("name", ""))}
    cl = clusters(H, arts, cfg)

    wb = Workbook()
    wb.remove(wb.active)

    # --- About
    ws = wb.create_sheet("About")
    lines = [
        ("Court records linked to OVD-Info political prosecution cases", True),
        ("Trace Origin LLC. Prepared for OVD-Info. Not for publication without review.", False),
        ("", False),
        ("What this is", True),
        ("OVD-Info case records (by record_id) matched to first-instance criminal cases on Russian court websites (sudrf.ru), "
         "with the presiding judge, case UID, outcome and a link to the court's case card.", False),
        ("How matches were made", True),
        ("Each court was searched by criminal article and registration year; result rows were matched to OVD-Info records by "
         "docket number, then confirmed with defendant name, decision date and article. Rows where the court's article "
         "contradicted OVD-Info's were rejected. All matches here were automatic; none has been checked by hand yet.", False),
        ("What is NOT in this file", True),
        ("No defendant names. Join to your data on record_id. Court card links do display defendant names, "
         "including for people OVD-Info lists as anonymous: those rows are flagged in the 'Case links' sheet.", False),
        ("Coverage", True),
        ("Only regions swept so far are included (see 'Coverage'). Moscow (mos-gorsud.ru), magistrate courts and occupied "
         "territories were not searched.", False),
        ("Caveats", True),
        ("Judges are identified per court. The same name in two courts may or may not be one person ('Judges' sheet flags these). "
         "'Clusters counted once' groups registrations at one court with near-consecutive docket numbers and a shared article "
         "(the same rule as the graph and the report). It is used to avoid double counting, not as evidence of one investigation. "
         "'Verdict' covers conviction and acquittal; the courts' result field does not distinguish them. The judge is the one listed on "
         "the card; in panel courts (regional-level and district military) that is the presiding or reporting judge only.", False),
        ("Reading without Russian", True),
        ("Every Russian field has English beside it. Courts are translated the way English-language media cite them "
         "(place adjective kept: 'Nevsky District Court'). Judges' names appear twice in Latin script: 'press' spelling "
         "(BGN/PCGN, as newspapers write it: Yuri, Vorobyeva) for reading, and 'passport' spelling (ICAO 9303, used in Russian "
         "passports since 2013: Iurii, Vorobeva) because sanctions lists often copy passport spellings. Court results are "
         "translated from the courts' fixed vocabulary; articles carry a short gloss of the Criminal Code offence. "
         "Russian originals are kept in grey columns at the right for checking.", False),
        ("Evidence", True),
        ("Each card was fetched and stored; its SHA-256 and fetch time are given so the exact page can be produced later.", False),
        ("Sources", True),
        ("Court websites: sudrf.ru (public). Court list: Dataout / sudrfparser (CC BY-SA 4.0, Nov 2023). Case records: OVD-Info.", False),
    ]
    for i, (t, b) in enumerate(lines, 1):
        c = ws.cell(i, 1, t)
        c.font = Font(name=F, bold=b, size=14 if i == 1 else 10)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 110

    # --- Case links
    rows = []
    for h in sorted(H, key=lambda h: (C.get(h["record_id"], {}).get("region", ""), h["court_name"], h["docket"])):
        rid = h["record_id"]
        chk = h.get("uid_court_check", "")
        if chk.startswith("transferred_in_from:"):
            src = chk.split(":", 1)[1]
            chk = "transferred in from " + (en.court(src) if re.search("[А-Яа-я]", src) else (f"magistrate court {src}" if src[2:4] == "MS" else f"court code {src}"))
        elif chk == "ok":
            chk = "yes"
        rows.append([rid, C.get(rid, {}).get("region", ""), en.court(h["court_name"]), TYPE_EN.get(h["court_type"], h["court_type"]),
                     h["docket"], h["uid"], chk, en.press(h["judge"]), en.icao(h["judge"]), h["decision_date"],
                     OUTCOME_EN.get(h["outcome_class"], h["outcome_class"]), en.result(h["result"]),
                     cl.get(h["uid"], ""), en.articles(sorted(arts.get(rid, set()), key=lambda x: [int(p) for p in x.split(".")] if x.replace(".", "").isdigit() else [999])),
                     "YES" if rid in anon else "", h["card_url"], h["card_sha256"], h.get("card_fetched_at", ""),
                     h["court_name"], h["judge"], h["result"]])
    ws, r0 = sheet(wb, "Case links",
                   ["OVD record_id", "Region (OVD)", "Court", "Court type", "Docket", "Case UID", "UID belongs to this court",
                    "Judge listed on card (press spelling)", "Judge listed on card (passport spelling)", "Decision date", "Outcome",
                    "Court result (English)", "Co-registration cluster", "Articles (OVD)", "OVD anonymous: card shows name",
                    "Court card", "Card SHA-256", "Card fetched (UTC)", "Court (Russian)", "Judge (Russian)", "Result (Russian)"],
                   rows, [19, 16, 40, 18, 12, 28, 16, 34, 34, 11, 22, 40, 22, 40, 14, 50, 20, 20, 34, 30, 40])
    GREY = Font(name=F, size=10, color="808080")
    for i, row in enumerate(rows, r0 + 1):
        if row[14]:
            for j in range(1, 19):
                ws.cell(i, j).fill = FLAG
        ws.cell(i, 16).hyperlink = row[15]
        for j in (19, 20, 21):
            ws.cell(i, j).font = GREY
    n_links = len(rows)

    # --- Judges
    J = {}
    for h in H:
        j = parse_judge(h.get("judge", ""))
        if not j:
            continue
        jid = judge_key(h["court_id"], j)
        r = J.setdefault(jid, {"j": j, "court": h["court_name"], "court_id": h["court_id"], "type": h["court_type"],
                               "recs": set(), "uids": set(), "groups": set(), "arts": collections.Counter(),
                               "years": set(), "out": collections.Counter()})
        if j["full"] and not r["j"]["full"]:
            r["j"] = j
        r["recs"].add(h["record_id"])
        u = h["uid"] or f'{h["court_id"]}:{h["docket"]}'
        r["uids"].add(u)
        r["groups"].add(cl.get(h["uid"], u))
        for x in arts.get(h["record_id"], set()):
            r["arts"][x] += 1
        if h["decision_date"][-4:].isdigit():
            r["years"].add(h["decision_date"][-4:])
        r["out"][h["outcome_class"]] += 1
    byp = collections.defaultdict(set)
    for r in J.values():
        byp[person_key(r["j"])].add(r["court"])
    jrows = []
    for r in sorted(J.values(), key=lambda r: (-len(r["groups"]), -len(r["recs"]))):
        j = r["j"]
        jrows.append([en.press(j["display"]), en.icao(j["display"]), en.court(r["court"]), TYPE_EN.get(r["type"], r["type"]),
                      len(r["recs"]), len(r["uids"]), len(r["groups"]), r["out"].get("verdict", 0),
                      "; ".join(f"{en.articles([k])}: {v}" for k, v in r["arts"].most_common(5)),
                      ", ".join(sorted(r["years"])), "; ".join(en.court(x) for x in sorted(byp[person_key(j)] - {r["court"]})),
                      j["display"], r["court"]])
    ws, r0 = sheet(wb, "Judges", ["Judge (press spelling)", "Judge (passport spelling)", "Court", "Court type", "Records",
                                  "Registrations", "Clusters counted once", "Verdicts (conviction or acquittal)", "Articles (OVD-Info, per record)",
                                  "Decision years", "Same name in another court (verify)", "Judge (Russian)", "Court (Russian)"],
                   jrows, [36, 36, 42, 20, 11, 11, 15, 10, 60, 16, 34, 34, 40])
    for i in range(r0 + 1, r0 + 1 + len(jrows)):
        for j in (12, 13):
            ws.cell(i, j).font = Font(name=F, size=10, color="808080")

    # --- Co-registration clusters
    g = collections.defaultdict(lambda: {"uids": set(), "recs": set(), "judges": set(), "court": "", "arts": set()})
    for h in H:
        cid = cl.get(h["uid"])
        if cid:
            d = g[cid]
            d["uids"].add(h["uid"]); d["recs"].add(h["record_id"]); d["judges"].add(en.press(h["judge"])); d["court"] = en.court(h["court_name"])
            d["arts"] |= arts.get(h["record_id"], set())
    grows = [[k, d["court"], len(d["uids"]), len(d["recs"]), len(d["judges"]), "; ".join(sorted(d["judges"])),
              en.articles(sorted(d["arts"])), "; ".join(sorted(d["uids"]))]
             for k, d in sorted(g.items(), key=lambda x: -len(x[1]["uids"]))]
    from courtlink.clusters import DEFAULT_GAP, RULE_TEXT
    sheet(wb, "Co-registration clusters", ["Cluster", "Court", "Registrations", "Records", "Judges listed", "Judge names", "Articles", "Case UIDs"],
          grows, [30, 36, 11, 11, 9, 50, 16, 70],
          note="Rule: " + RULE_TEXT.format(gap=DEFAULT_GAP) + ". A numbering pattern, not evidence of one investigation; "
               "test against investigative case numbers, registration dates and the court's bench.")

    # --- Coverage + summary (formulas over 'Case links')
    ws = wb.create_sheet("Coverage")
    hdr = ["Region", "Docketed cases (OVD)", "Searched", "Matched", "Match rate (of searched)"]
    for j, t in enumerate(hdr, 1):
        c = ws.cell(1, j, t); c.font = Font(name=F, bold=True, color="FFFFFF", size=10); c.fill = HEAD
    cov = read_csv(a.coverage) if a.coverage else []
    for i, r in enumerate(cov, 2):
        ws.cell(i, 1, r["region"]); ws.cell(i, 2, int(r["docketed"])); ws.cell(i, 3, int(r["searched"]))
        ws.cell(i, 4, int(r["matched"])); ws.cell(i, 5, f"=IF(C{i}=0,0,D{i}/C{i})").number_format = "0%"
        for j in range(1, 4):
            ws.cell(i, j).font = Font(name=F, size=10, color="0000FF")
        ws.cell(i, 4).font = Font(name=F, size=10, color="0000FF")
    last = 1 + len(cov)
    if cov:
        t = last + 1
        ws.cell(t, 1, "Total").font = Font(name=F, bold=True)
        for col in "BCD":
            ws[f"{col}{t}"] = f"=SUM({col}2:{col}{last})"
        ws[f"E{t}"] = f"=IF(C{t}=0,0,D{t}/C{t})"; ws[f"E{t}"].number_format = "0%"
        ws.cell(t + 1, 1, "Blue figures: from coverage.py output, run 2026-10-15 (regions not listed: matches present, "
                          "coverage not yet measured).").font = Font(name=F, italic=True, size=9, color="555555")
    s = (last + 4) if cov else 3
    ws.cell(s, 1, "Outcomes of linked cases").font = Font(name=F, bold=True)
    rng = f"'Case links'!$K$2:$K${n_links + 1}"
    for i, k in enumerate(OUTCOME_EN.values(), s + 1):
        ws.cell(i, 1, k).font = Font(name=F, size=10)
        ws.cell(i, 2, f'=COUNTIF({rng},A{i})')
    tot = s + len(OUTCOME_EN) + 1
    ws.cell(tot, 1, "All linked defendants").font = Font(name=F, bold=True)
    ws.cell(tot, 2, f"=SUM(B{s + 1}:B{tot - 1})")
    ws.cell(tot + 1, 1, "Distinct judges").font = Font(name=F, size=10)
    ws.cell(tot + 1, 2, f"=COUNTA(Judges!$A$2:$A${len(jrows) + 1})")
    ws.cell(tot + 2, 1, "Rows where the card shows a name OVD keeps anonymous").font = Font(name=F, size=10)
    ws.cell(tot + 2, 2, f"=COUNTIF('Case links'!$O$2:$O${n_links + 1},\"YES\")")
    ws.column_dimensions["A"].width = 52
    for col in "BCDE":
        ws.column_dimensions[col].width = 18
    wb.move_sheet("Coverage", offset=-(len(wb.sheetnames) - 2))
    wb.save(a.out)
    print(f"wrote {a.out}: {n_links} case links, {len(jrows)} judges, {len(grows)} co-registration clusters, {len(anon & {h['record_id'] for h in H})} anonymous-flagged")


if __name__ == "__main__":
    main()
