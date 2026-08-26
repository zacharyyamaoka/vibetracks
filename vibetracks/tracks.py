"""Tracks: one lane of the graph, addressed by area.

A track is not a second entity. It is the projection of the dependency graph
onto one area tag — the same "strand" idea the graph view draws, made
addressable from the command line so a per-track agent can be handed its lane
and nothing else.

`lane_table` answers "what lanes exist and where is the work?".
`track_briefing` prints a paste-ready brief for one pinned per-track agent:
its features, its cross-lane blockers, and the panel link scoped to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import VibeTracksError
from .project import TrackItem, TrackProject

UNTRACKED = "(untracked)"

# Kept in step with STALE_RUNNING_MINUTES in static/app.js: how long a `running`
# claim may sit without its note changing before the panel calls it stale.
STALE_RUNNING_MINUTES = 15

# Order lanes by how much they want a human, not alphabetically.
_STATUS_URGENCY = ["review", "frontier", "running", "waiting", "ready", "backlog", "done", "archived"]


@dataclass
class Lane:
    name: str
    description: str
    items: list[TrackItem]

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    @property
    def needs_you(self) -> int:
        return sum(1 for item in self.items if item.status in {"review", "frontier"})


def lanes(project: TrackProject, include_archived: bool = False) -> list[Lane]:
    """Every declared or used area, plus one lane for untagged work."""
    described = {entry["name"]: entry["description"] for entry in project.area_catalog()}
    buckets: dict[str, list[TrackItem]] = {name: [] for name in described}
    untracked: list[TrackItem] = []
    for item in project.items:
        if item.archived and not include_archived:
            continue
        if not item.areas:
            untracked.append(item)
            continue
        for area in item.areas:
            buckets.setdefault(area, []).append(item)
    result = [Lane(name, described.get(name, ""), items) for name, items in buckets.items()]
    result.sort(key=lambda lane: (-lane.needs_you, -len(lane.items), lane.name))
    if untracked:
        result.append(Lane(UNTRACKED, "No area tag — invisible to every per-track agent", untracked))
    return result


def lane_table(project: TrackProject, panel_url: str | None = None) -> str:
    """The lane overview: which tracks exist, and where the pressure is."""
    rows = lanes(project)
    width = max((len(lane.name) for lane in rows), default=8)
    lines = [
        f"{project.title} · {len(project.items)} features · {len(rows)} tracks",
        f"descriptor: {project.descriptor}",
    ]
    lines.append(f"panel: {panel_url}" if panel_url else "panel: not running (start it with `vibetracks serve`)")
    lines.append("")
    for lane in rows:
        counts = lane.counts
        summary = "  ".join(
            f"{counts[status]} {status}" for status in _STATUS_URGENCY if counts.get(status))
        mark = "!" if lane.needs_you else " "
        lines.append(f" {mark} {lane.name.ljust(width)}  {str(len(lane.items)).rjust(3)}  {summary}")
    lines.append("")
    lines.append("Brief one agent on one lane with:  vibetracks track <name>")
    return "\n".join(lines)


def _feature_line(item: TrackItem, lane_ids: set[str], project: TrackProject) -> str:
    outside = [
        dependency for dependency in item.dependencies
        if dependency not in lane_ids
    ]
    blocked = ""
    if outside:
        names = ", ".join(
            f"{dependency} ({project.item_by_id(dependency).status})"
            for dependency in outside
            if project.item_by_id(dependency)
        )
        blocked = f"   ← waits on another track: {names}"
    priority = f" [{item.priority}]" if item.priority not in {"none", ""} else ""
    return f"  {item.status.ljust(8)} {item.id} · {item.title}{priority}{blocked}"


def track_briefing(project: TrackProject, area: str, panel_url: str | None = None) -> str:
    """A self-contained prompt for one pinned per-track agent."""
    matches = [lane for lane in lanes(project) if lane.name == area]
    if not matches:
        known = ", ".join(lane.name for lane in lanes(project))
        raise VibeTracksError(f"No track called {area!r}. Known tracks: {known}")
    lane = matches[0]
    lane_ids = {item.id for item in lane.items}
    ordered = sorted(
        lane.items,
        key=lambda item: (_STATUS_URGENCY.index(item.status) if item.status in _STATUS_URGENCY else 99, item.id),
    )
    panel = panel_url or "start it with `vibetracks serve`"
    scoped = f"{panel_url}#kanban/{area}" if panel_url else panel

    lines = [
        f"You are the **{area}** track on {project.title}.",
        "",
        lane.description or "(no description in the area catalog yet — add one when it becomes clear)",
        "",
        f"Repo: {project.root}",
        f"Descriptor: {project.descriptor}",
        f"Panel (this lane): {scoped}",
        "",
        f"Your lane holds {len(lane.items)} feature note(s). The Markdown files are the database;",
        "the panel is a lens over them, and Zach is watching the same files you write.",
        "",
    ]
    for item in ordered:
        lines.append(_feature_line(item, lane_ids, project))
    waiting_outside = [
        item for item in lane.items
        if any(dependency not in lane_ids for dependency in item.dependencies)
    ]
    lines += [
        "",
        "How to work this lane",
        "---------------------",
        "1. Take one `ready` feature whose prerequisites are `done`.",
        "2. Claim it — `vibetracks status <id> running` — BEFORE you start. The panel ages",
        f"   every claim; a `running` note unchanged for {STALE_RUNNING_MINUTES} minutes is shown as stale,",
        "   so an unclaimed hour of work looks exactly like an idle hour to Zach.",
        "3. Do the work. Touch the note as you go (`vibetracks comment <id> \"...\"`) — that is",
        "   the heartbeat the panel can actually see.",
        "4. Finish into `review` with a self-contained, media-rich HTML packet in `reports/`",
        "   and link it from the note. Never set `done`; approving is Zach's gesture.",
        "5. Blocked? `vibetracks status <id> waiting` and say what you are waiting on, in the note.",
        "   An open question is `frontier`.",
        "",
        "Stay inside this lane. Work in another area belongs to that track's agent:",
        "file it with `vibetracks new \"<title>\" --area <other-area>` and move on.",
    ]
    if waiting_outside:
        lines += [
            "",
            f"{len(waiting_outside)} of your features wait on other tracks (marked above). Do not",
            "reach across and finish their prerequisites yourself.",
        ]
    return "\n".join(lines)
