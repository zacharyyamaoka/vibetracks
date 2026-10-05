#!/usr/bin/env python3
"""Build the integration report for the LIVE Vibe Tracks dashboard (variant A, five work tracks).

    python3 /home/bam/vibetracks-dashboard/docs/dashboard/build_live_report.py

Writes ONE self-contained file:
    /home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04.html

Inputs (all in MEDIA, written by the headless drive; none of them is hand-typed here):
    drive-facts.json        what the real lane showed: home rows, each track page's state, order and KPI rows, rename
    evidence-facts.json     the L3 evidence item, the wave-4 report, CAN 16 and the rig's deployments
    source-checks.json      KPIs recomputed straight from each loop's own files vs what the projection shows
    projection-*.json       the projection the backend served at check time (sources, freshness, roadmap declaration)
    *.webp / hero-live-tracks.mp4 / .gif   the captures

WHY the per-track table and the check table are read from JSON: a hand-typed number in a report outlives the data
it describes; these files are the drive's own output, so a re-drive refreshes the report.
WHY every capture is inlined exactly once: Zach reviews by reading, from any device; the lightbox re-uses the
clicked <img>'s src at runtime instead of a second copy. The page is ~3 MB, past the desktop preview's ~1.9 MB cap,
so it is browser-only (the handoff says so) and lives in the gitignored reports/media/ half.
"""
from __future__ import annotations

import base64
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

MEDIA = Path("/home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04")
FB_DIR = Path("/home/bam/vibetracks/reports/media/dashboard-prior-art-2026-10-03")
OUT = Path("/home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04.html")
REPORT_NAME = OUT.name
LAUNCHER = "/home/bam/vibetracks-dashboard/scripts/open-dashboard"

sys.path.insert(0, str(FB_DIR))
import report_feedback as FB  # noqa: E402

FACTS = json.loads((MEDIA / "drive-facts.json").read_text())
EV = json.loads((MEDIA / "evidence-facts.json").read_text())
CHECKS = json.loads((MEDIA / "source-checks.json").read_text())
PROJ_PATH = sorted(MEDIA.glob("projection-*.json"))[-1]
PROJ = json.loads(PROJ_PATH.read_text())
TRACKS = {t["id"]: t for t in PROJ["tracks"]}
ORDER = [row["id"] for row in FACTS["home"]["rows"]]
assert ORDER == ["kinsim", "rig", "grasping", "detection", "pyblocks"], f"home rows changed: {ORDER}"
assert FACTS["rename"]["restored"]["identical"], "the rename-back did not restore the note byte-for-byte"
assert all(c["match"] for c in CHECKS), "a source check disagrees with the projection: read source-checks.json"

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
    alt = f"{label}"
    return (
        f'<figure class="cell {cls}"><button class="zoom" type="button" aria-label="Open {esc(alt)} full size">'
        f'<img width="1440" height="900" alt="{esc(alt)}" src="{data_uri(MEDIA / name, "image/webp")}"></button>'
        f'<figcaption><b>{inline_md(label)}</b><span class="cap">{inline_md(cap)}</span></figcaption></figure>'
    )


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "—"
    return datetime.fromisoformat(iso).strftime("%m-%d %H:%M")


def age(h: float | None) -> str:
    if h is None:
        return "unknown"
    if h < 1:
        return f"{round(h * 60)} min"
    if h < 48:
        return f"{h:.1f} h"
    return f"{h / 24:.0f} days"


# ---- per-track facts --------------------------------------------------------------------------------------------
TRACK_PAGE = {t: FACTS["tracks"][t] for t in ORDER}

