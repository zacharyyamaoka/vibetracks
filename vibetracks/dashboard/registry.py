"""The work-track registry: one Markdown note per agent work track, read into ordered ``WorkTrack`` rows.

    from vibetracks.dashboard.registry import load_registry
    load_registry("/home/bam/vibetracks-dashboard/workspace")  # -> [WorkTrack(id='kinsim', ...), ...]

The workspace's ``.vtdash`` names the registry descriptor (``"registry": "Work tracks.vibetrack"``); the descriptor
selects ``note["vibe-track"] == "worktrack"`` notes in its source folder (``tracks/``). Each note's frontmatter:

- ``vibe-id``: the stable key, ``[a-z0-9][a-z0-9_-]*``. It never changes; the title does.
- ``vibe-title``: the display name. ``rename_title`` is its one writer (POST /tracks/<id>/title).
- ``vibe-status``: ``running`` | ``paused`` | ``archived`` (Zach's declared state; live state comes from the loop).
- ``vibe-priority``: a positive integer, the home-page row order (1 first). Anything else sorts last.
- ``vibe-owner``: a label for the session or agent. Liveness never comes from it.
- ``vibe-adapter``: the module ``vibetracks/dashboard/adapters/<name>.py`` that builds the track (ADAPTERS.md).
- ``vibe-sources``: keys of ``vibetracks/sources.py`` ``load_sources()``, the files the adapter reads.
- ``vibe-heartbeat`` (optional): the subset of those keys whose mtime says the loop is alive. Default: the keys the
  adapter's ``READS`` marks ``heartbeat`` (build.py), else all of them.
- ``vibe-stall-hours`` (optional): quiet for longer than this and the track reads stale; default 24.
- ``vibe-roadmap``: ``{projector, sources}`` for the roadmap session, or null ("No roadmap reported yet").
- ``vibe-children``: ids of deployments drawn inside this track and never on the home page (rig: can12, can16).

WHY one note per track and not a JSON list: the notes are ordinary Vibe Tracks notes (the same parser, the same
fenced, span-preserving writes), so a track joins by dropping in one file and a rename touches one line of one file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..descriptor import DescriptorConfig, load_descriptor
from ..edits import apply_note_edit, replace_frontmatter_entry
from ..errors import UnknownFeature, VibeTracksError
from ..notes import first_paragraph, note_revision, parse_frontmatter

TRACK_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ADAPTER_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
STATUSES = ("running", "paused", "archived")
DEFAULT_STALL_HOURS = 24.0
TITLE_MAX = 80

#: The registry's keys beyond the stock ``vibe-`` set; a descriptor may rename any of them under
#: ``vibetracks.properties`` (``Work tracks.vibetrack`` spells them out).
WORKTRACK_PROPERTIES = {
    "title": "vibe-title",
    "owner": "vibe-owner",
    "adapter": "vibe-adapter",
    "sources": "vibe-sources",
    "heartbeat": "vibe-heartbeat",
    "stallHours": "vibe-stall-hours",
    "roadmap": "vibe-roadmap",
    "children": "vibe-children",
}


class TitleInvalid(VibeTracksError):
    """A rename's title is empty, too long, or has a newline or control character."""


@dataclass
class WorkTrack:
    id: str
    title: str
    status: str
    priority: int | None
    owner: str | None
    adapter: str | None
    sources: list[str]
    roadmap: dict[str, Any] | None
    children: list[str]
    note_path: str
    revision: str
    heartbeat: list[str] = field(default_factory=list)
    stall_hours: float = DEFAULT_STALL_HOURS
    purpose: str = ""
    #: True when the note sets ``vibe-heartbeat`` itself; otherwise the build narrows the default to the adapter's
    #: ``heartbeat`` reads, so a shared folder an adapter only lists for media never makes a quiet loop look alive.
    heartbeat_declared: bool = False

    @property
    def archived(self) -> bool:
        return self.status == "archived"

    def to_dict(self) -> dict[str, Any]:
        """The registry block a projection track carries (``track.registry``)."""

        return {
            "status": self.status,
            "priority": self.priority,
            "owner": self.owner,
            "adapter": self.adapter,
            "sources": list(self.sources),
            "heartbeat": list(self.heartbeat),
            "stall_hours": self.stall_hours,
            "roadmap": self.roadmap,
            "children": list(self.children),
            "note_path": self.note_path,
            "revision": self.revision,
        }


@dataclass
class Registry:
    descriptor: Path
    tracks: list[WorkTrack]
    problems: list[dict[str, str]]

    def by_id(self, track_id: str) -> WorkTrack | None:
        return next((track for track in self.tracks if track.id == track_id), None)


# ------------------------------------------------------------------------------------------------ finding it


