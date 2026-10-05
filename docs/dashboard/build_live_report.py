#!/usr/bin/env python3
"""Build the integration report for the LIVE Vibe Tracks dashboard (variant A, five work tracks).

    python3 /home/bam/vibetracks-dashboard/docs/dashboard/build_live_report.py

Writes ONE self-contained file:
    /home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04.html

Inputs (all in MEDIA, written by the headless drive; none of them is hand-typed here):
    drive-facts.json        what the real lane showed: home rows, each track page's state, order and KPI rows, rename
    evidence-facts.json     the L3 evidence item, the wave-4 report, CAN 16 and the rig's deployments
    source-checks.json      KPIs recomputed straight from each loop's own files vs what the projection shows
    fixwave-facts.json      the fix-wave verifier's measurements (verify-fixwave.mjs): rung cells, purposes, labels,
                            headers, switcher rects, the reload fan-out, the detection scroll positions
    timescan-facts.json     every clock time on the home, iteration and item pages without a zone, or in UTC
    timescan-after.json     the times lane's after-scan (79 pages); verify-2/times-verify2.json the verifier's own
    projection-*.json       the projection the backend served at check time (sources, freshness, roadmap declaration)
    *.webp / hero-live-tracks.mp4 / .gif   the captures
    r6-report/              round 6: the 04:35 re-capture of home and kinsim (shoot-r6.mjs + its JSON) and the
                            headless render check of both reports (render-reports.mjs)
    <needs media>/r6/round6-fixes.json   round 6's six items, verify-7's evidence and the still-open probes (shared)

WHY the per-track table and the check table are read from JSON: a hand-typed number in a report outlives the data
it describes; these files are the drive's own output, so a re-drive refreshes the report.
WHY every capture is inlined exactly once: Zach reviews by reading, from any device; the lightbox re-uses the
clicked <img>'s src at runtime instead of a second copy. The page is ~3 MB, past the desktop preview's ~1.9 MB cap,
so it is browser-only (the handoff says so) and lives in the gitignored reports/media/ half.
"""
from __future__ import annotations

import base64
import html
import io
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from PIL import Image

MEDIA = Path("/home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04")
FB_DIR = Path("/home/bam/vibetracks/reports/media/dashboard-prior-art-2026-10-03")
OUT = Path("/home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04.html")
REPORT_NAME = OUT.name
LAUNCHER = "/home/bam/vibetracks-dashboard/scripts/open-dashboard"

sys.path.insert(0, str(FB_DIR))
import report_feedback as FB  # noqa: E402

FACTS = json.loads((MEDIA / "drive-facts.json").read_text())
FW = json.loads((MEDIA / "fixwave-facts.json").read_text())
TS = json.loads((MEDIA / "timescan-facts.json").read_text())
TS_AFTER = json.loads((MEDIA / "timescan-after.json").read_text())
TS_V2 = json.loads((MEDIA / "verify-2" / "times-verify2.json").read_text())
assert TS_AFTER["pass"] and TS_AFTER["totals"]["bad"] == 0 and TS_AFTER["totals"]["forbidden"] == 0, "times after-scan is not clean"
NEEDS_MEDIA = Path("/home/bam/vibetracks/reports/media/vibetracks-needs-you-2026-10-04")
NEEDS_REPORT = "/home/bam/vibetracks/reports/media/vibetracks-needs-you-2026-10-04.html"
NEEDS_COUNTS = json.loads((NEEDS_MEDIA / "verify-2" / "counts.json").read_text())
EV = json.loads((MEDIA / "evidence-facts.json").read_text())
# Fix wave 3, re-checked by verify-3 (an independent pass that changed no product code).
V3_COUNTS = json.loads((NEEDS_MEDIA / "verify-3" / "v3-counts.json").read_text())
V3_OVERLAP = json.loads((NEEDS_MEDIA / "verify-3" / "v3-overlap.json").read_text())
V3_PAGE_RUNS = {r["name"]: r for r in V3_OVERLAP["runs"] if r["name"] == "home" or r["name"].startswith("track-")}
CHECKS = json.loads((MEDIA / "source-checks.json").read_text())
# Round 3 (verify-4, measure-only): the frame/review-bar scan, its mutation run, the time scan and the bench oracle.
V4_DIR = NEEDS_MEDIA / "verify-4"
V4 = json.loads((V4_DIR / "v4-frame.json").read_text())
V4_MUT = json.loads((V4_DIR / "v4-mutation.json").read_text())
V4_STATES = [r[k] for r in V4["frame"] for k in ("rest", "max") if k in r]
V4_HITS = sum(st["hitCount"] for st in V4_STATES)
V4_SEAMS = sorted({st["seam"] for st in V4_STATES})
# The dashboard-formatted hover titles that still carry a raw ISO stamp, from verify-4's scan (variant A only).
V4_ISO_TITLES = sorted({(h["text"], h["ctx"].split("<")[0]) for t in V4["times"] for h in t["hits"]
                        if h["where"] == "title" and h["kind"] == "iso" and "vt-a" in h["ctx"]})
ORACLE_V4 = json.loads((MEDIA / "verify-4" / "bench-oracle.json").read_text())
# Round 3's build-time pair (projection + the bench's own gallery, 23:39-23:45), kept so the history row stays true.
ORACLE_R3 = json.loads((MEDIA / "verify-4" / "oracle-at-build.json").read_text())
R3_PROJ = json.loads((MEDIA / ORACLE_R3["projection"]).read_text())
# Round 4: re-read 10-05 01:31 after the Codex fixes (r5-report/oracle.py, the bench's venv, VIRTUAL_ENV unset).
ORACLE_NOW = json.loads((MEDIA / "r5-report" / "oracle-at-build.json").read_text())
HOVER_SCAN = json.loads((MEDIA / "r5-report" / "hover-iso-scan.json").read_text())
assert HOVER_SCAN["pass"] and not HOVER_SCAN["pageErrors"], "the hover-title scan found a raw ISO stamp or a page error"
OLD_PROJ = json.loads((MEDIA / "projection-2026-10-04T2055.json").read_text())
PROJ_PATH = sorted(MEDIA.glob("projection-*.json"))[-1]
PROJ = json.loads(PROJ_PATH.read_text())
TRACKS = {t["id"]: t for t in PROJ["tracks"]}
OLD_GRASP = next(t for t in OLD_PROJ["tracks"] if t["id"] == "grasping")


def _latest(kpi: dict) -> dict:
    return kpi["values"][-1]


G_STAR = _latest(TRACKS["grasping"]["kpis"][0])
G_STAR_OLD = _latest(OLD_GRASP["kpis"][0])
G_STAR_R3 = _latest(next(t for t in R3_PROJ["tracks"] if t["id"] == "grasping")["kpis"][0])
assert G_STAR_R3["value"] == len(ORACLE_R3["beaten"]), (G_STAR_R3, ORACLE_R3["beaten"])
# WHY these asserts: the report's lead is "the dashboard now shows the bench's own verdict". If the projection used
# here and the bench's own gallery (run at build time, in its own venv) disagree, that lead is false and must not ship.
assert ORACLE_NOW["projection"] == PROJ_PATH.name, "the build-time oracle was run against a different projection"
assert G_STAR["value"] == len(ORACLE_NOW["beaten"]), (G_STAR, ORACLE_NOW["beaten"])
assert G_STAR["note"].startswith("beaten: " + ", ".join(e.split("/")[1] for e in ORACLE_NOW["beaten"])), G_STAR["note"]
assert TRACKS["grasping"]["source"]["bench_verdict"]["ok"] and not TRACKS["grasping"]["source"].get("problems")
ORDER = [row["id"] for row in FACTS["home"]["rows"]]
assert ORDER == ["kinsim", "rig", "grasping", "detection", "pyblocks"], f"home rows changed: {ORDER}"
assert FACTS["rename"]["restored"]["identical"], "the rename-back did not restore the note byte-for-byte"
assert all(c["match"] for c in CHECKS), "a source check disagrees with the projection: read source-checks.json"

# ---- the independent audit (Codex round 1) ----------------------------------------------------------------------
# WHY parsed from the audit file and a JSON beside the captures: severity and title are Codex's words, the evidence is
# the verifier's; a hand-typed table would outlive either. The Needs-you report renders the same rows from the same files.
AUDIT_FILE = Path("/home/bam/vibetracks/reports/media/audits/2026-10-04-vibetracks-live-needs-r1.md")
AUDIT = json.loads((NEEDS_MEDIA / "audit-r1-fixes.json").read_text())
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
# WHY the same files as the Needs-you report: Codex's status words, severities and titles are parsed from its own file,
# the evidence is verify-6's JSON beside the captures, so the two reports cannot tell the round differently.
AUDIT2_FILE = Path("/home/bam/vibetracks/reports/media/audits/2026-10-05-vibetracks-live-needs-r2.md")
AUDIT2 = json.loads((NEEDS_MEDIA / "audit-r2-fixes.json").read_text())
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

# ---- round 6: verify-6's siblings and leftovers, closed and re-measured by verify-7 -----------------------------
# WHY the needs report's data file: both reports render the same six rows and the same open list from verify-7's words.
R6 = json.loads((NEEDS_MEDIA / "r6" / "round6-fixes.json").read_text())
R6_ITEMS = R6["items"]
assert [i["n"] for i in R6_ITEMS] == ["1", "2", "3", "4", "5", "6"], "round 6's item list changed: re-read the verdict"
R6_PASS = sum(1 for i in R6_ITEMS if i["pass"] is True)
assert (R6_PASS, sum(1 for i in R6_ITEMS if i["pass"] == "partly")) == (5, 1)
R6_SHOTS = json.loads((MEDIA / "r6-report" / "shoot-r6.json").read_text())
# WHY assert the re-capture's own measurements: the captions below say there is no switcher and no review-bar height on
# these pages; if a re-shoot ever finds one, the caption would be false, so the build stops instead.
assert all(sh["switchers"] == 0 and sh["dataVariant"] is None and not sh["abcText"] and sh["barH"] == 0 and sh["sideways"] == 0
           for sh in R6_SHOTS["shots"]), R6_SHOTS["shots"]
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
    """Refuse to build if a tree no longer shows an item the page calls open (same probes as the needs report).
    WHY: a stale 'still open' is as untrue as a stale 'fixed'; each probe names the exact text that makes the claim true.
    WHY `at`: round 6's 'still open' lines describe the tree Codex round 3 read (56c75c0), and most were closed in
    e0bd8e5 since; the page says so beside each, so those probes check the commit they describe, while this round's
    open list is checked against the working tree. `closed` lists round-6 claims the 56c75c0 commit itself closed."""
    where = at or "the working tree"
    for probe in probes:
        text = _probe_text(probe, at)
        if probe["claim"] in closed:
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


# WHY AUDIT3 is read here: it records which of round 6's open claims the 56c75c0 commit closed (and round 3's own rows).
AUDIT3 = json.loads((NEEDS_MEDIA / "r7" / "audit-r3-fixes.json").read_text())
R6_PROBES = check_open_probes(R6["open_probes"], at=R6_TREE, closed=frozenset(AUDIT3["r6_closed_by_commit"]))

# ---- media -----------------------------------------------------------------------------------------------------
_inlined: set[str] = set()


def data_uri(path: Path, mime: str) -> str:
    key = str(path)
    assert key not in _inlined, f"would inline twice: {path}"
    _inlined.add(key)
    if mime == "image/png":
        # WHY: the headless captures are PNG at ~150 KB each; WebP in memory is about a third of that and nothing is
        # written next to the capture.
        buf = io.BytesIO()
        with Image.open(path) as image:
            image.convert("RGB").save(buf, "WEBP", quality=80, method=6)
        return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def inline_md(s: str) -> str:
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


MIME = {".webp": "image/webp", ".png": "image/png", ".gif": "image/gif"}


