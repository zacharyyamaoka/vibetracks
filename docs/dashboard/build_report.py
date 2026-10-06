#!/usr/bin/env python3
"""Build the media-rich review report for the three Vibe Tracks dashboard proposals.

    python3 /home/bam/vibetracks-dashboard/docs/dashboard/build_report.py

Writes ONE self-contained file:
    /home/bam/vibetracks/reports/media/vibetracks-dashboard-2026-10-04.html

WHY one file with everything inlined: Zach reviews by reading, not by clicking around
(/rate bad 2026-10-04). Every still and hero video is a data: URI, and each is inlined
exactly ONCE: the lightbox re-uses the clicked <img>'s src at runtime instead of a second copy.
WHY the scores are recomputed here: the judges' raw scores are the data; a hardcoded total
would silently outlive an edited score.
"""
from __future__ import annotations

import base64
import html
import io
import json
import re
import sys
from pathlib import Path

MEDIA = Path("/home/bam/vibetracks/reports/media/vibetracks-dashboard-2026-10-03")
RESULTS = MEDIA / "workflow-results.json"
FB_DIR = Path("/home/bam/vibetracks/reports/media/dashboard-prior-art-2026-10-03")
OUT = Path("/home/bam/vibetracks/reports/media/vibetracks-dashboard-2026-10-04.html")
REPORT_NAME = "vibetracks-dashboard-2026-10-04.html"
LAUNCHER = "/home/bam/vibetracks-dashboard/scripts/open-dashboard"

sys.path.insert(0, str(FB_DIR))
import report_feedback as FB  # noqa: E402

DATA = json.loads(RESULTS.read_text())

# ---- frozen criteria (BRIEF.md) --------------------------------------------------------------
CRITERIA = [
    ("fr1", "Three clean levels", 25),
    ("fr2", "Research principles applied", 25),
    ("fr3", "Calm design language", 20),
    ("fr4", "KPI progress legible", 15),
    ("fr5", "Real and working", 15),
]
GATES = [("g1", "Truthful data"), ("g2", "No fake controls"), ("g3", "Local only"), ("g4", "One command")]
JUDGES = [("judge:zach", "Judge: Zach's brief"), ("judge:research", "Judge: research principles")]
LETTERS = ["A", "B", "C"]


def weighted(row: dict) -> float:
    return sum(w * row[k]["score"] / 5 for k, _n, w in CRITERIA)


def judge_rows(key: str) -> dict:
    return {r["letter"]: r for r in DATA[key]["scores"]}


SCORES = {jk: judge_rows(jk) for jk, _ in JUDGES}
MEAN = {L: sum(weighted(SCORES[jk][L]) for jk, _ in JUDGES) / len(JUDGES) for L in LETTERS}
ORDER = sorted(LETTERS, key=lambda L: -MEAN[L])  # judge order: highest mean first
assert ORDER == ["A", "B", "C"], f"judge order changed: {ORDER} - check the verdict line before shipping"

# ---- media -------------------------------------------------------------------------------------
_inlined: set[str] = set()


def _once(path: Path) -> None:
    key = str(path)
    assert key not in _inlined, f"would inline twice: {path}"
    _inlined.add(key)


def data_uri(path: Path, mime: str) -> str:
    _once(path)
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def webp_uri(path: Path) -> str:
    return data_uri(path, "image/webp")


def settings_uri() -> str:
    from PIL import Image
    path = MEDIA / "foundation" / "settings-page.png"
    _once(path)
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "WEBP", quality=82, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def inline_md(s: str) -> str:
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def md(text: str) -> str:
    """Tiny markdown: paragraphs, - bullets, 1. lists, **bold**, `code`. Input is trusted data, still escaped."""
    out: list[str] = []
    mode = None  # None | "ul" | "ol"

    def close():
        nonlocal mode
        if mode:
            out.append(f"</{mode}>")
            mode = None

    for raw in text.split("\n"):
        line = raw.rstrip()
        m_ul = re.match(r"^\s*[-*]\s+(.*)$", line)
        m_ol = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m_ul:
            if mode != "ul":
                close(); out.append("<ul>"); mode = "ul"
            out.append(f"<li>{inline_md(m_ul.group(1))}</li>")
        elif m_ol:
            if mode != "ol":
                close(); out.append("<ol>"); mode = "ol"
            out.append(f"<li>{inline_md(m_ol.group(1))}</li>")
        elif not line.strip():
            close()
        else:
            close()
            out.append(f"<p>{inline_md(line.strip())}</p>")
    close()
    return "\n".join(out)


