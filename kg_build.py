#!/usr/bin/env python3
"""Build the CourtLink knowledge graph (RDF) from the pipeline outputs, and validate it with SHACL.

    python kg_build.py

Reads   work/hearings.csv, work/matches.csv, work/judge_edges.csv, work/cases.csv, work/courts.csv,
        work/census.csv (from census.py, optional but this is where the analytics come from)
Writes  work/kg/courtlink.ttl          ontology (copy of kg/courtlink.ttl)
        work/kg/courtlink-data.ttl     instance data
        work/kg/shacl-report.txt       validation report (if pyshacl is installed)

Load both .ttl files into Stardog, GraphDB or Oxigraph; queries live in kg/queries/*.rq.
No defendant names are written. Persecution records appear only as OVD-Info record IRIs.
"""
from __future__ import annotations

import argparse
import collections
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, OWL, PROV, RDF, RDFS, SKOS, XSD

from courtlink import english as en
from courtlink.common import LOG, load_config, parse_date, read_csv, setup_logging, work_path, write_csv
from courtlink.dockets import docket_key as dkey
from courtlink.judges import judge_key, parse_judge, person_key
from courtlink.clusters import DEFAULT_GAP, RULE_TEXT, cluster as split_groups

CL = Namespace("https://traceoriginresearch.com/ontology/courtlink#")
D = Namespace("https://traceoriginresearch.com/id/courtlink/")
OVD = Namespace("https://traceoriginresearch.com/id/ovd-record/")
ORG = Namespace("http://www.w3.org/ns/org#")
TYPE_CLASS = {"district": CL.DistrictCourt, "regional": CL.RegionalCourt, "military_district": CL.MilitaryDistrictCourt,
              "garrison": CL.GarrisonCourt, "magistrate": CL.MagistrateCourt}
TERMINAL = {"verdict", "compulsory_medical", "court_fine_dismissal", "dismissed"}
OUTCOMES = {"verdict": "Verdict (conviction or acquittal; not distinguished)", "pending": "Pending (no result posted)", "compulsory_medical": "Compulsory psychiatric treatment",
            "transferred": "Transferred to another court", "returned_to_prosecutor": "Returned to prosecutor",
            "court_fine_dismissal": "Dismissed with court fine", "dismissed": "Dismissed",
            "joined_to_other_case": "Joined to another case", "suspended": "Proceedings suspended", "other": "Other"}


def iri(ns, *parts) -> URIRef:
    return ns["/".join(quote(str(p).replace("/", "_"), safe="-._~") for p in parts)]


