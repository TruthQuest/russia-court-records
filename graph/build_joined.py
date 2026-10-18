#!/usr/bin/env python3
"""Join your persecution graph with the CourtLink layer, and write the bridge between them.

    python graph/build_joined.py --merged ~/path/russia_persecutions_merged.ttl[.zip]
    python graph/build_joined.py --merged ~/path/ontology/          every .ttl/.ttl.zip in the folder (see load_inputs)

Reads   your merged graph (Persecution, CriminalCase, Person, rfcc articles with ICCPR annotations)
        work/kg/courtlink.ttl + work/kg/courtlink-data.ttl (from kg_build.py)
        work/cases.csv (record region), work/courts.csv
Writes  work/graph/bridge.ttl      only the new links between the two graphs
        work/graph/joined.nt       everything, ready for rdflib or for graph/reason.py

Bridge (all in the cl: namespace, nothing in your graph is modified):
  ovdrec:recX            cl:documents              rd:persecution-recx
  rd:persecution-recx    cl:hasCourtRegistration   <registration>
  rd:persecution-recx    cl:recordRegion           <region>            (OVD-Info's region, ISO code)
  <registration>         cl:mentionsArticle        rfcc:art_N          (so your ICCPR annotations apply)
  rfcc:art_N             a cl:FaciallyIncompatibleArticle | cl:AsAppliedArticle | cl:LegitimateWeaponizedArticle
  <registration>         cl:docketPrefix / docketSeq / docketYear / decidedYear   (for SWRL arithmetic)
  <proceeding>           cl:uidYear / cl:uidKind
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from courtlink.common import load_config, work_path  # noqa: E402

CL = Namespace("https://traceoriginresearch.com/ontology/courtlink#")
D = Namespace("https://traceoriginresearch.com/id/courtlink/")
OVDREC = Namespace("https://traceoriginresearch.com/id/ovd-record/")
O = Namespace("http://repressions.russia/ontology/")
RD = Namespace("http://repressions.russia/data/")
RFCC = Namespace("http://repressions.russia/vocab/rf-criminal-code/")
FACIAL = {"facially_incompatible": CL.FaciallyIncompatibleArticle, "as_applied": CL.AsAppliedArticle,
          "legitimate_weaponized": CL.LegitimateWeaponizedArticle}
DOCKET = re.compile(r"^(\d+(?:-\d+)?)-(\d+)/(\d{4})$")


PARTS_OF_MERGED = ("_tbox", "_abox", "criminal_code_skos")


def load_inputs(args: list[str]) -> list[Path]:
    """Expand folders; inside a folder that holds a *merged* file, skip the parts already in it (tbox, abox,
    criminal-code SKOS) and load everything else alongside it (e.g. sdg_skos_extension.ttl). A .ttl.zip is skipped
    when the unzipped .ttl sits next to it."""
    files: list[Path] = []
    for a in args:
        p = Path(a).expanduser()
        if not p.is_dir():
            files.append(p); continue
        found = sorted(f for f in p.iterdir() if f.name.endswith((".ttl", ".ttl.zip")) and not f.name.startswith("."))
        has_merged = any("merged" in f.name for f in found)
        for f in found:
            if f.name.endswith(".zip") and (f.with_suffix("")).exists():
                continue
            if has_merged and "merged" not in f.name and any(k in f.name for k in PARTS_OF_MERGED):
                print("skipping", f.name, "(already in the merged file)")
                continue
            files.append(f)
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config"); ap.add_argument("--merged", required=True, nargs="+",
                                                     help="your graph: one or more .ttl/.ttl.zip files, or a folder of them")
    a = ap.parse_args()
    cfg = load_config(a.config)
    kg = Path(cfg["_work"]) / "kg"
    out = Path(cfg["_work"]) / "graph"
    out.mkdir(parents=True, exist_ok=True)

    g = Graph()
    for f in load_inputs(a.merged):
        print("loading", f)
        if f.suffix == ".zip":  # read the .ttl straight out of the archive, no unzip needed
            import zipfile
            with zipfile.ZipFile(f) as z:
                name = next(n for n in z.namelist() if n.endswith(".ttl") and not n.startswith("__MACOSX"))
                g.parse(data=z.read(name).decode("utf-8"), format="turtle")
        else:
            g.parse(f, format="turtle")
    n_merged = len(g)
    for f in ("courtlink.ttl", "courtlink-data.ttl"):
        if not (kg / f).exists():
            raise SystemExit(f"{kg / f} not found. Run `python kg_build.py` first (it builds the court-side graph), then rerun this.")
        g.parse(kg / f)
    cases = {r["record_id"]: r for r in csv.DictReader(open(work_path(cfg, "cases.csv"), encoding="utf-8"))}

    b = Graph()
    for p, ns in (("cl", CL), ("rd", RD), ("rfcc", RFCC), ("ovdrec", OVDREC), ("o", O)):
        b.bind(p, ns)
    b.add((CL.FaciallyIncompatibleArticle, RDFS.subClassOf, CL.ClassifiedArticle))
    b.add((CL.AsAppliedArticle, RDFS.subClassOf, CL.ClassifiedArticle))
    b.add((CL.LegitimateWeaponizedArticle, RDFS.subClassOf, CL.ClassifiedArticle))
    # article classes from your ICCPR annotation
    for art, fc in g.subject_objects(O.facialCharacter):
        if str(fc) in FACIAL:
            b.add((art, RDF.type, FACIAL[str(fc)]))
    rfcc_by_notation = {str(n): s for s, n in g.subject_objects(O.articleNotation) if str(s).startswith(str(RFCC))}

    found = missing = 0
    for link in g.subjects(RDF.type, CL.RecordRegistrationLink):
        rec, reg = g.value(link, CL.linksRecord), g.value(link, CL.linksRegistration)
        rid = str(rec).rsplit("/", 1)[-1]
        pers = RD["persecution-" + rid.lower()]
        if (pers, RDF.type, O.Persecution) not in g:
            missing += 1
            continue
        found += 1
        b.add((rec, CL.documents, pers))
        b.add((pers, CL.hasCourtRegistration, reg))
        iso = (cases.get(rid, {}).get("iso") or "").split(",")[0].strip()
        if iso:
            b.add((pers, CL.recordRegion, D["region/" + iso]))
    for reg in set(g.subjects(RDF.type, CL.CourtRegistration)):
        for art in g.objects(reg, CL.mentionsArticle):
            n = str(g.value(art, URIRef("http://www.w3.org/2004/02/skos/core#notation")) or "")
            if n in rfcc_by_notation:
                b.add((reg, CL.mentionsArticle, rfcc_by_notation[n]))
        m = DOCKET.match(str(g.value(reg, CL.docketNumber) or "").strip())
        if m:
            b.add((reg, CL.docketPrefix, Literal(m.group(1))))
            b.add((reg, CL.docketSeq, Literal(int(m.group(2)), datatype=XSD.integer)))
            b.add((reg, CL.docketYear, Literal(int(m.group(3)), datatype=XSD.integer)))
        d = g.value(reg, CL.decidedOn)
        if d:
            b.add((reg, CL.decidedYear, Literal(int(str(d)[:4]), datatype=XSD.integer)))
    for p in set(g.subjects(RDF.type, CL.Proceeding)):
        uid = str(g.value(p, CL.caseUID) or "")
        if len(uid) >= 16:
            b.add((p, CL.uidKind, Literal(uid[9:11])))
            b.add((p, CL.uidYear, Literal(int(uid[12:16]), datatype=XSD.integer)))
    b.serialize(out / "bridge.ttl", format="turtle")
    g += b
    g.serialize(out / "joined.nt", format="nt", encoding="utf-8")
    print(f"your graph: {n_merged} triples | joined: {len(g)} | bridge: {len(b)} | "
          f"linked records found in your graph: {found}, not found: {missing}"
          + (" (records newer than your export)" if missing else ""))


if __name__ == "__main__":
    main()
