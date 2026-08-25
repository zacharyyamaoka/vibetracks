from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Iterable

import yaml


DEFAULT_STATUSES = [
    "backlog",
    "ready",
    "running",
    "waiting",
    "review",
    "frontier",
    "done",
    "archived",
]

DEFAULT_PROPERTIES = {
    "marker": "vibe-track",
    "id": "vibe-id",
    "status": "vibe-status",
    "description": "vibe-description",
    "dependsOn": "vibe-depends-on",
    "areas": "vibe-areas",
    "priority": "vibe-priority",
    "archived": "vibe-archived",
    "reviewPacket": "vibe-review-packet",
    "preview": "vibe-preview",
    "evidence": "vibe-evidence",
    "runs": "vibe-runs",
    "updated": "vibe-updated",
}

STATUS_ALIASES = {
    "todo": "ready",
    "to-do": "ready",
    "in-progress": "running",
    "in-review": "review",
    "cancelled": "archived",
    "canceled": "archived",
}

FRONTMATTER = re.compile(r"\A\ufeff?---\r?\n(?P<yaml>[\s\S]*?)\r?\n---[ \t]*\r?\n?")
IN_FOLDER = re.compile(r"file\.inFolder\(\s*[\"'](?P<folder>[^\"']+)[\"']\s*\)")
MARKER_FILTER = re.compile(
    r"note\[[\"'](?P<property>[^\"']+)[\"']\]\s*==\s*[\"'](?P<value>[^\"']+)[\"']"
)
WIKI_IMAGE = re.compile(r"!\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class VibeTracksError(RuntimeError):
    pass


class RevisionConflict(VibeTracksError):
    pass


class InvalidTransition(VibeTracksError):
    pass


@dataclass
class MediaRef:
    path: str
    kind: str
    label: str


@dataclass
class TrackItem:
    id: str
    title: str
    path: str
    absolute_path: str
    status: str
    description: str
    body: str
    areas: list[str] = field(default_factory=list)
    priority: str = "none"
    archived: bool = False
    dependencies: list[str] = field(default_factory=list)
    unresolved_dependencies: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    review_packet: str | None = None
    preview: str | None = None
    evidence: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    media: list[MediaRef] = field(default_factory=list)
    revision: str = ""
    updated: str = ""
    obsidian_uri: str | None = None
    raw_dependencies: list[str] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("absolute_path", None)
        data.pop("raw_dependencies", None)
        return data


@dataclass
class TrackProject:
    descriptor: Path
    root: Path
    source: Path
    id: str
    title: str
    description: str
    statuses: list[str]
    properties: dict[str, str]
    views: list[dict[str, Any]]
    items: list[TrackItem]
    revision: str
    obsidian_vault: str | None = None

    def item_by_id(self, feature_id: str) -> TrackItem | None:
        return next((item for item in self.items if item.id == feature_id), None)

    def resolve_project_path(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError as exc:
            raise VibeTracksError("Path leaves the configured project root") from exc
        return candidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "descriptor": str(self.descriptor),
            "root": str(self.root),
            "source": str(self.source),
            "statuses": self.statuses,
            "views": self.views,
            "revision": self.revision,
            "obsidianVault": self.obsidian_vault,
            "items": [item.to_dict() for item in self.items],
        }


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def _strip_property(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip()
    return text.removeprefix("note.")


def _normalize_status(value: Any) -> str:
    status = str(value or "ready").strip().lower().replace(" ", "-")
    return STATUS_ALIASES.get(status, status)


def _strip_wikilink(value: str) -> str:
    text = value.strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.split("|", 1)[0].strip()
    return text


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "feature"


def _extract_filter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _extract_filter_strings(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _extract_filter_strings(child)


def _frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER.match(markdown)
    if not match:
        return {}, markdown
    loaded = yaml.safe_load(match.group("yaml")) or {}
    if not isinstance(loaded, dict):
        raise VibeTracksError("Markdown frontmatter must be a mapping")
    return loaded, markdown[match.end():]


def _first_paragraph(body: str) -> str:
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
        cleaned = re.sub(r"[*_`]", "", line)
        lines.append(cleaned)
        if len(" ".join(lines)) >= 240:
            break
    return " ".join(lines)[:280]


def _revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _project_relative(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _resolve_file_reference(raw: Any, note: Path, root: Path) -> str | None:
    if not raw:
        return None
    text = _strip_wikilink(str(raw)).split("#", 1)[0]
    if not text or "://" in text:
        return text or None
    candidate = Path(text).expanduser()
    candidates = [candidate] if candidate.is_absolute() else [note.parent / candidate, root / candidate]
    if not candidate.suffix:
        candidates += [path.with_suffix(".md") for path in list(candidates)]
    for path in candidates:
        if path.is_file():
            return _project_relative(path, root)
    basename = candidate.name
    matches = [path for path in root.rglob(basename) if path.is_file()]
    if len(matches) == 1:
        return _project_relative(matches[0], root)
    return candidate.as_posix()


def _media_refs(body: str, note: Path, root: Path) -> list[MediaRef]:
    seen: set[str] = set()
    refs: list[MediaRef] = []
    for raw in [*WIKI_IMAGE.findall(body), *MARKDOWN_IMAGE.findall(body)]:
        resolved = _resolve_file_reference(raw, note, root)
        if not resolved or resolved in seen or "://" in resolved:
            continue
        seen.add(resolved)
        suffix = Path(resolved).suffix.lower()
        kind = "image" if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"} else "file"
        refs.append(MediaRef(path=resolved, kind=kind, label=Path(resolved).name))
    return refs


def _load_descriptor(descriptor: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(descriptor.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise VibeTracksError("The project descriptor must contain a YAML mapping")
    return loaded


def _descriptor_settings(descriptor: Path, config: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    meta = _as_mapping(config.get("vibetracks"))
    root_value = str(meta.get("vaultRoot") or meta.get("root") or ".").strip()
    root_path = Path(root_value).expanduser()
    root = root_path.resolve() if root_path.is_absolute() else (descriptor.parent / root_path).resolve()

    source_value = str(meta.get("source") or "").strip()
    if not source_value:
        for expression in _extract_filter_strings(config.get("filters")):
            match = IN_FOLDER.search(expression)
            if match:
                source_value = match.group("folder")
                break
    source_value = source_value or "."
    source_path = Path(source_value).expanduser()
    source = source_path.resolve() if source_path.is_absolute() else (root / source_path).resolve()
    if not source.is_dir() and not source_path.is_absolute():
        alternate = (descriptor.parent / source_path).resolve()
        if alternate.is_dir():
            source = alternate
    return root, source, meta


def _marker(config: dict[str, Any], meta: dict[str, Any], properties: dict[str, str]) -> tuple[str, str] | None:
    marker = _as_mapping(meta.get("marker"))
    if marker:
        return str(marker.get("property") or properties["marker"]), str(marker.get("value") or "feature")
    for expression in _extract_filter_strings(config.get("filters")):
        match = MARKER_FILTER.search(expression)
        if match:
            return match.group("property"), match.group("value")
    return None


def _item_from_file(
    path: Path,
    root: Path,
    properties: dict[str, str],
    obsidian_vault: str | None,
) -> tuple[TrackItem, dict[str, Any]]:
    content = path.read_text(encoding="utf-8")
    frontmatter, body = _frontmatter(content)
    heading = HEADING.search(body)
    title = str(frontmatter.get("title") or (heading.group(1).strip() if heading else path.stem))
    item_id = str(frontmatter.get(properties["id"]) or _slug(path.stem)).strip()
    status = _normalize_status(frontmatter.get(properties["status"]))
    archived = bool(frontmatter.get(properties["archived"], False)) or status == "archived"
    relative = _project_relative(path, root) or path.name
    description = str(frontmatter.get(properties["description"]) or _first_paragraph(body)).strip()
    review_packet = _resolve_file_reference(frontmatter.get(properties["reviewPacket"]), path, root)
    preview = _resolve_file_reference(frontmatter.get(properties["preview"]), path, root)
    evidence = [
        resolved
        for value in _strings(frontmatter.get(properties["evidence"]))
        if (resolved := _resolve_file_reference(value, path, root))
    ]
    obsidian_uri = None
    if obsidian_vault:
        from urllib.parse import quote

        obsidian_uri = f"obsidian://open?vault={quote(obsidian_vault)}&file={quote(relative)}"
    updated_value = frontmatter.get(properties["updated"])
    updated = str(updated_value) if updated_value else datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    item = TrackItem(
        id=item_id,
        title=title,
        path=relative,
        absolute_path=str(path.resolve()),
        status=status,
        description=description,
        body=body.strip(),
        areas=_strings(frontmatter.get(properties["areas"])),
        priority=str(frontmatter.get(properties["priority"]) or "none").lower(),
        archived=archived,
        raw_dependencies=_strings(frontmatter.get(properties["dependsOn"])),
        review_packet=review_packet,
        preview=preview,
        evidence=evidence,
        runs=_strings(frontmatter.get(properties["runs"])),
        media=_media_refs(body, path, root),
        revision=_revision(content),
        updated=updated,
        obsidian_uri=obsidian_uri,
    )
    return item, frontmatter


def _dependency_key(value: str) -> str:
    text = _strip_wikilink(value).removesuffix(".md")
    return text.split("/")[-1].strip().lower()


def load_project(descriptor: str | Path) -> TrackProject:
    descriptor_path = Path(descriptor).expanduser().resolve()
    if descriptor_path.suffix not in {".base", ".vibetrack"}:
        raise VibeTracksError("Expected a .base or .vibetrack descriptor")
    if not descriptor_path.is_file():
        raise VibeTracksError(f"Descriptor does not exist: {descriptor_path}")
    config = _load_descriptor(descriptor_path)
    root, source, meta = _descriptor_settings(descriptor_path, config)
    if not source.is_dir():
        raise VibeTracksError(f"Feature source folder does not exist: {source}")

    configured_properties = _as_mapping(meta.get("properties"))
    properties = {
        name: _strip_property(configured_properties.get(name), default)
        for name, default in DEFAULT_PROPERTIES.items()
    }
    marker = _marker(config, meta, properties)
    obsidian_vault = str(meta.get("obsidianVault") or "").strip() or None
    items: list[TrackItem] = []
    for note in sorted(source.rglob("*.md")):
        item, frontmatter = _item_from_file(note, root, properties, obsidian_vault)
        if marker and str(frontmatter.get(marker[0], "")) != marker[1]:
            continue
        items.append(item)

    aliases: dict[str, str] = {}
    for item in items:
        for alias in {item.id, item.title, Path(item.path).stem, item.path.removesuffix(".md")}:
            aliases[alias.lower()] = item.id
    by_id = {item.id: item for item in items}
    for item in items:
        for raw in item.raw_dependencies:
            resolved = aliases.get(_dependency_key(raw)) or aliases.get(_strip_wikilink(raw).lower())
            if resolved and resolved != item.id:
                if resolved not in item.dependencies:
                    item.dependencies.append(resolved)
            else:
                item.unresolved_dependencies.append(raw)
    for item in items:
        for dependency in item.dependencies:
            if item.id not in by_id[dependency].dependents:
                by_id[dependency].dependents.append(item.id)

    statuses = [_normalize_status(value) for value in _strings(meta.get("statuses"))] or list(DEFAULT_STATUSES)
    for item in items:
        if item.status not in statuses:
            statuses.append(item.status)
    project_hash = hashlib.sha256()
    project_hash.update(descriptor_path.read_bytes())
    for item in items:
        project_hash.update(item.id.encode("utf-8"))
        project_hash.update(item.revision.encode("ascii"))
    return TrackProject(
        descriptor=descriptor_path,
        root=root,
        source=source,
        id=str(meta.get("id") or _slug(descriptor_path.stem)),
        title=str(meta.get("title") or descriptor_path.stem),
        description=str(meta.get("description") or ""),
        statuses=statuses,
        properties=properties,
        views=[view for view in _as_list(config.get("views")) if isinstance(view, dict)],
        items=items,
        revision=project_hash.hexdigest()[:16],
        obsidian_vault=obsidian_vault,
    )


def _replace_frontmatter_scalar(markdown: str, key: str, value: str) -> str:
    match = FRONTMATTER.match(markdown)
    line = f"{key}: {value}"
    if not match:
        return f"---\n{line}\n---\n\n{markdown.lstrip()}"
    yaml_source = match.group("yaml")
    pattern = re.compile(rf"^{re.escape(key)}\s*:.*$", re.MULTILINE)
    if pattern.search(yaml_source):
        yaml_source = pattern.sub(line, yaml_source, count=1)
    else:
        yaml_source = f"{yaml_source.rstrip()}\n{line}"
    return f"---\n{yaml_source}\n---\n{markdown[match.end():]}"


def update_feature_status(
    descriptor: str | Path,
    feature_id: str,
    status: str,
    expected_revision: str,
) -> TrackItem:
    project = load_project(descriptor)
    item = project.item_by_id(feature_id)
    if item is None:
        raise VibeTracksError(f"Unknown feature: {feature_id}")
    normalized = _normalize_status(status)
    if normalized not in project.statuses:
        raise InvalidTransition(f"Unsupported status: {status}")
    if item.revision != expected_revision:
        raise RevisionConflict(
            f"Feature changed since it was loaded ({expected_revision} != {item.revision})"
        )
    path = Path(item.absolute_path)
    original = path.read_text(encoding="utf-8")
    if _revision(original) != expected_revision:
        raise RevisionConflict("Feature changed while the status update was being prepared")
    updated = _replace_frontmatter_scalar(original, project.properties["status"], normalized)
    if updated == original:
        return item
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
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
        if _revision(path.read_text(encoding="utf-8")) != expected_revision:
            raise RevisionConflict("Feature changed before the status update could be committed")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    refreshed = load_project(descriptor).item_by_id(feature_id)
    if refreshed is None:
        raise VibeTracksError("Feature disappeared after status update")
    return refreshed
