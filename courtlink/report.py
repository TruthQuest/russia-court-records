"""Static HTML report in the Trace Origin house style (Fraunces / Inter / JetBrains Mono, paper palette,
numbered figures with mono captions, inline SVG drawn here, no JavaScript). Pastes into a Ghost HTML card.

render(data) -> str. `data` comes from export_html.build().
"""
from __future__ import annotations

import html
import math
from collections import Counter, defaultdict

PAPER, INK, MUTE, FAINT, RULE = "#FBF9F1", "#171412", "#5F564C", "#9A9080", "#C4BBA4"
COURT, MODEL, GREEN, AMBER = "#7C1D1D", "#1F3A5F", "#5F8A5F", "#A07A30"
TYPE_COL = {"district": MODEL, "regional": AMBER, "military_district": COURT}
TYPE_EN = {"district": "District / city court", "regional": "Regional-level court", "military_district": "District military court"}
MONO, SANS, SERIF = "JetBrains Mono, monospace", "Inter, sans-serif", "Fraunces, serif"

CSS = """
  *{margin:0;padding:0;box-sizing:border-box}
  :root{--bg:#F1EDE1;--ink:#171412;--ink-mute:#5F564C;--ink-faint:#9A9080;--rule:#C4BBA4;--court:#7C1D1D;--model:#1F3A5F;--paper:#FBF9F1;--green:#5F8A5F;--amber:#A07A30}
  body{font-family:'Inter',sans-serif;color:var(--ink);font-size:17px;line-height:1.55;background:var(--bg)}
  .wrap{max-width:1120px;margin:0 auto;padding:0 32px}
  .section{padding:72px 0}
  .section-num{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--court);margin-bottom:24px}
  h2{font-family:'Fraunces',serif;font-variation-settings:"SOFT" 30,"opsz" 96;font-weight:400;font-size:clamp(32px,4.5vw,52px);line-height:1.05;letter-spacing:-.025em;max-width:900px;margin-bottom:28px}
  h2 em{font-style:italic;font-variation-settings:"SOFT" 100,"opsz" 96;font-weight:300;color:var(--court)}
  h3{font-family:'Fraunces',serif;font-variation-settings:"SOFT" 40,"opsz" 36;font-weight:500;font-size:24px;line-height:1.2;margin:40px 0 16px}
  p{margin-bottom:20px;max-width:720px}
  ul.plain{margin:0 0 20px 22px;max-width:720px}
  ul.plain li{margin-bottom:10px}
  p.large{font-family:'Fraunces',serif;font-variation-settings:"SOFT" 60,"opsz" 24;font-weight:400;font-size:22px;line-height:1.45;color:var(--ink-mute);max-width:780px;margin-bottom:40px}
  .numbers{background:var(--ink);color:var(--paper);padding:64px 32px}
  .numbers-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:48px;max-width:1120px;margin:0 auto}
  @media (max-width:760px){.numbers-grid{grid-template-columns:1fr;gap:32px}.wrap{padding:0 16px}}
  .stat .n{font-family:'Fraunces',serif;font-variation-settings:"SOFT" 20,"opsz" 144;font-weight:400;font-size:clamp(32px,3.5vw,48px);line-height:1;letter-spacing:-.03em;color:var(--paper);margin-bottom:10px;white-space:nowrap}
  .stat .l{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);line-height:1.6}
  .fig{margin:48px 0 8px;max-width:900px}
  .fig svg{display:block;width:100%;height:auto;background:var(--paper);border:1px solid var(--rule)}
  .fig-caption{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.06em;color:var(--ink-mute);margin-top:12px;max-width:780px;line-height:1.6}
  .fig-caption .lbl{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--court);margin-right:10px}
  .pullquote{font-family:'Fraunces',serif;font-variation-settings:"SOFT" 100,"opsz" 72;font-style:italic;font-weight:300;font-size:clamp(22px,2.8vw,34px);line-height:1.3;color:var(--ink);margin:56px 0;max-width:780px;padding-left:28px;border-left:2px solid var(--court)}
  .method-note{margin:32px 0;padding:24px 28px;border-left:3px solid var(--model);background:var(--paper);font-size:15px;color:var(--ink-mute);line-height:1.6;max-width:820px}
  .method-note .tag{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--model);margin-bottom:10px;display:block}
  .method-note.revision{border-left-color:var(--court)}
  .method-note.revision .tag{color:var(--court)}
  .method-note p{max-width:none;margin-bottom:12px}
  .method-note p:last-child{margin-bottom:0}
  .tbl-wrap{overflow-x:auto;max-width:900px;margin:40px 0 8px}
  table.tbl{border-collapse:collapse;width:100%;background:var(--paper);border:1px solid var(--rule);font-size:14px}
  table.tbl th{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-mute);text-align:left;padding:12px 14px;border-bottom:1px solid var(--rule);font-weight:500}
  table.tbl td{padding:10px 14px;border-bottom:1px solid #E4DDCB;vertical-align:top}
  table.tbl td.num{font-family:'JetBrains Mono',monospace;font-size:13px;white-space:nowrap}
  table.tbl tr.hl td{background:rgba(124,29,29,.05)}
  table.tbl tr:last-child td{border-bottom:none}
  .tag-ok{color:var(--green);font-weight:600}
  .tag-no{color:var(--court);font-weight:600}
  .tag-mid{color:var(--amber);font-weight:600}
  .link-block{margin:56px 0;padding:48px 40px;background:var(--ink);border-radius:2px;text-align:center}
  .link-block .heading{font-family:'Fraunces',serif;font-variation-settings:"SOFT" 40,"opsz" 36;font-size:26px;color:var(--paper);margin-bottom:20px}
  .link-block .fine{font-size:11px;color:var(--ink-faint);margin-top:24px;line-height:1.7}
"""

SERIES = [
    ("Part I", "https://www.traceoriginresearch.com/what-a-knowledge-graph-found-in-7-111-russian-prosecution-records-that-no-single-case-file-could-show/",
     "found three groups of charges in OVD-Info records: speech, organizational, and protest."),
    ("Part II", "https://www.traceoriginresearch.com/who-is-inside-the-machine-what-217-814-triples-reveal-about-the-people-russia-prosecutes/",
     "described the 6,702 people in those records: their charges, their imprisonment rates, and the severity gradient from treason (88%) to undesirable organization (8%)."),
    ("Part III", "https://www.traceoriginresearch.com/two-databases-one-person-what-happens-when-you-merge-7-111-russian-prosecutions-with-400-000-sanctioned-entities/",
     "merged OVD-Info's records with 400,000 sanctioned entities. 135 people appear in both databases."),
    ("Part IV", "https://www.traceoriginresearch.com/45-children-in-russias-prosecution-machine-what-happens-when-the-system-that-doesnt-distinguish-targets-someone-under-18/",
     "documented 45 children charged under the same political articles as adults, the youngest age 14."),
    ("Part V", "https://www.traceoriginresearch.com/what-a-knowledge-graph-found-across-five-authoritarian-systems-one-million-soviet-records-and-the-six-categories-of-political-prosecution-that-keep-coming-back/",
     "compared charge co-occurrence in Soviet, Belarusian, Myanmar, Cuban, and modern Russian records."),
    ("Part VI", "", "measured how the co-occurrence of charges in OVD-Info's records changed over fourteen years, and closed by noting that evidence about courts and personnel was needed and not yet in hand."),
]


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def n(x) -> str:
    return f"{x:,}"


