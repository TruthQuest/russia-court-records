#!/usr/bin/env python3
"""Who tried the political cases: one row per judge, from the knowledge graph, checked against sanctions lists.

    python kg_build.py                                   (the graph this reads: work/kg/courtlink-data.ttl)
    python judge_dossier.py                              ranking only
    python judge_dossier.py --os targets.simple.csv      ranking + sanctions/PEP check (OpenSanctions)

    OpenSanctions file (one download, large):
    curl -L -o targets.simple.csv https://data.opensanctions.org/datasets/latest/default/targets.simple.csv

For every judicial post (a judge at one court) the graph holds the registrations the court lists under that judge.
This counts, per post, the political registrations, folded to distinct cases (one case UID, else one co-registration
cluster, else one registration) and defendants; splits them into speech articles and terrorism/extremism/treason
articles (so a reader can tell a judge who tries anti-war posts from one who tries bombings); counts verdicts and
pending cases, OVD-Info-linked cases, and the archived court pages behind them; and follows cl:possiblySameAs to the
same surname and initials at other courts, which is how a judge's moves between courts show up.

Writes (all private: judges' names next to case counts, for OVD-Info and legal review, not for publication):
    work/analysis/judge_dossier.csv               every judge with at least one political case
    work/analysis/judge_dossier.md                summary and the top of the ranking
    work/analysis/judge_sanctions_candidates.csv  name matches to sanctions/PEP entries, for HUMAN REVIEW

"Sanctioned" means the OpenSanctions entry carries a sanctions listing; judges also appear on PEP lists, which are
not sanctions. A name match is not an identification: court pages give surname and initials, and many Russians share them. A
candidate counts as likely only when the listing itself mentions a court or the judiciary; confirm each one against
the listing's stated position before it goes anywhere.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import re
from pathlib import Path

from rapidfuzz import fuzz
from rdflib import Graph, Namespace
from rdflib.namespace import ORG, PROV, RDF, RDFS, SKOS

from courtlink.common import LOG, load_config, read_csv, setup_logging, work_path, write_csv
from courtlink.translit import skeleton
from kg_analytics import POLITICAL

CL = Namespace("https://traceoriginresearch.com/ontology/courtlink#")
# four groups, so a reader can tell anti-war posts from bombings; a case can fall in more than one
SPEECH = {"207.3", "280.3", "280.4", "284.1", "284.2", "330.1", "354.1", "280.1", "207.2", "148", "128.1", "329",
          "212.1", "280", "282"}  # expression, protest, 'foreign agent', undesirable organisations
TERROR_SPEECH = {"205.2"}  # 'justifying terrorism': anti-war posts and jihadist propaganda alike
ORGANISATION = {"282.1", "282.2", "282.3", "282.4"}  # 'extremist' organisations: Navalny's FBK, Jehovah's Witnesses, ...
SECURITY = set(POLITICAL) - SPEECH - TERROR_SPEECH - ORGANISATION  # terrorism acts, treason, espionage, 278, 279
LEVEL = {"MilitaryDistrictCourt": "military (district)", "GarrisonCourt": "military (garrison)",
         "RegionalCourt": "regional", "DistrictCourt": "district", "AppellateCourt": "appellate",
         "CassationCourt": "cassation"}
FIELDS = ["rank", "judge_ru", "judge_en", "court", "court_level", "region", "political_cases", "political_defendants",
          "speech_cases", "terror_speech_cases", "organisation_cases", "security_cases", "registrations", "verdicts", "pending", "ovd_linked_cases",
          "cases_with_card", "defendants_convicted", "defendants_acquitted", "defendants_dismissed",
          "custody_decisions", "custody_extensions", "postponements", "single_hearing_trials", "median_days_to_sentence",
          "median_minutes_to_judge", "top_articles", "first_seen", "last_seen", "same_name_other_courts", "archived_pages", "sanctions_status",
          "sanctions_entities", "post_id"]


CARD_PROPS = {"convicted": CL.convictedCount, "acquitted": CL.acquittedCount, "dismissed": CL.dismissedCount,
              "undecided": CL.undecidedCount, "hearing_days": CL.hearingDays, "postponed": CL.postponementCount,
              "custody": CL.custodyDecisionCount, "custody_ext": CL.custodyExtensionCount,
              "minutes_to_judge": CL.minutesToJudge, "days_to_sentence": CL.daysToSentence,
              "single_hearing": CL.singleHearingTrial}


def median(xs):
    xs = sorted(xs)
    if not xs:
        return ""
    m = xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2
    return int(m) if m == int(m) else round(m, 1)


def card_cols(cards: dict) -> dict:
    v = list(cards.values())
    tot = lambda k: sum(c.get(k, 0) for c in v)  # noqa: E731
    return {"cases_with_card": len(v), "defendants_convicted": tot("convicted"), "defendants_acquitted": tot("acquitted"),
            "defendants_dismissed": tot("dismissed"), "custody_decisions": tot("custody"),
            "custody_extensions": tot("custody_ext"), "postponements": tot("postponed"),
            "single_hearing_trials": tot("single_hearing"),
            "median_days_to_sentence": median([c["days_to_sentence"] for c in v if "days_to_sentence" in c]),
            "median_minutes_to_judge": median([c["minutes_to_judge"] for c in v if "minutes_to_judge" in c])}


def local(u) -> str:
    return str(u).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def label(g, n, lang):
    for o in g.objects(n, SKOS.prefLabel if lang == "en" else RDFS.label):
        if getattr(o, "language", None) == lang:
            return str(o)
    return ""


def collect(g: Graph) -> list[dict]:
    pol = set(POLITICAL)
    art_note = {a: str(n) for a in g.subjects(RDF.type, SKOS.Concept) for n in g.objects(a, SKOS.notation)}
    posts = collections.defaultdict(lambda: {"regs": set(), "cases": {}, "speech": set(), "security": set(),
                                             "terror_speech": set(), "organisation": set(),
                                             "verdicts": set(), "pending": set(), "linked": set(),
                                             "arts": collections.Counter(), "sources": set(), "card": {}})
    linked_regs = set(g.objects(None, CL.linksRegistration))
    for reg, post in g.subject_objects(CL.cardJudge):
        arts = {art_note.get(a, "") for a in g.objects(reg, CL.mentionsArticle)} & pol
        if not arts:
            continue
        p = posts[post]
        p["regs"].add(reg)
        case = (next(g.objects(reg, CL.registrationOf), None) or next(g.objects(reg, CL.inCluster), None) or reg)
        n_def = max((int(x) for x in g.objects(reg, CL.defendantCount)), default=1)
        p["cases"][case] = max(p["cases"].get(case, 0), n_def)
        if arts & SPEECH:
            p["speech"].add(case)
        if arts & SECURITY:
            p["security"].add(case)
        if arts & TERROR_SPEECH:
            p["terror_speech"].add(case)
        if arts & ORGANISATION:
            p["organisation"].add(case)
        out = local(next(g.objects(reg, CL.hasOutcome), "pending"))
        if out == "verdict":
            p["verdicts"].add(case)
        elif out == "pending":
            p["pending"].add(case)
        if reg in linked_regs:
            p["linked"].add(case)
        for a in arts:
            p["arts"][a] += 1
        p["sources"] |= set(g.objects(reg, PROV.wasDerivedFrom))
        cd = {k: int(v.toPython()) for k, prop in CARD_PROPS.items() for v in list(g.objects(reg, prop))[:1]}
        if cd:  # one case registered twice: keep the registration that carries more card detail
            old = p["card"].get(case, {})
            p["card"][case] = max(old, cd, key=lambda x: (x.get("convicted", 0) + x.get("acquitted", 0), len(x)))
    rows = []
    for post, p in posts.items():
        court = next(g.objects(post, ORG.organization), None)
        person = next(g.objects(post, ORG.member), None)
        types = {local(t) for t in g.objects(court, RDF.type)} if court is not None else set()
        region = next((str(n) for r in g.objects(court, CL.inRegion) for n in g.objects(r, SKOS.notation)), "")
        others = []
        for twin in g.objects(person, CL.possiblySameAs):
            for tp in g.subjects(ORG.member, twin):
                for tc in g.objects(tp, ORG.organization):
                    others.append(label(g, tc, "en") or local(tc))
        rows.append({
            "post_id": local(post), "judge_ru": label(g, post, "ru"), "judge_en": label(g, post, "en"),
            "_family": next((str(x) for x in g.objects(person, CL.familyName)), ""),
            "_initials": next((str(x) for x in g.objects(person, CL.initials)), ""),
            "court": label(g, court, "en") if court is not None else "",
            "court_level": next((LEVEL[t] for t in types if t in LEVEL), ""), "region": region,
            "political_cases": len(p["cases"]), "political_defendants": sum(p["cases"].values()),
            "speech_cases": len(p["speech"]), "terror_speech_cases": len(p["terror_speech"]),
            "organisation_cases": len(p["organisation"]), "security_cases": len(p["security"]), "registrations": len(p["regs"]),
            "verdicts": len(p["verdicts"]), "pending": len(p["pending"]), "ovd_linked_cases": len(p["linked"]),
            "top_articles": ", ".join(f"{a} ({n})" for a, n in p["arts"].most_common(4)),
            "first_seen": str(next(g.objects(post, CL.firstObserved), "")),
            "last_seen": str(next(g.objects(post, CL.lastObserved), "")),
            "same_name_other_courts": "; ".join(sorted(set(others))), "archived_pages": len(p["sources"]),
            "sanctions_status": "not checked", "sanctions_entities": "", **card_cols(p["card"])})
    rows.sort(key=lambda r: (-r["political_cases"], -r["political_defendants"], r["judge_en"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def load_matcher():
    p = Path(__file__).with_name("07_sanctions_match.py")
    spec = importlib.util.spec_from_file_location("sanctions_match", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


JUDGE_ROLE_RE = re.compile(r"\bjuge\b|\bjudge\b|\bсудь[яеи]\b|\bjuez\b|\brichter\b|presiding|président du tribunal", re.I)
GENERIC = {"district", "court", "city", "regional", "military", "of", "the", "st", "petersburg", "republic", "fleet",
           "oblastnoy", "sud", "krai", "territorial", "garrison", "inter-district"}
MILITARY_FR = {"western": "occidental", "southern": "sud", "central": "central", "eastern": "oriental",
               "northern": "nord", "pacific": "pacifique", "baltic": "baltique"}


def court_marks(court_en: str) -> list[set[str]]:
    """Distinctive words of a court name, each with the spellings a sanctions listing might use (EU listings are in
    French): 'Moskovsky' -> {'moskov'}, 'Southern' -> {'southe', 'sud'}. A listing names the court when it carries
    one spelling of each of the first two distinctive words."""
    out = []
    for w in re.findall(r"[A-Za-z]+", court_en):
        lw = w.lower()
        if lw in GENERIC or len(lw) < 4:
            continue
        out.append({lw[:6]} | ({MILITARY_FR[lw]} if lw in MILITARY_FR else set()))
    return out


# patronymic endings in the spellings sanctions lists use: Russian, Ukrainian ('Viacheslavovych'), Estonian
# ('Vladimirovitš'), French ('Vladimirovitch')
PATRONYMIC_ANY = re.compile(r"(vich|vna|ovna|evna|ichna|chna|ich|vych|ivna|yivna|vitš|vitsh|vitch|vytch|"
                            r"вич|вна|ична|чна|ич|ович|івна)$", re.I)


def sanctions(rows: list[dict], path: str, min_score: float) -> list[dict]:
    sm = load_matcher()
    sm.PATRONYMIC_RE = PATRONYMIC_ANY  # analyse() reads it from the module
    block = collections.defaultdict(list)
    n = 0
    for r in read_csv(path):
        if r.get("schema") != "Person":
            continue
        cs = (r.get("countries") or "").lower()
        if cs and "ru" not in cs.split(";"):
            continue
        n += 1
        for v in sm.name_variants(r):
            for sur, i1, i2, first in sm.analyse(v):
                sk = skeleton(sur)
                if PATRONYMIC_ANY.search(sur) and not sur.isupper():
                    continue  # a patronymic read as a surname ('Fedorovich' ~ 'Fedorova') is not a match
                if len(sk) >= 3:
                    block[sk[:3]].append((sk, i1, i2, first, v, r))
    LOG.info("sanctions/PEP persons indexed (Russia or no country): %d", n)
    cands = []
    for j in rows:
        jsk = skeleton(j["_family"])
        ini = [x for x in re.split(r"[.\s]+", j["_initials"]) if x]
        ji1, ji2 = (skeleton(ini[0])[:1] if ini else ""), (skeleton(ini[1])[:1] if len(ini) > 1 else "")
        toks = j["judge_ru"].split()
        jfirst = toks[1] if len(toks) == 3 and "." not in toks[1] else ""
        best = {}
        for sk, i1, i2, first, v, r in block.get(jsk[:3], []):
            s = fuzz.ratio(jsk, sk)
            if s < min_score:
                continue
            i1m = (i1 == ji1) if (i1 and ji1) else None
            i2m = (i2 == ji2) if (i2 and ji2) else None
            if i1m is False or i2m is False:
                continue
            score = s + (10 if i1m else 0) + (10 if i2m else 0)
            fr = fuzz.ratio(skeleton(jfirst), skeleton(first)) if (jfirst and first) else None
            if fr is not None:
                score += (fr - 80) / 4
            blob = " ".join(str(x) for x in r.values())
            jud = bool(JUDGE_ROLE_RE.search(blob))  # the listing describes a judge, not just any court mention
            marks = court_marks(j["court"])
            low = blob.lower()
            same_court = bool(marks) and all(any(v in low for v in alts) for alts in marks[:2])
            if r["id"] not in best or score > best[r["id"]]["score"]:
                best[r["id"]] = {"rank": j["rank"], "judge_ru": j["judge_ru"], "judge_en": j["judge_en"],
                                 "court": j["court"], "political_cases": j["political_cases"], "os_id": r["id"],
                                 "os_name": r.get("name", ""), "matched_variant": v, "score": round(score, 1),
                                 "first_initial_match": i1m, "patronymic_initial_match": i2m,
                                 "surname_ratio": round(s, 1), "first_name_ratio": "" if fr is None else round(fr),
                                 "listing_mentions_judiciary": jud,
                                 "listing_names_this_court": same_court, "birth_date": r.get("birth_date", ""),
                                 "datasets": r.get("dataset", "") or r.get("datasets", ""),
                                 "sanctions": (r.get("sanctions") or "")[:300], "sanctioned": bool(r.get("sanctions")),
                                 "os_url": f"https://www.opensanctions.org/entities/{r['id']}/",
                                 "review_decision": "", "review_note": ""}
        top = sorted(best.values(), key=lambda x: (-x["listing_names_this_court"], -x["listing_mentions_judiciary"],
                                                   -x["score"]))[:5]
        cands += top
        # strong: same surname, both initials agree (or the full first name), and the listing describes a judge
        strong = [c for c in top if c["listing_mentions_judiciary"] and c["surname_ratio"] >= 95 and c["first_initial_match"]
                  and c["patronymic_initial_match"] is not False
                  and (c["first_name_ratio"] == "" or c["first_name_ratio"] >= 80)]  # Eduard is not Evgeny
        court = [c for c in strong if c["listing_names_this_court"]]
        j["sanctions_status"] = ("sanctioned: listing names a judge of this court (check)" if any(c["sanctioned"] for c in court) else
                                 "sanctioned: a judge of this name (check)" if any(c["sanctioned"] for c in strong) else
                                 "PEP or other list: a judge of this name (check)" if strong else
                                 "name match only (check)" if top else "no match")
        likely = court or strong
        j["sanctions_entities"] = "; ".join(f"{c['os_name']} [{c['os_id']}]" for c in (likely or top)[:3])
    return cands


def gini(xs: list[int]) -> float:
    xs = sorted(xs)
    n, s = len(xs), sum(xs)
    if not n or not s:
        return 0.0
    return (2 * sum(i * x for i, x in enumerate(xs, 1)) / (n * s)) - (n + 1) / n


def write_md(rows, path: Path, checked: bool, top: int) -> None:
    tot = sum(r["political_cases"] for r in rows)
    k = max(1, len(rows) // 10)
    top10 = sum(r["political_cases"] for r in rows[:k])
    lvl = collections.Counter()
    for r in rows:
        lvl[r["court_level"] or "?"] += r["political_cases"]
    L = ["# Judges who tried the political cases (private working file)", "",
         f"- Judges (judge at one court) with at least one political case: **{len(rows)}**; political cases: **{tot}** "
         "(registrations folded to cases by case UID or co-registration cluster).",
         f"- The busiest tenth ({k} judges) presided over **{top10 / tot:.0%}** of the cases; Gini over judges "
         f"{gini([r['political_cases'] for r in rows]):.2f}. Concentration across the system, not within a court: "
         "large courts and military courts with many terrorism cases account for much of it.",
         "- Cases by court level: " + ", ".join(f"{k_} {v}" for k_, v in lvl.most_common()) + ".",
         "- Groups (a case can be in more than one): 'speech' = 207.3, 280.3, 280.4, 284.1/284.2, 330.1, 354.1, 280, 282 "
         "and other expression and protest articles; '205.2' = 'justifying terrorism', used both for anti-war posts and "
         "for jihadist propaganda, so it is shown on its own; 'organisation' = 282.1-282.4 ('extremist' organisations, "
         "including Navalny's FBK and Jehovah's Witnesses); 'security' = terrorism acts, treason, espionage (205, 205.1, "
         "205.3-205.5, 275, 275.1, 276, 278, 279). 319 (insulting an official) is not counted. 354.1 part 2 cases are "
         "mostly Holocaust denial and Nazi praise (see gap_acts.csv).",
         "- In panel courts (regional and military) the card names the presiding judge only.",
         "- Coverage: only the courts and searches in the census (19 regions plus the targeted OVD-Info sweeps).", ""]
    wc = [r for r in rows if r["cases_with_card"]]
    if wc:
        conv, acq = sum(r["defendants_convicted"] for r in wc), sum(r["defendants_acquitted"] for r in wc)
        L += [f"- Full case card read for {sum(r['cases_with_card'] for r in wc)} cases of {len(wc)} judges: "
              f"defendants convicted {conv}, acquitted {acq}, dismissed {sum(r['defendants_dismissed'] for r in wc)}; "
              f"custody extensions {sum(r['custody_extensions'] for r in wc)}; sentenced on the only hearing day: "
              f"{sum(r['single_hearing_trials'] for r in wc)} cases. Judges with at least 5 decided defendants and no "
              f"acquittal: {sum(1 for r in wc if r['defendants_acquitted'] == 0 and r['defendants_convicted'] >= 5)}.", ""]
    else:
        L += ["- Case cards not read in full yet (run census_cards.py, card_details.py, kg_build.py): convictions, "
              "acquittals, custody and speed columns are empty.", ""]
    if checked:
        st = collections.Counter(r["sanctions_status"] for r in rows)
        st_top = collections.Counter(r["sanctions_status"] for r in rows[:top])
        L += [f"- Sanctions/PEP check (OpenSanctions, name matching, to be confirmed by hand): all judges {dict(st)}; "
              f"top {top}: {dict(st_top)}.", ""]
    else:
        L += ["- Sanctions not checked: rerun with --os targets.simple.csv.", ""]
    L += ["| # | Judge | Court | Level | Cases | Speech | 205.2 | Organisation | Security | Convicted / acquitted | "
          "Custody ext. | Median days to sentence | Pending | Other courts | Sanctions |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows[:top]:
        ca = f"{r['defendants_convicted']} / {r['defendants_acquitted']}" if r["cases_with_card"] else "card not read"
        L.append(f"| {r['rank']} | {r['judge_en']} | {r['court']} | {r['court_level']} | {r['political_cases']} | "
                 f"{r['speech_cases']} | {r['terror_speech_cases']} | {r['organisation_cases']} | {r['security_cases']} | {ca} | {r['custody_extensions'] if r['cases_with_card'] else ''} | "
                 f"{r['median_days_to_sentence']} | {r['pending']} | {r['same_name_other_courts'] or '-'} | {r['sanctions_status']} |")
    sp = sorted(rows, key=lambda r: -r["speech_cases"])[:top]
    L += ["", f"## Top {top} by speech cases (anti-war, 'fakes', 'discreditation', undesirable organisations)", "",
          "| Judge | Court | Level | Speech cases | Convicted / acquitted | Single-hearing trials | Pending | Top articles | Sanctions |",
          "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['judge_en']} | {r['court']} | {r['court_level']} | {r['speech_cases']} | "
          f"{(str(r['defendants_convicted']) + ' / ' + str(r['defendants_acquitted'])) if r['cases_with_card'] else 'card not read'} | "
          f"{r['single_hearing_trials'] if r['cases_with_card'] else ''} | {r['pending']} | "
          f"{r['top_articles']} | {r['sanctions_status']} |" for r in sp if r["speech_cases"]]
    path.write_text("\n".join(L) + "\n", "utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--os", help="OpenSanctions targets.simple.csv (default: sanctions.opensanctions_csv in config)")
    ap.add_argument("--min-score", type=float)
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    ttl = work_path(cfg, "kg/courtlink-data.ttl")
    if not ttl.exists():
        raise SystemExit("no graph yet: run `python kg_build.py` first")
    g = Graph().parse(ttl)
    rows = collect(g)
    path = a.os or (cfg.get("sanctions") or {}).get("opensanctions_csv")
    out = work_path(cfg, "analysis")
    out.mkdir(parents=True, exist_ok=True)
    checked = bool(path) and Path(path).exists()
    if checked:
        cands = sanctions(rows, path, a.min_score or float((cfg.get("sanctions") or {}).get("min_score", 85)))
        write_csv(out / "judge_sanctions_candidates.csv", cands)
    elif path:
        LOG.warning("sanctions file not found: %s (ranking written without the check)", path)
    write_csv(out / "judge_dossier.csv", [{k: r[k] for k in FIELDS} for r in rows], FIELDS)
    write_md(rows, out / "judge_dossier.md", checked, a.top)
    LOG.info("judges with political cases: %d, cases: %d -> %s", len(rows), sum(r["political_cases"] for r in rows),
             out / "judge_dossier.md")


if __name__ == "__main__":
    main()
