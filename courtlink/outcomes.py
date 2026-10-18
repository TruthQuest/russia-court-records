"""Coarse classes of first-instance result texts, shared by the case-card and census steps."""
import re

OUTCOMES = [("joined_to_other_case", r"присоедин"), ("compulsory_medical", r"принудительн\w*\s+мер\w*\s+медицинск"),
            ("returned_to_prosecutor", r"возвращено\s+прокурор"), ("court_fine_dismissal", r"судебн\w*\s+штраф"),
            ("dismissed", r"прекращ"), ("transferred", r"направлен\w*\s+по\s+подсудност|передан"),
            ("verdict", r"приговор"), ("suspended", r"приостановлен")]


def outcome_class(result: str) -> str:
    """Coarse class of the first-instance result text, for analysis (verdict vs. ended without one)."""
    r = (result or "").lower()
    for cls, pat in OUTCOMES:
        if re.search(pat, r):
            return cls
    return "other" if r else "pending"  # no result on the card: still before the court
