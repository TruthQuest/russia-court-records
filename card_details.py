#!/usr/bin/env python3
"""Read every cached first-instance criminal case card in full: per-defendant results, every procedural event, party
roles. Offline: works on pages already in work/cache (fetch them first with census_cards.py and 05_fetch_cards.py).

    python census_cards.py        cards for every census registration (no captcha)
    python card_details.py        parse them all
    python kg_build.py            the graph picks up card_summary.csv (convictions, acquittals, custody, speed)
    python judge_dossier.py       the judge ranking gains those columns

Writes to work/cards/ (no defendant, lawyer or victim names; prosecutors' names only, as officials):
    card_summary.csv   one row per card: presiding judge, articles (all defendants), defendants guilty / acquitted / dismissed / pending, hearing days,
                       postponements, custody decisions and extensions, minutes from registration to the judge,
                       days to sentence, single-hearing trials, longest delay in posting an event, party counts
    card_people.csv    one row per defendant: name withheld or not, articles with parts, date, result
    card_events.csv    one row per event: type, date, time, result, reason, date posted, flags
    card_parties.csv   one row per party: role; name for prosecutors only
"""
from __future__ import annotations

import argparse
import collections
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from courtlink.progress import tqdm

from courtlink.card_detail import parse_card_detail, summarize
from courtlink.common import LOG, court_id_from_url, load_config, setup_logging, write_csv
from courtlink.dockets import docket_key

FIRST_INSTANCE = "delo_id=1540006"
SUMMARY = ["court_id", "docket_key", "uid", "received", "judge", "category", "articles", "panel", "single_judge", "division", "people", "names_hidden",
           "guilty", "acquitted", "dismissed", "medical", "returned", "pending", "hearing_days", "postponed",
           "custody_decisions", "custody_extensions", "minutes_to_judge", "first_hearing", "sentence_date",
           "days_to_sentence", "single_hearing_trial", "max_posting_lag_days", "prosecutors", "defence_lawyers",
           "victims", "card_url", "card_sha256", "fetched_at"]


def card_paths(cache: Path) -> list[tuple[dict, Path]]:
    """(meta, body path) for every cached first-instance criminal case card."""
    out = []
    for meta_p in cache.glob("*.json"):
        try:
            meta = json.loads(meta_p.read_text("utf-8"))
        except Exception:
            continue
        url = meta.get("url", "")
        if meta.get("status") == 200 and "name_op=case" in url and FIRST_INSTANCE in url:
            body = meta_p.with_suffix(".body")
            if body.exists():
                out.append((meta, body))
    return out


def parse_one(item: tuple[dict, Path]):
    """Worker: one cached card -> (key, fetched_at, summary, people, events, parties), or None."""
    meta, body = item
    html = body.read_bytes().decode(meta.get("encoding") or "utf-8", errors="replace")
    url = meta["url"]
    d = parse_card_detail(html, url)
    key = (court_id_from_url(url), docket_key(d["case"]["docket"]))
    if not key[1]:
        return None
    base = {"court_id": key[0], "docket_key": key[1]}
    arts = []
    for p in d["people"]:
        for x in (p["articles"] or "").split(";"):
            if x and x not in arts:
                arts.append(x)
    summ = {**base, **summarize(d), "judge": d["case"]["judge"], "category": d["case"]["category"],
            "articles": ";".join(arts), "card_url": url, "card_sha256": meta.get("sha256", ""),
            "fetched_at": meta.get("fetched_at", "")}
    return (key, meta.get("fetched_at", ""), summ,
            [{**base, "n": i, **p} for i, p in enumerate(d["people"], 1)],
            [{**base, "n": i, **e} for i, e in enumerate(d["events"], 1)],
            [{**base, "n": i, **p} for i, p in enumerate(d["parties"], 1)])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--workers", type=int, default=0, help="parallel parser processes (default: CPU cores - 1)")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    W = Path(cfg["_work"])
    items = card_paths(W / "cache")
    workers = a.workers or max(1, (os.cpu_count() or 2) - 1)
    stats = collections.Counter()
    best = {}
    if workers > 1 and len(items) > 50:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = ex.map(parse_one, items, chunksize=max(1, len(items) // (workers * 8)))
            for r in tqdm(results, total=len(items), unit="card", desc="parsing", dynamic_ncols=True):
                if r is None:
                    stats["no_docket"] += 1
                elif r[0] not in best or r[1] > best[r[0]][1]:  # the same card fetched twice: keep the newest
                    best[r[0]] = r
    else:
        for it in tqdm(items, unit="card", desc="parsing", dynamic_ncols=True):
            r = parse_one(it)
            if r is None:
                stats["no_docket"] += 1
            elif r[0] not in best or r[1] > best[r[0]][1]:
                best[r[0]] = r
    stats["cards"] = len(best)
    stats["older_copies"] = len(items) - len(best) - stats["no_docket"]
    summ = {k: r[2] for k, r in best.items()}
    people = [p for r in best.values() for p in r[3]]
    events = [e for r in best.values() for e in r[4]]
    parties = [p for r in best.values() for p in r[5]]
    out = W / "cards"
    write_csv(out / "card_summary.csv", list(summ.values()), SUMMARY)
    write_csv(out / "card_people.csv", people,
              ["court_id", "docket_key", "n", "name_hidden", "articles", "date", "result", "result_class"])
    write_csv(out / "card_events.csv", events,
              ["court_id", "docket_key", "n", "event", "event_class", "date", "time", "result", "basis", "posted",
               "postponed", "break", "custody", "custody_extended", "sentence"])
    write_csv(out / "card_parties.csv", parties, ["court_id", "docket_key", "n", "role", "role_class", "name"])
    res = collections.Counter(p["result_class"] for p in people)
    S = list(summ.values())
    LOG.info("cards parsed: %d (%s) | defendants: %d %s | events: %d | cards with events: %d, with defendants: %d",
             len(S), dict(stats), len(people), dict(res.most_common()), len(events),
             sum(1 for s in S if s["hearing_days"] or s["minutes_to_judge"] != ""), sum(1 for s in S if s["people"]))
    if S and not people:
        LOG.warning("no defendant rows found on any card: the FACES table headers may differ on these sites; "
                    "run `python probe.py card --url <one card url>` and send the output")


if __name__ == "__main__":
    main()