# ---- comparison grid -----------------------------------------------------------------------------
V = {L: DATA[f"build:{L.lower()}"] for L in LETTERS}
VARIANT_NAME = {L: V[L]["name"] for L in LETTERS}


def caption_for(letter: str, filename: str) -> str:
    for s in V[letter]["stills"]:
        if s["path"].endswith("/" + filename):
            return s["caption"]
    raise KeyError(f"{letter}/{filename} has no caption in workflow-results.json")


# row title, then (file, short bold label) per variant
GRID = [
    ("Level 1: pick a track", [
        ("a/1-l1-tracks.webp", "Tracks table"),
        ("b/1-l1-tracks.webp", "Loop tabs and glance"),
        ("c/c-1-l1-glance.webp", "Glance and worklist"),
    ]),
    ("Level 2: kinsim's KPIs over waves", [
        ("a/2-l2-kinsim-scorecard.webp", "Scorecard, W3 emphasised"),
        ("b/2-l2-kinsim-cursor.webp", "Cursor on W2 through every row"),
        ("c/c-2-l2-kinsim.webp", "KPI table and burn-up"),
    ]),
    ("Level 2: CAN 16's KPIs over sessions", [
        ("a/3-l2-can16-scorecard.webp", "Sessions as columns"),
        ("b/3-l2-can16.webp", "Day-median headlines"),
        ("c/c-3-l2-can16.webp", "Held condition on the chart"),
    ]),
    ("Level 3: kinsim evidence", [
        ("a/4-l3-kinsim-w3-bt1-evidence.webp", "BT1 cell opens its run inline"),
        ("b/5-l3-kinsim-wave3-report.webp", "Drawer with the Wave 3 report"),
        ("c/c-5-l3-kinsim-judged-run.webp", "Judged run, no video recorded"),
    ]),
    ("Level 3: a real run video playing", [
        ("a/5-l3-can16-run-video-playing.webp", "Run page, Play both"),
        ("b/4-l3-can16-video-playing.webp", "Drawer, real and sim side by side"),
        ("c/c-4-l3-can16-run-video.webp", "Real video playing in pane 3"),
    ]),
    ("One more each", [
        ("a/6-l2-rig-by-day-from-settings.webp", "Settings, X axis: Day"),
        ("b/6-l2-can12-cursor-dense-axis.webp", "CAN 12 dense axis"),
        ("c/c-6-l3-kinsim-wave3-report.webp", "Wave 3 report in place"),
    ]),
]


def grid_html() -> str:
    head = "".join(
        f'<div class="gcol-h"><span class="ltr">{L}</span> {esc(VARIANT_NAME[L])}</div>' for L in LETTERS
    )
    rows = []
    for title, cells in GRID:
        figs = []
        for L, (rel, label) in zip(LETTERS, cells):
            fname = Path(rel).name
            cap = caption_for(L, fname)
            alt = f"{L} · {label}"
            figs.append(
                '<figure class="cell">'
                f'<button class="zoom" type="button" aria-label="Open {esc(alt)} full size">'
                f'<img alt="{esc(alt)}" src="{webp_uri(MEDIA / rel)}"></button>'
                f'<figcaption><b><span class="ltr">{L}</span> {esc(label)}</b>'
                f'<span class="cap">{esc(cap)}</span></figcaption></figure>'
            )
        rows.append(f'<div class="grow"><h3 class="rowt">{esc(title)}</h3><div class="gcells">{"".join(figs)}</div></div>')
    return f'<div class="gheads">{head}</div>' + "".join(rows)


# ---- videos ----------------------------------------------------------------------------------------
HEROES = [
    ("A", "a/hero-drill-down.mp4", "Drill-down pages",
     "Tracks table, then kinsim's scorecard, then the BT1 cell at W3 with its evidence open inline. Back, Back, "
     "then CAN 16's scorecard, the held-condition cell at the 07-28 baseline, the gentle_step · ff_fb run page, "
     "and Play both with the real and sim clips running together. Back climbs exactly one level each press."),
    ("B", "b/hero-shared-timeline.mp4", "Shared timeline",
     "Kinsim's KPI wall; the cursor glides from Start to W3 across every row, then the W3 drawer opens, the BT1 "
     "judged run, and the Wave 3 report. Esc closes the drawer, the rig tab and CAN 16 follow, and a click on "
     "the held gentle_step point opens its ff_fb run with real and sim video side by side."),
    ("C", "c/c-hero.mp4", "Three panes",
     "The glance, then kinsim, then the W3 point and the Wave 3 report in pane 3. Esc, Esc climbs back to L2. "
     "CAN 16, the held gentle_step · ff_fb KPI, the 07-28 baseline cam2 point, and the run's real video "
     "playing on a loop in pane 3."),
]


