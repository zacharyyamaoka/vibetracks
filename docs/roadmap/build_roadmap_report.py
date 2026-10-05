#!/usr/bin/env python3
"""Build the review report for the roadmap widget inside the Vibe Tracks dashboard.

    python3 /home/bam/vibetracks-roadmap/docs/roadmap/build_roadmap_report.py

Writes ONE self-contained file:
    /home/bam/vibetracks/reports/media/vibetracks-roadmap-2026-10-04.html

Inputs (all in MEDIA, written by docs/roadmap/record_roadmap_widget.py against the running lane; none hand-typed here):
    hero.json               every hero step's clip offset and measured predicate, every still's predicate
    hero.mp4 / hero.gif     the hero clip (H.264, muted) and its GIF fallback
    stills/*.webp           the captures
The audit trail reads the Codex round files in AUDITS and this checkout's git log (which commit names which finding).

WHY the numbers come from hero.json: a hand-typed number in a report outlives the data it describes; a re-record
refreshes the report. WHY every capture is inlined exactly once: Zach reviews by reading, from any device; the lightbox
re-uses the clicked <img>'s src instead of a second copy. The page is past the desktop preview's 2,097,024-byte data:
URL ceiling (the build prints the measured size), so it is browser-only and lives in the gitignored reports/media/ half.
WHY sections with fixed ids (audit-round-3, decisions): the orchestrator fills them after this build, by id.
"""
from __future__ import annotations

import base64
import html
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

MEDIA = Path("/home/bam/vibetracks/reports/media/vibetracks-roadmap-2026-10-04")
OUT = Path("/home/bam/vibetracks/reports/media/vibetracks-roadmap-2026-10-04.html")
REPO = Path("/home/bam/vibetracks-roadmap")
AUDITS = Path("/home/bam/bam_ws/reports/media/audits")
LANE_URL = "http://127.0.0.1:4400/?vtdash=Agent%20work.vtdash"
RECORD_CMD = ("cd ~/vibetracks-roadmap && uv run --no-project --with playwright==1.55.0 python3 docs/roadmap/record_roadmap_widget.py "
              f"--url http://127.0.0.1:4400/ --out {MEDIA}")
# The desktop preview builds `data:text/html,` + encodeURIComponent(html) and refuses a URL longer than this.
PREVIEW_CAP = 2_097_024

HERO = json.loads((MEDIA / "hero.json").read_text())
assert HERO["passed"], f"the recording did not pass: {HERO['failed']} {HERO['page_errors']}"
STILLS = {s["name"]: s for s in HERO["stills"]}
TRACKS = ["kinsim", "rig", "grasping", "detection"]
TRACK_TITLE = {"kinsim": "Kinematic Sim", "rig": "Sim to Real & Trajectory Tracking", "grasping": "Grasping", "detection": "Object Detection & Hyperspectral"}

# ---- media -----------------------------------------------------------------------------------------------------
_inlined: set[str] = set()


def data_uri(path: Path, mime: str) -> str:
    key = str(path)
    assert key not in _inlined, f"would inline twice: {path}"
    _inlined.add(key)
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def inline_md(s: str) -> str:
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def fig(name: str, label: str, cap: str, cls: str = "") -> str:
    """A still with a two-tier caption: bold label (what it is), then the dim line (what to notice)."""
    path = MEDIA / "stills" / f"{name}.webp"
    return (
        f'<figure class="cell {cls}"><button class="zoom" type="button" aria-label="Open {esc(label)} full size">'
        f'<img alt="{esc(label)}" src="{data_uri(path, "image/webp")}"></button>'
        f'<figcaption><b>{inline_md(label)}</b><span class="cap">{inline_md(cap)}</span></figcaption></figure>'
    )


