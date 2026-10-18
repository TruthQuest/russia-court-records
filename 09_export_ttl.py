#!/usr/bin/env python3
"""Step 9 (superseded by kg_build.py, which writes the CourtLink 0.3 graph). Kept for older pipelines only.

Model (hearing-level, not person-level):
    cl:Proceeding  cl:concernsPersecution <ovd record> ; cl:heldAt cl:Court ; cl:presidedBy cl:Judge ;
                   cl:instance ; cl:docketNumber ; cl:caseUID ; cl:decisionDate ;
                   prov:wasDerivedFrom cl:SourceDocument (url, sha256, fetched_at)
    cl:Judge       cl:servesAt cl:Court ; foaf:familyName ; cl:initials
    cl:Judge       cl:sanctionsListing <opensanctions entity>   ONLY for review_decision=confirmed

    python 09_export_ttl.py [--persecution-ns https://.../persecution/]
"""
from __future__ import annotations

import argparse
import re

from courtlink.common import LOG, load_config, parse_date, read_csv, setup_logging, work_path

CL = "https://traceoriginresearch.com/ontology/courtlink#"
DATA = "https://traceoriginresearch.com/id/"


def lit(s: str) -> str:
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{s}"'


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s or "x")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--persecution-ns", default="https://traceoriginresearch.com/id/persecution/",
                    help="namespace of OVD record IRIs in your existing graph")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    judges = {j["judge_id"]: j for j in read_csv(work_path(cfg, "judges.csv"))}
    edges = read_csv(work_path(cfg, "judge_edges.csv"))
    hearings = {h["hearing_id"]: h for h in read_csv(work_path(cfg, "hearings.csv"))}
    if work_path(cfg, "hearings_manual.csv").exists():
        hearings.update({h["hearing_id"]: h for h in read_csv(work_path(cfg, "hearings_manual.csv"))})
    sanc_p = work_path(cfg, "sanctions_candidates.csv")
    confirmed = [s for s in read_csv(sanc_p) if s.get("review_decision", "").strip().lower() == "confirmed"] \
        if sanc_p.exists() else []

    L = [f"@prefix cl: <{CL}> .", f"@prefix d: <{DATA}> .", f"@prefix p: <{a.persecution_ns}> .",
         "@prefix prov: <http://www.w3.org/ns/prov#> .", "@prefix foaf: <http://xmlns.com/foaf/0.1/> .",
         "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .", "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", ""]
    courts = {}
    for e in edges:
        h = hearings.get(e["hearing_id"], {})
        courts[e["court_id"]] = h.get("court_name", "")
        pid = f"d:proceeding_{slug(e['hearing_id'])}"
        L.append(f"{pid} a cl:Proceeding ;")
        L.append(f"  cl:concernsPersecution p:{slug(e['record_id'])} ;")
        L.append(f"  cl:heldAt d:court_{slug(e['court_id'])} ;")
        L.append(f"  cl:presidedBy d:judge_{slug(e['judge_id'])} ;")
        if e.get("instance"):
            L.append(f"  cl:instance {lit(e['instance'])} ;")
        if e.get("docket"):
            L.append(f"  cl:docketNumber {lit(e['docket'])} ;")
        if e.get("uid"):
            L.append(f"  cl:caseUID {lit(e['uid'])} ;")
        dd = parse_date(e.get("decision_date", ""))
        if dd:
            L.append(f"  cl:decisionDate \"{dd}\"^^xsd:date ;")
        L.append(f"  cl:judgeSource {lit(e.get('judge_source', ''))} ;")
        if h.get("card_url"):
            sid = f"d:src_{slug((h.get('card_sha256') or e['hearing_id'])[:16])}"
            L.append(f"  prov:wasDerivedFrom {sid} .")
            L.append(f"{sid} a cl:SourceDocument ; prov:atLocation {lit(h['card_url'])} ;")
            if h.get("card_sha256"):
                L.append(f"  cl:sha256 {lit(h['card_sha256'])} ;")
            if h.get("card_fetched_at"):
                L.append(f"  prov:generatedAtTime \"{h['card_fetched_at']}\"^^xsd:dateTime ;")
            L[-1] = L[-1].rstrip(" ;") + " ."
        else:
            L[-1] = L[-1].rstrip(" ;") + " ."
    for cid, name in courts.items():
        L.append(f"d:court_{slug(cid)} a cl:Court ; rdfs:label {lit(name or cid)} .")
    for jid, j in judges.items():
        L.append(f"d:judge_{slug(jid)} a cl:Judge ; foaf:familyName {lit(j['surname'])} ; "
                 f"cl:initials {lit(j['i1'] + '.' + j['i2'] + '.')} ; rdfs:label {lit(j['display'])} ; "
                 f"cl:servesAt d:court_{slug(j['court_id'])} .")
    for s in confirmed:
        L.append(f"d:judge_{slug(s['judge_id'])} cl:sanctionsListing <{s['os_url']}> .")
    out = work_path(cfg, "judicial_layer.ttl")
    out.write_text("\n".join(L) + "\n", "utf-8")
    LOG.info("wrote %s: %d proceedings, %d judges, %d courts, %d confirmed listings",
             out, len(edges), len(judges), len(courts), len(confirmed))


if __name__ == "__main__":
    main()