def fig(name: str, label: str, cap: str, cls: str = "") -> str:
    """A still with a two-tier caption: bold label (what it is), then the dim line (what to notice)."""
    alt = f"{label}"
    path = Path(name) if name.startswith("/") else MEDIA / name
    with Image.open(path) as image:  # WHY the real size: the fix-wave crops are not 1440x900
        width, height = image.size
    return (
        f'<figure class="cell {cls}"><button class="zoom" type="button" aria-label="Open {esc(alt)} full size">'
        f'<img width="{width}" height="{height}" alt="{esc(alt)}" src="{data_uri(path, MIME[path.suffix])}"></button>'
        f'<figcaption><b>{inline_md(label)}</b><span class="cap">{inline_md(cap)}</span></figcaption></figure>'
    )


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "—"
    # WHY astimezone + %Z: the report holds itself to the dashboard's rule, local time with its zone name.
    return datetime.fromisoformat(iso).astimezone().strftime("%m-%d %H:%M %Z")


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
        "Fix wave: triage.json, ROADMAP.md, the run cache (watched two levels deep) and the audits folder are now declared; nothing else is opened.",
        "kpis_session/kpis_day fixtures are frozen at 10-02 23:13 and miss twin V1-f2308e5f (filled from deployments.json + the run cache).",
        "Tick 2 has no events and tick 4 no wave_started row; 6 package landings and 2 greens are placed by ladder.json times.",
        "Everything lives on the unmerged worktree rig-loop-work-continue-cb3c52.",
    ],
    "grasping": [
        "Beaten / provisional envs, headline runs, frozen and privileged flags, and the frontier tier come from the bench's own "
        "gallery.py, run in the bench's venv by grasp_bench_bridge.py (round 3). No copy of its rules is left in the adapter.",
        "The ledger lives in the gitignored out/ of agent worktree grasping-agent-roadmap-ab12d8; a sweep turns the row 'not reporting'.",
        "If the bench cannot answer, the north star and six verdict KPIs are null with the reason, never a guess; seed_rule and "
        "dirty_share still count raw ledger fields the bench does not judge. The bridge calls the bench's private `gallery._run_privileged`.",
        "The 1 s latency limit comes from Zach's deck, not curriculum.py; sim latency excludes camera capture.",
    ],
    "detection": [
        "Fix wave: ladder_data.py, compile_results.py, per-run logs, wandb/, the queue script, the plan note and the reports folder are now declared; with nothing declared it opens nothing.",
        "Rung status is not stored as data anywhere, so there is no 'rungs green' KPI; the frontier is derived (H1 2 of 12).",
        "Needs-you reflects the 10-04 plan note; the Windows answer in the daily note is not read.",
        "ladder_data.py is untracked in a worktree and could be lost to a sweep or stash -u.",
    ],
    "pyblocks": [
        "The loop writes no status file and no questions: needs-you is 'not reported', never 0.",
        "The INT stop (account limit, reset 10-06 08:00 PDT) is a dated constant attributed to the 10-04 discovery; it drops itself when a newer window lands.",
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
            + "<br><span class=\"warnt\">widget not rendered: a stub in this lane, /roadmap answers 404</span>"
            + (f"<br>rung shown from <code>track.rung</code>: {esc(t['rung']['current'])}" if t.get("rung") else ""))


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


def _now(c: dict) -> str:
    """What the projection used for this report shows now; numbers only, never re-derived from the source here."""
    kpi = next((k for k in TRACKS[c["track"]]["kpis"] if k["label"] == c["kpi"]), None)
    now = _latest(kpi)["value"] if kpi else None
    try:
        shown = float(c["shown"])
    except (TypeError, ValueError):
        shown = None
    if shown is None or now is None or c["kpi"].endswith("per finished run"):
        return '<span class="dim">not compared</span>'
    if abs(shown - float(now)) < 1e-9:
        return '<span class="dim">same</span>'
    return f'<b class="warnt">{esc(now)}</b><span class="dim blk">moved: the ledger grew</span>'


def checks_table() -> str:
    rows = "".join(
        f'<tr><td>{esc(TRACKS[c["track"]]["title"])}</td><td>{esc(c["kpi"])}</td>'
        f'<td class="num">{esc(c["shown"])}</td><td class="num">{esc(c["recomputed"])}</td>'
        f'<td><code>{esc(c["source"])}</code><span class="dim blk">{esc(c["how"])}</span></td>'
        f'<td class="{"okt" if c["match"] else "badt"}">{"match" if c["match"] else "MISMATCH"}</td>'
        f'<td class="num">{_now(c)}</td></tr>'
        for c in CHECKS
    )
    return ('<div class="tablewrap"><table class="grid"><thead><tr><th>Track</th><th>KPI</th><th>Dashboard showed (first drive)</th>'
            '<th>Recomputed from source</th><th>Source file · how</th><th></th><th>Projection now</th></tr></thead><tbody>' + rows
            + "</tbody></table></div>")