# The gaps each adapter lane reported (their own words, condensed); the numbers beside them are read from JSON.
GAPS = {
    "kinsim": [
        "status.json has no per-wave KPI series, so W1–W4 are rebuilt from loop_events.jsonl + runs.jsonl with the "
        "loop's own gate rules; the last wave is cross-checked against status.json (they agree: 15 green + 4 done).",
        "Packages landed and the df readings are parsed from event prose; a wording change makes them explicit gaps, never zeros.",
        "W1 has no elapsed hours (its wave_started was written at the close).",
        "The loop checkout resolves through the agent worktree wave-3-handoff-af2b9b.",
    ],
    "rig": [
        "triage.json, ROADMAP.md and the run cache are read but not declared in vibe-sources, so changing only them does not rebuild.",
        "kpis_session/kpis_day fixtures are frozen at 10-02 23:13 and miss twin V1-f2308e5f (filled from deployments.json + the run cache).",
        "Tick 2 has no events and tick 4 no wave_started row; 6 package landings and 2 greens are placed by ladder.json times.",
        "Everything lives on the unmerged worktree rig-loop-work-continue-cb3c52.",
    ],
    "grasping": [
        "No loop status file: the frontier tier and 'next tier' are derived from the ledger and curriculum.py.",
        "The ledger lives in the gitignored out/ of agent worktree grasping-agent-roadmap-ab12d8; a sweep turns the row 'not reporting'.",
        "The frozen protocol and EnvSpec field order are mirrored from the bench (the live smoke test catches drift).",
        "The 1 s latency limit comes from Zach's deck, not curriculum.py; sim latency excludes camera capture.",
    ],
    "detection": [
        "Only queue.log is declared; ladder_data.py, compile_results.py, per-run logs, wandb/ and the vault plan note are read from defaults.",
        "Rung status is not stored as data anywhere, so there is no 'rungs green' KPI; the frontier is derived (H1 2 of 12).",
        "Needs-you reflects the 10-04 plan note; the Windows answer in the daily note is not read.",
        "ladder_data.py is untracked in a worktree and could be lost to a sweep or stash -u.",
    ],
    "pyblocks": [
        "The loop writes no status file and no questions: needs-you is 'not reported', never 0.",
        "The INT stop (account limit, reset 10-06 08:00) is a dated constant attributed to the 10-04 discovery; it drops itself when a newer window lands.",
        "The board series stops at b07c38b (10-01); the 10-02 numbers exist only in an HTML summary's prose and are not emitted.",
        "No roadmap is declared (vibe-roadmap: null).",
    ],
}


def roadmap_source(t: dict) -> str:
    rm = (t.get("registry") or {}).get("roadmap")
    if not rm:
        return "none declared (<code>vibe-roadmap: null</code>)"
    return (f"declared: projector <code>{esc(rm.get('projector'))}</code> over "
            + ", ".join(f"<code>{esc(s)}</code>" for s in rm.get("sources", []))
            + "<br><span class=\"warnt\">not rendered: widget is a stub in this lane, /roadmap answers 404</span>")