def pct(x, d=0) -> str:
    return f"{100 * x:.{d}f}%"


# ---------------------------------------------------------------- svg helpers
def svg_open(w, h, title):
    return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"><rect width="{w}" height="{h}" fill="{PAPER}"/>'
            f'<text x="{w / 2}" y="22" font-family="{MONO}" font-size="9" fill="{FAINT}" letter-spacing=".12em" '
            f'text-anchor="middle">{e(title.upper())}</text>')


def t(x, y, s, size=8, fill=MUTE, anchor="start", font=SANS, weight=None, italic=False):
    w = f' font-weight="{weight}"' if weight else ""
    i = ' font-style="italic"' if italic else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{w}{i}>{e(s)}</text>'


def fig(svg, num, caption):
    return f'<div class="fig">{svg}<div class="fig-caption"><span class="lbl">Fig. {num}</span> {caption}</div></div>'


def table(header, rows, hl=None, num_cols=()):
    hl = hl or set()
    th = "".join(f"<th>{h}</th>" for h in header)
    body = []
    for i, r in enumerate(rows):
        tds = "".join(f'<td class="num">{c}</td>' if j in num_cols else f"<td>{c}</td>" for j, c in enumerate(r))
        body.append(f'<tr{" class=\"hl\"" if i in hl else ""}>{tds}</tr>')
    return f'<div class="tbl-wrap"><table class="tbl"><tr>{th}</tr>{"".join(body)}</table></div>'


def table_caption(num, text):
    return f'<div class="fig-caption"><span class="lbl">Fig. {num}</span> {text}</div>'


def hbars(title, rows, maxv=None, fmt=n, color=MODEL, label_w=230, w=700):
    """rows: [(label, value, highlight?)]"""
    rh, top = 26, 44
    h = top + rows.__len__() * rh + 20
    maxv = maxv or max(v for _, v, _ in rows) or 1
    x0, x1 = label_w, w - 70
    s = [svg_open(w, h, title)]
    for i, (lab, v, hlite) in enumerate(rows):
        y = top + i * rh
        s.append(t(x0 - 10, y + 13, lab, 8, INK if hlite else MUTE, "end", weight=600 if hlite else None))
        bw = max(1.5, (x1 - x0) * v / maxv)
        s.append(f'<rect x="{x0}" y="{y + 4}" width="{bw:.1f}" height="12" fill="{COURT if hlite else color}" opacity="{0.9 if hlite else 0.8}"/>')
        s.append(t(x0 + bw + 6, y + 13, fmt(v), 8, INK, font=MONO))
    s.append(f'<line x1="{x0}" y1="{top - 4}" x2="{x0}" y2="{top + len(rows) * rh}" stroke="{RULE}" stroke-width="1"/>')
    return "".join(s) + "</svg>"


# ---------------------------------------------------------------- figures
def fig_schema(classes):
    W, H = 700, 360
    N = {"rec": (72, 52, "OVD-Info record", "PersecutionRecord"), "link": (340, 52, "Record-registration link", "RecordRegistrationLink"),
         "rule": (95, 135, "Matching rule", "MatchingRule"), "reg": (350, 180, "Court registration", "CourtRegistration"),
         "proc": (500, 58, "Proceeding (UID)", "Proceeding"), "src": (630, 150, "Card (sha256)", "SourceDocument"),
         "court": (600, 250, "Court", "Court"), "post": (470, 305, "Judicial post", "JudicialPost"),
         "person": (640, 335, "Person", "foaf:Person"), "art": (360, 325, "Article", "skos:Concept"),
         "out": (185, 325, "Result at date", "skos:Concept"), "clu": (115, 240, "Co-registration cluster", "CoRegistrationCluster")}
    E = [("link", "rec", "linksRecord"), ("link", "reg", "linksRegistration"), ("link", "rule", "matchedBy"),
         ("reg", "proc", "registrationOf"), ("proc", "court", "firstRegisteredAt"), ("reg", "src", "wasDerivedFrom"),
         ("reg", "court", "heldAt"), ("reg", "post", "cardJudge"), ("post", "court", "org:organization"),
         ("post", "person", "org:member"), ("reg", "art", "recorded/courtListedArticle", .72),
         ("reg", "out", "hasOutcome, outcomeAsOf", .7), ("reg", "clu", "inCluster")]
    s = [svg_open(W, H, "The CourtLink graph (version 0.3): classes and properties"),
         f'<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
         f'<path d="M0,0L10,5L0,10z" fill="{FAINT}"/></marker></defs>']

    def bw(k):
        return max(len(N[k][2]), len(N[k][3]) + 6) * 5.0 + 16

    for ed in E:
        a, b, lab = ed[:3]
        fr = ed[3] if len(ed) > 3 else .5
        (x1, y1), (x2, y2) = N[a][:2], N[b][:2]
        dx, dy = x2 - x1, y2 - y1
        tt = min(abs((bw(b) / 2) / (dx or 1e-9)), abs(17 / (dy or 1e-9)))
        ex, ey = x2 - dx * tt, y2 - dy * tt
        s.append(f'<line x1="{x1}" y1="{y1}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{FAINT}" stroke-width="1" marker-end="url(#ar)"/>')
        mx, my = x1 + (ex - x1) * fr, y1 + (ey - y1) * fr
        s.append(f'<text x="{mx:.1f}" y="{my - 3:.1f}" font-family="{MONO}" font-size="6.2" fill="{FAINT}" text-anchor="middle" '
                 f'paint-order="stroke" stroke="{PAPER}" stroke-width="3">{e(lab)}</text>')
    cnt = {"rec": classes.get("PersecutionRecord"), "link": classes.get("RecordRegistrationLink"),
           "reg": classes.get("CourtRegistration"), "proc": classes.get("Proceeding"), "src": classes.get("SourceDocument"),
           "post": classes.get("JudicialPost"), "person": classes.get("Person"), "clu": classes.get("CoRegistrationCluster"),
           "court": classes.get("CourtHolding")}
    for k, (x, y, lab, cls) in N.items():
        w = bw(k)
        hub = k == "reg"
        s.append(f'<rect x="{x - w / 2:.1f}" y="{y - 17}" width="{w:.1f}" height="34" fill="{PAPER}" stroke="{COURT if hub else RULE}" stroke-width="{1.6 if hub else 1}"/>')
        s.append(t(x, y - 3, lab, 8.3, COURT if hub else INK, "middle", SERIF))
        sub = (cls if ":" in cls else "cl:" + cls) + (f" · {n(cnt[k])}" if cnt.get(k) else "")
        s.append(t(x, y + 10, sub, 6.3, FAINT, "middle", MONO))
    return "".join(s) + "</svg>"


