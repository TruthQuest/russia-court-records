#!/usr/bin/env python3
"""OWL + SWRL inference over the joined graph with owlready2 and Pellet.

    python graph/reason.py

Reads   work/graph/joined.nt (from build_joined.py)
Writes  work/graph/inferred.ttl     only the triples the reasoner added
        work/graph/rules.owl        the inference ontology (axioms + SWRL), loadable in Protege

Reasoning runs on a focused module of the joined graph: the court layer, the bridge, every persecution in an
OVD-Info criminal case that has at least one linked court registration (so co-defendants are in scope), and the
article concepts. Your full graph stays in rdflib for querying; the inferred triples are merged back at query time.

What the reasoner derives
  Property chains
    cl:caseRegistration     CriminalCase -> CourtRegistration   = inverse(partOfCase) o hasCourtRegistration
    cl:sameOVDCaseAs        Registration -> Registration         = inverse(hasCourtRegistration) o partOfCase o caseRegistration
    cl:trialRegion          Persecution  -> Region               = hasCourtRegistration o heldAt o inRegion
  Precomputed (deterministic; asserted before Pellet runs, because as a SWRL rule Pellet's rule engine joins every
  pair of registrations at a court before testing the docket distance, which exhausts memory at census scale)
    cl:coRegisteredWith     same court, docket prefix and year, docket numbers 1..5 apart, a shared article
                            (symmetric only: NOT transitive. A transitive closure of a windowed rule chains without bound
                            and would absorb a busy court's whole docket series; runs are read from direct links in query 02)
  SWRL
    cl:LongPreTrialInterval registration whose docket year is >= 2 years after its proceeding's UID year. The UID is
                            assigned when the first material reaches a court (often an investigator's custody or search
                            request), so this interval is mostly the investigation, not the court phase
  Defined classes (owl:equivalentClass)
    cl:FaciallyIncompatibleApplication = CourtRegistration and mentionsArticle some FaciallyIncompatibleArticle
    cl:PostApplyingIncompatibleArticle = JudicialPost and inverse(cardJudge) some FaciallyIncompatibleApplication
    cl:MilitaryForumRegistration       = CourtRegistration and heldAt some MilitaryDistrictCourt
    cl:InterimResultRegistration       = CourtRegistration and hasOutcome some InterimResult
  Not here: cl:DetainedWithoutTerminalResult needs closed-world negation ("no registration of the same case UID, at any
  court, has a terminal result"), which OWL's open world cannot express; it is computed in graph/closed/ after inference.

Requires Java for Pellet (macOS: `brew install openjdk`). Without Java the script stops and says so; the SPARQL
CONSTRUCT versions of the same rules in graph/rules/*.rq are used by run_queries.py as a fallback.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from courtlink.common import load_config  # noqa: E402

CLS = "https://traceoriginresearch.com/ontology/courtlink#"
O = "http://repressions.russia/ontology/"
RFCC = "http://repressions.russia/vocab/rf-criminal-code/"


def focused_module(g: Graph) -> Graph:
    """Court layer + bridge + persecutions in linked OVD-Info cases + articles + schema."""
    m = Graph()
    linked = set(g.subjects(URIRef(CLS + "hasCourtRegistration"), None))
    cases = {c for p in linked for c in g.objects(p, URIRef(O + "partOfCase"))}
    pers = set(linked) | {p for c in cases for p in g.subjects(URIRef(O + "partOfCase"), c)}
    keep_subjects = pers | cases
    for s, p, o in g:
        ss = str(s)
        if ss.startswith(("https://traceoriginresearch.com/", RFCC)) or s in keep_subjects or ss.startswith(O):
            if s in keep_subjects and str(p) not in (O + "partOfCase", O + "isImprisoned", CLS + "hasCourtRegistration",
                                                    CLS + "recordRegion", str(RDF.type)):
                continue  # persons' and persecutions' other fields are not needed for reasoning
            m.add((s, p, o))
    # drop axioms Pellet 2.3 cannot load from the base ontology: the anonymous-inverse property chain behind
    # cl:concernsRegistration (already materialised in the data) and owl:hasKey (identity is enforced by SHACL)
    for p in ("http://www.w3.org/2002/07/owl#propertyChainAxiom", "http://www.w3.org/2002/07/owl#hasKey"):
        for s, o in list(m.subject_objects(URIRef(p))):
            m.remove((s, URIRef(p), o))
    return m


def co_registered(m: Graph, max_gap: int = 5) -> int:
    """Assert cl:coRegisteredWith both ways: same court, docket prefix and year, docket numbers 1..max_gap apart, a
    shared article. Sorted per (court, prefix, year), so each registration is compared only with its near neighbours."""
    P = lambda n: URIRef(CLS + n)  # noqa: E731
    groups = {}
    for r in m.subjects(RDF.type, P("CourtRegistration")):
        c, pre, yr, seq = (m.value(r, P("heldAt")), m.value(r, P("docketPrefix")), m.value(r, P("docketYear")),
                           m.value(r, P("docketSeq")))
        if None in (c, pre, yr, seq):
            continue
        groups.setdefault((c, str(pre), int(yr)), []).append((int(seq), r, set(m.objects(r, P("mentionsArticle")))))
    n = 0
    for items in groups.values():
        items.sort(key=lambda x: x[0])
        for i, (s1, a, arts_a) in enumerate(items):
            for s2, b, arts_b in items[i + 1:]:
                if s2 - s1 > max_gap:
                    break
                if s2 > s1 and arts_a & arts_b:
                    m.add((a, P("coRegisteredWith"), b)); m.add((b, P("coRegisteredWith"), a)); n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--java-memory", type=int, default=6000, help="Pellet heap in MB (default 6000)")
    a = ap.parse_args()
    cfg = load_config(a.config)
    gdir = Path(cfg["_work"]) / "graph"
    if not shutil.which("java"):
        sys.exit("Pellet needs Java. Install it (macOS: brew install openjdk) and rerun, or skip this step: "
                 "run_queries.py falls back to the SPARQL versions of the rules in graph/rules/.")
    import owlready2 as ow
    import owlready2.reasoning
    owlready2.reasoning.JAVA_MEMORY = a.java_memory
    from owlready2 import (DataProperty, FunctionalProperty, Imp, Inverse, ObjectProperty, PropertyChain,
                           SymmetricProperty, Thing, sync_reasoner_pellet)

    g = Graph(); g.parse(gdir / "joined.nt", format="nt")
    mod = focused_module(g)
    n_co = co_registered(mod)
    co_links = list(mod.subject_objects(URIRef(CLS + "coRegisteredWith")))
    print(f"co-registration links: {n_co} pairs (precomputed)")
    tmp = Path(tempfile.mkdtemp()) / "module.nt"
    mod.serialize(tmp, format="nt", encoding="utf-8")
    print(f"focused module: {len(mod)} triples of {len(g)}")

    world = ow.World()
    base = world.get_ontology(f"file://{tmp}").load(format="ntriples")
    before = set(world.as_rdflib_graph())
    rules = world.get_ontology("https://traceoriginresearch.com/ontology/courtlink-inference")
    cl = rules.get_namespace(CLS)
    o = rules.get_namespace(O)

    with rules:
        # declarations for bridge properties (typed so owlready2 and Pellet treat them correctly)
        class hasCourtRegistration(ObjectProperty): namespace = cl
        class recordRegion(ObjectProperty): namespace = cl
        class documents(ObjectProperty): namespace = cl
        class docketSeq(DataProperty): namespace = cl; range = [int]
        class docketYear(DataProperty): namespace = cl; range = [int]
        class decidedYear(DataProperty): namespace = cl; range = [int]
        class uidYear(DataProperty): namespace = cl; range = [int]
        class docketPrefix(DataProperty): namespace = cl; range = [str]
        class partOfCase(ObjectProperty): namespace = o
        class isImprisoned(DataProperty): namespace = o; range = [bool]
        CourtRegistration, JudicialPost = cl.CourtRegistration, cl.JudicialPost
        heldAt, inRegion, cardJudge, hasOutcome = cl.heldAt, cl.inRegion, cl.cardJudge, cl.hasOutcome
        mentionsArticle, registrationOf, isTerminal = cl.mentionsArticle, cl.registrationOf, cl.isTerminal

        class FaciallyIncompatibleArticle(Thing): namespace = cl
        class InterimResult(Thing): namespace = cl
        class LongPreTrialInterval(Thing): namespace = cl

        # named inverses (owlready2 serialises chains over named properties reliably)
        class casePersecution(ObjectProperty):
            namespace = cl
            inverse_property = partOfCase

        class registrationOfPersecution(ObjectProperty):
            namespace = cl
            inverse_property = hasCourtRegistration

        class judgedRegistration(ObjectProperty):
            namespace = cl
            inverse_property = cardJudge

        class caseRegistration(ObjectProperty):
            namespace = cl
            property_chain = [PropertyChain([casePersecution, hasCourtRegistration])]

        class sameOVDCaseAs(ObjectProperty):
            namespace = cl
            property_chain = [PropertyChain([registrationOfPersecution, partOfCase, caseRegistration])]

        class trialRegion(ObjectProperty):
            namespace = cl
            property_chain = [PropertyChain([hasCourtRegistration, heldAt, inRegion])]

        class coRegisteredWith(ObjectProperty, SymmetricProperty):
            namespace = cl

        class FaciallyIncompatibleApplication(Thing):
            namespace = cl
            equivalent_to = [CourtRegistration & mentionsArticle.some(FaciallyIncompatibleArticle)]

        class PostApplyingIncompatibleArticle(Thing):
            namespace = cl
            equivalent_to = [JudicialPost & judgedRegistration.some(FaciallyIncompatibleApplication)]

        class MilitaryForumRegistration(Thing):
            namespace = cl
            equivalent_to = [CourtRegistration & heldAt.some(cl.MilitaryDistrictCourt)]

        class InterimResultRegistration(Thing):
            namespace = cl
            equivalent_to = [CourtRegistration & hasOutcome.some(InterimResult)]

        # interim results: outcome concepts flagged isTerminal false
        for c in world.search(is_a=world["http://www.w3.org/2004/02/skos/core#Concept"]):
            if False in list(getattr(c, "isTerminal", []) or []):
                c.is_a.append(InterimResult)

        Imp().set_as_rule(
            "CourtRegistration(?r), registrationOf(?r, ?p), uidYear(?p, ?u), docketYear(?r, ?d), "
            "subtract(?g, ?d, ?u), greaterThanOrEqual(?g, 2) -> LongPreTrialInterval(?r)", namespaces=[cl, o])

    rules.save(file=str(gdir / "rules.owl"), format="rdfxml")
    print("running Pellet ...")
    with rules:
        sync_reasoner_pellet(world, infer_property_values=True, infer_data_property_values=False, debug=0)
    after = set(world.as_rdflib_graph())
    new = Graph()
    new.bind("cl", CLS)
    for a_, b_ in co_links:  # precomputed before Pellet, so not in (after - before): written out explicitly
        new.add((a_, URIRef(CLS + "coRegisteredWith"), b_))
    for t in after - before:
        s, p, o_ = t
        if str(p).startswith(CLS) or (str(p) == str(RDF.type) and str(o_).startswith(CLS)):
            new.add(t)
    new.serialize(gdir / "inferred.ttl", format="turtle")
    counts = {}
    for s, p, o_ in new:
        k = str(o_).split("#")[-1] if str(p) == str(RDF.type) else str(p).split("#")[-1]
        counts[k] = counts.get(k, 0) + 1
    print(f"inferred {len(new)} triples -> {gdir / 'inferred.ttl'}")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {v:6d}  {k}")


if __name__ == "__main__":
    main()
