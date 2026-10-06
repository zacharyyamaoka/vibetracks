"""Write-side: narrow, revision-fenced, atomic edits of individual notes.

Every mutation follows the same discipline:

1. The caller supplies the note revision it last read (`expectedRevision`).
2. The file is re-read and the fence checked immediately before commit.
3. The new content is written to a temporary file and atomically `os.replace`d.
4. Only the intended span changes — untouched frontmatter keys and body text
   keep their exact original formatting.

A conflict raises `RevisionConflict`; stale writers refuse instead of silently
overwriting newer work. Note: this coordinates *disk* files. It cannot see a
live editor buffer (e.g. a note open and unsaved in Obsidian) — hosts with live
buffers must route writes through the host editor's own API.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Callable, Iterable

import yaml

from .errors import InvalidTransition, RevisionConflict, UnknownFeature, VibeTracksError
from .notes import FRONTMATTER, normalize_status, note_revision, parse_frontmatter
from .project import TrackItem, TrackProject, load_project

try:
    import fcntl
except ImportError:  # Windows: no advisory locks; the revision fence still holds
    fcntl = None

LOCK_FILENAME = ".vibetracks.lock"


@contextmanager
def _write_lock(directory: Path):
    """Serialize writers within one source folder via an advisory lock.

    Closes the check-then-replace window between concurrent fenced writers and
    the id-allocation race between concurrent `vibetracks new` calls. On
    platforms without fcntl the revision fence alone still refuses stale
    writes; only the simultaneous-commit interleaving remains theoretical.
    """
    if fcntl is None:
        yield
        return
    lock_path = directory / LOCK_FILENAME
    handle = open(lock_path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _serialize_entry(key: str, value: object) -> list[str]:
    dumped = yaml.safe_dump(
        {key: value},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )
    # WHY split on "\n" only: the dumper's line break; splitlines would also cut at U+2028 inside a quoted value.
    return dumped.rstrip("\n").split("\n")


def _span_end(lines: list[str], start: int) -> int:
    """Index one past the last line of the block value starting after a key.

    Value lines are indented lines and zero-indent sequence items. Blank and
    comment-only lines are legal *inside* a block value, so they extend the
    span — but only when more value lines follow; a trailing blank/comment run
    before the next key belongs to the surrounding document and is preserved.
    """
    end = start
    scan = start
    while scan < len(lines):
        line = lines[scan]
        stripped = line.strip()
        if line.startswith((" ", "\t")) or line.startswith("- "):
            scan += 1
            end = scan
        elif not stripped or stripped.startswith("#"):
            scan += 1  # tentative: joins the span only if value lines follow
        else:
            break
    return end


_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")


def _lines_keepends(text: str) -> list[str]:
    """``text`` split after each CRLF, CR or LF, every line keeping its own ending, so ``"".join`` is ``text``.

    WHY not ``str.splitlines``: it also splits on U+2028, form feed, \\x1c..., which are characters inside a value,
    not line breaks of the note; and joining its lines back with "\\n" turned every CRLF note into LF.
    """
    return _LINE.findall(text)


def _ending(line: str) -> str:
    return line[len(line.rstrip("\r\n")):]


def _splice_yaml_key(yaml_source: str, key: str, serialized: list[str], eol: str = "\n") -> str:
    """Replace one top-level key's span, preserving every other byte verbatim (line endings included).

    Every span of the key is consumed (duplicate keys would otherwise leave a
    stale value that YAML's last-wins reading silently prefers); the
    replacement is written once, at the first occurrence, with the line ending
    the key's own line used (CRLF stays CRLF).
    """
    lines = _lines_keepends(yaml_source)
    bare = [line.rstrip("\r\n") for line in lines]
    default_eol = next((_ending(line) for line in lines if _ending(line)), eol)
    key_line = re.compile(rf"^{re.escape(key)}\s*:")
    output: list[str] = []
    index = 0
    replaced = False
    while index < len(lines):
        if key_line.match(bare[index]):
            end = _span_end(bare, index + 1)
            if not replaced:
                eol = _ending(lines[index]) or default_eol
                # The span's last line keeps its own ending ("" when it closes the YAML block before ``---``).
                output.append(eol.join(serialized) + _ending(lines[end - 1]))
                replaced = True
            index = end
            continue
        output.append(lines[index])
        index += 1
    if not replaced:
        # Appended before any trailing blank lines, which stay where they were.
        insert = len(output)
        while insert > 0 and not output[insert - 1].strip():
            insert -= 1
        block = default_eol.join(serialized)
        if insert == 0:
            output.insert(0, block + (default_eol if output else ""))
        else:
            previous = output[insert - 1]
            if not _ending(previous):
                output[insert - 1] = previous + default_eol
            output.insert(insert, block + (default_eol if insert < len(output) else ""))
    return "".join(output)


def replace_frontmatter_entry(markdown: str, key: str, value: object) -> str:
    """Set one frontmatter key (scalar or list), creating frontmatter if absent.

    Only the key's span changes: a BOM, the ``---`` delimiters exactly as written (trailing spaces included), every
    line ending and every byte of the body stay as they were. WHY (audit 2026-10-04, finding 8): the splicer rebuilt
    the note as ``"---\\n" + yaml + "\\n---\\n" + body``, so a BOM/CRLF note lost its BOM, its frontmatter line
    endings and the closing delimiter's spaces on a title rename that was only allowed to change ``vibe-title``.

    The result's frontmatter is re-parsed before being returned: an edit that
    would leave the note unreadable raises instead of corrupting the file.
    """
    serialized = _serialize_entry(key, value)
    match = FRONTMATTER.match(markdown)
    if not match:
        bom = "\ufeff" if markdown.startswith("\ufeff") else ""
        body = markdown[len(bom):]
        first = _lines_keepends(body)[:1]
        eol = (_ending(first[0]) if first else "") or "\n"
        block = eol.join(serialized)
        updated = f"{bom}---{eol}{block}{eol}---{eol}{eol}{body}"
    else:
        opening = markdown[:match.start("yaml")]
        yaml_source = _splice_yaml_key(match.group("yaml"), key, serialized, opening[len(opening.rstrip("\r\n")):])
        updated = markdown[:match.start("yaml")] + yaml_source + markdown[match.end("yaml"):]
    try:
        parse_frontmatter(updated)
    except VibeTracksError as exc:
        raise VibeTracksError(
            f"Refusing an edit that would corrupt the note's frontmatter: {exc}"
        ) from exc
    return updated


def append_body_block(markdown: str, block: str) -> str:
    """Append a Markdown block to the end of the note, separated by a blank line."""
    return f"{markdown.rstrip()}\n\n{block.rstrip()}\n"


def read_note_exact(path: Path) -> str:
    """The note's text exactly as stored: no newline translation (CRLF stays CRLF) and a BOM kept as U+FEFF."""
    return path.read_bytes().decode("utf-8")


def _universal_newlines(text: str) -> str:
    """What ``Path.read_text`` returns for ``text``: CRLF and CR read as LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def apply_note_edit(
    path: Path,
    expected_revision: str,
    transform: Callable[[str], str],
) -> bool:
    """Atomically rewrite `path` through `transform`, fenced on `expected_revision`.

    Returns False when the transform was a no-op. Raises `RevisionConflict`
    when the file no longer matches the revision the caller reviewed.
    """
    with _write_lock(path.parent):
        try:
            original = read_note_exact(path)
        except FileNotFoundError as exc:
            raise UnknownFeature(f"Note no longer exists: {path}") from exc
        # WHY two spellings of the same revision: the fence is the exact text now (registry.py reads it that way),
        # while project.py still hashes Python's newline-translated read; a note with no CR has one revision anyway.
        if expected_revision not in (note_revision(original), note_revision(_universal_newlines(original))):
            raise RevisionConflict(
                f"Note changed since it was loaded (expected {expected_revision})"
            )
        updated = transform(original)
        if updated == original:
            return False
        # WHY newline="": the transform returns the note's exact text; text-mode translation must not rewrite it.
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(stat.S_IMODE(path.stat().st_mode))
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def _fsync_directory(directory: Path) -> None:
    """Make a rename durable: fsync the directory entry (POSIX; no-op elsewhere)."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _require_item(project: TrackProject, feature_id: str) -> TrackItem:
    item = project.item_by_id(feature_id)
    if item is None:
        raise UnknownFeature(f"Unknown feature: {feature_id}")
    return item


def _refreshed_item(descriptor: str | Path, feature_id: str) -> TrackItem:
    refreshed = load_project(descriptor).item_by_id(feature_id)
    if refreshed is None:
        raise VibeTracksError("Feature disappeared after the edit")
    return refreshed


def update_feature_status(
    descriptor: str | Path,
    feature_id: str,
    status: str,
    expected_revision: str,
) -> TrackItem:
    project = load_project(descriptor)
    item = _require_item(project, feature_id)
    normalized = normalize_status(status, declared=project.statuses)
    if normalized not in project.statuses:
        raise InvalidTransition(f"Unsupported status: {status}")
    apply_note_edit(
        Path(item.absolute_path),
        expected_revision,
        lambda markdown: replace_frontmatter_entry(
            markdown, project.properties["status"], normalized
        ),
    )
    return _refreshed_item(descriptor, feature_id)


def serialize_dependencies(project: TrackProject, feature_id: str, tokens: Iterable[str]) -> list[str]:
    """Resolve dependency tokens to wikilinks where possible, verbatim otherwise.

    Self-referential tokens are dropped rather than rejected: the frontend
    resends the full list on every edit, so a stray self-edge left in a note by
    hand must not brick all subsequent dependency edits.
    """
    serialized: list[str] = []
    for token in tokens:
        text = str(token).strip()
        if not text:
            continue
        target = project.resolve_reference(text)
        if target is not None and target.id == feature_id:
            continue
        entry = f"[[{Path(target.path).stem}]]" if target is not None else text
        if entry not in serialized:
            serialized.append(entry)
    return serialized


def update_feature_dependencies(
    descriptor: str | Path,
    feature_id: str,
    depends_on: Iterable[str],
    expected_revision: str,
) -> TrackItem:
    project = load_project(descriptor)
    item = _require_item(project, feature_id)
    serialized = serialize_dependencies(project, feature_id, depends_on)
    apply_note_edit(
        Path(item.absolute_path),
        expected_revision,
        lambda markdown: replace_frontmatter_entry(
            markdown, project.properties["dependsOn"], serialized
        ),
    )
    return _refreshed_item(descriptor, feature_id)


def append_feature_comment(
    descriptor: str | Path,
    feature_id: str,
    text: str,
    expected_revision: str,
    author: str = "👦 Feedback",
) -> TrackItem:
    cleaned = str(text).strip()
    if not cleaned:
        raise VibeTracksError("Cannot append an empty comment")
    project = load_project(descriptor)
    item = _require_item(project, feature_id)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    quoted = "\n".join(f"> {line}" for line in cleaned.splitlines())
    block = f"> [!quote] {author} — {stamp}\n{quoted}"
    apply_note_edit(
        Path(item.absolute_path),
        expected_revision,
        lambda markdown: append_body_block(markdown, block),
    )
    return _refreshed_item(descriptor, feature_id)


def next_feature_id(project: TrackProject) -> str:
    """Next sequential id, counting EVERY note in the source tree.

    Marker-filtered notes still own their ids (a typoed marker must not cause
    the id to be minted twice), so the scan covers all Markdown files plus the
    ids embedded in filenames.
    """
    prefix = project.config.id_prefix
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)\b")
    numbers = [0]
    for item in project.items:
        if match := pattern.match(item.id):
            numbers.append(int(match.group(1)))
    id_property = project.properties["id"]
    for note in project.source.rglob("*.md"):
        if match := pattern.match(note.stem):
            numbers.append(int(match.group(1)))
        try:
            frontmatter, _ = parse_frontmatter(note.read_text(encoding="utf-8"))
        except (OSError, VibeTracksError, yaml.YAMLError):
            continue
        if match := pattern.match(str(frontmatter.get(id_property, ""))):
            numbers.append(int(match.group(1)))
    return f"{prefix}-{max(numbers) + 1:03d}"


