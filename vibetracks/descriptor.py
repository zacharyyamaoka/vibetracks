"""Project descriptor loading.

One schema, two host-facing extensions: a real `.base` file inside an Obsidian
vault, `.vibetrack` with the same YAML shape everywhere else. The descriptor is
a query/view description plus project memory (statuses, areas, id prefix) — the
Markdown notes remain the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from .errors import VibeTracksError
from .notes import as_mapping, slugify, string_list

DESCRIPTOR_SUFFIXES = {".base", ".vibetrack"}

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

IN_FOLDER = re.compile(r"file\.inFolder\(\s*[\"'](?P<folder>[^\"']+)[\"']\s*\)")
MARKER_FILTER = re.compile(
    r"note\[[\"'](?P<property>[^\"']+)[\"']\]\s*==\s*[\"'](?P<value>[^\"']+)[\"']"
)


@dataclass
class DescriptorConfig:
    path: Path
    root: Path
    source: Path
    id: str
    title: str
    description: str
    statuses: list[str]
    properties: dict[str, str]
    marker: tuple[str, str] | None
    views: list[dict[str, Any]]
    obsidian_vault: str | None
    id_prefix: str
    areas: dict[str, str] = field(default_factory=dict)


def _extract_filter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _extract_filter_strings(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _extract_filter_strings(child)


def _strip_property(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip()
    return text.removeprefix("note.")


def _declared_areas(value: Any) -> dict[str, str]:
    """`areas:` accepts a mapping (name -> description) or a bare name list."""
    if isinstance(value, dict):
        return {str(name).strip(): str(description or "").strip() for name, description in value.items() if str(name).strip()}
    return {name: "" for name in string_list(value)}


def load_descriptor(descriptor: str | Path) -> DescriptorConfig:
    path = Path(descriptor).expanduser().resolve()
    if path.suffix not in DESCRIPTOR_SUFFIXES:
        raise VibeTracksError("Expected a .base or .vibetrack descriptor")
    if not path.is_file():
        raise VibeTracksError(f"Descriptor does not exist: {path}")
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise VibeTracksError(f"Descriptor is not valid YAML ({path.name}): {exc}") from exc
    if not isinstance(config, dict):
        raise VibeTracksError("The project descriptor must contain a YAML mapping")

    meta = as_mapping(config.get("vibetracks"))

    root_value = str(meta.get("vaultRoot") or meta.get("root") or ".").strip()
    root_path = Path(root_value).expanduser()
    root = root_path.resolve() if root_path.is_absolute() else (path.parent / root_path).resolve()

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
        alternate = (path.parent / source_path).resolve()
        if alternate.is_dir():
            source = alternate

    configured_properties = as_mapping(meta.get("properties"))
    properties = {
        name: _strip_property(configured_properties.get(name), default)
        for name, default in DEFAULT_PROPERTIES.items()
    }

    marker: tuple[str, str] | None = None
    marker_config = as_mapping(meta.get("marker"))
    if marker_config:
        marker = (
            str(marker_config.get("property") or properties["marker"]),
            str(marker_config.get("value") or "feature"),
        )
    else:
        for expression in _extract_filter_strings(config.get("filters")):
            match = MARKER_FILTER.search(expression)
            if match:
                marker = (match.group("property"), match.group("value"))
                break

    # Declared statuses are the project's own vocabulary: case/space
    # normalization only, never alias-mapped (a track may declare `todo`).
    statuses = [
        value.strip().lower().replace(" ", "-")
        for value in string_list(meta.get("statuses"))
    ] or list(DEFAULT_STATUSES)

    return DescriptorConfig(
        path=path,
        root=root,
        source=source,
        id=str(meta.get("id") or slugify(path.stem)),
        title=str(meta.get("title") or path.stem),
        description=str(meta.get("description") or ""),
        statuses=statuses,
        properties=properties,
        marker=marker,
        views=[view for view in config.get("views", []) if isinstance(view, dict)] if isinstance(config.get("views"), list) else [],
        obsidian_vault=str(meta.get("obsidianVault") or "").strip() or None,
        id_prefix=str(meta.get("idPrefix") or "VT").strip() or "VT",
        areas=_declared_areas(meta.get("areas")),
    )