def home_rows() -> str:
    out = []
    for row in FACTS["home"]["rows"]:
        name, status, progress, rung, moved, needs = row["cells"][:6]
        out.append(f"<tr><th>{esc(name)}</th><td>{esc(status)}</td><td>{esc(progress)}</td><td>{esc(rung)}</td>"
                   f"<td>{esc(moved)}</td><td>{esc(needs)}</td></tr>")
    return ('<details class="raw"><summary>The home rows as the first drive read them (text, 20:55; grasping and the Needs-you counts have changed since)</summary><div class="tablewrap">'
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


def _fix_rows() -> list[tuple[str, str, bool, str]]:
    """(id, issue, fixed, measured evidence) for the nine findings of the integration check, read from the verifier's JSON."""
    home = {r["id"]: r for r in FW["home"]}
    pages = FW["pages"]
    g = home["grasping"]
    rung_src = ", ".join(f"{tid} {home[tid]['rungSource']}" for tid in ORDER)
    utc_lines = [tid for tid, f in pages.items() if f["times"]["text"]["utc"]]
    offset_lines = [tid for tid, f in pages.items() if any("−07:00" in b for b in f["times"]["text"]["bare"])]
    # Only the page's own evidence timestamps ("2026-10-05 03:28"); times inside quoted loop prose are the loop's words.
    l3_bare = sum(1 for k, v in TS.items() if "/" in k for b in v["text"]["bare"] if re.search(r"20\d\d-\d\d-\d\d \d\d:\d\d", b))
    tog = FW["toggle"]["rig"]
    t900 = FW["toggleAt900"]
    purp = ", ".join(f"{tid} {pages[tid]['purpose']['len']}" for tid in ORDER)
    repeats = sum(len(f["labelRepeats"]) for f in pages.values())
    cut = sum(len(f["headCut"]) for f in pages.values())
    cut_ok = all(h["shown"].endswith("…") and h["title"] for f in pages.values() for h in f["headCut"])
    det = FW["detectionScroll"]
    left_cut = sum(len(d["leftCut"]) for d in det)
    positions = sorted({d["scrollLeft"] for d in det})
    over = {k: v["overlap"] for k, v in pages.items()}
    over["home"] = FW["overlap"]["home"]
    hits = [k for k, v in over.items() if v["lastRowHits"] or v["anyContentHits"]]
    rl = FW["reload"]
    return [
        ("a", "Grasping's home row contradicted itself; rung cell showed the newest phase", g["rung"].startswith(g["status"].split(" 30 of")[0]),
         f"Grasping: status '{g['status'].split(' 30 of')[0]}', rung '{g['rung']}'. Rung cell source per row: {rung_src} "
         "(pyblocks has no rung and says 'latest wave: v5-#10 · b07c38b · no roadmap declared')."),
        ("b", "Every human-facing time in local time with a zone", TS_AFTER["pass"],
         f"Fixed in fix wave 2. One shared formatter (local time + zone name, raw ISO on hover) replaced columns.ts formatSince and the "
         f"slice(0,16) in EvidenceList, ItemPage, B's Drawer and snapshot line, C's detail and N1-N5. The times lane's scan: "
         f"{TS_AFTER['totals']['pages']} pages, {TS_AFTER['totals']['clocks']} clocks, {TS_AFTER['totals']['bad']} bad, "
         f"{TS_AFTER['totals']['forbidden']} UTC/offset; {TS_AFTER['totals']['verbatimInLoopProse']} zoneless clocks are the loops' own prose, "
         f"each found in the source data. The verifier's independent scan: {TS_V2['tot']['clocks']} clocks, {TS_V2['tot']['ok']} 'PDT'; "
         f"the rest ({TS_V2['tot']['verbatim']} prose, {TS_V2['tot']['zoneless']} 'UPDATE 17:15' headers, {TS_V2['tot']['bad']} 'at 14:54 UTC' and "
         f"{TS_V2['tot']['iso']} raw ISO) are the loops' words, shown verbatim. Kinsim's line now reads 'since 10-04 17:55 PDT'; grasping's runs '10-04 20:28 PDT'."),
        ("c", "Purpose whole in the projection, clamped to 3 lines with more/less", True,
         f"Purposes {purp} characters, identical to the rendered text. Rig at 1440: {tog['closed']['lines']} lines + '{tog['closed']['toggle']}' "
         f"→ {tog['open']['lines']} lines + '{tog['open']['toggle']}' (aria-expanded {tog['open']['expanded']}) → back to {tog['closedAgain']['lines']}. "
         f"At 900 px kinsim and pyblocks grow the toggle too ({t900['kinsim']['toggle']}, {t900['pyblocks']['toggle']})."),
        ("d", "No KPI label repeats its group header", repeats == 0,
         f"{repeats} repeats across the 5 track pages and CAN 12 / CAN 16, read from the rendered group rows."),
        ("e", "Scorecard headers: visible ellipsis + title; no clipped header when Detection scrolls", cut_ok and left_cut == 0,
         f"{cut} cut markers, every one ends in '…' with the whole marker in its title. Detection at scrollLeft {positions}: "
         f"{left_cut} headers cut at the sticky KPI column (getBoundingClientRect)."),
        ("f", "Switcher no longer covers the last row at max scroll", not hits,
         "At max scroll the switcher (" + ", ".join(map(str, over["home"]["switcher"])) + ") intersects nothing on home or any of the "
         f"7 track pages; home's last row ends at y {over['home']['lastRow'][3]}, kinsim's at {over['kinsim']['lastRow'][3]}."),
        ("g", "Reload also reloads the roadmap", rl["roadmapReloadCalls"] == rl["rowsMounted"],
         f"The stub's reload() was patched in flight to count calls: one Reload click = {rl['projectionRequests']} projection request + "
         f"{rl['roadmapReloadCalls']} roadmap reload() calls ({rl['rowsMounted']} rows mounted). No /roadmap network request, because the stub fetches nothing."),
        ("h", "Two stale tests updated, not deleted", True,
         "test_stub_adapters_… became test_real_adapters_with_nothing_declared_… (asserts not reporting, the missing input named, no numbers, "
         "needs null); the snapshot-children test split into 'drawn live' and 'a child no adapter draws falls back to the snapshot'. Both stronger."),
        ("i", "Every file an adapter reads is declared in its note", True,
         "READS equals vibe-sources key for key on all five; an audit hook over every open/listdir finds nothing outside the declared paths. "
         "Re-run here: dropping any one key is caught except 3 keys nested inside another declared folder (grasping_out_dir, "
         "detection_queue_log, pyblocks_windows), as the lane reported. bam_loops still reads its frozen snapshot, which is not a track adapter."),
        ("j", "Needs-you counts: the cell agrees with the page it opens", _needs_one_source(),
         "needs.py is now the only source: the projection's needs_you_count is {open: wants_you, blocking: blocking_now} of the doc /needs "
         "serves. Measured by the verifier: " + "; ".join(f"{t} '{c}'" for t, c in _home_cells().items())
         + ". In fix wave 3 every proposal's header reads the same two numbers: the verifier matched 48 of 48 needs pages "
         "(N1-N6 × 7 tracks + every-track) against /needs. Detail in the Needs-you report, " + NEEDS_REPORT + "."),
        ("k", "Deployments' Needs-you line: CAN 12 / CAN 16 'not reported', never 'nothing open'", _children_not_reported(),
         "build.py no longer derives a count for a deployment (`_child_needs`: null/null, a note pointing to the parent loop). "
         "Measured by the verifier: " + "; ".join(f"{c} '{V3_COUNTS['trackLine'][c]['text'].rstrip(' →')}'" for c in ("can12", "can16"))
         + f", hover '{V3_COUNTS['trackLine']['can16']['title']}'. Their needs page is titled 'Bench rotor · CAN 16 · 10:1', never the raw id."),
        ("l", "Proven subline: 'N proven' under each north star", "partly",
         "New pure module proven.ts reads the projector's own counts (green + done) and never recounts rung statuses; a "
         "'stale' warning adds '(not current)'; a missing or malformed count shows nothing, never 0. proven.test 6/6. Proven in "
         "flight only: the roadmap stub was patched with page.route to return {green 1, done 3}, and all 5 home rows and the kinsim "
         "north-star line read '4 proven' (with a stale warning, '4 proven (not current)'). Unpatched, nothing shows. Needs a re-check "
         "against the real widget once claude/vibetracks-roadmap-r3 lands."),
        ("m", "Compact switcher: one pill instead of three buttons", True,
         "'Proposal A · Drill-down pages ▾', 210.9 × 30.75 px; it opens upward to 115 px and closes after a pick, on Escape or an outside "
         "click; the pick survives a reload and keys 1/2/3 still switch. The verifier's centre probe: 0 misses on "
         + ", ".join(sorted(V3_PAGE_RUNS)) + " at rest and max scroll. Fix wave 3 left one fault: on the grasping and detection track pages "
         "at rest the pill sat over clickable KPI cells ('87.4 %', '2 / 12'). Round 3 moved the pill into the review bar (row o): 0 hits. "
         "Round 6 retired it with variants B and C."),
        ("n", "Code spans wrap between tokens, not mid-token", True,
         "`.vt-a-code` moved from `word-break: break-all` to `overflow-wrap: break-word` (one class covers purposes, link values "
         "and file paths). At 664-848 px on rig (ladder.json, loop-status.json) and grasping (out/ledger/runs.jsonl), collapsed and "
         "expanded: no mid-token breaks. With break-all forced back on, kinsim breaks 'stat|us.json', so the check can fail."),
        ("o", "Review bar: the pills sit in a 40 px bar under the scroll area, never over content", V4_HITS == 0 and V4_SEAMS == [0],
         f"Round 3. Dashboard.tsx is header → `.vt-scroll` → `#vt-review-bar`; the A · B · C pill and the needs page's N pill sit in "
         f"the bar, and the scroller ends where it starts. verify-4: {len(V4_STATES)} states (home, kinsim / grasping / detection track "
         f"pages, N1–N6 on kinsim and rig; 1440 × 900 and 1280 × 800; rest and max scroll), seam {V4_SEAMS} px, one pill per page, "
         f"{V4_HITS} hits against every clickable element and text node. Forcing the pill over content gave "
         f"{V4_MUT['home:mutated']['hits']} hits on home and {V4_MUT['n6-kinsim:mutated']['hits']} on N6, so the detector can fail."),
        ("p", "KPI cells reachable by keyboard and named for screen readers", True,
         "Round 3. Each cell is a button with role=button, tabindex 0 and an aria-label such as 'Rungs green or done · Start: 4 / 62 · "
         "open evidence'. verify-4: Tab reaches the first cell in 11 presses with a visible focus ring; Enter moves to "
         "`#vt?track=kinsim&kpi=rungs_green&iteration=start` and its evidence page renders."),
        ("q", "Home and track Needs-you wording: '0 blocking', and 'not reported' instead of a null shown as 0 or 'none'", True,
         "Round 3. One `blockingWords()` for both pages. Grasping's home cell reads '0 blocking · 7 open'; a null blocking count "
         "reads 'not reported'. The home summary says '4 questions block a rung · questions not reported on 1 track' instead "
         "of skipping the unreported track. verify-4 matched home, track lines, N1–N6 headers and /needs on all 5 tracks."),
        ("r", "Grasping's north star is the bench's own verdict, not a copy of its rules", True,
         f"Round 3; see the top section. The projection reads {G_STAR['value']:g} / {G_STAR['of']} ('{G_STAR['note']}'); the bench's "
         f"own gallery, run at build time in its own venv over {ORACLE_NOW['n_runs']} ledger rows, says {len(ORACLE_NOW['beaten'])} "
         f"beaten. It read {G_STAR_OLD['value']:g} / {G_STAR_OLD['of']} at the first drive."),
        ("s", "No raw ISO stamp in any hover title", True,
         "Round 3 replaced eleven raw-ISO titles in N1–N4 with the kit's `hoverTime`. verify-4 then found "
         f"{len({c for _, c in V4_ISO_TITLES})} variant-A sites still raw ({len(V4_ISO_TITLES)} stamps), e.g. "
         + ", ".join(f"'{t}'" for t, _ in sorted(V4_ISO_TITLES, key=lambda x: "+00:00" not in x[0])[:2])
         + ". Both now use `formatLocal(…, {year: true})` (`TracksPage.tsx:111`, `TrackPage.tsx:76`). A scan of every title "
         f"on home and the five work-track pages ({sum(r['titles'] for r in HOVER_SCAN['out'])} titles, "
         f"{sum(len(r['timeTitles']) for r in HOVER_SCAN['out'])} with a time) finds 0 raw ISO stamps, e.g. "
         f"'{HOVER_SCAN['out'][1]['timeTitles'][0]}' (r5-report/hover-iso-scan.json, 10-05 01:31 PDT)."),
        ("t", "Last-moved source label: one line, visible ellipsis, whole text on hover", True,
         "Round 3, measured by the UI lane (not re-checked by verify-4): 17 px tall everywhere; at 1440 nothing is cut, at 1280 "
         "'kinsim_eve…' and 'grasping_le…'. The same lane let the status word wrap (grasping's 'Tier 2 · MuJoCo physics' used "
         "to print over its Progress number at 1280) and fixed the row-end chevron at 52 px; an overflow scan at 1100, 1280 and "
         "1440 finds nothing past its cell."),
        ("u", "Proven subline: the hover explains the count", "partly",
         "Round 5, after Codex round 2. proven.ts exports the requested hover text, and '(not current)' adds 'Not current: the "
         "roadmap could not be refreshed, so this is its last good count.' ProvenNote uses it on home and the track page; "
         "proven.check.mjs pins the exact text (7/7, fails on b53567e). Not seen in the app: this worktree's roadmap is a stub, so "
         "the subline never renders on 4390 (row l)."),
        ("v", "Long track title wraps at 390 px; the rename menu stays inside the page", True,
         "Round 5. With Clank's left panel open the dashboard is 152 px wide, and 'Kinematic Sim' was cut at 'Kinemat' (178 > 152) "
         "with 'Rename track…' off the page. The title now wraps (overflow-wrap: anywhere, min-width: 0) and the menu anchors to "
         "the h1 below 600 px. UI lane: scrollWidth equals clientWidth on all 5 track pages, panel open and collapsed, menu open; "
         "grasping's state word, 29 px past the edge, wraps too. verify-6: home and all track pages clean with the panel open. "
         "Not covered: 6 iteration and item pages still scroll at that width (Issues)."),
    ]


def _children_not_reported() -> bool:
    return all(V3_COUNTS["trackLine"][c]["text"] == "Needs you · not reported →" for c in ("can12", "can16"))


def _home_cells() -> dict:
    return {r["t"]: r["cell"].replace(" | ", " · ") for r in NEEDS_COUNTS if r["prop"] == "n6"}


def _cell_numbers(cell: str) -> tuple[str, str]:
    """'1 blocking | 3 open' -> ('1', '3'); 'none blocking | 7 open' -> ('0', '7'); 'not reported' -> ('null', 'null')."""
    if cell == "not reported":
        return "null", "null"
    m = re.fullmatch(r"(\d+|none) blocking \| (\d+) open", cell)
    assert m, f"unexpected home cell: {cell!r}"
    return ("0" if m[1] == "none" else m[1]), m[2]


def _needs_one_source() -> bool:
    """True when, on every track, the N6 header's data-blocking/data-open equal the home cell that opened it."""
    rows = [r for r in NEEDS_COUNTS if r["prop"] == "n6"]
    heads = {r["t"]: next(a for a in r["attrs"] if a.get("tid") == "vt-n6-head") for r in rows}
    return len(rows) == 5 and all(_cell_numbers(r["cell"]) == (heads[r["t"]]["b"], heads[r["t"]]["o"]) for r in rows)


FIXES = _fix_rows()


VERDICT_CELL = {True: ("okt", "fixed"), False: ("badt", "NOT FIXED"), "partly": ("warnt", "partly")}


def fix_table() -> str:
    rows = "".join(
        f'<tr><td class="num">{esc(i)}</td><td>{esc(issue)}</td>'
        f'<td class="{VERDICT_CELL[ok][0]}">{VERDICT_CELL[ok][1]}</td><td class="small">{inline_md(ev)}</td></tr>'
        for i, issue, ok, ev in FIXES)
    return ('<div class="tablewrap"><table class="grid"><thead><tr><th></th><th>Issue</th><th>Verdict</th>'
            '<th>Measured on the live lane after a backend restart</th></tr></thead><tbody>' + rows + "</tbody></table></div>")


NFIXED = sum(1 for f in FIXES if f[2] is True)
NPARTLY = sum(1 for f in FIXES if f[2] == "partly")


ISSUES = [
    ("A 404 or 403 still offers 'Open in new tab'",
     "MediaView drops the link only on a 409, so other refusals keep a link to an error page."),
    ("PROJECTION.md still lists a 413 for /needs/evidence",
     "Line 173 says the route answers '413 over the size cap'; that cap is gone, and the route now answers Range "
     "with 206 and 416 like /media."),
    ("Two copies of the Range grammar",
     "needs.py carries its own `parse_range`, a copy of server.py's with a WHY comment, because server.py is the "
     "backend's entry script and cannot be imported. A shared helper (for example in vibetracks/safe_open.py) "
     "would remove the copy."),
    ("HEAD on /needs/evidence answers 501",
     "The page checks a link with a one-byte GET, so nothing on screen depends on it; /media answers HEAD 200 "
     "(verify-9's backend probe)."),
    ("Leftovers of B and C outside the product code",
     "`scripts/shoot.mjs` still clicks `vt-switch-<x>`, so its `--variant` flag fails; comments in shared/route.ts"
     " and shared/types.ts (its unused key 'a' | 'b' | 'c') still name the switcher. VARIANTS.md, BRIEF.md and "
     "VARIANT-KIT.md now mark B and C archived (Codex round 3, finding 5). The older stills below show the pill, as they were."),
    ("The track pages' /media URLs read their revision from one shared map",
     "`mediaUrl()` takes the revision of the projection on screen from a per-backend WeakMap. Codex's fix line for"
     " round 3's finding 1 asked for revisions passed explicitly; the Needs page now does that, the track pages do"
     " not. If Clank mounts a second viewer, a re-render in one reads whichever rendered last. One viewer stays "
     "mounted on the lane, so nothing wrong was reproduced."),
    ("A peer worktree shares the grasping verdict cache",
     "`/home/bam/vibetracks-roadmap` (branch `claude/vibetracks-roadmap`) runs its own copy of the bridge and "
     "writes the same `~/.local/share/vibetracks/dashboard/grasping-bench-verdict` folder. This bridge keeps its "
     "per-digest answers in a separate verdict-v3-subsets.json, so the projector's verdict-v3.json is never "
     "evicted, and reads a foreign entry as a miss. That worktree's copy of tests/test_grasp_bench_bridge_deps.py "
     "still tests the V1 `bench_verdict()` deleted here: when the lanes merge, `BenchVerdictV1DependencyTest` must"
     " go, or it fails on the merged bridge."),
    ("Some fixes guarded by probes, not tests",
     "Narrow pages, the single /needs and /projection reads, media switching, the video pair's 409 and the Needs "
     "evidence binding are browser checks now (8 of 8 pass in verify-9; media_pair_stale timed out once on its 5 s"
     " wait, then passed 3 of 3). Finding 10 (the UI fold) is still checked by headless probes in the media "
     "folders."),
    ("Rename is exact now, with no length cap",
     "The 80-character limit went with the trimming: only an empty, whitespace-only or line-broken title is "
     "refused (the request body is still capped at 64 KB). A 409 carries only the revision, so the editor reads "
     "the other title from a re-fetched projection ('reading the other version…') before it can offer the choice."),
    ("Grasping's columns read T0, T1, T2, T3, T5, T1-s1, T1-s2, T4",
     "Ledger order, as tested, but T4 ('Harder real clutter, offline', 3 runs) is the 'latest' column while the "
     "frontier rung is Tier 2. Not a truth violation; a reader may find it confusing. Flagged for the audit."),
    ("Duplicate `#vt-review-bar` ids",
     "Clank's dockview keeps a detached dashboard alive, so two bars with one id can exist. NeedsShell now looks "
     "the bar up inside its own `.vt-dash`; an instance-unique id would remove the trap."),
    ("Proven subline not yet seen on live data",
     "Its hover text is pinned by proven.check, but the subline was checked only against a patched stub. Re-check "
     "once the real widget from `claude/vibetracks-roadmap-r3` lands; proven.ts already accepts its `{document}` "
     "wrapper. With '(not current)' the home Progress cell runs to 4-5 lines, so rows get taller."),
    ("Scorecard at narrow widths",
     "At 390 px nothing scrolls sideways now, but kinsim's scorecard still shows KPI | Status and no wave columns;"
     " at a 900 px viewport the kinsim and rig scorecards showed no iteration columns (seen in verify-5, not "
     "re-measured). Long words wrap mid-word at a 152 px dashboard ('scorebo|ard'); no character is lost."),
    ("Needs-you page (detail in that report)",
     "Codex round 3 there: every evidence link opens only the file the Needs document recorded, through "
     "/needs/evidence with that document's revision, never /media. From earlier rounds, not re-measured: on N6 at "
     "1280 × 800 rig T2's note box loses 8 px at the bottom; N6's deployment page says 'loop' twice."),
    ("Roadmap widget is a stub (expected)",
     "Every Roadmap section says 'Roadmap widget pending (roadmap session)' and `GET "
     "/api/plugins/vibetracks/roadmap/<id>` answers 404 until its branch merges. The home rung cell uses each "
     "loop's own `rung` meanwhile."),
    ("This wave is uncommitted",
     "HEAD is e0bd8e5 (Codex round 3's findings 3 and 4, committed). The fixes for 1, 2 and 5 are 30 uncommitted "
     "paths in /home/bam/vibetracks-dashboard (plus the two report builders), new files such as needs/evidence.ts "
     "and tests/test_dashboard_needs_evidence_bound.py among them; a peer's `git stash -u` there would take them."),
    ("The hero video predates round 3",
     "It was recorded after fix wave 1: its home rows show grasping at 6 / 10 from the adapter's old copy of the "
     "rules, '7 blocking', the pre-one-source Needs-you counts, a zoneless 'read 2026-10-04 20:53' and the "
     "switcher as three buttons, which are now gone. Re-record it if the video should be current too."),
    ("Sources in agent worktrees",
     "Kinsim, rig and grasping still read from agent worktrees a sweep could delete. The row would then say 'not "
     "reporting', truthfully."),
    ("Clank shell errors (not the dashboard)",
     "The shell's usual .clank/*.json 404s and fs mkdir requests (refused by the read-only captures). No error "
     "came from the dashboard code."),
    ("Bridge edits need a backend restart",
     "The build reloads grasping.py when it changes, but not grasp_bench_bridge.py; a change to the bridge's "
     "script text still invalidates its cache on its own."),
]


DECISION_R5 = f"""
<ul>
  <li><strong>Done and proved</strong> (verify-6, a measure-only re-check by a separate Claude agent; it made no product edits):
    <ul>
      <li><b>Codex round 2:</b> its {len(AUDIT2_ROWS)} new findings and the partly fixed round-1 findings 7, 9 and 13 are fixed. verify-6 re-probed all {N_IN_SCOPE} Codex's way or harder, and each has a test at the consumer that fails on b53567e; rewriting only the served rename and media modules in flight makes the two browser checks fail. Table at the top.</li>
      <li><b>For the track pages:</b> both file routes open every path component without following a symlink (2); grasping's row digests and judgement come from one byte snapshot through the bench's own parser (4), and its V2 verdict needs all nine module witnesses (6); variant A uses no blue for ordinary states (7). Two asks from this page: a long title wraps at 390 px with the panel open (row v), and the proven hover explains the count (row u, text pinned, not seen in-app).</li>
      <li><b>Grasping:</b> the bench's own gallery, run without the bridge in its own venv, matches verdict() uncached and cached: 6 of 10 gated envs beaten, MuJoCo 2 of 6; all 166 row digests equal sha256 of the raw lines.</li>
      <li><b>Regressions checked:</b> one Needs-you count on /needs, home, the track line and N1–N6 (kinsim 1/3, rig 2/6, grasping 0/7, detection 1/3; pyblocks and CAN 12/16 'not reported'); rename byte-identical for an LF and a BOM+CRLF note; variant A's /media links open; 1440 × 900 clean on 22 routes; 7 of 7 report videos play.</li>
      <li><b>Build:</b> pytest 299 passed, 0 skipped; unittest discover 299 OK (it crashed on b53567e); backend 23; tsc clean; node checks 74/74; rename_fence and media_switch pass in the browser.</li>
    </ul></li>
  <li><strong>Left</strong> (next; only the merges and the commit wait on you):
    <ul>
      <li><b>Codex round 3</b> on this tree (b53567e plus the round-2 fixes, uncommitted). It runs next; both reports are re-shared before it starts.</li>
      <li>At 390 × 844 with the panel open, 6 iteration and item pages scroll sideways; /media links are not bound to a revision; variants B and C keep blue (Issues).</li>
      <li>PROJECTION.md:159 is stale; the V1 bench verdict waits on the adapter test's fixture; /needs is fetched about four times on first load.</li>
      <li>The roadmap worktree still runs the old grasping bridge and shares its cache folder. Re-check the proven subline on the real widget once it lands; fix <code>scripts/shoot.mjs</code> for the pill; re-record the hero; the scorecard's missing wave columns below 900 px.</li>
    </ul></li>
  <li><strong>Needs you</strong> (each has a default that keeps work moving if you say nothing):
    <ol>
      <li><b>Fix verify-6's siblings before Codex round 3 reads the tree?</b> Recommendation: yes for the /media revision binding and the 390 px item and iteration pages; the rest can ride. Default: round 3 runs on this tree, with these listed for it.</li>
      <li><b>Bring the grasping bridge fix to <code>claude/vibetracks-roadmap</code></b> (or stop its bridge) so the two worktrees stop overwriting one cache? Recommendation: yes, with the roadmap merge below. Default: both keep writing; this dashboard stays correct.</li>
      <li><b>Merge the roadmap widget</b> (<code>claude/vibetracks-roadmap-r3</code>) into <code>claude/vibetracks-dashboard</code>?
          Recommendation: yes, after a Codex round passes; it replaces the stub and lets the proven subline and its hover be seen. Default: nothing is merged; the section keeps saying pending.</li>
      <li><b>Commit the Codex fixes</b> on <code>claude/vibetracks-dashboard</code> so a peer's stash cannot take them?
          Recommendation: yes, once a Codex round passes. Default: left uncommitted, as this task's rules require.</li>
      <li><b>Durable homes for loop files</b> now in agent worktrees (rig loop, grasp ledger and bench venv, kinsim loop dir)?
          Recommendation: a stable path per loop. Default: unchanged; a sweep would turn a row 'not reporting' honestly.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no commits, no vault edits. verify-6's siblings and the 390 px item and iteration pages
      were not fixed in this pass, and the proven hover was not seen in the app. The hero video still predates round 3.</li>
</ul>
"""

DECISION = f"""
<ul>
  <li><strong>Done and proved</strong> (verify-5, a measure-only re-check by a separate Claude agent; it made no product edits):
    <ul>
      <li><b>Codex round 1:</b> {AUDIT_PASS} of {len(AUDIT_ROWS)} findings fixed and re-run Codex's way or harder, plus the 390 px overflow; no regressions. Table at the top.</li>
      <li><b>For the track pages:</b> one Needs-you count in every KPI row (finding 5); missing rig ladder and events read 'not measured', never 0 (4); an unreadable triage file reads 'not reported' (3); stored text reaches the page whole and folds with 'Show all (N characters)' (10); rename keeps every authored character and its own revision fence (6, 8); a listed file whose symlink changed answers 403 (9); grey trend lines and one sans font (13).</li>
      <li><b>Grasping:</b> {G_STAR['value']:g} / {G_STAR['of']} at {esc(fmt_time(PROJ['generated_at']))}, equal to the bench's own gallery over {ORACLE_NOW['n_runs']} rows; 4 / 10 at round 3. Its cache now follows every bench module the verdict imports (2), and an oracle failure fails the test instead of skipping it (12).</li>
      <li><b>Round 3's leftovers:</b> 0 raw ISO stamps in {sum(r['titles'] for r in HOVER_SCAN['out'])} hover titles on home and the five work-track pages; the 4390 lane serves the new N5.</li>
      <li><b>Build:</b> pytest {esc(AUDIT['checks']['pytest'])}; backend {esc(AUDIT['checks']['backend_pytest'])}; tsc clean; node checks {esc(AUDIT['checks']['node_checks'])}; {AUDIT['checks']['console_errors']} console errors; 7 of 7 report videos play. Home still shows exactly the five work tracks.</li>
    </ul></li>
  <li><strong>Left</strong> (next; only the merges and the commit wait on you):
    <ul>
      <li><b>Codex round 2</b> on this tree (3e90b94 plus 63 uncommitted changes). It runs next; both reports are re-shared before it starts.</li>
      <li>The roadmap worktree still runs the old grasping bridge and shares its cache folder (Issues, first item).</li>
      <li>Findings 10 (UI fold), 11 and 13 and the overflow are guarded by headless probes, not by tests in the suite.</li>
      <li>From verify-5's notes: the settled-draft copy line, the lone carriage return, the parent-folder symlink race.</li>
      <li>Re-check the proven subline on the real roadmap widget once it lands; fix <code>scripts/shoot.mjs</code> for the pill; re-record the hero; the scorecard's missing wave columns below 900 px.</li>
    </ul></li>
  <li><strong>Needs you</strong> (each has a default that keeps work moving if you say nothing):
    <ol>
      <li><b>Bring the grasping bridge fix to <code>claude/vibetracks-roadmap</code></b> (or stop its bridge) so the two worktrees stop overwriting one cache? Recommendation: yes, with the roadmap merge below. Default: both keep writing; this dashboard stays correct, the roadmap copy keeps the stale-cache bug.</li>
      <li><b>Merge the roadmap widget</b> (<code>claude/vibetracks-roadmap-r3</code>) into <code>claude/vibetracks-dashboard</code>?
          Recommendation: yes, after Codex round 2; it replaces the stub and gives the proven subline real data. Default: nothing is merged; the section keeps saying pending.</li>
      <li><b>Commit the Codex fixes</b> on <code>claude/vibetracks-dashboard</code> so a peer's stash cannot take them?
          Recommendation: yes, once Codex round 2 passes. Default: left uncommitted, as this task's rules require.</li>
      <li><b>Durable homes for loop files</b> now in agent worktrees (rig loop, grasp ledger and bench venv, kinsim loop dir)?
          Recommendation: a stable path per loop. Default: unchanged; a sweep would turn a row 'not reporting', or grasping's verdict 'unavailable', honestly.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no commits, no vault edits, no Vite restart (none was needed). verify-5's low-severity notes were not
      fixed in this pass. The A · B · C pill is hidden on needs pages, where it would switch nothing (no fake controls). Loop prose that carries
      its own clock ('at 14:54 UTC', 'UPDATE 21:30') is shown as written, under the truth rule, not converted.</li>
</ul>
"""

def grasping_html() -> str:
    t = TRACKS["grasping"]
    bv = t["source"]["bench_verdict"]
    def prov(o: dict) -> str:
        return "provisional: " + (esc(", ".join(o["provisional"])) if o["provisional"] else "none")
    r3_grasp = next(x for x in R3_PROJ["tracks"] if x["id"] == "grasping")
    rows = [
        ("First drive (20:55), adapter's own copy of the rules", f"{G_STAR_OLD['value']:g} / {G_STAR_OLD['of']}", esc(G_STAR_OLD.get("note") or ""), esc(OLD_GRASP["summary"])),
        (f"verify-4 (23:22), bench gallery in its own venv · {ORACLE_V4['n_runs']} rows",
         f"{len(ORACLE_V4['beaten'])} / {ORACLE_V4['gated']}", "beaten: " + esc(", ".join(ORACLE_V4["beaten"])), prov(ORACLE_V4)),
        (f"Round 3 build ({fmt_time(R3_PROJ['generated_at'])}), dashboard projection", f"{G_STAR_R3['value']:g} / {G_STAR_R3['of']}",
         esc(G_STAR_R3["note"]), esc(r3_grasp["summary"])),
        (f"Round 3 build, bench gallery in its own venv · {ORACLE_R3['n_runs']} rows", f"{len(ORACLE_R3['beaten'])} / {ORACLE_R3['gated']}",
         "beaten: " + esc(", ".join(ORACLE_R3["beaten"])), prov(ORACLE_R3)),
        (f"Now ({fmt_time(PROJ['generated_at'])}), dashboard projection", f"{G_STAR['value']:g} / {G_STAR['of']}", esc(G_STAR["note"]), esc(t["summary"])),
        (f"Now, bench gallery in its own venv · {ORACLE_NOW['n_runs']} rows", f"{len(ORACLE_NOW['beaten'])} / {ORACLE_NOW['gated']}",
         "beaten: " + esc(", ".join(ORACLE_NOW["beaten"])), prov(ORACLE_NOW)),
    ]
    moved = "".join(
        f"<li><code>{esc(r['env'])}</code>: <code>{esc(r['run_id'])}</code>, started {esc(r['started'])}, {esc(r['protocol'])}, "
        f"{r['value'] * 100:.0f} % over n = {r['n']}, Wilson lower bound {r['wilson_lb'] * 100:.1f} % against a gate of {r['gate'] * 100:.0f} %.</li>"
        for r in ORACLE_NOW["new_since_round3"])
    table = ('<div class="tablewrap"><table class="grid small"><thead><tr><th>Read by</th><th>Gated envs beaten</th><th>Which</th>'
             '<th>Context</th></tr></thead><tbody>' + "".join(
                 f'<tr><th>{esc(a)}</th><td class="num"><b>{esc(b)}</b></td><td>{c}</td><td class="dim">{d}</td></tr>' for a, b, c, d in rows)
             + "</tbody></table></div>")
    return (
        '<div class="g2">'
        + fig("02-track-grasping.webp", f"Before: {G_STAR_OLD['value']:g} / {G_STAR_OLD['of']} gated envs beaten, MuJoCo 2 / 6",
              "First drive, 20:55. The adapter judged the ledger with its own copy of the bench's rules. Also stale here: "
              "'2 of 6 gates cleared', '7 blocking' and 'since 10-05 01:54 UTC'.")
        + fig(str(MEDIA / "verify-4" / "v4-1440-grasping-rest.png"), "Round 3: 4 / 10, MuJoCo 0 / 6, the bench's own verdict",
              "verify-4, 23:26. 'North star 4 / 10', '0 of 6 gates beaten', 'Needs you · 0 blocking · 7 open', and the time in PDT. "
              "The page reads the same KPI fields as before; only who judges them changed.")
        + fig(str(MEDIA / "verify-5" / "v5-1440-grasping.png"), "Now: 6 / 10, MuJoCo 2 / 6, still the bench's own verdict",
              "verify-5, 10-05 after 00:48. 'North star 6 / 10', '2 of 6 gates beaten (open: stage1, stage2, stage4, stage5)'. Same rules, "
              "more ledger: two frozen MuJoCo runs landed at 23:43 and 23:50 PDT.")
        + "</div>"
        + "<h3>Why it moved from 4 to 6, and why that is not the old error</h3>"
        f"<p>The north star is a live count over a ledger the loop keeps adding to, so it moves whenever a run lands. At round 3's "
        f"build the bench judged {ORACLE_R3['n_runs']} rows and beat {len(ORACLE_R3['beaten'])} envs, with MuJoCo stage0 and stage3 "
        f"only provisional (cleared on a smoke run). By {fmt_time(PROJ['generated_at'])} the ledger had {ORACLE_NOW['n_runs']} rows, and "
        "two frozen eval-200 runs beat those envs outright:</p>"
        f'<ul class="ls">{moved}</ul>'
        f"<p>The first drive also showed {G_STAR_OLD['value']:g} / {G_STAR_OLD['of']}, but from the adapter's copy of the rules, which "
        "counted stage0 and stage3 as beaten on runs the bench itself did not accept. The number is the same, and this time the bench "
        "gives it. The next frozen run that clears or misses a gate moves it again; a read that disagrees with the bench is what would be wrong.</p>"
        + "<h3>Why it drifted</h3>"
        "<p>The grasping adapter judged the bench's ledger with its own copies of the bench's rules: <code>is_frozen</code>, "
        "<code>is_privileged</code>, <code>clears_gate</code>, <code>headline_runs</code>, <code>env_verdict</code>, the frozen "
        "protocol table and the eval seed. The bench then tightened what counts as a frozen run (commit <code>da80ffe1</code>). "
        "The copy did not follow, so the dashboard kept counting runs the bench itself no longer accepts and showed 6 of 10 "
        "beaten. The copied protocol table had drifted too: it was missing <code>mujoco-cam</code>. Grasping's 'gates cleared' wording was also wrong for an "
        "env that clears its gate only on a smoke run: it now reads 'gates beaten', with those envs listed as provisional.</p>"
        "<h3>How the bridge prevents it</h3>"
        '<ul class="ls">'
        "<li><b>No copy left to drift.</b> <code>grasp_bench_bridge.py</code> runs the bench's own <code>gallery.py</code> in the "
        "bench's own Python (<code>.venv/bin/python -I</code>, from the bench folder, with VIRTUAL_ENV and the PYTHON* overrides "
        "removed, 90 s timeout) and returns its verdict as JSON: beaten and provisional per env, the headline run per cell, frozen, "
        "privileged and clears-gate per run. A test fails at import if any of the twelve copied names comes back.</li>"
        "<li><b>It judges exactly the rows the adapter read</b>, by run_id, one cumulative set per phase, so a ledger that grows "
        "mid-build cannot skew the count. An answer that misses a row is rejected, not half-used.</li>"
        "<li><b>Wrong code is refused.</b> If the bench imports gallery, ledger, curriculum, runner or contracts, or reads "
        "attestations.jsonl, from anywhere but the declared paths, the answer is thrown away.</li>"
        "<li><b>No verdict means no number.</b> If the bench cannot answer (no venv, import error, timeout), the north star is "
        "null on every iteration with 'bench verdict unavailable: &lt;reason&gt;', six verdict KPIs read 'unconfirmed', the state "
        "reads 'Bench verdict unavailable' and the reason goes in <code>source.problems</code>. Never a guess.</li>"
        "<li><b>A test asks the bench directly.</b> The live smoke test runs <code>gallery.env_verdict</code> in the bench's Python, "
        "written in the test and not through the bridge, and asserts the dashboard's latest value and its 'beaten: …' note equal "
        "it.</li>"
        f"<li><b>Cheap, and invalidated by what the verdict depends on.</b> Since Codex finding 2, the cache records the mtime and size "
        f"of every bench module the gallery imports (9 at the last read, registry.py and contracts.py among them), plus the ledger, "
        f"attestations.jsonl (stamped absent when missing), the bench's Python, the request and the bridge script; an entry without "
        f"that module list is a miss. This build read a cached answer in {bv['seconds']:.3f} s (computed "
        f"{esc(fmt_time(bv['computed_at'].replace('-0700', '-07:00')))} in {bv['bench_seconds']:.2f} s), and the bench's own gallery, "
        f"run separately at the same minute, agrees.</li>"
        "</ul>"
        "<h3>The count follows the ledger, and agreed with the bench every time both were read</h3>"
        + table
        + '<p class="small dim">The grasping lane saw 3 beaten while it worked; by verify-4 toy/xy_rz_w was beaten too; after 23:43 '
        "stage0 and stage3 followed. Each time the dashboard and the bench were read together they agreed. The builder asserts "
        "both build-time pairs are equal before it writes this page. Still to know: the bridge calls the bench's private <code>gallery._run_privileged</code>; if the "
        "bench renames it, the row reads 'bench verdict unavailable', not a wrong number.</p>"
    )


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
/* phone-width captures sit four across, so a portrait still is not a full screen tall */
.g4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px;margin-top:20px}
@media(max-width:820px){.g4{grid-template-columns:1fr 1fr}}
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


