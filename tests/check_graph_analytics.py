#!/usr/bin/env python3
"""Checks for graph_analytics.py on synthetic case pages with planted signals: one hidden batch, one over-frequent
prosecutor-judge pair, one judge running a template, and the proximity ranking. Also checks that background noise
is not flagged.

    python tests/check_graph_analytics.py
"""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import graph_analytics as ga  # noqa: E402
from courtlink.common import write_csv  # noqa: E402

rng = random.Random(1)
SUMMARY, EVENTS, PARTIES, MATCHES = [], [], [], []
JUDGES = ["Иванов Иван Иванович", "Петров Петр Петрович", "Сидоров Сидор Сидорович", "Кузнецов Олег Олегович",
          "Смирнов Илья Ильич"]
PROS = ["помощник прокурора Орлова А.Б.", "Волков В.Г.", "Зайцев Д.Е.", "государственный обвинитель Лебедев Ж.З.",
        "Соколов И.К.", "Попов Л.М.", "Морозов Н.О.", "Новиков П.Р."]


def ev(court, dk, seq):
    for n, (cls, flags) in enumerate(seq, 1):
        EVENTS.append({"court_id": court, "docket_key": dk, "n": n, "event": cls, "event_class": cls, "date": "", "time": "",
                       "result": "", "basis": "", "posted": "", "postponed": int("postponed" in flags), "break": 0,
                       "custody": int("ext" in flags), "custody_extended": int("ext" in flags), "sentence": int("sent" in flags)})


def case(court, dk, uid, received, judge, arts, seq, pros, in_ovd=False, single=0):
    SUMMARY.append({"court_id": court, "docket_key": dk, "uid": uid, "received": received, "judge": judge, "category": "",
                    "articles": arts, "single_hearing_trial": single, "card_url": f"https://x/{court}/{dk}"})
    ev(court, dk, seq)
    for p in pros:
        PARTIES.append({"court_id": court, "docket_key": dk, "n": 1, "role": "прокурор", "role_class": "prosecutor", "name": p})
    if in_ovd:
        MATCHES.append({"court_id": court, "docket_key": dk})


def random_seq():
    s = [("registered", ""), ("to_judge", "")]
    for _ in range(rng.randint(1, 6)):
        s.append(rng.choice([("hearing", ""), ("hearing", "postponed"), ("hearing", "ext"), ("preliminary", "")]))
    return s + [("sentence_read", "sent")]


# background: court A, 240 cases over 2023-2024, five judges, eight prosecutors at random
n = 0
for yr in ("2023", "2024"):
    for _ in range(120):
        n += 1
        num = rng.randint(1, 3000)
        art = rng.choice(["207.3(2)", "280.3(1)", "205.2(2)", "275"])
        case("A", f"1-{n}/{int(yr) + 1}", f"77RS0001-01-{yr}-{num:06d}-11", f"{int(yr) + 1}-{rng.randint(1, 12):02d}-15",
             rng.choice(JUDGES), art, random_seq(), [rng.choice(PROS)])
# planted pair: Petrov with prosecutor Orlova in 26 of 30 cases (court A, 205.2, 2025 receipts)
for i in range(30):
    n += 1
    case("A", f"1-{n}/2025", f"77RS0001-01-2024-{5000 + i * 37:06d}-11", f"2025-{(i % 12) + 1:02d}-03", JUDGES[1], "205.2(2)",
         random_seq(), [PROS[0] if i < 26 else rng.choice(PROS[1:])])
for i in range(60):  # other judges on 205.2 in 2025 with random prosecutors
    n += 1
    case("A", f"1-{n}/2025", f"77RS0001-01-2024-{7000 + i * 29:06d}-11", f"2025-{(i % 12) + 1:02d}-09",
         rng.choice([JUDGES[0], JUDGES[2], JUDGES[3]]), "205.2(2)", random_seq(), [rng.choice(PROS)])
# planted template: Smirnov, 30 cases at court A on 207.3, all R J D H S
for i in range(30):
    n += 1
    case("A", f"1-{n}/2025", f"77RS0001-01-2024-{9000 + i * 41:06d}-11", f"2025-{(i % 12) + 1:02d}-20", JUDGES[4], "207.3(2)",
         [("registered", ""), ("to_judge", ""), ("decision_on_case", ""), ("hearing", ""), ("sentence_read", "sent")],
         [rng.choice(PROS[1:])], single=1)
for i in range(60):
    n += 1
    case("A", f"1-{n}/2025", f"77RS0001-01-2024-{11000 + i * 31:06d}-11", f"2025-{(i % 12) + 1:02d}-21",
         rng.choice(JUDGES[:4]), "207.3(2)", random_seq(), [rng.choice(PROS[1:])])