def videos_html() -> str:
    out = []
    for L, rel, name, cap in HEROES:
        src = data_uri(MEDIA / rel, "video/mp4")
        out.append(
            '<figure class="vid">'
            '<video controls autoplay muted loop playsinline preload="auto">'
            f'<source src="{src}" type="video/mp4"></video>'
            f'<figcaption><b><span class="ltr">{L}</span> {esc(name)}</b>'
            f'<span class="cap">{esc(cap)}</span></figcaption></figure>'
        )
    return '<div class="vids">' + "".join(out) + "</div>"


# ---- proposals in detail -------------------------------------------------------------------------------
def proposal_html(L: str) -> str:
    b = V[L]
    levels = "".join(
        f'<div class="lvl"><span class="lk">{k.upper()}</span><div>{inline_md(b["levels"][k])}</div></div>'
        for k in ("l1", "l2", "l3")
    )
    principles = "".join(
        f'<li><span class="pp">{inline_md(p["principle"])}</span><span class="pw">{inline_md(p["where"])}</span></li>'
        for p in b["principles"]
    )
    decisions = "".join(
        f'<li><b>{inline_md(d["label"])}</b> <span>{inline_md(d["value"])}</span></li>' for d in b["decisions"]
    )
    keep = "".join(f"<li>{inline_md(k)}</li>" for k in b["keepParts"])
    return f"""
<article class="prop" id="prop-{L}">
  <header class="prophead"><span class="ltr big">{L}</span>
    <h3>{esc(b['name'])}</h3>
    <div class="meanbadge" title="mean of both judges, weighted">{MEAN[L]:.1f}<small>/ 100</small></div>
    <p class="thesis">{inline_md(b['thesis'])}</p>
  </header>
  <h4>How the levels work</h4>
  <div class="lvls">{levels}</div>
  <h4>Research principles applied <small>({len(b['principles'])})</small></h4>
  <ul class="pairs">{principles}</ul>
  <h4>Decisions the builder made</h4>
  <ul class="decs">{decisions}</ul>
  <div class="two">
    <div><h4>Best when</h4><p>{inline_md(b['bestWhen'])}</p></div>
    <div><h4>Loses when</h4><p>{inline_md(b['losesWhen'])}</p></div>
  </div>
  <h4>Parts worth keeping</h4>
  <ul class="keep">{keep}</ul>
  <details class="limits"><summary>Honest limits (the builder's own)</summary>{md(b['honest_limits'])}</details>
  {FB.strip(L, b['name'], noun="proposal")}
</article>"""