def track_table() -> str:
    rows = []
    for tid in ORDER:
        t = TRACKS[tid]
        fr = t.get("freshness") or {}
        srcs = "".join(
            f'<li><code>{esc(s["key"])}</code> <span class="dim">{esc(fmt_time(s.get("modified")))}</span>'
            f'<span class="path">{esc(s["path"])}</span></li>'
            for s in fr.get("sources", [])
        )
        stale = fr.get("stale")
        fresh = (f'<b class="{"warnt" if stale else "okt"}">{"stale" if stale else "fresh"}</b> · newest '
                 f'{esc(age(fr.get("age_h")))} old <span class="dim">({esc(fr.get("newest_source"))})</span>'
                 + (f'<br><span class="dim">{esc(fr["note"])}</span>' if fr.get("note") else ""))
        kpis = t.get("kpis", [])
        star = (t.get("north_star") or {})
        kpi_list = "".join(f"<li>{esc(k['label'])}</li>" for k in kpis)
        gaps = "".join(f"<li>{inline_md(g)}</li>" for g in GAPS[tid])
        rows.append(
            f'<tr><th scope="row">{esc(t["title"])}<span class="tid">id <code>{esc(tid)}</code> · adapter '
            f'{esc((t.get("source") or {}).get("kind"))}</span></th>'
            f'<td><ul class="srcs">{srcs}</ul></td><td>{fresh}</td>'
            f'<td><details><summary>{len(kpis)} KPIs</summary><ul class="kl">{kpi_list}</ul></details></td>'
            f'<td>{roadmap_source(t)}</td><td><ul class="gaps">{gaps}</ul></td></tr>'
        )
    return ('<div class="tablewrap"><table class="grid"><thead><tr><th>Track</th><th>Data source files (modified)</th>'
            '<th>Freshness</th><th>KPIs shown</th><th>Roadmap source</th><th>Gaps</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div>")


def checks_table() -> str:
    rows = "".join(
        f'<tr><td>{esc(TRACKS[c["track"]]["title"])}</td><td>{esc(c["kpi"])}</td>'
        f'<td class="num">{esc(c["shown"])}</td><td class="num">{esc(c["recomputed"])}</td>'
        f'<td><code>{esc(c["source"])}</code><span class="dim blk">{esc(c["how"])}</span></td>'
        f'<td class="{"okt" if c["match"] else "badt"}">{"match" if c["match"] else "MISMATCH"}</td></tr>'
        for c in CHECKS
    )
    return ('<div class="tablewrap"><table class="grid"><thead><tr><th>Track</th><th>KPI</th><th>Dashboard shows</th>'
            '<th>Recomputed from source</th><th>Source file · how</th><th></th></tr></thead><tbody>' + rows
            + "</tbody></table></div>")


def home_rows() -> str:
    out = []
    for row in FACTS["home"]["rows"]:
        name, status, progress, rung, moved, needs = row["cells"][:6]
        out.append(f"<tr><th>{esc(name)}</th><td>{esc(status)}</td><td>{esc(progress)}</td><td>{esc(rung)}</td>"
                   f"<td>{esc(moved)}</td><td>{esc(needs)}</td></tr>")
    return ('<details class="raw"><summary>The home rows as the drive read them (text)</summary><div class="tablewrap">'
            '<table class="grid small"><thead><tr><th>Name</th><th>Status</th><th>Progress</th><th>Current rung → next</th>'
            '<th>Last moved</th><th>Needs you</th></tr></thead><tbody>' + "".join(out) + "</tbody></table></div></details>")


def order_table() -> str:
    out = []
    for tid in ORDER:
        o = TRACK_PAGE[tid]["order"]
        cells = " < ".join(f"{k} {v}" for k, v in sorted(((k, v) for k, v in o.items() if v is not None), key=lambda kv: kv[1]))
        out.append(f"<li><b>{esc(TRACKS[tid]['title'])}</b> <span class=\"dim\">{esc(cells)} px</span></li>")
    return "<ul class=\"order\">" + "".join(out) + "</ul>"


def live_status() -> str:
    groups = {"fresh": [], "stale": []}
    for tid in ORDER:
        t = TRACKS[tid]
        fr = t.get("freshness") or {}
        groups["stale" if fr.get("stale") else "fresh"].append(t)
    def item(t: dict) -> str:
        st = t.get("state") or {}
        return (f'<li><b>{esc(t["title"])}</b> · <span class="sw">{esc(st.get("word"))}</span>'
                f'<span class="dim blk">{esc(st.get("detail"))}</span></li>')
    kids = [TRACKS[c] for c in ("can12", "can16")]
    return f"""
<div class="two">
  <div><h4>Live and current ({len(groups['fresh'])})</h4><ul class="ls">{''.join(item(t) for t in groups['fresh'])}</ul></div>
  <div><h4>Live but stale ({len(groups['stale'])})</h4><ul class="ls">{''.join(item(t) for t in groups['stale'])}</ul>
  <p class="dim small">Both read from their loops' real files; the files simply have not moved. Detection's loop has never
  started (plan only, data drive not mounted); Pyblocks' INT loop stopped 10-01 on the account's weekly limit.</p></div>
</div>
<h4>Not reporting (0)</h4>
<p class="small">All five adapters are live (<code>source.kind = live</code>); the registry reports no problems.</p>
<h4>Deployments under the rig (live, old data)</h4>
<ul class="ls">{''.join(item(t) for t in kids)}</ul>
<p class="dim small">CAN 12 and CAN 16 are built live, but their newest real runs are 07-29 and 07-28, and the session KPI
fixtures they read were written 10-02 23:13. The page says "last moved 68 days ago" for CAN 16, not the rig loop's minutes.</p>"""


# ---- sections ----------------------------------------------------------------------------------------------------
def kinsim_kpi_text() -> str:
    rows = TRACK_PAGE["kinsim"]["kpis"]
    return "".join(
        f"<li><b>{esc(r['cells'][0])}</b> <span class=\"dim\">{esc(' → '.join(c for c in r['cells'][1:6] if c))}"
        f" · {esc(r['cells'][-1])}</span></li>" for r in rows[:4]
    )


ISSUES = [
    ("Roadmap is a stub on every track", "The Roadmap section says 'Roadmap widget pending (roadmap session)' on all five "
     "pages, and the home's **Current rung → next** cell falls back to the current iteration plus 'roadmap not reported yet'. "
     "The real widget exists on branch `claude/vibetracks-roadmap` (b19d6a3, worktree `/home/bam/vibetracks-roadmap`) but is "
     "not in this lane, and `GET /api/plugins/vibetracks/roadmap/<id>` answers 404 for all five. This is the largest gap "
     "against the brief ('the roadmap for what is next and what is the current rung')."),
    ("Grasping's home row contradicts itself", "Status reads **Tier 2 · MuJoCo physics** (the frontier: lowest tier with an "
     "unbeaten gate) while Current rung reads **T5 · Live sim with a simulated camera** (the newest phase the ledger touched). "
     "The fallback cell shows the latest iteration, not the frontier. It goes away once the roadmap widget supplies current/next."),
    ("Mixed time zones in state lines", "Kinsim, Grasping and Pyblocks say 'since … UTC'; Rig and Detection say '… −07:00'. "
     "The adapters emit different zones and the page renders them as given. Recommend local time everywhere, in the adapters."),
    ("Purpose text cut at 280 characters by the build", "`vibetracks/notes.py first_paragraph` cuts with no mark "
     "(kinsim ends 'Its live fold is stat…'). Variant A adds the ellipsis and the note path on hover; the fix belongs in the build."),
    ("Detection labels repeat their group", "KPI labels start with 'North star ·', 'Frontier gate ·', 'Delivery ·' under group "
     "headers of the same name, so the north-star line reads 'North star — North star · best valid…'. Adapter labels."),
    ("Wide scorecards clip their left header", "Detection has 8 iterations; the scorecard scrolls to the latest and the first "
     "visible column's header is cut at the scroll edge. Minor."),
    ("Review chrome covers content", "The temporary 'Proposal A/B/C' switcher (and the Needs-you N1–N5 switcher on the needs "
     "page) float over the bottom-right Status column. Expected to go when a variant is chosen."),
    ("Needs page count differs from the row", "Kinsim's needs link opens the other workflow's N1 page reading '1 of 3' while the "
     "row says 11 open · 1 blocking. Possibly deliberate (items whose default is already in force); flagged to that workflow, "
     "not checked here."),
    ("Clank shell errors (not the dashboard)", "One '[clank] workspace autosave failed … Bad Request' (400 POST /api/fs/write) "
     "during the drive, plus the shell's usual .clank/*.json 404s and fs mkdir 409s. No error came from the dashboard code."),
    ("Two stale shared tests", "`python3 -m pytest tests` → 171 passed, 2 failed, both in tests/test_dashboard_live_build.py and "
     "both pinning the pre-live stub/snapshot state (kinsim stub summary; rig children from the snapshot). Owner to update."),
    ("Most of the lane is untracked", "The five adapters, their tests, live.ts, rename.tsx and the needs code are untracked in "
     "/home/bam/vibetracks-dashboard. A peer's `git stash -u` in that checkout would take them."),
    ("Undeclared inputs and worktree-hosted sources", "Rig, Detection and Grasping read files their notes do not declare (no "
     "rebuild when only those change), and kinsim, rig and grasping read from agent worktrees a sweep could delete."),
]


DECISION = f"""
<ul>
  <li><strong>Done and proved:</strong>
    <ul>
      <li>Home shows exactly the five work tracks in priority order, no deployments: {esc(FACTS['home']['header'])}.</li>
      <li>Every track page drove headless in the real lane: title → state → needs link → Key KPIs → Roadmap
          (rig adds Deployments after Roadmap); measured with getBoundingClientRect.</li>
      <li>{len(CHECKS)} KPI values on five tracks plus CAN 16 recomputed from the loops' own files: all match.</li>
      <li>Rename by double-click and back by ⋯ menu: two POSTs to <code>/tracks/pyblocks/title</code>, <code>vibe-id</code> unchanged,
          the note's sha256 identical afterwards ({esc(FACTS['rename']['before']['sha'][:12])}…).</li>
      <li>L3: the W4 iteration, the BT2 promotion run (418/1000) and the Wave 4 report open; Back climbs one level per press.</li>
      <li>Typecheck clean (whole clank project); 171 of 173 tests pass (2 stale, above).</li>
    </ul></li>
  <li><strong>Left:</strong>
    <ul>
      <li>Land the roadmap widget into this lane (blocked on you, below), then re-drive the Roadmap section and the home's rung cell.</li>
      <li>Update the two stale tests; declare the undeclared inputs in the track notes and sources.py (owners: the adapter lanes).</li>
      <li>Codex audit of this integration (not run in this pass).</li>
    </ul></li>
  <li><strong>Needs you</strong> (each has a default that keeps work moving if you say nothing):
    <ol>
      <li><b>Merge the roadmap widget</b> (<code>claude/vibetracks-roadmap</code> b19d6a3) into <code>claude/vibetracks-dashboard</code>?
          Recommendation: yes, it is what makes 'current rung → next' real. Default: nothing is merged; the section keeps saying pending.</li>
      <li><b>Commit the lane</b> on <code>claude/vibetracks-dashboard</code> so a peer's stash cannot take the untracked adapters and UI?
          Recommendation: yes. Default: left uncommitted, as this task's rules require.</li>
      <li><b>One time zone</b>: local time in every state line? Recommendation: local. Default: each adapter keeps its own zone.</li>
      <li><b>Durable homes for loop files</b> now in agent worktrees (rig loop, grasp ledger, kinsim loop dir)?
          Recommendation: a stable path per loop. Default: unchanged; a sweep would turn a row 'not reporting', honestly.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no git commits, no vault edits, nothing fixed outside <code>clank/src/variants/a/</code>
      (and nothing changed there in this pass); the Needs-you files and the roadmap widget were not touched; the Clank lane was
      left running; only the vibetracks plugin backend was restarted.</li>
</ul>
"""

CSS = r"""
:root{
  --bg:#fff; --fg:#1b1d21; --dim:#5d6470; --dim2:#8a919c; --line:#e6e8ec; --line2:#d3d7de; --panel:#f7f8fa;
  --accent:#2563eb; --ok:#2f7d4f; --warn:#b4540a; --bad:#b42318;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 var(--sans);-webkit-text-size-adjust:100%}
.wrap{max-width:1240px;margin:0 auto;padding:0 16px 120px}
h1{font-size:34px;line-height:1.15;margin:0 0 12px;letter-spacing:-.02em}
h2{font-size:22px;margin:0 0 6px;letter-spacing:-.01em}
h3{font-size:16px;margin:18px 0 6px}
h4{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim2);margin:22px 0 8px;font-weight:700}
p{margin:0 0 10px}
code{font:12.5px var(--mono);background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:0 4px;word-break:break-word}
.hidden{display:none !important}
.dim{color:var(--dim)} .small{font-size:13px} .blk{display:block}
.okt{color:var(--ok);font-weight:600} .warnt{color:var(--warn)} .badt{color:var(--bad);font-weight:700}
header.top{padding:40px 0 18px}
.date{color:var(--dim2);font-size:13px;margin-bottom:8px}
.verdict{font-size:18px;line-height:1.45;font-weight:700;margin:0 0 10px;max-width:62em}
.built{color:var(--dim);font-size:13.5px;margin:0 0 16px;max-width:62em}
.launch{display:flex;align-items:stretch;max-width:640px;border:1px solid var(--line2);border-radius:9px;overflow:hidden;background:var(--panel)}
.launch pre{margin:0;padding:10px 14px;font:13px/1.4 var(--mono);overflow-x:auto;flex:1;white-space:pre}
.launch button{border:0;border-left:1px solid var(--line2);background:#fff;font:600 13px var(--sans);padding:0 16px;cursor:pointer;color:var(--fg)}
.launch button.done{color:var(--ok)}
nav.toc{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);border-bottom:1px solid var(--line);
  display:flex;gap:4px;overflow-x:auto;padding:8px 16px;margin:0 -16px;scrollbar-width:none}
nav.toc a{color:var(--dim);text-decoration:none;font-size:13px;padding:5px 11px;border-radius:7px;white-space:nowrap}
nav.toc a:hover{background:var(--panel);color:var(--fg)}
section{padding-top:44px;scroll-margin-top:44px}
.lead{color:var(--dim);margin:0 0 18px;max-width:62em}
.hero{margin:0}
.hero video,.hero img.gif{width:100%;max-width:1100px;display:block;border:1px solid var(--line2);border-radius:10px;background:#111;aspect-ratio:1280/800}
figcaption{margin-top:8px;font-size:13px;max-width:1100px}
figcaption b{display:block;font-size:13.5px}
.cap{display:block;color:var(--dim);font-size:12.5px;line-height:1.5;margin-top:2px}
.g1{display:grid;grid-template-columns:1fr;gap:18px;max-width:1100px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.cell{margin:0;min-width:0}
.zoom{all:unset;display:block;width:100%;cursor:zoom-in;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--panel);line-height:0}
.zoom:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.zoom img{width:100%;height:auto;display:block}
.zoom:hover{border-color:var(--accent)}
@media(max-width:820px){.g2{grid-template-columns:1fr}}
#lb{position:fixed;inset:0;z-index:100;background:rgba(10,12,16,.88);display:none;flex-direction:column;align-items:center;justify-content:center;padding:20px;gap:12px}
#lb.open{display:flex}
#lb img{max-width:100%;max-height:calc(100vh - 120px);object-fit:contain;border-radius:6px;background:#fff;cursor:zoom-out}
#lb .lbcap{color:#e8eaee;font-size:13px;max-width:900px;text-align:center}
#lb button{position:fixed;top:12px;right:14px;border:1px solid #ffffff55;background:#00000066;color:#fff;border-radius:8px;font:600 13px var(--sans);padding:7px 12px;cursor:pointer}
@media(max-width:560px){#lb{justify-content:flex-start;align-items:flex-start;overflow:auto;padding-top:56px}#lb img{max-width:none;max-height:none;width:900px}}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table.grid{border-collapse:collapse;width:100%;min-width:900px;font-size:13px}
table.grid th,table.grid td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
table.grid thead th{font-size:11.5px;color:var(--dim);font-weight:700;background:var(--panel)}
table.grid tbody th{font-weight:700;min-width:150px}
table.grid.small{font-size:12.5px}
.tid{display:block;font-weight:400;color:var(--dim2);font-size:12px;margin-top:2px}
.num{text-align:right !important;font-variant-numeric:tabular-nums;white-space:nowrap}
ul.srcs,ul.gaps,ul.kl{margin:0;padding-left:16px}
ul.srcs li,ul.gaps li{margin:0 0 6px}
.path{display:block;font:11px var(--mono);color:var(--dim2);word-break:break-all}
ul.order,ul.ls{margin:0;padding-left:18px;font-size:14px}
ul.order li,ul.ls li{margin:0 0 8px}
.sw{font-weight:600}
.two{display:grid;grid-template-columns:1fr 1fr;gap:28px}
@media(max-width:820px){.two{grid-template-columns:1fr;gap:0}}
.steps{margin:0;padding-left:20px;font-size:14px;max-width:62em} .steps li{margin:0 0 8px}
details.raw{margin-top:12px} summary{cursor:pointer;color:var(--dim);font-weight:600;font-size:13px}
.issues{margin:0;padding-left:20px;max-width:66em} .issues li{margin:0 0 12px;font-size:14px} .issues b{display:block}
.decide{border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:12px;padding:6px 22px 14px;background:var(--panel)}
.decide ul,.decide ol{margin:4px 0 8px;padding-left:20px}
.decide>ul>li{margin:12px 0}
footer.end{margin-top:40px;color:var(--dim2);font-size:12px}
"""

FB_LIGHT = r"""
.fb{border-top:1px solid var(--line);margin-top:18px;padding-top:12px}
.fb button{background:#fff;color:var(--dim);border:1px solid var(--line2)}
.fb button:hover{color:var(--fg);border-color:var(--dim2)}
.fb button[aria-pressed="true"]{color:#fff}
.fb .no[aria-pressed="true"]{background:var(--bad);border-color:var(--bad)}
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


def section(sid: str, title: str, lead: str, body: str, fb_rank: int) -> str:
    return (f'<section id="{sid}"><h2>{esc(title)}</h2>' + (f'<p class="lead">{lead}</p>' if lead else "") + body
            + FB.strip(fb_rank, title, noun="section") + "</section>")


def build() -> str:
    fb_js = FB.JS
    needle = "var out = ['# Feedback \\u2014 ' + REPORT, ''];"
    assert needle in fb_js, "report_feedback.JS changed: re-check how the markdown heading is built"
    fb_js = fb_js.replace(needle, "var out = ['Re: Vibe Tracks live work tracks (2026-10-04)', '', '<sub>' + REPORT + '</sub>', ''];")

    k = TRACK_PAGE["kinsim"]
    rn = FACTS["rename"]
    posts = FACTS.get("posts", [])
    gen = datetime.fromisoformat(PROJ["generated_at"]).strftime("%Y-%m-%d %H:%M") + " PDT"
    star = {tid: TRACK_PAGE[tid]["kpis"][0]["cells"] for tid in ORDER}

    hero = f"""
<figure class="hero">
  <video controls autoplay muted loop playsinline preload="auto" aria-label="Hero: home, Kinematic Sim, roadmap, back, rig, CAN 16, rename">
    <source src="{data_uri(MEDIA / 'hero-live-tracks.mp4', 'video/mp4')}" type="video/mp4"></video>
  <img id="hero-gif" class="gif hidden" alt="Hero as a GIF" src="{data_uri(MEDIA / 'hero-live-tracks.gif', 'image/gif')}">
  <figcaption><b>Home → Kinematic Sim → Roadmap → back → Rig → CAN 16 → rename (24 s, 1.25× speed)</b>
  <span class="cap">Recorded headless from the running lane at http://127.0.0.1:4390 on live data. The blue dot is the pointer.
  The rename at the end was reverted through the ⋯ menu right after the recording; the note came back byte-identical.</span></figcaption>
</figure>"""

    home = (
        '<div class="g1">'
        + fig("01-home.webp", "Home: one row per work track",
              f"{FACTS['home']['header']}. Columns: Status (state word + clamped detail), Progress (north star + sparkline), "
              "Current rung → next (falls back to the current iteration until a roadmap reports), Last moved (the build's "
              "heartbeat, 'stale' past the 24 h stall rule), Needs you (blocking · open; 'not reported' when unknown, never 0). "
              "CAN 12 and CAN 16 are not on this page.")
        + "</div>" + home_rows()
    )

    pages = '<div class="g2">' + "".join(
        fig(f"02-track-{tid}.webp", f"{TRACKS[tid]['title']} · track page",
            f"State: {TRACK_PAGE[tid]['state'].splitlines()[0]}. "
            f"{(TRACK_PAGE[tid]['needs'] or '').replace(' →', '')}. "
            f"North star: {TRACKS[tid]['kpis'][0]['label']} = {next((c for c in reversed(star[tid][1:-3]) if c), '—')}. "
            f"{len(TRACK_PAGE[tid]['kpis'])} KPIs × {len(TRACK_PAGE[tid]['colheads'])} {TRACKS[tid]['iteration']['unit']}s at capture time; "
            "Roadmap section below the scorecard reads 'pending'.")
        for tid in ORDER
    ) + fig("09-can16.webp", "Bench rotor · CAN 16 (a deployment under the rig)",
            "Repeat needed: the held gentle_step · ff_fb condition rests on n = 1 (2.77 → 2.78 → 9.03°), so it reads "
            "'unconfirmed · repeat needed'. Last moved 68 days ago (its own newest session, not the rig loop's minutes). "
            "No roadmap section and no rename for a deployment.") + "</div>"
    pages += "<h3>Section order, measured</h3><p class=\"small dim\">Top of each element in page pixels (getBoundingClientRect + scrollY).</p>" + order_table()

    drill = '<div class="g2">' + "".join([
        fig("03-kinsim-kpis.webp", "Key KPIs: kinsim's scorecard",
            "Waves as columns, W4 emphasised; each column head carries its change marker (ruler pins, landed packages, rungs). "
            "The BT2 cell is orange and the status says the ruler changed, so 37.3 → 41.8 is not read as progress."),
        fig("04-kinsim-roadmap.webp", "Roadmap section, expanded",
            "Expand writes rmopen=1 into the URL. The widget slot renders the stub ('Roadmap widget pending'), then the links "
            "the adapter supplies (Wave 4 report, ROADMAP.md, TRIAGE.md, status.json, runs.jsonl, loop_events.jsonl)."),
        fig("05-kinsim-needs.webp", "Needs you link (the other workflow's page)",
            f"The state line's 'Needs you · 1 blocking · 11 open →' goes to {k.get('needsHash')}. This page belongs to the "
            "concurrent Needs-you workflow; shown only to prove the link lands."),
        fig("06-kinsim-iteration.webp", "L3: the W4 iteration",
            f"Opened from the W4 column head ({k.get('l3hash')}). What changed, then every KPI at W4 with its change vs W3 and "
            "its evidence count."),
        fig("07-kinsim-evidence-bt2.webp", "L3: one evidence item, the BT2 promotion run",
            f"{EV['itemHash']}: 418/1000 feasible under ruler dbb25b0c, the run's batch.json inline, and 'This feeds' back to "
            "the Frontier gate KPI. Back returned to the W4 page."),
        fig("07b-kinsim-wave4-report.webp", "L3: the Wave 4 report, in place",
            "The loop's own HTML report served by the plugin backend (media allowlist) and framed inside the item page."),
        fig("08-rig-deployments.webp", "Rig: Roadmap, then Deployments",
            "The quiet sub-table under the rig: name, state, north star with sparkline, last moved. A row opens that "
            "deployment's own page."),
    ]) + "</div>"
    drill += f"<h3>What kinsim's first KPI rows read</h3><ul class=\"order\">{kinsim_kpi_text()}</ul>"

    rename = f"""
<div class="g2">
{fig("10-rename-editing.webp", "Rename in progress (double-click the name)", "An inline input replaces the name; 'Enter saves · Esc cancels'. F2 or ⋯ → Rename track… open the same editor; the track-page title works too.")}
{fig("11-rename-saved.webp", "Saved: the row reads 'Pyblocks · Block View'", "The id stays pyblocks, so links, the hash route (#vt?track=pyblocks) and every adapter keep working.")}
</div>
<h3>How it works</h3>
<ol class="steps">
  <li>The id is <code>vibe-id</code> in the track's registry note (<code>workspace/tracks/&lt;id&gt;.md</code>) and never changes; the
      display name is <code>vibe-title</code>. Renaming touches only that one line.</li>
  <li>Save posts <code>{{title, revision}}</code> to <code>/api/plugins/vibetracks/tracks/&lt;id&gt;/title</code>; <code>revision</code> is the
      note's hash from the projection. <code>registry.rename_title</code> is the only writer.</li>
  <li>The UI updates optimistically and rolls back on error. A 409 (the note changed elsewhere) shows 'Changed elsewhere, reloaded',
      reloads and keeps your text in the open editor.</li>
  <li>Empty or unchanged saves nothing; over 80 characters or a control character keeps the editor open with an error.
      Deployments have no registry note, so they get no rename and no ⋯ menu.</li>
</ol>
<h3>Verified on the real note</h3>
<ul class="ls">
  <li>Before: <code>vibe-title: {esc(rn['before']['title'])}</code>, <code>vibe-id: {esc(rn['before']['id'])}</code>, sha256 <code>{esc(rn['before']['sha'][:16])}…</code></li>
  <li>After the double-click rename: <code>vibe-title: {esc(rn['after']['title'])}</code>, <code>vibe-id: {esc(rn['after']['id'])}</code>; the home row read '{esc(rn['after']['rowName'])}'.</li>
  <li>After renaming back through ⋯ → Rename track…: title '{esc(rn['restored']['title'])}', sha256 identical to before: <b>{esc(rn['restored']['identical'])}</b>.</li>
  <li>The two requests: {''.join(f'<code class="blk">POST {esc(p)}</code>' for p in posts)}</li>
</ul>"""

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vibe Tracks live tracks</title>
<style>{CSS}{FB.CSS}{FB_LIGHT}</style></head>
<body><div class="wrap">

<header class="top">
  <div class="date">2026-10-04 · integration check</div>
  <h1>Vibe Tracks: your five work tracks, live</h1>
  <p class="verdict">The home page now shows only your five work tracks, all on live loop data. Each track page shows its key KPIs
  and a roadmap section, and you can rename a track while its id stays fixed. The catch: the roadmap section is still a stub on
  every track. The real widget is on an unmerged branch, so 'current rung → next' falls back to the current iteration.</p>
  <p class="built">Drove the running lane headless at {esc(gen)}. {len(CHECKS)} of {len(CHECKS)} KPI values matched when recomputed
  from the loops' own files. Rename round-trip left the note byte-identical. Typecheck clean; 171 of 173 tests pass (2 stale).
  Nothing committed. This page is about 3 MB, so open it in the browser, not the desktop preview.</p>
  <div class="launch"><pre id="launch-cmd">{esc(LAUNCHER)}</pre><button id="copy-launch" type="button">Copy</button></div>
</header>

<nav class="toc" aria-label="Sections">
  <a href="#watch">Watch</a><a href="#home">Home</a><a href="#pages">Track pages</a><a href="#drill">Drill-down</a>
  <a href="#tracks">Per track</a><a href="#checks">Numbers checked</a><a href="#rename">Rename</a><a href="#live">Live vs stale</a>
  <a href="#issues">Issues</a><a href="#decide">Decide</a>
</nav>

{section("watch", "Watch first", "One recorded walk through the real app: pick a track, read its KPIs, open the roadmap section, go back, open the rig and CAN 16, rename a track.", hero, 1)}
{section("home", "Home: the work tracks", "One calm row per top-level track, in registry priority order. It adapts to however many track notes exist, so a sixth track is one new note.", home, 2)}
{section("pages", "Each track page", "Title (renamable) → one state line → Needs you → purpose → Key KPIs → Roadmap. The rig adds its deployments under the roadmap.", pages, 3)}
{section("drill", "Drilling in: KPIs, roadmap, needs, evidence", "Kinsim end to end, then the rig's deployments.", drill, 4)}
{section("tracks", "Per track: sources, freshness, KPIs, roadmap, gaps", f"Read from the projection the backend served at {esc(gen)} (<code>{esc(PROJ_PATH.name)}</code>). File times are local.", track_table(), 5)}
{section("checks", "Numbers checked against the source files", "Each value recomputed by a separate script (<code>crosscheck.py</code> in the media folder) straight from the loop's own files, not from the adapter, then compared with what the dashboard served.", checks_table(), 6)}
{section("rename", "Renaming a track", "", rename, 7)}
{section("live", "What is live, what is stale, and why", "", live_status(), 8)}
{section("issues", "Issues found (not fixed here)", "No product code was changed in this pass (only this report builder was added); these are for their owners.", '<ol class="issues">' + ''.join(f'<li><b>{esc(t)}</b>{inline_md(d)}</li>' for t, d in ISSUES) + '</ol>', 9)}

<section id="decide">
  <h2>Decision surface</h2>
  <div class="decide">{DECISION}</div>
  {FB.ui(REPORT_NAME, noun="section", total=9)}
</section>

<footer class="end">Generated by docs/dashboard/build_live_report.py from the drive's JSON in {esc(MEDIA)}.</footer>
</div>
<div id="lb" role="dialog" aria-modal="true" aria-label="Full-size screenshot"><button type="button">Close (Esc)</button><img alt=""><div class="lbcap"></div></div>
{JS}
{fb_js}
</body></html>"""
    return page


if __name__ == "__main__":
    page = build()
    OUT.write_text(page, encoding="utf-8")
    size = OUT.stat().st_size
    print(f"wrote {OUT}  {size:,} bytes ({size / 1e6:.2f} MB), {len(_inlined)} media inlined once each")
