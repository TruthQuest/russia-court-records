"""ISO 3166-2 codes used by OVD-Info mapped to sudrf region codes.

sudrf numbers regions like the vehicle-plate (GIBDD) codes EXCEPT the first republics, which follow
the Constitution's order: 02 Altai Republic, 03 Bashkortostan, 04 Buryatia. Verified against
courts_info/rf_region_codes.json and the court codes in sudrf_websites.json.

Occupied Ukrainian territories are listed with the code Russia's court system uses where known.
Entries marked VERIFY must be confirmed against the sudrf directory before use.
"""
from __future__ import annotations

ISO_TO_SUBJ = {
    "RU-AD": "01", "RU-AL": "02", "RU-BA": "03", "RU-BU": "04", "RU-DA": "05", "RU-IN": "06",
    "RU-KB": "07", "RU-KL": "08", "RU-KC": "09", "RU-KR": "10", "RU-KO": "11", "RU-ME": "12",
    "RU-MO": "13", "RU-SA": "14", "RU-SE": "15", "RU-TA": "16", "RU-TY": "17", "RU-UD": "18",
    "RU-KK": "19", "RU-CE": "20", "RU-CU": "21", "RU-ALT": "22", "RU-KDA": "23", "RU-KYA": "24",
    "RU-PRI": "25", "RU-STA": "26", "RU-KHA": "27", "RU-AMU": "28", "RU-ARK": "29", "RU-AST": "30",
    "RU-BEL": "31", "RU-BRY": "32", "RU-VLA": "33", "RU-VGG": "34", "RU-VLG": "35", "RU-VOR": "36",
    "RU-IVA": "37", "RU-IRK": "38", "RU-KGD": "39", "RU-KLU": "40", "RU-KAM": "41", "RU-KEM": "42",
    "RU-KIR": "43", "RU-KOS": "44", "RU-KGN": "45", "RU-KRS": "46", "RU-LEN": "47", "RU-LIP": "48",
    "RU-MAG": "49", "RU-MOS": "50", "RU-MUR": "51", "RU-NIZ": "52", "RU-NGR": "53", "RU-NVS": "54",
    "RU-OMS": "55", "RU-ORE": "56", "RU-ORL": "57", "RU-PNZ": "58", "RU-PER": "59", "RU-PSK": "60",
    "RU-ROS": "61", "RU-RYA": "62", "RU-SAM": "63", "RU-SAR": "64", "RU-SAK": "65", "RU-SVE": "66",
    "RU-SMO": "67", "RU-TAM": "68", "RU-TVE": "69", "RU-TOM": "70", "RU-TUL": "71", "RU-TYU": "72",
    "RU-ULY": "73", "RU-CHE": "74", "RU-ZAB": "75", "RU-YAR": "76", "RU-MOW": "77", "RU-SPE": "78",
    "RU-YEV": "79", "RU-NEN": "83", "RU-KHM": "86", "RU-CHU": "87", "RU-YAN": "89",
    # Occupied Ukrainian territory, courts operated by the Russian system.
    "UA-43": "91",   # Crimea
    "UA-40": "92",   # Sevastopol
    # Donetsk (UA-14), Luhansk (UA-09), Zaporizhzhia (UA-23), Kherson (UA-65): courts installed after
    # 2022 are not in the 2023 sudrf list; these records go to manual lookup.
}

OCCUPIED = {"UA-43", "UA-40", "UA-14", "UA-09", "UA-23", "UA-65"}
VERIFY = {"UA-14", "UA-09", "UA-23", "UA-65"}  # occupied after 2022, no sudrf subject in the court list


def subjects_for(iso_field: str) -> list[tuple[str, str]]:
    """'RU-BA, RU-ORE' -> [('RU-BA','02'), ('RU-ORE','56')]; unknown codes dropped."""
    out = []
    for iso in (iso_field or "").split(","):
        iso = iso.strip()
        if iso in ISO_TO_SUBJ:
            out.append((iso, ISO_TO_SUBJ[iso]))
    return out
