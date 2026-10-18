"""English renderings for readers who don't read Russian.

Names are romanized two ways, because they serve two purposes:
  - press():  BGN/PCGN without diacritics, as English-language media write Russian names
              (Yuri, Vorobyeva, Nevsky). Best for reading.
  - icao():   ICAO 9303, the system in Russian international passports since 2013 (Iurii, Vorobeva).
              Sanctions lists often copy passport spellings, so use this column when matching.
Court names are translated, not just romanized: the place adjective is kept the way English media
cite courts ("Nevsky District Court", "Meshchansky District Court"), the court type is translated,
and the city is put in the nominative ("of Yekaterinburg").
Court results are translated from sudrf's fixed vocabulary; articles get a short English gloss.
"""
from __future__ import annotations

import re

_BASE = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "з": "z", "и": "i", "к": "k", "л": "l", "м": "m",
         "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
         "ч": "ch", "ш": "sh", "щ": "shch", "ж": "zh", "э": "e"}
_PRESS = {**_BASE, "й": "y", "ы": "y", "ъ": "", "ь": "", "ю": "yu", "я": "ya", "ё": "yo", "е": "e"}
_ICAO = {**_BASE, "й": "i", "ы": "y", "ъ": "ie", "ь": "", "ю": "iu", "я": "ia", "ё": "e", "е": "e"}
_VOWELS = set("аеёиоуыэюяъь")


def _word(w: str, table: dict, press: bool) -> str:
    lw = w.lower()
    if press:  # -ий / -ый endings read as -y in English (Nevsky, Yuri -> Yury handled as Yuri below)
        lw = re.sub(r"(ий|ый)$", "#", lw)
    out = []
    for i, ch in enumerate(lw):
        if ch == "#":
            out.append("y" if not lw.endswith("ий#") else "y")
            continue
        if press and ch in "её" and (i == 0 or lw[i - 1] in _VOWELS):
            out.append("ye" if ch == "е" else "yo")
            continue
        out.append(table.get(ch, ch))
    s = "".join(out)
    if press:
        s = re.sub(r"yy$", "y", s)
        s = re.sub(r"^yury$", "yuri", s)
    return s[:1].upper() + s[1:] if w[:1].isupper() else s


def _romanize(text: str, table: dict, press: bool) -> str:
    def fix(m):
        w = m.group(0)
        r = _word(w, table, press)
        return r.upper() if w.isupper() and len(w) > 1 else r
    return re.sub(r"[А-Яа-яЁё]+", fix, text or "")


def press(text: str) -> str:
    return _romanize(text, _PRESS, True)


def icao(text: str) -> str:
    return _romanize(text, _ICAO, False)


# --- courts ---------------------------------------------------------------------------------
CITY_GEN = {"Екатеринбурга": "Yekaterinburg", "Уфы": "Ufa", "Казани": "Kazan", "Краснодара": "Krasnodar",
            "Сочи": "Sochi", "Нижний Тагил": "Nizhny Tagil", "Нижнего Тагила": "Nizhny Tagil",
            "Санкт-Петербурга": "St. Petersburg", "Лесного": "Lesnoy", "Новороссийска": "Novorossiysk",
            "Москвы": "Moscow", "Ростова-на-Дону": "Rostov-on-Don", "Самары": "Samara", "Перми": "Perm",
            "Челябинска": "Chelyabinsk", "Новосибирска": "Novosibirsk", "Омска": "Omsk", "Тюмени": "Tyumen"}
REGION_ADJ = {"Свердловский": "Sverdlovsk", "Краснодарский": "Krasnodar", "Ростовский": "Rostov", "Московский": "Moscow",
              "Оренбургский": "Orenburg", "Самарский": "Samara", "Мурманский": "Murmansk", "Тамбовский": "Tambov",
              "Санкт-Петербургский": "St. Petersburg", "Ленинградский": "Leningrad", "Челябинский": "Chelyabinsk",
              "Новосибирский": "Novosibirsk", "Нижегородский": "Nizhny Novgorod", "Пермский": "Perm",
              "Тюменский": "Tyumen", "Омский": "Omsk", "Иркутский": "Irkutsk", "Калининградский": "Kaliningrad",
              "Воронежский": "Voronezh", "Волгоградский": "Volgograd", "Саратовский": "Saratov"}
MILITARY = {"Центральный окружной военный суд": "Central District Military Court",
            "Южный окружной военный суд": "Southern District Military Court",
            "1-й Западный окружной военный суд": "1st Western District Military Court",
            "2-й Западный окружной военный суд": "2nd Western District Military Court",
            "1-й Восточный окружной военный суд": "1st Eastern District Military Court",
            "2-й Восточный окружной военный суд": "2nd Eastern District Military Court",
            "Балтийский флотский военный суд": "Baltic Fleet Military Court",
            "Северный флотский военный суд": "Northern Fleet Military Court",
            "Тихоокеанский флотский военный суд": "Pacific Fleet Military Court"}
KIND = {"районный": "District Court", "городской": "City Court", "межрайонный": "Interdistrict Court",
        "гарнизонный военный": "Garrison Military Court"}


def _adj(a: str) -> str:
    return press(a)


