# Your persecution graph + the court layer, with OWL/SWRL inference

```
python graph/build_joined.py --merged /path/to/russia_persecutions_merged.ttl
python graph/reason.py
python graph/run_queries.py
python graph/run_queries.py --sparql my_query.rq
```

1. **build_joined.py** joins your graph with `work/kg/courtlink-data.ttl` and writes only bridge triples (`work/graph/bridge.ttl`):
   `rd:persecution-recX cl:hasCourtRegistration <registration>`, the record region, article links to your `rfcc:` concepts,
   classes from your `:facialCharacter` annotation, and integer docket/UID fields for SWRL arithmetic. Nothing in your graph is changed.
2. **reason.py** (owlready2 + Pellet) reasons over a focused module (court layer, bridge, every persecution in an OVD-Info case that
   has a linked registration, articles) and writes only what it inferred to `work/graph/inferred.ttl`; the inference ontology
   with its axioms and SWRL rules is saved as `work/graph/rules.owl` (opens in Protege).
   - property chains: `cl:caseRegistration` (case -> registration), `cl:sameOVDCaseAs`, `cl:trialRegion`
   - SWRL: `cl:coRegisteredWith` (symmetric, not transitive: a windowed rule closed transitively chains without bound), `cl:LongPreTrialInterval` (UID year to docket year; mostly the investigation)
   - defined classes: `FaciallyIncompatibleApplication`, `PostApplyingIncompatibleArticle`, `MilitaryForumRegistration`,
     `InterimResultRegistration`
   - closed-world, after inference (`graph/closed/`): `DetainedWithoutTerminalResult`, which follows the case UID across courts
   Needs Java 11 to 21 with owlready2 0.47 (`brew install openjdk@21`). Without Java, run_queries.py uses the SPARQL versions in `graph/rules/`.
3. **run_queries.py** runs `graph/queries/*.rq` over joined + inferred, writes CSVs to `work/graph/results/` and an aggregate
   summary to `work/graph/findings.md`.

Two things learned while building this: Pellet 2.3 does not know `rdf:langString`, so a range declared with it makes the
ontology inconsistent (CourtLink 0.3 no longer declares one); and an anonymous inverse inside a property chain is rejected,
so the chains use named inverse properties.

Privacy: results CSVs for queries 01, 03 and 07 carry OVD-Info case or persecution IRIs and case labels that contain names. `work/` stays private.


## Pointing at your ontology folder

`--merged` takes files or a folder. Given `scripts/ontology/`, it loads the merged file plus anything not already in it
(today: `sdg_skos_extension.ttl`), and skips the tbox, abox and criminal-code SKOS files because the merged file contains
them (verified: the only triples they add are two `dcterms:created` dates). Query 11 needs the SDG extension.

## Known modelling limits (October 2026 review)

- `:facialCharacter "facially_incompatible"` is a normative assessment attached to a timeless article. It should attach to an
  article *version* (207.3, 280.3, 280.4 and 284.1 were amended 2022-2024) as a `prov:Entity` attributed to its assessor, and use
  the ICCPR art. 19(3) test (legality, legitimate aim, necessity, proportionality), not the US facial/as-applied distinction.
- `cl:cardJudge` links a registration to the judge the card names: the judge, or the presiding judge of a panel. It is a role in a
  proceeding, not individual responsibility; counts per post measure presiding frequency.
- `cl:trialRegion` gives a court's seat region. A district military court's competence covers several regions, so "tried outside
  the region" is expected for its cases by construction.
