#!/usr/bin/env python3
"""Review borderline matches in your browser, then fold the decisions into matches.csv.

Shows each case in work/review_queue.csv: the OVD-Info record on the left, the court
candidates on the right (docket, defendant text, judge, date, link to the court card).
Pick the right candidate or "none of these", Submit. Decisions are applied to
work/matches.csv and logged to work/review_log.csv (who/when/what, for the methods section).

    python review.py
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import getpass
import html
import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from courtlink.common import LOG, load_config, read_csv, setup_logging, work_path, write_csv

MATCH_FIELDS = ["record_id", "court_id", "court_name", "court_type", "instance", "docket", "docket_key",
                "judge", "decision_date", "case_url", "score", "why", "source", "source_url", "sha256",
                "fetched_at"]

CSS = """body{font:14px -apple-system,system-ui,sans-serif;margin:24px;background:#f6f6f4;color:#1d1d1b}
h1{font-size:20px;margin:0 0 4px} p.l{color:#555;margin:0 0 16px}
.case{background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px;margin-bottom:14px}
.ovd{background:#f0f4fb;border-radius:6px;padding:8px;margin-bottom:8px}
.cand{border-top:1px solid #eee;padding:8px 0;display:flex;gap:10px}
.cand label{flex:1;cursor:pointer} small{color:#666} code{font-size:13px}
button{font-size:16px;padding:8px 18px}"""


def page(groups: dict) -> bytes:
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Match review</title>"
             f"<style>{CSS}</style></head><body><h1>{len(groups)} cases to review</h1>"
             "<p class='l'>Pick the court case that is the same prosecution, or 'none of these'. "
             "Same docket plus a matching or hidden defendant name is usually right; check the card if unsure.</p>"
             "<form id='f'>"]
    for rid, rows in groups.items():
        o = rows[0]
        e = html.escape
        anon = "anonym" in (o.get("ovd_name", "") or "").lower()
        parts.append(f"<div class='case'><div class='ovd'><b>OVD-Info</b> {e(o.get('ovd_name',''))} · "
                     f"docket <code>{e(o.get('ovd_docket',''))}</code> · {e(o.get('ovd_city',''))} · "
                     f"verdict {e(o.get('ovd_verdict_date',''))} · art. {e(o.get('ovd_articles',''))}"
                     f"<br><small>{e(rid)}</small>"
                     + ("<br><b style='color:#a33'>Anonymous in OVD-Info: use the court name only to verify the match; "
                        "never publish it.</b>" if anon else "") + "</div>")
        for i, r in enumerate(rows):
            parts.append(f"<div class='cand'><input type='radio' name='{e(rid)}' value='{i}' id='{e(rid)}_{i}'>"
                         f"<label for='{e(rid)}_{i}'><b>{e(r.get('court_name',''))}</b> · <code>{e(r.get('docket',''))}</code>"
                         f" · score {e(r.get('score',''))}<br>{e(r.get('info','') or r.get('names',''))}"
                         f"<br><small>judge {e(r.get('judge','') or '?')} · decided {e(r.get('decision_date','') or '?')}"
                         f" · {e(r.get('decision',''))} · <a href='{e(r.get('case_url',''))}' target='_blank'>open card</a>"
                         f" · why {e(r.get('why',''))}</small></label></div>")
        parts.append(f"<div class='cand'><input type='radio' name='{e(rid)}' value='none' id='{e(rid)}_n'>"
                     f"<label for='{e(rid)}_n'>none of these</label></div></div>")
    parts.append("<button type='submit'>Submit decisions</button></form><script>"
                 "document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();"
                 "const d={};new FormData(e.target).forEach((v,k)=>d[k]=v);"
                 "const r=await fetch('/submit',{method:'POST',body:JSON.stringify(d)});"
                 "document.body.innerHTML='<h1>'+await r.text()+'</h1><p>You can close this tab.</p>';});"
                 "</script></body></html>")
    return "".join(parts).encode("utf-8")


def collect(body: bytes) -> dict:
    result, done = {}, threading.Event()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            result.update(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Saved {len(result)} decisions.".encode())
            done.set()

    srv = HTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    LOG.info("review page: %s  (waiting for Submit)", url)
    webbrowser.open(url)
    done.wait()
    time.sleep(0.5)
    srv.shutdown()
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    a = ap.parse_args()
    setup_logging()
    cfg = load_config(a.config)
    q = read_csv(work_path(cfg, "review_queue.csv")) if work_path(cfg, "review_queue.csv").exists() else []
    groups = collections.OrderedDict()
    for r in q:
        groups.setdefault(r["record_id"], []).append(r)
    if not groups:
        LOG.info("nothing to review")
        return
    decisions = collect(page(groups))

    matches = read_csv(work_path(cfg, "matches.csv")) if work_path(cfg, "matches.csv").exists() else []
    have = {m["record_id"] for m in matches}
    logp = work_path(cfg, "review_log.csv")
    log = read_csv(logp) if logp.exists() else []
    now = dt.datetime.now().isoformat(timespec="seconds")
    who = getpass.getuser()
    added = 0
    for rid, rows in groups.items():
        d = decisions.get(rid)
        if d is None:
            continue
        chosen = rows[int(d)] if d != "none" else None
        log.append({"record_id": rid, "decision": "accept" if chosen else "none", "court_id": chosen["court_id"] if chosen else "",
                    "docket": chosen["docket"] if chosen else "", "reviewer": who, "reviewed_at": now})
        if chosen and rid not in have:
            matches.append({**chosen, "source": "review"})
            have.add(rid)
            added += 1
    write_csv(work_path(cfg, "matches.csv"), matches, MATCH_FIELDS)
    write_csv(logp, log, ["record_id", "decision", "court_id", "docket", "reviewer", "reviewed_at"])
    LOG.info("decided %d of %d cases; %d added to matches. Next: python 05_fetch_cards.py && python 06_judges.py",
             len([r for r in groups if r in decisions]), len(groups), added)


if __name__ == "__main__":
    main()