# ---- judges ----------------------------------------------------------------------------------------------
def judges_html() -> str:
    crit_head = "".join(f'<th class="num">{esc(n)}<small>{w}</small></th>' for _k, n, w in CRITERIA)
    gate_head = "".join(f'<th class="gate">{k.upper()}<small>{esc(n)}</small></th>' for k, n in GATES)
    rows = []
    for L in ORDER:
        for jk, jname in JUDGES:
            r = SCORES[jk][L]
            cells = "".join(f'<td class="num">{r[k]["score"]}</td>' for k, _n, _w in CRITERIA)
            gates = "".join(
                f'<td class="gate {"ok" if r[k]["pass"] else "bad"}">{"pass" if r[k]["pass"] else "FAIL"}</td>'
                for k, _n in GATES
            )
            rows.append(
                f'<tr class="jrow"><th scope="row"><span class="ltr">{L}</span> <span class="jn">{esc(jname)}</span></th>'
                f'<td class="num wt">{weighted(r):.1f}</td>{cells}{gates}</tr>'
            )
            ev = "".join(
                f'<div class="ev"><b>{k.upper()} {esc(n)} · {r[k]["score"]}/5</b> <em>{esc(r[k]["confidence"])} confidence</em>'
                f'<p>{inline_md(r[k]["evidence"])}</p></div>'
                for k, n, _w in CRITERIA
            ) + "".join(
                f'<div class="ev"><b>{k.upper()} {esc(n)} · {"pass" if r[k]["pass"] else "FAIL"}</b>'
                f'<p>{inline_md(r[k]["evidence"])}</p></div>'
                for k, n in GATES
            )
            rows.append(
                f'<tr class="evrow"><td colspan="{2 + len(CRITERIA) + len(GATES)}">'
                f'<details><summary>Evidence · {L} · {esc(jname)}</summary>{ev}</details></td></tr>'
            )
        gates_ok = all(SCORES[jk][L][g]["pass"] for jk, _ in JUDGES for g, _n in GATES)
        rows.append(
            f'<tr class="meanrow"><th scope="row"><span class="ltr">{L}</span> {esc(VARIANT_NAME[L])} · mean</th>'
            f'<td class="num wt">{MEAN[L]:.1f}</td>'
            f'<td colspan="{len(CRITERIA)}" class="meanbar"><span style="width:{MEAN[L]:.1f}%"></span></td>'
            f'<td colspan="{len(GATES)}" class="gate {"ok" if gates_ok else "bad"}">'
            f'{"all gates pass" if gates_ok else "a gate failed"}</td></tr>'
        )
    board = "".join(
        f'<div class="sb"><span class="ltr">{L}</span><div><b>{esc(VARIANT_NAME[L])}</b>'
        f'<span class="sbn">{MEAN[L]:.1f}<small> / 100</small></span></div></div>' for L in ORDER
    )
    table = (
        f'<div class="scoreboard">{board}</div>'
        '<div class="tablewrap"><table class="scores"><thead><tr><th></th>'
        + '<th class="num">Weighted<small>of 100</small></th>' + crit_head + gate_head
        + '</tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
    )
    quotes = []
    for title, field in (("The hinge", "hinge"), ("The splice", "splice")):
        cols = "".join(
            f'<div class="quote"><div class="qwho">{esc(jname)}</div>{md(DATA[jk][field])}</div>' for jk, jname in JUDGES
        )
        quotes.append(f'<h3>{title}</h3><div class="two quotes">{cols}</div>')
    return table + "".join(quotes)


