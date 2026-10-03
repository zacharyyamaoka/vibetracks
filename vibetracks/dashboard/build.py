"""Build the dashboard projection: ``python3 -m vibetracks.dashboard.build [--data-home DIR] [--refresh-sources]``.

The data home (default ``~/.local/share/vibetracks/dashboard``, or ``dashboard_data_home`` in vibetracks/sources.py) holds:

- ``sources/bam-loops-snapshot-2026-10-03.json``: the verified snapshot of both BAM loops (copied once from the
  research context; the adapter reads only this copy),
- ``sources/kinsim-curriculum-2026-10-03.json``: the kinsim curriculum the snapshot names, for each rung's
  ``kpi_weight`` (the one column the snapshot does not carry),
- ``projection.json``: the output, schema ``vibetracks-dashboard/1`` (docs/dashboard/PROJECTION.md).

WHY a copy in the data home and not a read of the research folder: the research folder is a report's evidence and
may be moved or rewritten; the dashboard's input must stay put and be named in the projection's ``source`` block.
TODO(live): replace the snapshot with the loops' own files (see adapters/bam_loops.py).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from .adapters.bam_loops import build_projection, load_json
from ..sources import load_sources

_SOURCES = load_sources()
#: The data home when neither ``--data-home`` nor ``$VIBETRACKS_DASHBOARD_HOME`` names one (vibetracks/sources.py).
DEFAULT_HOME = Path(_SOURCES["dashboard_data_home"])
SNAPSHOT_NAME = "bam-loops-snapshot-2026-10-03.json"
CURRICULUM_NAME = "kinsim-curriculum-2026-10-03.json"
#: Where the sources were verified (2026-10-03). Read only to seed the data home. The snapshot is a dated research
#: artifact, not a live loop folder, so it stays a constant; the curriculum comes from ``kinsim_curriculum_dir``.
SNAPSHOT_ORIGIN = Path("/home/bam/vibetracks/reports/media/dashboard-prior-art-2026-10-03/context/real-data.json")
CURRICULUM_ORIGIN = Path(_SOURCES["kinsim_curriculum_dir"]) / "curriculum.json"


def data_home(value: str | os.PathLike[str] | None = None) -> Path:
    return Path(value or os.environ.get("VIBETRACKS_DASHBOARD_HOME") or load_sources()["dashboard_data_home"]).expanduser()


def seed_sources(home: Path, *, refresh: bool = False, snapshot_origin: Path = SNAPSHOT_ORIGIN,
                 curriculum_origin: Path = CURRICULUM_ORIGIN) -> tuple[Path, Path | None]:
    sources = home / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    snapshot = sources / SNAPSHOT_NAME
    curriculum = sources / CURRICULUM_NAME
    if refresh or not snapshot.exists():
        if not snapshot_origin.is_file():
            raise FileNotFoundError(f"no snapshot at {snapshot} and none to copy from {snapshot_origin}")
        shutil.copyfile(snapshot_origin, snapshot)
    if (refresh or not curriculum.exists()) and curriculum_origin.is_file():
        shutil.copyfile(curriculum_origin, curriculum)
    return snapshot, (curriculum if curriculum.exists() else None)


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def build(home: Path, *, refresh: bool = False) -> dict:
    snapshot_path, curriculum_path = seed_sources(home, refresh=refresh)
    projection = build_projection(
        load_json(snapshot_path),
        load_json(curriculum_path) if curriculum_path else None,
        snapshot_path=str(snapshot_path),
        curriculum_path=str(curriculum_path) if curriculum_path else None,
    )
    write_json_atomic(home / "projection.json", projection)
    return projection


def stats(projection: dict) -> str:
    lines = []
    for track in projection["tracks"]:
        items = sum(len(v) for v in track["evidence"]["by_iteration"].values())
        lines.append(f"  {track['id']:<7} {track['kind']:<10} {len(track['iterations']):>2} iterations · {len(track['kpis']):>2} KPIs · "
                     f"{items:>3} evidence items · {len(track['needs_you'])} needs-you")
    kinds: dict[str, int] = {}
    for item in projection["media"].values():
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    lines.append("  media: " + ", ".join(f"{n} {kind}" for kind, n in sorted(kinds.items())))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Vibe Tracks dashboard projection.")
    parser.add_argument("--data-home", help=f"default: $VIBETRACKS_DASHBOARD_HOME or {DEFAULT_HOME}")
    parser.add_argument("--refresh-sources", action="store_true", help="re-copy the snapshot and curriculum from their origins")
    args = parser.parse_args(argv)
    home = data_home(args.data_home)
    projection = build(home, refresh=args.refresh_sources)
    print(f"wrote {home / 'projection.json'}")
    print(stats(projection))
    return 0


if __name__ == "__main__":
    sys.exit(main())
