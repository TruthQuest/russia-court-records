"""Planted-effect checks for the census-based analyses: coverage_gap, judge_severity, careers, and the census name
index. Each analysis must find an effect that was planted and must not find one where none was planted.

    python tests/check_analyses.py
"""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import careers  # noqa: E402
import coverage_gap  # noqa: E402
import judge_severity  # noqa: E402
from census import ovd_index  # noqa: E402

ok = []

# ---- census name index: exactly one OVD-Info record, same region + surname + initial + article + plausible year -------
from census import name_match  # noqa: E402
recs = [{"record_id": "a", "last_name": "Ivanov", "first_name": "Ivan", "cyr_last_candidates": "Иванов", "iso": "RU-SVE",
         "articles": "207.3", "started_date": "2023-03-01"},
        {"record_id": "b", "last_name": "", "first_name": "", "iso": "RU-SVE", "articles": "207.3"},
        {"record_id": "c", "last_name": "Petrov", "first_name": "Pyotr", "cyr_last_candidates": "Петров", "iso": "RU-SVE",
         "articles": "207.3", "started_date": "2022-05-01"},
        {"record_id": "d", "last_name": "Petrov", "first_name": "Pavel", "cyr_last_candidates": "Петров", "iso": "RU-SVE",
         "articles": "207.3", "started_date": "2022-06-01"}]
idx = ovd_index(recs)
A = {"207.3"}
assert name_match(idx, "RU-SVE", "Иванов И.И.", A, 2024, set()) == "a"
assert name_match(idx, "RU-BA", "Иванов И.И.", A, 2024, set()) == ""           # other region
assert name_match(idx, "RU-SVE", "Иванов П.И.", A, 2024, set()) == ""          # other initial
assert name_match(idx, "RU-SVE", "Иванов И.И.", {"158"}, 2024, set()) == ""    # no shared article
assert name_match(idx, "RU-SVE", "Иванов И.И.", A, 2021, set()) == ""          # registered before the persecution began
assert name_match(idx, "RU-SVE", "Иванов И.И.", A, 2024, {"a"}) == ""          # record docket-linked elsewhere
assert name_match(idx, "RU-SVE", "Петров П.И.", A, 2024, set()) == ""          # two OVD-Info records: ambiguous
assert name_match(idx, "*", "Иванов И.И.", A, 2024, set()) == "a"             # military court: any region
ok.append("census name match: unique record, region, initial, article, year window, not linked elsewhere, ambiguity refused")


# ---- coverage: region A 80% of defendants covered, region B 30%; registrations hold 1-3 defendants; the docket link
#      covers the OVD-Info records on half the registrations; name matching finds 75% of covered defendants ------------
rnd = random.Random(1)
census, n = [], 0
for iso, cov in (("RU-AAA", 0.8), ("RU-BBB", 0.3)):
    for i in range(300):
        n += 1
        nd = rnd.choice([1, 1, 2, 3])
        covered = sum(rnd.random() < cov for _ in range(nd))
        linked_n = covered if (covered and rnd.random() < 0.5) else 0
        named = sum(rnd.random() < 0.75 for _ in range(covered))
        census.append({"region_iso": iso, "docket_key": f"1-{n}/2024", "articles": "207.3", "article_queried": "207.3",
                       "n_defendants": str(nd), "ovd_linked": "1" if linked_n else "", "ovd_linked_n": str(linked_n),
                       "ovd_named": str(named)})
R = coverage_gap.analyse(census, [], ["207.3"], 2022, 2026)
reg = {r["iso"]: r for r in R["region"]}
assert abs(R["recall"] - 0.75) < 0.08, R["recall"]
assert abs(reg["RU-AAA"]["coverage_recall_corrected"] - 0.8) < 0.07, reg["RU-AAA"]
assert abs(reg["RU-BBB"]["coverage_recall_corrected"] - 0.3) < 0.07, reg["RU-BBB"]
assert reg["RU-AAA"]["coverage"] < reg["RU-AAA"]["coverage_recall_corrected"]  # raw undercounts before correction
Rc = coverage_gap.analyse([dict(r, court_id="cX", srv="1") for r in census], [], ["207.3"], 2022, 2026, complete=set())
assert Rc["defendants"] == 0 and Rc["dropped_incomplete"] == len(census), "incomplete searches must not be counted"
Rk = coverage_gap.analyse([dict(r, court_id="cX", srv="1") for r in census], [], ["207.3"], 2022, 2026,
                          complete={("cX", "1", "207.3")})
