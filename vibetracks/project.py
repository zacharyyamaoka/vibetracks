"""Project assembly: notes + descriptor → one navigable snapshot.

`load_project` re-derives everything from disk on every call. There is no
cache and no hidden state: the Markdown files are the database, this module is
the read lens.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .descriptor import DescriptorConfig, load_descriptor
from .errors import VibeTracksError
from .notes import (
    HEADING,
    first_paragraph,
    media_refs,
    normalize_status,
    note_revision,
    parse_frontmatter,
    project_relative,
    resolve_file_reference,
    slugify,
    string_list,
    strip_wikilink,
)


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
    media: list[dict[str, str]] = field(default_factory=list)
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
    config: DescriptorConfig
    items: list[TrackItem]
    revision: str
    aliases: dict[str, str] = field(default_factory=dict, repr=False)
    problems: list[dict[str, str]] = field(default_factory=list)

    @property
    def descriptor(self) -> Path:
        return self.config.path

    @property
    def root(self) -> Path:
        return self.config.root

    @property
    def source(self) -> Path:
        return self.config.source

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def title(self) -> str:
        return self.config.title

    @property
    def description(self) -> str:
        return self.config.description

    @property
    def statuses(self) -> list[str]:
        return self._statuses

    @property
    def properties(self) -> dict[str, str]:
        return self.config.properties

    @property
    def views(self) -> list[dict[str, Any]]:
        return self.config.views

    @property
    def obsidian_vault(self) -> str | None:
        return self.config.obsidian_vault

    def __post_init__(self) -> None:
        statuses = list(self.config.statuses)
        for item in self.items:
            if item.status not in statuses:
                statuses.append(item.status)
        self._statuses = statuses

    def item_by_id(self, feature_id: str) -> TrackItem | None:
        return next((item for item in self.items if item.id == feature_id), None)

    def resolve_reference(self, token: str) -> TrackItem | None:
        """Resolve a dependency token (id, title, filename, wikilink) to an item."""
        key = _dependency_key(token)
        feature_id = self.aliases.get(key) or self.aliases.get(strip_wikilink(token).lower())
        return self.item_by_id(feature_id) if feature_id else None

    def area_catalog(self) -> list[dict[str, str]]:
        """Declared descriptor areas ∪ areas actually used on items."""
        catalog = dict(self.config.areas)
        for item in self.items:
            for area in item.areas:
                catalog.setdefault(area, "")
        return [{"name": name, "description": description} for name, description in sorted(catalog.items())]

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
            "areaCatalog": self.area_catalog(),
            "views": self.views,
            "revision": self.revision,
            "obsidianVault": self.obsidian_vault,
            "problems": self.problems,
            "items": [item.to_dict() for item in self.items],
        }


def _dependency_key(value: str) -> str:
    text = strip_wikilink(value).split("#", 1)[0].removesuffix(".md")
    return text.split("/")[-1].strip().lower()


def _item_from_file(
    path: Path,
    config: DescriptorConfig,
) -> tuple[TrackItem, dict[str, Any]]:
    properties = config.properties
    root = config.root
    content = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(content)
    heading = HEADING.search(body)
    title = str(frontmatter.get("title") or (heading.group(1).strip() if heading else path.stem))
    status = normalize_status(frontmatter.get(properties["status"]), declared=config.statuses)
    relative = project_relative(path, root) or path.name
    evidence = [
        resolved
        for value in string_list(frontmatter.get(properties["evidence"]))
        if (resolved := resolve_file_reference(value, path, root))
    ]
    obsidian_uri = None
    if config.obsidian_vault:
        obsidian_uri = f"obsidian://open?vault={quote(config.obsidian_vault)}&file={quote(relative)}"
    updated_value = frontmatter.get(properties["updated"])
    updated = (
        str(updated_value)
        if updated_value
        else datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    )
    item = TrackItem(
        id=str(frontmatter.get(properties["id"]) or slugify(path.stem)).strip(),
        title=title,
        path=relative,
        absolute_path=str(path.resolve()),
        status=status,
        description=str(frontmatter.get(properties["description"]) or first_paragraph(body)).strip(),
        body=body.strip(),
        areas=string_list(frontmatter.get(properties["areas"])),
        priority=str(frontmatter.get(properties["priority"]) or "none").lower(),
        archived=bool(frontmatter.get(properties["archived"], False)) or status == "archived",
        raw_dependencies=string_list(frontmatter.get(properties["dependsOn"])),
        review_packet=resolve_file_reference(frontmatter.get(properties["reviewPacket"]), path, root),
        preview=resolve_file_reference(frontmatter.get(properties["preview"]), path, root),
        evidence=evidence,
        runs=string_list(frontmatter.get(properties["runs"])),
        media=media_refs(body, path, root),
        revision=note_revision(content),
        updated=updated,
        obsidian_uri=obsidian_uri,
    )
    return item, frontmatter


def load_project(descriptor: str | Path) -> TrackProject:
    config = load_descriptor(descriptor)
    if not config.source.is_dir():
        raise VibeTracksError(f"Feature source folder does not exist: {config.source}")

    items: list[TrackItem] = []
    problems: list[dict[str, str]] = []
    for note in sorted(config.source.rglob("*.md")):
        try:
            item, frontmatter = _item_from_file(note, config)
        except (VibeTracksError, OSError, UnicodeDecodeError) as exc:
            # One malformed or torn note must not take down the whole track:
            # skip it, but name it in the snapshot so it can be repaired.
            problems.append({
                "path": project_relative(note, config.root) or note.name,
                "error": str(exc),
            })
            continue
        if config.marker and str(frontmatter.get(config.marker[0], "")) != config.marker[1]:
            continue
        items.append(item)

    # Alias precedence: titles first, then filename stems/paths, then ids —
    # later tiers overwrite earlier ones, so a note *titled* with another
    # feature's id can never hijack that id.
    aliases: dict[str, str] = {}
    for item in items:
        aliases[item.title.lower()] = item.id
    for item in items:
        aliases[Path(item.path).stem.lower()] = item.id
        aliases[item.path.removesuffix(".md").lower()] = item.id
    for item in items:
        aliases[item.id.lower()] = item.id

    by_id = {item.id: item for item in items}
    for item in items:
        for raw in item.raw_dependencies:
            resolved = aliases.get(_dependency_key(raw)) or aliases.get(strip_wikilink(raw).lower())
            if resolved and resolved != item.id:
                if resolved not in item.dependencies:
                    item.dependencies.append(resolved)
            else:
                item.unresolved_dependencies.append(raw)
    for item in items:
        for dependency in item.dependencies:
            if item.id not in by_id[dependency].dependents:
                by_id[dependency].dependents.append(item.id)

    project_hash = hashlib.sha256()
    project_hash.update(config.path.read_bytes())
    for item in items:
        project_hash.update(item.id.encode("utf-8"))
        project_hash.update(item.revision.encode("ascii"))
    for problem in problems:
        project_hash.update(problem["path"].encode("utf-8"))
        project_hash.update(problem["error"].encode("utf-8"))

    return TrackProject(
        config=config,
        items=items,
        revision=project_hash.hexdigest()[:16],
        aliases=aliases,
        problems=problems,
    )