def _safe_filename(title: str) -> str:
    # Windows/NTFS forbids <>:"/\|?* — strip them so clones stay portable.
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "Untitled"


def create_feature(
    descriptor: str | Path,
    title: str,
    *,
    status: str = "ready",
    areas: Iterable[str] = (),
    depends_on: Iterable[str] = (),
    description: str = "",
    priority: str | None = None,
    body: str = "",
) -> TrackItem:
    """Create a new feature note with the next sequential id.

    New notes are ordinary Markdown files; this helper only guarantees they are
    born well-formed (marker, id, status) so every lens picks them up.
    """
    cleaned_title = str(title).strip()
    if not cleaned_title:
        raise VibeTracksError("A feature needs a title")
    with _write_lock(Path(load_project(descriptor).source)):
        return _create_feature_locked(
            descriptor,
            cleaned_title,
            status=status,
            areas=areas,
            depends_on=depends_on,
            description=description,
            priority=priority,
            body=body,
        )


def _create_feature_locked(
    descriptor: str | Path,
    cleaned_title: str,
    *,
    status: str,
    areas: Iterable[str],
    depends_on: Iterable[str],
    description: str,
    priority: str | None,
    body: str,
) -> TrackItem:
    project = load_project(descriptor)
    properties = project.properties
    normalized = normalize_status(status, declared=project.statuses)
    if normalized not in project.statuses:
        raise InvalidTransition(f"Unsupported status: {status}")

    feature_id = next_feature_id(project)
    marker = project.config.marker or (properties["marker"], "feature")
    frontmatter: dict[str, object] = {marker[0]: marker[1], properties["id"]: feature_id}
    frontmatter[properties["status"]] = normalized
    if description.strip():
        frontmatter[properties["description"]] = description.strip()
    area_list = [str(area).strip() for area in areas if str(area).strip()]
    if area_list:
        frontmatter[properties["areas"]] = area_list
    serialized_dependencies = serialize_dependencies(project, feature_id, depends_on)
    if serialized_dependencies:
        frontmatter[properties["dependsOn"]] = serialized_dependencies
    if priority:
        frontmatter[properties["priority"]] = str(priority).lower()

    dumped = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )
    content = f"---\n{dumped}---\n\n# {cleaned_title}\n"
    if body.strip():
        content += f"\n{body.strip()}\n"

    path = project.source / f"{feature_id} - {_safe_filename(cleaned_title)}.md"
    try:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise VibeTracksError(f"Note already exists: {path}") from exc
    _fsync_directory(path.parent)
    return _refreshed_item(descriptor, feature_id)