def court(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip())
    if n in MILITARY:
        return MILITARY[n]
    m = re.match(r"^Верховный Суд Республики (.+)$", n)
    if m:
        return f"Supreme Court of the Republic of {press(m.group(1))}"
    m = re.match(r"^(\S+) (областной|краевой|городской) суд$", n)
    if m and m.group(1) in REGION_ADJ:
        kind = {"областной": "Regional Court", "краевой": "Krai Court", "городской": "City Court"}[m.group(2)]
        return f"{REGION_ADJ[m.group(1)]} {kind}"
    m = re.match(r"^Городской суд г\. (.+)$", n)
    if m:
        return f"{CITY_GEN.get(m.group(1), press(m.group(1)))} City Court"
    m = re.match(r"^(.+?) (гарнизонный военный|межрайонный|районный|городской) суд(.*)$", n)
    if m:
        out = f"{_adj(m.group(1))} {KIND[m.group(2)]}"
        rest = m.group(3).strip()
        city = re.search(r"(?:г\.|города)\s+(.+?)(?:\s+Республики|$)", rest)
        if city:
            out += f" of {CITY_GEN.get(city.group(1).strip(), press(city.group(1).strip()))}"
        rep = re.search(r"Республики (.+)$", rest)
        if rep:
            out += f", Republic of {press(rep.group(1))}"
        return out
    return press(n)


# --- results --------------------------------------------------------------------------------
RESULTS = [
    (r"^$", "No result posted yet"),
    (r"ПРИГОВОР", "Verdict delivered"),
    (r"ПРИНУДИТЕЛЬН\w+ МЕР\w+ МЕДИЦИНСК", "Compulsory medical (psychiatric) measures applied"),
    (r"ПО ПОДСУДНОСТИ", "Sent to another court (jurisdiction)"),
    (r"ВОЗВРАЩЕНО ПРОКУРОРУ", "Returned to the prosecutor: indictment drawn up in violation of the Criminal Procedure Code"),
    (r"СУДЕБНЫЙ ШТРАФ", "Case dismissed with a court fine (Art. 25.1 Criminal Procedure Code)"),
    (r"ИСТЕЧЕНИЕ СРОКОВ ДАВНОСТИ", "Case dismissed: statute of limitations expired"),
    (r"ДЕЯТЕЛЬНЫМ РАСКАЯНИЕМ", "Case dismissed: active repentance"),
    (r"ПРИМИРЕНИЕМ", "Case dismissed: reconciliation of the parties"),
    (r"СМЕРТЬЮ|СМЕРТИ", "Case dismissed: death of the defendant"),
    (r"АМНИСТИ", "Case dismissed: amnesty"),
    (r"ОТСУТСТВИЕМ СОСТАВА|ОТСУТСТВИЕМ СОБЫТИЯ|ОПРАВДАТ", "Case dismissed or acquitted: no offence"),
    (r"ПРЕКРАЩЕНО", "Case dismissed"),
    (r"присоедин", "Case joined to another case"),
    (r"ПРИОСТАНОВЛЕН", "Proceedings suspended"),
]


def result(text: str) -> str:
    t = (text or "").strip()
    for rx, en in RESULTS:
        if re.search(rx, t, re.I if rx.islower() else 0):
            return en
    return f"[untranslated] {press(t)}"


# --- articles of the Criminal Code -----------------------------------------------------------
ARTICLES = {
    "105": "murder", "111": "grave bodily harm", "115": "minor bodily harm", "119": "threat of murder",
    "128.1": "libel", "148": "insulting religious feelings", "150": "involving a minor in a crime", "158": "theft",
    "159": "fraud", "205": "terrorist act", "205.1": "assisting terrorism", "205.2": "public justification of terrorism",
    "205.3": "terrorism training", "205.4": "terrorist community", "205.5": "terrorist organization",
    "205.6": "failure to report terrorism", "206": "hostage taking", "207": "false report of terrorism",
    "207.2": "fake news on emergencies", "207.3": "'fakes' about the armed forces", "208": "illegal armed formation",
    "212": "mass riots", "212.1": "repeated violation of protest rules", "213": "hooliganism", "214": "vandalism",
    "222": "illegal weapons", "222.1": "illegal explosives", "226": "theft of weapons", "228": "drugs",
    "239": "association infringing citizens' rights", "264": "traffic offence", "275": "high treason",
    "275.1": "confidential cooperation with a foreign state", "276": "espionage", "277": "attempt on a statesman",
    "278": "violent seizure of power", "279": "armed rebellion", "280": "calls to extremism", "280.1": "calls to separatism",
    "280.3": "discrediting the armed forces", "280.4": "calls against state security", "281": "sabotage",
    "282": "inciting hatred", "282.1": "extremist community", "282.2": "extremist organization",
    "282.3": "financing extremism", "282.4": "repeated display of banned symbols", "284.1": "'undesirable' organization",
    "284.2": "calls for sanctions", "317": "attempt on a law enforcement officer", "318": "violence against an official",
    "319": "insulting an official", "329": "desecration of state symbols", "330": "arbitrariness",
    "330.1": "evading 'foreign agent' duties", "354.1": "'rehabilitation of Nazism'", "360": "attack on protected persons",
}


def articles(arts) -> str:
    out = []
    for a in arts:
        g = ARTICLES.get(a)
        out.append(f"{a} ({g})" if g else a)
    return "; ".join(out)
