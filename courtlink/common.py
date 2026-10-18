"""Shared helpers: paths, config, CSV I/O, dates, OVD-Info column map."""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
import pathlib
import re
import sys

import yaml

csv.field_size_limit(10**9)

LOG = logging.getLogger("courtlink")

# OVD-Info "Public EN.csv" columns used by the pipeline.
COL = {
    "record": "Record ID",
    "person": "ID фигуранта",
    "name": "Name (first name, last name)",
    "region": "Region",
    "iso": "ISO код региона",
    "city": "City",
    "articles": "Статья без части",
    "articles_full": "Article of the Criminal Code",
    "verdict": "Дата приговора",
    "first_verdict": "Дата первого приговора",
    "started": "Дата начала преследования",
    "docket": "Номер дела",
    "case_name": "Criminal case name",
    "story": "Story",
    "plot": "Plot of the case",
    "hearings": "Hearings with sentence",
    "state": "Persecuted person state within the case",
}

ROOT = pathlib.Path(__file__).resolve().parent.parent


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config(path: str | os.PathLike | None = None) -> dict:
    path = pathlib.Path(path or ROOT / "config.yaml")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_path"] = str(path)
    work = pathlib.Path(os.path.expanduser(cfg.get("work_dir", "work")))
    if not work.is_absolute():
        work = ROOT / work
    work.mkdir(parents=True, exist_ok=True)
    cfg["_work"] = work
    return cfg


def work_path(cfg: dict, name: str) -> pathlib.Path:
    return cfg["_work"] / name


def read_csv(path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows: list[dict], fields: list[str] | None = None) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})
    LOG.info("wrote %s (%d rows)", path, len(rows))


_DATE_FORMATS = ("%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M:%S")


def parse_date(s: str | None) -> str:
    """Return ISO date (YYYY-MM-DD) or '' if unparseable."""
    s = (s or "").strip()
    if not s:
        return ""
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""


def days_between(a: str, b: str) -> int | None:
    if not a or not b:
        return None
    return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)


def split_list(s: str, sep: str = ",") -> list[str]:
    return [x.strip() for x in (s or "").split(sep) if x.strip()]


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def court_id_from_url(url_or_host: str) -> str:
    """Stable court ID across sudrf's host migration:
    covs--svd.sudrf.ru and covs.svd.sudrf.ru both -> 'covs--svd'."""
    h = (url_or_host or "").split("//")[-1].split("/")[0].lower()
    h = re.sub(r"^www\.", "", h)
    h = re.sub(r"\.sudrf\.ru$", "", h)
    return h.replace(".", "--") or "unknown"


def die(msg: str) -> None:
    LOG.error(msg)
    sys.exit(1)