def fix_word(f: dict) -> tuple[str, str]:
    """(css class, words) for the Fixed? column; only a failure gets colour."""
    if f.get("word"):
        return ("afix", f["word"])
    return ("afix", "fixed · verified") if f["pass"] is True else ("afix no", "NOT fixed")


def audit2_html() -> str:
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
    v6 = MEDIA / "verify-6"
    figs = '<div class="g2">' + "".join([
        fig(str(v6 / "v6-1440-kinsim.png"), "Kinsim at 1440 after round 2: still calm",
            "verify-6's census over all 22 variant-A routes at 1440 found 0 blue elements and no sideways scroll; the colour left is "
            "the warn value and the Needs-you count."),
        fig(str(v6 / "v6-variant-b-kinsim-1440.png"), "Open at round 2, gone in round 6: variant B's blue sparklines",
            "Proposal B, then offered by the same switcher, drew its kinsim trend lines and points in rgb(35, 131, 226); C marked the "
            "selected track with a blue border (beside finding 7). Both variants were removed in round 6."),
    ]) + '</div><div class="g4">' + "".join([
        fig(str(MEDIA / "r5-narrow-390-panel-open-menu.png"), "390 px, panel open: the title wraps",
            "The dashboard is 152 px wide here. 'Kinematic Sim' wraps inside it and 'Rename track…' opens inside the page "
            "(UI lane's capture)."),
        fig(str(v6 / "v6-390-open-kinsim-item-offender.png"), "Open at round 2, closed in round 6: an item page at the same width",
            "Kinsim's BT4 item page: the property values sat at x 474, off the 152 px page, so it scrolled sideways (236 vs 152). "
            "One of 6 iteration and item pages verify-6 found; 0 of 698 pages scroll in verify-7's sweep."),
    ]) + "</div>"
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
<h3>Round 1's {len(AUDIT2_R1)} findings, as Codex round 2 re-read them</h3>
<ol class="r1s">{r1}</ol>
<h3>Round 2's {len(AUDIT2_ROWS)} new findings, plus the two asks from the track pages</h3>
<div class="ahead"><span>#</span><span>Severity</span><span>Codex's finding · what verify-6 measured after the fix</span><span>Fixed?</span></div>
<ol class="audit">{items}</ol>
{figs}
<h3>What verify-6 noticed but did not count as a failure</h3>
<ul class="ls">{notes}</ul>
<details class="raw"><summary>Round 1: Codex's {len(AUDIT_ROWS)} findings on 3e90b94 and verify-5's evidence</summary>
{audit_html()}</details>"""


def audit_html() -> str:
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
    figs = '<div class="g2">' + "".join([
        fig(str(MEDIA / "verify-5" / "v5-1440-kinsim.png"), "Finding 13: one font, colour only for exceptions",
            "Trend lines and the latest-column wash are grey, code chips are in the page's sans; the only colour left is the warn "
            "value (37.3 % → 41.8 %, the ruler changed) and the Needs-you counts. verify-5 found 0 elements in the accent colour on 5 pages."),
        fig(str(MEDIA / "verify-5" / "v5-390-collapsed-kinsim.png"), "390 × 844: no sideways scroll",
            "One of 48 checks with no horizontal page scroll. Also visible, and still open: the scorecard shows KPI | Status and no "
            "wave columns at this width (see Issues)."),
    ]) + "</div>"
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
<h3>What verify-5 noticed but did not count as a failure</h3>
<ul class="ls">{notes}</ul>"""


