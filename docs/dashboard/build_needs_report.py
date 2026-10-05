#!/usr/bin/env python3
"""Build the media-rich review report for the Vibe Tracks Needs-you page: N6 (the default now), the shared fixes, N1-N5.

    python3 /home/bam/vibetracks-dashboard/docs/dashboard/build_needs_report.py

Writes ONE self-contained file:
    /home/bam/vibetracks/reports/media/vibetracks-needs-you-2026-10-04.html

Same structure and house style as build_report.py (the three-proposal dashboard report). The proposals', research and
judges' words live in needs_data.py, which sits in MEDIA (not in this repo); the captures and hero videos are the builders' own, in MEDIA.
Round 6 (verify-6's leftovers, re-measured by verify-7) renders from MEDIA/r6/round6-fixes.json, which the live-tracks
report shares; its 'open_probes' are re-read from the tree on every build.

WHY one file with everything inlined: Zach reviews by reading, not by clicking around (/rate bad 2026-10-04).
Every still and hero video is a data: URI, each inlined exactly ONCE: the lightbox re-uses the clicked <img>'s src at
runtime instead of a second copy. The page is several MB, past the desktop preview's ~2 MB cap on the encoded data: URL,
so it is browser-only and lives in the gitignored reports/media/ half.
WHY the scores are recomputed here: the judges' raw per-criterion scores are the data; a hardcoded total would
silently outlive an edited score.
"""
from __future__ import annotations

import base64
import html
import importlib.util
import io
import json
import re
import subprocess
from collections import Counter
import sys
from pathlib import Path

from PIL import Image

MEDIA = Path("/home/bam/vibetracks/reports/media/vibetracks-needs-you-2026-10-04")
# WHY the data module lives beside the captures, not in this repo: it quotes the BAM loops' own questions and
# answers, which must not live in the public dashboard repo. Imported by absolute path; a missing file is a hard stop.
DATA = MEDIA / "needs_data.py"
if not DATA.is_file():
    sys.exit(f"build_needs_report: {DATA} is missing. It holds the loop text this report quotes and lives only in the "
             "reports media folder (never in the repo). Restore it there, then re-run.")
_spec = importlib.util.spec_from_file_location("needs_data", DATA)
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)
FB_DIR = Path("/home/bam/vibetracks/reports/media/dashboard-prior-art-2026-10-03")
OUT = Path("/home/bam/vibetracks/reports/media/vibetracks-needs-you-2026-10-04.html")
REPORT_NAME = OUT.name
LAUNCHER = "/home/bam/vibetracks-dashboard/scripts/open-dashboard"
DASH_URL = "http://127.0.0.1:4390/?vtdash=Agent%20work.vtdash#vt?track=kinsim&needs=1"

sys.path.insert(0, str(FB_DIR))
import report_feedback as FB  # noqa: E402

NS = ["N1", "N2", "N3", "N4", "N5"]
NAME = {n: D.BUILDERS[n]["name"] for n in NS}

# ---- scores (recomputed) -----------------------------------------------------------------------------------------
def weighted(judge_row: dict) -> float:
    return sum(w * judge_row["f"][i][0] / 5 for i, (_k, _n, w) in enumerate(D.CRITERIA))


assert sum(w for _k, _n, w in D.CRITERIA) == 100
MEAN = {n: sum(weighted(rows[n]) for _j, _s, rows in D.JUDGES) / len(D.JUDGES) for n in NS}
ORDER = sorted(NS, key=lambda n: -MEAN[n])
assert ORDER == ["N1", "N2", "N4", "N3", "N5"], f"judge order changed: {ORDER} - re-check the verdict line"
# The judges' own stated totals (Judge 2: N1 4.75, N2 4.70, N4 4.35, N3 4.25, N5 3.70) must reproduce from the raw scores.
_J2 = {n: weighted(D.JUDGES[1][2][n]) / 20 for n in NS}
assert [round(_J2[n], 2) for n in ("N1", "N2", "N4", "N3", "N5")] == [4.75, 4.70, 4.35, 4.25, 3.70], _J2
GATE_FAIL = {n for n in NS for _j, _s, rows in D.JUDGES if not rows[n]["gates"]}

# ---- media -------------------------------------------------------------------------------------------------------
_inlined: set[str] = set()


def data_uri(path: Path, mime: str) -> str:
    key = str(path)
    assert path.exists(), f"missing media: {path}"
    assert key not in _inlined, f"would inline twice: {path}"
    _inlined.add(key)
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


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
    mode = None

    def close():
        nonlocal mode
        if mode:
            out.append(f"</{mode}>")
            mode = None

    for raw in text.strip().split("\n"):
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


def link_or_path(src: str) -> str:
    if src.startswith("http"):
        return f'<a href="{esc(src)}" target="_blank" rel="noopener noreferrer">{esc(src)}</a>'
    return f"<code>{esc(src)}</code>"


# ---- videos --------------------------------------------------------------------------------------------------------
# WHY the first-wave heroes come from r2-small/ (960 wide, 15 fps, crf 30) and carry a small poster instead of a GIF:
# the page has to stay under ~9 MB (it was 12.8 MB). They play at a fifth of the page width, where 960 px is still
# sharp; the full-size originals stay in n1/..n5/. A viewer that cannot play H.264 sees the poster still, not a GIF.
SMALL = MEDIA / "r2-small"


def videos_html() -> str:
    out = []
    for n in NS:
        b = D.BUILDERS[n]
        src = data_uri(SMALL / f"hero-{n.lower()}.mp4", "video/mp4")
        poster = data_uri(SMALL / f"poster-{n.lower()}.webp", "image/webp")
        out.append(
            '<figure class="vid">'
            f'<video controls autoplay muted loop playsinline preload="auto" poster="{poster}" data-n="%s">'
            f'<source src="{src}" type="video/mp4"></video>'
            f'<figcaption><b><span class="ltr">{n}</span> {esc(b["name"])}</b>'
            f'<span class="cap">{esc(b["hero_caption"])}</span></figcaption></figure>' % n
        )
    return '<div class="vids">' + "".join(out) + "</div>"


# ---- comparison grid -----------------------------------------------------------------------------------------------
_CAPTION = {n: {Path(p).name: (label, cap) for p, label, cap in D.BUILDERS[n]["stills"]} for n in NS}
GRID_USED: set[str] = set()


def figure(n: str, rel: str, label: str, show_cap: bool = True) -> str:
    fname = Path(rel).name
    _lab, cap = _CAPTION[n][fname]
    alt = f"{n} · {label}"
    # grid cells hide the caption (the proposal cards below show it) but keep it in the DOM for the lightbox
    cap_html = f'<span class="cap{"" if show_cap else " capx"}">{esc(cap)}</span>'
    return (
        '<figure class="cell">'
        f'<button class="zoom" type="button" aria-label="Open {esc(alt)} full size">'
        f'<img alt="{esc(alt)}" loading="lazy" src="{data_uri(MEDIA / rel, "image/webp")}"></button>'
        f'<figcaption><b><span class="ltr">{n}</span> {esc(label)}</b>{cap_html}</figcaption></figure>'
    )


def grid_html() -> str:
    head = "".join(f'<div class="gcol-h"><span class="ltr">{n}</span> {esc(NAME[n])}</div>' for n in NS)
    rows = []
    for title, cells in D.GRID:
        assert len(cells) == 5
        figs = []
        for n, (rel, label) in zip(NS, cells):
            assert rel.startswith(n.lower() + "/"), (n, rel)
            GRID_USED.add(rel)
            figs.append(figure(n, rel, label, show_cap=False))
        rows.append(f'<div class="grow"><h3 class="rowt">{esc(title)}</h3><div class="gcells">{"".join(figs)}</div></div>')
    return f'<div class="gscroll"><div class="ginner"><div class="gheads">{head}</div>' + "".join(rows) + "</div></div>"


# ---- proposals in detail ------------------------------------------------------------------------------------------
def extras_html(n: str) -> str:
    figs = []
    for rel, label, _cap in D.BUILDERS[n]["stills"]:
        if rel in GRID_USED:
            continue
        figs.append(figure(n, rel, label))
    if not figs:
        return ""
    return f'<h4>More stills <small>({len(figs)})</small></h4><div class="extras">{"".join(figs)}</div>'


def proposal_html(n: str) -> str:
    b = D.BUILDERS[n]
    decisions = "".join(f'<li><b>{inline_md(l)}</b> <span>{inline_md(v)}</span></li>' for l, v in b["decisions"])
    gate = (' <span class="gatebad" title="a judge failed this proposal on a gate">gate fail</span>'
            if n in GATE_FAIL else "")
    rank = ORDER.index(n) + 1
    return f"""
<article class="prop" id="prop-{n}">
  <header class="prophead"><span class="ltr big">{n}</span>
    <h3>{esc(b['name'])}{gate}</h3>
    <div class="meanbadge" title="mean of both judges, weighted">{MEAN[n]:.1f}<small>/ 100 · rank {rank}</small></div>
    <p class="thesis">{inline_md(b['thesis'])}</p>
  </header>
  <h4>Flow</h4>
  <div class="prose">{md(b['flow'])}</div>
  <div class="two">
    <div><h4>Context shown</h4><div class="prose">{md(b['context_shown'])}</div></div>
    <div><h4>Copy-out</h4><div class="prose">{md(b['copy_out'])}</div></div>
  </div>
  <h4>Decisions the builder made</h4>
  <ul class="decs">{decisions}</ul>
  <div class="two">
    <div><h4>Best when</h4><div class="prose">{md(b['best_when'])}</div></div>
    <div><h4>Loses when</h4><div class="prose">{md(b['loses_when'])}</div></div>
  </div>
  {extras_html(n)}
  <details class="limits"><summary>Limits (the builder's own, plus what the judges found)</summary>{md(b['limits'])}</details>
  {FB.strip(n, b['name'], noun="proposal")}
</article>"""


# ---- prior art -----------------------------------------------------------------------------------------------------
def prior_art_html() -> str:
    sauna = "".join(f'<h4>{esc(h)}</h4><div class="prose">{md(t)}</div>' for h, t in D.SAUNA)
    sauna_src = "".join(f"<li>{link_or_path(s)}</li>" for s in D.SAUNA_SOURCES)
    principles = "".join(
        f'<li><b>{inline_md(h)}</b> <span>{inline_md(t)}</span></li>' for h, t in D.PRINCIPLES
    )
    cards = []
    for name, what, steal, sources in D.FINDINGS:
        srcs = "".join(f"<li>{link_or_path(s)}</li>" for s in sources)
        cards.append(
            f'<article class="pa"><h3>{esc(name)}</h3><p>{inline_md(what)}</p>'
            f'<p class="steal"><b>Take:</b> {inline_md(steal)}</p>'
            f'<details><summary>Sources ({len(sources)})</summary><ul class="srcs">{srcs}</ul></details></article>'
        )
    return f"""
<article class="sauna">
  <header><span class="tag">Starting point</span><h3>Sauna's Zen Mode</h3>
  <p class="sub">The keyboard-driven, one-session-per-screen Review lane Zach pointed at. Described from Sauna's own docs, primary but self-descriptive: nothing here was observed in the running app.</p></header>
  {sauna}
  <details><summary>Sources ({len(D.SAUNA_SOURCES)})</summary><ul class="srcs">{sauna_src}</ul></details>
</article>
<h3 class="sect">The seven principles the proposals were briefed on</h3>
<ol class="principles">{principles}</ol>
<h3 class="sect">Everything else the research drew on <small>({len(D.FINDINGS)})</small></h3>
<div class="pas">{''.join(cards)}</div>
"""


