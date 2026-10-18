"""Co-registration clusters: one rule, used by the graph, the workbook and the report.

Registrations at the same court (and srv), with the same docket prefix and docket year, docket numbers within `gap`
of a neighbour (single linkage), at least one shared article, and the same registration date when both dates are known.
The rule says nothing about whether a cluster derives from one investigation; that is a separate, testable hypothesis.
"""
from __future__ import annotations

import collections
import re

DOCKET_NUM = re.compile(r"^(\d+(?:-\d+)?)-(\d+)/(\d{4})$")
DEFAULT_GAP = 5
RULE_TEXT = ("same court, docket prefix and docket year; docket numbers within {gap} of a neighbour; a shared article; "
             "the same registration date where both are known")


def docket_number(docket_key: str):
    m = DOCKET_NUM.match(docket_key or "")
    return (m.group(1), int(m.group(2)), m.group(3)) if m else None


def cluster(regs: dict, gap: int = DEFAULT_GAP) -> dict:
    """regs: key -> {court_id, srv, docket_key, articles:set, received:str}. Returns key -> cluster id."""
    by = collections.defaultdict(list)
    for k, c in regs.items():
        dn = docket_number(c["docket_key"])
        if dn and c["articles"]:
            by[(c["court_id"], c.get("srv") or "1", dn[0], dn[2])].append((dn[1], k))
    out = {}
    for (court, srv, pre, yr), items in by.items():
        items.sort()
        cur = [items[0]]

        def ok(a, b):
            ca, cb = regs[a[1]], regs[b[1]]
            if b[0] - a[0] > gap or not (ca["articles"] & cb["articles"]):
                return False
            return not (ca.get("received") and cb.get("received") and ca["received"] != cb["received"])

        for it in items[1:] + [None]:
            if it and ok(cur[-1], it):
                cur.append(it)
                continue
            if len(cur) > 1:
                cid = f"{court}_{pre}-{cur[0][0]}-{cur[-1][0]}_{yr}"
                for _, k in cur:
                    out[k] = cid
            cur = [it] if it else []
    return out