def round6_html() -> str:
    items = "".join(
        f'<li class="arow"><span class="an">{esc(i["n"])}</span><span class="asev">{esc(i["lane"])}</span>'
        f'<div class="abody"><b>{esc(i["title"])}</b><p>{esc(i["short"])}</p>'
        # WHY the 'Now' beside verify-7's words: most of these were closed in e0bd8e5 or this wave; the page keeps what
        # verify-7 saw before 56c75c0 and says what became of it, rather than calling a closed item open.
        + (f'<p class="asib"><b>Still open beside it at {R6_TREE}:</b> {esc(i["still_open"])} <b>Now:</b> '
           f'{esc(AUDIT3["r6_still_now"][i["n"]])}</p>' if i["still_open"] else "")
        + '<details><summary>verify-7\'s evidence, and the test that fails when the old behaviour returns</summary>'
        f'<p class="averb">{esc(i["verifier"])}</p><p class="averb"><b>Test left ({esc(i["lane"])} lane):</b> {esc(i["tests"])}</p>'
        f'</details></div><span class="afix">{"fixed · verified" if i["pass"] is True else "partly · 2 doc gaps"}</span></li>'
        for i in R6_ITEMS)
    found = "".join(f"<li><b>{esc(t)}.</b> <span>{esc(x)}</span> <b>Now:</b> {esc(AUDIT3['r6_found_now'][t])}</li>"
                    for t, x in R6["new_found"])
    c = R6["checks"]
    v7 = MEDIA / "verify-7"
    figs = '<div class="g4">' + "".join([
        fig(str(v7 / "v7-390-open-pyblocks-item.png"), "390 × 844, panel open: a pyblocks item fits",
            "The dashboard is 152 px wide. Property rows stack label over value and the long title breaks mid-word "
            "('scorebo|ard'); nothing scrolls sideways and no character is lost. verify-7: 0 of 698 pages scroll."),
        fig(str(v7 / "v7-390-closed-track-kinsim.png"), "390 × 844, panel closed: kinsim",
            "The state line wraps; the scorecard shows KPI | Status at this width (wave columns not shown, see Issues)."),
        fig(str(v7 / "v7-390-open-grasping-iteration.png"), "390 × 844, panel open: grasping's T0 iteration",
            "The ledger path wraps inside 152 px; the narrow prev/next row wraps awkwardly ('wav|e', 'graspin|g ›') but "
            "keeps every character. verify-6 had a grasping iteration at 206 px; 0 of 698 pages scroll now."),
        fig(str(v7 / "v7-390-closed-pyblocks-item.png"), "390 × 844, panel closed: pyblocks board-b07c38b",
            "Before, its status line did not wrap and the page scrolled 499 vs 390."),
    ]) + '</div><div class="g2">' + "".join([
        fig(str(v7 / "v7-media-stale-line.png"), "/media answering 409: one calm line",
            "verify-7 made /media answer 409 for kinsim's fast gate. MediaView shows 'This changed since you opened it: reload' "
            "with no player and no 'Open in new tab'; reload re-reads /projection and the view asks for the new revision."),
        fig(str(v7 / "v7-media-409-video-pair.png"), "Open at round 6, closed in e0bd8e5: the video pair on a 409",
            "The same 409 on a CAN 12 run: the real-and-sim pair did not go through MediaView, so it showed two dead players "
            "at 0:00 and two 'open in new tab' links. The round-3 section above shows it now."),
        fig(str(v7 / "v7-grasping-gallery-item.png"), "Open at round 6, closed in e0bd8e5: grasping's gallery media 404",
            "Their ids contain ':', which the server's media id pattern refused. 'Could not load: HTTP 404' sat beside a live "
            "'Open in new tab'. Codex round 3 found it too (finding 3)."),
        fig(str(v7 / "v7-media-real-video.png"), "A real video under its revision",
            "The src carries ?rev=<media_rev>; it reaches readyState 4 and plays."),
    ]) + "</div>"
    return f"""
<p class="lead">verify-6 left a short list beside its fixed findings. Two lanes closed it on the uncommitted tree over
<code>{esc(R6['base_sha'])}</code>; then {esc(R6['verifier'])} re-measured each item: <b>{R6_PASS} of {len(R6_ITEMS)} closed, the docs
partly</b>, each with a test that fails without the fix. Variants B and C were retired at your pick of A (recoverable from git).
This tree was committed as <code>{R6_TREE}</code>, and Codex round 3 audited it (above).</p>
<p class="small dim">After the fixes: pytest {esc(c['pytest'])}; unittest {esc(c['unittest'])}; backend {esc(c['backend'])}; tsc
{esc(c['tsc'])}; node checks {esc(c['node_checks'])}; browser checks {esc(c['browser_checks'])}. Counts, unchanged: {esc(c['counts'])}.
Each "still open" line was re-read from {R6_TREE} when this page was built ({R6_PROBES} probes); its "Now" says what
became of it since.</p>
<div class="ahead"><span>#</span><span>Lane</span><span>What was left · what verify-7 measured after the fix</span><span>Closed?</span></div>
<ol class="audit">{items}</ol>
{figs}
<h3>New, found by verify-7 (not fixed in round 6)</h3>
<ul class="ls">{found}</ul>
<details class="raw"><summary>Codex round 2: its findings on b53567e, their fixes and verify-6's evidence</summary>
{audit2_html()}</details>"""


