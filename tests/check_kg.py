"""Statistical self-test of kg_build + kg_analytics on a synthetic census with a planted effect.
Court A: political cases go mostly to one judge (planted). Court B: political cases follow the baseline.
Judge X at court C: political cases almost never end in a verdict (planted)."""
import csv, json, os, random, subprocess, sys, shutil
from pathlib import Path

T = Path(sys.argv[1]); shutil.rmtree(T, ignore_errors=True); (T / "work").mkdir(parents=True)
rnd = random.Random(3)
F = ["court_id","court_name","court_type","region_iso","srv","docket","docket_key","received","judge","decision_date",
     "decision","outcome_class","articles","article_queried","n_defendants","ovd_linked","case_url","source_url","source_sha256","fetched_at"]
rows, n = [], 0
def add(court, judge, art, outcome="verdict", linked="", year=2024):
    global n; n += 1
    d = f"1-{n * 10}/{year}"
    rows.append({"court_id": court, "court_name": f"Суд {court}", "court_type": "district", "region_iso": "RU-SVE", "srv": "1",
                 "docket": d, "docket_key": d, "received": f"2024-{1 + n % 12:02d}-{1 + n % 27:02d}", "judge": judge,
                 "decision_date": f"2024-{1 + n % 12:02d}-28", "decision": "", "outcome_class": outcome, "articles": art,
                 "article_queried": art, "n_defendants": 1, "ovd_linked": linked, "case_url": f"https://x/{n}",
                 "source_url": f"https://{court}.sudrf.ru/modules.php?name_op=r", "source_sha256": f"{n:064x}", "fetched_at": "2026-10-01T00:00:00+00:00"})
JA = ["Аров А.А.", "Бров Б.Б.", "Вров В.В.", "Гров Г.Г.", "Дров Д.Д."]
for i in range(200): add("courtA", JA[i % 5], "158")
for i in range(30): add("courtA", JA[0] if rnd.random() < .8 else rnd.choice(JA), "207.3")
JB = ["Еров Е.Е.", "Жров Ж.Ж.", "Зров З.З.", "Иров И.И."]
for i in range(200): add("courtB", JB[i % 4], "228")
for i in range(30): add("courtB", JB[i % 4], "280.3")
JC = ["Кров К.К.", "Лров Л.Л.", "Мров М.М.", "Нров Н.Н.", "Оров О.О.", "Пров П.П."]
for j in JC:
    for i in range(14):
        bad = j == "Кров К.К."
        add("courtC", j, "282.2", "dismissed" if (bad and i < 9) or (not bad and rnd.random() < .06) else "verdict")
# Court D: judge Ш sits only in 2022, judge Щ only in 2025; all political cases are 2025, split evenly between Щ and Э.
for i in range(60): add("courtD", "Шров Ш.Ш.", "158", year=2022)
for i in range(60): add("courtD", ["Щров Щ.Щ.", "Эров Э.Э."][i % 2], "158", year=2025)
for i in range(20): add("courtD", ["Щров Щ.Щ.", "Эров Э.Э."][i % 2], "207.3", year=2025)
with open(T / "work/census.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=F); w.writeheader(); w.writerows(rows)
for name, hdr in (("hearings.csv", "hearing_id,record_id,court_id,court_name,court_type,instance,docket,docket_key,uid,uid_court_code,uid_court_check,judge,judges_all,judge_source,decision_date,result,outcome_class,card_url,card_sha256,card_fetched_at,match_source,results_sha256"),
                  ("cases.csv", "record_id,name,region,iso,articles"), ("courts.csv", "court_id,name,court_type,iso,sudrf_code,url")):
    (T / "work" / name).write_text(hdr + "\n", "utf-8")
here = Path(__file__).resolve().parent.parent
cfg = (here / "config.yaml").read_text("utf-8").replace("work_dir: work", f"work_dir: {T / 'work'}")
import re; cfg = re.sub(r"(?m)^work_dir: .*$", f"work_dir: {T / 'work'}", cfg)
(T / "cfg.yaml").write_text(cfg, "utf-8")
for s in ("kg_build.py", "kg_analytics.py"):
    subprocess.run([sys.executable, str(here / s), "--config", str(T / "cfg.yaml")] + (["--sims", "5000"] if "analytics" in s else []), check=True)
f = json.loads((T / "work/kg/findings.json").read_text("utf-8"))
A = {r["court"].rsplit("/", 1)[-1]: r for r in f["assignment"]}
assert A["courtA"]["q_value"] < 0.01, A["courtA"]["q_value"]
assert A["courtB"]["p_value"] > 0.2, A["courtB"]["p_value"]
assert A["courtD"]["p_value"] > 0.2, ("time stratification failed", A["courtD"]["p_value"])
J = {r["judgeEn"].split()[0]: r for r in f["judge_outcomes"]["judges"]}
assert J["Krov"]["flag"] == "above pool", J["Krov"]
assert all(r["flag"] != "above pool" for k, r in J.items() if k != "Krov"), J
assert f["ovd_gap"]["unlinked_cases"] == 30 + 30 + 84 + 20, f["ovd_gap"]["unlinked_cases"]
print("KG CHECKS PASSED: planted assignment effect found (q=%.4f), null court not flagged (p=%.2f), judge absent in the political years not counted (p=%.2f), planted outcome judge flagged"
      % (A["courtA"]["q_value"], A["courtB"]["p_value"], A["courtD"]["p_value"]))
