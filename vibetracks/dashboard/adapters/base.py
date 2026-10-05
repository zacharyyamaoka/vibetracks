"""The adapter interface: one module per work track turns its loop's own files into one ``vibetracks-dashboard/1``
track. The full contract, with each track's source map, is docs/dashboard/ADAPTERS.md.

    # vibetracks/dashboard/adapters/<name>.py
    def build_track(work_track: WorkTrack, sources: dict[str, str]) -> dict: ...
    def build_children(work_track: WorkTrack, sources: dict[str, str]) -> list[dict]: ...   # optional

- ``work_track`` is the registry row (registry.py): id, title, status, priority, owner, adapter, sources, roadmap,
  children, note_path, revision, heartbeat, stall_hours, purpose.
- ``sources`` maps each key the note declares in ``vibe-sources`` to its absolute path (vibetracks/sources.py). Only
  declared keys are passed: the build's cache and freshness watch exactly those files, so an undeclared input would
  change without the dashboard noticing.
- The return value is a Track (docs/dashboard/PROJECTION.md). ``skeleton`` gives one with every field present and
  honest empties; fill ``state``, ``summary``, ``iteration``/``iterations``, ``north_star``/``kpis``, ``needs_you``,
  ``evidence`` and ``links``. The build counts ``needs_you`` into ``needs_you_count`` ({open, blocking}); set
  ``needs_you_count`` yourself only when the loop reports counts but not the questions (null = unknown, never 0). A track may also carry
  ``media``: ``{id: MediaEntry}``, which the build lifts into the projection's allowlist (prefix ids with the track id).
- The build owns ``id`` (= vibe-id), ``title`` (= vibe-title), ``kind``, ``parent``, ``registry``, ``freshness`` and
  ``purpose``: whatever an adapter puts there is overwritten.
- Raising, returning a non-dict, or returning a track that ``problems`` rejects all yield an honest
  "not reporting · <reason>" track. An adapter never takes the dashboard down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; registry imports nothing from here
    from ..registry import WorkTrack

PENDING = "adapter pending"
NOT_REPORTING = "Not reporting"
TONES = ("ok", "warn", "risk", "stale", "muted")
DIRECTIONS = ("higher", "lower", "info", "count")
UNITS = ("wave", "tick", "session", "day")


def skeleton(work_track: "WorkTrack", *, unit: str = "tick") -> dict[str, Any]:
    """A Track with every field present and nothing claimed yet: no iterations, no KPIs, no evidence."""

    return {
        "id": work_track.id,
        "title": work_track.title,
        "kind": "loop",
        "parent": None,
        "summary": "",
        "state": {"word": NOT_REPORTING, "tone": "muted", "detail": None, "since": None},
        "iteration": {"unit": unit, "label": "none reported"},
        "iterations": [],
        "north_star": None,
        "kpis": [],
        "needs_you": [],
        "evidence": {"by_iteration": {}, "by_kpi": {}},
        "links": [],
        "provenance": {"snapshot": None, "pointer": None, "source": work_track.note_path,
                       "derived": "work-track registry note; no adapter output"},
    }


def not_reporting(work_track: "WorkTrack", reason: str) -> dict[str, Any]:
    """The honest track for a loop the dashboard cannot read: it says so and why, and claims no numbers."""

    track = skeleton(work_track)
    track["state"] = {"word": NOT_REPORTING, "tone": "muted", "detail": reason, "since": None}
    track["summary"] = f"not reporting · {reason}"
    # WHY null and not 0: a track that has not reported has not said it needs nothing (truth rule 2).
    track["needs_you_count"] = {"open": None, "blocking": None}
    track["reporting"] = False
    return track


def problems(track: Any) -> list[str]:
    """What makes an adapter's track unusable by the page; [] when it is sound.

    Checks the shape the shared model reads (PROJECTION.md): required fields and types, tones, KPI directions and
    that every KPI's values align one to one with the track's iterations. It does not judge the numbers.
    """

    if not isinstance(track, dict):
        return [f"build_track returned {type(track).__name__}, not a dict"]
    found: list[str] = []
    for key, kind in (("summary", str), ("state", dict), ("iteration", dict), ("iterations", list), ("kpis", list),
                      ("needs_you", list), ("evidence", dict), ("links", list)):
        if not isinstance(track.get(key), kind):
            found.append(f"{key} must be a {kind.__name__}")
    if found:
        return found
    state = track["state"]
    if not isinstance(state.get("word"), str) or state.get("tone") not in TONES:
        found.append(f"state needs a word and a tone in {TONES}")
    if track["iteration"].get("unit") not in UNITS:
        found.append(f"iteration.unit must be one of {UNITS}")
    ids = []
    for iteration in track["iterations"]:
        if not isinstance(iteration, dict) or not isinstance(iteration.get("id"), str):
            found.append("every iteration needs a string id")
            return found
        ids.append(iteration["id"])
    if len(set(ids)) != len(ids):
        found.append("iteration ids must be unique")
    kpi_ids = []
    for kpi in track["kpis"]:
        if not isinstance(kpi, dict) or not isinstance(kpi.get("id"), str):
            found.append("every KPI needs a string id")
            continue
        kpi_ids.append(kpi["id"])
        if kpi.get("direction") not in DIRECTIONS:
            found.append(f"KPI {kpi['id']}: direction must be one of {DIRECTIONS}")
        values = kpi.get("values")
        if not isinstance(values, list) or [v.get("iteration") if isinstance(v, dict) else None for v in values] != ids:
            found.append(f"KPI {kpi['id']}: values must align one to one with the track's iterations")
            continue
        for value in values:
            if value.get("value") is None and value.get("measured"):
                found.append(f"KPI {kpi['id']}@{value.get('iteration')}: a null value cannot be measured")
            if value.get("value") is None and not value.get("note"):
                found.append(f"KPI {kpi['id']}@{value.get('iteration')}: a gap must say why (note)")
    if track.get("north_star") is not None and track.get("north_star") not in kpi_ids:
        found.append("north_star must name one of the track's KPIs (or be null)")
    if not isinstance(track["evidence"].get("by_iteration"), dict):
        found.append("evidence.by_iteration must be a dict")
    counts = track.get("needs_you_count")
    if counts is not None and not (isinstance(counts, dict) and all(
            counts.get(key) is None or (isinstance(counts.get(key), int) and counts[key] >= 0) for key in ("open", "blocking"))):
        found.append("needs_you_count must be {open, blocking}, each a count or null")
    media = track.get("media")
    if media is not None and not isinstance(media, dict):
        found.append("media must be {id: MediaEntry}")
    return found