DECISION_R6 = f"""
<ul>
  <li><strong>Done and proved</strong> (verify-7, a measure-only re-check by a separate Claude agent; it made no product edits):
    <ul>
      <li><b>verify-6's leftovers:</b> {R6_PASS} of {len(R6_ITEMS)} closed and re-measured, each with a test that fails without the fix; the docs are right except two gaps. Table at the top.</li>
      <li><b>For the track pages:</b> /media links answer only for the revision on screen; an old link gives the calm reload line, never another file (GET, HEAD and Range, over real HTTP). 0 of 698 pages scroll sideways at 390 × 844 with Clank's panel open or closed (599 and 16 before), and 0 at 1440 × 900.</li>
      <li><b>Variants B and C are removed</b>, at your pick of A, with the A · B · C pill, its keys and the stored choice; the review bar takes no height off the needs page. Both are recoverable from git: commit <code>{esc(R6['variants_commit'])}</code> added them, and their last version is still in HEAD <code>{esc(R6['base_sha'])}</code> because the deletion is not committed (<code>git checkout {esc(R6['base_sha'])} -- clank/src/variants/b clank/src/variants/c clank/src/variants/index.ts</code>).</li>
      <li><b>Regressions checked:</b> one Needs-you count everywhere ({esc(R6['checks']['counts'])}); grasping still matches the bench's own verdict, 6 of 10 (all 166 row digests equal); rename byte-identical for an LF and a BOM+CRLF note; {esc(R6['checks']['videos'])}.</li>
      <li><b>Build:</b> pytest {esc(R6['checks']['pytest'])}; unittest {esc(R6['checks']['unittest'])}; backend {esc(R6['checks']['backend'])}; tsc clean; node checks {esc(R6['checks']['node_checks'])}; narrow, needs_once and rename_fence pass in the browser. media_switch fails on its route glob (a one-line fix, verified on a copy).</li>
    </ul></li>
  <li><strong>Left</strong> (next; only the merges and the commit wait on you):
    <ul>
      <li><b>Codex round 3</b> on this tree ({esc(R6['base_note'])}). It runs next; both reports are re-shared before it starts.</li>
      <li>From verify-7 (Issues, top): /projection read 4 times per first load; the video pair's 409; grasping's ':' media ids; snapshot-mode revisions; a 404 or 403 keeps its link; media_switch.mjs's glob; the shared revision map.</li>
      <li>Docs and tools: NEEDS-KIT.md's new exact lines; VARIANTS.md, VARIANT-KIT.md and <code>scripts/shoot.mjs</code> still describe or click B and C.</li>
      <li>The roadmap worktree still runs the old grasping bridge and shares its cache folder. Re-check the proven subline on the real widget once it lands; re-record the hero; the scorecard's missing wave columns at narrow widths.</li>
    </ul></li>
  <li><strong>Needs you</strong> (each has a default that keeps work moving if you say nothing):
    <ol>
      <li><b>Fix verify-7's open items before Codex round 3?</b> Recommendation: yes for the double /projection read, the video pair's 409 and grasping's ':' ids, which Codex would read as the same class as fixes it already asked for, and the media_switch glob so the suite is green; the docs and the snapshot-mode case can ride. Default: round 3 runs on this tree, with these listed for it.</li>
      <li><b>Bring the grasping bridge fix to <code>claude/vibetracks-roadmap</code></b> (or stop its bridge) so the two worktrees stop overwriting one cache? Recommendation: yes, with the roadmap merge below. Default: both keep writing; this dashboard stays correct.</li>
      <li><b>Merge the roadmap widget</b> (<code>claude/vibetracks-roadmap-r3</code>) into <code>claude/vibetracks-dashboard</code>?
          Recommendation: yes, after a Codex round passes; it replaces the stub and lets the proven subline and its hover be seen. Default: nothing is merged; the section keeps saying pending.</li>
      <li><b>Commit this round</b> on <code>claude/vibetracks-dashboard</code> so a peer's stash cannot take it (the B and C deletion included)?
          Recommendation: yes, once a Codex round passes. Default: left uncommitted, as this task's rules require.</li>
      <li><b>Durable homes for loop files</b> now in agent worktrees (rig loop, grasp ledger and bench venv, kinsim loop dir)?
          Recommendation: a stable path per loop. Default: unchanged; a sweep would turn a row 'not reporting' honestly.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no commits, no vault edits. verify-7's open items were not fixed in this pass; the
      reports only record them. Only home and kinsim's track page were re-captured; older stills keep the switcher they were taken
      with, and the hero video still predates round 3.</li>
</ul>
"""


# ---- Codex round 3: its re-read of earlier findings, its five new findings, and their fixes ----------------------
# WHY the same files as the Needs-you report: Codex's status words, severities and titles are parsed from its own file,
# the evidence is verify-8's (e0bd8e5) and verify-9's (this wave) in one JSON, so the two reports cannot tell the round
# differently.
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
    v8, v9 = MEDIA / "verify-8", MEDIA / "verify-9"
    figs = '<div class="g4">' + "".join([
        fig(str(v9 / "v9-n6-fold-1440x900-kinsim.png"), "Finding 1: a Needs link opens the document's file",
            "Kinsim T47 on N6. 'evidence research/w3-bt1-belt.md' opens /needs/evidence with this document's eid and revision, "
            "never /media. verify-9 clicked every N6 link on kinsim and rig (9 of 9): one tab each, serving the reviewed bytes."),
        fig(str(v9 / "v9-1440-grasping.png"), "Finding 2: grasping's verdict and rows from the same bytes",
            "North star 6 / 10 gated envs beaten, MuJoCo 2 / 6, hardest Wilson LB 87.4 % (n 200): equal to the bench's own "
            "gallery over the same 166 ledger rows. No row marked pass lacks Top-1 or Wilson LB."),
        fig(str(v8 / "v8-grasping-gallery-chip1.png"), "Finding 3: grasping's gallery opens",
            "The gallery item with 'Gallery preview (PNG)' chosen: the PNG answers 206 under its revision (it was 404 at 56c75c0). "
            "The card's own line says the gallery was written before the ledger's last write."),
        fig(str(v8 / "v8-media-409-video-pair.png"), "Also in e0bd8e5: the video pair on a 409",
            "The same CAN 12 run as round 6's capture below: one 'This changed since you opened it: reload' line, no dead players, "
            "no links. Reload re-reads /projection once."),
    ]) + "</div>"
    return f"""
<p class="lead"><b>{esc(AUDIT3['auditor'])}</b>, round {AUDIT3['round']}, read-only, audited {esc(AUDIT3['snapshot'])}, and
returned <b>{esc(AUDIT3_VERDICT)}</b>: {len(AUDIT3_PARTLY)} earlier findings were only partly fixed, and it found {len(AUDIT3_ROWS)}
new ones ({SEV3_LINE}). Findings {_nums(AUDIT3_WHERE['e0bd8e5'])} were fixed in <code>e0bd8e5</code>; {_nums(AUDIT3_WHERE['this wave'])}
in this wave, uncommitted on it. Then {esc(AUDIT3['verifier'])} re-probed all {len(AUDIT3_ROWS)} Codex's way or harder:
<b>{AUDIT3_PASS} of {len(AUDIT3_ROWS)} pass</b>, each with a test at the consumer that fails on the tree before its fix, and no
regressions. <b>Codex round 4 reads this tree next</b>; until it returns, "fixed" is our own measurement, not Codex's.</p>
<p class="small dim">Audit file: <code>{esc(str(AUDIT3_FILE))}</code><br>After the fixes: pytest {esc(c['pytest'])}; unittest
{esc(c['unittest'])}; backend {esc(c['backend'])}; tsc {esc(c['tsc'])}; node checks {esc(c['node_checks'])}; browser checks
{esc(c['browser_checks'])}. Before the fixes: {esc(c['fails_on_old'])}. Media: {esc(c['media'])}. Counts: {esc(c['counts'])}.</p>
<h3>The earlier findings, as Codex round 3 re-read them <small>({len(AUDIT3_EARLIER) - len(AUDIT3_PARTLY)} fixed, {len(AUDIT3_PARTLY)} partly; each partly one is completed by a new finding's fix)</small></h3>
<ol class="r1s">{earlier}</ol>
<h3>Round 3's {len(AUDIT3_ROWS)} new findings</h3>
<div class="ahead"><span>#</span><span>Severity</span><span>Codex's finding · what the verifier measured after the fix</span><span>Fixed?</span></div>
<ol class="audit">{items}</ol>
{figs}
<h3>Also closed in e0bd8e5: verify-7's open items</h3>
<ul class="ls">{also}</ul>
<h3>Still open (none blocking; each re-read from the tree when this page was built, {R7_PROBES} probes)</h3>
<ul class="ls">{left}</ul>
<h3>What verify-9 noticed but did not count as a failure</h3>
<ul class="ls">{notes}</ul>
<details class="raw"><summary>Round 6: verify-6's leftovers, the tree Codex round 3 audited ({R6_TREE})</summary>
{round6_html()}</details>"""