# ---- judges -------------------------------------------------------------------------------------------------------
def judges_html() -> str:
    crit_head = "".join(f'<th class="num">{esc(nm)}<small>{w}</small></th>' for _k, nm, w in D.CRITERIA)
    rows = []
    ncols = 3 + len(D.CRITERIA)
    for n in ORDER:
        for jname, _short, jrows in D.JUDGES:
            r = jrows[n]
            cells = "".join(f'<td class="num">{s}</td>' for s, _e in r["f"])
            gate = f'<td class="gate {"ok" if r["gates"] else "bad"}">{"pass" if r["gates"] else "FAIL"}</td>'
            rows.append(
                f'<tr class="jrow"><th scope="row"><span class="ltr">{n}</span> <span class="jn">{esc(jname)}</span></th>'
                f'<td class="num wt">{weighted(r):.1f}</td>{cells}{gate}</tr>'
            )
            ev = "".join(
                f'<div class="ev"><b>{k.upper()} {esc(nm)} · {r["f"][i][0]}/5</b><p>{inline_md(r["f"][i][1])}</p></div>'
                for i, (k, nm, _w) in enumerate(D.CRITERIA)
            ) + (
                f'<div class="ev"><b>Gates (truthful live data, no fake controls, local only) · '
                f'{"pass" if r["gates"] else "FAIL"}</b><p>{inline_md(r["gate_note"])}</p></div>'
            )
            rows.append(
                f'<tr class="evrow"><td colspan="{ncols}">'
                f'<details><summary>Evidence · {n} · {esc(jname)}</summary>{ev}</details></td></tr>'
            )
        gates_ok = n not in GATE_FAIL
        rows.append(
            f'<tr class="meanrow"><th scope="row"><span class="ltr">{n}</span> {esc(NAME[n])} · mean</th>'
            f'<td class="num wt">{MEAN[n]:.1f}</td>'
            f'<td colspan="{len(D.CRITERIA)}" class="meanbar"><span style="width:{MEAN[n]:.1f}%"></span></td>'
            f'<td class="gate {"ok" if gates_ok else "bad"}">{"gates pass" if gates_ok else "a gate failed"}</td></tr>'
        )
    board = "".join(
        f'<div class="sb"><span class="ltr">{n}</span><div><b>{esc(NAME[n])}</b>'
        f'<span class="sbn">{MEAN[n]:.1f}<small> / 100</small></span></div></div>' for n in ORDER
    )
    table = (
        f'<div class="scoreboard">{board}</div>'
        '<div class="tablewrap"><table class="scores"><thead><tr><th></th>'
        '<th class="num">Weighted<small>of 100</small></th>' + crit_head + '<th class="gate">Gates</th>'
        '</tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
    )
    quotes = []
    for title, field in (("The hinge", D.HINGE), ("The splice", D.SPLICE)):
        cols = "".join(
            f'<div class="quote"><div class="qwho">{esc(jname)}</div>{md(field[short])}</div>'
            for jname, short, _rows in D.JUDGES
        )
        quotes.append(f'<h3>{title}</h3><div class="two quotes">{cols}</div>')
    return table + "".join(quotes)