def rd(cfg, name):
    p = work_path(cfg, name)
    return read_csv(p) if p.exists() else []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--split-gap", type=int, default=DEFAULT_GAP, help="max docket-number distance inside one co-registration cluster")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    out_dir = Path(cfg["_work"]) / "kg"
    out_dir.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).parent / "kg"
    shutil.copy(here / "courtlink.ttl", out_dir / "courtlink.ttl")

    H = rd(cfg, "hearings.csv")
    M = {(m["record_id"], m["court_id"], m["docket_key"]): m for m in rd(cfg, "matches.csv")}
    E = rd(cfg, "judge_edges.csv")
    C = {c["record_id"]: c for c in rd(cfg, "cases.csv")}
    courts = {c["court_id"]: c for c in rd(cfg, "courts.csv")}
    census = rd(cfg, "census.csv")
    uid_of = {(u["court_id"], u["docket_key"]): u["uid"] for u in rd(cfg, "census_uids.csv") if u.get("uid")}
    card = {(s_["court_id"], s_["docket_key"]): s_ for s_ in rd(cfg, "cards/card_summary.csv")}
    for k_, s_ in card.items():
        if s_.get("uid"):
            uid_of.setdefault(k_, s_["uid"])
    code_to_court = {c.get("sudrf_code", ""): cid for cid, c in courts.items() if c.get("sudrf_code")}
    rec_arts = {e["record_id"]: set(filter(None, e.get("articles", "").split(";"))) for e in E}
    for rid, c in C.items():
        rec_arts.setdefault(rid, set(filter(None, c.get("articles", "").split(";"))))

    # ---- unify court cases from census and linked hearings ----
    cases: dict[tuple, dict] = {}

    def case_for(court_id, srv, docket, **kw):
        k = (court_id, srv or "1", dkey(docket) or docket)
        c = cases.setdefault(k, {"court_id": court_id, "srv": srv or "1", "docket": docket, "docket_key": k[2],
                                 "articles": set(), "rec_arts": set(), "court_arts": set(), "asof": "", "received": "", "decided": "", "judge": "", "outcome": "",
                                 "result": "", "uid": "", "n_def": 0, "sources": {}, "records": {}, "transfer_from": ""})
        for f, v in kw.items():
            if v and not c.get(f):
                c[f] = v
        return k, c

    for r in census:
        k, c = case_for(r["court_id"], r["srv"], r["docket"], received=r["received"], decided=r["decision_date"],
                        judge=r["judge"], outcome=r["outcome_class"], result=r["decision"],
                        uid=uid_of.get((r["court_id"], r.get("docket_key") or dkey(r["docket"])), ""))
        ca = set(filter(None, (r["articles"] or r.get("article_queried", "")).split(";")))
        c["articles"] |= ca; c["court_arts"] |= ca
        c["asof"] = max(c["asof"], r.get("fetched_at", ""))
        c["n_def"] = max(c["n_def"], int(r["n_defendants"] or 1))
        c.setdefault("court_name", r.get("court_name", "")); c.setdefault("court_type", r.get("court_type", ""))
        if r["source_sha256"]:
            c["sources"][r["source_sha256"]] = (r["source_url"], r["fetched_at"])
    for h in H:
        k, c = case_for(h["court_id"], "1", h["docket"], decided=parse_date(h["decision_date"]), judge=h["judge"],
                        outcome=h["outcome_class"], result=h["result"], uid=h["uid"])
        if h["judge"]:  # the card is authoritative for the judge (full name)
            c["judge"] = h["judge"]
        if h.get("outcome_class"):
            c["outcome"] = h["outcome_class"]
        c["articles"] |= rec_arts.get(h["record_id"], set()); c["rec_arts"] |= rec_arts.get(h["record_id"], set())
        c["asof"] = max(c["asof"], h.get("card_fetched_at", ""))
        c["n_def"] = max(c["n_def"], 1)
        if h.get("card_sha256"):
            c["sources"][h["card_sha256"]] = (h["card_url"], h.get("card_fetched_at", ""))
        m = M.get((h["record_id"], h["court_id"], h.get("docket_key", "")), {})
        c["records"][h["record_id"]] = (m.get("rule") or "unrecorded", m.get("confidence") or ("reviewed" if h.get("match_source") == "review" else "high"))
        chk = h.get("uid_court_check", "")
        if chk.startswith("transferred_in_from:"):
            c["transfer_from"] = h.get("uid_court_code", "")
        c.setdefault("court_name", h["court_name"]); c.setdefault("court_type", h["court_type"])
    groups = split_groups(cases, a.split_gap)

    g = Graph()
    for p, ns in (("cl", CL), ("d", D), ("ovd", OVD), ("skos", SKOS), ("prov", PROV), ("org", ORG), ("dct", DCTERMS),
                  ("foaf", FOAF)):
        g.bind(p, ns)
    rule_node = CL.CoRegistrationRule_v1
    g.add((rule_node, RDF.type, CL.CoRegistrationRule))
    g.add((rule_node, RDFS.comment, Literal(RULE_TEXT.format(gap=a.split_gap), lang="en")))

    def court_node(cid, name="", ctype=""):
        n = iri(D, "court", cid)
        if (n, RDF.type, None) in g:
            return n
        c = courts.get(cid, {})
        name = name or c.get("name", "") or cid
        g.add((n, RDF.type, TYPE_CLASS.get(ctype or c.get("court_type", ""), CL.Court)))
        g.add((n, RDFS.label, Literal(name, lang="ru")))
        g.add((n, SKOS.prefLabel, Literal(en.court(name), lang="en")))
        if c.get("sudrf_code"):
            g.add((n, CL.sudrfCode, Literal(c["sudrf_code"])))
        if c.get("url"):
            g.add((n, PROV.atLocation, URIRef(c["url"])))
        if c.get("iso"):
            reg = iri(D, "region", c["iso"])
            g.add((n, CL.inRegion, reg)); g.add((reg, RDF.type, CL.Region)); g.add((reg, SKOS.notation, Literal(c["iso"])))
        return n

    def code_court(code):
        cid = code_to_court.get(code)
        if cid:
            return court_node(cid)
        b = iri(D, "court", "code", code)
        if (b, RDF.type, None) not in g:
            g.add((b, RDF.type, CL.MagistrateCourt if code[2:4] == "MS" else CL.Court))
            g.add((b, CL.sudrfCode, Literal(code))); g.add((b, RDFS.label, Literal(code)))
            g.add((b, SKOS.prefLabel, Literal(("magistrate court " if code[2:4] == "MS" else "court ") + code, lang="en")))
        return b

    posts, person = {}, collections.defaultdict(set)
    post_dates = collections.defaultdict(list)

    def post_node(cid, raw, when):
        j = parse_judge(raw)
        if not j:
            return None
        jid = judge_key(cid, j)
        pn, hn = iri(D, "post", jid), iri(D, "person", jid)
        if jid not in posts:
            posts[jid] = pn
            g.add((pn, RDF.type, CL.JudicialPost)); g.add((pn, ORG.member, hn)); g.add((pn, ORG.organization, court_node(cid)))
            g.add((hn, RDF.type, FOAF.Person))
            g.add((hn, CL.familyName, Literal(j["surname"], lang="ru")))
            g.add((hn, CL.initials, Literal(f'{j["i1"]}.{j["i2"]}.')))
            person[person_key(j)].add(hn)
        if j["full"] or (hn, RDFS.label, None) not in g:
            for x in (hn, pn):
                g.remove((x, RDFS.label, None)); g.remove((x, SKOS.prefLabel, None))
                g.add((x, RDFS.label, Literal(j["display"], lang="ru")))
                g.add((x, SKOS.prefLabel, Literal(en.press(j["display"]), lang="en")))
            g.remove((hn, CL.passportSpelling, None))
            g.add((hn, CL.passportSpelling, Literal(en.icao(j["display"]), lang="en")))
        if when:
            post_dates[jid].append(when)
        return pn

    def article(a_):
        n = iri(D, "article", a_)
        if (n, RDF.type, None) not in g:  # flat scheme: no broader/narrower between articles
            g.add((n, RDF.type, SKOS.Concept)); g.add((n, SKOS.inScheme, CL.CriminalCodeScheme))
            g.add((n, SKOS.notation, Literal(a_)))
            g.add((n, SKOS.prefLabel, Literal(f"Art. {a_}" + (f": {en.ARTICLES[a_]}" if a_ in en.ARTICLES else ""), lang="en")))
        return n

    for k, lab in OUTCOMES.items():
        n = iri(D, "outcome", k)
        g.add((n, RDF.type, SKOS.Concept)); g.add((n, SKOS.inScheme, CL.OutcomeScheme))
        g.add((n, SKOS.prefLabel, Literal(lab, lang="en"))); g.add((n, CL.isTerminal, Literal(k in TERMINAL)))

    n_links = 0
    proceedings = set()
    for key, c in cases.items():
        cn = iri(D, "registration", c["court_id"], c["srv"], c["docket_key"])
        g.add((cn, RDF.type, CL.CourtRegistration))
        g.add((cn, CL.heldAt, court_node(c["court_id"], c.get("court_name", ""), c.get("court_type", ""))))
        g.add((cn, CL.docketNumber, Literal(c["docket"])))
        if c["uid"]:
            pr = iri(D, "proceeding", c["uid"])
            proceedings.add(pr)
            g.add((pr, RDF.type, CL.Proceeding)); g.add((pr, CL.caseUID, Literal(c["uid"])))
            g.add((pr, CL.firstRegisteredAt, code_court(c["uid"][:8])))
            g.add((cn, CL.registrationOf, pr))
        if c["received"]:
            g.add((cn, CL.registeredOn, Literal(c["received"], datatype=XSD.date)))
        if c["decided"]:
            g.add((cn, CL.decidedOn, Literal(c["decided"], datatype=XSD.date)))
        if c["result"]:
            g.add((cn, CL.resultText, Literal(c["result"], lang="ru")))
        g.add((cn, CL.hasOutcome, iri(D, "outcome", c["outcome"] or "pending")))
        if c["asof"]:
            g.add((cn, CL.outcomeAsOf, Literal(c["asof"], datatype=XSD.dateTime)))
        g.add((cn, CL.defendantCount, Literal(c["n_def"] or 1, datatype=XSD.nonNegativeInteger)))
        cs = card.get((c["court_id"], c["docket_key"]))
        if cs and int(cs.get("people") or 0):
            for prop, col in ((CL.convictedCount, "guilty"), (CL.acquittedCount, "acquitted"),
                              (CL.dismissedCount, "dismissed"), (CL.undecidedCount, "pending")):
                g.add((cn, prop, Literal(int(cs.get(col) or 0), datatype=XSD.nonNegativeInteger)))
        if cs:
            for prop, col in ((CL.hearingDays, "hearing_days"), (CL.postponementCount, "postponed"),
                              (CL.custodyDecisionCount, "custody_decisions"),
                              (CL.custodyExtensionCount, "custody_extensions")):
                g.add((cn, prop, Literal(int(cs.get(col) or 0), datatype=XSD.nonNegativeInteger)))
            for prop, col in ((CL.minutesToJudge, "minutes_to_judge"), (CL.daysToSentence, "days_to_sentence")):
                if str(cs.get(col, "")).lstrip("-").isdigit():
                    g.add((cn, prop, Literal(int(cs[col]), datatype=XSD.integer)))
            if cs.get("sentence_date"):
                g.add((cn, CL.singleHearingTrial, Literal(cs.get("single_hearing_trial") == "1")))
            if cs.get("single_judge") in ("0", "1"):
                g.add((cn, CL.consideredBySingleJudge, Literal(cs["single_judge"] == "1")))
            if cs.get("card_sha256"):
                c["sources"][cs["card_sha256"]] = (cs["card_url"], cs.get("fetched_at", ""))
        for a_ in c["rec_arts"]:
            g.add((cn, CL.recordedArticle, article(a_))); g.add((cn, CL.mentionsArticle, article(a_)))
        for a_ in c["court_arts"]:
            g.add((cn, CL.courtListedArticle, article(a_))); g.add((cn, CL.mentionsArticle, article(a_)))
        pn = post_node(c["court_id"], c["judge"], c["decided"] or c["received"]) if c["judge"] else None
        if pn:
            g.add((cn, CL.cardJudge, pn))
        for sha, (url, ts) in c["sources"].items():
            s_ = iri(D, "source", sha)
            g.add((s_, RDF.type, CL.SourceDocument)); g.add((s_, CL.sha256, Literal(sha)))
            g.add((s_, PROV.atLocation, URIRef(url)))
            if ts:
                g.add((s_, PROV.generatedAtTime, Literal(ts, datatype=XSD.dateTime)))
            g.add((cn, PROV.wasDerivedFrom, s_))
        if key in groups:
            kn = iri(D, "cluster", groups[key])
            g.add((kn, RDF.type, CL.CoRegistrationCluster)); g.add((kn, PROV.wasGeneratedBy, rule_node))
            g.add((cn, CL.inCluster, kn))
        for rid, (rule, conf) in c["records"].items():
            rn, ln = OVD[rid], iri(D, "link", rid, c["court_id"], c["docket_key"])
            g.add((rn, RDF.type, CL.PersecutionRecord))
            g.add((ln, RDF.type, CL.RecordRegistrationLink)); g.add((ln, CL.linksRecord, rn)); g.add((ln, CL.linksRegistration, cn))
            rule_n = iri(D, "rule", rule)
            g.add((rule_n, RDF.type, CL.MatchingRule)); g.add((rule_n, RDFS.label, Literal(rule)))
            g.add((ln, CL.matchedBy, rule_n)); g.add((ln, CL.confidence, Literal(conf)))
            g.add((rn, CL.concernsRegistration, cn))  # materialised property chain, for stores without OWL RL
            n_links += 1
    for jid, ds in post_dates.items():
        ds = sorted(d for d in ds if d)
        if ds:
            g.add((posts[jid], CL.firstObserved, Literal(ds[0], datatype=XSD.date)))
            g.add((posts[jid], CL.lastObserved, Literal(ds[-1], datatype=XSD.date)))
    n_same = 0
    for pk, nodes in person.items():
        nodes = sorted(nodes)
        for i, x in enumerate(nodes):
            for y in nodes[i + 1:]:
                g.add((x, CL.possiblySameAs, y)); g.add((y, CL.possiblySameAs, x)); n_same += 1
    # one cluster table for every downstream product (workbook, report)
    write_csv(out_dir / "clusters.csv",
              [{"court_id": k[0], "srv": k[1], "docket_key": k[2], "cluster_id": v} for k, v in sorted(groups.items())],
              ["court_id", "srv", "docket_key", "cluster_id"])

    data = out_dir / "courtlink-data.ttl"
    g.serialize(data, format="turtle")
    LOG.info("wrote %s: %d triples | registrations %d (OVD-linked %d) in %d proceedings | judicial posts %d | "
             "courts holding registrations %d | co-registration clusters %d | record links %d | possible same-person pairs %d",
             data, len(g), len(cases), sum(1 for c in cases.values() if c["records"]), len(proceedings), len(posts),
             len(set(g.objects(None, CL.heldAt))), len(set(groups.values())), n_links, n_same)
    try:
        from pyshacl import validate
        ont = Graph().parse(out_dir / "courtlink.ttl")
        conforms, _, text = validate(g, shacl_graph=Graph().parse(here / "shapes.ttl"), ont_graph=ont, inference="rdfs")
        (out_dir / "shacl-report.txt").write_text(text, "utf-8")
        LOG.info("SHACL: %s (report: %s)", "conforms" if conforms else "VIOLATIONS", out_dir / "shacl-report.txt")
    except ImportError:
        LOG.info("pyshacl not installed; skipping validation (pip install pyshacl)")


if __name__ == "__main__":
    main()