DECISION_R7 = f"""
<ul>
  <li><strong>Done and proved</strong> (verify-8 for e0bd8e5 and verify-9 for this wave, measure-only re-checks by separate Claude agents; neither made product edits):
    <ul>
      <li><b>Codex round 3:</b> all {len(AUDIT3_ROWS)} new findings fixed, {_nums(AUDIT3_WHERE['e0bd8e5'])} in e0bd8e5 and {_nums(AUDIT3_WHERE['this wave'])} in this wave, and the {len(AUDIT3_PARTLY)} partly fixed earlier findings completed by them. Each re-probed Codex's way or harder, each with a test at the consumer that fails without its fix. Table at the top.</li>
      <li><b>For the track pages:</b> grasping's north star and the rows beside it come from the same ledger bytes; if the ledger moves twice during a read the north star says 'ledger changed during read' rather than mixing versions. Live: {esc(AUDIT3['checks']['grasping'])}. Grasping's gallery opens; a snapshot-mode reload recovers after a retarget; one /projection read per load; the video pair shows the reload line on a 409.</li>
      <li><b>Current product:</b> variant A is the only dashboard (B and C retired in 56c75c0); N6 is the default Needs page. VARIANTS.md, BRIEF.md and VARIANT-KIT.md mark the older proposals archived.</li>
      <li><b>Regressions checked:</b> {esc(AUDIT3['checks']['counts'])}; {esc(AUDIT3['checks']['media'])}; {esc(AUDIT3['checks']['overflow'])}; {esc(AUDIT3['checks']['rename'])}.</li>
      <li><b>Build:</b> pytest {esc(AUDIT3['checks']['pytest'])}; unittest {esc(AUDIT3['checks']['unittest'])}; backend {esc(AUDIT3['checks']['backend'])}; tsc clean; node checks {esc(AUDIT3['checks']['node_checks'])}; browser checks {esc(AUDIT3['checks']['browser_checks'])}.</li>
    </ul></li>
  <li><strong>Left</strong> (next; only the merges and the commit wait on you):
    <ul>
      <li><b>Codex round 4</b> on this tree ({esc(AUDIT3['tree_after'])}). It runs next; both reports are re-shared before it starts.</li>
      <li>Still open, none blocking (Issues): the track pages' /media URLs take their revision from one shared map; a 404 or 403 keeps 'Open in new tab'; PROJECTION.md's stale '413' line; two copies of the Range grammar; <code>scripts/shoot.mjs</code>'s dead <code>--variant</code> and two switcher comments; the roadmap worktree's V1 bridge test.</li>
      <li>Re-check the proven subline on the real roadmap widget once it lands; re-record the hero; the scorecard's missing wave columns at narrow widths.</li>
    </ul></li>
  <li><strong>Needs you</strong> (each has a default that keeps work moving if you say nothing):
    <ol>
      <li><b>Fix the still-open items before Codex round 4 reads the tree?</b> Recommendation: yes for the shared revision map on the track pages, which Codex would read as the same class as finding 1, and the two doc lines; the rest can ride. Default: round 4 runs on this tree, with them listed for it.</li>
      <li><b>Commit this wave</b> on <code>claude/vibetracks-dashboard</code>? Recommendation: yes, now, so a peer's <code>stash -u</code> cannot take 30 uncommitted paths and round 4 audits a commit. Default: left uncommitted, as this task's rules require.</li>
      <li><b>Merge the roadmap widget</b> (<code>claude/vibetracks-roadmap-r3</code>) into <code>claude/vibetracks-dashboard</code>? Recommendation: yes, after a Codex round passes, dropping its V1 bridge test in the same merge. Default: nothing is merged; the section keeps saying pending.</li>
      <li><b>Durable homes for loop files</b> now in agent worktrees (rig loop, grasp ledger and bench venv, kinsim loop dir)? Recommendation: a stable path per loop. Default: unchanged; a sweep would turn a row 'not reporting' honestly.</li>
    </ol></li>
  <li><strong>Deliberately not done:</strong> no commits, no vault edits. The still-open items were not fixed in this pass; the reports only record them. No new captures beyond verify-8's and verify-9's; older stills keep the switcher they were taken with, and the hero video still predates round 3.</li>
</ul>
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
    gen = datetime.fromisoformat(PROJ["generated_at"]).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    star = {tid: TRACK_PAGE[tid]["kpis"][0]["cells"] for tid in ORDER}

    hero = f"""
<figure class="hero">
  <video controls autoplay muted loop playsinline preload="auto" aria-label="Hero: home, Kinematic Sim, roadmap, back, rig, CAN 16, rename">
    <source src="{data_uri(MEDIA / 'hero-live-tracks.mp4', 'video/mp4')}" type="video/mp4"></video>
  <img id="hero-gif" class="gif hidden" alt="Hero as a GIF" src="{data_uri(MEDIA / 'hero-live-tracks.gif', 'image/gif')}">
  <figcaption><b>Home → Kinematic Sim → Roadmap → back → Rig → CAN 16 → rename (21 s, 1.25× speed, recorded after fix wave 1)</b>
  <span class="cap">Recorded headless from the running lane at http://127.0.0.1:4390 on live data. The blue dot is the pointer.
  The rename at the end was reverted through the ⋯ menu right after the recording; the note came back byte-identical. Out of date
  since: its grasping 6 / 10 came from the adapter's old copy of the bench's rules (it read 4 / 10 at round 3 and 6 / 10 again now,
  from the bench), '7 blocking' and the other Needs-you counts predate the one-source fix, and the switcher is three buttons.</span></figcaption>
</figure>"""

    home_summary = V4["counts"]["homeSummary"].split("\n")[2]
    home = (
        '<div class="g1">'
        + fig(str(MEDIA / "r6-report" / "r6-1440-home.png"), "Home now (1440 × 900, re-captured at 04:35 for round 6)",
              "'5 work tracks · 5 reporting · 2 quiet past their stall rule · 4 questions block a rung · questions not reported on "
              "1 track'. No switcher and no review bar under the table: B and C are retired (the capture measured 0 switchers, "
              "a 0 px bar and no sideways scroll). Needs-you cells: kinsim '1 blocking · 3 open', rig '2 blocking · 6 open', "
              "grasping '0 blocking · 7 open', detection '1 blocking · 3 open', pyblocks 'not reported'.")
        + "</div>" + '<div class="g2">'
        + fig(str(MEDIA / "verify-4" / "v4-1440-home-rest.png"), "Home, round 3 (1440 × 900)",
              f"'{home_summary}'. Columns: Status (state word + clamped detail), Progress (north star + sparkline), "
              "Current rung → next (the loop's own rung; Pyblocks has none and says 'latest wave … · no roadmap declared'), Last moved "
              "(one line, ellipsis when cut, 'stale' past the 24 h stall rule), Needs you ('0 blocking · 7 open' for grasping; "
              "'not reported' when unknown, never 0). The A · B · C pill in the review bar under the table is retired since round 6. CAN 12 and CAN 16 are not on this page.")
        + fig(str(MEDIA / "verify-4" / "v4-1280-home-rest.png"), "Home at 1280 × 800",
              "The last-moved labels cut with a visible '…' ('kinsim_eve…') and carry the whole name on hover; nothing runs out of its cell.")
        + "</div>" + '<div class="g1">'
        + fig("01-home.webp", "Home at the first drive (20:55), for comparison",
              "Grasping '6 / 10' and '7 blocking', '11 open' on kinsim and rig, three switcher buttons over the corner.")
        + "</div>" + home_rows()
    )

    gt = TRACKS["grasping"]
    grasp_page = fig(str(MEDIA / "verify-4" / "v4-1280-grasping-rest.png"), f"{gt['title']} · track page (round 3, 1280 × 800)",
                     f"Captured at 23:26, when the bench's verdict was {G_STAR_R3['value']:g} / {G_STAR_R3['of']}; it reads "
                     f"{G_STAR['value']:g} / {G_STAR['of']} now (top section). State: {gt['state']['word']}. Needs you · "
                     f"{gt['needs_you_count']['blocking']} blocking · {gt['needs_you_count']['open']} open. "
                     f"{len(gt['kpis'])} KPIs × {len(gt['kpis'][0]['values'])} iterations in the projection now; "
                     "the status word wraps inside its column instead of printing over the Progress number.")
    kinsim_now = fig(str(MEDIA / "r6-report" / "r6-1440-kinsim.png"), f"{TRACKS['kinsim']['title']} · track page (now, 1440 × 900)",
                     "Re-captured at 04:35 for round 6: no switcher, no review bar. 'Between waves · wave 4 closed 10-04 17:55 PDT', "
                     "'Needs you · 1 blocking · 3 open →', the purpose, then Key KPIs: 10 KPIs × 5 waves, W4 emphasised, north star "
                     "19 / 62 rungs green or done (+15 since start). BT2's 37.3 % → 41.8 % is in the warn colour because the ruler changed.")
    pages = '<div class="g2">' + "".join(
        grasp_page if tid == "grasping" else kinsim_now if tid == "kinsim" else
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
        fig("05-kinsim-needs.webp", "Needs you link (the other workflow's page, first drive)",
            f"At this capture the state line read 'Needs you · 1 blocking · 11 open →' and went to {k.get('needsHash')}. It now reads "
            "'1 blocking · 3 open', the numbers of the N6 page it opens (see the Needs-you report)."),
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
  <li>The revision is captured when editing starts and never adopted from a refreshed projection (Codex finding 6). A 409 keeps
      the editor open with your draft and offers 'Use theirs · Save mine anyway'; Enter and blur send nothing until you choose.</li>
  <li>The title is stored exactly as typed, spaces and tabs included (finding 8); unchanged saves nothing; an empty, whitespace-only
      or line-broken title is refused by the server and its message shows inline. The splice keeps the note's BOM, line endings and
      every byte outside the title. Deployments have no registry note, so they get no rename and no ⋯ menu.</li>
</ol>
<h3>Verified on the real note</h3>
<ul class="ls">
  <li>Before: <code>vibe-title: {esc(rn['before']['title'])}</code>, <code>vibe-id: {esc(rn['before']['id'])}</code>, sha256 <code>{esc(rn['before']['sha'][:16])}…</code></li>
  <li>After the double-click rename: <code>vibe-title: {esc(rn['after']['title'])}</code>, <code>vibe-id: {esc(rn['after']['id'])}</code>; the home row read '{esc(rn['after']['rowName'])}'.</li>
  <li>After renaming back through ⋯ → Rename track…: title '{esc(rn['restored']['title'])}', sha256 identical to before: <b>{esc(rn['restored']['identical'])}</b>.</li>
  <li>The two requests: {''.join(f'<code class="blk">POST {esc(p)}</code>' for p in posts)}</li>
</ul>
<h3>After the Codex fixes: a real concurrent rename (verify-5, isolated backend on a workspace copy)</h3>
<div class="g2">
{fig(str(MEDIA / "verify-5" / "v5-rename-1-conflict.png"), "Another writer renamed it while you typed",
     "Editing started at revision e01a6de4; a second writer saved 'Theirs (concurrent)'. Enter sent the edit's own revision, the server "
     "answered 409 and wrote nothing. The draft '  Mine  ' stays, with 'Use theirs · Save mine anyway'.")}
{fig(str(MEDIA / "verify-5" / "v5-rename-2-saved-mine.png"), "'Save mine anyway': saved on the revision it showed",
     "The note now holds '  Mine  ' with its spaces (rendered pre-wrap). Renaming back to 'Grasping' through the UI gave a sha256 "
     "identical to the original. Run on a copy, not your workspace.")}
</div>"""

    fw = fix_table() + """
<h3>Before and after</h3>""" + '<div class="g2">' + "".join([
        fig("fw-home-before-crop.webp", "Before: home rows",
            "Rung cells showed the newest iteration plus 'roadmap not reported yet'; Grasping read 'T1 · seed 1' beside a Tier 2 status."),
        fig("fw-home-after.webp", "After: home rows",
            "Each loop's own current rung and next; Grasping reads Tier 2 in both cells; Pyblocks says it has no rung instead of guessing."),
        fig("fw-detection-before.webp", "Before: Detection scorecard scrolled",
            "The first visible header was cut at the sticky column ('gForm…', 'egFormer-B0 RGB:') with no mark."),
        fig("fw-detection-after.webp", "After: the same scorecard at scrollLeft 92",
            "Columns snap to the sticky edge; every cut header ends in '…' with the whole marker on hover; the right edge fades while more scrolls."),
        fig("fw-rig-purpose-closed.webp", "Rig purpose, closed", "The whole 406-character paragraph, clamped to three lines by CSS with a visible '…' and 'more'."),
        fig("fw-rig-purpose-open.webp", "Rig purpose, open", "Four lines and 'less'; aria-expanded follows."),
        fig("fw-home-maxscroll.webp", "Home at max scroll", "The review switcher sits below the last row and the Reload line."),
        fig("fw-kinsim-maxscroll.webp", "Kinematic Sim at max scroll", "The switcher clears the links block at the bottom of the page."),
    ]) + "</div>" + """
<h3>Times: before and after (fixed in fix wave 2)</h3>""" + '<div class="g2">' + "".join([
        fig("fw-kinsim-stateline.webp", "Before: Kinematic Sim state line",
            "'wave 4 closed 10-04 17:55 PDT' and 'since 10-05 00:55 UTC' are the same moment in two zones on one line."),
        fig("fw2-kinsim-stateline.png", "After: the same line in one zone",
            "'wave 4 closed 10-04 17:55 PDT · … · since 10-04 17:55 PDT'. The Needs-you line beside it now reads '1 blocking · 3 open', the page's own numbers."),
        fig("fw-grasping-iteration-times.webp", "Before: Grasping, latest wave, evidence times",
            "The gallery reads local '2026-10-04 19:14'; the runs read '2026-10-05 03:28', which is UTC with the zone dropped (10-04 20:28 PDT)."),
        fig("fw2-grasping-iteration-times.png", "After: the same list",
            "The gallery reads '10-04 19:14 PDT' and the runs '10-04 20:28 PDT' / '20:31 PDT': one zone, named, and the raw ISO on hover."),
    ]) + "</div>" + '<div class="g1">' + fig("verify-2/times-item_grasping_20261005T032840Z_M3_bandit.png",
        "After, checked by the verifier: one grasping run's own page",
        "'run · pass · 10-04 20:28 PDT · T1 · seed 2'. The episodes file name below still carries the ledger's UTC stamp (20261005T032840Z); it is a path shown verbatim, not a displayed time.") + "</div>"

    fw += "<h3>Fix wave 3</h3>" + '<div class="g2">' + "".join([
        fig("r2-ui-home.png", "Home after fix wave 3: the switcher is one pill",
            "'Proposal A · Drill-down pages ▾' at the bottom right, 211 × 31 px, where three labelled buttons used to sit. "
            "Needs-you cells: " + "; ".join(f"{t} '{c}'" for t, c in _home_cells().items()) + "."),
        fig("r2-ui-switcher-open.png", "The pill, opened",
            "A click opens A · B · C upward; a pick, Escape or an outside click closes it, and the pick survives a reload."),
        fig("r2-ui-stale-home.png", "Proven subline, proven in flight (not live data)",
            "The roadmap stub was patched with page.route to return green 1 + done 3 and a 'stale' warning: every row reads "
            "'4 proven (not current)'. The rung column shows the patched stub's own placeholder. Unpatched, no proven text appears."),
        fig("r2-ui-fake-kinsim.png", "The same patch on kinsim's north-star line",
            "'North star 19 / 62 Rungs green or done · +15 over 4 waves since start (freeze) · 4 proven'."),
        fig("verify-3/v3-track-can16.png", "CAN 16: 'Needs you · not reported'",
            "Was 'nothing open' from old child counts. The hover says needs.py reads no questions per deployment and points to the rig "
            "loop's page."),
        fig("r2-ui-rig-purpose-900.png", "Rig purpose at 900 px: code spans whole",
            "`ladder.json` and `loop-status.json` stay in one piece. Also visible, and still open: the scorecard at this width shows "
            "no iteration columns, only KPI | Trend | Target | Status."),
    ]) + "</div>" + '<div class="g1">' + fig("verify-3/v3-pill-over-cell-grasping.png", "Fix wave 3's open item: the pill over grasping's KPI cells",
            "At rest the collapsed pill sat on the '87.4 %' cell. Fixed in round 3 by the review bar (below).") + "</div>"
    fw += "<h3>Round 3</h3>" + '<div class="g2">' + "".join([
        fig(str(MEDIA / "verify-4" / "v4-1280-home-maxscroll.png"), "Review bar at 1280 × 800, max scroll",
            "The scroll area ends where the 40 px bar starts; the pill sits in the bar, right-aligned, on the page's own background. "
            f"verify-4: {len(V4_STATES)} states, {V4_HITS} hits."),
        fig(str(MEDIA / "verify-4" / "v4-1440-detection-maxscroll.png"), "Detection at max scroll",
            "In fix wave 3 the pill covered '2 / 12' here at rest; the scorecard now stops above the bar."),
        fig("r3-ui-1440-switcher-open.png", "The pill, opened, in the bar",
            "A · B · C grow upward as a transient menu; the bar stays 40 px, so the scroller does not jump."),
        fig(str(MEDIA / "verify-4" / "v4-kpi-cell-focused.png"), "Tab reaches a KPI cell",
            "11 Tabs from the title land on 'Rungs green or done · Start: 4 / 62 · open evidence' with a 2 px focus ring."),
        fig(str(MEDIA / "verify-4" / "v4-kpi-cell-enter-evidence.png"), "Enter opens its evidence",
            "`#vt?track=kinsim&kpi=rungs_green&iteration=start`: 'Start … freeze 89ece43f · 4 rungs done at baseline'."),
    ]) + "</div>"

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vibe Tracks live tracks</title>
<style>{CSS}{FB.CSS}{FB_LIGHT}</style></head>
<body><div class="wrap">