def fig_network(nodes, links):
    """Courts (ringed) with their judges (filled) arranged around them, one cluster per region."""
    courts = [x for x in nodes if x["kind"] == "court"]
    judges = [x for x in nodes if x["kind"] == "judge"]
    key = lambda c: "Military courts" if c["type"] == "military_district" else c["region"]
    groups = defaultdict(list)
    for c in courts:
        groups[key(c)].append(c)
    order = sorted(groups, key=lambda k: -sum(c["n"] for c in groups[k]))
    court_of = {c["id"]: c for c in courts}
    jr = lambda j: 1.6 + math.sqrt(j["n"]) * 1.3
    cr = lambda c: 3 + math.sqrt(c["n"]) * 1.9
    W, cols = 700, 4
    rows = math.ceil(len(order) / cols)
    cell_w, cell_h, top = W / cols, 200, 40
    H = top + rows * cell_h + 34
    s = [svg_open(W, H, "Courts and their judges, by region")]
    for gi, k in enumerate(order):
        cx = (gi % cols + 0.5) * cell_w
        cy = top + (gi // cols) * cell_h + 105
        cs = sorted(groups[k], key=lambda c: -c["n"])
        js_of = {c["id"]: [j for j in judges if j["id"].split(":")[0] == c["id"]] for c in cs}
        foot = lambda c: cr(c) + 3 + 2 * max([jr(j) for j in js_of[c["id"]]] or [0]) + 2
        # phyllotaxis packing of courts, judges on a ring around their court
        spacing = 2 * max(foot(c) for c in cs) * 0.95
        P = {}
        for i2, c in enumerate(cs):
            r_ = spacing * math.sqrt(i2) * 0.62
            th = i2 * 2.39996
            P[c["id"]] = (r_ * math.cos(th), r_ * math.sin(th))
        ext = max(math.hypot(*p) + foot(c) for c, p in ((c, P[c["id"]]) for c in cs))
        sc = min(1.0, 80 / ext) if ext else 1.0
        P = {kk: (cx + x * sc, cy + y * sc) for kk, (x, y) in P.items()}
        s.append(t(cx, cy - min(ext * sc, 80) - 12, k.upper(), 7.5, MUTE, "middle", MONO))
        for c in cs:
            x0, y0 = P[c["id"]]
            js = js_of[c["id"]]
            for q, jd in enumerate(js):
                ang = -math.pi / 2 + 2 * math.pi * q / max(len(js), 1)
                d = cr(c) + 2 + jr(jd)
                x, y = x0 + d * math.cos(ang), y0 + d * math.sin(ang)
                s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{jr(jd):.1f}" fill="{TYPE_COL.get(jd["type"], MODEL)}" opacity="0.85"/>')
            s.append(f'<circle cx="{x0:.1f}" cy="{y0:.1f}" r="{cr(c):.1f}" fill="{PAPER}" stroke="{TYPE_COL.get(c["type"], MODEL)}" stroke-width="1.5"/>')
    ly = H - 16
    lx = 40
    for tp, lab in TYPE_EN.items():
        s.append(f'<circle cx="{lx}" cy="{ly - 3}" r="4" fill="{TYPE_COL[tp]}"/>'); s.append(t(lx + 8, ly, lab, 8)); lx += 150
    s.append(f'<circle cx="{lx + 4}" cy="{ly - 3}" r="5" fill="{PAPER}" stroke="{MUTE}" stroke-width="1.4"/>')
    s.append(t(lx + 14, ly, "court (ringed); judges filled; size = linked defendants", 8))
    return "".join(s) + "</svg>"


def fig_heat(heat, arts, types):
    W = 700
    left, top, cw, ch = 270, 62, 140, 18
    H = top + len(arts) * ch + 20
    s = [svg_open(W, H, "Records by article (as recorded by OVD-Info) and court level")]
    mx = max((h["n"] for h in heat), default=1) or 1
    cols = list(types)
    for i, c in enumerate(cols):
        s.append(t(left + i * cw + cw / 2, top - 10, types[c], 7.5, TYPE_COL.get(c, MUTE), "middle", MONO))
    for j, a in enumerate(arts):
        g = next(h["gloss"] for h in heat if h["art"] == a)
        s.append(t(left - 10, top + j * ch + 12, f"{a}  {g}", 8, MUTE, "end"))
    for h in heat:
        i, j = cols.index(h["type"]), arts.index(h["art"])
        x, y = left + i * cw + 1, top + j * ch + 1
        if h["n"]:
            op = 0.12 + 0.88 * (h["n"] / mx) ** 0.6
            s.append(f'<rect x="{x}" y="{y}" width="{cw - 2}" height="{ch - 2}" fill="{TYPE_COL.get(h["type"], MODEL)}" opacity="{op:.2f}"/>')
            s.append(t(x + cw / 2 - 1, y + 11.5, h["n"], 8, PAPER if op > 0.55 else INK, "middle", MONO))
        else:
            s.append(f'<rect x="{x}" y="{y}" width="{cw - 2}" height="{ch - 2}" fill="#E4DDCB" opacity="0.45"/>')
    return "".join(s) + "</svg>"


def fig_years(by_year, types):
    W, H, l, r, top, b = 700, 300, 50, 20, 44, 40
    tot = lambda d: sum(d[k] for k in types)
    mx = max((tot(d) for d in by_year), default=1)
    mx = int(math.ceil(mx / 10.0) * 10) or 10
    s = [svg_open(W, H, "Linked decisions by year and court level")]
    y = lambda v: H - b - (H - b - top) * v / mx
    for v in range(0, mx + 1, max(10, mx // 5)):
        s.append(f'<line x1="{l}" y1="{y(v):.1f}" x2="{W - r}" y2="{y(v):.1f}" stroke="{RULE}" stroke-width="0.5" opacity="0.5"/>')
        s.append(t(l - 6, y(v) + 3, v, 7.5, FAINT, "end", MONO))
    bw = (W - l - r) / max(len(by_year), 1)
    for i, d in enumerate(by_year):
        x = l + i * bw + bw * 0.2
        base = 0
        for k in types:
            if d[k]:
                s.append(f'<rect x="{x:.1f}" y="{y(base + d[k]):.1f}" width="{bw * 0.6:.1f}" height="{y(base) - y(base + d[k]) - 1:.1f}" fill="{TYPE_COL[k]}" opacity="0.85"/>')
                base += d[k]
        if base:
            s.append(t(x + bw * 0.3, y(base) - 5, base, 7.5, INK, "middle", MONO))
        s.append(t(x + bw * 0.3, H - b + 14, d["year"], 7.5, FAINT, "middle", MONO))
    lx = l
    for k, lab in types.items():
        s.append(f'<rect x="{lx}" y="{H - 14}" width="10" height="8" fill="{TYPE_COL[k]}" opacity="0.85"/>'); s.append(t(lx + 14, H - 7, lab, 8)); lx += 160
    return "".join(s) + "</svg>"


def fig_split(groups):
    W = 700
    rowh, top = 74, 44
    H = top + len(groups) * rowh + 6
    s = [svg_open(W, H, "Registrations with near-consecutive docket numbers, by judge listed on the card")]
    pal = [COURT, MODEL, GREEN]
    court_judges = defaultdict(list)
    for g in groups:
        for c in g["cases"]:
            if c["judge"] not in court_judges[g["court"]]:
                court_judges[g["court"]].append(c["judge"])
    for i, g in enumerate(groups):
        y0 = top + i * rowh
        s.append(t(30, y0 + 10, f'{g["court"]} · {g["articles"]}', 8.5, INK, font=SERIF))
        seqs = [c["seq"] for c in g["cases"]]
        lo, hi = min(seqs) - 1, max(seqs) + 1
        X = lambda v: 60 + (W - 120) * (v - lo) / (hi - lo)
        yl = y0 + 34
        s.append(f'<line x1="60" y1="{yl}" x2="{W - 60}" y2="{yl}" stroke="{RULE}" stroke-width="1"/>')
        for c in g["cases"]:
            col = pal[court_judges[g["court"]].index(c["judge"]) % 3]
            s.append(f'<circle cx="{X(c["seq"]):.1f}" cy="{yl}" r="6" fill="{col}" stroke="{PAPER}" stroke-width="1.5"/>')
        for c in g["cases"]:
            s.append(t(X(c["seq"]), yl + 18, c["docket"], 6.5, FAINT, "middle", MONO))
        lx = W - 60
        for jn in reversed(sorted({c["judge"] for c in g["cases"]})):
            col = pal[court_judges[g["court"]].index(jn) % 3]
            short = jn.split()[0] + " " + "".join(p[0] + "." for p in jn.split()[1:3])
            k = sum(1 for c in g["cases"] if c["judge"] == jn)
            lab = f"{short} ({k})"
            wlab = len(lab) * 4.6 + 16
            lx -= wlab
            s.append(f'<circle cx="{lx + 4:.1f}" cy="{y0 + 7}" r="3.5" fill="{col}"/>'); s.append(t(lx + 10, y0 + 10, lab, 7.5))
    return "".join(s) + "</svg>"


def fig_gap(by_article):
    rows = by_article[:14]
    W, left = 700, 270
    rh, top = 24, 44
    H = top + len(rows) * rh + 34
    mx = max(r["cases"] for r in rows) or 1
    s = [svg_open(W, H, "Political-article cases on court sites: linked and not linked to an OVD-Info record")]
    for i, r in enumerate(rows):
        y = top + i * rh
        s.append(t(left - 10, y + 12, r["artEn"].replace("Art. ", ""), 8, MUTE, "end"))
        w1 = (W - left - 70) * r["linked"] / mx
        w2 = (W - left - 70) * (r["cases"] - r["linked"]) / mx
        if w1:
            s.append(f'<rect x="{left}" y="{y + 4}" width="{w1:.1f}" height="11" fill="{MODEL}" opacity="0.85"/>')
        s.append(f'<rect x="{left + w1 + (1 if w1 else 0):.1f}" y="{y + 4}" width="{max(w2, 0):.1f}" height="11" fill="{COURT}" opacity="0.8"/>')
        s.append(t(left + w1 + w2 + 6, y + 12, f'{n(r["cases"] - r["linked"])} / {n(r["cases"])}', 8, INK, font=MONO))
    s.append(f'<rect x="{left}" y="{H - 16}" width="10" height="8" fill="{MODEL}"/>' + t(left + 14, H - 9, "linked to an OVD-Info record", 8))
    s.append(f'<rect x="{left + 190}" y="{H - 16}" width="10" height="8" fill="{COURT}"/>' + t(left + 204, H - 9, "no OVD-Info record linked", 8))
    return "".join(s) + "</svg>"


def fig_assign(r):
    rows = sorted(r["dist"], key=lambda d: -d["political"])
    W, left = 700, 220
    rh, top = 22, 44
    H = top + len(rows) * rh + 30
    mx = max(max(d["political"], d["expected"]) for d in rows) or 1
    X = lambda v: left + (W - left - 70) * v / mx
    s = [svg_open(W, H, f'{r["courtEn"]}: political cases per judge against the court\'s own baseline')]
    for i, d in enumerate(rows):
        y = top + i * rh
        s.append(t(left - 10, y + 12, d["judge"], 8, MUTE, "end"))
        s.append(f'<rect x="{left}" y="{y + 4}" width="{max(1.5, X(d["political"]) - left):.1f}" height="11" fill="{COURT}" opacity="0.8"/>')
        s.append(f'<line x1="{X(d["expected"]):.1f}" y1="{y + 1}" x2="{X(d["expected"]):.1f}" y2="{y + 18}" stroke="{INK}" stroke-width="1.6"/>')
        s.append(t(max(X(d["political"]), X(d["expected"])) + 6, y + 12, d["political"], 8, INK, font=MONO))
    s.append(f'<rect x="{left}" y="{H - 16}" width="10" height="8" fill="{COURT}"/>' + t(left + 14, H - 9, "political cases presided", 8))
    s.append(f'<line x1="{left + 170}" y1="{H - 18}" x2="{left + 170}" y2="{H - 6}" stroke="{INK}" stroke-width="1.6"/>' + t(left + 178, H - 9, "expected from the court's other criminal cases", 8))
    return "".join(s) + "</svg>"


def fig_intervals(O):
    rows = sorted(sorted(O["judges"], key=lambda d: -d["decided"])[:28], key=lambda d: d["shrunk_rate"])
    W, left, top = 700, 260, 50
    rh = 18
    H = top + len(rows) * rh + 34
    mx = min(1.0, max(d["ci90_high"] for d in rows) * 1.08)
    X = lambda v: left + (W - left - 30) * v / mx
    s = [svg_open(W, H, "Share of decided political cases ending without a verdict, per judge (shrunk, 90% interval)")]
    for v in [0, .1, .2, .3, .4, .5, .6, .8, 1.0]:
        if v <= mx:
            s.append(f'<line x1="{X(v):.1f}" y1="{top - 6}" x2="{X(v):.1f}" y2="{top + len(rows) * rh}" stroke="{RULE}" stroke-width="0.5" opacity="0.5"/>')
            s.append(t(X(v), top - 10, pct(v), 7, FAINT, "middle", MONO))
    pr = O["prior"]["pooled_rate"]
    s.append(f'<line x1="{X(pr):.1f}" y1="{top - 6}" x2="{X(pr):.1f}" y2="{top + len(rows) * rh}" stroke="{MODEL}" stroke-width="1" stroke-dasharray="4,3"/>')
    for i, d in enumerate(rows):
        y = top + i * rh + 9
        col = COURT if d["flag"] else MODEL
        nm = d["judgeEn"].split()[0] + " " + "".join(p[0] + "." for p in d["judgeEn"].split()[1:3])
        s.append(t(left - 10, y + 3, f'{nm} · {d["courtEn"].split(" District")[0].split(" City")[0]} ({d["decided"]})', 7.5, INK if d["flag"] else MUTE, "end", weight=600 if d["flag"] else None))
        s.append(f'<line x1="{X(d["ci90_low"]):.1f}" y1="{y}" x2="{X(d["ci90_high"]):.1f}" y2="{y}" stroke="{col}" stroke-width="1.4" opacity="0.6"/>')
        s.append(f'<circle cx="{X(d["shrunk_rate"]):.1f}" cy="{y}" r="3.5" fill="{col}"/>')
    s.append(t(X(pr) + 6, H - 10, f"pooled rate {pct(pr)}", 8, MODEL))
    return "".join(s) + "</svg>"


# ---------------------------------------------------------------- page
CITATIONS = [
    ("Art. 30(2) CPC", "composition of the court: which categories are heard by a panel of three judges or with a jury, and from which date"),
    ("Art. 31(3) and 31(6.1) CPC", "jurisdiction of regional-level courts and of district military courts by article; the amending laws and their dates"),
    ("Automated case distribution", "the provision requiring cases to be assigned to judges through an automated system, its effective date and its exceptions"),
    ("Art. 237 CPC", "return of a criminal case to the prosecutor"),
    ("Art. 25.1 CPC", "termination with a court fine"),
    ("Art. 154 CPC", "separation of a criminal case into separate proceedings"),
    ("Art. 354.1 UK RF", "the parts of the article and any jurisdiction rule that sends them to regional-level courts"),
    ("Prior work", "existing projects that have collected sudrf.ru case data at scale, to position this report"),
]


def render(D: dict) -> str:
    T = D["totals"]
    K = D.get("kg") or {}
    cls = K.get("classes", {})
    census = bool(K.get("has_census"))
    cov = D.get("coverage") or []
    regs = [r for r in D["regions"] if r["n"] >= 5]
    RT = D.get("regtest")
    PR = D.get("precision")
    A354 = D.get("a354") or {}
    judges = [x for x in D["nodes"] if x["kind"] == "judge"]
    repeat = sorted([j for j in judges if j["groups"] >= 2 or j["n"] >= 3], key=lambda j: (-j["groups"], -j["n"]))
    split = D.get("split") or []
    swept = len(regs)
    extra = sum(r["n"] for r in D["regions"] if r["n"] < 5)
    reg_phrase = f"{swept} regions" + (f" (plus {extra} record{'s' if extra != 1 else ''} elsewhere)" if extra else "")
    cov_tot = (sum(r["matched"] for r in cov), sum(r["searched"] for r in cov))
    unsearched = sum(r.get("courts_unsearched", 0) for r in cov)
    obstructed = sum(r.get("cases_obstructed", 0) for r in cov)
    rereg = K.get("reregistered", [])
    same = K.get("same_judge", [])
    figno = iter(range(1, 60))
    P = []
    a = P.append
    pv = lambda p: "&lt; 0.001" if p < 0.001 else f"{p:.3f}" if p < 0.1 else f"{p:.2f}"

    a(f'<div style="margin:0 -32px;background:var(--ink);padding:40px 32px;"><div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;'
      f'letter-spacing:.18em;text-transform:uppercase;color:var(--ink-faint)">Trace Origin LLC &middot; Part VII &middot; Data: OVD-Info, sudrf.ru '
      f'&middot; Draft for OVD-Info, {e(D["generated"])} &middot; Not for publication</div></div>')
    a('<div style="padding:32px 0 0;font-family:\'Inter\',sans-serif;font-size:14px;color:var(--ink-mute);max-width:720px;line-height:1.7">'
      '<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--court);margin-bottom:16px">The series so far</div>')
    for part, url, txt in SERIES:
        lab = f'<strong>{part}</strong>'
        if url:
            lab = f'<a href="{url}" style="color:var(--ink);text-decoration:none;border-bottom:1px solid var(--rule)">{lab}</a>'
        a(f'<p style="margin-bottom:10px">{lab} {e(txt)}</p>')
    a('<p style="margin-bottom:0"><strong style="color:var(--court)">Part VII (this report)</strong> links OVD-Info records to the courts\' own registrations of '
      'the cases, and to the judge each court lists for them.</p></div>')

    prec_txt = (f'A hand check of {PR["checked"]} randomly drawn links found {PR["correct"]} correct '
                f'(precision {pct(PR["precision"])}, 95% interval {pct(PR["ci95_low"])} to {pct(PR["ci95_high"])}).' if PR else
                'No hand check of the links has been done yet; a random sample of 50 is drawn for that purpose and its result will be reported here.')
    a('<div class="method-note revision"><span class="tag">Status of this draft</span>'
      f'<p>All record-to-registration links were made by written rules; none is cited individually here. {prec_txt}</p>'
      '<p>The page carries no defendant names and no record identifiers. Row-level links and card evidence are in the accompanying workbook.</p></div>')

    a('<div class="section" style="padding-bottom:40px">')
    a(f'<div class="section-num">Part VII &middot; OVD-Info &times; court registrations &middot; {n(T["records"])} records &middot; {e(reg_phrase)}</div>')
    a(f'<h2>{n(T["records"])} OVD-Info records, traced to the court registrations of their cases and the judges the courts <em>list.</em></h2>')
    a('<p class="large">OVD-Info documents who was prosecuted and under which articles. Its case narratives often name the court. What they do not provide, '
      'in structured and checkable form, is the court\'s own registration of the case: the docket number, the unified case identifier, the judge the court lists, '
      'and the first-instance result the court has posted. This report adds that layer for part of OVD-Info\'s records, with every value tied to a stored copy '
      'of the court page it came from.</p>')
    a(f'<p class="large">{n(T["records"])} records were linked to {n(T["registrations"])} court registrations, belonging to {n(T["cases"])} proceedings, '
      f'in {n(T["courts"])} courts. The courts list {n(T["judges"])} judge entries for them. By the date each page was retrieved, '
      f'{T["verdict_share"]}% of the records had a first-instance verdict posted; the courts\' result field does not say whether it convicted or acquitted.</p>')
    a('<p>These are findings about linked registrations in the regions searched. They are not estimates for Russian political prosecution as a whole, '
      'and they say nothing about how any judge reasoned. The tests that could bear on case assignment and on outcomes by judge are specified below with '
      'their decision rules; they need the full court census, which this draft does not yet include.' if not census else
      '<p>These are findings about linked registrations and the court census around them. Assignment and outcome results are leads to check, not conclusions about any judge.')
    a('</p></div>')

    a('<div class="numbers"><div class="numbers-grid">'
      f'<div class="stat"><div class="n">{n(T["records"])}</div><div class="l">OVD-Info records linked to<br>{n(T["registrations"])} court registrations<br>({n(T["cases"])} proceedings)</div></div>'
      f'<div class="stat"><div class="n">{n(T["judges"])}</div><div class="l">Judge entries listed on cards<br>(judge at one court; at least<br>{len(same)} probable duplicate{"s" if len(same) != 1 else ""})</div></div>'
      f'<div class="stat"><div class="n" style="color:var(--court)">{pct(cov_tot[0] / max(cov_tot[1], 1)) if cov else "n/a"}</div><div class="l">Docketed records linked in<br>the regions measured<br>({n(cov_tot[0])} of {n(cov_tot[1])})</div></div>'
      '</div></div>')

    # coverage
    a('<div class="section"><div class="section-num">what the analysis covers</div>')
    a(f'<h2>Records with a docket number, in {swept} regions, minus the courts that could not be <em>searched.</em></h2>')
    a('<p>A registration can only be found if there is something to search for. The search used OVD-Info\'s docket numbers, articles, city and dates, region by region, '
      'against each court\'s own search page. Two things limit what was searched. Some records carry no docket number. And some courts\' search pages could not be '
      'opened because their captchas were not answered in the session; those courts were not searched for the records that pointed to them.</p>')
    if cov:
        rows = [[e(r["region"]), n(r["docketed"]), n(r["matched"]), pct(r["matched"] / max(r["docketed"], 1)), n(r.get("courts_unsearched", 0)),
                 n(r.get("cases_obstructed", 0))] for r in cov]
        rows.append(["<strong>Total</strong>", f'<strong>{n(sum(r["docketed"] for r in cov))}</strong>', f'<strong>{n(cov_tot[0])}</strong>',
                     f'<strong>{pct(cov_tot[0] / max(cov_tot[1], 1))}</strong>', f"<strong>{n(unsearched)}</strong>", f"<strong>{n(obstructed)}</strong>"])
        a(table(["Region", "Records with a docket", "Linked", "Share", "Candidate courts not searched", "Records left unresolved by an unsearched court"],
                rows, hl={len(rows) - 1}, num_cols=(1, 2, 3, 4, 5)))
        a(table_caption(next(figno), "Coverage in the regions measured. \"Not searched\" means the court's search page was never opened successfully for at least one record "
                        "(captcha unanswered, blocked or error), from the search log of 15 October 2026. Obstruction counts from that run may be overstated for Sverdlovsk, "
                        "where earlier skipped captchas were later answered. Linked records in St Petersburg and Tatarstan are included in the findings; their coverage is not yet measured. "
                        "Moscow (mos-gorsud.ru), magistrate courts and occupied territories were not searched. Result lists were read up to 40 pages per search."))
    a('<div class="method-note"><span class="tag">What a link is, and is not</span>'
      '<p>A link joins one OVD-Info record to one court registration. It is the output of a rule, not a fact read off a page: the docket number must match, and the '
      'defendant\'s name, the decision date and the article then confirm or reject it. A registration listing an article that contradicts OVD-Info\'s is rejected even when '
      'the docket matches. Eight written rules are used, and every link records which one made it.</p>'
      '<p>A record is not a person: OVD-Info keeps one record per person per case, so one person can have several. A registration is not a proceeding: '
      f'a case transferred or re-registered receives a new docket number but keeps its unified identifier. Here {n(T["registrations"])} registrations belong to '
      f'{n(T["cases"])} proceedings' + (f'; {len(D.get("multi_reg", []))} proceeding{" appears" if len(D.get("multi_reg", [])) == 1 else "s appear"} under two registrations, '
      + ("after a transfer between courts" if all(m["courts"] > 1 for m in D.get("multi_reg", [])) else "after transfer or re-registration") if D.get("multi_reg") else "") + '. '
      'The judge is the one the court lists on its card; in courts that sit in panels this is the presiding or reporting judge only.</p></div></div>')

    # graph
    a('<div class="section" style="padding-top:0"><div class="section-num">the graph</div>')
    a('<h2>The registration is the hub; everything else is <em>qualified.</em></h2>')
    a('<p>Every number in this report is a query against a knowledge graph (CourtLink 0.3). Earlier parts put the person or the article at the centre. Here the centre is the '
      'court registration, because that is what a court enters, lists a judge for and posts a result against. The modelling choices that matter for interpretation:</p>')
    a('<ul class="plain">'
      '<li><strong>Proceeding and registration are distinct.</strong> The unified case identifier names the proceeding across transfers; the docket number names one court\'s registration of it.</li>'
      '<li><strong>Person and post are distinct.</strong> A judge is a person; service at a court is a post, dated by the first and last decisions observed. '
      f'Because persons cannot be identified across courts from surname and initials, each post has its own person node, and same-name pairs are marked as possibly the same ({len(same)} so far), never merged.</li>'
      '<li><strong>Results are observations at a date,</strong> classed as terminal (verdict, dismissal, court fine, compulsory medical measures) or interim (returned to the prosecutor, transferred, joined, pending).</li>'
      '<li><strong>Articles keep their source.</strong> Articles recorded by OVD-Info and articles listed by the court are separate properties. Criminal Code articles form a flat scheme: '
      'Art. 282.2 is not modelled as a kind of Art. 282.</li>'
      '<li><strong>Links are first-class</strong> and carry the rule and confidence that produced them. <strong>Absence is not evidence:</strong> an unlinked registration means "not linked in this dataset".</li></ul>')
    if cls:
        a(fig(fig_schema(cls), next(figno), f'Classes and properties of CourtLink 0.3 with instance counts. {n(K.get("triples", 0))} triples; the data validate against SHACL shapes, '
              f'including a shape that forbids broader/narrower links between articles and one that requires every result to carry its observation date. '
              f'The court count is courts holding linked registrations ({n(cls.get("CourtHolding", 0))}); the graph also holds {n(cls.get("CourtOriginOnly", 0))} courts known only as the place a proceeding was first registered.'))
    a(fig(fig_network(D["nodes"], D["links"]), next(figno),
          'Each ringed node is a court; each filled node is a judge entry (judge listed on the card at that court). District military courts, which serve several regions, are grouped separately. '
          'Node size is the number of linked records. Positions within a region carry no meaning beyond grouping.'))
    a('</div>')

    # outcomes
    term_share = T["verdict_share_terminal"]
    a('<div class="section" style="padding-top:0"><div class="section-num">results</div>')
    a('<h2>Most linked records have a verdict posted. Whether one region differs depends on what is <em>counted.</em></h2>')
    a(f'<p>By the date each card was retrieved, {T["verdict_share"]}% of the {n(T["records"])} linked records had a first-instance verdict (приговор) posted. '
      'A verdict can convict or acquit, and the courts\' result field does not say which. Some results are not endpoints: a case returned to the prosecutor (Art. 237 CPC) '
      f'can come back, a transfer moves it, and a pending case has no result yet. Counting only terminal results, {term_share}% of {n(T["terminal"])} records ended in a verdict.</p>')
    a(table(["Result posted on the card", "Records", "Share", "Terminal?"],
            [[e(o["k"]), n(o["n"]), pct(o["n"] / T["records"]), "yes" if o["terminal"] else "no (interim)"] for o in D["outcomes"]],
            hl={0}, num_cols=(1, 2)))
    a(table_caption(next(figno), "First-instance result classes, read from the court's result field at the time of retrieval and grouped. \"Verdict\" covers conviction and acquittal. "
                    "\"Compulsory medical measures\" is imposed by court order, not by verdict. Appeals are not followed."))
    if regs:
        lo_name = RT["region"] if RT else None
        a(fig(hbars("Share of linked records with a verdict posted, by region (all results)",
                    [(r["region"], r["verdict"] / r["n"], r["region"] == lo_name) for r in regs], maxv=1, fmt=pct), next(figno),
              "Regions with at least five linked records. All results in the denominator, including interim results and pending cases."))
        if RT:
            a(table(["Comparison", f'{e(RT["region"])}', "Other regions", "Fisher's exact p", f"Bonferroni (×{RT['k']})"],
                    [["All results", pct(RT["lo_share"]), pct(RT["rest_share"]), pv(RT["p_all"]), pv(RT["p_all_adj"])],
                     ["Terminal results only", pct(RT["lo_term_share"]) if RT["lo_term_share"] is not None else "n/a",
                      pct(RT["rest_term_share"]) if RT["rest_term_share"] is not None else "n/a",
                      pv(RT["p_term"]) if RT["p_term"] is not None else "n/a", pv(RT["p_term_adj"]) if RT["p_term_adj"] is not None else "n/a"]],
                    hl={1}, num_cols=(1, 2, 3, 4)))
            a(table_caption(next(figno), f'{e(RT["region"])} against the pooled other regions. The region was chosen because it was lowest, so p-values are multiplied by the number of regions compared. Post hoc.'))
            survives = RT["p_term_adj"] is not None and RT["p_term_adj"] < 0.05
            a(f'<p style="margin-top:40px">Counting all results, {e(RT["region"])} is lower than the other regions by a margin that survives correction for having picked it out '
              f'(p = {pv(RT["p_all_adj"])}). Counting only terminal results, the gap narrows to {pct(RT["lo_term_share"])} against {pct(RT["rest_term_share"])} and '
              + ("still survives correction." if survives else f"does not survive correction (p = {pv(RT['p_term_adj'])}).")
              + ' Most of the difference is interim results (returns to the prosecutor, transfers) and cases still pending. That is a difference in where cases '
              'stood when the pages were read, not evidence that courts in the region decide differently. The region was also searched first and most thoroughly, '
              'which this comparison cannot separate from anything else.</p>')
    a('</div>')

    # jurisdiction
    a('<div class="section" style="padding-top:0"><div class="section-num">jurisdiction</div>')
    a('<h2>Which court level hears which <em>article.</em></h2>')
    a('<p>The Criminal Procedure Code assigns some articles away from district courts. Under Art. 31 CPC, district military courts hear certain terrorism-related offences at '
      'first instance and regional-level courts hear a further list; the exact provisions, the amending laws and their dates are listed below as authorities still to be cited. '
      'The linked registrations are consistent with that routing. The figure uses the articles OVD-Info recorded, not the articles the courts list, so it shows where records '
      'carrying an article were heard, not the charge each court tried.</p>')
    a(fig(fig_heat(D["heat"], D["heat_arts"], D["types"]), next(figno),
          "Records by Criminal Code article as recorded by OVD-Info and the level of the court holding the linked registration. A record with several articles is counted under each. Fourteen most frequent articles."))
    if A354.get("regional"):
        a(f'<p style="margin-top:40px">One pattern needs explanation rather than assertion. {A354["regional"]} records carrying Art. 354.1 were heard by regional-level courts in '
          f'{A354["regional_courts"]} regions, {A354["regional_alone"]} of them with no other article recorded, and {A354.get("district", 0)} by district courts. Joinder with an article '
          'that carries regional jurisdiction does not explain the records where 354.1 stands alone. Either a provision assigns some parts of Art. 354.1 to regional-level courts, '
          'or these registrations were matched wrongly. Which it is requires the primary text of Art. 31 CPC and the cards themselves.</p>')
    a(fig(fig_years(D["by_year"], D["types"]), next(figno),
          f'Linked first-instance decisions by year of decision and court level. {D.get("partial_year", "")} is a partial year. Years with no bar have no linked decisions in this sample; '
          'they are gaps in coverage, not years without cases. The chart describes the linked sample, shaped by OVD-Info\'s coverage and by what court sites still publish.'))
    a('</div>')

    # clusters
    if split:
        a('<div class="section" style="padding-top:0"><div class="section-num">case numbering</div>')
        a('<h2>Near-consecutive registrations: a pattern to test, not yet a <em>finding.</em></h2>')
        a(f'<p>Counting registrations per judge treats each registration as a separate matter. Some are not obviously so. One rule, used throughout the graph, the workbook and this page, '
          f'groups registrations by {e(D.get("cluster_rule", ""))}. '
          f'{len(split)} clusters result.</p>')
        a(fig(fig_split(split), next(figno),
              "Each dot is a registration placed by its docket number and coloured by the judge listed on the card. In the two military-court clusters the courts may sit in panels, "
              "so different card judges do not show that different benches heard the cases."))
        v = split[0]
        if v["uid_years"] and v["docket_years"] and v["uid_years"] != v["docket_years"]:
            a(f'<p style="margin-top:40px">The largest cluster, at {e(v["court"])}, has a further detail. Its docket numbers are from {", ".join(v["docket_years"])}, '
              f'but its unified identifiers were opened in {", ".join(v["uid_years"])}. The proceedings therefore reached the court, or a court, two years before the dockets shown here, '
              'and were registered again. Why is not visible from the card list: a return to the prosecutor and resubmission is one possible route. '
              f'OVD-Info\'s start dates for these records also differ ({", ".join(v["started"]) if v["started"] else "none recorded"}).</p>')
        a('<p>Three readings fit the numbers. The registrations may come from one investigation separated into individual cases (Art. 154 CPC); from separate investigations '
          'submitted together; or from re-registration of earlier proceedings in one batch. Spreading such registrations across a court\'s judges is what automated distribution '
          'would be expected to do, so the spread is not itself anomalous. The readings can be told apart with evidence that is available but not yet collected:</p>')
        a('<ul class="plain"><li><strong>Investigative case numbers.</strong> OVD-Info records hold them for some cases; none of the clustered records carries one. The court cards may.</li>'
          '<li><strong>Registration dates and procedural history</strong> on each card, including any earlier return to the prosecutor.</li>'
          '<li><strong>The court\'s bench.</strong> If the judges observed are all the court\'s criminal judges, the spread is what allocation would produce.</li></ul>')
        a('<p>Until those are checked, the clusters are used only to avoid counting the same matter several times per judge.</p></div>')

    # judges
    a('<div class="section" style="padding-top:0"><div class="section-num">judges</div>')
    a('<h2>Judge entries with more than one linked <em>matter.</em></h2>')
    a('<p>Judge entries (judge at one court) with at least two clusters, counting each co-registration cluster once, or at least three linked records. Names are in English press '
      'spelling; the workbook also gives passport spelling (ICAO 9303, used when checking sanctions lists) and the Russian original. A dagger marks courts that may sit in panels, '
      'where the entry is the presiding or reporting judge only.</p>')
    a(table(["Judge listed on card", "Court", "Records", "Registrations", "Clusters counted once", "Articles (OVD-Info)", "Years"],
            [[e(j["name"]) + (" &dagger;" if j.get("panel") else ""), e(j["court"]), j["n"], j["cases"], f'<strong>{j["groups"]}</strong>', e(j["arts"]), e(j["years"])]
             for j in repeat], num_cols=(2, 3, 4)))
    a(table_caption(next(figno), "Small numbers. No ranking is implied: a judge's count reflects which OVD-Info records could be linked, not the judge's docket."))
    a('</div>')

    # census or decision rules
    if census:
        G = K["ovd_gap"]
        a('<div class="section" style="padding-top:0"><div class="section-num">the census</div>')
        a('<h2>What the court lists contain that OVD-Info records do not <em>link.</em></h2>')
        a(f'<p>Each article search returned the court\'s full list of registrations under that article. Classified by the articles the courts list, {n(G["political_cases"])} registrations '
          f'carry a political article; {n(G["linked"])} are linked to an OVD-Info record and {n(G["unlinked_cases"])}, with {n(G["unlinked_defendants"])} defendants, are not. '
          'These are candidates for OVD-Info to check, not people OVD-Info has missed.</p>')
        a(fig(fig_gap(G["by_article"]), next(figno), "Registrations per court-listed article, split by whether an OVD-Info record is linked. Closed-world reading over the census."))
        Aall = K.get("assignment", [])
        A = [r for r in Aall if r["q_value"] < 0.05 and not r.get("weak")]
        a('<h3>Assignment</h3>')
        a(f'<p>{len(Aall)} courts had enough registrations to test; in {len(A)} the political registrations depart from the court\'s own baseline of other criminal registrations in the same '
          'docket years (Monte Carlo test, Benjamini-Hochberg q &lt; 0.05, courts with a thin baseline excluded). A departure is evidence to examine, not proof of non-random assignment: '
          'lawful specialisation, leave and recusal also produce it.</p>')
        for r in A[:4]:
            a(fig(fig_assign(r), next(figno), f'{e(r["courtEn"])}: {r["political_cases"]} political registrations across {r["judges"]} judge entries and {r.get("years", "?")} docket years; '
                  f'baseline: {e(r["baseline"])}. p {pv(r["p_value"])}, q = {r["q_value"]:.3f}.'))
        O = K.get("judge_outcomes", {})
        if O.get("judges"):
            a('<h3>Terminal results by judge entry</h3>')
            a(fig(fig_intervals(O), next(figno), "Share of each judge entry's political registrations with a terminal result that did not end in a verdict. Interim results are excluded. "
                  "Shrunk toward the pooled rate (empirical-Bayes beta-binomial); lines are 90% intervals."))
        a('</div>')
    else:
        a('<div class="section" style="padding-top:0"><div class="section-num">decision rules</div>')
        a('<h2>What the court census will be allowed to <em>show.</em></h2>')
        a('<p>The article searches already run returned each court\'s full list of registrations under each political article. Parsed into a census, they support three tests. '
          'The rules for reading them are fixed here, before any result has been seen:</p>')
        a('<ul class="plain">'
          '<li><strong>Classification.</strong> Registrations are classed as political by the articles the court lists, never by OVD-Info\'s, so linked and unlinked registrations are treated alike.</li>'
          '<li><strong>OVD-Info blind spot.</strong> Political registrations with no linked record are reported as candidates for OVD-Info to check, never as missed people, and only as counts in any public version.</li>'
          '<li><strong>Assignment.</strong> Stratified by docket year, so a judge is expected to receive cases only in years the census shows them sitting at that court. A court is reported only if '
          'Benjamini-Hochberg q &lt; 0.05 across all courts tested, with at least eight political and twenty baseline registrations. The legal requirement of automated distribution, '
          'its date and its exceptions must be cited before any result is interpreted.</li>'
          '<li><strong>Results by judge entry.</strong> Terminal results only. An entry is reported as differing from the pool only if the 90% interval of the shrunk non-verdict rate excludes the pooled rate, '
          'with at least five terminal results. No judge is ranked. Panel courts are reported separately.</li></ul>')
        a('<p>The procedures were checked on synthetic data with planted effects before any real run: they recovered a planted concentration, did not flag a court with even allocation, '
          'did not flag a judge who sat only in years without political cases, and recovered a planted outlier.</p></div>')

    # authorities
    a('<div class="section" style="padding-top:0"><div class="section-num">authorities</div>')
    a('<h2>Legal and scholarly sources still to be <em>cited.</em></h2>')
    a('<p>This draft makes no claim that rests on these authorities without saying so. Each must be cited from the primary text, in the version in force at the relevant dates, before publication.</p>')
    a(table(["Authority", "Needed for"], [[e(x), e(y)] for x, y in CITATIONS]))
    a(table_caption(next(figno), "CPC: Criminal Procedure Code of the Russian Federation. UK RF: Criminal Code of the Russian Federation."))
    a('</div>')

    # limitations + methods
    a('<div class="section" style="padding-top:0"><div class="section-num">limitations</div>')
    a('<h2>What this analysis cannot <em>see</em></h2><ul class="plain">'
      f'<li><strong>Link precision.</strong> {e(prec_txt)}</li>'
      f'<li><strong>Partial coverage.</strong> {e(reg_phrase)}; {pct(cov_tot[0] / max(cov_tot[1], 1)) if cov else "an unmeasured share"} of docketed records in the measured regions; '
      f'{n(unsearched)} candidate courts not searched. Moscow, magistrate courts and occupied territories are absent.</li>'
      '<li><strong>Records, registrations and proceedings are different units,</strong> and each figure says which it counts.</li>'
      '<li><strong>Judge entries are per court</strong> and, in panel courts, name the presiding or reporting judge only.</li>'
      '<li><strong>Results are as of retrieval.</strong> Verdicts are not split into convictions and acquittals; appeals are not followed.</li>'
      '<li><strong>Articles in the jurisdiction figure are OVD-Info\'s,</strong> not the courts\'.</li>'
      '<li><strong>Clusters are a numbering heuristic.</strong> They support de-duplication, not any claim about investigations.</li>'
      '<li><strong>Post hoc analyses.</strong> The regional test and the terminal-result split were added after the first results were seen.</li>'
      '<li><strong>"Political" is OVD-Info\'s classification</strong> under its published criteria, not an adjudicated status.</li></ul>')
    a('<div class="method-note"><span class="tag">Methods and reproducibility</span>'
      '<p><strong>Data.</strong> OVD-Info public export; Russian court websites (sudrf.ru), first-instance criminal search results and case cards, retrieved October 2026; '
      'court directory from Dataout / sudrfparser (CC BY-SA 4.0, November 2023).</p>'
      '<p><strong>Search.</strong> For each region, candidate courts were searched by article and registration year, reading up to 40 result pages per search. Captchas were answered by a person, '
      'in batches, and never solved automatically; courts whose captchas were not answered were not searched and are counted in Fig. 1. Result rows were matched locally to OVD-Info '
      'records by docket number and confirmed or rejected by name, date and article under eight written rules; ties across courts went to human review.</p>'
      '<p><strong>Graph.</strong> CourtLink 0.3, OWL 2, reusing W3C ORG, PROV-O and SKOS terms; instance data in Turtle, validated with SHACL. Proceedings keyed by unified case identifier; '
      'registrations by court and docket. Judicial posts as org:Membership, persons per post, cross-court candidates as a symmetric, non-transitive possiblySameAs. '
      f'Results dated and classed terminal or interim. Articles flat, with source-specific properties. Co-registration clusters: {e(D.get("cluster_rule", ""))}.</p>'
      '<p><strong>Statistics.</strong> Regional comparison: Fisher\'s exact test of the lowest region against the rest, Bonferroni across regions, on all results and on terminal results (post hoc). '
      'Census tests (pending): year-stratified multinomial G test with 20,000 Monte Carlo draws and Benjamini-Hochberg across courts; beta-binomial empirical Bayes on terminal results with 90% intervals. '
      'Link precision: Wilson interval on a random sample of 50, hand-checked against the cards.</p>'
      '<p><strong>Privacy.</strong> No defendant names are stored in the census or shown here. Court cards name defendants, including some OVD-Info keeps anonymous; those links stay in the workbook.</p></div></div>')

    a('<div class="link-block"><div class="heading">'
      f'{n(T["records"])} OVD-Info records traced to {n(T["registrations"])} court registrations and the judges the courts list. The layer is evidenced; most interpretations still need their tests.</div>'
      '<div class="fine">'
      f'Linked: {n(T["records"])} records, {n(T["registrations"])} registrations, {n(T["cases"])} proceedings, {n(T["courts"])} courts, {e(reg_phrase)}. '
      f'Verdict posted for {T["verdict_share"]}% of records ({term_share}% of terminal results).<br>'
      + (f'Coverage in measured regions: {n(cov_tot[0])} of {n(cov_tot[1])} docketed records linked ({pct(cov_tot[0] / max(cov_tot[1], 1))}); {n(unsearched)} candidate courts not searched.<br>' if cov else "")
      + (f'Regional difference: p = {pv(RT["p_all_adj"])} on all results, {pv(RT["p_term_adj"])} on terminal results (Bonferroni, post hoc).<br>' if RT and RT["p_term_adj"] is not None else "")
      + f'Co-registration clusters: {len(split)}, untested as investigations. Graph: {n(K.get("triples", 0))} triples, SHACL-validated. '
      + ("Link precision: not yet estimated." if not PR else f'Link precision {pct(PR["precision"])} ({PR["correct"]}/{PR["checked"]}).') + '<br><br>'
      f'&copy; 2026 Trace Origin LLC. Data: OVD-Info (used with permission); sudrf.ru. Draft for OVD-Info, {e(D["generated"])}.</div></div>')

    head = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f'<title>{n(T["records"])} OVD-Info Records Traced to Court Registrations and the Judges the Courts List</title>\n'
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT@9..144,300..800,50..100&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">\n'
            f'<style>{CSS}</style>\n</head>\n<body>\n<div class="wrap">\n')
    return head + "\n".join(P) + "\n</div>\n</body>\n</html>\n"
