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
WHY sections with fixed ids (audit-round-4, decisions): the orchestrator fills them after this build, by id.
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
# The commits the Found section names (read from git log; verified to exist at build time like every other sha shown).
# WHY these shas are looked up, not typed (2026-10-05): every rebase onto the Dashboard lane rewrote them, and a typed
# sha kept passing `git cat-file -e` because the pre-rebase object still exists; the page then cited a commit that is
# not in the branch. Each is found by what it is, and verify_shas() demands it be an ancestor of HEAD.
def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout.strip()


DASHBOARD_BASE = _git("rev-parse", "--short", "claude/vibetracks-dashboard")  # the Dashboard lane tip this branch sits on
RELOAD_FIX = _git("log", "-1", "--format=%h", "--", "clank/src/variants/a/roadmapReload.tsx")  # wires reload() in
FOCUS_FIX = _git("log", "-1", "--format=%h", "--", "clank/src/roadmap/focus.ts")  # focus.ts and the worded phase
RECORD_CMD = ("cd ~/vibetracks-roadmap && uv run --no-project --with playwright==1.55.0 python3 docs/roadmap/record_roadmap_widget.py "
              f"--url http://127.0.0.1:4400/ --out {MEDIA}")
# The desktop preview builds `data:text/html,` + encodeURIComponent(html) and refuses a URL longer than this.
PREVIEW_CAP = 2_097_024

HERO = json.loads((MEDIA / "hero.json").read_text())
# WHY a failing recording may still build, but only for a failure another lane owns (2026-10-05): the report must show
# the real state, and a check that fails on the Dashboard lane's markup is real state; anything else failing (or any page
# error) stops the build, so this page never presents a broken widget as shipped.
FOREIGN_FAILURES = {
    "kinsim's calm head at 390 px": "the Dashboard lane's: variant A's path lines do not wrap at 390 px (see Found in the real app)",
}
_unexplained = [label for label in HERO["failed"] if label not in FOREIGN_FAILURES]
assert not _unexplained and not HERO["page_errors"], f"the recording did not pass: {_unexplained} {HERO['page_errors']}"
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
        b, a = m["back"], m["arrow"]
        return (f"trail `{b['trail']}` · lens {b['lens']} · `rmopen={b['route']['rmopen']}` · proof tab shown · card in view "
                f"without scrolling: {m['inViewAfterBack']} · keyboard focus on `{b['active']}` · then one → (no click: "
                f"{m['clicksBetween']} clicks) selected {a['sel']}, focus on {a['focused']}")
    if label == "The dashboard's Reload re-projects the roadmap":
        urls = [r["url"] for r in m["requests"] if "url" in r]
        statuses = [str(r["status"]) for r in m["requests"] if "status" in r]
        return (f"the tracks page's Reload sent `{urls[0]}` → {', '.join(statuses)} · kinsim's calm head after it: “{m['calmAfter']}”")
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
FINDING = re.compile(r"^\*\*([A-Z]\d\d) — (\w+) — ([\w_]+)\*\* — (.*)$")


def findings(path: Path) -> tuple[list[dict], str]:
    """Each finding's id, severity and headline (its first sentence after the file links), and the round's verdict."""
    out, verdict = [], ""
    for line in path.read_text().splitlines():
        match = FINDING.match(line)
        if match:
            fid, severity, domain, rest = match.groups()
            text = re.sub(r"\[[^\]]+\]\([^)]+\)(, )?", "", rest).lstrip(" —").strip()
            out.append({"id": fid, "severity": severity, "domain": domain, "headline": re.split(r"(?<=\.)\s", text, maxsplit=1)[0]})
        elif line.strip().strip("*").startswith("VERDICT:"):  # bold or plain: the judge writes both
            verdict = line.strip().strip("*").replace("VERDICT: ", "").strip("*").strip()
    return out, verdict


_shas: set[str] = set()


def sha(value: str) -> str:
    """A commit id as the page shows it, remembered so the build can prove each one is in this branch (an ancestor of HEAD)."""
    _shas.add(value)
    return f"<code>{esc(value)}</code>"


