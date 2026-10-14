"""Build the Oct 9 roadmap report: Vibe Tracks' own plan (features/) as a graph and a table, with where every item came
from, what was dropped, and the track page that now draws it.

    cd ~/vibetracks-roadmap-oct9
    python3 docs/roadmap/build_features_report.py --captures <dir with roadmap-*.png, track-*-top.png, phone-dark.png, measure.json> --out ~/vibetracks/reports/media/vibetracks-roadmap-oct9/index.html

The plan is read the way the track page reads it (``vibetracks.roadmap.projector.features.project_features``), so the
statuses here are the projector's, never retyped. Stills are inlined; the hero video and its GIF sit in ``media/``
beside the page (written by hand with ffmpeg from the headless recording). Stdlib + this package only.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: `python3 -m unittest discover -s tests` on this branch at 976e8ac (main d0b4b5a: 530 run; the same 3 known reds).
TESTS_RUN = 544
sys.path.insert(0, str(ROOT))  # WHY: run as a plain script from any cwd, against this checkout's package

from vibetracks.project import load_project  # noqa: E402
from vibetracks.roadmap.projector.features import project_features  # noqa: E402

# The ten that matter most, in dependency order, and why (the roadmap pass's call; the notes carry the detail).
TEN = [
    ("VT-019", "Green the suite: two one-line bugs in frozen checks plus one old adapter error. Needs your OK to touch the ruler."),
    ("VT-059", "Kincal's 12 MB ledger sits in a sweepable worktree, the way grasping's was lost. Cheap now, expensive later."),
    ("VT-060", "Fivebar and kincal get real KPIs instead of 'no KPI adapter yet'. Lands after the ledger moves."),
    ("VT-010", "Your Oct 9 ask: drag the sidebar edge, one view switcher. Running on the r3 lane."),
    ("VT-011", "Your Oct 9 ask: other sessions listed open, the way Claude shows them."),
    ("VT-068", "The home sees every machine's sessions, the point of merging remote. Running on the r3 lane."),
    ("VT-027", "Pick V1 Inbox to Zen or V3 Zen with bookends. Default V1. Unblocks Review."),
    ("VT-028", "Review on the real questions, in the picked design."),
    ("VT-058", "Write routes from the home: rename, reassign, New project, Board, answers and the phone all wait on it."),
    ("VT-029", "Your answers reach the loops. Today they leave only through Copy."),
]

# Where items came from: (label, test on an item's origin text or id).
SOURCES = [
    ("Repo plan, Aug 25 (features/VT-001…VT-007)", lambda i, o: i in {f"VT-00{n}" for n in range(1, 8)}),
    ("Unmerged wip/vt-008 branch (cef2ff9)", lambda i, o: "wip/vt-008" in o),
    ("Vault: PROJECT - Vibe Tracks (Oct 9 consolidation)", lambda i, o: "PROJECT - Vibe Tracks" in o),
    ("Daily Note Oct 9 (feedback and the round-4 callout)", lambda i, o: "Daily Note - Oct 9" in o or "Daily Note Oct 9" in o),
    ("Earlier daily notes, Oct 3 to Oct 8", lambda i, o: re.search(r"Daily Note - Oct [3-8] ", o) is not None),
    ("The 8 Linear proposals, accepted (Oct 6)", lambda i, o: "linear-proposals" in o),
    ("Linear integration report (Oct 9)", lambda i, o: "linear-integration" in o),
    ("Evo dashboard study, ranked ideas (Oct 6)", lambda i, o: "evo-dashboard-study" in o),
    ("Home proposals, rounds 1-3 (Oct 6)", lambda i, o: "home-proposals" in o),
    ("B1 report leftovers (Oct 9)", lambda i, o: "B1 report" in o or "home-b1" in o),
    ("B2 report leftovers (Oct 9)", lambda i, o: "B2 report" in o),
    ("Review proposals, V1 / V3 pending (Oct 9)", lambda i, o: "review-proposals" in o),
    ("Remote / multi-machine (report, r3 lane, memory)", lambda i, o: any(k in o for k in ("vibetracks-remote", "multi-machine-results", "Across Computers", "(agent 1)"))),
    ("Kincal ledger task (Oct 6 chat) and live-tracks report", lambda i, o: "75d64cb1" in o or "live-tracks" in o),
    ("Other reports (needs-you, one number, dashboard, roadmap, rig)", lambda i, o: any(k in o for k in ("needs-you", "one-number", "vibetracks-dashboard-2026", "vibetracks-roadmap-2026", "rig-track-proposals", "claude/vibetracks-dashboard"))),
]

DROPPED = [
    ("VT-003 Obsidian plugin wrapper", "Archived. The Graph / Kanban / Focus panel it would wrap is no longer the primary surface (Oct 9: the home is), and on the Obsidian side Vibe Kanban was sunset on Sep 29 for stock Bases, which already render these notes."),
    ("Clank's \"Agent work\" dashboard (Proposal A) as the primary surface", "Superseded by the home. Zach, Oct 9: it \"is not the primary vibe tracks\". Open question 2 (keep linking Clank's pages until B2 lands) is moot now that B2 is merged. Its rig page content survives as VT-053."),
    ("Linear #8, Loops", "A note, never cloned by design (Oct 6 report)."),
    ("Linear #7's code-review queue", "Rejected by design: \"I want to manage outcomes not code\". The outcome view is VT-050."),
    ("The flat Linear inbox (Linear #4's list, review V2)", "Rejected Oct 6 (\"that is just another thing for me to consider\"). On Oct 9 Zach asked for an inbox grouped by project instead, which is V1 in VT-027. The age badge is kept (VT-031)."),
    ("Hand-written health / status fields, and an activity.jsonl written by hooks", "Superseded by derived state from Claude Code's own files (VT-054). Hooks stay only as a measured second writer later (VT-064)."),
    ("One KPI per track", "Overruled Oct 6: \"trakcs have multiple KPIs though\"."),
    ("Sparklines in the sidebar; a sidebar shown only after drilling in", "Rejected Oct 6 (\"to messy\"; \"slightly disorientating to have it hide\")."),
    ("Timeline views that need estimates", "Rejected Oct 3: \"requires like estimating timelines\"."),
    ("Syncthing as the v1 sync", "Git was Zach's v1 call (Oct 6). Syncthing or Obsidian Headless stays only as the later swap (VT-075)."),
    ("Open questions answered by later work", "B1 merge (merged in d0b4b5a; only the test fixes remain, VT-019), projects as files with roots (done, VT-035), remote v1 merge (c5ce6b3), the icon (#01 installed, kept)."),
    ("claude/vibetracks-roadmap-r3 (tag archive/vibetracks-roadmap-r3-2026-10-06)", "A duplicate of the merged roadmap lane under other shas; nothing to recover. Not content-diffed. The first citation for VT-057 (3691852) came from that lane, and the projector drew it stale until main's fa91965 replaced it."),
    ("Dot meaning (Claude's real one vs the first brief)", "Not a feature: B2 already follows Claude's meaning, and that is the default (noted on VT-009)."),
]

STATUS_WORD = {"done": "done", "running": "running", "review": "in review", "waiting": "needs you", "ready": "ready",
               "frontier": "ready", "backlog": "backlog"}


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def data_uri(path: Path) -> str:
    kind = "image/png" if path.suffix == ".png" else "image/jpeg"
    return f"data:{kind};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def depth_of(rungs: dict[str, dict]) -> dict[str, int]:
    depth: dict[str, int] = {}

    def visit(rung_id: str) -> int:
        if rung_id not in depth:
            parents = rungs[rung_id]["depends_on"]
            depth[rung_id] = 0 if not parents else 1 + max(visit(parent) for parent in parents)
        return depth[rung_id]

    for rung_id in rungs:
        visit(rung_id)
    return depth


def node_class(rung: dict) -> str:
    status = rung["x"]["vibe_status"]
    if rung["status"] == "done":
        return "n-done"
    if status in ("running", "review"):
        return "n-moving"
    if status == "waiting":
        return "n-waiting"
    if status in ("ready", "frontier"):
        return "n-ready"
    return "n-backlog"


def graph_svg(document: dict) -> str:
    """Lanes as columns (the axes, in order), dependency depth as rows, so 74 features fit one screen's width."""

    rungs = {rung["id"]: rung for rung in document["rungs"]}
    depth = depth_of(rungs)
    rows = max(depth.values()) + 1
    axes = [axis["id"] for axis in document["axes"]]
    node_w, node_h, gap, col_w, head_h, row_pad, left = 146, 22, 5, 156, 44, 12, 52
    cells: dict[tuple[str, int], list[str]] = defaultdict(list)
    for rung in document["rungs"]:
        cells[(rung["axis"], depth[rung["id"]])].append(rung["id"])
    position: dict[str, tuple[float, float]] = {}
    row_top, y = [], float(head_h)
    for row in range(rows):
        stack = max((len(cells[(axis, row)]) for axis in axes), default=0)
        row_top.append((y, stack))
        for column, axis in enumerate(axes):
            for index, rung_id in enumerate(cells[(axis, row)]):
                position[rung_id] = (left + column * col_w + 5, y + row_pad / 2 + index * (node_h + gap))
        y += max(1, stack) * (node_h + gap) + row_pad
    width, height = left + len(axes) * col_w, y
    parts = [f'<svg class="graph" viewBox="0 0 {width} {height:.0f}" width="{width}" height="{height:.0f}" role="img" '
             f'aria-label="Vibe Tracks roadmap: {len(rungs)} features in {len(axes)} lanes, prerequisites above what needs them">']
    for column, axis in enumerate(document["axes"]):
        x0 = left + column * col_w
        parts.append(f'<rect class="lane{" alt" if column % 2 else ""}" x="{x0}" y="0" width="{col_w}" height="{height:.0f}"/>')
        mine = [rung for rung in rungs.values() if rung["axis"] == axis["id"]]
        done = sum(1 for rung in mine if rung["status"] == "done")
        parts.append(f'<text class="lane-t" x="{x0 + 6}" y="18">{esc(axis["title"])}</text>')
        parts.append(f'<text class="lane-s" x="{x0 + 6}" y="33">{done} of {len(mine)} done</text>')
    for row, (top, _stack) in enumerate(row_top):
        parts.append(f'<text class="col-t" x="6" y="{top + row_pad / 2 + 15:.0f}">depth {row}</text>')
        if row:
            parts.append(f'<line class="rowline" x1="0" x2="{width}" y1="{top:.0f}" y2="{top:.0f}"/>')
    for rung_id, rung in rungs.items():
        x2, y2 = position[rung_id]
        for parent in rung["depends_on"]:
            x1, y1 = position[parent]
            sx, sy, ex, ey = x1 + node_w / 2, y1 + node_h, x2 + node_w / 2, y2
            bend = max(14.0, (ey - sy) / 2)
            parts.append(f'<path class="edge" d="M{sx:.0f},{sy:.0f} C{sx:.0f},{sy + bend:.0f} {ex:.0f},{ey - bend:.0f} {ex:.0f},{ey:.0f}"/>')
    for rung_id, rung in rungs.items():
        x, y0 = position[rung_id]
        title = rung["title"]
        short = title if len(title) <= 17 else title[:16].rstrip(" ,") + "…"
        front = " front" if rung["frontier"] else ""
        tip = f'{rung_id} · {title} · {STATUS_WORD.get(rung["x"]["vibe_status"], rung["x"]["vibe_status"])} · {rung["status_reason"]}'
        parts.append(f'<g class="node {node_class(rung)}{front}"><title>{esc(tip)}</title>'
                     f'<rect x="{x}" y="{y0:.0f}" width="{node_w}" height="{node_h}" rx="5"/>'
                     f'<text x="{x + 6}" y="{y0 + 15:.0f}"><tspan class="nid">{rung_id[3:]}</tspan> {esc(short)}</text></g>')
    parts.append("</svg>")
    return "".join(parts)


