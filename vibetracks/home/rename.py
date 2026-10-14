"""The home's inline renames (r3, 2026-10-09; Zach: "I want to be able to double click to rename", like Claude's
sidebar). Each is one fenced, atomic write of one line, beside the work-track rename it extends
(``dashboard.registry.rename_title``, served as ``POST /tracks/<id>/title`` by clank/backend/server.py):

- ``rename_activity_title``: an activity track's ``vibe-title`` (a ``vibe-track: activity`` note, docs/peps/0001), so
  every track on the home renames the same way whether or not it has a KPI adapter yet.
- ``rename_project``: a project descriptor's ``name`` (one of ``workspace/projects/*.vibetrack``). The project's id is
  the slug of its name (B2's contract), so it follows the new name; its tracks stay under it (projects.resolve).

Both are fenced on the file's revision (``notes.note_revision`` of its exact text; RevisionConflict when it changed
since the page read it) and written through ``edits.apply_note_edit`` (same-folder temp file, fsync, replace). A
title or name is stored exactly as typed (never trimmed); only empty, whitespace-only or multi-line text is refused
(``registry.validate_title``'s rules). Sessions are never renamed here: their titles belong to Claude.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from ..dashboard.registry import TRACK_ID, TitleInvalid, read_registry, validate_title
from ..descriptor import load_descriptor
from ..edits import _serialize_entry, apply_note_edit, read_note_exact, replace_frontmatter_entry
from ..errors import UnknownFeature
from ..notes import note_revision, parse_frontmatter
from .projects import read_projects, slug

#: A project id: the slug of its name (or its descriptor's stem); one path segment, no leading dot.
PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TITLE_KEY = "vibe-title"


# ------------------------------------------------------------------------------------------------ activity tracks


def activity_note(workspace: str | os.PathLike[str], track_id: str) -> Path | None:
    """The ``vibe-track: activity`` note whose ``vibe-id`` is ``track_id``, or None."""

    if not isinstance(track_id, str) or not TRACK_ID.fullmatch(track_id):
        return None
    source = load_descriptor(read_registry(workspace).descriptor).source
    for path in sorted(source.rglob("*.md")):
        try:
            frontmatter, _ = parse_frontmatter(read_note_exact(path))
        except Exception:  # noqa: BLE001 - an unreadable note is not this track
            continue
        if str(frontmatter.get("vibe-track", "")) == "activity" and frontmatter.get("vibe-id") == track_id:
            return path
    return None


def rename_activity_title(workspace: str | os.PathLike[str], track_id: str, title: Any, revision: str) -> tuple[str, str]:
    """Set an activity track's ``vibe-title``; returns ``(title, new revision)``. Raises TitleInvalid, UnknownFeature
    (no such activity track) or RevisionConflict."""

    cleaned = validate_title(title)
    path = activity_note(workspace, track_id)
    if path is None:
        raise UnknownFeature(f"unknown track: {track_id!r}")
    written: dict[str, str] = {}

    def transform(markdown: str) -> str:
        updated = replace_frontmatter_entry(markdown, TITLE_KEY, cleaned)
        if parse_frontmatter(updated)[0].get(TITLE_KEY) != cleaned:  # the write must read back as typed, or not happen
            raise TitleInvalid("the note would not store the title as typed")
        written["content"] = updated
        return updated

    changed = apply_note_edit(path, str(revision or ""), transform)
    return cleaned, note_revision(written["content"]) if changed else str(revision)


def activity_revision(workspace: str | os.PathLike[str], track_id: str) -> str | None:
    path = activity_note(workspace, track_id)
    return note_revision(read_note_exact(path)) if path else None


# ------------------------------------------------------------------------------------------------ projects


def descriptor_path(workspace: str | os.PathLike[str], project_id: str) -> Path | None:
    """The descriptor of the project whose id (the slug of its name) is ``project_id``, else the one whose file stem
    is; only files ``read_projects`` lists, so an id never reaches a path outside ``workspace/projects/``."""

    if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
        return None
    descriptors, _ = read_projects(workspace)
    for match in (lambda p: p.id == project_id, lambda p: p.stem == project_id):
        found = next((p for p in descriptors.values() if match(p)), None)
        if found is not None:
            return Path(found.path)
    return None


def validate_name(value: Any) -> str:
    try:
        return validate_title(value)
    except TitleInvalid as error:
        raise TitleInvalid(str(error).replace("title", "name")) from None


def set_descriptor_name(text: str, name: str) -> str:
    """``text`` with the ``vibetracks:`` block's ``name`` set to ``name``: the one ``name:`` line replaced, or one line
    added after ``kind:`` (else first) in that block at its indent. Every other byte stays as written."""

    lines = text.splitlines(keepends=True)
    eol = "\r\n" if "\r\n" in text else "\n"
    head = next((i for i, line in enumerate(lines) if re.match(r"^vibetracks:\s*(#.*)?$", line.rstrip("\r\n"))), None)
    if head is None:
        raise TitleInvalid("the descriptor has no top-level vibetracks: block")
    block: list[int] = []
    for i in range(head + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not lines[i][0] in " \t":
            break
        block.append(i)
    if not block:
        raise TitleInvalid("the descriptor's vibetracks: block is empty")
    indent = re.match(r"^[ \t]*", lines[block[0]]).group(0)
    children = [i for i in block if re.match(r"^[ \t]*", lines[i]).group(0) == indent]
    serialized = _serialize_entry("name", name)
    if len(serialized) != 1:
        raise TitleInvalid("a project name must fit on one line")
    new_line = indent + serialized[0]
    for i in children:
        if re.match(rf"^{re.escape(indent)}name\s*:", lines[i]):
            ending = lines[i][len(lines[i].rstrip("\r\n")):] or eol
            lines[i] = new_line + ending
            return "".join(lines)
    after = next((i for i in children if re.match(rf"^{re.escape(indent)}kind\s*:", lines[i])), head)
    if not lines[after].endswith(("\n", "\r")):
        lines[after] += eol
    lines.insert(after + 1, new_line + eol)
    return "".join(lines)


def rename_project(workspace: str | os.PathLike[str], project_id: str, name: Any, revision: str) -> tuple[str, str]:
    """Set a project descriptor's ``name``; returns ``(name, new revision)``. Raises TitleInvalid (a bad name, or one
    another project already has), UnknownFeature (no such descriptor) or RevisionConflict."""

    cleaned = validate_name(name)
    path = descriptor_path(workspace, project_id)
    if path is None:
        raise UnknownFeature(f"unknown project: {project_id!r}")
    descriptors, _ = read_projects(workspace)
    taken = {project.name for project in descriptors.values() if Path(project.path) != path}
    if cleaned in taken:
        raise TitleInvalid(f"another project is already named {cleaned!r}")
    written: dict[str, str] = {}

    def transform(text: str) -> str:
        updated = set_descriptor_name(text, cleaned)
        block = (yaml.safe_load(updated) or {}).get("vibetracks") or {}
        if block.get("name") != cleaned:  # the write must read back as typed, or not happen
            raise TitleInvalid("the descriptor would not store the name as typed")
        written["content"] = updated
        return updated

    changed = apply_note_edit(path, str(revision or ""), transform)
    return cleaned, note_revision(written["content"]) if changed else str(revision)


def project_id_of(name: str) -> str:
    return slug(name)


def project_revision(workspace: str | os.PathLike[str], project_id: str) -> str | None:
    path = descriptor_path(workspace, project_id)
    return note_revision(read_note_exact(path)) if path else None
