"""Adapter for the Object Detection & Hyperspectral work track (vibe-id ``detection``).

Interface: docs/dashboard/ADAPTERS.md (section ``detection``); the discovery behind it is
docs/dashboard/track-discovery-2026-10-04.json key ``scout:detection``.

What this loop has today, honestly: a fresh PLAN (the H0-H9 ladder in ``ladder_data.py`` and the vault plan note, both
2026-10-04) and a STALE run history (the SpectralWaste Table IV repro queue of 2026-07-10/11). No loop agent has
started, so there is no loop-status, ladder status or run ledger to read. The adapter therefore reads:

- ``detection_queue_log``: ``logs/queue.log``, START/DONE lines per config run. It is lossy: the main queue held it
  open with ``>`` while ``run_retry.sh`` appended with ``>>``, so the queue's later writes overwrote some retry START
  lines. The per-run ``logs/<tag>.log`` files beside it fill those gaps.
- ``detection_logs_dir``: the per-run logs (``logs/<tag>.log``: epoch lines, NaN losses, the W&B run id). Required:
  without them no run's validity is known, so the track is not reporting rather than calling runs valid.
- ``detection_wandb_dir``: ``wandb/run-<YYYYMMDD_HHMMSS>-<id>`` directory names (a run's start time when queue.log lost
  its START line);
- ``detection_compile_results``: ``compile_results.py`` (the 12 Table IV paper targets, parsed with ``ast``, never
  executed); ``detection_queue_script``: ``run_repro_queue.sh`` (its ``DATA=`` line, for the drive check);
- ``detection_ladder`` (``ladder_data.py``: rungs, the KPI table and the H1 tolerance, parsed with ``ast``, never
  imported: it is an untracked file in a worktree, and importing would execute it);
- ``detection_plan_note``: the vault plan note's ``## Needs you`` list (the only place the open decisions and their
  defaults are written down);
- ``detection_reports_dir``: bam_ws ``reports/``, listed only for the roadmap report and loop work order (evidence).

Every input comes from the note's ``vibe-sources`` and nowhere else (``READS``): a key the note does not declare is read
as missing, because the build would not notice that file change.

Iterations are runs (unit ``session``): one per config run of the repro queue, ordered by start time, plus one for the
plan written on 2026-10-04. Truth rules (PROJECTION.md) hold throughout: every number names its file, missing values
are null with a note, and a single-seed result reads "unconfirmed · repeat needed".
"""

from __future__ import annotations

import ast
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import local_time, not_reporting, skeleton
from .base import rung as make_rung

#: Every sources.py key this adapter opens, and what it is to the loop (base.py READ_ROLES). WHY the plan, the ladder
#: and the scripts are "input" and not "heartbeat": the loop has never started, and a plan written today must not make
#: a run history last touched in July read as a live loop.
READS = {"detection_queue_log": "heartbeat", "detection_logs_dir": "heartbeat", "detection_wandb_dir": "heartbeat",
         "detection_compile_results": "input", "detection_queue_script": "input", "detection_ladder": "input",
         "detection_plan_note": "input", "detection_reports_dir": "evidence"}
#: Reports the planning session wrote for this track, searched in the bam_ws ``reports/`` directory (newest wins).
REPORT_GLOBS = (("detection-roadmap-report", "hyperspectral-roadmap-*.html", "report", "Hyperspectral roadmap report"),
                ("detection-work-order", "hyperspectral-loop-work-order-*.md", "text", "Loop work order (brief for the loop agent)"))

ANSI = re.compile(r"\x1b\[[0-9;]*m")
QUEUE_LINE = re.compile(r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+(?P<event>START|DONE)\s+(?P<tag>\S+)"
                        r"(?:\s+rc=(?P<rc>-?\d+))?(?:.*?test/miou:\s*(?P<miou>[0-9.]+(?:[eE][-+]?\d+)?))?")
TAG = re.compile(r"^(?P<idx>\d\d)(?P<retry>r\d+[a-z]*)?_(?P<model>[^.]+)\.(?P<input>[^.]+)\.(?P<target>.+)$")
EPOCH = re.compile(r"^epoch:\s*(?P<n>\d+)\s*\|\s*train/loss:\s*(?P<train>\S+)\s*\|\s*val/loss:\s*(?P<val>\S+)"
                   r"\s*\|\s*val/miou:\s*(?P<miou>\S+)")
WANDB_URL = re.compile(r"https://wandb\.ai/\S+?/runs/(?P<id>[a-z0-9]+)")
WANDB_DIR = re.compile(r"^run-(?P<ts>\d{8}_\d{6})-(?P<id>[a-z0-9]+)$")
TOLERANCE = re.compile(r"±\s*(?P<tol>\d+(?:\.\d+)?)\s*(?:test\s+)?mIoU")
RUNG_ID = re.compile(r"\bH\d\b")
BLOCKS = re.compile(r"\bblock(?:s|ed|ing)?\s+H\d(?:(?:,\s*|\s+and\s+|\s+or\s+)H\d)*")

# --------------------------------------------------------------------------------------------- small helpers