def item_origins(project, document) -> dict[str, list[str]]:
    from vibetracks.edits import read_note_exact
    from vibetracks.notes import parse_frontmatter, string_list

    out = {}
    for item in project.items:
        meta = parse_frontmatter(read_note_exact(Path(item.absolute_path)))[0]
        out[item.id] = string_list(meta.get("vibe-origin"))
    return out


def link_for(origin: str) -> str:
    text = esc(origin)
    match = re.search(r"(/home/bam/vibetracks/reports/media/\S+?\.html)", origin)
    if match:
        path = match.group(1)
        return text.replace(esc(path), f'<a href="file://{esc(path)}">{esc(path.split("/reports/media/")[1])}</a>')
    return text


def build(captures: Path, out: Path) -> None:
    project = load_project(ROOT / "Project.vibetrack")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    document = project_features(ROOT / "Project.vibetrack", now=now)
    measure = json.loads((captures / "measure.json").read_text(encoding="utf-8"))
    origins = item_origins(project, document)
    items = {item.id: item for item in project.items}
    rungs = {rung["id"]: rung for rung in document["rungs"]}
    archived = [item for item in project.items if item.id not in rungs]
    counts = document["counts"]["by_status"]
    moving = sum(1 for rung in rungs.values() if rung["x"]["vibe_status"] in ("running", "review"))
    waiting = [rung for rung in document["rungs"] if rung["x"]["vibe_status"] == "waiting"]
    new_ids = [i for i in items if int(i[3:]) >= 8]
    head = document["as_of"]

    def chip(rung: dict) -> str:
        word = STATUS_WORD.get(rung["x"]["vibe_status"], rung["x"]["vibe_status"])
        proof = ""
        if rung["status"] == "done":
            proof = " · " + ", ".join(f'<code>{esc(c[:7])}</code>' for c in rung["support"]["commits"])
        return f'<span class="chip {node_class(rung)}">{esc(word)}</span>{proof}'

    # ---------------------------------------------------------------- the table
    table_rows = []
    for axis in document["axes"]:
        mine = [rung for rung in document["rungs"] if rung["axis"] == axis["id"]]
        table_rows.append(f'<tr class="axis-row"><th colspan="4">{esc(axis["title"])} '
                          f'<span class="faint">· {sum(1 for r in mine if r["status"] == "done")} of {len(mine)} done</span></th></tr>')
        for rung in mine:
            deps = ", ".join(rung["depends_on"]) or "—"
            came = "<br>".join(link_for(o) for o in origins.get(rung["id"], [])) or "—"
            star = ' <span class="star" title="on the frontier: unblocked and scheduled">◆</span>' if rung["frontier"] else ""
            table_rows.append(
                f'<tr><td class="id">{rung["id"]}{star}</td>'
                f'<td><b>{esc(rung["title"])}</b><div class="desc">{esc(items[rung["id"]].description)}</div></td>'
                f'<td class="st">{chip(rung)}<div class="faint small">needs {esc(deps)}</div></td>'
                f'<td class="src">{came}</td></tr>')

    # ---------------------------------------------------------------- recovered from where
    source_rows = []
    for label, test in SOURCES:
        hits = [i for i in sorted(items) if test(i, " | ".join(origins.get(i, [])))]
        done = [i for i in hits if i in rungs and rungs[i]["status"] == "done"]
        source_rows.append(f'<tr><td>{esc(label)}</td><td class="num">{len(hits)}</td><td class="num">{len(done)}</td>'
                           f'<td class="ids">{", ".join(hits) or "—"}</td></tr>')

    ten_rows = "".join(
        f'<li><b>{tid} {esc(rungs[tid]["title"])}</b> {chip(rungs[tid])}'
        f'{" · needs " + esc(", ".join(rungs[tid]["depends_on"])) if rungs[tid]["depends_on"] else ""}<div class="desc">{esc(why)}</div></li>'
        for tid, why in TEN)
    waiting_rows = "".join(
        f'<li><b>{r["id"]} {esc(r["title"])}</b><div class="desc">{esc(items[r["id"]].description)}</div></li>' for r in waiting)
    dropped_rows = "".join(f'<li><b>{esc(what)}</b><div class="desc">{esc(why)}</div></li>' for what, why in DROPPED)
    axes_measured = "".join(f'<li>{esc(a["title"])}: {a["rungs"]} rungs · {esc(a["where"])}</li>' for a in measure["dark"]["axes"])

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vibe Tracks Roadmap</title>
<style>
:root {{ --bg:#fbfaf7; --ink:#1d1d1b; --soft:#5d5b55; --faint:#8b887f; --line:#e6e3dc; --card:#ffffff; --lane:#f6f4ef;
  --done:#2f8f5b; --moving:#2f6fd6; --waiting:#c27a12; --ready:#2f6fd6; --backlog:#b9b5ab; --edge:#c9c5bb; --code:#f0eee8; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#171716; --ink:#ecebe7; --soft:#b5b2aa;
  --faint:#85827a; --line:#2c2b29; --card:#1f1f1d; --lane:#1b1b1a; --done:#5fbf86; --moving:#6ea2ff; --waiting:#e3a23f;
  --ready:#6ea2ff; --backlog:#5d5a54; --edge:#45433f; --code:#2a2927; }} }}
:root[data-theme="dark"] {{ --bg:#171716; --ink:#ecebe7; --soft:#b5b2aa; --faint:#85827a; --line:#2c2b29; --card:#1f1f1d;
  --lane:#1b1b1a; --done:#5fbf86; --moving:#6ea2ff; --waiting:#e3a23f; --ready:#6ea2ff; --backlog:#5d5a54; --edge:#45433f; --code:#2a2927; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:28px 16px 80px; }}
h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:-0.01em; }}
h2 {{ font-size:18px; margin:40px 0 10px; }}
p {{ margin:8px 0; }} .faint {{ color:var(--faint); }} .small {{ font-size:12px; }}
.verdict {{ font-size:17px; margin:10px 0 4px; }}
code {{ background:var(--code); padding:1px 5px; border-radius:4px; font-size:12.5px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
@media (max-width:760px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
figure {{ margin:0; }} figcaption {{ color:var(--faint); font-size:12.5px; margin-top:6px; }}
img, video {{ max-width:100%; height:auto; border-radius:8px; border:1px solid var(--line); display:block; }}
.kpis {{ display:flex; flex-wrap:wrap; gap:10px; margin:14px 0; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; min-width:120px; }}
.kpi b {{ font-size:22px; display:block; }} .kpi span {{ color:var(--faint); font-size:12.5px; }}
ol.ten, ul.list {{ padding-left:20px; }} ol.ten li, ul.list li {{ margin:8px 0; }}
.desc {{ color:var(--soft); font-size:13.5px; }}
.chip {{ display:inline-block; font-size:11.5px; padding:0 7px; border-radius:9px; border:1px solid currentColor; margin-left:4px; }}
.chip.n-done {{ color:var(--done); }} .chip.n-moving {{ color:var(--moving); }} .chip.n-waiting {{ color:var(--waiting); }}
.chip.n-ready {{ color:var(--ready); }} .chip.n-backlog {{ color:var(--faint); }}
.scroll {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--card); }}
svg.graph {{ display:block; width:100%; height:auto; min-width:900px; font:12px ui-sans-serif, system-ui, sans-serif; }}
svg .lane {{ fill:var(--card); }} svg .lane.alt {{ fill:var(--lane); }}
svg .lane-t {{ fill:var(--ink); font-weight:600; font-size:13px; }} svg .lane-s, svg .col-t {{ fill:var(--faint); font-size:11px; }}
svg .rowline {{ stroke:var(--line); stroke-dasharray:2 4; }}
svg .edge {{ fill:none; stroke:var(--edge); stroke-width:1.2; }}
svg .node rect {{ fill:var(--card); stroke:var(--backlog); stroke-width:1.2; }}
svg .node text {{ fill:var(--ink); }} svg .node .nid {{ fill:var(--faint); font-weight:600; }}
svg .n-done rect {{ fill:var(--done); stroke:var(--done); }} svg .n-done text, svg .n-done .nid {{ fill:#fff; }}
svg .n-moving rect {{ stroke:var(--moving); stroke-width:2; }} svg .n-waiting rect {{ stroke:var(--waiting); stroke-width:2; stroke-dasharray:4 2; }}
svg .n-ready rect {{ stroke:var(--ready); }} svg .n-backlog text {{ fill:var(--soft); }}
svg .front rect {{ stroke-width:2.6; }}
.legend {{ display:flex; flex-wrap:wrap; gap:14px; font-size:12.5px; color:var(--soft); margin:8px 0; }}
.legend i {{ display:inline-block; width:14px; height:10px; border-radius:3px; margin-right:5px; vertical-align:middle; border:1.5px solid var(--backlog); }}
.legend .l-done {{ background:var(--done); border-color:var(--done); }} .legend .l-moving {{ border-color:var(--moving); border-width:2px; }}
.legend .l-waiting {{ border-color:var(--waiting); border-style:dashed; }} .legend .l-ready {{ border-color:var(--ready); }}
table {{ border-collapse:collapse; width:100%; font-size:13.5px; }}
th, td {{ text-align:left; vertical-align:top; padding:7px 8px; border-bottom:1px solid var(--line); }}
tr.axis-row th {{ background:var(--lane); font-size:14px; padding-top:12px; }}
td.id {{ white-space:nowrap; font-weight:600; }} td.st {{ white-space:nowrap; }} td.src {{ font-size:12px; color:var(--soft); max-width:360px; }}
td.num {{ text-align:right; width:52px; }} td.ids {{ font-size:12px; color:var(--soft); }}
.star {{ color:var(--moving); font-size:11px; }}
a {{ color:var(--moving); }}
details > summary {{ cursor:pointer; color:var(--soft); }}
@media (max-width:760px) {{ td.src {{ display:none; }} }}
</style></head><body><main>
<p class="faint small">Vibe Tracks · roadmap pass · {esc(now[:10])} · branch <code>{esc(head["branch"])}</code> @ <code>{esc(head["head"][:7])}</code>, not merged</p>
<h1>Vibe Tracks' roadmap is back, and its track page draws it</h1>
<p class="verdict"><b>{len(rungs)} features on the Vibe Tracks track page: {counts["done"]} done (each proven by commits in this history), {moving} in hand, {len(rungs) - counts["done"] - moving} open; {len(archived)} archived.</b>
On <code>claude/vibetracks-roadmap-oct9</code>, not merged. Stable (4394) still says "no roadmap" until this merges and Stable is promoted.</p>
<div class="kpis">
<div class="kpi"><b>{len(new_ids)}</b><span>new notes, VT-008 to VT-{max(int(i[3:]) for i in items):03d}</span></div>
<div class="kpi"><b>{counts["done"]}</b><span>done, proven by commits</span></div>
<div class="kpi"><b>{moving}</b><span>running or in review</span></div>
<div class="kpi"><b>{len(waiting)}</b><span>need you (waiting)</span></div>
<div class="kpi"><b>{len(document["summary"]["frontier"])}</b><span>on the frontier</span></div>
<div class="kpi"><b>{TESTS_RUN}</b><span>tests run, same 3 known reds</span></div>
</div>

<h2>The track page, on a scratch Stable built from the branch</h2>
<figure><video autoplay muted loop playsinline controls src="media/hero.mp4" poster="{data_uri(captures / 'roadmap-dark.png')}"><img src="media/hero.gif" alt="Home, then the Vibe Tracks track, then its roadmap"></video>
<figcaption>Recorded headless from the real page (scratch Stable on :4486, release built from <code>{esc(head["head"][:7])}</code>): home, the Vibe Tracks track, scroll to its rung ladder, hover the frontier. <a href="media/hero.gif">GIF fallback</a>.</figcaption></figure>
<div class="grid2" style="margin-top:14px">
<figure><img src="{data_uri(captures / 'roadmap-dark.png')}" alt="Roadmap card, dark"><figcaption>Dark. {measure["dark"]["rungs"]} rungs measured in the DOM ({esc(json.dumps(measure["dark"]["by_status"]))}), {measure["dark"]["frontier"]} on the frontier, no page errors.</figcaption></figure>
<figure><img src="{data_uri(captures / 'roadmap-light.png')}" alt="Roadmap card, light"><figcaption>Light, same counts.</figcaption></figure>
</div>
<div class="grid2" style="margin-top:14px">
<figure><img src="{data_uri(captures / 'track-dark-top.png')}" alt="Vibe Tracks track page"><figcaption>The whole Overview tab: no KPI adapter yet, so the roadmap is the substance.</figcaption></figure>
<figure><img src="{data_uri(captures / 'phone-dark.png')}" alt="Phone width" style="max-width:260px"><figcaption>390 px: page scroll width {measure["phone"]["scrollW"]} = viewport {measure["phone"]["innerW"]}, no sideways scroll.</figcaption></figure>
</div>
<details><summary>Per-axis rows as measured in the page</summary><ul class="list">{axes_measured}</ul></details>

<h2>The ten that matter most, in dependency order</h2>
<ol class="ten">{ten_rows}</ol>

<h2>Needs you</h2>
<p class="desc">Each is a <code>waiting</code> note; its body carries the recommendation and the default that holds if you say nothing.</p>
<ul class="list">{waiting_rows}</ul>

<h2>The roadmap as a graph</h2>
<p class="desc">Columns are your five areas plus Data / Backend and Multi-machine; top to bottom is dependency depth, so every prerequisite sits above what needs it. Hover a box for its full title, status and why.</p>
<div class="legend"><span><i class="l-done"></i>done (proven)</span><span><i class="l-moving"></i>running / in review</span><span><i class="l-waiting"></i>needs you</span><span><i class="l-ready"></i>ready</span><span><i></i>backlog</span><span>thick border = frontier</span></div>
<div class="scroll">{graph_svg(document)}</div>

<h2>The roadmap as a table, with where each item came from</h2>
<div class="scroll"><table>{"".join(table_rows)}</table></div>
<p class="faint small">Archived and not drawn: {", ".join(f"{i.id} {esc(i.title)}" for i in archived) or "none"}.</p>

<h2>What was recovered from where</h2>
<div class="scroll"><table><tr><th>Source</th><th class="num">items</th><th class="num">done</th><th>ids</th></tr>{"".join(source_rows)}</table></div>
<p class="desc">An item can come from several sources. The <code>vibe-origin</code> list in each note is the record.</p>

<h2>Dropped as superseded, and why</h2>
<ul class="list">{dropped_rows}</ul>

<h2>How the track page gets it</h2>
<ul class="list">
<li><b>Why it said "no roadmap".</b> The vibetracks track is a home-only activity note, not a work-track registry row, and once a registry exists only its rows could name a projector; no projector read feature notes either.</li>
<li><b>The projector.</b> <code>vibetracks/roadmap/projector/features.py</code> turns <code>Project.vibetrack</code> + <code>features/*.md</code> into the same bam-roadmap/1 document the loops produce. Axes come from <code>vibetracks.roadmap.axes</code>; a done note is drawn done only when every commit in its <code>vibe-commits</code> is in the checkout's history (otherwise claimed, or stale for a known unmerged commit). It caught one wrong citation on the way.</li>
<li><b>The hookup.</b> <code>/roadmap/doc</code> also reads <code>vibe-roadmap</code> from an activity note (a work track of the same id wins), and the vibetracks note declares <code>{{projector: features, sources: {{features_project_dir: vibetracks_project_dir}}}}</code>. One source key, <code>vibetracks_project_dir</code> = <code>~/vibetracks</code>, because Stable runs from a snapshot with no <code>.git</code>.</li>
<li><b>Tests.</b> 14 new (<code>tests/test_roadmap_features.py</code>); the pinned projector table in <code>tests/test_roadmap_api_r2.py</code> gains <code>features</code> (the one ruler touched). Full suite: {TESTS_RUN} run (main: 530), the same 3 known reds as main; the projector's own pytest suite 292 passed.</li>
</ul>
<p class="faint small">Built by <code>docs/roadmap/build_features_report.py</code> at {esc(now)} from the plan at {esc(head["head"][:7])}.</p>
</main></body></html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(out, f"{out.stat().st_size / 1024:.0f} KB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    build(arguments.captures, arguments.out.expanduser())


if __name__ == "__main__":
    main()
