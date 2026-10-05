"""Adapter for the Pyblocks work track (vibe-id ``pyblocks``): the single-file Block View loop, M1 "One file, verified".

Interface: docs/dashboard/ADAPTERS.md (section ``pyblocks``); the discovery behind it is
docs/dashboard/track-discovery-2026-10-04.json key ``scout:pyblocks``.

Inputs (the note's ``vibe-sources``; nothing else is read for a number):

- ``pyblocks_board_dir``: ``/home/bam/pyblocks/reports/media/board``. One scoreboard per merge window,
  ``<commit7>.json`` (schema 1: ``totals.{runnable,adversarial}.{goldens,green,red,grey,l0Pass}``, ``easy[]``,
  ``goldens[]`` rows with ``status``), its human ``.md`` twin, and ``merges.jsonl`` (one line per lane landing, in
  landing order, with the fast gate's tail). The build watches this directory one level deep, so a new board or
  a new merges line reruns the adapter.
- ``pyblocks_windows``: ``windows.jsonl``, the integrator's merge-window log (window id, main sha, board totals,
  ``scoreboard --check`` result, ``vs_previous`` prose).

One iteration is one board file (a merge window, keyed by main's commit), oldest first. A windows.jsonl line joins
its board by main's sha; landings join their window by walking merges.jsonl up to the board's commit.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import skeleton

TRACK_ID = "pyblocks"

# WHY a dated, attributed constant and not a file read: the INT loop's stop (its Claude account hit the weekly
# limit on 10-01; the limit resets 10-06 08:00) is recorded in no file the loop writes, only in the 2026-10-04
# discovery (session transcripts). Zach asked for it on the row. It applies only while the newest window is still the
# one the loop stopped after; the first new window drops it, so it can never outlive the stop it describes.
KNOWN_STOP = {
    "after_window": "v5-#10",
    "text": "INT loop stopped 10-01 (account weekly limit, reset due 10-06 08:00)",
    "source": "docs/dashboard/track-discovery-2026-10-04.json scout:pyblocks.freshness (not in the loop's files)",
}

# Files next to the board that the page may open as links (checked to exist at build time; never read for numbers).
SUMMARY_REPORT = "single-file-evaluation-summary-2026-09-30.html"   # under reports/media/
ROADMAP_REPORT = "pyblocks-roadmap-2026-09-29.html"                  # under reports/

_TIER = re.compile(r"--tier\s+(\w+)")
_GATE_COUNTS = re.compile(r"(\d+) passed, (\d+) failed(?:, (\d+) skipped)?")
_KNOWN_RED = re.compile(r"(\d+) known red")
_VERDICT = re.compile(r"GATE (PASS|FAIL)")


# --------------------------------------------------------------------------------------------------------- readers
def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Rows of a jsonl file in order, and how many lines did not parse (reported, never silently dropped)."""

    rows: list[dict[str, Any]] = []
    bad = 0
    if not path.is_file():
        return rows, bad
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            bad += 1
    return rows, bad