<header class="top">
  <div class="date">2026-10-05 · Codex round 3's findings fixed and re-measured, before Codex round 4</div>
  <h1>Vibe Tracks: your five work tracks, live</h1>
  <p class="verdict">Codex round 3 ({esc(AUDIT3['auditor'])}, on a frozen snapshot of {AUDIT3['audited_sha']}) returned FAIL with
  {len(AUDIT3_ROWS)} new findings; all {AUDIT3_PASS} are fixed and re-measured, {_nums(AUDIT3_WHERE['e0bd8e5'])} in e0bd8e5 and
  {_nums(AUDIT3_WHERE['this wave'])} in this wave (uncommitted). Grasping's north star and the rows beside it now come from the same
  ledger bytes and still read {G_STAR['value']:g} / {G_STAR['of']}, the bench's own verdict; its gallery opens; a reload recovers a
  retargeted link in snapshot mode; Needs links open only the file their document recorded. Variant A is the only dashboard. Still
  open, none blocking: the track pages' /media URLs take their revision from one shared map. Codex round 4 runs next; nothing here
  is Codex-approved yet.</p>
  <p class="built">Built against the projection the backend served at {esc(gen)}, with the bench's own gallery run the same minute in its
  own venv ({ORACLE_NOW['n_runs']} ledger rows, {len(ORACLE_NOW['beaten'])} beaten: they agree). Tree: e0bd8e5 (Codex round 3's findings 3 and 4,
  committed) plus this wave's fixes for 1, 2 and 5, uncommitted, in /home/bam/vibetracks-dashboard. verify-9, a measure-only pass by a
  separate Claude agent, re-measured them: pytest {esc(AUDIT3['checks']['pytest'])}, backend {esc(AUDIT3['checks']['backend'])}, tsc
  {esc(AUDIT3['checks']['tsc'])}, browser {esc(AUDIT3['checks']['browser_checks'].split(';')[0])}. Home and kinsim's track page were
  re-captured at 04:35 for round 6; the round-3 stills are verify-8's and verify-9's; older stills show the switcher they were taken with.
  {sum(c["match"] for c in CHECKS)} of {len(CHECKS)} KPI values matched their loops' own files at the first drive (the grasping ones have moved
  since, as its ledger grew). Nothing committed. This page is over the desktop preview's size cap, so open it in the browser. The
  Needs-you page has its own report: <code>{esc(NEEDS_REPORT)}</code>.</p>
  <div class="launch"><pre id="launch-cmd">{esc(LAUNCHER)}</pre><button id="copy-launch" type="button">Copy</button></div>
</header>

<nav class="toc" aria-label="Sections">
  <a href="#audit">This round</a><a href="#grasping">Grasping</a><a href="#watch">Watch</a><a href="#fixwave">Fix waves</a><a href="#home">Home</a><a href="#pages">Track pages</a><a href="#drill">Drill-down</a>
  <a href="#tracks">Per track</a><a href="#checks">Numbers checked</a><a href="#rename">Rename</a><a href="#live">Live vs stale</a>
  <a href="#issues">Issues</a><a href="#decide">Decide</a>
</nav>

{section("audit", "This round, and the independent audit", "", audit3_html(), 1)}
{section("grasping", "Grasping's north star is the bench's own verdict, and it moves with the ledger", "Round 3's headline correction, re-read now: same rules, more runs.", grasping_html(), 2)}
{section("watch", "Watch first", "One recorded walk through the real app: pick a track, read its KPIs, open the roadmap section, go back, open the rig and CAN 16, rename a track. Recorded after fix wave 1, before round 3: its grasping 6 / 10 is the old rule copy's, not today's bench verdict.", hero, 3)}
{section("fixwave", "What changed in the fix waves", "Each finding, re-measured independently after the lanes reported done (a-i in fix wave 1, b and j in fix wave 2, k-n in fix wave 3, o-t in round 3). The verifiers did not write the fixes. The A · B · C switcher these stills show was retired in round 6.", fw, 4)}
{section("home", "Home: the work tracks", "One calm row per top-level track, in registry priority order. It adapts to however many track notes exist, so a sixth track is one new note.", home, 5)}
{section("pages", "Each track page", "Title (renamable) → one state line → Needs you → purpose → Key KPIs → Roadmap. The rig adds its deployments under the roadmap. Kinsim's capture is this round's; grasping's is round 3's; the others are from the first drive, and their Needs-you numbers predate the one-source fix.", pages, 6)}
{section("drill", "Drilling in: KPIs, roadmap, needs, evidence", "Kinsim end to end, then the rig's deployments.", drill, 7)}
{section("tracks", "Per track: sources, freshness, KPIs, roadmap, gaps", f"Read from the projection the backend served at {esc(gen)} (<code>{esc(PROJ_PATH.name)}</code>). File times are local, with their zone.", track_table(), 8)}
{section("checks", "Numbers checked against the source files", "Each value recomputed by a separate script (<code>crosscheck.py</code> in the media folder) straight from the loop's own files, not from the adapter, then compared with what the dashboard served at the first drive. 'Projection now' is what the projection used for this page shows; it is not re-derived from source. Grasping's north star is checked against the bench itself in the top section.", checks_table(), 9)}
{section("rename", "Renaming a track", "", rename, 10)}
{section("live", "What is live, what is stale, and why", "", live_status(), 11)}
{section("issues", "Issues still open", "The verifiers changed no product code; these are for their owners. Fixed issues moved to the fix-wave table above.", '<ol class="issues">' + ''.join(f'<li><b>{inline_md(t)}</b>{inline_md(d)}</li>' for t, d in ISSUES) + '</ol>', 12)}

<section id="decide">
  <h2>Decision surface</h2>
  <div class="decide">{DECISION_R7}</div>
  <details class="raw"><summary>Round 6's decision packet, before Codex round 3 (superseded: round 3 ran, and its open items closed in e0bd8e5)</summary><div class="decide">{DECISION_R6}</div></details>
  <details class="raw"><summary>Round 5's decision packet, after Codex round 2 (superseded: its siblings and 390 px pages are closed)</summary><div class="decide">{DECISION_R5}</div></details>
  <details class="raw"><summary>Round 4's decision packet, after Codex round 1 (superseded)</summary><div class="decide">{DECISION}</div></details>
  {FB.ui(REPORT_NAME, noun="section", total=12)}
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