# ---- page -------------------------------------------------------------------------------------------------
CSS = r"""
:root{
  --bg:#fff; --fg:#1b1d21; --dim:#5d6470; --dim2:#8a919c; --line:#e6e8ec; --line2:#d3d7de; --panel:#f7f8fa;
  --accent:#2563eb; --accent2:#2563eb; --ok:#2f7d4f; --warn:#b4540a; --bad:#b42318;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 var(--sans);-webkit-text-size-adjust:100%}
.wrap{max-width:1240px;margin:0 auto;padding:0 16px 120px}
h1{font-size:34px;line-height:1.15;margin:0 0 12px;letter-spacing:-.02em}
h2{font-size:22px;margin:0 0 6px;letter-spacing:-.01em}
h3{font-size:17px;margin:0 0 6px}
h4{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim2);margin:22px 0 8px;font-weight:700}
h4 small{font-weight:500;letter-spacing:0;text-transform:none}
p{margin:0 0 10px}
code{font:12.5px var(--mono);background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:0 4px}
.hidden{display:none !important}
.sub{color:var(--dim)}

header.top{padding:40px 0 18px}
.date{color:var(--dim2);font-size:13px;margin-bottom:8px}
.verdict{font-size:18px;line-height:1.45;font-weight:700;margin:0 0 10px;max-width:60em}
.built{color:var(--dim);font-size:13.5px;margin:0 0 16px}
.launch{display:flex;align-items:stretch;gap:0;max-width:640px;border:1px solid var(--line2);border-radius:9px;overflow:hidden;background:var(--panel)}
.launch pre{margin:0;padding:10px 14px;font:13px/1.4 var(--mono);overflow-x:auto;flex:1;white-space:pre}
.launch button{border:0;border-left:1px solid var(--line2);background:#fff;font:600 13px var(--sans);padding:0 16px;cursor:pointer;color:var(--fg)}
.launch button:hover{background:var(--panel)}
.launch button.done{color:var(--ok)}
nav.toc{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);border-bottom:1px solid var(--line);
  display:flex;gap:4px;overflow-x:auto;padding:8px 0;margin:0 -16px 0;padding-left:16px;padding-right:16px;scrollbar-width:none}
nav.toc a{color:var(--dim);text-decoration:none;font-size:13px;padding:5px 11px;border-radius:7px;white-space:nowrap}
nav.toc a:hover{background:var(--panel);color:var(--fg)}
section{padding-top:44px;scroll-margin-top:44px}
.lead{color:var(--dim);margin:0 0 18px;max-width:60em}
.ltr{display:inline-grid;place-items:center;min-width:1.45em;height:1.45em;border-radius:5px;background:var(--fg);color:#fff;font:700 .78em var(--sans);padding:0 .3em;vertical-align:.08em}
.ltr.big{width:40px;height:40px;font-size:20px;border-radius:9px;flex:none}

/* videos */
.vids{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.vid{margin:0}
.vid video{width:100%;display:block;border:1px solid var(--line2);border-radius:10px;background:#111;aspect-ratio:1280/800}
figcaption{margin-top:8px;font-size:13px}
figcaption b{display:block;font-size:13.5px}
.cap{display:block;color:var(--dim);font-size:12.5px;line-height:1.5;margin-top:2px}
.vid .cap{font-size:13px}
@media(max-width:980px){.vids{grid-template-columns:1fr}}

/* comparison grid */
.gheads,.gcells{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.gheads{position:sticky;top:41px;z-index:10;background:rgba(255,255,255,.95);padding:8px 0;border-bottom:1px solid var(--line);margin-bottom:6px}
.gcol-h{font-weight:700;font-size:14px}
.grow{padding-top:22px}
.rowt{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim2);margin:0 0 8px}
.cell{margin:0;min-width:0}
/* WHY crop: every capture is the whole 1440x900 Clank window; the left file sidebar (308 px) and the status bar
   (28 px) are shell, not the dashboard, and cost a fifth of the width at three-up. The lightbox shows the uncropped file. */
.zoom{all:unset;display:block;width:100%;cursor:zoom-in;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--panel);line-height:0;aspect-ratio:1132/872;position:relative}
.zoom:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.zoom img{width:127.2%;max-width:none;height:auto;display:block;margin-left:-27.2%}
.zoom:hover{border-color:var(--accent)}
@media(max-width:760px){
  .gheads{display:none}
  .gcells{grid-template-columns:1fr;gap:16px}
}

/* lightbox */
#lb{position:fixed;inset:0;z-index:100;background:rgba(10,12,16,.88);display:none;flex-direction:column;align-items:center;justify-content:center;padding:20px;gap:12px}
#lb.open{display:flex}
#lb img{max-width:100%;max-height:calc(100vh - 120px);object-fit:contain;border-radius:6px;background:#fff;cursor:zoom-out}
#lb .lbcap{color:#e8eaee;font-size:13px;max-width:900px;text-align:center}
@media(max-width:560px){
  /* WHY: a 1440 px capture fitted into 390 px is unreadable; let the phone pan a 900 px copy instead. */
  #lb{justify-content:flex-start;align-items:flex-start;overflow:auto;padding-top:56px}
  #lb img{max-width:none;max-height:none;width:900px}
  #lb .lbcap{position:sticky;left:0;width:calc(100vw - 40px)}
}
#lb button{position:fixed;top:12px;right:14px;border:1px solid #ffffff55;background:#00000066;color:#fff;border-radius:8px;font:600 13px var(--sans);padding:7px 12px;cursor:pointer}

/* proposals */
.prop{scroll-margin-top:52px;border:1px solid var(--line);border-radius:14px;padding:22px 22px 18px;margin:0 0 24px;background:#fff}
.prophead{display:grid;grid-template-columns:40px 1fr auto;column-gap:14px;row-gap:8px;align-items:center}
.prophead h3{margin:0;font-size:20px}
.thesis{grid-column:2 / -1;color:var(--dim);margin:0;max-width:62em}
.meanbadge{font-size:26px;font-weight:700;line-height:1;text-align:right;color:var(--accent)}
.meanbadge small{display:block;font-size:11px;font-weight:500;color:var(--dim2);margin-top:3px}
.lvls{display:grid;gap:0;border-top:1px solid var(--line)}
.lvl{display:grid;grid-template-columns:36px 1fr;gap:10px;padding:10px 0;border-bottom:1px solid var(--line);font-size:14px}
.lvl .lk{font:700 12px var(--mono);color:var(--accent);padding-top:2px}
ul.pairs{list-style:none;margin:0;padding:0;columns:2;column-gap:28px}
ul.pairs li{break-inside:avoid;padding:8px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.pp{display:block;font-weight:600}
.pw{display:block;color:var(--dim);font-size:12.5px;margin-top:2px}
ul.decs,ul.keep{margin:0;padding-left:18px;font-size:13.5px}
ul.decs li,ul.keep li{margin:0 0 6px}
ul.decs li span{color:var(--dim)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:28px}
.two p{font-size:13.5px}
details.limits{margin-top:16px;border-top:1px solid var(--line);padding-top:10px;font-size:13.5px}
summary{cursor:pointer;color:var(--dim);font-weight:600;font-size:13px}
summary:hover{color:var(--fg)}
details.limits ul,details.limits ol{padding-left:18px}
@media(max-width:820px){ul.pairs{columns:1}.two{grid-template-columns:1fr;gap:0}.thesis{grid-column:1 / -1}.prop{padding:16px 14px}}

/* judges */
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table.scores{border-collapse:collapse;width:100%;min-width:860px;font-size:13px}
table.scores th,table.scores td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
table.scores thead th{font-size:11.5px;color:var(--dim);font-weight:700;background:var(--panel);vertical-align:bottom}
table.scores thead th small{display:block;font-weight:500;color:var(--dim2)}
.num{text-align:center !important;font-variant-numeric:tabular-nums}
.wt{font-weight:700;color:var(--accent)}
.gate{text-align:center !important;font-size:12px;color:var(--dim)}
.gate.ok{color:var(--dim)} .gate.bad{color:var(--bad);font-weight:700}
.jn{color:var(--dim);font-weight:500}
tr.evrow td{padding:0 10px 6px;border-bottom:1px solid var(--line)}
tr.evrow details{padding:2px 0}
tr.evrow summary{font-size:12px}
.ev{margin:10px 0;font-size:13px;max-width:70em}
.ev em{color:var(--dim2);font-size:12px;font-style:normal;margin-left:6px}
.ev p{margin:2px 0 0;color:var(--dim)}
tr.meanrow th,tr.meanrow td{background:var(--panel);border-bottom:2px solid var(--line2)}
.meanbar{padding:0 10px !important}
.meanbar span{display:block;height:8px;background:var(--accent);border-radius:4px;opacity:.85}
.quotes{margin-top:6px}
#judges h3{margin-top:30px}
.quote{border-left:3px solid var(--line2);padding:2px 0 2px 14px;font-size:13.5px;min-width:0}
.quote ul,.quote ol{padding-left:18px;margin:0 0 10px}
.qwho{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim2);font-weight:700;margin-bottom:6px}
@media(max-width:820px){.quotes{gap:20px}}

.scoreboard{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px}
.sb{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.sb b{display:block;font-size:13px}
.sbn{display:block;font-size:28px;font-weight:700;color:var(--accent);line-height:1.15}
.sbn small{font-size:12px;color:var(--dim2);font-weight:500}
@media(max-width:560px){.scoreboard{grid-template-columns:1fr}}
/* what's built */
.built-grid{display:grid;grid-template-columns:1.5fr 1fr;gap:28px;align-items:start}
.built-grid ul{margin:0;padding-left:18px;font-size:14px}
.built-grid li{margin:0 0 8px}
.built-grid figure{margin:0}

@media(max-width:820px){.built-grid{grid-template-columns:1fr}}

/* decision surface */
.decide{border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:12px;padding:6px 22px 14px;background:var(--panel)}
.decide ul,.decide ol{margin:4px 0 8px;padding-left:20px}
.decide>ul>li{margin:12px 0}
.decide li ul{margin-top:4px}
footer.end{margin-top:40px;color:var(--dim2);font-size:12px}
"""