# ---- wave 2: N6 and the shared fixes ------------------------------------------------------------------------------
def png_uri(path: Path, crop: tuple[int, int, int, int] | None = None, quality: int | None = None) -> str:
    """A PNG capture re-encoded to WebP in memory (a third of the bytes; nothing is written next to the capture).
    WHY the optional crop: the page sits under a 9 MB budget, and the audit stills only need the dashboard, not Clank's
    sidebar and window chrome; the crop box is in the capture's own pixels and the caption says the capture is cropped."""
    key = str(path)
    assert path.exists(), f"missing media: {path}"
    assert key not in _inlined, f"would inline twice: {path}"
    _inlined.add(key)
    buf = io.BytesIO()
    with Image.open(path) as image:
        # WHY quality 70 for the cropped audit stills: they are UI text on white, where 70 reads the same as 78, and the
        # 9 MB budget is otherwise spent; the uncropped first-wave stills keep 78.
        q = quality if quality is not None else (70 if crop else 78)
        (image.crop(crop) if crop else image).convert("RGB").save(buf, "WEBP", quality=q, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def still(rel: str, label: str, cap: str, crop: tuple[int, int, int, int] | None = None, quality: int | None = None) -> str:
    """Two-tier caption: the bold label says what it is, the dim line says what to notice."""
    path = Path(rel) if rel.startswith("/") else MEDIA / rel
    return (
        '<figure class="cell w2"><button class="zoom nocrop" type="button" aria-label="Open '
        f'{esc(label)} full size"><img alt="{esc(label)}" loading="lazy" src="{png_uri(path, crop, quality)}"></button>'
        f'<figcaption><b>{esc(label)}</b><span class="cap">{esc(cap)}</span></figcaption></figure>'
    )


W2 = ["N6", "N1", "N2"]
# Round 2 N6 stills that show a fault round 3 fixed (their round-3 replacements are in D.N6_R3_STILLS).
R2_SUPERSEDED = {"r2-rig-01-landing.png", "r2-grasping-01-enter.png", "r2-detection-01-enter.png", "r2-kinsim-04-end-copied.png"}
assert set(D.JUDGE_N6) == set(W2) == set(D.JUDGE_R2)
# Round 1 (the first N6 judge) and round 2 (today's re-judge), both recomputed from the raw per-criterion scores.
MEAN_R1 = {n: weighted(D.JUDGE_N6[n]) for n in W2}
MEAN2 = {n: weighted(D.JUDGE_R2[n]) for n in W2}
ORDER_R1 = sorted(W2, key=lambda n: -MEAN_R1[n])
ORDER2 = sorted(W2, key=lambda n: -MEAN2[n])
assert ORDER_R1 == ["N1", "N6", "N2"], f"round-1 order changed: {ORDER_R1}"
# WHY the verdict and the decision default branch on this: the brief says N1 becomes the default page if N6 still
# trails it. The text below is chosen from the recomputed numbers, never typed against them.
N6_LEADS = MEAN2["N6"] > MEAN2["N1"]
# The judge's stated totals must reproduce, or the report says which one does not.
STATED_OFF = {n: D.JUDGE_R2_STATED[n] for n in W2 if abs(D.JUDGE_R2_STATED[n] - MEAN2[n]) > 0.05}
NAME2 = {"N6": D.N6["name"], "N1": NAME["N1"], "N2": NAME["N2"]}
GIF_MAX = 1_500_000
assert (MEDIA / D.N6_R2["hero_gif"]).stat().st_size < GIF_MAX, "the N6 GIF fallback is over 1.5 MB: re-encode it smaller"


def score_cells(r: dict) -> str:
    return "".join(f'<td class="num">{s:g}</td>' for s, _e in r["f"])


def n6_html() -> str:
    h = D.N6_R2
    # WHY the GIF sits hidden and only replaces the video when H.264 cannot play: it is a fallback, not a second hero,
    # and it is the page's only GIF (older proposals fall back to a poster still).
    hero = (
        '<figure class="hero6"><video controls autoplay muted loop playsinline preload="auto" data-n="N6" '
        f'poster="{data_uri(MEDIA / h["poster"], "image/webp")}">'
        f'<source src="{data_uri(MEDIA / h["hero"], "video/mp4")}" type="video/mp4"></video>'
        f'<img id="hero6-gif" class="hidden" alt="N6 hero as a GIF" src="{data_uri(MEDIA / h["hero_gif"], "image/gif")}">'
        f'<figcaption><b><span class="ltr">N6</span> {esc(D.N6_R3_HERO_LABEL)}</b>'
        f'<span class="cap">{esc(D.N6_R3_HERO_CAPTION)}</span></figcaption></figure>'
    )
    # WHY round 2's stills are filtered: four of them show faults round 3 fixed (rig's update first, grasping's thin
    # lead, detection's '+1 more', '8 more are open'). Keeping them as current would mislead, and the page has a 9 MB cap.
    r2_kept = [x for x in h["stills"] if Path(x[0]).name not in R2_SUPERSEDED]
    stills = ('<div class="stills">' + "".join(still(*x) for x in D.N6_R3_STILLS) + "</div>"
              + '<h4>Round 2 stills that still hold</h4><div class="stills">' + "".join(still(*x) for x in r2_kept) + "</div>")
    crit_head = "".join(f'<th class="num">{esc(nm)}<small>{w}</small></th>' for _k, nm, w in D.CRITERIA)
    ncols = 4 + len(D.CRITERIA)
    rows = []
    for n in ORDER2:
        r = D.JUDGE_R2[n]
        stated = (f'<small class="off">judge wrote {D.JUDGE_R2_STATED[n]:g}</small>' if n in STATED_OFF else "")
        delta = MEAN2[n] - MEAN_R1[n]
        rows.append(
            f'<tr class="jrow"><th scope="row"><span class="ltr">{n}</span> {esc(NAME2[n])}</th>'
            f'<td class="num wt">{MEAN2[n]:.0f}{stated}</td>'
            f'<td class="num r1">{MEAN_R1[n]:.0f}<small>{delta:+.0f}</small></td>{score_cells(r)}'
            f'<td class="gate {"ok" if r["gates"] else "bad"}">{"pass" if r["gates"] else "FAIL"}</td></tr>'
        )
        ev = "".join(
            f'<div class="ev"><b>{k.upper()} {esc(nm)} · {r["f"][i][0]:g}/5</b><p>{inline_md(r["f"][i][1])}</p></div>'
            for i, (k, nm, _w) in enumerate(D.CRITERIA)
        ) + f'<div class="ev"><b>Gates · {"pass" if r["gates"] else "FAIL"}</b><p>{inline_md(r["gate_note"])}</p></div>'
        rows.append(f'<tr class="evrow"><td colspan="{ncols}"><details><summary>Evidence · {n} · round 2</summary>{ev}</details></td></tr>')
    off_note = "".join(
        f" The judge wrote {D.JUDGE_R2_STATED[n]:g} for {n}; its raw scores give {MEAN2[n]:.1f}, which is what the table shows."
        for n in STATED_OFF)
    weights = " / ".join(str(w) for _k, _n, w in D.CRITERIA)
    table = (
        '<div class="tablewrap"><table class="scores"><thead><tr><th></th><th class="num">Round 2<small>of 100</small></th>'
        '<th class="num">Round 1<small>change</small></th>'
        + crit_head + '<th class="gate">Gates</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
        f'<p class="small dim">Round 2: one judge drove N6, N1 and N2 on this round\'s build. Weighted = Σ weight × score / 5 '
        f'(weights {weights}), recomputed here from the raw scores'
        + ("; the judge's own totals (" + ", ".join(f"{n} {D.JUDGE_R2_STATED[n]:g}" for n in ORDER2) + ") reproduce." if not STATED_OFF else ".")
        + f'{esc(off_note)} Round 1 is the previous judge on the previous build, recomputed the same way.</p>'
    )
    r1_rows = "".join(
        f'<tr><th scope="row"><span class="ltr">{n}</span> {esc(NAME2[n])}</th><td class="num wt">{MEAN_R1[n]:.0f}</td>'
        f'{score_cells(D.JUDGE_N6[n])}<td class="gate {"ok" if D.JUDGE_N6[n]["gates"] else "bad"}">'
        f'{"pass" if D.JUDGE_N6[n]["gates"] else "FAIL"}</td></tr>' for n in ORDER_R1)
    r1_wrong = "".join(f"<li><b>{esc(t)}</b> <span>{inline_md(x)}</span></li>" for t, x in D.N6_STILL_WRONG)
    round1 = (
        '<details class="limits"><summary>Round 1, for reference: the scores and the list N6 was rebuilt against</summary>'
        f'<p class="small">{inline_md(D.JUDGE_N6_VERDICT)}</p>'
        '<div class="tablewrap"><table class="scores"><thead><tr><th></th><th class="num">Weighted</th>'
        + crit_head + '<th class="gate">Gates</th></tr></thead><tbody>' + r1_rows + '</tbody></table></div>'
        f'<ol class="wrong">{r1_wrong}</ol></details>'
    )
    changed = "".join(f"<li><b>{esc(t)}</b> <span>{inline_md(x)}</span></li>" for t, x in D.N6_R2_CHANGED)
    changed3 = "".join(f"<li><b>{esc(t)}</b> <span>{inline_md(x)}</span></li>" for t, x in D.N6_R3_CHANGED)
    assert len(D.N6_R3_ITEM_STATUS) == len(D.N6_R2_STILL_WRONG)
    wrong = "".join(
        f'<li><b>{esc(t)}</b> <span class="{STATUS_WORD[st][1]}">{STATUS_WORD[st][0]} in round 3</span> '
        f'<span>{inline_md(x)}</span><span class="r3line">{inline_md(r3)}</span></li>'
        for (t, x), (st, r3) in zip(D.N6_R2_STILL_WRONG, D.N6_R3_ITEM_STATUS))
    tag = "now the default" if N6_LEADS else "selectable; N1 is the default"
    return f"""
<article class="prop n6" id="prop-N6">
  <header class="prophead"><span class="ltr big">N6</span>
    <h3>{esc(D.N6['name'])} <span class="deftag">{tag}</span></h3>
    <div class="meanbadge" title="round-2 judge, weighted">{MEAN2['N6']:.0f}<small>/ 100 · round 2 (was {MEAN_R1['N6']:.0f})</small></div>
    <p class="thesis">{inline_md(D.N6['thesis'])}</p>
  </header>
  {hero}
  <h4>Scores, round 2: N6 vs N1 vs N2 <small>(no re-judge in round 3, so these are still round 2's)</small></h4>
  <p class="jverdict">{inline_md(D.JUDGE_R2_VERDICT)}</p>
  {table}
  <h4>What changed in round 3</h4>
  <ol class="wrong changed">{changed3}</ol>
  <h4>Stills <small>(round 3, 1440 × 900 unless the label says otherwise)</small></h4>
  {stills}
  <h4>Round 2's list of what was wrong in N6, and what round 3 did <small>(6 of 7 fixed)</small></h4>
  <ol class="wrong">{wrong}</ol>
  <details class="limits"><summary>What changed in round 2 (since round 1)</summary><ol class="wrong changed">{changed}</ol></details>
  {round1}
  {FB.strip("N6", "N6 · " + D.N6['name'], noun="proposal")}
</article>"""


STATUS_WORD = {"fixed": ("fixed", "okt"), "partly": ("partly fixed", "partt"), "open": ("still open", "opent")}


def shared_html() -> str:
    out = []
    assert set(D.SHARED_R3) <= {f["key"] for f in D.SHARED_R2}, "a round-3 key matches no shared fix"
    # WHY round 3 first: the cards it changed are what this round is about; the untouched ones follow in round-2 order.
    order = sorted(D.SHARED_R2, key=lambda f: f["key"] not in D.SHARED_R3)
    for i, f in enumerate(order, 1):
        r3 = D.SHARED_R3.get(f["key"])
        status = r3[0] if r3 else f["status"]
        word, cls = STATUS_WORD[status]
        # A round-2 capture labelled 'Still open' shows a fault round 3 fixed; it is dropped rather than shown as current.
        r2_stills = [x for x in f["stills"] if not (r3 and r3[0] == "fixed" and x[1].startswith("Still open"))]
        # WHY quality 64 for a round-2 capture under a round-3 card: it is the record of an older state, UI text on white
        # that reads the same at 64, and the bytes it frees keep round 3 of Codex's audit inside the 9 MB budget.
        figs = "".join(still(*x) for x in (r3[2] if r3 else [])) + "".join(
            still(x[0], ("Round 2 · " + x[1]) if r3 else x[1], x[2], None, 64 if r3 else None) for x in r2_stills)
        grid = f'<div class="stills two-up">{figs}</div>' if figs else ""
        if r3:
            r3_html = f'<p class="r3"><b>Round 3:</b> {inline_md(r3[1])}</p>'
            was = (f'<p class="was"><b>Round 2 left open:</b> {inline_md(f["still"])}</p>' if f["still"] else "")
            body = f'{r3_html}<details class="limits"><summary>Round 2 on this seam</summary><p>{inline_md(f["body"])}</p>{was}</details>'
            tag = ' <span class="rtag">round 3</span>'
        else:
            still_open = (f'<p class="stillopen"><b>Still open:</b> {inline_md(f["still"])}</p>' if f["still"] else "")
            body = f'<p class="lead">{inline_md(f["body"])}</p>{still_open}'
            tag = ""
        out.append(
            f'<div class="fix" id="fix-{f["key"]}"><h3>{i} · {esc(f["title"])} <span class="{cls}">{word}</span>{tag}</h3>'
            f'{body}{grid}'
            f'{FB.strip("S" + str(i), "Shared fix · " + f["title"], noun="section")}</div>'
        )
    return "".join(out) + f'<p class="small dim">{inline_md(D.SHARED_R3_HOLD)} {inline_md(D.SHARED_R2_HOLD)}</p>'


# ---- the independent audit (Codex round 1) and what verify-5 measured after the fixes -------------------------------
# WHY the rows are parsed from the audit file and the fix data is a JSON beside the captures: the severity and title
# are Codex's words and the evidence is the verifier's; a hand-typed table would outlive either.
AUDIT_FILE = Path("/home/bam/vibetracks/reports/media/audits/2026-10-04-vibetracks-live-needs-r1.md")
AUDIT = json.loads((MEDIA / "audit-r1-fixes.json").read_text())
_AUDIT_TEXT = AUDIT_FILE.read_text()
AUDIT_VERDICT = _AUDIT_TEXT.splitlines()[0].strip()
AUDIT_ROWS = [(int(n), sev, title) for n, sev, title in
              re.findall(r"^(\d+)\. \*\*\[(high|medium|low)\] (.+?)\*\*\s*$", _AUDIT_TEXT, re.M)]
assert AUDIT_VERDICT == "VERDICT: FAIL", AUDIT_VERDICT
assert [n for n, _s, _t in AUDIT_ROWS] == list(range(1, 14)), "the audit file's numbered findings changed"
AUDIT_FIX = {f["n"]: f for f in AUDIT["findings"]}
assert set(AUDIT_FIX) == {n for n, _s, _t in AUDIT_ROWS}
AUDIT_PASS = sum(1 for n, _s, _t in AUDIT_ROWS if AUDIT_FIX[n]["pass"])
AUDIT_SEV = Counter(sev for _n, sev, _t in AUDIT_ROWS)
SEV_LINE = ", ".join(f"{AUDIT_SEV[k]} {k}" for k in ("high", "medium", "low") if AUDIT_SEV[k])

# ---- Codex round 2: its re-read of round 1, its new findings, and what verify-6 measured after the fixes ---------
# WHY the same split as round 1: the status words, severities and titles are parsed from Codex's own file, and the
# evidence is verify-6's, kept in a JSON beside the captures; the live-tracks report renders the same rows from the same files.
AUDIT2_FILE = Path("/home/bam/vibetracks/reports/media/audits/2026-10-05-vibetracks-live-needs-r2.md")
AUDIT2 = json.loads((MEDIA / "audit-r2-fixes.json").read_text())
_AUDIT2_TEXT = AUDIT2_FILE.read_text()
AUDIT2_VERDICT = _AUDIT2_TEXT.splitlines()[0].strip()
AUDIT2_R1 = [(int(n), word, note) for n, word, note in
             re.findall(r"^(\d+)\. (fixed|partly) — (.+?)\s*$", _AUDIT2_TEXT, re.M)]
AUDIT2_ROWS = [(int(n), sev, title) for n, sev, title in
               re.findall(r"^(\d+)\. \*\*\[(high|medium|low)\] (.+?)\*\*\s*$", _AUDIT2_TEXT, re.M)]
assert AUDIT2_VERDICT == "VERDICT: FAIL", AUDIT2_VERDICT
assert [n for n, _w, _x in AUDIT2_R1] == list(range(1, 14)), "round 2's re-read of round 1 changed"
AUDIT2_PARTLY = [n for n, w, _x in AUDIT2_R1 if w == "partly"]
assert AUDIT2_PARTLY == [7, 9, 13] and sorted(map(int, AUDIT2["r1_partly_now"])) == AUDIT2_PARTLY, AUDIT2_PARTLY
assert [n for n, _s, _t in AUDIT2_ROWS] == list(range(1, 8)), "the round-2 file's numbered findings changed"
AUDIT2_FIX = {f["n"]: f for f in AUDIT2["findings"]}
assert set(AUDIT2_FIX) == {n for n, _s, _t in AUDIT2_ROWS}
AUDIT2_PASS = sum(1 for n, _s, _t in AUDIT2_ROWS if AUDIT2_FIX[n]["pass"] is True)
AUDIT2_SEV = Counter(sev for _n, sev, _t in AUDIT2_ROWS)
SEV2_LINE = ", ".join(f"{AUDIT2_SEV[k]} {k}" for k in ("high", "medium", "low") if AUDIT2_SEV[k])
N_IN_SCOPE = len(AUDIT2_ROWS) + len(AUDIT2_PARTLY)


def fix_word(f: dict) -> tuple[str, str]:
    """(css class, words) for the Fixed? column; only a failure gets colour."""
    if f.get("word"):
        return ("afix", f["word"])
    return ("afix", "fixed · verified") if f["pass"] is True else ("afix no", "NOT fixed")


def audit2_html(stills: list[tuple[str, str, str]], r1_stills: list[tuple[str, str, str]]) -> str:
    r1 = "".join(
        f'<li class="r1row"><span class="an">{n}</span><span class="r1w{" partly" if w == "partly" else ""}">{esc(w)}</span>'
        f'<span class="r1note">{inline_md(note)}</span>'
        f'<span class="r1now">{esc(AUDIT2["r1_partly_now"][str(n)] + " · verified") if w == "partly" else ""}</span></li>'
        for n, w, note in AUDIT2_R1)
    rows = [(str(n), sev, title, AUDIT2_FIX[n]) for n, sev, title in AUDIT2_ROWS] + [
        ("+", "peer", p["title"], p) for p in AUDIT2["peers"]]
    items = "".join(
        f'<li class="arow"><span class="an">{esc(n)}</span><span class="asev">{esc(sev)}</span>'
        f'<div class="abody"><b>{esc(title)}</b><p>{esc(f["short"])}</p>'
        # WHY the round-6 status beside verify-6's words: three of these siblings are closed now; the page keeps what
        # verify-6 saw and says what became of it, rather than calling a closed item open.
        + (f'<p class="asib"><b>verify-6 left open beside it:</b> {esc(f["sibling"])} <b>Now:</b> '
           f'{esc(R6["r2_siblings_now"][str(n)])}</p>' if f.get("sibling") else "")
        + f'<details><summary>The verifier\'s evidence, and the test that fails when the old behaviour returns</summary>'
        f'<p class="averb">{esc(f["verifier"])}</p><p class="averb"><b>Test left ({esc(f["lane"])} lane):</b> {esc(f["tests"])}</p>'
        f'</details></div><span class="{fix_word(f)[0]}">{esc(fix_word(f)[1])}</span></li>'
        for n, sev, title, f in rows)
    notes = "".join(f"<li><b>{esc(t)}.</b> <span>{esc(x)}</span></li>" for t, x in AUDIT2["observations"])
    c = AUDIT2["checks"]
    figs = '<div class="stills">' + "".join(still(*x) for x in stills) + "</div>" if stills else ""
    partly = ", ".join(map(str, AUDIT2_PARTLY[:-1])) + f" and {AUDIT2_PARTLY[-1]}"
    return f"""
<p class="lead"><b>{esc(AUDIT2['auditor'])}</b>, round {AUDIT2['round']}, read-only, audited <code>{esc(AUDIT2['audited_sha'])}</code> and
returned <b>{esc(AUDIT2_VERDICT)}</b>: round-1 findings {partly} were only partly fixed, and it found {len(AUDIT2_ROWS)} new ones
({SEV2_LINE}). Three lanes fixed them on the uncommitted tree ({esc(AUDIT2['tree_after'])}). Then {esc(AUDIT2['verifier'])} re-probed
all {N_IN_SCOPE}: <b>{AUDIT2_PASS + len(AUDIT2_PARTLY)} of {N_IN_SCOPE} pass</b>, each with a test at the consumer that fails on
<code>{esc(AUDIT2['audited_sha'])}</code>. Codex round 3 then re-read them on 56c75c0: {esc(AUDIT3_R2_LINE)} (the round-3
table above).</p>
<p class="small dim">Audit file: <code>{esc(str(AUDIT2_FILE))}</code><br>After the fixes: pytest {esc(c['pytest'])}; unittest
{esc(c['unittest'])}; backend {esc(c['backend'])}; tsc {esc(c['tsc'])}; node checks {esc(c['node_checks'])}; browser checks
{esc(c['browser_checks'])}. On {esc(AUDIT2['audited_sha'])}: {esc(c['fails_on_old'])}; and {esc(c['mutation'])}. Report videos:
{esc(c['videos'])}.</p>
<h4>Round 1's {len(AUDIT2_R1)} findings, as Codex round 2 re-read them</h4>
<ol class="r1s">{r1}</ol>
<h4>Round 2's {len(AUDIT2_ROWS)} new findings, plus the two asks from the track pages</h4>
<div class="ahead"><span>#</span><span>Severity</span><span>Codex's finding · what verify-6 measured after the fix</span><span>Fixed?</span></div>
<ol class="audit">{items}</ol>
{figs}
<h4>What verify-6 noticed but did not count as a failure</h4>
<ul class="open">{notes}</ul>
<details class="limits"><summary>Round 1: Codex's {len(AUDIT_ROWS)} findings on 3e90b94 and verify-5's evidence</summary>
{audit_html(r1_stills)}</details>"""


def audit_html(stills: list[tuple[str, str, str]]) -> str:
    peer = AUDIT["peer"]
    rows = [(str(n), sev, title, AUDIT_FIX[n]) for n, sev, title in AUDIT_ROWS] + [("+", "peer", peer["title"], peer)]
    items = "".join(
        f'<li class="arow"><span class="an">{esc(n)}</span><span class="asev{" hi" if sev == "high" else ""}">{esc(sev)}</span>'
        f'<div class="abody"><b>{esc(title)}</b><p>{esc(f["short"])}</p>'
        f'<details><summary>The verifier\'s evidence, and the test that would have caught it</summary>'
        f'<p class="averb">{esc(f["verifier"])}</p><p class="averb"><b>Test left ({esc(f["lane"])} lane):</b> {esc(f["tests"])}</p>'
        f'</details></div><span class="afix{"" if f["pass"] else " no"}">{"fixed · verified" if f["pass"] else "NOT fixed"}</span></li>'
        for n, sev, title, f in rows)
    notes = "".join(f"<li><b>{esc(t)}.</b> <span>{esc(x)}</span></li>" for t, x in AUDIT["observations"])
    checks = AUDIT["checks"]
    figs = '<div class="stills">' + "".join(still(*x) for x in stills) + "</div>" if stills else ""
    return f"""
<p class="lead"><b>{esc(AUDIT['auditor'])}</b>, round {AUDIT['round']}, read-only, audited <code>{esc(AUDIT['audited_sha'])}</code> and
returned <b>{esc(AUDIT_VERDICT)}</b> with {len(AUDIT_ROWS)} findings ({SEV_LINE}). Three lanes fixed them on the uncommitted tree
({esc(AUDIT['tree_after'])}). Then {esc(AUDIT['verifier'])} re-ran every finding Codex's way or harder: <b>{AUDIT_PASS} of
{len(AUDIT_ROWS)} pass</b>, plus the 390 px overflow a peer found, with no regressions. Codex round 2 then re-read
all {len(AUDIT_ROWS)}: its status line for each is above.</p>
<p class="small dim">Audit file: <code>{esc(str(AUDIT_FILE))}</code><br>After the fixes: pytest {esc(checks['pytest'])}; backend
{esc(checks['backend_pytest'])}; tsc {esc(checks['tsc'])}; node checks {esc(checks['node_checks'])}; videos {esc(checks['videos'])};
{checks['console_errors']} console errors.</p>
<div class="ahead"><span>#</span><span>Severity</span><span>Codex's finding · what verify-5 measured after the fix</span><span>Fixed?</span></div>
<ol class="audit">{items}</ol>
{figs}
<h4>What verify-5 noticed but did not count as a failure</h4>
<ul class="open">{notes}</ul>"""


# The dashboard without Clank's sidebar and window chrome, in capture pixels (the captures are 1440 x 900).
PAGE_CROP = (288, 130, 1440, 872)

# WHY the folded rounds' stills are re-encoded below the default quality (see the loop after AUDIT2_STILLS): round 6
# added three stills and the page must stay under 9 MB; these sit two clicks deep as the record of earlier rounds.
AUDIT_STILLS = [
    ("verify-5/v5-n6-2-changed-notice.png", "Finding 1: a draft on a changed question is not copied",
     "verify-5 rewrote the real /needs in flight so T47's recommendation reads '(UPDATED: now 46 V)'; that text is the "
     "probe's, not the loop's. The draft made on 44 V shows its note word for word, is named as not in the copy, and "
     "waits for Reconfirm or Discard. Cropped to the dashboard.", PAGE_CROP),
    ("verify-5/v5-n5-changed.png", "N5 on the live lane: the new module is served",
     "Round 3's leftover is gone: the 4390 lane serves N5 with 'Recommended', not 'I recommend', and the same stale "
     "notice. Copy answers is disabled and T47 is named under 'Not in the copy'. Cropped to the dashboard.", PAGE_CROP),
    ("verify-5/v5-settings-include-defaulting.png", "Finding 13: the queue option lives in Settings",
     "'Needs you · Include questions whose default is already in effect', off by default. 'Review them too' is gone from "
     "N1–N6; turning this on takes N6's kinsim lane from 3 cards to 11. Cropped to the settings page.", (48, 130, 800, 700)),
]

AUDIT2_STILLS = [
    ("verify-6/v6-evidence-real-409.png", "Finding 1: a link to a changed document opens nothing",
     "verify-6 handed the page a stale revision (the probe's doing; the evidence itself was unchanged). The real backend "
     "answered 409, T47's evidence line reads 'This changed since you opened it: reload' and no tab opened; reload "
     "re-fetched /needs and the link then opened with 200. Cropped to the card.", (480, 130, 1240, 740)),
    ("verify-6/v6-n5-kinsim-chip-pressed.png", "Finding 7: N5 with a chip pressed, and no blue",
     "'Go with the recommendation' pressed on kinsim T12: a grey fill and ring; the recommended tag, the meter and the "
     "draft bubble are neutral. verify-6's census found 0 blue elements on N1–N6 for kinsim and rig. Cropped to the "
     "dashboard.", (288, 170, 1440, 830)),
]

AUDIT_STILLS = [(*x, 48) for x in AUDIT_STILLS]
AUDIT2_STILLS = [(*x, 52) for x in AUDIT2_STILLS]

DECISION_R5 = f"""
<ul>
  <li><strong>Done and proved</strong> (verify-6, a measure-only re-check by a separate Claude agent; it made no product edits):
    <ul>
      <li><b>Codex round 2:</b> its {len(AUDIT2_ROWS)} new findings and the partly fixed round-1 findings 7, 9 and 13 are fixed. verify-6 re-probed all {N_IN_SCOPE} Codex's way or harder, and each has a test at the consumer that fails on b53567e. Table above.</li>
      <li><b>For this page:</b> an evidence link opens only the file listed in the document you reviewed; if anything in it changed, the click says 'This changed since you opened it: reload' and opens nothing (1). No path component is followed through a symlink (2). Copy-out keeps every CR, CRLF and option edge space, with an 'exact:' line where Markdown would lose one (3). N4 and N5 use no blue for ordinary states (7).</li>
      <li><b>From the track pages:</b> the proven subline's hover now explains the count (its text is pinned by a check, but it was not seen in the app: this worktree's roadmap is a stub), and a long track title wraps at 390 px with Clank's panel open.</li>
      <li><b>Regressions checked:</b> one Needs-you count everywhere (kinsim 1/3, rig 2/6, grasping 0/7, detection 1/3; pyblocks and CAN 12/16 'not reported'); the rename round trip is byte-identical for an LF and a BOM+CRLF note; 7 of 7 report videos play; no sideways scroll at 1440 on 22 routes.</li>
      <li><b>Build:</b> pytest 299 passed, 0 skipped; unittest discover 299 OK (it crashed on b53567e); backend 23; tsc clean; node checks 74/74; rename_fence and media_switch pass in the browser.</li>
    </ul></li>
  <li><strong>Left</strong> (next; none blocked on you):
    <ul>
      <li><b>Codex round 3</b> on this tree (b53567e plus the round-2 fixes, uncommitted). It runs next; both reports are re-shared before it starts.</li>
      <li>Siblings verify-6 found beside fixed findings: /media links are not bound to a revision (beside 1); an item title's trailing spaces are lost in the parsed Markdown heading (beside 3); the V1 bench verdict does not yet require all nine modules (beside 6); variants B and C still use blue (beside 7).</li>
      <li>At 390 × 844 with Clank's panel open, 6 of 14 iteration and item pages scroll sideways (detail in the live-tracks report). On N6 at 1280 × 800, rig T2's note box loses its bottom 8 px under the switcher (unchanged since verify-5).</li>
      <li>Docs: PROJECTION.md:159 still describes the old O_NOFOLLOW / 403 evidence rule; NEEDS-KIT.md does not describe the 'exact:' lines.</li>
      <li>From earlier rounds: the settled-draft copy line offers a Reconfirm that does not exist; N6's deployment lane says 'loop' twice; the first-wave N1–N5 cards below still describe 'Review them too'.</li>
    </ul></li>
  <li><strong>Needs you</strong> (each has the default I take if you say nothing):
    <ol>
      <li><b>Fix verify-6's siblings before Codex round 3 reads the tree?</b> Recommendation: yes for the /media revision binding and the 390 px item and iteration pages, which Codex would read as the same class as finding 1 and the old overflow; the rest can ride. Default: round 3 runs on this tree, with these listed for it.</li>
      <li><b>Your existing drafts still show the stale notice</b> ('drafted before the dashboard recorded which version of the question you saw'). Recommendation: discard them and answer again on N6. Default: they stay stale and are never copied.</li>
      <li><b>Keep N6 as the default?</b> The judges' round 2 scored it 93 against N1's 87; nothing since has lowered it. Recommendation: keep it. Default: N6 stays the default.</li>
      <li><b>Retire N2–N5 from the chooser</b> after Codex round 3? Recommendation: yes, keep N1 as the calm comparison. Default: all six stay selectable.</li>
      <li><b>Commit the wave</b> on <code>claude/vibetracks-dashboard</code>? Recommendation: yes, once a Codex round passes, so a peer's <code>stash -u</code> cannot take it. Default: left uncommitted.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no re-judge of N6, so its scores are the judges' round 2. Nothing is sent; answers only copy out. No commits, no vault edits. verify-6's siblings and the 390 px pages were not fixed in this pass, and the proven hover was not seen in the app.</li>
</ul>
"""

DECISION_R4 = f"""
<ul>
  <li><strong>Done and proved</strong> (verify-5, a measure-only re-check by a separate Claude agent; it made no product edits):
    <ul>
      <li><b>Codex round 1:</b> {AUDIT_PASS} of {len(AUDIT_ROWS)} findings fixed and re-run Codex's way or harder, plus the 390 px overflow. Table above.</li>
      <li><b>For this page:</b> a draft is copied only while the question, its options, its default and its status read as they did when you drafted it (finding 1); notes copy byte-exact and never as an unoffered 'other' (7); one Needs-you count on home, the track line, N1–N6 headers and /needs (5); an unreadable triage file reads 'not reported', never 0 (3); the defaulting-questions option is a setting, off by default (13).</li>
      <li><b>Round 3's two leftovers are cleared:</b> the 4390 lane serves the new N5 ('Recommended'; the module Vite serves has no 'I recommend'), and every hover time on home and the five work-track pages is local with its zone (0 raw ISO stamps, scanned 10-05 01:31 PDT).</li>
      <li><b>Build:</b> pytest 276 passed, 0 skipped; backend 23 passed; tsc clean; node checks 21/21, 6/6, 6/6; 0 console errors; 7 of 7 report videos play.</li>
    </ul></li>
  <li><strong>Left</strong> (next; none blocked on you):
    <ul>
      <li><b>Codex round 2</b> on this tree (3e90b94 plus 63 uncommitted changes). It runs next; this page and the live-tracks report are re-shared before it starts.</li>
      <li>From verify-5's notes: a settled draft's copy line says 'reconfirm or discard it' although only Discard is offered; a lone carriage return in a note drops text in the Markdown copy (typing cannot produce one).</li>
      <li>Findings 10 (the UI fold), 11 and 13 and the 390 px overflow are guarded by headless probes, not by tests in the suite.</li>
      <li>N6's one open judge item from round 2: a deployment's empty lane still says 'loop' twice.</li>
      <li>The first-wave N1–N5 cards below still describe 'Review them too'; that control is now the Settings option.</li>
    </ul></li>
  <li><strong>Needs you</strong> (each has the default I take if you say nothing):
    <ol>
      <li><b>Your existing drafts now all show the stale notice</b> ('drafted before the dashboard recorded which version of the question you saw'), because nothing can prove what they answered. Recommendation: discard them and answer again on N6, which takes seconds per card. Default: they stay stale and are never copied.</li>
      <li><b>Keep N6 as the default?</b> Round 2 scored it 93 against N1's 87; nothing since has lowered it. Recommendation: keep it. Default: N6 stays the default.</li>
      <li><b>Retire N2–N5 from the chooser</b> after Codex round 2? Recommendation: yes, keep N1 as the calm comparison; fewer variants is less to keep true. Default: all six stay selectable.</li>
      <li><b>Commit the wave</b> on <code>claude/vibetracks-dashboard</code>? Recommendation: yes, once Codex round 2 passes, so a peer's <code>stash -u</code> cannot take it. Default: left uncommitted.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no re-judge of N6, so its scores are round 2's. Nothing is sent; answers only copy out. No commits, no vault edits, no Vite restart (none was needed). verify-5's low-severity notes were not fixed in this pass.</li>
</ul>
"""


# ---- round 6: verify-6's siblings and leftovers, closed and re-measured by verify-7 ------------------------------
# WHY a data file shared with the live-tracks report: both pages render the same six rows and the same open list, so
# neither can drift from the other or from verify-7's words; the probes keep the "still open" list honest (below).
R6 = json.loads((MEDIA / "r6" / "round6-fixes.json").read_text())
R6_ITEMS = R6["items"]
assert [i["n"] for i in R6_ITEMS] == ["1", "2", "3", "4", "5", "6"], "round 6's item list changed: re-read the verdict"
R6_PASS = sum(1 for i in R6_ITEMS if i["pass"] is True)
R6_PARTLY = [i for i in R6_ITEMS if i["pass"] == "partly"]
assert (R6_PASS, len(R6_PARTLY)) == (5, 1), (R6_PASS, len(R6_PARTLY))
REPO = Path(__file__).resolve().parents[2]


R6_TREE = "56c75c0"  # the commit round 6's tree became, and the snapshot Codex round 3 audited


def _probe_text(probe: dict, at: str | None) -> str | None:
    """The probed file's text in the working tree (at=None) or in commit `at`; None when it does not exist there."""
    name = probe["file"]
    if at is None or name.startswith("/"):
        f = Path(name) if name.startswith("/") else REPO / name
        return f.read_text(encoding="utf-8") if f.exists() else None
    shown = subprocess.run(["git", "-C", str(REPO), "show", f"{at}:{name}"], capture_output=True, text=True)
    return shown.stdout if shown.returncode == 0 else None


def check_open_probes(probes: list[dict], at: str | None = None, source: str = "round6-fixes.json",
                      closed: frozenset[str] = frozenset()) -> int:
    """Refuse to build if a tree no longer shows an item the page calls open.
    WHY: a report built after a peer fixes one of these would still list it as open; a stale 'open' is as untrue as a
    stale 'fixed'. Each probe names the exact text that makes the claim true.
    WHY `at`: round 6's 'still open' lines describe the tree Codex round 3 read (56c75c0), and most of them were closed
    in e0bd8e5 since; the page now says so beside each one, so those probes check the commit they describe, while the
    current round's open list is checked against the working tree."""
    where = at or "the working tree"
    for probe in probes:
        text = _probe_text(probe, at)
        if probe["claim"] in closed:
            # WHY: verify-7 measured these on the uncommitted tree and the commit itself closed them; the page says so,
            # so the probe must now read closed there, not open.
            assert text is not None and probe.get("contains") and probe["contains"] not in text, \
                f"{probe['claim']}: listed as closed by {where} but still open there"
            continue
        if probe.get("missing"):
            assert text is None, f"{probe['claim']}: {probe['file']} exists in {where}; re-measure and update {source}"
            continue
        assert text is not None, f"{probe['claim']}: {probe['file']} is missing in {where}; update {source}"
        if "contains" in probe:
            assert probe["contains"] in text, f"looks fixed in {where}: {probe['claim']} ({probe['file']}); update {source}"
        if "absent" in probe:
            assert probe["absent"] not in text, f"looks fixed in {where}: {probe['claim']} ({probe['file']}); update {source}"
    return len(probes)


# WHY AUDIT3 is read here, ahead of its section: it records which of round 6's open claims the 56c75c0 commit closed.
AUDIT3 = json.loads((MEDIA / "r7" / "audit-r3-fixes.json").read_text())
R6_PROBES = check_open_probes(R6["open_probes"], at=R6_TREE, closed=frozenset(AUDIT3["r6_closed_by_commit"]))
LIVE_MEDIA = Path("/home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04")
# WHY no home still here: home is the live-tracks report's page (it carries the 04:35 re-capture); this page stays
# under 9 MB by showing only what round 6 changed on the needs page and in media.
R6_STILLS = [
    (str(LIVE_MEDIA / "r6-1440-needs-pill-docked.png"), "The needs page: the bar holds only the needs pill",
     "The UI lane's capture of kinsim's N6 page with Clank's panel wide: 'Needs you N6 · Lane + context ▾' alone at the "
     "bottom right, nothing beside it. Cropped to the dashboard.", (900, 130, 1440, 872), 62),
    (str(LIVE_MEDIA / "verify-7" / "v7-media-stale-line.png"), "/media answering 409: one calm line",
     "verify-7 made /media answer 409 for this item. MediaView shows 'This changed since you opened it: reload' with no "
     "player and no 'Open in new tab'; reload re-reads /projection. Cropped.", (288, 150, 1000, 520), 70),
]


def round6_html() -> str:
    items = "".join(
        f'<li class="arow"><span class="an">{esc(i["n"])}</span><span class="asev">{esc(i["lane"])}</span>'
        f'<div class="abody"><b>{esc(i["title"])}</b><p>{esc(i["short"])}</p>'
        # WHY the 'Now' beside verify-7's words: most of these were closed in e0bd8e5 or this wave; the page keeps what
        # verify-7 saw at 56c75c0 and says what became of it, rather than calling a closed item open.
        + (f'<p class="asib"><b>Still open beside it at {R6_TREE}:</b> {esc(i["still_open"])} <b>Now:</b> '
           f'{esc(AUDIT3["r6_still_now"][i["n"]])}</p>' if i["still_open"] else "")
        + '<details><summary>verify-7\'s evidence, and the test that fails when the old behaviour returns</summary>'
        f'<p class="averb">{esc(i["verifier"])}</p><p class="averb"><b>Test left ({esc(i["lane"])} lane):</b> {esc(i["tests"])}</p>'
        f'</details></div><span class="afix">{"fixed · verified" if i["pass"] is True else "partly · 2 doc gaps"}</span></li>'
        for i in R6_ITEMS)
    found = "".join(f"<li><b>{esc(t)}.</b> <span>{esc(x)}</span> <b>Now:</b> {esc(AUDIT3['r6_found_now'][t])}</li>"
                    for t, x in R6["new_found"])
    c = R6["checks"]
    figs = '<div class="stills">' + "".join(still(*x) for x in R6_STILLS) + "</div>"
    return f"""
<p class="lead">verify-6 left a short list beside its fixed findings. Two lanes closed it on the uncommitted tree over
<code>{esc(R6['base_sha'])}</code>; then {esc(R6['verifier'])} re-measured each item: <b>{R6_PASS} of {len(R6_ITEMS)} closed, the docs
partly</b>, each with a test that fails without the fix. Variants B and C were retired at your pick of A (recoverable from git).
This tree was committed as <code>{R6_TREE}</code>, and Codex round 3 audited it (above).</p>
<p class="small dim">After the fixes: pytest {esc(c['pytest'])}; unittest {esc(c['unittest'])}; backend {esc(c['backend'])}; tsc
{esc(c['tsc'])}; node checks {esc(c['node_checks'])}; browser checks {esc(c['browser_checks'])}. Counts, unchanged: {esc(c['counts'])}.
Each "still open" line below was re-read from {R6_TREE} when this page was built ({R6_PROBES} probes); its "Now" says what
became of it since.</p>
<div class="ahead"><span>#</span><span>Lane</span><span>What was left · what verify-7 measured after the fix</span><span>Closed?</span></div>
<ol class="audit">{items}</ol>
{figs}
<h4>New, found by verify-7 (not fixed in round 6)</h4>
<ul class="open">{found}</ul>"""


DECISION_R6 = f"""
<ul>
  <li><strong>Done and proved</strong> (verify-7, a measure-only re-check by a separate Claude agent; it made no product edits):
    <ul>
      <li><b>verify-6's leftovers:</b> {R6_PASS} of {len(R6_ITEMS)} closed and re-measured, each with a test that fails without the fix; the docs are right except two gaps. Table at the top.</li>
      <li><b>For this page:</b> an item title, id, option label or track title with edge spaces or markup now copies out exactly (168 of 168 of verify-7's cases; 93 on the old exporter). /needs is read once per page (was 4). On the needs page the bar holds only the needs pill.</li>
      <li><b>Variants B and C are removed</b>, at your pick of A, with the A · B · C pill, its keys and the stored choice. Both are recoverable from git: commit <code>{esc(R6['variants_commit'])}</code> added them, and their last version is still in HEAD <code>{esc(R6['base_sha'])}</code> because the deletion is not committed (<code>git checkout {esc(R6['base_sha'])} -- clank/src/variants/b clank/src/variants/c clank/src/variants/index.ts</code>).</li>
      <li><b>Regressions checked:</b> one Needs-you count everywhere ({esc(R6['checks']['counts'])}); N6 T47's evidence link opens, and a stale one answers 409, reloads, then opens; the N6 fold is unchanged at 1440 × 900 and 1280 × 800; the rename round trip is byte-identical; {esc(R6['checks']['videos'])}.</li>
      <li><b>Build:</b> pytest {esc(R6['checks']['pytest'])}; unittest {esc(R6['checks']['unittest'])}; backend {esc(R6['checks']['backend'])}; tsc clean; node checks {esc(R6['checks']['node_checks'])}; narrow, needs_once and rename_fence pass in the browser. media_switch fails: its route glob does not match the new <code>?rev=</code> URLs (a one-line fix, verified on a copy).</li>
    </ul></li>
  <li><strong>Left</strong> (next; none blocked on you):
    <ul>
      <li><b>Codex round 3</b> on this tree ({esc(R6['base_note'])}). It runs next; both reports are re-shared before it starts.</li>
      <li>Open beside the fixes: first loads still read /projection 4 times (2 live builds); the real-and-sim video pair shows two dead players on a 409 instead of the reload line; in snapshot mode a retargeted link keeps its revision, so its reload cannot recover it.</li>
      <li>Found by verify-7: grasping's two gallery media always answer 404 (their ids contain ':'); a 404 or 403 still offers 'Open in new tab'; media_switch.mjs's glob; one media-revision map shared by two viewers (read, not reproduced).</li>
      <li>Docs and tools: NEEDS-KIT.md does not describe the 'exact title / id / option label / track title' lines; VARIANTS.md, VARIANT-KIT.md and <code>scripts/shoot.mjs</code> still describe or click B and C.</li>
      <li>From earlier rounds: on N6 at 1280 × 800 rig T2's note box loses its bottom 8 px; N6's deployment lane says 'loop' twice; the settled-draft copy line offers a Reconfirm that does not exist.</li>
    </ul></li>
  <li><strong>Needs you</strong> (each has the default I take if you say nothing):
    <ol>
      <li><b>Fix verify-7's open items before Codex round 3?</b> Recommendation: yes for the double /projection read, the video pair's 409 and grasping's ':' ids, which Codex would read as the same class as fixes it already asked for, and the media_switch glob so the suite is green; the docs and the snapshot-mode case can ride. Default: round 3 runs on this tree, with these listed for it.</li>
      <li><b>Your existing drafts still show the stale notice.</b> Recommendation: discard them and answer again on N6. Default: they stay stale and are never copied.</li>
      <li><b>Keep N6 as the default?</b> The judges' round 2 scored it {MEAN2['N6']:.0f} against N1's {MEAN2['N1']:.0f}; nothing since has lowered it. Recommendation: keep it. Default: N6 stays the default.</li>
      <li><b>Retire N2–N5 from the chooser</b> the way B and C went? Recommendation: yes, keep N1 as the calm comparison. Default: all six stay selectable.</li>
      <li><b>Commit the wave</b> on <code>claude/vibetracks-dashboard</code>? Recommendation: yes, once a Codex round passes, so a peer's <code>stash -u</code> cannot take it (the B and C deletion included). Default: left uncommitted.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no re-judge of N6, so its scores are the judges' round 2. Nothing is sent; answers only copy out. No commits, no vault edits. verify-7's open items were not fixed in this pass; the reports only record them.</li>
</ul>
"""


# ---- Codex round 3: its re-read of earlier findings, its five new findings, and their fixes ----------------------
# WHY the same split as rounds 1 and 2: the status words, severities and titles are parsed from Codex's own file, and
# the fix evidence is verify-8's (e0bd8e5) and verify-9's (this wave), kept in a JSON beside the captures; the
# live-tracks report renders the same rows from the same files, so the two pages cannot tell the round differently.
AUDIT3_FILE = Path("/home/bam/vibetracks/reports/media/audits/2026-10-05-vibetracks-live-needs-r3.md")
_AUDIT3_TEXT = AUDIT3_FILE.read_text()
AUDIT3_VERDICT = _AUDIT3_TEXT.splitlines()[0].strip()
AUDIT3_EARLIER = re.findall(r"^- \*\*(r\d+-\d+): (fixed|partly)\*\* — (.+?)\s*$", _AUDIT3_TEXT, re.M)
AUDIT3_ROWS = [(int(n), sev, title) for n, sev, title in
               re.findall(r"^(\d+)\. \*\*\[(high|medium|low)\] (.+?)\*\*\s*$", _AUDIT3_TEXT, re.M)]
assert AUDIT3_VERDICT == "VERDICT: FAIL", AUDIT3_VERDICT
assert len(AUDIT3_EARLIER) == 10, "round 3's re-read of the earlier findings changed: re-read the file"
AUDIT3_PARTLY = [k for k, w, _x in AUDIT3_EARLIER if w == "partly"]
assert AUDIT3_PARTLY == ["r2-1", "r2-4", "r1-9"] and sorted(AUDIT3["earlier_now"]) == sorted(AUDIT3_PARTLY), AUDIT3_PARTLY
assert [n for n, _s, _t in AUDIT3_ROWS] == [1, 2, 3, 4, 5], "the round-3 file's numbered findings changed"
AUDIT3_FIX = {f["n"]: f for f in AUDIT3["findings"]}
assert set(AUDIT3_FIX) == {n for n, _s, _t in AUDIT3_ROWS}
AUDIT3_PASS = sum(1 for n, _s, _t in AUDIT3_ROWS if AUDIT3_FIX[n]["pass"] is True)
AUDIT3_SEV = Counter(sev for _n, sev, _t in AUDIT3_ROWS)
SEV3_LINE = ", ".join(f"{AUDIT3_SEV[k]} {k}" for k in ("high", "medium", "low") if AUDIT3_SEV[k])
AUDIT3_WHERE = {w: [n for n in sorted(AUDIT3_FIX) if AUDIT3_FIX[n]["where"] == w] for w in ("e0bd8e5", "this wave")}
assert AUDIT3_WHERE == {"e0bd8e5": [3, 4], "this wave": [1, 2, 5]}, AUDIT3_WHERE
R2_IN_R3 = [(k, w) for k, w, _x in AUDIT3_EARLIER if k.startswith("r2-")]
AUDIT3_R2_LINE = (f"{sum(1 for _k, w in R2_IN_R3 if w == 'fixed')} of {len(R2_IN_R3)} fixed, "
                  + " and ".join(k.replace("r2-", "finding ") for k, w in R2_IN_R3 if w == "partly") + " only partly")
# WHY probed against the working tree: these are the items this round's page calls open now.
R7_PROBES = check_open_probes(AUDIT3["open_probes"], source="r7/audit-r3-fixes.json")


def _nums(ns: list[int]) -> str:
    return ", ".join(map(str, ns[:-1])) + f" and {ns[-1]}" if len(ns) > 1 else str(ns[0])


# WHY one still: the page sits under its 9 MB budget; the needs-side fix (finding 1) is a link that shows the file you
# reviewed, so the still is that link on N6's first card. The track-page stills live in the live-tracks report.
R7_STILLS = [
    (str(LIVE_MEDIA / "verify-9" / "v9-n6-fold-1440x900-kinsim.png"), "N6's first card: its evidence link is the document's",
     "verify-9's capture of kinsim T47 at 1440 × 900. 'evidence research/w3-bt1-belt.md' opens /needs/evidence with this "
     "document's eid and revision, never /media; verify-9 clicked every N6 link on kinsim and rig (9 of 9): one tab each, "
     "serving the reviewed bytes. Cropped to the card.", (500, 165, 1225, 470), 62),
]


def audit3_html() -> str:
    earlier = "".join(
        f'<li class="r1row r3"><span class="an">{esc(k)}</span><span class="r1w{" partly" if w == "partly" else ""}">{esc(w)}</span>'
        f'<span class="r1note">{inline_md(note)}</span>'
        f'<span class="r1now">{esc(AUDIT3["earlier_now"][k]) if w == "partly" else ""}</span></li>'
        for k, w, note in AUDIT3_EARLIER)
    items = "".join(
        f'<li class="arow"><span class="an">{n}</span><span class="asev">{esc(sev)}</span>'
        f'<div class="abody"><b>{esc(title)}</b><p>{esc(AUDIT3_FIX[n]["short"])}</p>'
        f'<details><summary>The verifier\'s evidence, and the test that fails when the old behaviour returns</summary>'
        f'<p class="averb">{esc(AUDIT3_FIX[n]["verifier"])}</p>'
        f'<p class="averb"><b>Test left ({esc(AUDIT3_FIX[n]["lane"])} lane):</b> {esc(AUDIT3_FIX[n]["tests"])}</p>'
        f'</details></div><span class="afix">fixed · verified<br><small>'
        f'{"in e0bd8e5" if AUDIT3_FIX[n]["where"] == "e0bd8e5" else "this wave"}</small></span></li>'
        for n, sev, title in AUDIT3_ROWS)
    also = "".join(f"<li><b>{esc(t)}.</b> <span>{esc(x)}</span></li>" for t, x in AUDIT3["also_in_e0bd8e5"])
    left = "".join(f"<li><b>{esc(t)}.</b> <span>{esc(x)}</span></li>" for t, x in AUDIT3["open"])
    notes = "".join(f"<li><b>{esc(t)}.</b> <span>{esc(x)}</span></li>" for t, x in AUDIT3["observations"])
    c = AUDIT3["checks"]
    figs = '<div class="stills">' + "".join(still(*x) for x in R7_STILLS) + "</div>"
    return f"""
<p class="lead"><b>{esc(AUDIT3['auditor'])}</b>, round {AUDIT3['round']}, read-only, audited {esc(AUDIT3['snapshot'])}, and
returned <b>{esc(AUDIT3_VERDICT)}</b>: {len(AUDIT3_PARTLY)} earlier findings were only partly fixed, and it found {len(AUDIT3_ROWS)}
new ones ({SEV3_LINE}). Findings {_nums(AUDIT3_WHERE['e0bd8e5'])} were fixed in <code>e0bd8e5</code>; {_nums(AUDIT3_WHERE['this wave'])}
in this wave, uncommitted on it. Then {esc(AUDIT3['verifier'])} re-probed all {len(AUDIT3_ROWS)} Codex's way or harder:
<b>{AUDIT3_PASS} of {len(AUDIT3_ROWS)} pass</b>, each with a test at the consumer that fails on the tree before its fix, and no
regressions. <b>Codex round 4 reads this tree next</b>; until it returns, "fixed" is our own measurement, not Codex's.</p>
<p class="small dim">Audit file: <code>{esc(str(AUDIT3_FILE))}</code><br>After the fixes: pytest {esc(c['pytest'])}; unittest
{esc(c['unittest'])}; backend {esc(c['backend'])}; tsc {esc(c['tsc'])}; node checks {esc(c['node_checks'])}; browser checks
{esc(c['browser_checks'])}. Before the fixes: {esc(c['fails_on_old'])}. Counts: {esc(c['counts'])}.</p>
<h4>The earlier findings, as Codex round 3 re-read them <small>({len(AUDIT3_EARLIER) - len(AUDIT3_PARTLY)} fixed, {len(AUDIT3_PARTLY)} partly; each partly one is completed by a new finding's fix)</small></h4>
<ol class="r1s">{earlier}</ol>
<h4>Round 3's {len(AUDIT3_ROWS)} new findings</h4>
<div class="ahead"><span>#</span><span>Severity</span><span>Codex's finding · what the verifier measured after the fix</span><span>Fixed?</span></div>
<ol class="audit">{items}</ol>
{figs}
<h4>Also closed in e0bd8e5: verify-7's open items</h4>
<ul class="open">{also}</ul>
<h4>Still open (none blocking; each re-read from the tree when this page was built, {R7_PROBES} probes)</h4>
<ul class="open">{left}</ul>
<h4>What verify-9 noticed but did not count as a failure</h4>
<ul class="open">{notes}</ul>"""


DECISION_R7 = f"""
<ul>
  <li><strong>Done and proved</strong> (verify-8 for e0bd8e5 and verify-9 for this wave, measure-only re-checks by separate Claude agents; neither made product edits):
    <ul>
      <li><b>Codex round 3:</b> all {len(AUDIT3_ROWS)} new findings fixed, {_nums(AUDIT3_WHERE['e0bd8e5'])} in e0bd8e5 and {_nums(AUDIT3_WHERE['this wave'])} in this wave, and the {len(AUDIT3_PARTLY)} partly fixed earlier findings completed by them. Each re-probed Codex's way or harder, each with a test at the consumer that fails without its fix. Table at the top.</li>
      <li><b>For this page:</b> every evidence link opens only the file this Needs document recorded (/needs/evidence with its eid and revision), never /media; a changed document answers 409 and shows the reload line. verify-9 clicked all 9 N6 links on kinsim and rig, and an HTTP pass served the reviewed bytes for 36 of 36 servable entries. Video and large files now seek (Range) and have no size cap.</li>
      <li><b>Current product:</b> variant A is the only dashboard (B and C retired in 56c75c0) and N6 is the default Needs page, N1–N5 still selectable. VARIANTS.md, BRIEF.md and VARIANT-KIT.md mark the older proposals archived; NEEDS-KIT.md describes A + N6.</li>
      <li><b>Regressions checked:</b> {esc(AUDIT3['checks']['counts'])}; {esc(AUDIT3['checks']['overflow'])}; {esc(AUDIT3['checks']['rename'])}.</li>
      <li><b>Build:</b> pytest {esc(AUDIT3['checks']['pytest'])}; unittest {esc(AUDIT3['checks']['unittest'])}; backend {esc(AUDIT3['checks']['backend'])}; tsc clean; node checks {esc(AUDIT3['checks']['node_checks'])}; browser checks {esc(AUDIT3['checks']['browser_checks'])}.</li>
    </ul></li>
  <li><strong>Left</strong> (next; none blocked on you):
    <ul>
      <li><b>Codex round 4</b> on this tree ({esc(AUDIT3['tree_after'])}). It runs next; both reports are re-shared before it starts.</li>
      <li>Still open, none blocking: PROJECTION.md's stale '413' line; <code>scripts/shoot.mjs</code>'s dead <code>--variant</code>; the track pages' /media URLs still take their revision from one shared map; a 404 or 403 keeps 'Open in new tab'; two switcher comments; the roadmap worktree's V1 bridge test.</li>
      <li>From earlier rounds, not re-measured: on N6 at 1280 × 800 rig T2's note box loses its bottom 8 px; N6's deployment lane says 'loop' twice.</li>
    </ul></li>
  <li><strong>Needs you</strong> (each has the default I take if you say nothing):
    <ol>
      <li><b>Fix the still-open items before Codex round 4 reads the tree?</b> Recommendation: yes for the shared revision map on the track pages, which Codex would read as the same class as finding 1, and the two doc lines; the rest can ride. Default: round 4 runs on this tree, with them listed for it.</li>
      <li><b>Commit the wave</b> on <code>claude/vibetracks-dashboard</code>? Recommendation: yes, now, so a peer's <code>stash -u</code> cannot take 30 uncommitted paths; round 4 can audit the commit. Default: left uncommitted.</li>
      <li><b>Retire N2–N5 from the chooser</b> the way B and C went? Recommendation: yes, keep N1 as the calm comparison. Default: all six stay selectable.</li>
      <li><b>Your existing drafts still show the stale notice.</b> Recommendation: discard them and answer again on N6. Default: they stay stale and are never copied.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no re-judge of N6, so its scores are the judges' round 2 ({MEAN2['N6']:.0f} against N1's {MEAN2['N1']:.0f}). Nothing is sent; answers only copy out. No commits, no vault edits. The still-open items were not fixed in this pass; the reports only record them.</li>
</ul>
"""


# ---- page --------------------------------------------------------------------------------------------------------
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
h2.wave1{margin:64px 0 0;padding-top:24px;border-top:1px solid var(--line2);font-size:26px}
h2.wave1 small{font-weight:500;color:var(--dim2);font-size:15px}
.wrap{max-width:1360px;margin:0 auto;padding:0 16px 120px}
h1{font-size:34px;line-height:1.15;margin:0 0 12px;letter-spacing:-.02em}
h2{font-size:22px;margin:0 0 6px;letter-spacing:-.01em}
h3{font-size:17px;margin:0 0 6px}
h3 small{font-weight:500;color:var(--dim2);font-size:13px}
h4{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim2);margin:22px 0 8px;font-weight:700}
h4 small{font-weight:500;letter-spacing:0;text-transform:none}
p{margin:0 0 10px}
a{color:var(--accent)}
code{font:12.5px var(--mono);background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:0 4px;overflow-wrap:anywhere}
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
.reach{margin:18px 0 0;max-width:62em;border:1px solid var(--line);border-radius:10px;padding:4px 18px 10px;background:#fff}
.reach ol{margin:6px 0;padding-left:20px;font-size:14px}
.reach li{margin:4px 0}
nav.toc{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);border-bottom:1px solid var(--line);
  display:flex;gap:4px;overflow-x:auto;padding:8px 0;margin:0 -16px 0;padding-left:16px;padding-right:16px;scrollbar-width:none}