assert Rk["defendants"] == R["defendants"]
R0 = coverage_gap.analyse([dict(r, ovd_linked="", ovd_linked_n="0") for r in census], [], ["207.3"], 2022, 2026)
assert R0["recall"] is None and R0["region"][0]["coverage_recall_corrected"] == "", "no recall must mean no correction"
ok.append(f"coverage recovered with multi-defendant registrations: A {reg['RU-AAA']['coverage_recall_corrected']:.2f} (true .80), "
          f"B {reg['RU-BBB']['coverage_recall_corrected']:.2f} (true .30), recall {R['recall']:.2f} (true .75); no recall -> no correction")


# ---- severity: one judge sentences 1.6x longer; null world has no judge effect -------------------------------------
def severity_world(planted: bool, seed: int, harsh_court: bool = True):
    rnd = random.Random(seed)
    edges, sents = [], []
    base = {"207.3": 36, "280.3": 18, "205.2": 72}
    k = 0
    for c in range(6):
        for j in range(4):
            jid = f"c{c}:j{j}"
            for reg in range(10):
                art = rnd.choice(list(base))
                year = rnd.choice([2023, 2024, 2025])
                f = 1.6 if (planted and c == 0 and j == 0) else 1.0
                f *= 1.6 if (harsh_court and c == 3) else 1.0  # a harsh court: every judge, so no judge effect
                for d in range(rnd.choice([1, 1, 2])):
                    k += 1
                    m = base[art] * f * math.exp(rnd.gauss(0, 0.25)) * (1.1 if year == 2025 else 1.0)
                    edges.append({"record_id": f"r{k}", "judge_id": jid, "court_id": f"c{c}", "instance": "criminal_first",
                                  "docket": f"1-{c}{j}{reg}/{year}", "articles": art, "decision_date": f"01.06.{year}"})
                    if rnd.random() < 0.15:  # an earlier hearing (case returned to the prosecutor) before another judge
                        edges.append({"record_id": f"r{k}", "judge_id": f"c{c}:j{(j + 1) % 4}", "court_id": f"c{c}",
                                      "instance": "criminal_first", "docket": f"1-9{c}{j}{reg}/{year - 1}", "articles": art,
                                      "decision_date": f"01.03.{year - 1}"})
                    kind = "custodial" if rnd.random() < 0.8 else "suspended"
                    sents.append({"record_id": f"r{k}", "first_kind": kind, "first_months": str(round(m))})
    return judge_severity.analyse(edges, sents, {}, perms=2000)


S1 = severity_world(True, 4)["term"]
S0 = severity_world(False, 4)["term"]
top = S1["judges"][0]
assert top["judge"] == "c0:j0" and top["flag"] == "above" and 1.3 < top["raw_factor"] < 1.8 and top["factor"] > 1.05, top
assert S1["p_within_court"] < 0.05, S1["p_within_court"]
assert S0["p_within_court"] > 0.05 and not any(j["flag"] for j in S0["judges"]), (S0["p_within_court"], [j for j in S0["judges"] if j["flag"]])
assert not any(j["flag"] and j["court"] == "c3" for j in S1["judges"]), "a harsh court was read as harsh judges"
ok.append("severity: harsh court (all judges 1.6x) not mistaken for harsh judges; earlier hearings before other judges ignored")
ok.append(f"severity: planted 1.6x judge found (raw x{top['raw_factor']}, shrunk x{top['factor']}, p {S1['p_within_court']:.4f}); null world p {S0['p_within_court']:.2f}, no judge flagged")


# ---- careers: exposed judges promoted at 3x the base hazard; null world equal hazard --------------------------------
def career_world(rr: float, seed: int):
    rnd = random.Random(seed)
    census, appts, courts = [], [], []
    letters = "АБВГДЕЖЗИКЛМНОПРСТУФХ"
    for c in range(80):
        cid = f"court{c}"
        courts.append({"court_id": cid, "court_type": "regional" if c % 10 == 0 else "district"})
        for j in range(8):
            sur = f"Су{letters[c % 20].lower()}{letters[c // 20].lower()}{letters[j].lower()}{'ов' if c < 40 else 'ев'}"
            judge = f"{sur} {letters[j]}.{letters[(j + 3) % 20]}."
            political = rnd.random() < 0.5
            start = rnd.choice([2018, 2019])
            promoted = None
            for y in range(start, 2026):
                exposed = political and y >= start + 2  # political cases from start+1, counted from the next year
                h = 0.03 * (rr if exposed else 1.0)
                if y > start and rnd.random() < h:
                    promoted = y  # promoted early in the year: no cases at the old court that year
                    break
                for i in range(30):
                    pol = political and y >= start + 1 and i < 2
                    census.append({"court_id": cid, "judge": judge, "docket_key": f"1-{j}{i}/{y}",
                                   "articles": "207.3" if pol else "158", "article_queried": ""})
            if promoted:
                appts.append({"move": "elevation", "prev_court_id": cid, "decree_date": f"{promoted}-07-01", "decree_no": "1",
                              "surname_nom": sur, "first": letters[j] + "ина", "patronymic": letters[(j + 3) % 20] + "вну",
                              "court_text": "x"})
    panel, ev, stats = careers.build(census, courts, appts, {"elevation", "leadership"}, 2026)
    return careers.analyse(panel, boot=300), stats


