"""Read-side primitives for Markdown feature notes.

A feature note is an ordinary Markdown file with YAML frontmatter. Everything
here is pure reading and normalization; the write side lives in `edits`.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any

import yaml

from .errors import VibeTracksError

FRONTMATTER = re.compile(r"\A\ufeff?---\r?\n(?P<yaml>[\s\S]*?)\r?\n---[ \t]*\r?\n?")
WIKI_IMAGE = re.compile(r"!\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}

STATUS_ALIASES = {
    "todo": "ready",
    "to-do": "ready",
    "in-progress": "running",
    "in-review": "review",
    "cancelled": "archived",
    "canceled": "archived",
}


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in as_list(value) if str(item).strip()]


def normalize_status(value: Any, declared: list[str] | None = None) -> str:
    """Lowercase/hyphenate a status; map through aliases only when the raw
    value is not part of the project's own declared vocabulary — a track that
    declares `todo` keeps `todo`."""
    status = str(value or "ready").strip().lower().replace(" ", "-")
    if declared is not None and status in declared:
        return status
    return STATUS_ALIASES.get(status, status)


def strip_wikilink(value: str) -> str:
    text = value.strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    return text.split("|", 1)[0].strip()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "feature"


def note_revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    """Split a note into (frontmatter mapping, body)."""
    match = FRONTMATTER.match(markdown)
    if not match:
        return {}, markdown
    try:
        loaded = yaml.safe_load(match.group("yaml")) or {}
    except yaml.YAMLError as exc:
        raise VibeTracksError(f"Invalid YAML frontmatter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise VibeTracksError("Markdown frontmatter must be a mapping")
    return loaded, markdown[match.end():]


def first_paragraph(body: str, *, limit: int | None = 240) -> str:
    """A plain-text summary from the first prose paragraph of the body.

    ``limit`` (default 240) stops collecting lines once that many characters are in and cuts at ``limit + 40``;
    ``None`` returns the whole first paragraph, uncut (the dashboard registry's ``purpose``: the page clamps it
    visually with an explicit ellipsis instead of losing the end of the sentence here).
    """
    lines: list[str] = []
    in_fence = False
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line.startswith(("#", ">", "![[", "---")):
            if lines:
                break
            continue
        lines.append(re.sub(r"[*_`]", "", line))
        if limit is not None and len(" ".join(lines)) >= limit:
            break
    return " ".join(lines) if limit is None else " ".join(lines)[:limit + 40]


def project_relative(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _search_by_name(root: Path, basename: str) -> list[Path]:
    """Find files named `basename` under root, skipping dot-directories.

    Stops after a second match: only a unique match is usable, so walking the
    whole tree (which may be an entire vault) past that point is wasted work.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        if basename in filenames:
            found.append(Path(dirpath) / basename)
            if len(found) > 1:
                break
    return found


def resolve_file_reference(raw: Any, note: Path, root: Path) -> str | None:
    """Resolve a wikilink / relative path / basename into a project-relative path.

    Unresolvable references come back verbatim rather than as None so intent is
    never silently dropped.
    """
    if not raw:
        return None
    text = strip_wikilink(str(raw)).split("#", 1)[0]
    if not text or "://" in text:
        return text or None
    candidate = Path(text).expanduser()
    candidates = [candidate] if candidate.is_absolute() else [note.parent / candidate, root / candidate]
    if not candidate.suffix:
        candidates += [path.with_suffix(".md") for path in list(candidates)]
    for path in candidates:
        if path.is_file():
            return project_relative(path, root)
    matches = _search_by_name(root, candidate.name)
    if len(matches) == 1:
        return project_relative(matches[0], root)
    return candidate.as_posix()


def media_refs(body: str, note: Path, root: Path) -> list[dict[str, str]]:
    """Embedded images/files referenced from the note body."""
    seen: set[str] = set()
    refs: list[dict[str, str]] = []
    for raw in [*WIKI_IMAGE.findall(body), *MARKDOWN_IMAGE.findall(body)]:
        resolved = resolve_file_reference(raw, note, root)
        if not resolved or resolved in seen or "://" in resolved:
            continue
        seen.add(resolved)
        suffix = Path(resolved).suffix.lower()
        kind = "image" if suffix in IMAGE_SUFFIXES else "file"
        refs.append({"path": resolved, "kind": kind, "label": Path(resolved).name})
    return refs
