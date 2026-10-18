"""Unit checks for sentence extraction (English OVD-Info stories and Russian court text)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from courtlink.sentence_text import parse_all

CASES = [
    ("On 22 April 2026 the court sentenced her to a fine of 400,000 roubles.", "fine", None, 400000),
    ("The court sentenced him to six years in a general-regime penal colony.", "custodial", 72, None),
    ("He was sentenced to 2 years and 6 months of imprisonment in a strict regime colony.", "custodial", 30, None),
    ("She received a suspended sentence of three years with a probation period of 2 years.", "suspended", 36, None),
    ("In recent years he was active. In May the court sentenced him to 8 years in a penal colony.", "custodial", 96, None),
    ("The court sentenced him to six and a half years in prison.", "custodial", 78, None),
    ("He was sentenced to 300 hours of compulsory work.", "compulsory_works", None, None),
    ("He was sentenced to 1 year of forced labour.", "forced_labour", 12, None),
    ("The court acquitted him.", "acquittal", None, None),
    ("The court sentenced him to compulsory psychiatric treatment.", "medical", None, None),
    ("Суд назначил наказание в виде лишения свободы сроком на 6 (шесть) лет 6 месяцев с отбыванием в исправительной колонии общего режима.", "custodial", 78, None),
    ("Приговором суда назначено наказание в виде штрафа в размере 1 млн рублей.", "fine", None, 1000000),
    ("Приговор: 3 года лишения свободы условно с испытательным сроком 2 года.", "suspended", 36, None),
    ("He was fined 1.5 million roubles.", "fine", None, 1500000),
    ("The court sentenced him to a year and a half in a penal colony.", "custodial", 18, None),
    ("The court sentenced him to 6 years in a penal colony, although the defence asked for a suspended sentence.", "custodial", 72, None),
    ("He was sentenced to 5 years in a colony followed by 1 year of restriction of freedom.", "custodial", 60, None),
    ("The prosecutor requested a sentence of 7 years. The court sentenced him to 5 years in a penal colony.", "custodial", 60, None),
    ("In 2021 he was fined under the administrative code. In 2023 he was sentenced to 4 years in a penal colony.", "custodial", 48, None),
    ("He was sentenced to compulsory treatment in a psychiatric hospital.", "medical", None, None),
    ("He was sentenced to 6.5 years in a penal colony.", "custodial", 78, None),
    ("The court sentenced him in absentia to 8 years in a penal colony.", "custodial", 96, None),
    ("He was sentenced to a fine of 300 thousand roubles.", "fine", None, 300000),
    ("He was sentenced to two years of forced labour.", "forced_labour", 24, None),
    ("Суд назначил штраф в размере 1,5 млн рублей.", "fine", None, 1500000),
]
bad = 0
for text, kind, months, fine in CASES:
    r = parse_all(text)
    got = r[0] if r else {"kind": None, "months": None, "fine_rub": None}
    ok = got["kind"] == kind and (months is None or got["months"] == months) and (fine is None or got["fine_rub"] == fine)
    if not ok:
        bad += 1
        print("FAIL", text, "->", {k: got.get(k) for k in ("kind", "months", "fine_rub")})
first_last = parse_all("In March 2024 the court sentenced him to 7 years in a penal colony. On appeal in June the sentence was reduced to 5 years in a penal colony; he was sentenced to 5 years.")
assert first_last[0]["months"] == 84, first_last
r = parse_all("He was sentenced to 5 years in a penal colony and fined 500,000 roubles.")
assert len(r) == 1 and r[0]["kind"] == "custodial" and r[0]["fine_rub"] == 500000, r
assert parse_all("The court sentenced him in absentia to 8 years in a penal colony.")[0]["in_absentia"]
assert bad == 0, f"{bad} sentence cases failed"
print(f"SENTENCE CHECKS PASSED ({len(CASES)} cases)")
