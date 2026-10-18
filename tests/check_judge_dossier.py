#!/usr/bin/env python3
"""Checks for judge_dossier.py on a small graph: registrations fold to cases by UID, speech/security split, moves
between courts via possiblySameAs, sanctioned vs PEP vs name-only matches.

    python tests/check_judge_dossier.py
"""
from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rdflib import Graph, Literal, Namespace  # noqa: E402
from rdflib.namespace import ORG, PROV, RDF, RDFS, SKOS, XSD  # noqa: E402

import judge_dossier as jd  # noqa: E402

CL, D = jd.CL, Namespace("https://traceoriginresearch.com/id/courtlink/")


def build() -> Graph:
    g = Graph()

    def art(a):
        n = D["article/" + a]; g.add((n, RDF.type, SKOS.Concept)); g.add((n, SKOS.notation, Literal(a))); return n

    def court(cid, cls, en):
        n = D["court/" + cid]; g.add((n, RDF.type, cls)); g.add((n, SKOS.prefLabel, Literal(en, lang="en"))); return n

    def post(pid, ct, ru, en, fam, ini):
        p, h = D["post/" + pid], D["person/" + pid]
        g.add((p, ORG.organization, ct)); g.add((p, ORG.member, h))
        g.add((p, RDFS.label, Literal(ru, lang="ru"))); g.add((p, SKOS.prefLabel, Literal(en, lang="en")))
        g.add((h, CL.familyName, Literal(fam, lang="ru"))); g.add((h, CL.initials, Literal(ini)))
        return p, h

    def reg(i, p, arts, out="verdict", uid=None, nd=1):
        n = D[f"reg/{i}"]
        g.add((n, CL.cardJudge, p)); g.add((n, CL.hasOutcome, D["outcome/" + out]))
        g.add((n, CL.defendantCount, Literal(nd, datatype=XSD.nonNegativeInteger)))
        for a in arts:
            g.add((n, CL.mentionsArticle, art(a)))
        if uid:
            g.add((n, CL.registrationOf, D["proceeding/" + uid]))
        g.add((n, PROV.wasDerivedFrom, D[f"source/{i}"]))

    c1, c2 = court("c1", CL.DistrictCourt, "Kirovsky District Court"), court("c2", CL.RegionalCourt, "Regional Court")
    p1, h1 = post("a", c1, "Иванов Иван Петрович", "Ivanov Ivan Petrovich", "Иванов", "И.П.")
    p2, h2 = post("b", c2, "Иванов И.П.", "Ivanov I.P.", "Иванов", "И.П.")
    p3, _ = post("c", c1, "Петров П.С.", "Petrov P.S.", "Петров", "П.С.")
    g.add((h1, CL.possiblySameAs, h2)); g.add((h2, CL.possiblySameAs, h1))
    reg(1, p1, ["207.3"], uid="U1"); reg(2, p1, ["207.3"], out="returned_to_prosecutor", uid="U1")
    reg(3, p1, ["205.2", "280.4"], nd=2); reg(4, p1, ["158"]); reg(5, p2, ["275"], out="pending"); reg(6, p3, ["280.3"])
    return g


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    return cond


def main() -> int:
    rows = {r["post_id"]: r for r in jd.collect(build())}
    a, b = rows["a"], rows["b"]
    ok = check("non-political registration ignored; UID folds two registrations", a["registrations"] == 3 and a["political_cases"] == 2)
    ok &= check("defendants summed per case", a["political_defendants"] == 3)
    ok &= check("groups: 205.2 apart from speech and security", a["speech_cases"] == 2 and a["terror_speech_cases"] == 1 and a["security_cases"] == 0 and b["security_cases"] == 1)
    ok &= check("move between courts shown", a["same_name_other_courts"] == "Regional Court")
    ok &= check("levels", a["court_level"] == "district" and b["court_level"] == "regional")
    ok &= check("ranked by cases", a["rank"] == 1)
    d = Path(tempfile.mkdtemp())
    with open(d / "t.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "schema", "name", "aliases", "countries", "dataset", "sanctions"])
        w.writeheader()
        w.writerow({"id": "S1", "schema": "Person", "name": "Иванов Иван Петрович", "countries": "ru",
                    "dataset": "EU", "sanctions": "EU: judge of the Kirovsky District Court"})
        w.writerow({"id": "P1", "schema": "Person", "name": "Петров Пётр Сергеевич", "countries": "ru",
                    "dataset": "PEP", "sanctions": "", "aliases": "судья районного суда"})
        w.writerow({"id": "X1", "schema": "Person", "name": "Иванов Сергей Петрович", "countries": "ru", "dataset": "x"})
        w.writerow({"id": "V1", "schema": "Person", "name": "Ivan Viacheslavovych IVANOV", "countries": "ru", "dataset": "EU",
                    "sanctions": "EU: judge of the Kirovsky District Court"})
        w.writerow({"id": "Y1", "schema": "Person", "name": "Viktor Ivanovich Yanuk", "countries": "ru", "dataset": "EU",
                    "sanctions": "EU: former president; court ruling"})
    lst = list(rows.values())
    jd.sanctions(lst, str(d / "t.csv"), 85)
    ok &= check("sanctioned judge named with this court", a["sanctions_status"].startswith("sanctioned: listing names") and "S1" in a["sanctions_entities"])
    ok &= check("PEP is not sanctions", rows["c"]["sanctions_status"].startswith("PEP"))
    ok &= check("different first initial rejected", "X1" not in a["sanctions_entities"])
    ok &= check("a patronymic is not read as a surname", "Y1" not in a["sanctions_entities"])
    ok &= check("Ukrainian patronymic read: Viacheslavovych is not Petrovich", "V1" not in a["sanctions_entities"])
    jd.write_md(lst, d / "m.md", True, 10)
    ok &= check("summary written", "Judges who tried" in (d / "m.md").read_text("utf-8"))
    print("all passed" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