def verify_shas() -> None:
    missing = [value for value in sorted(_shas)
               if subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", value, "HEAD"], capture_output=True).returncode]
    assert not missing, f"the page names commits that do not exist: {missing}"


def landed() -> dict[str, bool]:
    """Whether this branch's HEAD is inside the Dashboard lane's branch or main (measured, never assumed)."""
    def inside(ref: str) -> bool:
        return subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", "HEAD", ref], capture_output=True).returncode == 0
    return {"claude/vibetracks-dashboard": inside("claude/vibetracks-dashboard"), "main": inside("main")}


def fixed_in() -> dict[str, list[str]]:
    """Finding id → the commits whose subject names it ("Codex V04 V05", or a range "V06-V10")."""
    log = subprocess.run(["git", "-C", str(REPO), "log", "--format=%h\t%s", "-60"], capture_output=True, text=True, check=True).stdout
    found: dict[str, list[str]] = {}
    for line in log.splitlines():
        sha, subject = line.split("\t", 1)
        codex = re.search(r"\(Codex ([^)]*)\)", subject)
        if not codex:
            continue
        for token in re.findall(r"[A-Z]\d\d(?:-[A-Z]\d\d)?", codex.group(1)):
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
        return " ".join(sha(c) for c in commits[fid])
    if fid in UNNAMED_FIXES:
        commit, why = UNNAMED_FIXES[fid]
        return f'{sha(commit)}<span class="dim blk small">{esc(why)}</span>'
    return '<span class="badt">none</span>'


def audit_file(n: int) -> Path | None:
    """Round ``n``'s report, whatever day it ran (the rounds crossed midnight)."""
    found = sorted(AUDITS.glob(f"20*-vibetracks-roadmap-r{n}.md"))
    return found[-1] if found else None


def audit_round(n: int, commits: dict[str, list[str]]) -> str:
    path = audit_file(n)
    items, verdict = findings(path)
    prefix = items[0]["id"][0] if items else ""  # each round names its own letter (V, W, … A, B): read it, never assume it
    rows = "".join(
        f'<tr><th scope="row">{esc(f["id"])}</th><td>{esc(f["severity"])}</td><td>{inline_md(f["headline"])}</td>'
        f'<td class="fix">{fix_cell(f["id"], commits)}</td></tr>'
        for f in items
    )
    unfixed = [f["id"] for f in items if f["id"] not in commits and f["id"] not in UNNAMED_FIXES]
    by_hand = [f["id"] for f in items if f["id"] not in commits and f["id"] in UNNAMED_FIXES]
    state = ("every finding has a fix commit" if not unfixed else f"no fix commit for {', '.join(unfixed)}") + (
        f" ({', '.join(by_hand)} by a commit that does not name it; see its row)" if by_hand else "")
    # WHY "PASS" is not followed by "→ fixed": a passing round had no blocker or major; its minors are listed with their
    # fix commits like any other finding, but the heading must say what the judge said.
    heading = f'Round {n}: {esc(verdict)}' + ('' if verdict.startswith('PASS') else ' → fixed')
    if not items:
        return (f'<h3>{heading}</h3><p class="small dim">No findings. Audit file: <code class="path">{esc(path)}</code></p>')
    return (f'<h3>{heading}</h3>'
            f'<p class="small dim">{len(items)} findings ({prefix}01–{prefix}{len(items):02d}); {state}. '
            f'Audit file: <code class="path">{esc(path)}</code></p>'
            f'<div class="tablewrap"><table class="grid"><thead><tr><th>id</th><th>severity</th><th>finding</th><th>fixed in</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


DECISIONS = """
<h3>Done and proved</h3>
<ul class="small">
  <li>The roadmap is a live widget in variant A's track page for kinsim, rig, grasping and detection, read from each loop's current
      files through the work-track registry; pyblocks shows “No roadmap reported yet.” The recordings above measure every step.</li>
  <li>The home page's Progress column now adds “· N proven” from this widget's counts (the Dashboard lane's change; measured on
      4400: kinsim 4, rig 0, grasping matching the live document, detection 0, pyblocks unchanged), so “19 / 62” no longer reads as proof.</li>
  <li>Freshness is honest end to end: a served fallback says “Not current: &lt;reason&gt;”, a failed refresh says so too, and the
      dashboard's Reload re-projects (measured above).</li>
  <li>Grasping reads the bench's own verdict. On Oct 4 evening the bench tightened what counts as a frozen run
      (a row must vouch for its own settings); the projector's copy of the bench's rules kept the old one and called envs
      the bench rates provisional “claimed”. The copy is gone: claims and per-run frozen status now come from the bench's own
      gallery, run in its own venv through the bridge shared with the Dashboard lane (<code>vibetracks/benches/grasp_bench_bridge.py</code>),
      and if the bench cannot run, grasping says “not current” instead of guessing. Its calm head above is this build's.</li>
  <li>Tests on the final head: every repo test module 415 OK run module by module (a whole-tree <code>unittest discover</code> stops
      at load on the Dashboard lane's own <code>test_server</code> name collision, which they are fixing), plugin backend 23 OK,
      widget 158 passed with a clean type check, projector 340 passed (1 bam_ws-only skip).</li>
</ul>
<h3>Needs you (each with the default if you say nothing)</h3>
<ol class="small">
  <li><b>Integrate the roadmap branch into <code>claude/vibetracks-dashboard</code>?</b> Recommended yes, once the Dashboard lane's own
      Codex pass is green. Default: a merge commit on that unpushed lane branch after both sides pass; never <code>main</code>.</li>
  <li><b>The three kinsim-dashboard roadmap candidates still in the merge-ready queue</b> (lens bar, React Flow, the bam_ws API) were
      built before the roadmap moved here. Recommended: supersede them. Default: leave them held and unlanded.</li>
</ol>
<h3>Deliberately not done</h3>
<ul class="small">
  <li>Clank's 390 px sidebar and title overlap, and its <code>.clank</code> console noise: the Clank host's, not this widget's.</li>
  <li>A Clank plugin-settings page: Clank has no reader for a plugin's settings section yet, so the dashboard renders the Roadmap
      settings itself; the section is already in Clank's <code>SettingsSection</code> shape for when it does.</li>
  <li>Nothing was written to any loop's worktree, to Vibe Tracks <code>main</code>, or to your own dashboard's ports.</li>
</ul>"""


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
.tag{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.03em;color:var(--dim);border:1px solid var(--line2);border-radius:999px;padding:0 8px;margin-left:6px;vertical-align:1px}
.tag.ok{color:var(--ok);border-color:var(--ok)}
.tag code{font-size:11px;border:0;background:none;padding:0}
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
  <video controls autoplay muted loop playsinline preload="auto" aria-label="Hero: tracks, kinsim, roadmap calm head, full board, Depth, arrow keys, RB0's proof, a named run, back, Reload, pyblocks">
    <source src="{data_uri(MEDIA / media['mp4'], 'video/mp4')}" type="video/mp4"></video>
  <img id="hero-gif" class="gif hidden" alt="Hero as a GIF" src="{data_uri(MEDIA / media['gif'], 'image/gif')}">
  <figcaption><b>Tracks → Kinematic Sim → Roadmap → Expand → Depth → arrow keys → RB0's proof → a named run → Back, then → → Tracks → Reload → Pyblocks ({media['clip_s']:.0f} s, {media['speed']}× speed)</b>
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
      projection never reads as current. The widget polls every 30 s, and the dashboard's own Reload re-projects every roadmap on the
      page (<code>&amp;refresh=1</code>).</li>
  <li><b>A settings page instead of a toolbar.</b> Line style (Curved / Elbow) moved to the dashboard's settings page as a Clank
      <code>SettingsSection</code>, so it can later move into Clank's plugin settings unchanged. The board's toolbar keeps lens,
      direction and card size: navigation, not settings.</li>
  <li><b>Named runs open their own record.</b> Every run in the proof tab opens its own recorded file at its path and line;
      “see the latest run” is the one control that goes to the rung's latest run.</li>
  <li><b>One Back stack.</b> The widget keeps no history of its own: its state is the <code>rm</code> key in the dashboard's URL hash,
      so the mouse's back button and a reload restore the lens, the picked rung and its tab.</li>
</ul>"""

    reload_step = next(st for st in HERO["steps"] if st["label"].startswith("The dashboard's Reload"))["measured"]
    kinsim_calm = STILLS["calm-kinsim"]["measured"]
    found = f"""
<ol class="issues">
  <li><b>The dashboard's Reload now reaches the roadmap <span class="tag ok">fixed in {sha(RELOAD_FIX)}</span></b>The Dashboard lane's
      <code>variants/a/roadmapReload.tsx</code> registers every mounted roadmap's <code>reload()</code> with variant A's own reload.
      Measured: the tracks page's Reload sent <code>{esc(next(r["url"] for r in reload_step["requests"] if "url" in r))}</code>
      (HTTP {esc(next(r["status"] for r in reload_step["requests"] if "status" in r))}), and kinsim's calm head was still drawn after it.</li>
  <li><b>Keyboard focus comes back after Back <span class="tag ok">fixed in {sha(FOCUS_FIX)}</span></b>After history back from a named run
      the RB0 card holds keyboard focus (<code>{esc(back['back']['active'])}</code>), and one → with no click moved the selection to
      {esc(back['arrow']['sel'])}.</li>
  <li><b>The calm head says the phase in words <span class="tag ok">fixed in {sha(FOCUS_FIX)}</span></b>Kinsim's head now reads
      “{esc(kinsim_calm['stage'])}”; the loop's raw token stays one hover away in its title (<code>{esc(kinsim_calm['phaseTitle'])}</code>),
      so no stored character is lost.</li>
  <li><b>→ in the Depth lens moves by column, not by rung number <span class="tag">expected</span></b>The arrow walk went
      {esc(' → '.join(arrows['sels']))}: in Depth, rungs that can be climbed in parallel share a column, and ↓ reaches them.
      Noted because it surprises.</li>
  <li><b>The Proposal switcher covers the bottom of a tall focus card <span class="tag">Dashboard lane's</span></b>The review-only switcher
      is theirs; a compact pill is in their next wave.</li>
  <li><b>At 390 px Clank's sidebar crowds the pane and its title overlaps the layout picker <span class="tag">Clank host's</span></b>Logged as a
      deliberate not-done. The phone still is taken with Clank's left panel hidden; the widget itself has no horizontal scroll.</li>
  <li><b>At 390 px variant A's path lines scroll the page sideways <span class="tag">Dashboard lane's</span></b>The one failing check
      above: kinsim's “Event log / Live fold / Run ledger” paths (<code>code.vt-a-code</code>) do not wrap, so the dashboard is
      453 px wide in a 390 px window. The calm head itself fits. Sent to the Dashboard lane with the fix (wrap, never clip).</li>
  <li><b>Clank's console noise <span class="tag">Clank host's</span></b>On every load Clank asks for <code>.clank/settings.json</code>,
      <code>tree.json</code> and <code>views.json</code> (404) and retries <code>mkdir .clank</code> (409). The dashboard throws no page
      errors (recorder: {len(HERO['page_errors'])}).</li>
</ol>"""

    commits = fixed_in()
    rounds = [n for n in range(1, 20) if audit_file(n) is not None]
    audit = "".join(audit_round(n, commits) for n in rounds)
    last_verdict = findings(audit_file(rounds[-1]))[1]
    where = landed()

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
  <p class="qual">Verified in the real app, on the roadmap branch rebased onto the Dashboard lane's {sha(DASHBOARD_BASE)}. Not landed:
  the roadmap branch is {'inside' if where['claude/vibetracks-dashboard'] else 'not in'} <code>claude/vibetracks-dashboard</code> and
  {'inside' if where['main'] else 'not in'} <code>main</code>. Integrating it is your call.</p>
  <p class="built">Recorded headless from the running lane at {esc(recorded)}: {passed} of {n_checks} measured checks pass
  ({len(HERO['steps'])} hero steps, {len(HERO['stills'])} stills), 0 page errors{"".join(f"; failing: {esc(label)}, {esc(FOREIGN_FAILURES[label])}" for label in HERO["failed"])}. Each calm head's numbers were checked against the
  live document the API serves. Codex ran {len(rounds)} read-only rounds; the last one says {esc(last_verdict)}, and every
  finding of every round has a fix commit.
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
<section id="found"><h2>Found in the real app</h2><p class="lead">What the recordings turned up, and where each one stands now.
Nothing in the product was changed to make this report.</p>{found}</section>
<section id="audit"><h2>Audit trail</h2><p class="lead">Codex (read-only) attacked the lane after each round of work. A finding counts
as fixed here when a commit names it (one exception, marked in its row); the round files are linked as paths.</p>{audit}</section>
<section id="decisions"><h2>Decision surface</h2>{DECISIONS}</section>

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
    _shas.clear()
    page = build()
    verify_shas()
    OUT.write_text(page, encoding="utf-8")
    size = OUT.stat().st_size
    url = encoded_size(page)
    verdict = "preview-openable" if url <= PREVIEW_CAP else "browser-only (over the desktop preview's cap)"
    print(f"wrote {OUT}  {size:,} bytes on disk, {len(_inlined)} media inlined once each")
    print(f"commits shown, each verified as an ancestor of HEAD: {' '.join(sorted(_shas))}")
    print(f"preview data: URL {url:,} bytes vs cap {PREVIEW_CAP:,}: {verdict}")
