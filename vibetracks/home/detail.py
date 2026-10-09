"""The track page's and the project page's documents, beside ``/home`` (docs/peps/0001; B2, 2026-10-09).

    GET /home/track?id=rig        -> vibetracks-home-track/1
    GET /home/project?id=pyblocks -> vibetracks-home-project/1
    GET /home/audit?track=rig&name=2026-10-05-rig-tick5-h3w6-r2b.md -> that audit file, text/plain (allowlisted)

Both are composed from the inputs the last ``/home`` build already read (``compose.LAST``: records by track, the
projection, the needs documents, the clock), so a page never re-reads the transcripts, and from three more files
that only these pages need:

- the projection's KPI series and iterations (dates), split into soft KPIs (every KPI whose target is not a gate)
  and hard gates (target kind ``gate``; pass/fail from the KPI's own direction, never averaged in);
- the track note's ``vibe-audits`` globs: Codex audit rounds under some ``reports/media/audits/`` (verdict from the
  file's first lines, model and effort from the ``.log`` beside it, how long it took from its prompt file's mtime);
- the needs documents' items (asked / updated times) for the activity timeline.

What was not observed is null and the page says "unknown". Stdlib only.
"""

from __future__ import annotations

import glob
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..activity import harness
from ..edits import read_note_exact
from ..notes import parse_frontmatter
from . import compose

TRACK_SCHEMA = "vibetracks-home-track/1"
PROJECT_SCHEMA = "vibetracks-home-project/1"
DAYS = 7
TIMELINE_MAX = 160
VERDICTS = [  # first match wins, so the longer phrase comes first
    ("UNSOUND", "red"), ("SOUND WITH FIXES", "yellow"), ("SOUND", "green"), ("DO NOT SHIP", "red"), ("NOT SHIPPABLE", "red"),
    ("PASS-WITH-FIXES", "yellow"), ("PASS WITH FIXES", "yellow"), ("FAIL", "red"), ("PASS", "green"), ("SHIP", "green"),
    ("BLOCKED", "red"), ("APPROVE", "green"),
]


# ------------------------------------------------------------------------------------------------ helpers


def _iso(epoch: float | None) -> str | None:
    return harness.iso(epoch)


def _days(now: float) -> list[tuple[str, float, float]]:
    """The last DAYS local days, oldest first: (YYYY-MM-DD, start, end)."""

    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for back in range(DAYS - 1, -1, -1):
        day = today - timedelta(days=back)
        out.append((day.strftime("%Y-%m-%d"), day.timestamp(), min(now, (day + timedelta(days=1)).timestamp())))
    return out


def worked_daily(files: list[harness.FileState], now: float) -> list[dict[str, Any]]:
    return [{"date": d, "s": compose.worked(files, start, end)} for d, start, end in _days(now)]