def _num(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _finite(value: float | None) -> bool:
    return value is not None and value == value and value not in (float("inf"), float("-inf"))


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone().isoformat(timespec="seconds") if moment else None


def _mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def _hm(moment: datetime | None) -> str:
    return local_time(moment, missing="unknown time")


def _pts(fraction: float | None) -> float | None:
    """A 0-1 mIoU as points (the paper's unit), 2 decimals."""

    return round(fraction * 100, 2) if fraction is not None else None


def _literal(node: ast.AST) -> Any:
    """ast.literal_eval, plus ``dict(key=literal, ...)`` calls (ladder_data.RUNGS uses them)."""

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict" and not node.args:
        return {keyword.arg: _literal(keyword.value) for keyword in node.keywords if keyword.arg}
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [_literal(element) for element in node.elts]
        return items if isinstance(node, ast.List) else tuple(items)
    return ast.literal_eval(node)


def _module_assignments(path: Path, names: tuple[str, ...]) -> dict[str, Any]:
    """Top-level ``NAME = <literal>`` assignments of a Python file, read without executing it."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, Any] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            name = statement.targets[0].id
            if name in names:
                try:
                    found[name] = _literal(statement.value)
                except (ValueError, TypeError, SyntaxError):
                    pass
    return found


def _locate(sources: dict[str, str], key: str) -> Path | None:
    """A declared key's path, or None. WHY no fallback to the machine's sources map: an input the note does not declare
    can change without the build rerunning this adapter, so the row would silently go stale."""

    return Path(sources[key]) if sources.get(key) else None


def _provenance(source: str | Path | None, derived: str) -> dict[str, Any]:
    return {"snapshot": None, "pointer": None, "source": str(source) if source else None, "derived": derived}


# --------------------------------------------------------------------------------------------- reading the loop's files


def read_paper_targets(compile_results: Path) -> dict[str, tuple[str, float | None]]:
    """compile_results.PAPER: run tag -> (paper label, Table IV test mIoU in points)."""

    found = _module_assignments(compile_results, ("PAPER",)).get("PAPER")
    if not isinstance(found, dict):
        return {}
    return {str(tag): (str(row[0]), float(row[1]) if row[1] is not None else None)
            for tag, row in found.items() if isinstance(row, (tuple, list)) and len(row) == 2}


def read_ladder(ladder: Path) -> dict[str, Any]:
    """ladder_data.RUNGS / KPIS, plus the H1 reproduction tolerance parsed from H1's gate text."""

    found = _module_assignments(ladder, ("RUNGS", "KPIS"))
    rungs = [rung for rung in found.get("RUNGS") or [] if isinstance(rung, dict) and isinstance(rung.get("id"), str)]
    tolerance = None
    for rung in rungs:
        if rung["id"] == "H1":
            match = TOLERANCE.search(str(rung.get("gate") or "")) or TOLERANCE.search(str(rung.get("gate_short") or ""))
            tolerance = float(match.group("tol")) if match else None
    return {"rungs": rungs, "kpis": found.get("KPIS") or [], "tolerance": tolerance}


def frontier_rung(ladder: dict[str, Any]) -> dict[str, Any] | None:
    """The rung the plan says the loop is on: the first ``H<n>`` in ladder_data.KPIS' S2 "Frontier gate" row's
    *today* column ("H1: 2 of 12 configs reproduced"). WHY that row and not the lowest rung id: no rung status is
    stored yet (H0 and H1 both need nothing), and that row is where the plan itself names the current rung."""

    by_id = {row["id"]: row for row in ladder.get("rungs") or []}
    for kpi in ladder.get("kpis") or []:
        if isinstance(kpi, (list, tuple)) and len(kpi) >= 4 and str(kpi[0]).startswith("S2"):
            match = RUNG_ID.search(str(kpi[3]))
            if match and match.group(0) in by_id:
                return by_id[match.group(0)]
    return None


def _rung(ladder: dict[str, Any], frontier_row: dict[str, Any] | None, progress: str | None) -> dict[str, Any] | None:
    """``track.rung``: the frontier rung, and the rungs whose ``needs_rungs`` name it (what the ladder says comes
    after it), in ladder_data.py's own short names."""

    if frontier_row is None:
        return None
    current = " · ".join(part for part in (frontier_row["id"], frontier_row.get("short"), progress) if part)
    after = [f"{row['id']} {row.get('short') or ''}".strip() for row in ladder.get("rungs") or []
             if frontier_row["id"] in (row.get("needs_rungs") or [])]
    return make_rung(current, ", ".join(after) or None, "ladder_data.py (RUNGS, KPIS S2) + queue.log")


DEFAULT_MARK = "*Default if silent:*"

#: A sentence ends at . ! or ? (plus closing quotes/brackets and any citation links glued on, ``".[[note|1]]``)
#: before whitespace and a capital, a quote, a bracket or bold, or at the end of the text.
SENTENCE_END = re.compile(r"[.!?][\"”’')\]]*(?:\[\[[^\]]*\]\]|\[\d+\]\([^)]*\))*(?=\s+[A-Z(`'\"“*\[]|\s*$)")
FIRST_BULLET = re.compile(r"\s*[-*]\s+[^\n]*")


def first_sentence(text: str) -> int:
    """Where ``text``'s first sentence ends (an index into ``text``): through its first sentence end, else through
    its first bullet line when it opens with a bullet, else the whole text. Never rewrites a character."""

    bullet = FIRST_BULLET.match(text)
    if bullet:
        return bullet.end()
    match = SENTENCE_END.search(text)
    return match.end() if match else len(text)


def parse_needs_section(text: str) -> list[dict[str, Any]]:
    """The plan note's ``## Needs you`` numbered list, every part verbatim (the one parser of that section).

    Each entry: ``n`` (its number), ``body_md`` (everything after ``N. `` up to a bold aside after a blank line),
    ``before_md`` (the body before ``*Default if silent:*``), ``title_md`` (the bold lead's inner text, or None),
    ``rest_md`` (``before_md`` after the bold lead), ``question_md`` (``rest_md`` up to a nested bullet list, which is
    the reasoning, not the question), ``default_md`` (the text after the marker, or None when the item states none)
    and ``blocks`` (the rung ids named after "block(s)"). ``ask_md`` is the decision as the note words it: the bold
    lead together with the first sentence (or first bullet) after it, a verbatim slice of ``before_md``;
    ``ask_rest_md`` is the rest of ``question_md`` after that sentence (None when nothing is left). WHY the lead plus
    a sentence: a lead alone ("**Data.**") is a heading, not a question Zach can answer, and a two-sentence or cleaned
    summary would be words the note never wrote. ``read_needs`` (this adapter) and /needs
    (vibetracks/dashboard/needs.py) both build on it, so the home count and the needs page read the same items.
    """

    section = re.search(r"^## Needs you\s*$(?P<body>.*?)(?=^## |\Z)", text, re.M | re.S)
    if not section:
        return []
    parsed = []
    for item in re.split(r"^(?=\d+\.\s)", section.group("body"), flags=re.M):
        head = re.match(r"^(?P<n>\d+)\.\s+(?P<rest>.*)", item, re.S)
        if not head:
            continue
        # A section-level aside ("**For your information ...**") trails the last item after a blank line; it is not
        # part of that item's question or default.
        body = re.split(r"\n\s*\n(?=\*\*)", head.group("rest").rstrip(), maxsplit=1)[0].rstrip()
        before, marker, after = body.partition(DEFAULT_MARK)
        title = re.match(r"\*\*(?P<t>[^*]+)\*\*\s*(?P<rest>.*)", before.strip(), re.S)
        rest = title.group("rest") if title else before
        # WHY only rungs after "block(s)": the items also name rungs in passing ("H0–H7 never touch the camera"),
        # and counting those would mark a question as blocking work it does not hold.
        held = " ".join(match.group(0) for match in BLOCKS.finditer(before))
        default_md = after.strip() if marker else None
        # The ask, sliced from the same stripped text the title was matched on, so it is the note's characters.
        stripped = before.strip()
        offset = title.start("rest") if title else 0
        remainder = stripped[offset:]
        question = remainder if FIRST_BULLET.match(remainder) else re.split(r"\n\s*[-*]\s", remainder, maxsplit=1)[0]
        end = first_sentence(question)
        ask_md = stripped[: offset + end].rstrip()
        ask_rest = question[end:].strip()
        parsed.append({
            "n": head.group("n"),
            "body_md": body,
            "before_md": before,
            "title_md": title.group("t") if title else None,
            "rest_md": rest,
            "question_md": re.split(r"\n\s*[-*]\s", rest, maxsplit=1)[0],
            "default_md": default_md or None,
            "after_md": after if marker else "",
            "blocks": sorted(set(RUNG_ID.findall(held)), key=lambda rung: int(rung[1:])),
            "ask_md": ask_md,
            "ask_rest_md": ask_rest or None,
        })
    return parsed


def read_needs(plan_note: Path) -> list[dict[str, Any]]:
    """The plan note's ``## Needs you`` numbered list -> NeedsYou items (q, default, blocks = rungs it names)."""

    needs = []
    for entry in parse_needs_section(plan_note.read_text(encoding="utf-8")):
        before, after = entry["before_md"], entry["after_md"]
        lead = _clean_markdown(entry["title_md"]).rstrip(".") if entry["title_md"] is not None else ""
        # A nested bullet list is the reasoning behind the question, not the question: stop before it.
        rest = _clean_markdown(entry["question_md"])
        # The question is its first two sentences; an explicit ellipsis marks a cut, never a silent trim.
        first = " ".join(re.split(r"(?<=\.)\s", rest, maxsplit=2)[:2])
        first = first if len(first) <= 400 else first[:399].rstrip() + "…"
        question = f"{lead}: {first}" if lead else first
        default = _clean_markdown(after.strip().splitlines()[0]) if after.strip() else None
        needs.append({"id": f"plan-{entry['n']}", "q": question, "blocks": entry["blocks"], "default": default or None,
                      "applies": None})
    # WHY blocking first: PROJECTION.md orders needs_you blocking ones first.
    return sorted(needs, key=lambda need: not need["blocks"])


def _clean_markdown(text: str) -> str:
    text = re.sub(r"\[\[[^\]|]*\|\d+\]\]", "", text)  # footnote-style wikilinks [[note|1]]
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[(\d+)\]\([^)]*\)", "", text)  # numbered source links
    text = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def read_runs(queue_log: Path, logs_dir: Path, wandb_dir: Path | None) -> list[dict[str, Any]]:
    """Every config run the repro queue left: queue.log events merged with the per-run logs in ``logs_dir``."""

    runs: dict[str, dict[str, Any]] = {}

    def run(tag: str) -> dict[str, Any]:
        if tag not in runs:
            runs[tag] = {"tag": tag, "start": None, "start_source": None, "done": None, "rc": None, "test": None,
                         "log": logs_dir / f"{tag}.log", "epochs": 0, "nan_epochs": 0, "best_val": None,
                         "last_epoch": None, "sanitized": 0, "skipped": 0, "wandb_id": None, "wandb_url": None,
                         "log_mtime": None}
        return runs[tag]

    for line in queue_log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = QUEUE_LINE.match(line.strip())
        if not match or not TAG.match(match.group("tag")):
            continue
        entry = run(match.group("tag"))
        moment = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")
        if match.group("event") == "START":
            entry["start"], entry["start_source"] = moment, "queue.log START"
        else:
            entry["done"] = moment
            entry["rc"] = int(match.group("rc")) if match.group("rc") is not None else None
            entry["test"] = _num(match.group("miou"))

    for log in sorted(logs_dir.glob("*.log")):
        if log.name != queue_log.name and TAG.match(log.stem):
            run(log.stem)

    wandb_starts: dict[str, datetime] = {}
    if wandb_dir is not None and wandb_dir.is_dir():
        for child in wandb_dir.iterdir():
            match = WANDB_DIR.match(child.name)
            if match:
                wandb_starts[match.group("id")] = datetime.strptime(match.group("ts"), "%Y%m%d_%H%M%S")

    for entry in runs.values():
        log: Path = entry["log"]
        if not log.is_file():
            continue
        entry["log_mtime"] = _mtime(log)
        for raw in log.read_text(encoding="utf-8", errors="replace").splitlines():
            line = ANSI.sub("", raw).strip()
            epoch = EPOCH.match(line)
            if epoch:
                entry["epochs"] += 1
                entry["last_epoch"] = int(epoch.group("n"))
                losses = (_num(epoch.group("train")), _num(epoch.group("val")))
                if not all(_finite(loss) for loss in losses):
                    entry["nan_epochs"] += 1
                val = _num(epoch.group("miou"))
                if _finite(val) and (entry["best_val"] is None or val > entry["best_val"]):
                    entry["best_val"] = val
                continue
            if line.startswith("warning: sanitized"):
                entry["sanitized"] += 1
            elif line.startswith("warning: skipped"):
                entry["skipped"] += 1
            url = WANDB_URL.search(line)
            if url and entry["wandb_id"] is None:
                entry["wandb_id"], entry["wandb_url"] = url.group("id"), url.group(0)
        if entry["start"] is None and entry["wandb_id"] in wandb_starts:
            entry["start"], entry["start_source"] = wandb_starts[entry["wandb_id"]], "wandb run directory"

    ordered = list(runs.values())
    # WHY order by start: overlapping runs (the queue and its retries ran side by side) need one shared x-axis.
    ordered.sort(key=lambda entry: (entry["start"] or entry["log_mtime"] or entry["done"] or datetime.max, entry["tag"]))
    for entry in ordered:
        parts = TAG.match(entry["tag"])
        entry["idx"] = parts.group("idx") + (parts.group("retry") or "")
        entry["base"] = f"{parts.group('idx')}_{parts.group('model')}.{parts.group('input')}.{parts.group('target')}"
        entry["hyper"] = "hyper" in parts.group("input")
        entry["finished"] = entry["done"] is not None and entry["rc"] == 0 and entry["test"] is not None
        entry["valid"] = entry["finished"] and entry["nan_epochs"] == 0 and entry["sanitized"] == 0 and entry["skipped"] == 0
    return ordered


