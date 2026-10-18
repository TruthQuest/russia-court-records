"""Parse Russian court docket numbers as they appear in OVD-Info's 'Номер дела'.

Observed forms:
  1-913/2025                      district (or garrison) court, criminal, first instance
  1-19/2023 (1-83/2022;)          current number plus earlier numbers in parentheses
  01-0123/2023 (01-0456/2022)     Moscow district courts (mos-gorsud.ru numbering)
  2-18/2026, 2-0097/2025          regional-level or district military court, criminal, first instance
                                  (2-0xxx zero padded = Moscow City Court style)
  2-2-29/2025, 1-3-00001/2013     sub-prefixed variants used by some courts
  22-1234/2023                    appeal in a regional-level court
  55-123/2024                     appeal in an appellate court of general jurisdiction
  01-0001/208/2022                Moscow magistrate courts (judicial section 208)
  12302410007000017               investigative case number (Investigative Committee etc.); kept separately
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DOCKET_RE = re.compile(r"(?<![\d-])(\d{1,2}(?:-\d{1,2})?)-(\d{1,6})(?:/(\d{1,4}))?/(\d{4})")
INVESTIGATIVE_RE = re.compile(r"\b\d{11,20}\b")


@dataclass
class Docket:
    raw: str
    prefix: str
    number: str
    year: int
    section: str = ""

    @property
    def key(self) -> str:
        """Comparison key: leading zeros removed so 01-0123/2023 == 1-30/2023 style variants line up."""
        pre = "-".join(str(int(p)) for p in self.prefix.split("-"))
        sec = f"/{int(self.section)}" if self.section else ""
        return f"{pre}-{int(self.number)}{sec}/{self.year}"

    @property
    def strict_key(self) -> str:
        return f"{self.prefix}-{self.number}/{self.year}"

    @property
    def head(self) -> str:
        return self.prefix.split("-")[0]

    @property
    def zero_padded(self) -> bool:
        return self.number.startswith("0") or self.prefix.startswith("0")

    def level_hint(self, iso: str = "") -> str:
        """Best guess of the court level that issued this number."""
        h = self.head
        if self.section:
            return "magistrate"
        moscow = "RU-MOW" in (iso or "")
        if h in ("01", "1") and self.prefix.startswith("0"):
            return "mosgorsud_district"
        if h == "1":
            return "district"            # district or garrison military court
        if h == "2":
            if moscow and self.zero_padded:
                return "mosgorsud_city"
            return "regional_or_military"  # regional court or district military court
        if h == "22":
            return "regional_appeal"
        if h == "55":
            return "appellate"
        return "unknown"


@dataclass
class DocketSet:
    raw: str
    current: Docket | None = None
    prior: list[Docket] = field(default_factory=list)
    investigative: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[Docket]:
        return ([self.current] if self.current else []) + self.prior

    @property
    def keys(self) -> set[str]:
        return {d.key for d in self.all}


def parse_dockets(raw: str) -> DocketSet:
    raw = (raw or "").strip()
    ds = DocketSet(raw=raw)
    found = [Docket(m.group(0), m.group(1), m.group(2), int(m.group(4)), m.group(3) or "")
             for m in DOCKET_RE.finditer(raw)]
    ds.investigative = INVESTIGATIVE_RE.findall(raw)
    if found:
        ds.current, ds.prior = found[0], found[1:]
    return ds


def docket_key(s: str) -> str:
    """Key for a docket string found on a court page ('' if none)."""
    m = DOCKET_RE.search(s or "")
    if not m:
        return ""
    return Docket(m.group(0), m.group(1), m.group(2), int(m.group(4)), m.group(3) or "").key