def find_registry(workspace: str | Path) -> Path | None:
    """The registry descriptor for ``workspace``: a folder of ``.vtdash`` files, one ``.vtdash``, or the descriptor.

    A folder answers with the ``registry`` its ``.vtdash`` files name, first by file name; None when none names one.
    """

    path = Path(workspace).expanduser()
    if path.suffix in (".vibetrack", ".base"):
        return path.resolve() if path.is_file() else None
    files = [path] if path.suffix == ".vtdash" else sorted(path.glob("*.vtdash")) if path.is_dir() else []
    for file in files:
        try:
            value = json.loads(file.read_text(encoding="utf-8")).get("registry")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(value, str) and value.strip():
            candidate = Path(value.strip()).expanduser()
            candidate = candidate if candidate.is_absolute() else file.parent / candidate
            if candidate.is_file():
                return candidate.resolve()
    return None


def _worktrack_properties(config: DescriptorConfig) -> dict[str, str]:
    try:
        raw = yaml.safe_load(config.path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    meta = raw.get("vibetracks") if isinstance(raw, dict) else None
    declared = meta.get("properties") if isinstance(meta, dict) else None
    declared = declared if isinstance(declared, dict) else {}
    return {name: str(declared.get(name) or default).strip().removeprefix("note.")
            for name, default in WORKTRACK_PROPERTIES.items()}


# ------------------------------------------------------------------------------------------------ reading it


def _string_list(value: Any) -> list[str] | None:
    """A list of non-empty strings, a lone string as a one-item list, None (empty) as []; anything else None."""

    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    return None


def _priority(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip()) or None
    return None


def _work_track(path: Path, content: str, frontmatter: dict[str, Any], body: str, config: DescriptorConfig,
                keys: dict[str, str], problems: list[dict[str, str]]) -> WorkTrack | None:
    name = path.name

    def problem(text: str) -> None:
        problems.append({"path": name, "error": text})

    track_id = frontmatter.get(config.properties["id"])
    if not isinstance(track_id, str) or not TRACK_ID.fullmatch(track_id):
        problem(f"{config.properties['id']} {track_id!r} must match {TRACK_ID.pattern}; the note is skipped")
        return None

    raw_title = frontmatter.get(keys["title"])
    if isinstance(raw_title, (str, int, float)) and not isinstance(raw_title, bool) and str(raw_title).strip():
        title = str(raw_title)  # WHY verbatim: a stored title renders as authored (truthful-rendering rule)
    else:
        title = track_id
        problem(f"{keys['title']} is missing; the row shows the id")

    raw_status = frontmatter.get(config.properties["status"])
    status = str(raw_status).strip().lower() if raw_status is not None else "running"
    if status not in STATUSES:
        problem(f"{config.properties['status']} {raw_status!r} is not one of {', '.join(STATUSES)}; shown as written")
    if frontmatter.get(config.properties["archived"]) is True:
        status = "archived"

    raw_priority = frontmatter.get(config.properties["priority"])
    priority = _priority(raw_priority)
    if raw_priority is not None and priority is None:
        problem(f"{config.properties['priority']} {raw_priority!r} is not a positive integer; the row sorts last")

    owner = frontmatter.get(keys["owner"])
    owner = str(owner).strip() if owner is not None and str(owner).strip() else None

    adapter = frontmatter.get(keys["adapter"])
    adapter = str(adapter).strip() if adapter is not None and str(adapter).strip() else None
    if adapter is not None and not ADAPTER_NAME.fullmatch(adapter):
        problem(f"{keys['adapter']} {adapter!r} must match {ADAPTER_NAME.pattern}; the track reads not reporting")

    sources = _string_list(frontmatter.get(keys["sources"]))
    if sources is None:
        problem(f"{keys['sources']} must be a list of sources.py keys; read as none")
        sources = []
    heartbeat = _string_list(frontmatter.get(keys["heartbeat"]))
    if heartbeat is None:
        problem(f"{keys['heartbeat']} must be a list of sources.py keys; every source counts instead")
        heartbeat = []
    heartbeat_declared = bool(heartbeat)
    heartbeat = heartbeat or list(sources)

    stall_hours = DEFAULT_STALL_HOURS
    raw_stall = frontmatter.get(keys["stallHours"])
    if raw_stall is not None:
        if isinstance(raw_stall, (int, float)) and not isinstance(raw_stall, bool) and raw_stall > 0:
            stall_hours = float(raw_stall)
        else:
            problem(f"{keys['stallHours']} {raw_stall!r} must be a positive number of hours; using {DEFAULT_STALL_HOURS:g}")

    roadmap = frontmatter.get(keys["roadmap"])
    if roadmap is not None and not isinstance(roadmap, dict):
        problem(f"{keys['roadmap']} must be {{projector, sources}} or null; read as null")
        roadmap = None

    children = _string_list(frontmatter.get(keys["children"]))
    if children is None:
        problem(f"{keys['children']} must be a list of ids; read as none")
        children = []
    bad = [child for child in children if not TRACK_ID.fullmatch(child)]
    if bad:
        problem(f"{keys['children']} ids {bad} must match {TRACK_ID.pattern}; skipped")
        children = [child for child in children if child not in bad]

    return WorkTrack(
        id=track_id,
        title=title,
        status=status,
        priority=priority,
        owner=owner,
        adapter=adapter,
        sources=sources,
        roadmap=roadmap,
        children=list(dict.fromkeys(children)),
        note_path=str(path.resolve()),
        revision=note_revision(content),
        heartbeat=heartbeat,
        stall_hours=stall_hours,
        # WHY the whole paragraph (limit=None): the default cuts near 240 characters with no mark, which hid the end
        # of every purpose ("Its live fold is stat"). The page clamps it with an explicit ellipsis and a "more" toggle.
        purpose=first_paragraph(body, limit=None),
        heartbeat_declared=heartbeat_declared,
    )


def sort_key(track: WorkTrack) -> tuple:
    """Priority 1 first; a track with no usable priority after every numbered one; then by id (stable)."""

    return (track.priority is None, track.priority or 0, track.id)


def read_registry(workspace: str | Path) -> Registry:
    """Every work track the registry declares (archived included), in row order, plus what could not be read.

    Raises VibeTracksError when the workspace names no registry or the descriptor is unreadable. One bad note never
    takes the registry down: it is skipped and named in ``problems``.
    """

    descriptor = find_registry(workspace)
    if descriptor is None:
        raise VibeTracksError(f"no work-track registry: no .vtdash in {workspace} names a 'registry' descriptor that exists")
    config = load_descriptor(descriptor)
    if not config.source.is_dir():
        raise VibeTracksError(f"the registry's source folder does not exist: {config.source}")
    keys = _worktrack_properties(config)
    marker = config.marker or (config.properties["marker"], "worktrack")
    tracks: list[WorkTrack] = []
    problems: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    for path in sorted(config.source.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(content)
        except (VibeTracksError, OSError, UnicodeDecodeError) as error:
            problems.append({"path": path.name, "error": str(error)})
            continue
        if str(frontmatter.get(marker[0], "")) != marker[1]:
            continue
        track = _work_track(path, content, frontmatter, body, config, keys, problems)
        if track is None:
            continue
        if track.id in seen:
            problems.append({"path": path.name, "error": f"duplicate id {track.id!r} (already {seen[track.id]}); skipped"})
            continue
        seen[track.id] = path.name
        tracks.append(track)
    ids = set(seen)
    for track in tracks:
        clashes = [child for child in track.children if child in ids]
        if clashes:
            problems.append({"path": Path(track.note_path).name,
                             "error": f"children {clashes} are registry tracks themselves; a child is never top-level, skipped"})
            track.children = [child for child in track.children if child not in clashes]
    tracks.sort(key=sort_key)
    return Registry(descriptor=descriptor, tracks=tracks, problems=problems)


def load_registry(workspace: str | Path) -> list[WorkTrack]:
    """The registry's work tracks in row order (archived included; the home page drops them)."""

    return read_registry(workspace).tracks


# ------------------------------------------------------------------------------------------------ renaming


def clean_title(value: Any) -> str:
    """The title a rename stores: a string, trimmed, 1-80 characters, no newline or other control character."""

    if not isinstance(value, str):
        raise TitleInvalid("title must be a string")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise TitleInvalid("title must be one line, with no newline or control character")
    cleaned = value.strip()
    if not cleaned:
        raise TitleInvalid("title must not be empty")
    if len(cleaned) > TITLE_MAX:
        raise TitleInvalid(f"title must be at most {TITLE_MAX} characters (got {len(cleaned)})")
    return cleaned


def rename_title(workspace: str | Path, track_id: str, title: Any, revision: str) -> tuple[str, str]:
    """Set one work track's ``vibe-title``; returns ``(title, new revision)``.

    Revision-fenced and atomic through ``edits.apply_note_edit`` (RevisionConflict when the note changed since
    ``revision``), and span-preserving through ``replace_frontmatter_entry``: only the title line changes, every
    other byte of the note stays as written. ``vibe-id`` is never touched.

    Raises TitleInvalid, UnknownFeature (no such id) or RevisionConflict.
    """

    cleaned = clean_title(title)
    if not isinstance(track_id, str) or not TRACK_ID.fullmatch(track_id):
        raise UnknownFeature(f"unknown work track: {track_id!r}")
    registry = read_registry(workspace)
    track = registry.by_id(track_id)
    if track is None:
        raise UnknownFeature(f"unknown work track: {track_id!r}")
    config = load_descriptor(registry.descriptor)
    key = _worktrack_properties(config)["title"]
    written: dict[str, str] = {}

    def transform(markdown: str) -> str:
        updated = replace_frontmatter_entry(markdown, key, cleaned)
        written["content"] = updated
        return updated

    path = Path(track.note_path)
    changed = apply_note_edit(path, str(revision or ""), transform)
    # WHY the revision of the bytes this call wrote (or, for a no-op, of the bytes it fenced on), not a re-read: a
    # re-read could already include a later writer's change, and the client must fence its next write on ours.
    return cleaned, note_revision(written["content"]) if changed else str(revision)
