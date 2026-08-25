"""`vibetracks init` — turn any folder into a track.

Creates a descriptor plus a `features/` folder. Inside an Obsidian vault the
descriptor is a real `.base` (so Obsidian itself can open it); anywhere else it
is a `.vibetrack` with the identical YAML shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from .descriptor import DESCRIPTOR_SUFFIXES
from .edits import create_feature
from .errors import VibeTracksError
from .notes import slugify

DESCRIPTOR_TEMPLATE = """\
filters:
  and:
    - 'note["vibe-track"] == "feature"'
    - 'file.inFolder("features")'

views:
  - type: vibetracks-graph
    name: Graph
  - type: vibetracks-kanban
    name: Kanban
  - type: vibetracks-focus
    name: Focus
  - type: table
    name: Plain data
    order:
      - file.name
      - vibe-id
      - vibe-status
      - vibe-depends-on
      - vibe-areas

vibetracks:
  version: 1
  id: {project_id}
  title: {title}
  description: ""
  vaultRoot: .
  source: features
  idPrefix: VT
  statuses: [backlog, ready, running, waiting, review, frontier, done, archived]
  # Area memory — the shared vocabulary humans and dispatch agents tag work with.
  # Grow it as themes emerge; keep each description to one line, e.g.:
  #   areas:
  #     backend: Server, model, and storage work
  areas: {{}}
"""

STARTER_BODY = """\
This note is a feature conversation: frontmatter carries the trackable state,
the body carries durable context, decisions, evidence, and feedback.

- Create more features with `vibetracks new "Title"` or by writing Markdown.
- Open the panel with `vibetracks serve`.
- Brief a dispatch agent with `vibetracks agent`.
"""


def _inside_obsidian_vault(target: Path) -> bool:
    return any((folder / ".obsidian").is_dir() for folder in [target, *target.parents])


def find_descriptors(folder: Path) -> list[Path]:
    return sorted(
        path
        for suffix in DESCRIPTOR_SUFFIXES
        for path in folder.glob(f"*{suffix}")
    )


def init_project(
    target: str | Path,
    *,
    title: str | None = None,
    use_base: bool | None = None,
) -> Path:
    """Scaffold a descriptor + features folder; returns the descriptor path."""
    folder = Path(target).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    existing = find_descriptors(folder)
    if existing:
        raise VibeTracksError(
            f"Already initialized: {', '.join(path.name for path in existing)}"
        )
    if use_base is None:
        use_base = _inside_obsidian_vault(folder)
    resolved_title = (title or folder.name).strip() or folder.name
    descriptor = folder / f"Project.{'base' if use_base else 'vibetrack'}"
    # json.dumps produces a valid double-quoted YAML scalar, so titles with
    # colons, quotes, or leading brackets cannot corrupt the descriptor.
    descriptor.write_text(
        DESCRIPTOR_TEMPLATE.format(
            project_id=json.dumps(slugify(resolved_title)),
            title=json.dumps(resolved_title),
        ),
        encoding="utf-8",
    )
    (folder / "features").mkdir(exist_ok=True)
    (folder / "reports").mkdir(exist_ok=True)
    create_feature(
        descriptor,
        f"Adopt Vibe Tracks in {resolved_title}",
        status="ready",
        description="Starter feature showing the note anatomy. Edit or delete freely.",
        body=STARTER_BODY,
    )
    return descriptor