# planted batch: court V, identifiers 2212..2220 of 2023 (2215 and 2217 never seen), 282.2, trial dockets in order;
# one member refiled (same UID, earlier registration) must count once
batch = [2212, 2213, 2214, 2216, 2218, 2219, 2220]
for i, num in enumerate(batch):
    case("V", f"1-{9 + i}/2025", f"66RS0001-01-2023-{num:06d}-44", f"2025-01-{10 + i:02d}", JUDGES[i % 3], "282.2(2)",
         random_seq(), [PROS[5]], in_ovd=i != 3)
case("V", "1-2/2024", "66RS0001-01-2024-001234-56", "2024-03-01", JUDGES[0], "282.2(2)", random_seq(), [PROS[5]])
for i in range(25):  # background at court V: other articles, spread out
    case("V", f"1-{100 + i}/2025", f"66RS0001-01-2023-{rng.randint(3000, 9000):06d}-44", f"2025-{(i % 12) + 1:02d}-02",
         rng.choice(JUDGES), rng.choice(["207.3(2)", "280.3(1)"]), random_seq(), [PROS[6]])

with tempfile.TemporaryDirectory() as td:
    W = Path(td)
    write_csv(W / "cards" / "card_summary.csv", SUMMARY)
    write_csv(W / "cards" / "card_events.csv", EVENTS)
    write_csv(W / "cards" / "card_parties.csv", PARTIES)
    write_csv(W / "matches.csv", MATCHES)
    D = ga.load(W)

C = D["cases"]
assert len(C) == len(SUMMARY), len(C)
assert ga.prosecutor_key("помощник прокурора Орлова А.Б.", "RU-MOW") == ("RU-MOW:орлова_аб", "Орлова А.Б.")
assert ga.prosecutor_key("прокуратура Ленинского района", "RU-MOW") == ("", "")
assert ga.group_of({"205.2", "207.3"}) == "terror_speech" and ga.group_of({"275", "205.2"}) == "security"

# 1. batches
B, M, G = ga.find_batches(C, D["all_uids"], window=20, days=45)
vb = [b for b in B if b["court_code"] == "66RS0001" and b["cases"] >= 5]
assert len(vb) == 1, vb
b = vb[0]
assert b["cases"] == 7 and b["span"] == 9 and b["q"] < 0.05, b
assert b["numbers_never_seen"] == 2 and {g["uid_prefix"][-6:] for g in G if g["batch"] == b["batch"]} == {"002215", "002217"}
assert b["dockets_in_same_order"] == "yes" and b["in_ovd"] == 6 and b["not_in_ovd"] == 1 and b["judges"] == 3, b
assert sum(1 for m in M if m["uid"].endswith("002212-44")) == 1  # refiled case counted once (latest registration)
noise = [x for x in B if x["court_code"] == "77RS0001" and x["q"] < 0.05]
assert not noise, noise[:3]

# 2. pairings
P = ga.pairings(C, D["prosecutors"], D["pnames"])
sig = [r for r in P if r["significant"]]
assert sig and sig[0]["judge"] == JUDGES[1] and sig[0]["prosecutor"] == "Орлова А.Б." and sig[0]["shared_cases"] >= 26, sig[:2]
assert len(sig) <= 2, [(r["judge"], r["prosecutor"], r["shared_cases"], r["q"]) for r in sig]

# 3. signatures
assert ga.signature([{"event_class": "registered"}, {"event_class": "hearing", "postponed": "1"},
                     {"event_class": "hearing", "postponed": "1"}, {"event_class": "hearing", "postponed": "1"},
                     {"event_class": "hearing", "postponed": "1"}, {"event_class": "sentence_read", "sentence": "1"},
                     {"event_class": "appeal"}]) == "R h3 S"
S, T = ga.signatures(C, D["events"], min_cases=10, perms=1000)
flag = [r for r in S if r["more_uniform_than_colleagues"]]
assert flag and flag[0]["judge"] == JUDGES[4] and flag[0]["modal_signature"] == "R J D H S" and flag[0]["modal_share"] > 0.5 and flag[0]["articles"] == "speech", flag[:2]
assert all(r["judge"] == JUDGES[4] for r in flag), [(r["judge"], r["court"], r["q"]) for r in flag]
assert T[0]["signature"] == "R J D H S" and T[0]["single_hearing_cases"] == 30

# 4. proximity
seed = C[("A", "1-241/2025")]["jkey"]  # Petrov
X = ga.proximity(C, D["prosecutors"], {seed})
assert X[0]["judge_key"] == seed and X[0]["is_seed"] == 1 and len(X) == len({c["jkey"] for c in C.values()})
assert abs(sum(ga.ppr({("a", "b"): 1, ("b", "c"): 2}, {"a"}).values()) - 1) < 1e-9  # mass is conserved
print(f"ok: {len(C)} cases | batch {b['batch']} q={b['q']:.2g} | pair {sig[0]['shared_cases']} vs {sig[0]['expected']} expected, "
      f"q={sig[0]['q']:.2g} | template judge q={flag[0]['q']:.2g} | {len(B)} batches, {len(sig)} pairs, {len(flag)} judges flagged")
