#!/usr/bin/env python3
"""Step 0. OVD-Info CSV -> work/cases.csv: one row per record with parsed dockets, dates, names,
region codes and court names mentioned in the narrative text.

    python 00_prepare_cases.py --csv "/path/Public EN.csv" [--ru-csv "/path/Public RU.csv"]
"""
from __future__ import annotations

import argparse
import collections
import re

from courtlink.common import COL, LOG, load_config, parse_date, read_csv, setup_logging, work_path, write_csv
from courtlink.dockets import parse_dockets
from courtlink.regions import OCCUPIED, VERIFY, subjects_for
from courtlink.translit import has_cyrillic, lat_to_cyr, skeleton, split_ovd_name

COURT_MENTION_RE = re.compile(
    r"((?:[A-Z][\w'’-]+\s){1,4}(?:District|City|Regional|Krai|Oblast|Republic|Garrison|Military|"
    r"District Military|Garrison Military|Supreme|Inter-?district|Municipal)\s+Court"
    r"(?:\s+of\s+(?:the\s+)?(?:[A-Z][\w'’-]+\s?){1,3})?)"
)
ANON_RE = re.compile(r"anonym|wished to remain|name withheld|unknown", re.I)
CITY_ALIASES = {"saint petersburg": "peterburg", "st petersburg": "peterburg", "moscow": "moskv",
                "oryol": "orl", "naberezhnye chelny": "naberezn", "veliky novgorod": "novgorod"}


GENERIC = {"village", "of", "settlement", "town", "city", "selo", "posyolok", "urban", "type", "pgt", "the",
           "stanitsa", "khutor", "aul", "district", "rural", "okrug", "on", "na"}


def _stem(t: str) -> str:
    if len(t) <= 5:  # short names inflect in court names: Уфа -> Уфы, Чита -> Читы
        return t[:-1] if t[-1:] in "aeiouy" and len(t) >= 3 else t
    return t[: max(4, len(t) - 2)]


def city_stem(city: str) -> str:
    """Space-joined stems of every meaningful word; all must match the court name (Nizhny Tagil)."""
    c = (city or "").split("(")[0].split(",")[0].strip().lower()
    if not c:
        return ""
    if c in CITY_ALIASES:
        return CITY_ALIASES[c]
    toks = [t for t in skeleton(c).split() if t not in {skeleton(g) for g in GENERIC} and len(t) >= 2]
    return " ".join(_stem(t) for t in toks)


def ru_names(path: str) -> dict[str, str]:
    """Record ID -> Cyrillic full name from an OVD-Info Russian export, if provided."""
    rows = read_csv(path)
    if not rows:
        return {}
    id_col = next((c for c in rows[0] if c.strip() in ("Record ID", "Идентификатор записи", "Идентификатор")), None)
    name_col = next((c for c in rows[0] if re.search(r"(ФИО|Имя|Name)", c) and
                     sum(has_cyrillic(r[c]) for r in rows[:200]) > 50), None)
    if not id_col or not name_col:
        LOG.warning("RU csv: could not identify id/name columns (%s / %s)", id_col, name_col)
        return {}
    LOG.info("RU csv: using %r and %r", id_col, name_col)
    return {r[id_col]: r[name_col] for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--ru-csv")
    ap.add_argument("--config")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    src = a.csv or cfg.get("ovd_csv")
    rows = read_csv(src)
    ru = ru_names(a.ru_csv or cfg.get("ovd_ru_csv")) if (a.ru_csv or cfg.get("ovd_ru_csv")) else {}

    out, stats = [], collections.Counter()
    for r in rows:
        ds = parse_dockets(r[COL["docket"]])
        anonymous = bool(ANON_RE.search(r[COL["name"]] or ""))
        first, last = ("", "") if anonymous else split_ovd_name(r[COL["name"]])
        ru_full = ru.get(r[COL["record"]], "")
        if ru_full:
            toks = ru_full.split()
            # OVD RU names may be 'Имя Фамилия' or 'Фамилия Имя Отчество'; keep both ends as candidates
            cyr = list(dict.fromkeys([toks[-1], toks[0]])) if toks else []
        else:
            cyr = lat_to_cyr(last, limit=2) if last else []
        subj = subjects_for(r[COL["iso"]])
        text = " ".join(r[c] for c in (COL["story"], COL["plot"], COL["case_name"]))
        mentions = list(dict.fromkeys(m.group(1).strip() for m in COURT_MENTION_RE.finditer(text)))
        isos = [s[0] for s in subj]
        rec = {
            "record_id": r[COL["record"]],
            "person_id": r[COL["person"]],
            "name": r[COL["name"]],
            "anonymous": int(anonymous),  # OVD-Info withholds the name: never publish a court-side name for it
            "first_name": first,
            "last_name": last,
            "cyr_last_candidates": ";".join(cyr),
            "region": r[COL["region"]],
            "iso": ";".join(isos),
            "subj": ";".join(s[1] for s in subj),
            "occupied": int(any(i.strip() in OCCUPIED for i in r[COL["iso"]].split(","))),
            "subj_unverified": int(any(i.strip() in VERIFY for i in r[COL["iso"]].split(","))),
            "city": r[COL["city"]],
            "city_stem": city_stem(r[COL["city"]]),
            "articles": ";".join(x.strip() for x in r[COL["articles"]].split(",") if x.strip()),
            "docket_raw": ds.raw,
            "docket": ds.current.raw if ds.current else "",
            "docket_key": ds.current.key if ds.current else "",
            "docket_keys": ";".join(d.key for d in ds.all),
            "prior_dockets": ";".join(d.raw for d in ds.prior),
            "investigative_numbers": ";".join(ds.investigative),
            "docket_prefix": ds.current.prefix if ds.current else "",
            "docket_year": ds.current.year if ds.current else "",
            "level_hint": ds.current.level_hint(r[COL["iso"]]) if ds.current else "",
            "verdict_date": parse_date(r[COL["verdict"]]),
            "first_verdict_date": parse_date(r[COL["first_verdict"]]),
            "started_date": parse_date(r[COL["started"]]),
            "court_mentions": " || ".join(mentions[:5]),
            "state": r[COL["state"]],
        }
        stats["records"] += 1
        stats["with_docket"] += bool(rec["docket"])
        stats["with_surname"] += bool(last)
        stats["anonymous"] += anonymous
        stats["with_verdict_date"] += bool(rec["verdict_date"] or rec["first_verdict_date"])
        stats["with_court_mention"] += bool(mentions)
        stats["no_region_code"] += not subj
        stats[f"level:{rec['level_hint'] or 'none'}"] += 1
        out.append(rec)
    write_csv(work_path(cfg, "cases.csv"), out)
    for k, v in sorted(stats.items()):
        LOG.info("%-28s %6d", k, v)


if __name__ == "__main__":
    main()
