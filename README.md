# courtlink

**Linking Russia's political prosecutions to the courts and judges that hear them, using the courts' own public records.**

courtlink takes the people documented by [OVD-Info](https://ovd.info/) as politically prosecuted in Russia, finds their cases in the courts' own public case records, and links each case to the court that heard it, the presiding judge, the outcome and every recorded step. It then checks the judges against international sanctions lists and builds everything into a knowledge graph that can be queried and tested as a whole.

It is the pipeline behind **No Way Out**, a Trace Origin report published in October 2026:

> [No Way Out: How Russia's Courts Convict Almost Everyone Charged for Speaking Against the War](https://www.traceoriginresearch.com/no-way-out-how-russias-courts-convict-almost-everyone-charged-for-speaking-against-the-war/)

This public repository holds the method: the matching, the knowledge graph and its ontology, the analyses, and tests on synthetic data. It holds **no data about any defendant**, and **not the code that collects data from the court websites**, which is available on request (see [Getting the data-collection code](#getting-the-data-collection-code)).

---

## Contents

1. [The question](#the-question)
2. [Where the data comes from](#where-the-data-comes-from)
3. [How it works](#how-it-works)
4. [The knowledge graph](#the-knowledge-graph)
5. [Analyses](#analyses)
6. [What it found](#what-it-found)
7. [Privacy and ethics](#privacy-and-ethics)
8. [Running it](#running-it)
9. [Getting the data-collection code](#getting-the-data-collection-code)
10. [Repository layout](#repository-layout)
11. [Limits](#limits)
12. [Credits, licences and citation](#credits-licences-and-citation) (licence: human rights, non-commercial)

---

## The question

OVD-Info has documented thousands of people prosecuted in Russia for what they said, wrote or believed. Its records say who was charged, under which article and what happened to them. They rarely say **which judge** decided the case, and they cannot say what the courts handle that OVD-Info has not yet heard about.

Russian courts publish that information themselves. Every court of general jurisdiction keeps a public page for each case: the case identifier, the presiding judge, every hearing, every custody decision and the result for each defendant. courtlink reads those pages at scale and joins them to OVD-Info's records, so that each documented person can be linked to their court case and to the judge who presided.

## Where the data comes from

| Source | What it provides | In this repository? |
|---|---|---|
| **Court websites in the sudrf.ru system** (GAS "Pravosudie") | One public case page per case: case identifier (УИД), docket number, presiding judge, events, outcome per defendant | No. Pages are fetched at run time and cached locally in `work/` |
| **Court directory** by Dataout ([sudrfparser](https://github.com/dataout-org/sudrfparser), November 2023, CC BY-SA 4.0) | The website of each of about 2,300 courts, by region | Yes, in `courts_info/` (with attribution in `courts_info/NOTICE.md`) |
| **OVD-Info export** | The people, articles, dates and docket numbers to be matched | No. Supplied by OVD-Info under agreement; never redistributed |
| **OpenSanctions** ([targets.simple.csv](https://www.opensanctions.org/datasets/default/)) | Consolidated EU, UK, US, Ukrainian and other sanctions lists | No. Downloaded at run time; a synthetic sample is in `tests/fixtures/` |

Moscow's courts publish on a separate system (mos-gorsud.ru) and are handled by a separate, smaller path. Magistrate courts and courts in occupied territories are outside the main search.

## How it works

The pipeline runs in two phases. Phase 1 starts from OVD-Info's records and looks for each one in the courts. Phase 2 turns the other way: it lists **every** case the courts register under the relevant articles, so that OVD-Info's records can be measured against the courts' own total.

```
OVD-Info records ──► candidate courts ──► court searches ──► matches ──► case pages ──► judges ──► sanctions
                                               ▲                              │
court directory (Dataout) ─────────────────────┘                              ▼
                                                               knowledge graph (RDF, OWL, SHACL)
court census (every case under the articles) ─────────────────────────────────┘        │
                                                                                         ▼
                                                     analyses: outcomes, custody, batches, recorded sequences,
                                                     judge concentration, sanctions, OVD-Info coverage
```

Steps marked &#8224; collect data from the court websites. Their code is not in this public repository; it is available on request.

### Phase 1: from OVD-Info's records to court cases

| Step | Script | What it does |
|---|---|---|
| 0 | `00_prepare_cases.py` | Parses OVD-Info's export: docket numbers (including earlier numbers in brackets), dates, articles, region codes, courts named in the narrative |
| 1 | `01_build_court_directory.py` &#8224; | Builds the court directory from the bundled Dataout list. Each court's code (for example `66OV0001`) is also the prefix of every case identifier it issues |
| 2 | `02_candidate_courts.py` | Ranks the courts likely to hold each case. Article 31 of the Code of Criminal Procedure sends terrorism offences, including 205.2, to the district military courts, so those articles route there |
| 3 | `sweep.py` (preferred), `03_search.py` &#8224; | Searches each court's case list by article and registration year, follows every result page, and matches dockets locally. One search per court instead of one per person keeps the load on the courts low |
| 4 | `04_match.py` | Scores each candidate on docket, surname (Cyrillic transliterated and fuzzy-matched), decision date and article, then decides by explicit rules R1 to R7. Every decision records its rule and confidence |
| 5 | `05_fetch_cards.py` &#8224; | Downloads each matched case page, saves it with its retrieval time and a SHA-256 checksum, and extracts the judge, the case identifier and the decision date |
| 6 | `06_judges.py` | Builds judges and judge-to-case links. A judge is identified per court; the same name at two courts is flagged as a possible match, never merged |
| 7 | `07_sanctions_match.py` | Compares judges with OpenSanctions entries: surname blocking, initials and patronymic checks, and a flag when the listing describes a judge. Nothing is asserted automatically |
| 8 | `08_manual.py`, `review.py` | Sheets for manual lookup and for reviewing uncertain matches |
| 9 | `09_export_ttl.py` | Exports the judicial layer as RDF, with provenance for every statement |

### Phase 2: the court census

| Script | What it does |
|---|---|
| `census_sweep.py` &#8224; | Lists every registration at every district and regional court in the census regions under the five articles used only against expression and protest (207.3, 280.3, 280.4, 284.1, 354.1), and every case at every district military court under the articles in scope |
| `census.py` | Parses every cached results page into a census of cases. Writes defendant counts, never names |
| `census_cards.py` &#8224; | Fetches the case page for every census registration, so one case refiled at another court is counted once, by its identifier |
| `card_details.py` | Extracts every event (hearings, postponements, custody decisions, sentence) and the outcome for each defendant. Writes no defendant, lawyer or victim names |
| `coverage_gap.py` | Measures what share of the court's defendants OVD-Info has a record for, by article, year and region |

### Matching rules

Docket numbers are unique only within a court, so a docket alone is never enough. Each candidate is scored, then decided by the first rule that applies:

| Rule | Evidence | Confidence |
|---|---|---|
| exclusions | different article; a different named defendant | reject |
| R1 | docket + surname (similarity 90 or more) | high |
| R2 | docket + article + decision within 7 days of OVD-Info's date | high |
| R3 | docket + decision within 7 days | high |
| R4 | docket + weaker surname match | medium |
| R5 | docket + article | medium |
| R6 | docket only | low |
| R7 | no docket: surname 90 or more, plus article and/or date | high or medium |

Weights and thresholds live in `config.yaml` (`matching:`). `precision_sample.py` draws a random sample of links for hand-checking and reports precision with a Wilson interval.

## The knowledge graph

The graph is the analytical core. It is built with `kg_build.py` against the CourtLink ontology in `kg/courtlink.ttl` and validated with SHACL shapes in `kg/shapes.ttl`.

Design choices that matter:

- **The court case is the hub.** A case is identified by its case identifier (УИД), which the court assigns when the first material arrives and which follows the case when it is sent to another court or returned and refiled. Each court registration (docket number) is a separate entity linked to the case.
- **Records and cases are linked, not merged.** The link from an OVD-Info record to a court case is reified, carrying the matching rule and confidence.
- **Judges are posts, not people.** A judge at a court is a dated membership (`org:Membership`). The same name at another court is `cl:possiblySameAs`, never `owl:sameAs`.
- **Provenance everywhere.** Every case cites the saved source page (`prov:wasDerivedFrom`) with its checksum and retrieval time.
- **Results are dated and typed.** Every outcome carries the date it was observed (`outcomeAsOf`) and is classed as terminal (verdict, dismissal, compulsory medical measures) or interim (returned to the prosecutor, transferred, pending).
- **Two kinds of article.** The article OVD-Info records and the article the court lists are kept apart, so disagreements stay visible.

`graph/` joins the court layer to the wider OVD-Info persecution graph and reasons over it with OWL 2 and Pellet (through owlready2):

- property chains such as `cl:caseRegistration` and `cl:sameOVDCaseAs`;
- `cl:coRegisteredWith`, symmetric but deliberately not transitive, computed in Python because a windowed rule closed transitively chains without bound;
- defined classes for registrations at military courts and interim results;
- a closed-world step, run after inference, for people with no recorded final result (`graph/closed/`).

Queries are portable SPARQL 1.1 in `kg/queries/` and `graph/queries/`.

## Analyses

| Script | Question | Method |
|---|---|---|
| `kg_analytics.py` | Are cases concentrated among a few judges? | Concentration curves per court type; year-stratified Monte Carlo against each court's own assignment, Benjamini–Hochberg correction |
| `graph_analytics.py` | Were related cases handled as a group? Do some judges' records follow one pattern? | **Batches:** a scan over windows of 20 consecutive case identifiers at a court with receipt within 45 days and a shared article, scored against random placement in the court's sequence, with Benjamini–Hochberg correction. **Recorded sequences:** each case reduced to its sequence of recorded events, then a permutation test (1,000 reassignments within court and article group) on the share of a judge's cases on one pattern |
| `gravity_check.py` | Is dismissal rare because the law forbids it, or because it is not used? | Outcomes by article part and gravity, single-charge defendants, compulsory medical measures, decision year, trials in absentia, and the recorded grounds of every dismissal |
| `coverage_gap.py` | How complete are OVD-Info's records? | Docket links plus a surname, initial, region, article and date check; name-match recall measured on docket-linked cases |
| `judge_dossier.py` | Who presides, and do they match a sanctions listing? | One row per judge per court: cases by article group, outcomes, custody extensions, time to sentence, sanctions candidates |
| `gap_acts.py` &#8224; | What are the cases OVD-Info does not have about? | Reads the published judgment, keeps only what the court established, and sorts it by topic. Writes no names and no judgment text |

Every analysis has a test in `tests/` that plants a known effect in synthetic data and checks the method finds it, and finds nothing in a null world.

## What it found

From 3,487 first-instance cases (every district military court nationally, plus district and regional courts in 23 regions), as of October 2026:

- **Almost no acquittals.** One acquittal among 2,302 decided defendants in the military courts; three among 547 in the district and regional courts.
- **Dismissal rarely recorded, even where the charge permits it.** 4 of 136 defendants charged only under the lesser parts of the anti-war articles had their case dismissed. Compulsory psychiatric measures were the commonest outcome other than conviction.
- **Expression charged as terrorism.** In 963 military-court registrations, article 205.2 (public calls to, or justification of, terrorism) is the only charge.
- **Judges and sanctions.** Nine judges match an EU listing that describes a judge, and 32 more share a full name with a person on Ukraine's sanctions register. All are unconfirmed leads. Most of the judges who preside over the most convictions match no list.
- **Gaps in the documentation.** Under article 280.4, 15 of 22 defendants the courts list had no OVD-Info record that could be found.

The report sets out what these findings do not establish, including that the comparison with national figures is not yet like for like. Read it before citing any number.

## Privacy and ethics

The people in these cases are at risk. The pipeline is built so that the analysis can be shared without exposing them.

- **No defendant data in this repository, ever.** Everything a run produces (cached court pages, matches, names, case links) goes to `work/`, which `.gitignore` excludes. `scripts/privacy_check.sh` blocks a commit or push that contains run outputs, an OVD-Info export, a sanctions dump, a workbook, a real case-page link, a real case identifier or a personal file path. Install it with `bash scripts/install_hooks.sh`.
- **Names are not written.** The census and case-detail steps write defendant counts and roles, never defendant, lawyer or victim names. Prosecutors and judges are recorded as public officials.
- **Published outputs omit anything that leads to a person.** The public report contains no case numbers or case-page links and suppresses small counts. A fuller workbook goes to OVD-Info only.
- **Captchas are solved by a person.** The collection code shows the captchas a run needs on one page for a human to type. The code never solves a captcha automatically.
- **Gentle on the courts.** One request at a time per court, a pause between requests, a cache so that no page is fetched twice, and a run that stops for a court that starts refusing requests.
- **No proxy without legal advice.** The fetcher can use a proxy, but routing requests through Russian infrastructure is a legal and security decision to take with a lawyer first.
- **Judges are named only from the courts' own records**, in their official capacity, and a name match with a sanctions list is reported as a lead, not an identification.
- **Collection code on request only.** Each copy goes to a named person or organisation, and each is marked so it can be traced.
- **Report misuse.** If you see this code used against people, tell us: see [SECURITY.md](SECURITY.md).

## Running it

Requirements: Python 3.11 or later (tested on 3.13); Java 11 to 21 for the OWL reasoning step (optional).

```bash
git clone https://github.com/TruthQuest/russia-court-records.git
cd russia-court-records
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash scripts/install_hooks.sh
```

The analysis and graph tests run on synthetic data, with no network:

```bash
python tests/check_analyses.py
python tests/check_graph_analytics.py
python tests/check_kg.py /tmp/courtlink-kg-test
python tests/check_card_detail.py
python tests/check_sentences.py
```

A live run needs OVD-Info's export, which is not public, and the data-collection code.

## Getting the data-collection code

The code that searches the court websites and downloads case pages, together with its end-to-end test and the full operating guide, is available to human rights organisations, journalists and researchers on request:

**ebrattin@traceoriginresearch.com**

Please say who you are, which organisation you work with, and what you want to use it for. Each copy is issued to a named person or organisation under the [licence](LICENSE.md). Keeping this part private makes it harder to use the tool to build databases of people, while everything needed to check the method stays public.

## Repository layout

```
00_…09_*.py            Phase 1 pipeline, in run order (collection steps 01, 03, 05 on request)
census.py              Phase 2 court census, from cached pages
card_details.py        events and outcomes from every case page
kg_build.py            builds and validates the knowledge graph
kg/                    ontology (courtlink.ttl), SHACL shapes, SPARQL queries
graph/                 join to the persecution graph, OWL reasoning, queries
kg_analytics.py        assignment and concentration analyses
graph_analytics.py     batch detection and recorded-sequence tests
gravity_check.py       outcomes by article part, dismissal grounds, trials in absentia
coverage_gap.py        OVD-Info coverage against the census
judge_dossier.py       one row per judge, with sanctions candidates
courtlink/             shared library: parsing, matching, dockets, regions, outcomes
courts_info/           court directory (Dataout, CC BY-SA 4.0)
tests/                 synthetic fixtures and tests (all people and judges invented)
scripts/               privacy check and git hooks
docs/                  the project website
SECURITY.md            how to report misuse
config.yaml            settings; values marked VERIFY need a live check first
```

## Limits

- **Records, not events.** A case page shows what the court's staff entered. A missing entry is not a hearing that did not happen, and a uniform record says nothing about how a trial was run.
- **Coverage.** Courts withhold some pages (closed hearings, state secrets) and some names. Moscow courts, magistrate courts and garrison military courts are outside the main search.
- **Identity.** A case identifier follows a case through transfers and refiling, but joinder and separation are not tracked.
- **Matching.** Links between OVD-Info records and court cases are automatic. Precision should be hand-checked on a sample before any figure is cited.
- **Sanctions.** Name matches are leads. EU listings must be confirmed against the Official Journal; Ukrainian register entries against the decree and date of birth.

## Credits, licences and citation

**Licence.** courtlink is released under the [courtlink Human Rights Non-Commercial License 1.0](LICENSE.md). In short: non-profit human rights organisations, human rights defenders and their lawyers, journalists, non-profit researchers and international human rights bodies may use, change and share it for human rights work. No one may use it to make money, and no one may use it to prosecute, surveil or target the people in these cases. This is not an open-source licence. For any other use, including commercial use, contact Trace Origin LLC.

- Court directory: Dataout, [sudrfparser](https://github.com/dataout-org/sudrfparser), CC BY-SA 4.0. See `courts_info/NOTICE.md`.
- Sanctions data: [OpenSanctions](https://www.opensanctions.org/), used under its licence terms and not redistributed here.
- Political prosecution records: [OVD-Info](https://ovd.info/), used with permission and not redistributed here.

Citation details are in [CITATION.cff](CITATION.cff).

Built by Eric Brattin, [Trace Origin LLC](https://www.traceoriginresearch.com/). Corrections and questions: ebrattin@traceoriginresearch.com.