# Light-theme override of the house feedback module, which was written dark. WHY an override block rather
# than editing the shared module: other reports still import it unchanged.
FB_LIGHT = r"""
.fb{border-top:1px solid var(--line);margin-top:18px;padding-top:12px}
.fb button{background:#fff;color:var(--dim);border:1px solid var(--line2)}
.fb button:hover{color:var(--fg);border-color:var(--dim2)}
.fb button[aria-pressed="true"]{color:#fff}
.fb .dno[aria-pressed="true"]{background:var(--bad);border-color:var(--bad)}
.fb .note-btn[aria-pressed="true"]{background:#fff7e6;border-color:var(--warn);color:var(--warn)}
.fb textarea,.overall textarea,.sheet textarea{background:#fff;color:var(--fg);border:1px solid var(--line2)}
.fb textarea::placeholder{color:var(--dim2)}
.dock{background:rgba(255,255,255,.97);box-shadow:0 8px 30px #0002;max-width:calc(100vw - 24px)}
.dock button,.sheet button{background:#fff;color:var(--fg);border:1px solid var(--line2)}
.dock button.go{background:var(--accent);border-color:var(--accent);color:#fff}
.sheet{background:rgba(15,18,24,.55)}
.sheet .inner{background:#fff}
.sheet textarea{background:var(--panel)}
.sheet button.go{background:var(--ok);border-color:var(--ok);color:#fff}
.overall{background:var(--panel);border-radius:12px}
@media(max-width:560px){.dock{left:12px;right:12px;bottom:12px;justify-content:space-between}.sheet{padding:12px}}
"""