# ---- what each step measured, in words ---------------------------------------------------------------------------
def step_note(label: str, m: dict) -> str:
    """The measured predicate as a line a reader can check against the clip; unknown labels fall back to the raw JSON."""
    if label == "Tracks page":
        return "rows in order: " + ", ".join(m["rows"])
    if label == "Open kinsim's track page":
        return f"track page for `{m['page']}`, route `#vt?track={m['route']['track']}`"
    if label == "Roadmap calm head":
        return (f"“{m['sentence']}” · `{m['asOf']}` = generated_at {m['generatedAt']} · {m['shownProven']} of {m['shownTotal']} "
                f"proven = the live document's {m['docProven']} green/done of {m['docTotal']} rungs · {m['shownClaimed']} claimed = "
                f"{m['docClaimed']} · in view: {m['inView']}")
    if label == "Expand: the full lens board":
        return f"{m['rungs']} of {m['docTotal']} rungs drawn · `rmopen={m['route']['rmopen']}` · lens {m['lens']}"
    if label == "Depth lens: the same cards glide":
        return f"lens {m['lens']} (`rm.lens={m['route']['rm'].get('lens')}`) · {m['moved']} cards changed position"
    if label == "Arrow keys walk the robots lane":
        return (f"→ → → selected {' → '.join(m['sels'])} (lanes: {', '.join(sorted(set(m['axis'].values())))}) · "
                f"keyboard focus on {m['focused']}")
    if label == "Click RB0: the focus card with its proof":
        return (f"trail `{m['trail']}` · verdict {m['verdict']} · {m['runs']} named runs, first `{m['firstRun']}`")
    if label == "A named run opens its own record":
        return f"file page shows `{m['shownPath']}` = the clicked run's own path · allowlisted: {m['allowlisted']}"
    if label == "History back restores the focus card":
        return (f"trail `{m['trail']}` · lens {m['lens']} · `rmopen={m['route']['rmopen']}` · proof tab shown · card in view "
                f"without scrolling: {m['inViewAfterBack']} · keyboard focus: {m['focused'] or 'none'}")
    if label == "Back to the tracks":
        return "tracks page (L1) again, route `#vt`"
    if label == "Pyblocks: No roadmap reported yet":
        return f"“{m['none']}” · loading line gone: {not m['loading']} · no calm head: {not m['calm']}"
    return "`" + json.dumps(m)[:300] + "`"


def steps_list() -> str:
    rows = []
    for s in HERO["steps"]:
        mark = '<span class="okt">PASS</span>' if s["ok"] else '<span class="badt">FAIL</span>'
        rows.append(f'<li><span class="t">{s["clip_t_s"]:.1f}s</span><div><b>{esc(s["label"])}</b> {mark}'
                    f'<span class="dim blk small">{inline_md(step_note(s["label"], s["measured"]))}</span></div></li>')
    return '<ol class="steps">' + "".join(rows) + "</ol>"


# ---- the audit trail ----------------------------------------------------------------------------------------------
FINDING = re.compile(r"^\*\*([VW]\d\d) — (\w+) — ([\w_]+)\*\* — (.*)$")


def findings(path: Path) -> tuple[list[dict], str]:
    """Each finding's id, severity and headline (its first sentence after the file links), and the round's verdict."""
    out, verdict = [], ""
    for line in path.read_text().splitlines():
        match = FINDING.match(line)
        if match:
            fid, severity, domain, rest = match.groups()
            text = re.sub(r"\[[^\]]+\]\([^)]+\)(, )?", "", rest).lstrip(" —").strip()
            out.append({"id": fid, "severity": severity, "domain": domain, "headline": re.split(r"(?<=\.)\s", text, maxsplit=1)[0]})
        elif line.startswith("**VERDICT"):
            verdict = line.strip("*").replace("VERDICT: ", "")
    return out, verdict


def fixed_in() -> dict[str, list[str]]:
    """Finding id → the commits whose subject names it ("Codex V04 V05", or a range "V06-V10")."""
    log = subprocess.run(["git", "-C", str(REPO), "log", "--format=%h\t%s", "-60"], capture_output=True, text=True, check=True).stdout
    found: dict[str, list[str]] = {}
    for line in log.splitlines():
        sha, subject = line.split("\t", 1)
        codex = re.search(r"\(Codex ([^)]*)\)", subject)
        if not codex:
            continue
        for token in re.findall(r"[VW]\d\d(?:-[VW]\d\d)?", codex.group(1)):
            if "-" in token:
                lo, hi = token.split("-")
                ids = [f"{lo[0]}{n:02d}" for n in range(int(lo[1:]), int(hi[1:]) + 1)]
            else:
                ids = [token]
            for fid in ids:
                found.setdefault(fid, []).append(sha)
    return found