def _data_path(script: Path | None) -> str | None:
    """The SpectralWaste data path the queue script trains from (its ``DATA=`` line)."""

    try:
        match = re.search(r"^DATA=(\S+)", script.read_text(encoding="utf-8"), re.M) if script else None
    except OSError:
        return None
    return match.group(1).strip("'\"") if match else None


def _reports_dir(sources: dict[str, str]) -> Path | None:
    return _locate(sources, "detection_reports_dir")


# --------------------------------------------------------------------------------------------- the track


def _run_outcome(entry: dict[str, Any], paper: float | None, tolerance: float | None) -> str:
    if entry["finished"] and not entry["valid"]:
        why = [f"NaN loss in {entry['nan_epochs']} of {entry['epochs']} epochs"] if entry["nan_epochs"] else []
        why += [f"{entry['sanitized']} sanitized-input warnings"] if entry["sanitized"] else []
        why += [f"{entry['skipped']} skipped-batch warnings"] if entry["skipped"] else []
        return "invalid · " + ", ".join(why)
    if entry["valid"]:
        if paper is None or tolerance is None:
            return "valid · no paper target to compare"
        delta = _pts(entry["test"]) - paper
        return "reproduced" if abs(delta) <= tolerance else f"valid · outside ±{tolerance:g}"
    if entry["done"] is not None:
        return f"ended rc={entry['rc']}" + (f" at epoch {entry['last_epoch']}" if entry["last_epoch"] is not None else "")
    stopped = f" · log quiet since {_hm(entry['log_mtime'])}" if entry["log_mtime"] else ""
    progress = (f" · {entry['epochs']} epoch{'s' if entry['epochs'] != 1 else ''} logged" if entry["epochs"]
                else " · no epoch logged")
    return "no DONE line" + progress + stopped


