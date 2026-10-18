#!/usr/bin/env python3
"""Checks for the full card reader (courtlink/card_detail.py, card_details.py) on a card laid out like sudrf's.

    python tests/check_card_detail.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from courtlink.card_detail import articles, parse_card_detail, summarize  # noqa: E402
from courtlink.common import read_csv  # noqa: E402


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    return cond


def main() -> int:
    html = (ROOT / "tests/fixtures/card_full.html").read_text("utf-8")
    d = parse_card_detail(html)
    s = summarize(d)
    ok = check("UID, panel, division", d["case"]["uid"] == "03RS0031-01-2024-001323-69" and s["single_judge"] == 1
               and "Буздяк" in s["division"])
    ok &= check("per-defendant results", [p["result_class"] for p in d["people"]] == ["guilty", "acquitted"])
    ok &= check("withheld name flagged; no names kept", [p["name_hidden"] for p in d["people"]] == [1, 0]
                and all("name" not in p for p in d["people"]))
    ok &= check("articles with parts", d["people"][1]["articles"] == "207.3(1);280.3(1)")
    ok &= check("events classified", [e["event_class"] for e in d["events"]][:4] == ["registered", "to_judge", "decision_on_case", "hearing"])
    ok &= check("20 minutes to the judge", s["minutes_to_judge"] == 20)
    ok &= check("hearing days, postponement, custody extension",
                (s["hearing_days"], s["postponed"], s["custody_extensions"]) == (3, 1, 1))
    ok &= check("days to sentence", s["days_to_sentence"] == 37 and s["single_hearing_trial"] == 0)
    ok &= check("posting lag", s["max_posting_lag_days"] == 20)
    roles = {p["role_class"]: p["name"] for p in d["parties"]}
    ok &= check("prosecutor named, lawyer and victim not", roles.get("prosecutor") == "Сидоров С.С."
                and roles.get("defence") == "" and roles.get("victim") == "")
    ok &= check("article forms", articles("Статья 284.1 Часть 2") == ["284.1(2)"] and articles("ч.3 ст.207.3") == ["207.3(3)"])

    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "work" / "cache").mkdir(parents=True)
        cfg = (ROOT / "config.yaml").read_text("utf-8")
        (t / "cfg.yaml").write_text(cfg.replace("work_dir: work", f"work_dir: {t / 'work'}") if "work_dir:" in cfg
                                    else cfg + f"\nwork_dir: {t / 'work'}\n", "utf-8")
        url = "https://kirovsky.svd.sudrf.ru/modules.php?name=sud_delo&srv_num=1&name_op=case&case_id=1&delo_id=1540006"
        body = html.encode("utf-8")
        key = hashlib.sha256(url.encode()).hexdigest()
        (t / "work/cache" / f"{key}.body").write_bytes(body)
        (t / "work/cache" / f"{key}.json").write_text(json.dumps({"url": url, "status": 200, "encoding": "utf-8",
                                                                   "sha256": hashlib.sha256(body).hexdigest(),
                                                                   "fetched_at": "2026-10-16T00:00:00+00:00"}), "utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "card_details.py"), "--config", str(t / "cfg.yaml")],
                           capture_output=True, text=True, cwd=ROOT)
        rows = read_csv(t / "work/cards/card_summary.csv") if (t / "work/cards/card_summary.csv").exists() else []
        ok &= check("card_details.py reads the cache", r.returncode == 0 and len(rows) == 1
                    and rows[0]["docket_key"] == "1-107/2024" and rows[0]["court_id"] == "kirovsky--svd"
                    and rows[0]["guilty"] == "1")
        if r.returncode:
            print(r.stderr[-800:])
    print("all passed" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