nav.toc a{color:var(--dim);text-decoration:none;font-size:13px;padding:5px 11px;border-radius:7px;white-space:nowrap}
nav.toc a:hover{background:var(--panel);color:var(--fg)}
section{padding-top:44px;scroll-margin-top:44px}
.lead{color:var(--dim);margin:0 0 18px;max-width:60em}
.ltr{display:inline-grid;place-items:center;min-width:1.6em;height:1.45em;border-radius:5px;background:var(--fg);color:#fff;font:700 .78em var(--sans);padding:0 .3em;vertical-align:.08em}
.ltr.big{width:44px;height:40px;font-size:18px;border-radius:9px;flex:none}

/* videos: 5 heroes, three then two */
.vids{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.vid{margin:0}
.vid video{width:100%;display:block;border:1px solid var(--line2);border-radius:10px;background:#111;aspect-ratio:1280/800}
figcaption{margin-top:8px;font-size:13px}
figcaption b{display:block;font-size:13.5px}
.cap{display:block;color:var(--dim);font-size:12.5px;line-height:1.5;margin-top:2px}
.vid .cap{font-size:13px}
@media(max-width:980px){.vids{grid-template-columns:1fr 1fr}}
@media(max-width:620px){.vids{grid-template-columns:1fr}}

/* comparison grid: rows are the same moment, columns are N1..N5 */
.gscroll{overflow-x:auto;margin:0 -16px;padding:0 16px}
.ginner{min-width:1040px}
.gheads,.gcells{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.gheads{position:sticky;top:41px;z-index:10;background:rgba(255,255,255,.95);padding:8px 0;border-bottom:1px solid var(--line);margin-bottom:6px}
.gcol-h{font-weight:700;font-size:13px;line-height:1.3}
.grow{padding-top:20px}
.rowt{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim2);margin:0 0 8px}
.cell{margin:0;min-width:0}
/* WHY crop: every capture is the whole 1440x900 Clank window; the file sidebar (228 px) and the status bar (28 px)
   are shell, not the proposal, and cost a sixth of the width at five-up. The lightbox shows the uncropped file. */
.zoom{all:unset;display:block;width:100%;cursor:zoom-in;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--panel);line-height:0;aspect-ratio:1212/872;position:relative}
.zoom:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.zoom img{width:118.8%;max-width:none;height:auto;display:block;margin-left:-18.8%}
.zoom:hover{border-color:var(--accent)}
.cell figcaption b{font-size:12.5px;font-weight:600}
.capx{display:none}
@media(max-width:760px){
  .gscroll{overflow:visible;margin:0;padding:0}
  .ginner{min-width:0}
  .gheads{display:none}
  .gcells{grid-template-columns:1fr;gap:16px}
}

/* lightbox */
#lb{position:fixed;inset:0;z-index:100;background:rgba(10,12,16,.88);display:none;flex-direction:column;align-items:center;justify-content:center;padding:20px;gap:12px}
#lb.open{display:flex}
#lb img{max-width:100%;max-height:calc(100vh - 120px);object-fit:contain;border-radius:6px;background:#fff;cursor:zoom-out}
#lb .lbcap{color:#e8eaee;font-size:13px;max-width:900px;text-align:center}
@media(max-width:560px){
  #lb{justify-content:flex-start;align-items:flex-start;overflow:auto;padding-top:56px}
  #lb img{max-width:none;max-height:none;width:900px}
  #lb .lbcap{position:sticky;left:0;width:calc(100vw - 40px)}
}
#lb button{position:fixed;top:12px;right:14px;border:1px solid #ffffff55;background:#00000066;color:#fff;border-radius:8px;font:600 13px var(--sans);padding:7px 12px;cursor:pointer}

/* proposals */
.prop{scroll-margin-top:52px;border:1px solid var(--line);border-radius:14px;padding:22px 22px 18px;margin:0 0 24px;background:#fff}
.prophead{display:grid;grid-template-columns:44px 1fr auto;column-gap:14px;row-gap:8px;align-items:center}
.prophead h3{margin:0;font-size:20px}
.thesis{grid-column:2 / -1;color:var(--dim);margin:0;max-width:62em}
.meanbadge{font-size:26px;font-weight:700;line-height:1;text-align:right;color:var(--accent)}
.meanbadge small{display:block;font-size:11px;font-weight:500;color:var(--dim2);margin-top:3px}
.gatebad{font-size:11px;font-weight:700;color:var(--bad);border:1px solid var(--bad);border-radius:5px;padding:1px 6px;margin-left:8px;vertical-align:.15em}
.prose{font-size:14px}
.prose p{margin:0 0 8px}
.prose ul,.prose ol{margin:0 0 10px;padding-left:20px}
.prose li{margin:0 0 5px}
ul.decs{margin:0;padding-left:18px;font-size:13.5px}
ul.decs li{margin:0 0 6px}
ul.decs li span{color:var(--dim)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:28px}
.extras{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
details.limits{margin-top:16px;border-top:1px solid var(--line);padding-top:10px;font-size:13.5px}
summary{cursor:pointer;color:var(--dim);font-weight:600;font-size:13px}
summary:hover{color:var(--fg)}
details.limits ul,details.limits ol{padding-left:18px}
@media(max-width:980px){.extras{grid-template-columns:1fr 1fr}}
@media(max-width:820px){.two{grid-template-columns:1fr;gap:0}.thesis{grid-column:1 / -1}.prop{padding:16px 14px}.extras{grid-template-columns:1fr}}

/* prior art */
.sauna{border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:12px;padding:6px 22px 14px;background:var(--panel);margin-bottom:8px}
.sauna header{padding-top:12px}
.tag{display:inline-block;font-size:11px;text-transform:uppercase;letter-spacing:.09em;font-weight:700;color:var(--accent);margin-bottom:4px}
.sauna .prose{max-width:62em}
h3.sect{margin:34px 0 10px}
ol.principles{margin:0;padding-left:22px;font-size:14px;max-width:62em}
ol.principles li{margin:0 0 10px}
ol.principles span{color:var(--dim)}
.pas{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.pa{border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.pa h3{font-size:15px}
.pa p{font-size:13.5px;color:var(--dim)}
.pa p.steal{color:var(--fg)}
ul.srcs{margin:6px 0 0;padding-left:18px;font-size:12px;overflow-wrap:anywhere}
@media(max-width:820px){.pas{grid-template-columns:1fr}}

/* judges */
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table.scores{border-collapse:collapse;width:100%;min-width:820px;font-size:13px}
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
.scoreboard{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}
.sb{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.sb b{display:block;font-size:13px}
.sbn{display:block;font-size:26px;font-weight:700;color:var(--accent);line-height:1.15}
.sbn small{font-size:12px;color:var(--dim2);font-weight:500}
@media(max-width:980px){.scoreboard{grid-template-columns:repeat(3,1fr)}}
@media(max-width:560px){.scoreboard{grid-template-columns:1fr}}

/* decision surface */
.decide{border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:12px;padding:6px 22px 14px;background:var(--panel)}
.decide ul,.decide ol{margin:4px 0 8px;padding-left:20px}
.decide>ul>li{margin:12px 0}
.decide li ul{margin-top:4px}
footer.end{margin-top:40px;color:var(--dim2);font-size:12px}

/* wave 2: N6 + shared fixes */
.prop.n6{border-color:var(--line2)}
.deftag{font-size:11px;font-weight:700;color:var(--accent);border:1px solid var(--accent);border-radius:5px;padding:1px 6px;margin-left:8px;vertical-align:.15em}
.hero6{margin:18px 0 0}
.hero6 video,.hero6 img{width:100%;max-width:1100px;display:block;border:1px solid var(--line2);border-radius:10px;background:#111;aspect-ratio:1280/800}
.stills{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.stills.two-up{grid-template-columns:1fr 1fr;margin-top:16px}
.stills.one-up{grid-template-columns:minmax(0,820px)}
.zoom.nocrop{aspect-ratio:auto}
.zoom.nocrop img{width:100%;margin:0}
.jverdict{font-size:14px;max-width:62em}
.off{display:block;font-size:10.5px;font-weight:500;color:var(--warn)}
ol.wrong{margin:0;padding-left:20px;font-size:14px;max-width:66em}
ol.wrong li{margin:0 0 8px} ol.wrong span{color:var(--dim)}
.fix{border:1px solid var(--line);border-radius:14px;padding:18px 22px 12px;margin:0 0 20px}
.fix h3{font-size:17px}
.okt{font-size:11px;font-weight:700;color:var(--ok);border:1px solid var(--ok);border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:.15em}
.partt,.opent{font-size:11px;font-weight:700;border:1px solid;border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:.15em}
.partt{color:var(--warn)} .opent{color:var(--bad)}
p.stillopen{font-size:13.5px;max-width:66em;margin:-8px 0 14px;padding-left:12px;border-left:2px solid var(--warn)}
td.r1{color:var(--dim)} td.r1 small{display:block;font-size:10.5px;color:var(--dim2)}
ol.changed span{color:var(--dim)}
p.r3{font-size:14px;max-width:66em;margin:0 0 12px}
p.was{font-size:13px;color:var(--dim);max-width:66em}
.rtag{font-size:11px;font-weight:600;color:var(--dim);border:1px solid var(--line2);border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:.15em}
ol.wrong .r3line{display:block;color:var(--fg);font-size:13px;margin-top:2px}
ol.wrong .okt,ol.wrong .opent{margin:0 4px 0 0}
table.counts{border-collapse:collapse;width:100%;min-width:760px;font-size:13px}
table.counts th,table.counts td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
table.counts thead th{font-size:11.5px;color:var(--dim);background:var(--panel)}
table.counts td.was{color:var(--dim2)}
ul.open{margin:0;padding-left:20px;font-size:13.5px;max-width:66em} ul.open li{margin:0 0 6px}
.small{font-size:13px} .dim{color:var(--dim)}
@media(max-width:980px){.stills{grid-template-columns:1fr 1fr}}
@media(max-width:820px){.stills,.stills.two-up{grid-template-columns:1fr}.fix{padding:14px}}
/* audit: one row per Codex finding; colour only for the one high finding and a failure */
.ahead,.arow{display:grid;grid-template-columns:2.2em 5.5em minmax(0,1fr) 8.5em;column-gap:14px;align-items:baseline}
.ahead{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim2);font-weight:700;padding:0 0 6px;border-bottom:1px solid var(--line2);max-width:1080px}
ol.audit{list-style:none;margin:0 0 18px;padding:0;max-width:1080px}
.arow{padding:12px 0;border-bottom:1px solid var(--line)}
.an{color:var(--dim2);font-variant-numeric:tabular-nums}
.asev{font-size:13px;color:var(--dim)} .asev.hi{color:var(--bad);font-weight:700}
.abody{min-width:0} .abody b{font-size:14.5px} .abody p{margin:3px 0 4px;font-size:13.5px;color:var(--dim)}
.abody details summary{font-weight:500;font-size:12.5px}
p.averb{font-size:13px;color:var(--fg);white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0}
.afix{font-size:13px;color:var(--dim)} .afix.no{color:var(--bad);font-weight:700}
@media(max-width:700px){.ahead{display:none}.arow{grid-template-columns:2.2em minmax(0,1fr);row-gap:2px}
  .asev{grid-column:2}.abody{grid-column:1 / -1}.afix{grid-column:1 / -1}}
p.asib{font-size:13px;color:var(--fg);margin:2px 0 4px;padding-left:10px;border-left:2px solid var(--line2)}
/* round 2's re-read of round 1: one quiet line per finding; 'partly' is bold, not coloured, since each is now completed */
ol.r1s{list-style:none;margin:0 0 18px;padding:0;max-width:1080px}
.r1row{display:grid;grid-template-columns:2.2em 5.5em minmax(0,1fr) 12em;column-gap:14px;align-items:baseline;padding:6px 0;
  border-bottom:1px solid var(--line);font-size:13px}
.r1w{color:var(--dim)} .r1w.partly{color:var(--fg);font-weight:700} .r1note{color:var(--dim);min-width:0;overflow-wrap:anywhere}
.r1now{color:var(--fg)}
.r1row.r3{grid-template-columns:3.4em 5.5em minmax(0,1fr) 12em} .afix small{font-weight:400;color:var(--dim2)}
@media(max-width:700px){.r1row.r3{grid-template-columns:3.4em minmax(0,1fr)}}
@media(max-width:700px){.r1row{grid-template-columns:2.2em minmax(0,1fr);row-gap:2px}.r1note,.r1now{grid-column:1 / -1}}
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

DECISION = """
<ul>
  <li><strong>Done and proved:</strong> five working Needs-you pages on the real loop data (kinsim 3 asks, rig 6, all tracks 9). Each was driven headless from entry to a copied answer, with 0 console errors from the pages and the project typecheck clean (the one error seen during building was a peer's unused variable). Two independent judges then drove all five again, hit-testing the first click, timing three answers plus the copy, and forcing the clipboard to refuse. Four of five passed every gate. N3 failed one on truthful counts.</li>
  <li><strong>Left:</strong>
    <ul>
      <li>build the splice below (blocked only on your pick);</li>
      <li>the shared fixes in the seam: the home count and the page it opens must agree, Back from a needs page must return home, and the chooser must not cover answer controls;</li>
      <li>a Codex audit of whatever ships (none is part of this report; the two judges are the only independent check).</li>
    </ul></li>
  <li><strong>Needs you:</strong>
    <ol>
      <li><strong>Pick N1, N2, or the splice.</strong> Recommendation: the splice, N1's Zen lane as the shell with N2's Blocks / If you stay silent / When / Opened table and the full verbatim context printed on every card, so nothing needs a key to open. Default if you say nothing: no further build.</li>
      <li><strong>Fix the shared seam either way?</strong> The home Needs-you cell lands on a number that contradicts the one you clicked (rig 4 blocking → 2 on the page; grasping 7 blocking → an empty page). Recommendation: yes, in the same change. Default if you say nothing: not built.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> nothing sends. Every page only collects a draft and copies it, because the backend is read-only and the loops read their own channels. No commits and no pushes; the five builds are untracked files in the lane. Sauna's per-keystroke send was not copied.</li>
</ul>
"""

JS = r"""
<script>
(function(){
  // launcher copy button: the clipboard API is often refused on file:/data: origins, so fall back to selection
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
    lbCap.textContent = lab ? lab.textContent.trim() + (txt ? ' — ' + txt.textContent.trim() : '') : img.alt;
    lb.classList.add('open'); lb.querySelector('button').focus();
  }
  function closeLb(){ lb.classList.remove('open'); lbImg.removeAttribute('src'); }
  Array.prototype.forEach.call(document.querySelectorAll('.zoom'), function(z){
    z.addEventListener('click', function(){ openLb(z.querySelector('img')); });
  });
  lb.addEventListener('click', function(e){ if (e.target !== lbCap) closeLb(); });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape' && lb.classList.contains('open')) closeLb(); });

  // five autoplaying videos at once is heavy: run only the ones on screen
  // WHY the GIF only on error: it is the fallback for a viewer that cannot play H.264, not a second hero.
  var v6 = document.querySelector('.hero6 video'), g6 = document.getElementById('hero6-gif');
  function toGif6(){ v6.classList.add('hidden'); g6.classList.remove('hidden'); }
  if (v6){ var s6 = v6.querySelector('source'); if (s6) s6.addEventListener('error', toGif6);
    if (!v6.canPlayType('video/mp4')) toGif6(); }
  var vids = document.querySelectorAll('.vid video, .hero6 video');
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
        "var out = ['Re: Vibe Tracks Needs-you proposals N1-N5 (2026-10-04)', '', '<sub>' + REPORT + '</sub>', ''];",
    )

    if N6_LEADS:
        verdict = (
            f"Codex round 3 ({AUDIT3['auditor']}, on a frozen snapshot of {AUDIT3['audited_sha']}) returned FAIL with "
            f"{len(AUDIT3_ROWS)} new findings; all {AUDIT3_PASS} are fixed and re-measured, {_nums(AUDIT3_WHERE['e0bd8e5'])} in "
            f"e0bd8e5 and {_nums(AUDIT3_WHERE['this wave'])} in this wave (uncommitted). On this page every evidence link now "
            f"opens only the file the Needs document recorded, never a newer one through /media, and grasping's verdict and "
            f"rows come from the same ledger bytes. Variant A is the only dashboard (B and C retired) and N6 is the default "
            f"({MEAN2['N6']:.0f} vs N1's {MEAN2['N1']:.0f}). Codex round 4 runs next; nothing here is Codex-approved yet."
        )
        h1 = "Vibe Tracks Needs-you: Codex round 3's findings are fixed, round 4 next"
    else:
        verdict = (
            f"N6 · {D.N6['name']} still scores below N1: {MEAN2['N6']:.0f} against {MEAN2['N1']:.0f} (N2 "
            f"{MEAN2['N2']:.0f}). Make N1 the default page and keep N6 selectable."
        )
        h1 = "Vibe Tracks Needs-you: N1 becomes the default"
    mean_line = " · ".join(f"{n} {MEAN[n]:.1f}" for n in ORDER)
    # WHY an assert, not a text swap: DECISION_R2's first ask and its default ("N6 stays the default") are written for
    # N6 leading. If a re-judge flips the order, the brief's rule applies (make N1 the default page, keep N6
    # selectable) and the ask, the recommendation and the numbers in it all need rewriting, not one phrase.
    assert N6_LEADS, "N6 trails N1: rewrite DECISION_R2's first ask to 'make N1 the default page and keep N6 selectable'"
    decision = DECISION_R7
    # WHY round 3 leads and the older rounds fold under it: this round is what Codex round 4 will read; round 6 (the tree
    # Codex round 3 audited) and round 2 are the record of how the tree got here, one click deeper (calm first screen).
    audit = (audit3_html()
             + f'<details class="limits"><summary>Round 6: verify-6\'s leftovers, the tree Codex round 3 audited ({R6_TREE})</summary>'
             + round6_html() + '<details class="limits"><summary>Codex round 2: its findings on b53567e, their fixes and '
             "verify-6's evidence</summary>" + audit2_html(AUDIT2_STILLS, AUDIT_STILLS) + "</details></details>")
    # grid first, so GRID_USED is known when the details pick their extra stills; the page below places them in order.
    videos = videos_html()
    grid = grid_html()
    props = "".join(proposal_html(n) for n in ORDER)
    prior = prior_art_html()
    judges = judges_html()
    n6 = n6_html()
    shared = shared_html()

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vibe Tracks Needs-you</title>
<style>{CSS}{FB.CSS}{FB_LIGHT}</style></head>
<body><div class="wrap">

<header class="top">
  <div class="date">2026-10-05 · Codex round 3's findings fixed and re-measured, before Codex round 4</div>
  <h1>{esc(h1)}</h1>
  <p class="verdict">{esc(verdict)}</p>
  <p class="built">Built on the live lane at 127.0.0.1:4390 against the real /needs data · answers only ever copy out, nothing is sent · branch claude/vibetracks-dashboard at e0bd8e5 (Codex round 3's findings 3 and 4, committed) plus this wave's fixes for 1, 2 and 5, uncommitted · variant A only (B and C retired in 56c75c0); N6 is the default Needs page, N1–N5 selectable · N1–N5 scored by two judges in the first wave; N6 vs N1 vs N2 re-judged in round 2 (not since) · Codex round 1 audited 3e90b94 (FAIL, 13 findings), round 2 audited b53567e (FAIL, 3 partly + 7 new; fixed in d579e39), round 3 audited 56c75c0 (FAIL, 3 partly + 5 new; fixed in e0bd8e5 and this wave) · verify-9 re-measured this wave (308 pytest, tsc clean, 8 of 8 browser checks) · Codex round 4 next · browser-only (over the desktop preview's size cap).</p>
  <div class="launch"><pre id="launch-cmd">{esc(LAUNCHER)}</pre><button id="copy-launch" type="button">Copy</button></div>
  <div class="reach">
    <h4>How to reach it</h4>
    <ol>
      <li>Run the launcher above. It starts or reuses this checkout's lane and opens the dashboard.</li>
      <li>Click a <strong>Needs you</strong> cell on home or a track page (one click lands on card 1 of N6), or paste <code>#vt?track=kinsim&amp;needs=1</code> after the dashboard URL (<code>{esc(DASH_URL)}</code>). <code>track=rig</code> gives the six rig asks, and no track gives all nine.</li>
      <li>N6 opens unless you picked another. The pill at the bottom right ("Needs you N6 · Lane + context ▾") is the only one left now that the A · B · C layout pill is retired; it switches between N1–N6 and remembers the pick.</li>
    </ol>
  </div>
</header>

<nav class="toc" aria-label="Sections">
  <a href="#audit">This round</a><a href="#n6">N6</a><a href="#shared">Shared fixes</a><a href="#decide">Decide</a>
  <a href="#watch">N1–N5 videos</a><a href="#compare">Compare</a><a href="#proposals">Proposals</a>
  <a href="#prior">Prior art</a><a href="#judges">Judges</a>
</nav>

<section id="audit">
  <h2>This round, and the independent audit</h2>
  {audit}
</section>

<section id="n6">
  <h2>N6 · Lane + context{", the default" if N6_LEADS else ""}</h2>
  <p class="lead">The splice both first-wave judges named, rebuilt against round 1's list, judged against N1 and N2 in round 2, then fixed against round 2's list in round 3 (no re-judge yet).</p>
  {n6}
</section>

<section id="shared">
  <h2>Shared fixes</h2>
  <p class="lead">The seams every proposal shares: the kit, the shell and the backend. The cards round 3 changed come first, each with how verify-4 measured it; round 2's text for that seam folds away under it.</p>
  {shared}
</section>

<section id="decide">
  <h2>Decision</h2>
  <p class="lead">After Codex round 3's findings were fixed and re-measured, before Codex round 4. The first-wave sections for N1–N5 follow it.</p>
  <div class="decide">{decision}</div>
  <details class="limits"><summary>Round 6's decision packet, before Codex round 3 (superseded: round 3 ran, and its open items closed in e0bd8e5)</summary>{DECISION_R6}</details>
  <details class="limits"><summary>Round 5's decision packet, after Codex round 2 (superseded: its siblings and 390 px pages are closed)</summary>{DECISION_R5}</details>
  <details class="limits"><summary>Round 4's decision packet, after Codex round 1 (superseded)</summary>{DECISION_R4}</details>
  <details class="limits"><summary>Round 3's decision packet (superseded: its two 'Left' failures are fixed)</summary>{D.DECISION_R3}</details>
  <details class="limits"><summary>Round 2's decision packet (superseded)</summary>{D.DECISION_R2}</details>
  <details class="limits"><summary>Round 1's decision packet (superseded)</summary>{D.DECISION_N6}</details>
  <details class="limits"><summary>The first wave's decision packet (superseded)</summary>{DECISION}</details>
  {FB.ui(REPORT_NAME, noun="proposal", total=10)}
</section>

<h2 class="wave1">The first wave: N1–N5 <small>(unchanged; heroes re-encoded at 960 wide to keep the page small; the 'Review them too' control these cards describe is now a Settings option)</small></h2>

<section id="watch">
  <h2>N1–N5: watch first</h2>
  <p class="lead">One recorded run through each page on the real data, 13 to 20 seconds each, muted and looping. All five start on kinsim's blocking T47 and end on a copied answer block.</p>
  {videos}
</section>

<section id="compare">
  <h2>The same moment in each proposal</h2>
  <p class="lead">Rows are the same step in all five. Click a screenshot for the full window with its caption, Esc closes it; the rest of each proposal's captures sit in its card below. Screenshots are cropped to the page (Clank's file sidebar is trimmed). Note that the temporary chooser sits at the bottom right of every capture.</p>
  {grid}
</section>

<section id="proposals">
  <h2>Each proposal in detail</h2>
  <p class="lead">In judge order ({esc(mean_line)}). Mark each one at the bottom of its card; the dock at the lower right copies your notes out as markdown.</p>
  {props}
</section>

<section id="prior">
  <h2>Prior art</h2>
  <p class="lead">Sauna's Zen Mode first, since it is what you pointed at. Everything below it is what the proposals were briefed to take, and the one thing not to copy.</p>
  {prior}
</section>

<section id="judges">
  <h2>The judges</h2>
  <p class="lead">Two independent judges drove all five pages and scored them on five criteria (the names are read from what each judge's evidence is about). The weighted score is Σ weight × score / 5 per judge (weights 25 / 25 / 20 / 20 / 10), then averaged. Open a row's evidence to see what each judge actually did.</p>
  {judges}
</section>



<footer class="end">Generated by docs/dashboard/build_needs_report.py from {esc(str(DATA))} and the 2026-10-04 captures.</footer>
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
    n_stills = sum(len(D.BUILDERS[n]["stills"]) for n in NS)
    # every still in the data must be used exactly once (grid or extras): an unused capture is a report bug
    assert len([p for p in _inlined if p.endswith(".webp") and "/r2-small/" not in p]) == n_stills, "a still was not inlined"
    gifs = [p for p in _inlined if p.endswith(".gif")]
    assert len(gifs) == 1, f"one GIF at most (the N6 hero's fallback): {gifs}"
    assert size < 9_000_000, f"page is {size/1e6:.2f} MB, over the 9 MB target"
    print(f"wrote {OUT}  {size:,} bytes ({size/1e6:.2f} MB), {len(_inlined)} media inlined once each")
    print("means:", {n: round(MEAN[n], 1) for n in NS})
    print("round 1:", {n: round(MEAN_R1[n], 1) for n in W2}, "round 2:", {n: round(MEAN2[n], 1) for n in W2},
          "stated totals that do not reproduce:", STATED_OFF)