C1, st1 = career_world(3.0, 2)
C0, st0 = career_world(1.0, 2)
assert C1["events"] == st1["linked"], ("promotions in a year with no cases at the old court were dropped", st1, C1["events"])
assert C1["or_ci95"][0] > 1.0 and C1["rate_ratio"] > 1.8, C1
assert C0["or_ci95"][0] < 1.0 < C0["or_ci95"][1], C0
ok.append(f"careers: planted 3x hazard -> OR {C1['or_exposed']:.2f} (CI {C1['or_ci95'][0]:.2f}-{C1['or_ci95'][1]:.2f}); "
          f"null -> OR {C0['or_exposed']:.2f} (CI {C0['or_ci95'][0]:.2f}-{C0['or_ci95'][1]:.2f}); decrees linked {st1['linked']}")

print("ANALYSIS CHECKS PASSED")
for line in ok:
    print(" -", line)


# ---- census.py end to end on a cached results page: names compared in memory, only a count written ----------------
def census_name_check():
    import csv, json, shutil, subprocess, tempfile
    root = Path(__file__).resolve().parent.parent
    T = Path(tempfile.mkdtemp())
    (T / "cache").mkdir()
    url = ("https://xasavjurtovskij-gs--dag.sudrf.ru/modules.php?name=sud_delo&name_op=r&srv_num=1&delo_id=1540006"
           "&U1_DEFENDANT__LAW_ARTICLESS=158")
    shutil.copy(root / "tests/fixtures/res_khas.html", T / "cache/k1.body")
    (T / "cache/k1.json").write_text(json.dumps({"url": url, "status": 200, "sha256": "x", "fetched_at": "2026-10-01",
                                                  "encoding": "cp1251"}), "utf-8")
    with open(T / "courts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["court_id", "name", "court_type", "iso"]); w.writeheader()
        w.writerow({"court_id": "xasavjurtovskij-gs--dag", "name": "Хасавюртовский городской суд", "court_type": "district", "iso": "RU-DA"})
    cols = ["record_id", "last_name", "first_name", "cyr_last_candidates", "iso", "articles"]
    for name, rows in (("cases.csv", [{"record_id": "r1", "last_name": "Magomedov", "first_name": "Magomed",
                                       "cyr_last_candidates": "Магомедов", "iso": "RU-DA", "articles": "158"}]),):
        with open(T / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    cfg = (root / "config.yaml").read_text("utf-8")
    import re as _re
    (T / "cfg.yaml").write_text(_re.sub(r"(?m)^work_dir: .*$", f"work_dir: {T}", cfg), "utf-8")
    subprocess.run([sys.executable, str(root / "census.py"), "--config", str(T / "cfg.yaml")], check=True, capture_output=True)
    rows = list(csv.DictReader(open(T / "census.csv", encoding="utf-8")))
    assert rows and rows[0]["ovd_named"] == "1", rows
    assert not any("МАГОМЕДОВ" in v.upper() for r in rows for v in r.values() if "Магомед" in v or "МАГОМЕД" in v), "a defendant name was written"
    shutil.rmtree(T)
    return len(rows)


n_rows = census_name_check()
print(f" - census.py: defendant on a cached court page matched to an OVD-Info record by name in memory; "
      f"{n_rows} census row written with the count only")

# ---- court name lists: capitals, Turkic patronymics, withheld names ---------------------------------------------
from courtlink.parsers import extract_names, hidden_names  # noqa: E402
assert extract_names("ИВАНОВ ИВАН ИВАНОВИЧ - ст.354.1 ч.2 УК РФ") == ["Иванов Иван Иванович"]
assert extract_names("Алиев Арзу Аджар оглы - ст.354.1 ч.3 УК РФ") == ["Алиев Арзу Аджар оглы"]
assert extract_names("<Информация скрыта> - ст.354.1 ч.4 УК РФ") == [] and hidden_names("<Информация скрыта> - ст.354.1") == 1
print(" - court lists: names in capitals and with Turkic patronymics are read; withheld names are counted, not guessed")