def build_track(work_track: Any, sources: dict[str, str]) -> dict[str, Any]:
    queue_log = _locate(sources, "detection_queue_log")
    logs_dir = _locate(sources, "detection_logs_dir")
    track = skeleton(work_track, unit="session")
    missing = [key for key, path in (("detection_queue_log", queue_log), ("detection_logs_dir", logs_dir)) if path is None]
    if missing:
        return not_reporting(work_track, f"{' and '.join(missing)} not declared in vibe-sources")
    if not queue_log.is_file():
        return not_reporting(work_track, f"the repro queue log {queue_log} is missing")

    compile_results = _locate(sources, "detection_compile_results")
    try:
        paper = read_paper_targets(compile_results) if compile_results else {}
    except (OSError, SyntaxError):
        paper = {}
    configs = [tag for tag in paper if re.match(r"^\d\d_", tag)]
    ladder_path = _locate(sources, "detection_ladder")
    ladder: dict[str, Any] = {"rungs": [], "kpis": [], "tolerance": None}
    ladder_mtime = None
    if ladder_path and ladder_path.is_file():
        try:
            ladder = read_ladder(ladder_path)
            ladder_mtime = _mtime(ladder_path)
        except (OSError, SyntaxError):
            pass
    tolerance = ladder["tolerance"]
    plan_path = _locate(sources, "detection_plan_note")
    needs: list[dict[str, Any]] | None = None
    plan_mtime = None
    if plan_path and plan_path.is_file():
        try:
            needs = read_needs(plan_path)
            plan_mtime = _mtime(plan_path)
        except OSError:
            needs = None

    runs = read_runs(queue_log, logs_dir, _locate(sources, "detection_wandb_dir"))

    # ---- iterations: one per run, plus the plan, in time order
    iterations: list[dict[str, Any]] = []
    rows: list[tuple[str, dict[str, Any] | None, datetime | None]] = []
    for entry in runs:
        rows.append(("run", entry, entry["start"]))
    plan_when = ladder_mtime or plan_mtime
    if plan_when is not None:
        rows.append(("plan", None, plan_when))
    rows.sort(key=lambda row: (row[2] or datetime.max))

    evidence_by_iteration: dict[str, list[dict[str, Any]]] = {}
    by_kpi: dict[str, list[str]] = {key: [] for key in ("hsi_test_miou", "h1_reproduced", "run_test_miou", "guardrails",
                                                        "valid_runs", "nan_runs", "run_hours", "needs_you")}
    media: dict[str, Any] = {}
    series: dict[str, list[dict[str, Any]]] = {key: [] for key in by_kpi}

    started = valid = nan_runs = 0
    reproduced: set[str] = set()
    graded: set[str] = set()
    best_hsi: tuple[float, str] | None = None
    last_run: dict[str, Any] | None = None
    queue_src = str(queue_log)

    def value(kpi: str, iteration: str, number: float | None, *, note: str | None = None, of: float | None = None,
              n: int | None = None, evidence: list[str] | None = None) -> None:
        series[kpi].append({"iteration": iteration, "value": number, "of": of, "n": n, "spread": None,
                            "measured": number is not None, "note": note,
                            "evidence": [item for item in (evidence or []) if item in by_kpi[kpi]]})

    for kind, entry, when in rows:
        if kind == "plan":
            iteration_id = f"plan-{when.date().isoformat()}"
            later_runs = [run for run in runs if run["start"] and run["start"] > when]
            marker = (f"plan written: ladder {ladder['rungs'][0]['id']}–{ladder['rungs'][-1]['id']} "
                      f"({len(ladder['rungs'])} rungs), KPI slots S1–S{len(ladder['kpis'])}" if ladder["rungs"]
                      else "plan written (ladder_data.py unreadable)")
            marker += " · no run since" if not later_runs else ""
            iterations.append({"id": iteration_id, "label": f"plan {when.strftime('%m-%d')}", "date": when.date().isoformat(),
                               "marker": marker, "provenance": _provenance(ladder_path, "file mtime of ladder_data.py")})
            items = []
            if ladder["rungs"]:
                items.append({"id": "plan-ladder", "iteration": iteration_id, "kind": "note",
                              "title": "Ladder H0–H9 (ladder_data.py)", "when": _iso(ladder_mtime),
                              "metrics": {"rungs": len(ladder["rungs"]), "KPI slots": len(ladder["kpis"]),
                                          "H1 tolerance (± pts)": tolerance},
                              "status": "planned", "media": [],
                              "links": [{"label": "ladder_data.py (untracked, in a worktree)", "kind": "path", "value": str(ladder_path)}],
                              "note": "Rung status is not stored as data anywhere yet; no rung is recorded green."})
                by_kpi["h1_reproduced"].append("plan-ladder")
            if needs is not None:
                items.append({"id": "plan-note", "iteration": iteration_id, "kind": "note",
                              "title": "Plan note · Needs you", "when": _iso(plan_mtime),
                              "metrics": {"open decisions": len(needs),
                                          "blocking a rung": sum(1 for need in needs if need["blocks"])},
                              "status": "open" if needs else "empty", "media": [],
                              "links": [{"label": "vault plan note", "kind": "path", "value": str(plan_path)}],
                              "note": "Decisions as the plan recorded them on its date; later answers elsewhere are not read."})
                by_kpi["needs_you"].append("plan-note")
            reports = _reports_dir(sources)
            for media_id, pattern, media_kind, label in REPORT_GLOBS:
                found = sorted(reports.glob(pattern), key=lambda path: path.stat().st_mtime) if reports and reports.is_dir() else []
                if not found:
                    continue
                path = found[-1]
                mime = "text/plain" if media_kind == "text" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                media[media_id] = {"id": media_id, "kind": "html" if media_kind == "report" else "text", "label": label,
                                   "path": str(path), "mime": mime, "bytes": path.stat().st_size}
                item_id = media_id.removeprefix("detection-")
                items.append({"id": item_id, "iteration": iteration_id, "kind": "report", "title": label,
                              "when": _iso(_mtime(path)), "metrics": {}, "status": "planned",
                              "media": [{"id": media_id, "kind": media[media_id]["kind"], "label": label}],
                              "links": [{"label": path.name, "kind": "media", "media": media_id}], "note": None})
            evidence_by_iteration[iteration_id] = items
            ids = [item["id"] for item in items]
            no_run = "plan iteration: no run"
            value("hsi_test_miou", iteration_id, _pts(best_hsi[0]) if best_hsi else None,
                  note=(f"best valid so far: {best_hsi[1]}" if best_hsi else "no valid hyperspectral test mIoU yet"),
                  n=1 if best_hsi else None, evidence=ids)
            value("h1_reproduced", iteration_id, len(reproduced) if tolerance is not None and configs else None,
                  of=len(configs) or None, n=len(graded),
                  note=("cumulative, from the runs before this plan; no run since" if not later_runs else "cumulative")
                  if tolerance is not None and configs else "no tolerance or paper targets readable", evidence=ids)
            value("run_test_miou", iteration_id, None, note=no_run)
            value("guardrails", iteration_id, None, note="not emitted: no frozen suite, worst-class IoU or latency is logged")
            value("valid_runs", iteration_id, valid if started else None, of=started or None, n=started,
                  note="cumulative over runs started before this plan", evidence=ids)
            value("nan_runs", iteration_id, nan_runs if started else None, of=started or None, n=started,
                  note="cumulative over runs started before this plan", evidence=ids)
            value("run_hours", iteration_id, None, note=no_run)
            value("needs_you", iteration_id, len(needs) if needs is not None else None,
                  note=None if needs is not None else f"plan note not readable: {plan_path}", evidence=ids)
            continue

        assert entry is not None
        last_run = entry
        started += 1
        paper_label, paper_value = paper.get(entry["base"], (None, None))
        outcome = _run_outcome(entry, paper_value, tolerance)
        test_pts = _pts(entry["test"])
        if entry["valid"]:
            valid += 1
            if paper_value is not None and tolerance is not None:
                graded.add(entry["base"])
                if abs(test_pts - paper_value) <= tolerance:
                    reproduced.add(entry["base"])
            if entry["hyper"] and (best_hsi is None or entry["test"] > best_hsi[0]):
                best_hsi = (entry["test"], f"{entry['idx']} {paper_label or entry['base']}")
        if entry["nan_epochs"]:
            nan_runs += 1
        hours = (round((entry["done"] - entry["start"]).total_seconds() / 3600, 2)
                 if entry["done"] and entry["start"] else None)
        name = paper_label or entry["base"]
        iteration_id = entry["idx"] if entry["idx"] not in evidence_by_iteration else entry["tag"]
        marker = f"{entry['idx']} {name}: {outcome}"
        if test_pts is not None:
            marker += f" · test {test_pts:.1f}" + (f" (paper {paper_value:.1f})" if paper_value is not None else "")
        iterations.append({"id": iteration_id, "label": f"{entry['idx']} {name}",
                           "date": entry["start"].date().isoformat() if entry["start"] else None, "marker": marker,
                           "provenance": _provenance(queue_src, f"start from {entry['start_source'] or 'nowhere (no START, no W&B dir)'}; "
                                                                 f"outcome from queue.log DONE and logs/{entry['tag']}.log")})
        evidence_id = f"run-{entry['idx']}"
        links = [{"label": f"logs/{entry['tag']}.log", "kind": "path", "value": str(entry["log"])}]
        if entry["wandb_url"]:
            links.append({"label": f"W&B run {entry['wandb_id']}", "kind": "path", "value": entry["wandb_url"]})
        item = {"id": evidence_id, "iteration": iteration_id, "kind": "run", "title": f"{entry['idx']} · {name}",
                "when": _iso(entry["start"]),
                "metrics": {"test mIoU (pts)": test_pts, "paper (pts)": paper_value,
                            "Δ vs paper (pts)": round(test_pts - paper_value, 2) if test_pts is not None and paper_value is not None else None,
                            "best val mIoU (pts)": _pts(entry["best_val"]), "epochs logged": entry["epochs"],
                            "NaN-loss epochs": entry["nan_epochs"], "sanitized-input warnings": entry["sanitized"],
                            "skipped-batch warnings": entry["skipped"], "rc": entry["rc"], "h elapsed": hours},
                "status": outcome, "media": [], "links": links,
                "note": "single seed (n = 1)" if entry["finished"] else None}
        evidence_by_iteration[iteration_id] = [item]
        for key in ("h1_reproduced", "valid_runs", "nan_runs", "run_hours"):
            by_kpi[key].append(evidence_id)
        if entry["hyper"]:
            by_kpi["hsi_test_miou"].append(evidence_id)
        if test_pts is not None:
            by_kpi["run_test_miou"].append(evidence_id)
        ev = [evidence_id]

        if best_hsi:
            value("hsi_test_miou", iteration_id, _pts(best_hsi[0]), n=1, note=f"best valid so far: {best_hsi[1]}", evidence=ev)
        elif entry["hyper"] and test_pts is not None:
            value("hsi_test_miou", iteration_id, None, evidence=ev, note=f"{test_pts:.1f} not counted: {outcome}")
        elif entry["hyper"]:
            value("hsi_test_miou", iteration_id, None, evidence=ev, note=f"hyperspectral run, no test score: {outcome}")
        else:
            value("hsi_test_miou", iteration_id, None, evidence=ev, note="RGB-only run; no valid hyperspectral result yet")
        if tolerance is not None and configs:
            value("h1_reproduced", iteration_id, len(reproduced), of=len(configs), n=len(graded), evidence=ev,
                  note=f"cumulative over runs started so far · this run: {outcome}")
        else:
            value("h1_reproduced", iteration_id, None, evidence=ev,
                  note="no ±tolerance (ladder_data.py unreadable)" if tolerance is None else "no paper targets (compile_results.py unreadable)")
        if test_pts is not None:
            delta = f" · Δ {test_pts - paper_value:+.1f}" if paper_value is not None else ""
            value("run_test_miou", iteration_id, test_pts, n=1, evidence=ev,
                  note=f"paper {paper_value:.1f}{delta} · {outcome}" if paper_value is not None else outcome)
        else:
            value("run_test_miou", iteration_id, None, evidence=ev, note=f"no test score: {outcome}")
        value("guardrails", iteration_id, None, note="not emitted: no frozen suite, worst-class IoU or latency is logged")
        value("valid_runs", iteration_id, valid, of=started, n=started, evidence=ev, note="cumulative over runs started so far")
        value("nan_runs", iteration_id, nan_runs, of=started, n=started, evidence=ev,
              note=f"cumulative · this run: {entry['nan_epochs']} NaN-loss epochs of {entry['epochs']}")
        value("run_hours", iteration_id, hours, n=1 if hours is not None else None, evidence=ev,
              note=(f"START→DONE wall clock, rc={entry['rc']}" if hours is not None
                    else f"no wall-clock span: {'no DONE line' if entry['done'] is None else 'no START time'}"))
        value("needs_you", iteration_id, None, note="no decisions recorded before the 10-04 plan")

    # ---- KPIs
    s1_target = max((value_ for tag, (_, value_) in paper.items() if value_ is not None and TAG.match(tag)
                     and "hyper" in TAG.match(tag).group("input") and tag in configs), default=None)
    s1_label = next((label for tag, (label, value_) in paper.items() if tag in configs and value_ == s1_target), None)
    paper_src = str(compile_results) if compile_results else None
    ns = len(configs)
    current_frontier = len(reproduced)
    first_run = runs[0] if runs else None

    def kpi(kpi_id: str, label: str, slot: str, unit: str, direction: str, target: dict[str, Any] | None,
            status: tuple[str, str], note: str | None, source: str | None, derived: str) -> dict[str, Any]:
        return {"id": kpi_id, "label": label, "slot": slot, "unit": unit, "direction": direction, "target": target,
                "baseline": None, "values": series[kpi_id], "status": {"word": status[0], "tone": status[1]},
                "note": note, "aggregate": None, "provenance": _provenance(source, derived)}

    hsi_runs = [run for run in runs if run["hyper"]]
    kpis = [
        kpi("hsi_test_miou", "Best valid hyperspectral test mIoU (E3)", "S1", "mIoU pts", "higher",
            {"value": s1_target, "kind": "gate", "label": f"paper best {s1_target:.1f} ({s1_label})"} if s1_target else None,
            (f"{_pts(best_hsi[0]):.1f} · unconfirmed · repeat needed", "muted") if best_hsi else
            (f"no valid value · {len(hsi_runs)} hyperspectral runs, none valid", "warn"),
            "Counts only finished runs with finite losses and no sanitized or skipped batches. Real SpectralWaste test "
            "split, 6 classes, background excluded (Table IV).", queue_src,
            "running best of valid hyperspectral-input runs; test/miou from queue.log DONE × 100; validity from logs/<tag>.log"),
        kpi("h1_reproduced", "H1 Table IV configs reproduced", "S2", "configs", "higher",
            {"value": ns, "kind": "scope", "label": f"of {ns} configs (H1 gate: all within ±{tolerance:g} mIoU)"}
            if ns and tolerance is not None else None,
            (f"{current_frontier} of {ns} · 1 seed each: unconfirmed · repeat needed", "muted") if ns and tolerance is not None
            else ("not computable", "muted"),
            f"A config counts once: a valid run within ±{tolerance:g} test mIoU of the paper. H1 is the frontier rung; "
            "no rung is recorded green." if tolerance is not None else "ladder_data.py unreadable: no tolerance.",
            paper_src, "compile_results.PAPER targets against queue.log DONE scores; tolerance from ladder_data.RUNGS H1 gate"),
        kpi("run_test_miou", "Test mIoU per finished run", "S2", "mIoU pts", "info", None,
            (f"last: {last_finished['idx']} {_pts(last_finished['test']):.1f}" if (last_finished := next(
                (run for run in reversed(runs) if run["test"] is not None), None)) else "no finished run", "muted"),
            "Each run is a different config with its own paper target (in each point's note); single seed.", queue_src,
            "queue.log DONE test/miou × 100"),
        kpi("guardrails", "Frozen-suite regressions, worst-class IoU, latency", "S3", "rows", "lower", None,
            ("not emitted", "muted"), "Planned (ladder_data.KPIS S3); no file records any guardrail yet.", str(ladder_path),
            "nothing to read"),
        kpi("valid_runs", "Valid runs of runs started", "S4", "runs", "higher", None,
            (f"{valid} valid of {started} started", "warn" if started and valid < started else "muted"),
            "Valid = DONE rc=0 with a test score, finite losses every epoch, zero sanitized or skipped batches.",
            queue_src, "queue.log START/DONE plus logs/<tag>.log, cumulative in start order"),
        kpi("nan_runs", "Runs with a NaN loss", "S5", "runs", "lower",
            {"value": 0, "kind": "gate", "label": "zero numerical faults (H1 gate)"},
            (f"{nan_runs} of {started} runs", "warn" if nan_runs else "muted"),
            "Single seed and test-used-for-selection are the plan's other S5 findings; they are not logged as data.",
            queue_src, "epoch lines in logs/<tag>.log with a non-finite train or val loss, cumulative"),
        kpi("run_hours", "Wall-clock hours per run", "S6", "h elapsed", "info", None,
            (f"{sum(1 for run in runs if run['done'] and run['start'])} runs timed · GPU h and peak RAM not metered", "muted"),
            "Wall-clock START→DONE, never agent-hours or GPU hours.", queue_src, "queue.log DONE − START (or the W&B run dir time)"),
        kpi("needs_you", "Open decisions (plan)", "S7", "questions", "lower",
            {"value": 0, "kind": "gate", "label": "empty (plan S7; at most 3 at a time)"},
            ((f"{len(needs)} open · {sum(1 for need in needs if need['blocks'])} blocking a rung", "warn" if needs else "muted")
             if needs is not None else ("plan note unreadable", "muted")),
            "From the plan note's Needs you list on its date; the loop itself records no questions yet.",
            str(plan_path), "numbered items under '## Needs you'"),
    ]

    # ---- state, summary
    now = datetime.now()
    data_path = _data_path(_locate(sources, "detection_queue_script"))
    drive = None
    if data_path:
        drive = "data drive mounted" if os.path.isdir(data_path) else "data drive not mounted"
        drive += f" (checked {local_time(now)})"
    in_progress = [run for run in runs if run["done"] is None and run["log_mtime"]
                   and (now - run["log_mtime"]).total_seconds() < work_track.stall_hours * 3600]
    after_plan = [run for run in runs if plan_when and run["start"] and run["start"] > plan_when]
    last_activity = max((moment for run in runs for moment in (run["done"], run["start"], run["log_mtime"]) if moment),
                        default=None)
    frontier_row = frontier_rung(ladder)
    frontier_id = frontier_row["id"] if frontier_row else None
    if frontier_id == "H1" and ns and tolerance is not None:
        progress = f"{current_frontier} of {ns} reproduced"
    else:
        progress = None  # only H1's gate metric (configs reproduced) is computed from these files
    frontier = (f"{frontier_id} frontier" + (f" {progress}" if progress else "")) if frontier_id else "frontier unknown (ladder_data.py unreadable)"
    if in_progress:
        word, tone, since = "Running", "ok", _iso(in_progress[-1]["start"])
        detail = f"run {in_progress[-1]['idx']} · {in_progress[-1]['epochs']} epochs logged · {frontier}"
    elif after_plan:
        word, tone, since = "Active", "ok", _iso(after_plan[0]["start"])
        detail = f"{len(after_plan)} runs since the plan · {frontier}"
    elif plan_when:
        word, tone, since = "Planned", "muted", _iso(plan_when)
        detail = f"loop not started · plan {plan_when.strftime('%m-%d')} · {frontier} · last run {_hm(last_activity)}"
    else:
        word, tone, since = "Idle", "muted", _iso(last_activity)
        detail = f"no plan readable · {frontier} · last run {_hm(last_activity)}"
    if drive:
        detail += f" · {drive}"
    track["state"] = {"word": word, "tone": tone, "detail": detail, "since": since}
    s1 = (f"best valid hyperspectral test mIoU {_pts(best_hsi[0]):.1f}" if best_hsi
          else "no valid hyperspectral test mIoU yet")
    s1 += f" (paper {s1_target:.1f})" if s1_target else ""
    lead = "Planned, loop not started" if word == "Planned" else word
    track["summary"] = (f"{lead}: {frontier}, {s1}; "
                        f"last training run {last_activity.date().isoformat() if last_activity else 'unknown'}.")
    current = iterations[-1] if iterations else None
    track["iteration"] = {"unit": "session",
                          "label": (f"{current['label']} · loop not started" if word == "Planned" and current else
                                    current["label"] if current else "none reported")}
    track["iterations"] = iterations
    track["rung"] = _rung(ladder, frontier_row, progress)
    track["kpis"] = kpis
    track["north_star"] = "hsi_test_miou"
    track["needs_you"] = needs or []
    if needs is None:
        # WHY null and not 0: the plan note could not be read, so the open decisions are unknown (truth rule 2).
        track["needs_you_count"] = {"open": None, "blocking": None}
    track["evidence"] = {"by_iteration": evidence_by_iteration, "by_kpi": by_kpi}
    track["links"] = [{"label": "Repro queue log", "kind": "path", "value": queue_src}]
    if compile_results:
        track["links"].append({"label": "Compile the Table IV comparison", "kind": "command", "value": f"python3 {compile_results}"})
    project = next((run["wandb_url"].rsplit("/runs/", 1)[0] for run in runs if run["wandb_url"]), None)
    if project:
        track["links"].append({"label": "W&B project", "kind": "path", "value": project})
    if ladder_path:
        track["links"].append({"label": "Ladder data (H0–H9)", "kind": "path", "value": str(ladder_path)})
    if plan_path:
        track["links"].append({"label": "Plan note (vault)", "kind": "path", "value": str(plan_path)})
    for media_id, entry in media.items():
        track["links"].append({"label": entry["label"], "kind": "media", "media": media_id})
    if media:
        track["media"] = media
    track["provenance"] = _provenance(queue_src, "queue.log + per-run logs + compile_results.PAPER + ladder_data.RUNGS "
                                                 "+ plan note Needs you; read live, nothing copied")
    if first_run is None:
        track["summary"] = f"{lead}: no run in the repro queue log yet."
    return track