# A fix whose commit subject names no finding: the commit, and why it counts. WHY by hand and said so in the table: V03
# (grasping and detection 404 in the dashboard's workspace) was fixed in the Dashboard lane's registry notes, not here.
UNNAMED_FIXES = {
    "V03": ("2abc184", "Dashboard lane's registry commit (its notes now name both projectors); names no finding. "
                       "This recording's calm heads read /doc for grasping and detection live."),
}


def fix_cell(fid: str, commits: dict[str, list[str]]) -> str:
    if fid in commits:
        return " ".join(f"<code>{esc(c)}</code>" for c in commits[fid])
    if fid in UNNAMED_FIXES:
        sha, why = UNNAMED_FIXES[fid]
        return f'<code>{esc(sha)}</code><span class="dim blk small">{esc(why)}</span>'
    return '<span class="badt">none</span>'


def audit_round(n: int, prefix: str, commits: dict[str, list[str]]) -> str:
    path = AUDITS / f"2026-10-04-vibetracks-roadmap-r{n}.md"
    items, verdict = findings(path)
    rows = "".join(
        f'<tr><th scope="row">{esc(f["id"])}</th><td>{esc(f["severity"])}</td><td>{inline_md(f["headline"])}</td>'
        f'<td class="fix">{fix_cell(f["id"], commits)}</td></tr>'
        for f in items
    )
    unfixed = [f["id"] for f in items if f["id"] not in commits and f["id"] not in UNNAMED_FIXES]
    by_hand = [f["id"] for f in items if f["id"] not in commits and f["id"] in UNNAMED_FIXES]
    state = ("every finding has a fix commit" if not unfixed else f"no fix commit for {', '.join(unfixed)}") + (
        f" ({', '.join(by_hand)} by a commit that does not name it; see its row)" if by_hand else "")
    return (f'<h3>Round {n}: {esc(verdict)} → fixed</h3>'
            f'<p class="small dim">{len(items)} findings ({prefix}01–{prefix}{len(items):02d}); {state}. '
            f'Audit file: <code class="path">{esc(path)}</code></p>'
            f'<div class="tablewrap"><table class="grid"><thead><tr><th>id</th><th>severity</th><th>finding</th><th>fixed in</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


CSS = r"""
:root{
  --bg:#fff; --fg:#1b1d21; --dim:#5d6470; --dim2:#8a919c; --line:#e6e8ec; --line2:#d3d7de; --panel:#f7f8fa; --btn:#fff;
  --accent:#2563eb; --ok:#2f7d4f; --warn:#b4540a; --bad:#b42318; --toc:rgba(255,255,255,.94);
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#15171b; --fg:#e7e9ee; --dim:#a3aab5; --dim2:#7d8590; --line:#2a2e35; --line2:#3a3f48; --panel:#1d2026; --btn:#23262d;
    --accent:#6b9bff; --ok:#5cc28a; --warn:#e3a050; --bad:#ff7b72; --toc:rgba(21,23,27,.94);
  }
}
:root[data-theme="dark"]{
  --bg:#15171b; --fg:#e7e9ee; --dim:#a3aab5; --dim2:#7d8590; --line:#2a2e35; --line2:#3a3f48; --panel:#1d2026; --btn:#23262d;
  --accent:#6b9bff; --ok:#5cc28a; --warn:#e3a050; --bad:#ff7b72; --toc:rgba(21,23,27,.94);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 var(--sans);-webkit-text-size-adjust:100%;overflow-wrap:anywhere}
.wrap{max-width:1240px;margin:0 auto;padding:0 16px 120px}
h1{font-size:32px;line-height:1.15;margin:0 0 12px;letter-spacing:-.02em}
h2{font-size:22px;margin:0 0 6px;letter-spacing:-.01em}
h3{font-size:16px;margin:22px 0 6px}
p{margin:0 0 10px}
code{font:12.5px var(--mono);background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:0 4px;word-break:break-word}
code.path{display:inline;word-break:break-all}
.hidden{display:none !important}
.dim{color:var(--dim)} .small{font-size:13px} .blk{display:block}
.okt{color:var(--ok);font-weight:700;font-size:11.5px;letter-spacing:.04em} .badt{color:var(--bad);font-weight:700}
header.top{padding:40px 0 18px}
.date{color:var(--dim2);font-size:13px;margin-bottom:8px}
.verdict{font-size:18px;line-height:1.45;font-weight:700;margin:0 0 8px;max-width:62em}
.qual{font-size:15px;margin:0 0 10px;max-width:62em}
.built{color:var(--dim);font-size:13.5px;margin:0 0 16px;max-width:62em}
.launch{display:flex;align-items:stretch;max-width:760px;border:1px solid var(--line2);border-radius:9px;overflow:hidden;background:var(--panel);margin-bottom:8px}
.launch pre{margin:0;padding:10px 14px;font:13px/1.4 var(--mono);overflow-x:auto;flex:1;min-width:0;white-space:pre}
.launch button{border:0;border-left:1px solid var(--line2);background:var(--btn);font:600 13px var(--sans);padding:0 16px;cursor:pointer;color:var(--fg)}
.launch button.done{color:var(--ok)}
nav.toc{position:sticky;top:0;z-index:20;background:var(--toc);backdrop-filter:blur(6px);border-bottom:1px solid var(--line);
  display:flex;gap:4px;overflow-x:auto;padding:8px 16px;margin:0 -16px;scrollbar-width:none}
nav.toc a{color:var(--dim);text-decoration:none;font-size:13px;padding:5px 11px;border-radius:7px;white-space:nowrap}
nav.toc a:hover{background:var(--panel);color:var(--fg)}
section{padding-top:44px;scroll-margin-top:44px}
.lead{color:var(--dim);margin:0 0 18px;max-width:62em}
.hero{margin:0}
.hero video,.hero img.gif{width:100%;max-width:1100px;height:auto;display:block;border:1px solid var(--line2);border-radius:10px;background:#111;aspect-ratio:1400/900}
figcaption{margin-top:8px;font-size:13px;max-width:1100px}
figcaption b{display:block;font-size:13.5px}
.cap{display:block;color:var(--dim);font-size:12.5px;line-height:1.5;margin-top:2px}
.g1{display:grid;grid-template-columns:1fr;gap:22px;max-width:1100px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.phone{display:grid;grid-template-columns:minmax(0,300px) 1fr;gap:24px;align-items:start}
.cell{margin:0;min-width:0}
.zoom{all:unset;display:block;width:100%;cursor:zoom-in;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--panel);line-height:0}
.zoom:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.zoom img{width:100%;height:auto;display:block}
.zoom:hover{border-color:var(--accent)}
@media(max-width:820px){.g2,.phone{grid-template-columns:1fr}}
#lb{position:fixed;inset:0;z-index:100;background:rgba(10,12,16,.88);display:none;flex-direction:column;align-items:center;justify-content:center;padding:20px;gap:12px}
#lb.open{display:flex}
#lb img{max-width:100%;max-height:calc(100vh - 120px);object-fit:contain;border-radius:6px;background:#fff;cursor:zoom-out}
#lb .lbcap{color:#e8eaee;font-size:13px;max-width:900px;text-align:center}
#lb button{position:fixed;top:12px;right:14px;border:1px solid #ffffff55;background:#00000066;color:#fff;border-radius:8px;font:600 13px var(--sans);padding:7px 12px;cursor:pointer}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;max-width:100%}
table.grid{border-collapse:collapse;width:100%;min-width:640px;font-size:13px}
table.grid th,table.grid td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
table.grid thead th{font-size:11.5px;color:var(--dim);font-weight:700;background:var(--panel)}
table.grid tbody th{font-weight:700;white-space:nowrap}
.num{white-space:nowrap} td.fix{min-width:90px;max-width:260px}
.steps{list-style:none;margin:18px 0 0;padding:0;max-width:66em}
.steps li{display:grid;grid-template-columns:52px 1fr;gap:10px;padding:9px 0;border-top:1px solid var(--line);font-size:14px}
.steps .t{font:12.5px var(--mono);color:var(--dim2);padding-top:2px}
ul.plain{margin:0;padding-left:20px;max-width:66em} ul.plain li{margin:0 0 10px;font-size:14px}
.issues{margin:0;padding-left:20px;max-width:66em} .issues li{margin:0 0 12px;font-size:14px} .issues b{display:block}
.placeholder{border:1px dashed var(--line2);border-radius:12px;padding:14px 18px;color:var(--dim);background:var(--panel)}
footer.end{margin-top:40px;color:var(--dim2);font-size:12px}
"""

JS = r"""
<script>
(function(){
  var btn = document.getElementById('copy-launch'), pre = document.getElementById('launch-cmd');
  btn.addEventListener('click', function(){
    var text = pre.textContent.trim(), ok = function(){ btn.textContent = 'Copied'; btn.classList.add('done');
      setTimeout(function(){ btn.textContent = 'Copy'; btn.classList.remove('done'); }, 1600); };
    function fallback(){
      var r = document.createRange(); r.selectNodeContents(pre);
      var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      try { if (document.execCommand('copy')) ok(); else btn.textContent = 'Press Ctrl-C'; } catch(e){ btn.textContent = 'Press Ctrl-C'; }
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(ok, fallback); else fallback();
  });
  var lb = document.getElementById('lb'), lbImg = lb.querySelector('img'), lbCap = lb.querySelector('.lbcap');
  function openLb(img){
    lbImg.src = img.src; lbImg.alt = img.alt;
    var cap = img.closest('figure') && img.closest('figure').querySelector('figcaption');
    lbCap.textContent = cap ? cap.textContent.trim() : img.alt;
    lb.classList.add('open'); lb.querySelector('button').focus();
  }
  function closeLb(){ lb.classList.remove('open'); lbImg.removeAttribute('src'); }
  Array.prototype.forEach.call(document.querySelectorAll('.zoom'), function(z){ z.addEventListener('click', function(){ openLb(z.querySelector('img')); }); });
  lb.addEventListener('click', function(e){ if (e.target !== lbCap) closeLb(); });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape' && lb.classList.contains('open')) closeLb(); });
  // WHY the GIF only on error: it is the fallback for a viewer that cannot play H.264, not a second hero.
  var v = document.querySelector('.hero video'), gif = document.getElementById('hero-gif');
  function toGif(){ if (gif && v){ v.classList.add('hidden'); gif.classList.remove('hidden'); } }
  if (v){ v.addEventListener('error', toGif, true); var src = v.querySelector('source'); if (src) src.addEventListener('error', toGif);
    if (!v.canPlayType('video/mp4')) toGif();
    // WHY an explicit play(): the autoplay attribute alone stayed paused at a phone-width viewport in headless Chrome.
    var p = v.play(); if (p && p.catch) p.catch(function(){}); }
})();
</script>
"""


def build() -> str:
    recorded = datetime.strptime(HERO["recorded_at"], "%Y-%m-%dT%H:%M:%S%z").strftime("%Y-%m-%d %H:%M")
    n_checks = len(HERO["steps"]) + len(HERO["stills"])
    passed = sum(1 for s in HERO["steps"] + HERO["stills"] if s["ok"])
    media = HERO["media"]
    elbow = STILLS["board-elbow"]["measured"]
    settings = STILLS["settings-roadmap"]["measured"]
    phone = STILLS["phone-kinsim"]["measured"]
    focus = STILLS["focus-bt1"]["measured"]
    full = STILLS["full-kinsim"]["measured"]
    back = next(s for s in HERO["steps"] if s["label"].startswith("History back"))["measured"]
    arrows = next(s for s in HERO["steps"] if s["label"].startswith("Arrow keys"))["measured"]

    hero = f"""
<figure class="hero">
  <video controls autoplay muted loop playsinline preload="auto" aria-label="Hero: tracks, kinsim, roadmap calm head, full board, Depth, arrow keys, RB0's proof, a named run, back, pyblocks">
    <source src="{data_uri(MEDIA / media['mp4'], 'video/mp4')}" type="video/mp4"></video>
  <img id="hero-gif" class="gif hidden" alt="Hero as a GIF" src="{data_uri(MEDIA / media['gif'], 'image/gif')}">
  <figcaption><b>Tracks → Kinematic Sim → Roadmap → Expand → Depth → arrow keys → RB0's proof → a named run → Back → Pyblocks ({media['clip_s']:.0f} s, {media['speed']}× speed)</b>
  <span class="cap">Recorded headless from the running lane at {esc(LANE_URL)} on live data, {esc(recorded)}. The blue dot is the pointer.
  Times below are offsets in this clip; each step's line is what the recorder measured in the page at that moment.</span></figcaption>
</figure>
{steps_list()}"""

    calm = '<div class="g1">' + "".join(
        fig(f"calm-{t}", f"{TRACK_TITLE[t]} · `{t}`",
            f"“{STILLS[f'calm-{t}']['measured']['sentence']}” · {STILLS[f'calm-{t}']['measured']['asOf']}. "
            f"Checked against the live document: {STILLS[f'calm-{t}']['measured']['docProven']} green/done and "
            f"{STILLS[f'calm-{t}']['measured']['docClaimed']} claimed of {STILLS[f'calm-{t}']['measured']['docTotal']} rungs; "
            f"the strip has {STILLS[f'calm-{t}']['measured']['stripLanes']} lanes.")
        for t in TRACKS
    ) + fig("none-pyblocks", "Pyblocks · `pyblocks`",
            f"The API answers {STILLS['none-pyblocks']['measured']['api']} for pyblocks (its loop writes no roadmap); the section "
            f"says “{STILLS['none-pyblocks']['measured']['none']}” in the faint style, not as an error.") + "</div>"

    board = '<div class="g1">' + "".join([
        fig("full-kinsim", "Kinsim's full board, Ladder lens",
            f"{full['rungs']} of {full['docTotal']} rungs in {full['lanes']} lanes (the document has {full['docAxes']} axes). "
            "Ladder is the quiet lens: lines appear only for the rung you pick."),
        fig("focus-bt1", "The focus card: BT1's proof",
            f"Verdict **{focus['verdict']}**: {focus['reason']}. {focus['evidenceRows']} evidence rows; the named runs "
            f"({', '.join(focus['runs'])}) each open their own recorded file. Picking a rung lights what it needs and what it unlocks."),
    ]) + "</div>"

    lines = '<div class="g1">' + "".join([
        fig("settings-roadmap", "The settings page: Roadmap → Lines",
            f"Gear at the top right → Settings. The Roadmap section's one item is Lines ({', '.join(o.split(':')[1] for o in settings['options'])}), "
            f"here set to {settings['value']}. The board's own toolbar keeps only {', '.join(c.replace('vt-roadmap-', '') for c in settings['toolbarControls'])}."),
        fig("board-elbow", "After switching to Elbow: the Depth board",
            f"{elbow['changed']} of {elbow['ordinary']} ordinary lines changed their path; curves before {elbow['curvesBefore']}, after "
            f"{elbow['curvesAfter']}. The crossing probe walked {elbow['checked']} lines every 4 px: {elbow['crossings']} cross a card. "
            f"The {elbow['paths'] - elbow['ordinary']} dashed alias ties keep their own short shape in both styles."),
    ]) + "</div>"

    phone_html = f"""
<div class="phone">
{fig("phone-kinsim", "Kinsim's calm head at 390 px",
     f"document scrollWidth {phone['docScroll'][0]} ≤ clientWidth {phone['docScroll'][1]}; the dashboard's scroller "
     f"{phone['dashScroll'][0]} ≤ {phone['dashScroll'][1]}; the head spans x {phone['calmBox'][0]}–{phone['calmBox'][1]} of {phone['viewport']}.")}
<div><p class="small">Captured with Clank's left panel hidden (its toggle in the status bar), as a phone reader would; with it shown,
Clank's own sidebar leaves the dashboard about 130 px and its pane scrolls sideways. That is the host's layout, not the widget's, and
the recorder shows the panel again afterwards because Clank saves its layout into the lane's workspace.</p>
<p class="small dim">The calm head wraps; nothing is cut. The same sentence, as of time and strip as on the desktop.</p></div>
</div>"""

    changed = """
<ul class="plain">
  <li><b>Live data per track, from the work-track registry.</b> Each track's note names its projector and sources; the backend projects
      <code>/roadmap/doc?track=…</code> live (kinsim, rig, grasping, detection), and a track with no roadmap gets a 404 that the widget
      reads as “No roadmap reported yet.” The kinsim dashboard read one loop's file.</li>
  <li><b>Freshness.</b> Both densities say “as of HH:MM” (the projection's own time). When a projection fails and an older good document
      is served, or a refresh fails, a calm “Not current: &lt;reason&gt;” line appears beside it; a green count from a failed
      projection never reads as current. The widget polls every 30 s.</li>
  <li><b>A settings page instead of a toolbar.</b> Line style (Curved / Elbow) moved to the dashboard's settings page as a Clank
      <code>SettingsSection</code>, so it can later move into Clank's plugin settings unchanged. The board's toolbar keeps lens,
      direction and card size: navigation, not settings.</li>
  <li><b>Named runs open their own record.</b> Every run in the proof tab opens its own recorded file at its path and line;
      “see the latest run” is the one control that goes to the rung's latest run.</li>
  <li><b>One Back stack.</b> The widget keeps no history of its own: its state is the <code>rm</code> key in the dashboard's URL hash,
      so the mouse's back button and a reload restore the lens, the picked rung and its tab.</li>
</ul>"""

    found = f"""
<ol class="issues">
  <li><b>The dashboard's reload does not reach the roadmap yet</b>The widget exposes <code>reload()</code> (re-project now) from
      <code>useRoadmap</code>, but the track page never calls it: the tracks page's Reload re-reads the projection only. Until the
      Dashboard lane wires it, a roadmap refreshes on its 30 s poll.</li>
  <li><b>Keyboard focus is not restored after Back</b>After history back from a named run, the focus card and the Depth lens come back
      (measured), but keyboard focus is on {esc(back['focused'] or 'nothing')}, so arrow keys need a click on the board first.</li>
  <li><b>→ in the Depth lens moves by column, not by rung number</b>From RB2, → went to {esc(arrows['sels'][-1])}: in Depth, RB3 sits
      in RB1's column (it can be climbed in parallel), and ↓ reaches it. Expected for the layout; noted because it surprises.</li>
  <li><b>Kinsim's head shows the loop's raw phase word</b>“Wave 4, between_waves” is the stored phase, rendered verbatim (truthful
      rendering). A friendlier word would be the projector's job, not the widget's.</li>
  <li><b>Host chrome, not the widget</b>At 390 px Clank's title overlaps its layout picker and its left panel crowds the pane (see the
      phone still). On every load Clank asks for <code>.clank/settings.json</code>, <code>tree.json</code> and <code>views.json</code> (404)
      and retries <code>mkdir .clank</code> (409); the console shows these, and the dashboard throws no page errors
      (recorder: {len(HERO['page_errors'])} page errors). The review-only Proposal switcher covers the bottom of a tall focus card.</li>
</ol>"""

    commits = fixed_in()
    audit = (audit_round(1, "V", commits) + audit_round(2, "W", commits))

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Roadmap widget review</title>
<style>{CSS}</style></head>
<body><div class="wrap">

<header class="top">
  <div class="date">2026-10-04 · roadmap lane · branch claude/vibetracks-roadmap</div>
  <h1>The roadmap, live inside Vibe Tracks</h1>
  <p class="verdict">The roadmap is now a live widget on the Vibe Tracks dashboard's track page for kinsim, rig, grasping and
  detection; pyblocks honestly says “No roadmap reported yet.”</p>
  <p class="qual">The catch: the dashboard's own Reload does not reach it yet. The widget has <code>reload()</code>, but the
  Dashboard lane has not wired it, so a roadmap refreshes on its 30-second poll.</p>
  <p class="built">Recorded headless from the running lane at {esc(recorded)}: {passed} of {n_checks} measured checks pass
  ({len(HERO['steps'])} hero steps, {len(HERO['stills'])} stills), 0 page errors. Each calm head's numbers were checked against the
  live document the API serves. Codex rounds 1 and 2 asked for fixes, and every finding has a fix commit; round 3 is running.
  This page is about {OUT_SIZE_MB} MB, so open it in a browser, not the desktop preview.</p>
  <div class="launch"><pre id="launch-cmd">{esc(RECORD_CMD)}</pre><button id="copy-launch" type="button">Copy</button></div>
  <p class="small dim">That re-records everything against the lane at <code>{esc(LANE_URL)}</code> (already running; open it to click around).
  Then rebuild this page: <code>python3 {esc(REPO)}/docs/roadmap/build_roadmap_report.py</code></p>
</header>

<nav class="toc" aria-label="Sections">
  <a href="#watch">Watch</a><a href="#heads">Per track</a><a href="#board">Board &amp; proof</a><a href="#lines">Lines setting</a>
  <a href="#phone">Phone</a><a href="#changed">What changed</a><a href="#found">Found</a><a href="#audit">Audit trail</a><a href="#decisions">Decide</a>
</nav>

<section id="watch"><h2>Watch first</h2><p class="lead">One walk through the real app, with what was measured at each step.</p>{hero}</section>
<section id="heads"><h2>The calm head on each track</h2><p class="lead">Collapsed, the Roadmap section is one sentence: where the loop is
climbing, what that unlocks, how much is proven, and what needs you. Then when it was projected and a thin per-lane strip.</p>{calm}</section>
<section id="board"><h2>Expanded: the board and the focus card</h2><p class="lead">Expand opens the full board in place. Click a rung
and its focus card grows out of it, proof first.</p>{board}</section>
<section id="lines"><h2>Line style lives on the settings page</h2><p class="lead">Your Oct 3 rule: view options go on a settings page,
never on the toolbar.</p>{lines}</section>
<section id="phone"><h2>At phone width</h2>{phone_html}</section>
<section id="changed"><h2>What changed since the kinsim dashboard</h2>{changed}</section>
<section id="found"><h2>Found in the real app (not fixed here)</h2><p class="lead">Nothing in the product was changed to make this
report; these are for their owners.</p>{found}</section>
<section id="audit"><h2>Audit trail</h2><p class="lead">Codex (read-only) attacked the lane after each round of work. A finding counts
as fixed here when a commit names it (one exception, marked in its row); the round files are linked as paths.</p>{audit}</section>
<section id="audit-round-3"><h3>Round 3</h3><div class="placeholder">Round 3 running. Its verdict is added here when it finishes.
Prompt: <code class="path">{esc(AUDITS / '2026-10-04-vibetracks-roadmap-r3-prompt.md')}</code></div></section>
<section id="decisions"><h2>Decision surface</h2><div class="placeholder">Filled in by the orchestrator.</div></section>

<footer class="end">Generated by docs/roadmap/build_roadmap_report.py from {esc(MEDIA / 'hero.json')} (recorded {esc(HERO['recorded_at'])}).</footer>
</div>
<div id="lb" role="dialog" aria-modal="true" aria-label="Full-size screenshot"><button type="button">Close (Esc)</button><img alt=""><div class="lbcap"></div></div>
{JS}
</body></html>"""
    return page


def encoded_size(page: str) -> int:
    """Length of the URL the desktop preview builds: `data:text/html,` + encodeURIComponent(page)."""
    return len("data:text/html,") + len(quote(page, safe="-_.!~*'()"))


if __name__ == "__main__":
    # The header states the page's size, so build twice: the size placeholder is a few bytes and cannot move the MB figure.
    OUT_SIZE_MB = "?"
    first = build()
    OUT_SIZE_MB = f"{len(first.encode()) / 1e6:.1f}"
    _inlined.clear()
    page = build()
    OUT.write_text(page, encoding="utf-8")
    size = OUT.stat().st_size
    url = encoded_size(page)
    verdict = "preview-openable" if url <= PREVIEW_CAP else "browser-only (over the desktop preview's cap)"
    print(f"wrote {OUT}  {size:,} bytes on disk, {len(_inlined)} media inlined once each")
    print(f"preview data: URL {url:,} bytes vs cap {PREVIEW_CAP:,}: {verdict}")