BUILT = [
    "**The projection**, `vibetracks-dashboard/1`, built from the real snapshot: 4 tracks, 46 KPIs, 167 media items.",
    "**A stdlib adapter** turns the loop data into that projection. No dependencies.",
    "**A read-only plugin backend** serves it: media is allowlisted and supports Range requests, so run videos seek.",
    "**The Clank plugin** with its shared calm kit: the Table, scorecard cells, sparklines, SeriesChart, VideoPlayer and report frame. The three variants differ only in how the three levels are composed.",
    "**A settings page** behind a quiet gear at the right end of the header. View options (X axis: iteration or day, show deltas) never sit on toolbars.",
    "**The roadmap widget slot** at L2 in every variant. The widget itself belongs to the roadmap session and is still a stub here.",
    "**Commits** `6903e97` → `1dc5d97` → `8369c05` on branch `claude/vibetracks-dashboard` in `/home/bam/vibetracks-dashboard`.",
    "**Untouched:** `main` in the vibetracks repo (24 older uncommitted VT-008 files) was not touched. The repo is public, so all BAM data and media live outside git.",
]

DECISION = """
<ul>
  <li><strong>Done:</strong> three working apps; real run videos and wave reports open; typecheck clean; 72 + 15 tests pass; both judges drove all three; all gates pass.</li>
  <li><strong>Left:</strong>
    <ul>
      <li>the Codex audit of the apps;</li>
      <li>live data instead of the morning snapshot;</li>
      <li>the vault note and daily-note callout still point at the old rounds.</li>
    </ul></li>
  <li><strong>Needs you:</strong>
    <ol>
      <li>Pick A, B, C or a splice. The recommendation is A + B's column cursor. Default if you say nothing: nothing more gets built.</li>
      <li>Where the plugin lives. It's inside the vibetracks repo for now; Clank's recipe prefers its own repo. Default: it stays.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no push (the repo is public); vibetracks main was not touched.</li>
</ul>
"""

JS = r"""
<script>
(function(){
  // launcher copy button — clipboard API is often refused on file:/data: origins, so fall back to selection
  var btn = document.getElementById('copy-launch'), pre = document.getElementById('launch-cmd');
  btn.addEventListener('click', function(){
    var text = pre.textContent.trim(), ok = function(){ btn.textContent = 'Copied'; btn.classList.add('done');
      setTimeout(function(){ btn.textContent = 'Copy'; btn.classList.remove('done'); }, 1600); };
    function fallback(){
      var r = document.createRange(); r.selectNodeContents(pre);
      var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      try { if (document.execCommand('copy')) ok(); else btn.textContent = 'Press Ctrl-C'; } catch(e){ btn.textContent = 'Press Ctrl-C'; }
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(ok, fallback);
    else fallback();
  });

  // lightbox: re-uses the clicked image's src, so no media is embedded twice
  var lb = document.getElementById('lb'), lbImg = lb.querySelector('img'), lbCap = lb.querySelector('.lbcap');
  function openLb(img){
    lbImg.src = img.src; lbImg.alt = img.alt;
    var fig = img.closest('figure'), cap = fig && fig.querySelector('figcaption');
    var lab = cap && cap.querySelector('b'), txt = cap && cap.querySelector('.cap');
    lbCap.textContent = lab ? lab.textContent.trim() + (txt ? ' \u2014 ' + txt.textContent.trim() : '') : img.alt;
    lb.classList.add('open'); lb.querySelector('button').focus();
  }
  function closeLb(){ lb.classList.remove('open'); lbImg.removeAttribute('src'); }
  Array.prototype.forEach.call(document.querySelectorAll('.zoom'), function(z){
    z.addEventListener('click', function(){ openLb(z.querySelector('img')); });
  });
  lb.addEventListener('click', function(e){ if (e.target !== lbCap) closeLb(); });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape' && lb.classList.contains('open')) closeLb(); });

  // three autoplaying videos at once is heavy: run only the ones on screen
  var vids = document.querySelectorAll('.vid video');
  if ('IntersectionObserver' in window){
    var io = new IntersectionObserver(function(entries){
      entries.forEach(function(en){
        if (en.isIntersecting){ var p = en.target.play(); if (p && p.catch) p.catch(function(){}); }
        else en.target.pause();
      });
    }, {threshold: .25});
    Array.prototype.forEach.call(vids, function(v){ io.observe(v); });
  }
})();
</script>
"""