def _read_boards(board_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Every schema-1 scoreboard in ``board_dir``, one per commit (the newest file wins), sorted by generatedAt."""

    boards: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    if not board_dir.is_dir():
        return [], skipped
    for path in sorted(board_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            skipped.append(f"{path.name}: {type(error).__name__}")
            continue
        if not (isinstance(data, dict) and data.get("schema") == 1 and isinstance(data.get("totals"), dict)
                and isinstance(data.get("commit"), str) and isinstance(data.get("generatedAt"), str)):
            skipped.append(f"{path.name}: not a schema-1 scoreboard")
            continue
        commit7 = data["commit"][:7]
        board = {"commit": data["commit"], "commit7": commit7, "at": data["generatedAt"], "dirty": bool(data.get("dirty")),
                 "totals": data["totals"], "easy": list(data.get("easy") or []), "rows": data.get("goldens") or [],
                 "file": path}
        previous = boards.get(commit7)
        if previous is None or previous["at"] < board["at"]:
            if previous is not None:
                skipped.append(f"{previous['file'].name}: superseded by {path.name} (same commit)")
            boards[commit7] = board
        else:
            skipped.append(f"{path.name}: superseded by {previous['file'].name} (same commit)")
    return sorted(boards.values(), key=lambda board: board["at"]), skipped


def _fast_gate(tail: str) -> dict[str, Any] | None:
    """The last fast-tier gate result in a merges.jsonl ``gate_tail``: {passed, failed, skipped, known_red, verdict}.

    A tail can hold several runs (a first run, then a rerun or a run after a ledger commit) and other tiers. Each
    ``N passed, M failed`` belongs to the tier named by the nearest ``--tier`` before it; its ledgered-red count and
    verdict are the first ones before the next result. The last fast result is the one the landing stood on."""

    if not tail:
        return None
    matches = list(_GATE_COUNTS.finditer(tail))
    found = None
    for index, match in enumerate(matches):
        tiers = _TIER.findall(tail, 0, match.start())
        if not tiers or tiers[-1] != "fast":
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(tail)
        window = tail[match.end():end]
        known = _KNOWN_RED.search(window)
        verdict = _VERDICT.search(window)
        found = {"passed": int(match.group(1)), "failed": int(match.group(2)),
                 "skipped": int(match.group(3)) if match.group(3) else None,
                 "known_red": int(known.group(1)) if known else None,
                 "verdict": verdict.group(1) if verdict else None}
    return found


def _num(record: Any, key: str) -> int | None:
    """An integer field of a dict, or None (a missing corpus or field is a gap, never a zero)."""

    value = record.get(key) if isinstance(record, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _local(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def _date(stamp: str | None) -> str | None:
    moment = _local(stamp)
    return moment.strftime("%Y-%m-%d") if moment else None


def _short(stamp: str | None) -> str:
    moment = _local(stamp)
    return moment.strftime("%m-%d %H:%M") if moment else "undated"


# --------------------------------------------------------------------------------------------------------- helpers
def _value(iteration: str, value: Any, *, of: Any = None, note: str | None = None, evidence: list[str] | None = None,
           missing: str | None = None) -> dict[str, Any]:
    if value is None:
        return {"iteration": iteration, "value": None, "of": None, "n": None, "spread": None, "measured": False,
                "note": missing or "not emitted", "evidence": []}
    return {"iteration": iteration, "value": value, "of": of, "n": None, "spread": None, "measured": True,
            "note": note, "evidence": list(evidence or [])}


def _status(values: list[dict[str, Any]], target: dict[str, Any] | None, direction: str,
            unit: str, single_pass: bool = False) -> dict[str, str]:
    """The calm reading: the latest measured value, its move in the last window, and the gate when there is one."""

    measured = [v for v in values if v["measured"]]
    if not measured:
        return {"word": "not emitted", "tone": "muted"}
    latest = measured[-1]
    text = f"{latest['value']:g}" + (f" of {latest['of']:g}" if latest.get("of") is not None else f" {unit}")
    if latest is not values[-1]:
        text += f" · as of {latest['iteration']}"
    elif len(values) > 1 and values[-2]["measured"]:
        delta = latest["value"] - values[-2]["value"]
        text += " · unchanged last window" if delta == 0 else f" · {delta:+g} last window"
        if single_pass and abs(delta) == 1:
            # WHY: each board is one pass per golden, so a one-golden move rests on n = 1 (truth rule 3);
            # windows.jsonl shows such moves flipping back under load (adversarial p15, runnable/16).
            text += " · unconfirmed · repeat needed"
    tone = "muted"
    if target and target.get("kind") == "gate":
        gate = target["value"]
        met = latest["value"] >= gate if direction == "higher" else latest["value"] <= gate
        text += " · gate met" if met else f" · gate {gate:g} not met"
        tone = "ok" if met else "warn"
    return {"word": text, "tone": tone}


def _kpi(kpi_id: str, label: str, slot: str, unit: str, direction: str, target: dict[str, Any] | None,
         values: list[dict[str, Any]], note: str, provenance: dict[str, Any], *,
         single_pass: bool = False) -> dict[str, Any]:
    first = next((v for v in values if v["measured"]), None)
    return {
        "id": kpi_id, "label": label, "slot": slot, "unit": unit, "direction": direction, "target": target,
        "baseline": ({"iteration": first["iteration"], "label": f"first board {first['iteration']}",
                      "value": first["value"]} if first and direction in ("higher", "lower") else None),
        "values": values, "status": _status(values, target, direction, unit, single_pass), "note": note, "aggregate": None,
        "provenance": provenance,
    }


def _media_entry(media_id: str, path: Path, kind: str, label: str, mime: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return {"id": media_id, "kind": kind, "label": label, "path": str(path.resolve()), "mime": mime,
            "bytes": path.stat().st_size}


# ----------------------------------------------------------------------------------------------------------- build
def build_track(work_track: Any, sources: dict[str, str]) -> dict[str, Any]:
    board_dir = Path(sources["pyblocks_board_dir"]).expanduser() if sources.get("pyblocks_board_dir") else None
    windows_path = Path(sources["pyblocks_windows"]).expanduser() if sources.get("pyblocks_windows") else None
    if board_dir is None:
        raise KeyError("pyblocks_board_dir not declared in the note's vibe-sources")
    if windows_path is None:
        windows_path = board_dir / "windows.jsonl"   # its documented default: it lives in the board dir
    merges_path = board_dir / "merges.jsonl"

    track = skeleton(work_track, unit="wave")
    boards, skipped = _read_boards(board_dir)
    windows, windows_bad = _read_jsonl(windows_path)
    merges, merges_bad = _read_jsonl(merges_path)

    if not boards:
        reason = f"no scoreboard JSON in {board_dir}" if board_dir.is_dir() else f"board dir missing: {board_dir}"
        track["state"] = {"word": "Not reporting", "tone": "muted", "detail": reason, "since": None}
        track["summary"] = f"not reporting · {reason}"
        track["needs_you_count"] = {"open": None, "blocking": None}
        track["reporting"] = False
        return track

    window_by_commit: dict[str, dict[str, Any]] = {}
    for window in windows:
        main = window.get("main")
        if isinstance(main, str) and main:
            window_by_commit[main[:7]] = window   # a later line for the same sha wins (a re-measure)

    # Landings per window: merges.jsonl is in landing order, so a board's landings are the lines after the previous
    # board's commit up to and including its own. A board whose commit never landed through merges.jsonl gets none.
    last_index: dict[str, int] = {}
    for index, merge in enumerate(merges):
        main = merge.get("main")
        if isinstance(main, str) and main:
            last_index[main[:7]] = index
    buckets: list[list[tuple[int, dict[str, Any]]] | None] = []
    boundary = -1
    for board in boards:
        index = last_index.get(board["commit7"])
        if index is None or index <= boundary:
            buckets.append(None)
            continue
        buckets.append([(i, merges[i]) for i in range(boundary + 1, index + 1)])
        boundary = index
    unmeasured = merges[boundary + 1:] if boundary + 1 < len(merges) else []

    media: dict[str, dict[str, Any]] = {}
    iterations: list[dict[str, Any]] = []
    by_iteration: dict[str, list[dict[str, Any]]] = {}
    by_kpi: dict[str, list[str]] = {}
    series: dict[str, list[dict[str, Any]]] = {key: [] for key in (
        "runnable_green", "adversarial_green", "easy_green", "l0_runnable", "l0_adversarial", "board_check",
        "fast_gate_known_red", "fast_gate_passed", "landings")}

    def link_kpi(kpi_id: str, item_id: str) -> None:
        by_kpi.setdefault(kpi_id, [])
        if item_id not in by_kpi[kpi_id]:
            by_kpi[kpi_id].append(item_id)

    previous_board: dict[str, Any] | None = None
    for board, bucket in zip(boards, buckets):
        it = board["commit7"]
        totals = board["totals"]
        runnable = totals.get("runnable") if isinstance(totals.get("runnable"), dict) else None
        adversarial = totals.get("adversarial") if isinstance(totals.get("adversarial"), dict) else None
        easy = set(board["easy"])
        easy_green = sum(1 for row in board["rows"] if isinstance(row, dict) and row.get("key") in easy
                         and row.get("status") == "green") if easy else None
        board["easy_green"] = easy_green
        window = window_by_commit.get(it)

        # ---- evidence: the board itself (with its .md twin), the window line, each landing
        items: list[dict[str, Any]] = []
        board_item = f"board-{it}"
        md = board["file"].with_suffix(".md")
        media_id = f"{TRACK_ID}.board-{it}"
        entry = _media_entry(media_id, md, "text", f"board {it} (scoreboard .md)", "text/plain")
        if entry:
            media[media_id] = entry
        metrics: dict[str, Any] = {}
        for corpus_name, corpus in (("runnable", runnable), ("adversarial", adversarial)):
            if corpus:
                for key in ("green", "red", "grey", "l0Pass"):
                    if isinstance(corpus.get(key), int):
                        metrics[f"{corpus_name} {key}"] = corpus[key]
        if easy_green is not None:
            metrics["easy green"] = easy_green
        items.append({"id": board_item, "iteration": it, "kind": "report", "title": f"scoreboard {it}",
                      "when": board["at"], "metrics": metrics,
                      "status": "dirty tree" if board["dirty"] else "measured",
                      "media": [{"id": media_id, "kind": "text", "label": md.name}] if entry else [],
                      "links": [{"label": "board JSON", "kind": "path", "value": str(board["file"])}],
                      "note": None})
        window_item = None
        if window:
            window_item = f"window-{window.get('window', it)}"
            wboard = window.get("board") if isinstance(window.get("board"), dict) else {}
            check = wboard.get("check") if isinstance(wboard.get("check"), dict) else {}
            items.append({"id": window_item, "iteration": it, "kind": "note",
                          "title": f"window {window.get('window', '?')}", "when": window.get("at"),
                          "metrics": {"check exit": check.get("exit"), "check failures": check.get("failures"),
                                      "check notes": check.get("notes"),
                                      "landings listed": len(window.get("merges_since_previous") or [])},
                          "status": None if not check else ("check pass" if check.get("exit") == 0 else "check fail"),
                          "media": [], "links": [], "note": wboard.get("vs_previous")})
        gate_item = None
        gate = None
        for index, merge in bucket or []:
            item_id = f"lane-{index}-{merge.get('lane', '?')}"
            parsed = _fast_gate(merge.get("gate_tail") or "")
            lane_metrics: dict[str, Any] = {}
            if parsed:
                lane_metrics = {"fast gate passed": parsed["passed"], "fast gate failed": parsed["failed"],
                                "fast gate ledgered reds": parsed["known_red"]}
                gate, gate_item = parsed, item_id
            items.append({"id": item_id, "iteration": it, "kind": "lane",
                          "title": f"{merge.get('lane', '?')} · {str(merge.get('main', ''))[:8]}", "when": None,
                          "metrics": lane_metrics,
                          "status": "landed" + (f" · gate {parsed['verdict']}" if parsed and parsed["verdict"] else ""),
                          "media": [], "links": [],
                          "note": " · ".join(part for part in (merge.get("increment"), merge.get("diffstat")) if part)
                          or None})
            link_kpi("landings", item_id)
        by_iteration[it] = items
        for kpi_id in ("runnable_green", "adversarial_green", "easy_green", "l0_runnable", "l0_adversarial"):
            link_kpi(kpi_id, board_item)
        if window_item:
            link_kpi("board_check", window_item)
        if gate_item:
            link_kpi("fast_gate_known_red", gate_item)
            link_kpi("fast_gate_passed", gate_item)

        # ---- KPI values for this iteration
        no_adv = "adversarial corpus not measured on this board"
        series["runnable_green"].append(_value(it, _num(runnable, "green"), of=_num(runnable, "goldens"),
                                               evidence=[board_item], missing="runnable totals absent from this board"))
        series["adversarial_green"].append(_value(it, _num(adversarial, "green"),
                                                  of=_num(adversarial, "goldens"), evidence=[board_item],
                                                  missing=no_adv))
        series["easy_green"].append(_value(it, easy_green, of=len(easy) or None, evidence=[board_item],
                                           missing="board names no easy set"))
        series["l0_runnable"].append(_value(it, _num(runnable, "l0Pass"), of=_num(runnable, "goldens"),
                                            evidence=[board_item], missing="runnable l0Pass absent from this board"))
        series["l0_adversarial"].append(_value(it, _num(adversarial, "l0Pass"),
                                               of=_num(adversarial, "goldens"), evidence=[board_item],
                                               missing=no_adv))
        check = ((window or {}).get("board") or {}).get("check") if window else None
        series["board_check"].append(_value(
            it, check.get("failures") if isinstance(check, dict) else None, evidence=[window_item] if window_item else [],
            missing=("no windows.jsonl line for this board" if not window else "window recorded no scoreboard --check")))
        no_gate = ("this board's commit is not in merges.jsonl" if bucket is None
                   else "no landing in this window logged a fast-gate tail")
        series["fast_gate_known_red"].append(_value(it, _num(gate, "known_red"),
                                                    evidence=[gate_item] if gate_item else [],
                                                    note=f"GATE {gate['verdict']}" if gate and gate["verdict"] else None,
                                                    missing="the fast-gate tail names no ledgered-red count" if gate
                                                    else no_gate))
        series["fast_gate_passed"].append(_value(it, _num(gate, "passed"), evidence=[gate_item] if gate_item else [],
                                                 missing=no_gate))
        first = previous_board is None
        series["landings"].append(_value(
            it, len(bucket) if bucket is not None else None,
            note="every landing logged before the first board (merges.jsonl start)" if first and bucket else None,
            evidence=[f"lane-{i}-{m.get('lane', '?')}" for i, m in bucket or []],
            missing="this board's commit is not in merges.jsonl"))

        # ---- the iteration and its change marker
        parts = [f"window {window['window']}" if window and window.get("window") else "board only (no windows.jsonl line)"]
        if bucket is not None:
            parts.append(f"{len(bucket)} landing{'s' if len(bucket) != 1 else ''}")
        if previous_board is not None:
            moves = []
            for label, now, before in (
                    ("runnable green", _num(runnable, "green"), (previous_board["totals"].get("runnable") or {}).get("green")),
                    ("easy", easy_green, previous_board.get("easy_green")),
                    ("adversarial green", _num(adversarial, "green"),
                     (previous_board["totals"].get("adversarial") or {}).get("green")),
                    ("L0 runnable", _num(runnable, "l0Pass"), (previous_board["totals"].get("runnable") or {}).get("l0Pass")),
                    ("L0 adversarial", _num(adversarial, "l0Pass"),
                     (previous_board["totals"].get("adversarial") or {}).get("l0Pass"))):
                if isinstance(now, int) and isinstance(before, int) and now != before:
                    moves.append(f"{label} {before}→{now}")
            parts.append(" · ".join(moves) if moves else "board totals unchanged")
        else:
            parts.append("first scoreboard")
        if board["dirty"]:
            parts.append("measured on a dirty tree")
        iterations.append({
            "id": it, "label": f"{window['window']} · {it}" if window and window.get("window") else it,
            "date": _date(board["at"]), "marker": " · ".join(parts),
            "provenance": {"snapshot": None, "pointer": None, "source": str(board["file"]),
                           "derived": "one scoreboard file = one merge window; window line joined by main sha; landings "
                                      "= merges.jsonl lines after the previous board's commit up to this one"},
        })
        previous_board = board

    track["iterations"] = iterations
    latest_board = boards[-1]
    latest_window = windows[-1] if windows else None
    track["iteration"] = {"unit": "wave", "label": iterations[-1]["label"]}

    board_prov = {"snapshot": None, "pointer": "/totals", "source": str(board_dir / "<commit7>.json"), "derived": None}
    stops_note = (f"The series stops at the last board file ({latest_board['commit7']}, {_short(latest_board['at'])}); "
                  "anything measured later but not written to reports/media/board is not emitted here.")
    track["kpis"] = [
        _kpi("runnable_green", "Runnable goldens green", "S1", "goldens", "higher",
             {"value": (latest_board["totals"].get("runnable") or {}).get("goldens"), "kind": "scope",
              "label": f"of {(latest_board['totals'].get('runnable') or {}).get('goldens')} runnable goldens"},
             series["runnable_green"],
             "Green = the golden matches CPython at every level and order (green-to-whole). The gated corpus. " + stops_note,
             {**board_prov, "pointer": "/totals/runnable/green"}, single_pass=True),
        _kpi("easy_green", "Easy-18 green (checkpoint B)", "S2", "goldens", "higher",
             {"value": len(latest_board["easy"]), "kind": "gate",
              "label": f"M1 checkpoint B: all {len(latest_board['easy'])} easy goldens green"},
             series["easy_green"],
             "Counted from the board's own rows: key in the board's easy[] and status green. The formal checkpoint B / "
             "M1 exit measurement is a separate run that has no file yet. " + stops_note,
             {**board_prov, "pointer": "/goldens/*/status", "derived": "count of rows with key in /easy and status == green"}, single_pass=True),
        _kpi("adversarial_green", "Adversarial goldens green (reported, not gated)", "S1", "goldens", "higher",
             {"value": (latest_board["totals"].get("adversarial") or {}).get("goldens"), "kind": "scope",
              "label": f"of {(latest_board['totals'].get('adversarial') or {}).get('goldens')} adversarial goldens"},
             series["adversarial_green"],
             "Reported, not gated (board.gated lists runnable only). windows.jsonl records load flakes in this corpus "
             "(e.g. p15 over the 60 s budget), so a ±1 move between two single passes is unconfirmed · repeat needed.",
             {**board_prov, "pointer": "/totals/adversarial/green"}, single_pass=True),
        _kpi("l0_runnable", "Level 0 passes · runnable", "S3", "goldens", "higher",
             {"value": (latest_board["totals"].get("runnable") or {}).get("goldens"), "kind": "gate",
              "label": "M1 exit clause 6: L0 passes on every runnable golden"},
             series["l0_runnable"], "totals.runnable.l0Pass: the Level-0 run passes with rows > 0.",
             {**board_prov, "pointer": "/totals/runnable/l0Pass"}, single_pass=True),
        _kpi("l0_adversarial", "Level 0 passes · adversarial", "S3", "goldens", "higher",
             {"value": (latest_board["totals"].get("adversarial") or {}).get("goldens"), "kind": "gate",
              "label": "M1 exit clause 6: L0 passes on every adversarial golden"},
             series["l0_adversarial"],
             "totals.adversarial.l0Pass. A golden over the 60 s budget under load reads not measured and drops out of "
             "this count; windows.jsonl says when that happened.",
             {**board_prov, "pointer": "/totals/adversarial/l0Pass"}, single_pass=True),
        _kpi("board_check", "Board vs ledger · scoreboard --check failures", "S5", "failures", "lower",
             {"value": 0, "kind": "gate", "label": "--check exits 0: every red is ledgered with the right first failure"},
             series["board_check"],
             "From the integrator's window line (board.check.failures). Boards measured without a window line have no "
             "check recorded.",
             {"snapshot": None, "pointer": "/board/check/failures", "source": str(windows_path), "derived": None}),
        _kpi("fast_gate_known_red", "Fast gate · ledgered reds", "S3", "tests", "lower", None,
             series["fast_gate_known_red"],
             "Reds the fast gate allowed because tests/known_issues.json ledgers them; GATE PASS means 0 unexpected "
             "reds. Read from the last landing in the window whose gate_tail names a fast-tier result. The count rises "
             "when a lane exposes and ledgers new failures, so it is a defect backlog, not a pass rate.",
             {"snapshot": None, "pointer": "/gate_tail", "source": str(merges_path),
              "derived": "last 'N passed, M failed … K known red' after '--tier fast' in the window's last gated landing"}),
        _kpi("fast_gate_passed", "Fast gate · tests passed", "S5", "tests", "count", None,
             series["fast_gate_passed"],
             "Passed tests in the same fast-gate run; grows as lanes add tests, so it is a size, not a score.",
             {"snapshot": None, "pointer": "/gate_tail", "source": str(merges_path),
              "derived": "same run as fast_gate_known_red"}),
        _kpi("landings", "Lane landings per window", "S4", "landings", "count", None, series["landings"],
             "merges.jsonl lines between the previous board's commit and this board's commit (inclusive).",
             {"snapshot": None, "pointer": "/*", "source": str(merges_path),
              "derived": "landings bucketed by walking merges.jsonl to each board's main sha"}),
    ]
    track["north_star"] = "runnable_green"
    track["evidence"] = {"by_iteration": by_iteration, "by_kpi": by_kpi}

    # ---- state: the one calm answer
    window_label = latest_window.get("window") if latest_window else None
    last_at = latest_window.get("at") if latest_window else latest_board["at"]
    details = []
    if latest_window and window_label == KNOWN_STOP["after_window"]:
        word, tone = "Stopped", "warn"
        details.append(KNOWN_STOP["text"])
    else:
        word, tone = "Measuring", "ok"
    details.append(f"last window {window_label or 'none logged'} on {latest_board['commit7']}, {_short(last_at)}")
    if unmeasured:
        details.append(f"{len(unmeasured)} landing{'s' if len(unmeasured) != 1 else ''} logged since, not yet on a board")
    details.append("no board or window written since")
    track["state"] = {"word": word, "tone": tone, "detail": " · ".join(details), "since": last_at}

    rg = (latest_board["totals"].get("runnable") or {})
    ad = (latest_board["totals"].get("adversarial") or {})
    gate_now = next((v for v in reversed(series["fast_gate_known_red"]) if v["measured"]), None)
    passed_now = next((v for v in reversed(series["fast_gate_passed"]) if v["measured"]), None)
    pieces = [f"runnable {rg.get('green')}/{rg.get('goldens')} green",
              f"easy {latest_board['easy_green']}/{len(latest_board['easy'])}"]
    if ad:
        pieces.append(f"adversarial {ad.get('green')}/{ad.get('goldens')}")
    pieces.append(f"L0 {rg.get('l0Pass')}/{rg.get('goldens')}" + (f" + {ad.get('l0Pass')}/{ad.get('goldens')}" if ad else ""))
    if gate_now and passed_now:
        pieces.append(f"fast gate {gate_now.get('note') or 'result'}: {passed_now['value']} passed, "
                      f"{gate_now['value']} ledgered reds")
    track["summary"] = (f"M1 'One file, verified' exit gate · board {latest_board['commit7']} "
                        f"({_short(latest_board['at'])}): " + ", ".join(pieces))

    # ---- needs you: the loop writes no questions to a file (they live in session handoffs and an HTML summary)
    track["needs_you"] = []
    track["needs_you_count"] = {"open": None, "blocking": None}

    # ---- links (files checked to exist; opened through the media allowlist, never read for numbers)
    links: list[dict[str, Any]] = []
    media_root = board_dir.parent
    repo = board_dir.parent.parent.parent
    for media_id, path, label in (
            (f"{TRACK_ID}.summary-2026-10-02", media_root / SUMMARY_REPORT,
             "Latest status report (10-02 prose; its numbers are not on a board file)"),
            (f"{TRACK_ID}.roadmap-2026-09-29", media_root.parent / ROADMAP_REPORT, "Roadmap: M1 → M2 → M3")):
        entry = _media_entry(media_id, path, "html", label, "text/html")
        if entry:
            media[media_id] = entry
            links.append({"label": label, "kind": "media", "media": media_id})
    links.append({"label": "board files", "kind": "path", "value": str(board_dir)})
    links.append({"label": "re-measure the board", "kind": "command",
                  "value": f"cd {repo} && python3 -m pyblocks.scoreboard --corpus runnable,adversarial --out reports/media/board"})
    track["links"] = links
    if media:
        track["media"] = media

    problems_seen = list(skipped)
    if windows_bad:
        problems_seen.append(f"windows.jsonl: {windows_bad} unparseable line(s)")
    if merges_bad:
        problems_seen.append(f"merges.jsonl: {merges_bad} unparseable line(s)")
    track["provenance"] = {
        "snapshot": None, "pointer": None, "source": str(board_dir),
        "derived": f"{len(boards)} scoreboards, {len(windows)} windows.jsonl lines, {len(merges)} merges.jsonl lines"
                   + (f"; skipped: {'; '.join(problems_seen)}" if problems_seen else "")
                   + (f"; state annotation from {KNOWN_STOP['source']}" if word == "Stopped" else ""),
    }
    return track