def _note_frontmatter(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return parse_frontmatter(read_note_exact(Path(path)))[0]
    except Exception:  # noqa: BLE001 - a note that cannot be read just has no extra keys
        return {}


def _kpi_series(kpi: Mapping[str, Any], dates: Mapping[str, str | None]) -> list[dict[str, Any]]:
    out = []
    for value in kpi.get("values") or []:
        if not isinstance(value, Mapping):
            continue
        out.append({"iteration": value.get("iteration"), "date": dates.get(str(value.get("iteration"))),
                    "value": value.get("value"), "of": value.get("of"), "measured": bool(value.get("measured")),
                    "note": value.get("note")})
    return out


def gate_verdict(kpi: Mapping[str, Any]) -> dict[str, Any]:
    """Pass/fail of a gate KPI from its last measured value, its target and its direction; null when unknowable."""

    target = kpi.get("target") if isinstance(kpi.get("target"), Mapping) else {}
    goal = target.get("value")
    measured = [v for v in kpi.get("values") or [] if isinstance(v, Mapping) and v.get("measured") and v.get("value") is not None]
    if not measured:
        return {"pass": None, "why": "not measured yet", "value": None, "of": None}
    last = measured[-1]
    value = last.get("value")
    direction = kpi.get("direction")
    if not isinstance(goal, (int, float)) or not isinstance(value, (int, float)):
        return {"pass": None, "why": "no numeric target", "value": value, "of": last.get("of")}
    if direction == "lower":
        ok = value <= goal
    elif direction == "higher":
        ok = value >= goal
    elif last.get("of") is not None and goal == last.get("of"):
        ok = value >= goal                      # "all N green": a scope-sized gate is met when the count reaches it
    else:
        return {"pass": None, "why": "the KPI has no direction, so pass/fail is unknown", "value": value, "of": last.get("of")}
    return {"pass": bool(ok), "why": f"{value} {'≤' if direction == 'lower' else '≥'} {goal}" if ok else
            f"{value} {'>' if direction == 'lower' else '<'} {goal}", "value": value, "of": last.get("of"),
            "iteration": last.get("iteration")}


# ------------------------------------------------------------------------------------------------ audits


def audit_globs(track_doc: Mapping[str, Any]) -> list[str]:
    raw = _note_frontmatter(track_doc.get("provenance", {}).get("note")).get("vibe-audits")
    globs = [raw] if isinstance(raw, str) else [str(g) for g in raw] if isinstance(raw, list) else []
    return [os.path.expanduser(g) for g in globs if g.strip()]


def audit_files(globs: Iterable[str]) -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in globs:
        for name in glob.glob(pattern):
            path = Path(name)
            if path.suffix == ".md" and not path.name.endswith("-prompt.md") and path.is_file():
                seen[str(path)] = path
    return sorted(seen.values(), key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def _verdict(text: str) -> tuple[str | None, str]:
    head = text[:1500].upper()
    for word, tone in VERDICTS:
        if re.search(r"(?<![A-Z])" + re.escape(word) + r"(?![A-Z])", head):
            return word.title().replace("-", " "), tone
    return None, "none"


def _log_meta(path: Path) -> dict[str, str | None]:
    log = path.with_suffix(".log")
    out: dict[str, str | None] = {"model": None, "effort": None, "provider": None}
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(3000)
    except OSError:
        return out
    for key, field_ in (("model", "model"), ("effort", "reasoning effort"), ("provider", "provider")):
        match = re.search(rf"^{field_}:\s*(\S.*)$", head, re.M)
        if match:
            out[key] = match.group(1).strip()
    return out


def audits(track_doc: Mapping[str, Any], limit: int = 60) -> dict[str, Any]:
    globs = audit_globs(track_doc)
    if not globs:
        return {"globs": [], "rounds": [], "unknown": "no vibe-audits glob in the track's note"}
    rounds = []
    for path in audit_files(globs)[:limit]:
        try:
            info = path.stat()
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                head = handle.read(1500)
        except OSError:
            continue
        verdict, tone = _verdict(head)
        first = next((line.strip(" *#>-") for line in head.splitlines() if line.strip()), "")
        prompt = path.with_name(path.stem + "-prompt.md")
        if not prompt.exists():
            prompt = path.with_name(re.sub(r"-(r|round)\d+[a-z]?$", "", path.stem) + "-prompt.md")
        took = None
        if prompt.exists():
            delta = info.st_mtime - prompt.stat().st_mtime
            took = int(delta) if 0 < delta < 6 * 3600 else None
        rounds.append({"name": path.name, "path": str(path), "ts": _iso(info.st_mtime), "verdict": verdict, "tone": tone,
                       "headline": first[:240], "bytes": info.st_size, "took_s": took,
                       "prompt": prompt.name if prompt.exists() else None, **_log_meta(path)})
    return {"globs": globs, "rounds": rounds, "unknown": None if rounds else "no audit file matches the globs"}


def serve_audit(doc: Mapping[str, Any], track_id: str, name: str) -> tuple[int, dict[str, str], list[bytes]] | None:
    """The bytes of one audit (or its prompt) of ``track_id``, only when its globs list it; None otherwise."""

    track = _find_track(doc, track_id)
    if track is None or "/" in name or name.startswith("."):
        return None
    for pattern in audit_globs(track):
        for candidate in glob.glob(pattern):
            path = Path(candidate)
            if path.name == name and path.suffix == ".md" and path.is_file():
                body = path.read_bytes()
                return 200, {"Content-Type": "text/plain; charset=utf-8", "Content-Length": str(len(body)),
                             "Cache-Control": "no-cache"}, [body]
    return None


# ------------------------------------------------------------------------------------------------ the timeline


def timeline(track_doc: Mapping[str, Any], records: list[Any], projected: Mapping[str, Any] | None,
             needs_doc: Mapping[str, Any] | None, audit_rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read-only events from the derived spine, newest first: sessions, agent actions, errors, questions, the loop's
    iterations and writes, triage updates and audit rounds. Every event names its source."""

    events: list[dict[str, Any]] = []

    def add(ts: float | None, kind: str, title: str, detail: str | None = None, source: str | None = None, **extra: Any) -> None:
        if ts is None:
            return
        events.append({"ts": _iso(ts), "kind": kind, "title": title, "detail": detail, "source": source, **extra})

    for record in records:
        name = record.title or record.session[:8]
        firsts = [f.first_ts for f in record.files if f.first_ts]
        if firsts:
            add(min(firsts), "session", f"Session started · {name}", f"{record.account} · {record.branch or 'no branch'}",
                record.transcript, session=record.session, account=record.account)
        last = record.last_agent()
        if last:
            add(last[0], "action", f"Last agent entry · {name}", f"{last[1]}: {last[2] or ''}"[:300], record.transcript,
                session=record.session, account=record.account)
        error = record.last_error()
        if error:
            add(error[0], "error", f"Error · {name}", f"{error[1]}: {error[2] or ''}"[:300], record.transcript,
                session=record.session, account=record.account)
        for asked, question in record.open_asks():
            add(asked, "question", f"Asked you · {name}", (question or "")[:300], record.transcript,
                session=record.session, account=record.account)
    for iteration in (projected or {}).get("iterations") or []:
        if isinstance(iteration, Mapping) and iteration.get("date"):
            when = harness.parse_ts(f"{iteration['date']}T12:00:00")
            add(when, "iteration", f"Iteration {iteration.get('label') or iteration.get('id')}", iteration.get("marker"),
                (iteration.get("provenance") or {}).get("source"), date_only=True)
    loop = track_doc.get("last_loop_write")
    if loop:
        add(harness.parse_ts(loop.get("ts")), "loop", "Loop wrote its files", loop.get("key"), loop.get("path"))
    for item in (needs_doc or {}).get("items") or []:
        created = harness.parse_ts((item.get("created") or {}).get("ts"))
        updated = harness.parse_ts((item.get("updated") or {}).get("ts"))
        if created:
            add(created, "need", f"Question asked · {item.get('title')}", item.get("group"), (needs_doc or {}).get("track"))
        if updated and updated != created:
            add(updated, "need", f"Question updated · {item.get('title')}", (item.get("updated") or {}).get("note"),
                (needs_doc or {}).get("track"))
    for audit in audit_rounds:
        add(harness.parse_ts(audit["ts"]), "audit", f"Audit · {audit['name']}",
            f"{audit['verdict'] or 'verdict unknown'}" + (f" · {audit['model']}" if audit.get("model") else ""), audit["path"])
    events.sort(key=lambda e: e["ts"] or "", reverse=True)
    return events[:TIMELINE_MAX]


# ------------------------------------------------------------------------------------------------ documents


def _find_track(doc: Mapping[str, Any], track_id: str) -> dict[str, Any] | None:
    return next((t for p in doc.get("projects") or [] for t in p.get("tracks") or [] if t.get("id") == track_id), None)


def _project_of(doc: Mapping[str, Any], track_id: str) -> dict[str, Any] | None:
    return next((p for p in doc.get("projects") or [] if any(t.get("id") == track_id for t in p.get("tracks") or [])), None)


def _kpis(projected: Mapping[str, Any] | None) -> dict[str, Any]:
    if not projected:
        return {"north_star": None, "soft": [], "gates": [], "iterations": [], "unknown": "no KPI adapter yet"}
    if projected.get("reporting") is False:
        detail_ = ((projected.get("state") or {}).get("detail") or "").strip()
        return {"north_star": None, "soft": [], "gates": [], "iterations": [],
                "unknown": "the adapter is not reporting" + (f": {detail_}" if detail_ else "")}
    dates = {str(i.get("id")): i.get("date") for i in projected.get("iterations") or [] if isinstance(i, Mapping)}
    soft, gates = [], []
    for kpi in projected.get("kpis") or []:
        if not isinstance(kpi, Mapping):
            continue
        target = kpi.get("target") if isinstance(kpi.get("target"), Mapping) else None
        entry = {"id": kpi.get("id"), "label": kpi.get("label"), "unit": kpi.get("unit"), "direction": kpi.get("direction"),
                 "target": target, "baseline": kpi.get("baseline"), "status": kpi.get("status"), "note": kpi.get("note"),
                 "north_star": kpi.get("id") == projected.get("north_star"), "series": _kpi_series(kpi, dates)}
        if target and target.get("kind") == "gate":
            entry["gate"] = gate_verdict(kpi)
            gates.append(entry)
        else:
            soft.append(entry)
    soft.sort(key=lambda k: not k["north_star"])
    return {"north_star": projected.get("north_star"), "soft": soft, "gates": gates,
            "iterations": [{"id": i.get("id"), "label": i.get("label"), "date": i.get("date"), "marker": i.get("marker")}
                           for i in projected.get("iterations") or [] if isinstance(i, Mapping)],
            "rung": projected.get("rung"), "summary": projected.get("summary"),
            "unknown": None if (soft or gates) else "the loop reports no KPI"}


def build_track(doc: Mapping[str, Any], last: Mapping[str, Any], track_id: str) -> dict[str, Any] | None:
    track = _find_track(doc, track_id)
    if track is None:
        return None
    started = time.perf_counter()
    now = last["now"]
    records = [r for r in last["records"].values() if r.track == track_id]
    projected = last["projected"].get(track_id)
    files = [state for record in records for state in record.files]
    rounds = audits(track)
    project = _project_of(doc, track_id) or {}
    return {
        "schema": TRACK_SCHEMA,
        "generated_at": _iso(now),
        "track": track,
        "project": {"id": project.get("id"), "name": project.get("name"), "color": project.get("color")},
        "kpis": _kpis(projected),
        "roadmap": {"href": f"../roadmap/doc?track={track_id}",
                    "note": "the roadmap projector's document for this track (vibetracks.roadmap); 404 when it has none"},
        "worked_daily": worked_daily(files, now),
        "timeline": timeline(track, records, projected, last["needs"].get(track_id), rounds["rounds"]),
        "audits": rounds,
        "timing_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def build_project(doc: Mapping[str, Any], last: Mapping[str, Any], project_id: str) -> dict[str, Any] | None:
    project = next((p for p in doc.get("projects") or [] if p.get("id") == project_id), None)
    if project is None:
        return None
    started = time.perf_counter()
    now = last["now"]
    leading = []
    for track in project["tracks"]:
        projected = last["projected"].get(track["id"])
        records = [r for r in last["records"].values() if r.track == track["id"]]
        files = [state for record in records for state in record.files]
        kpis = _kpis(projected)
        north = next((k for k in kpis["soft"] + kpis["gates"] if k["north_star"]), None)
        leading.append({"track": track["id"], "title": track["title"], "state": track["state"], "health": track["health"],
                        "kpi": north, "unknown": None if north else (kpis["unknown"] or "no north-star KPI reported"),
                        "worked_daily": worked_daily(files, now)})
    star = project.get("north_star")
    lagging: dict[str, Any] = {"declared": star, "unknown": None}
    if not star:
        lagging["unknown"] = "no north star declared in the project's descriptor"
    elif star["kind"] == "kpi":
        projected = last["projected"].get(star["track"])
        kpi = next((k for k in _kpis(projected)["soft"] + _kpis(projected)["gates"] if k["id"] == star["kpi"]), None)
        lagging["kpi"] = kpi
        if kpi is None:
            lagging["unknown"] = f"{star['track']} reports no KPI {star['kpi']}"
    else:
        lagging["roadmap"] = f"../roadmap/doc?track={star['track']}"
    return {
        "schema": PROJECT_SCHEMA,
        "generated_at": _iso(now),
        "project": project,
        "north_star": lagging,
        "leading": leading,
        "days": [d for d, _s, _e in _days(now)],
        "timing_ms": round((time.perf_counter() - started) * 1000, 1),
    }