def build() -> str:
    # FB.JS opens with "# Feedback — <report>"; Zach wants the pasted markdown to open with a Re: line.
    fb_js = FB.JS
    needle = "var out = ['# Feedback \\u2014 ' + REPORT, ''];"
    assert needle in fb_js, "report_feedback.JS changed: re-check how the markdown heading is built"
    fb_js = fb_js.replace(
        needle,
        "var out = ['Re: Vibe Tracks dashboard proposals (2026-10-04)', '', '<sub>' + REPORT + '</sub>', ''];",
    )

    props = "".join(proposal_html(L) for L in ORDER)
    built_items = "".join(f"<li>{inline_md(b)}</li>" for b in BUILT)
    mean_line = " · ".join(f"{L} {MEAN[L]:.1f}" for L in ORDER)

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vibe Tracks dashboard: three working proposals</title>
<style>{CSS}{FB.CSS}{FB_LIGHT}</style></head>
<body><div class="wrap">

<header class="top">
  <div class="date">2026-10-04</div>
  <h1>Vibe Tracks dashboard: three working proposals</h1>
  <p class="verdict">Three working Clank apps on your real loop data, all with the same three levels: pick a track → its KPIs over time → per-run evidence. Both judges rank A · Drill-down pages first; their splice is A plus B's column cursor.</p>
  <p class="built">Built from the real 2026-10-03 snapshot (not yet live) · branch claude/vibetracks-dashboard · not yet audited by Codex.</p>
  <div class="launch"><pre id="launch-cmd">{esc(LAUNCHER)}</pre><button id="copy-launch" type="button">Copy</button></div>
</header>

<nav class="toc" aria-label="Sections">
  <a href="#watch">Watch</a><a href="#compare">Compare</a><a href="#proposals">Proposals</a>
  <a href="#judges">Judges</a><a href="#built">What's built</a><a href="#decide">Decide</a>
</nav>

<section id="watch">
  <h2>Watch first</h2>
  <p class="lead">One recorded run through each app on the real data, about 19 seconds each, muted and looping. Same walk each time: pick a track, read its KPIs, open a run, play its video.</p>
  {videos_html()}
</section>

<section id="compare">
  <h2>The same moment in each app</h2>
  <p class="lead">Rows are the same step in all three apps. Screenshots are cropped to the dashboard (Clank's file sidebar is trimmed); click one for the full window, Esc closes it.</p>
  {grid_html()}
</section>

<section id="proposals">
  <h2>Each proposal in detail</h2>
  <p class="lead">In judge order ({esc(mean_line)}). Mark each one at the bottom of its card; the dock at the lower right copies your notes out as markdown.</p>
  {props}
</section>

<section id="judges">
  <h2>The judges</h2>
  <p class="lead">Two independent judges drove all three apps and scored them against the frozen criteria. The weighted score is Σ weight × score / 5 per judge (weights 25 / 25 / 20 / 15 / 15), then averaged. Open a row's evidence to see what each judge actually did.</p>
  {judges_html()}
</section>

<section id="built">
  <h2>What's built</h2>
  <div class="built-grid">
    <ul>{built_items}</ul>
    <figure><button class="zoom" type="button" aria-label="Open the settings page full size"><img alt="Settings page: X axis and Show deltas under Dashboard, Roadmap with no settings yet" src="{settings_uri()}"></button>
    <figcaption><b>The settings page</b><span class="cap">Opened from the gear in the dashboard header. X axis (iteration or day) and Show deltas live here, never on a toolbar. The A/B/C switcher at the bottom right is temporary.</span></figcaption></figure>
  </div>
</section>

<section id="decide">
  <h2>Decision surface</h2>
  <div class="decide">{DECISION}</div>
  {FB.ui(REPORT_NAME, noun="proposal", total=3)}
</section>

<footer class="end">Generated by docs/dashboard/build_report.py from workflow-results.json and the 2026-10-03 captures.</footer>
</div>

<div id="lb" role="dialog" aria-modal="true" aria-label="Full-size screenshot"><button type="button">Close (Esc)</button><img alt=""><div class="lbcap"></div></div>
{JS}
{fb_js}
</body></html>"""
    return page


if __name__ == "__main__":
    page = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    size = OUT.stat().st_size
    print(f"wrote {OUT}  {size:,} bytes ({size/1e6:.2f} MB), {len(_inlined)} media inlined once each")
    print("means:", {L: round(MEAN[L], 1) for L in LETTERS})
