from __future__ import annotations

import argparse
from pathlib import Path

from .model import VibeTracksError, load_project
from .server import serve


def _discover_descriptor(folder: Path) -> Path:
    candidates = sorted(folder.glob("*.vibetrack")) + sorted(folder.glob("*.base"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise VibeTracksError("No .vibetrack or .base descriptor found; pass one explicitly")
    raise VibeTracksError("Several project descriptors found; pass the one to open")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vibetracks",
        description="Render Markdown feature files as Graph, Kanban, and Focus views.",
    )
    parser.add_argument(
        "descriptor",
        nargs="?",
        help="Path to a Base-compatible .base or .vibetrack project descriptor.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Print a compact project summary and exit.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        descriptor = Path(args.descriptor).expanduser() if args.descriptor else _discover_descriptor(Path.cwd())
        descriptor = descriptor.resolve()
        project = load_project(descriptor)
        if args.inspect:
            counts: dict[str, int] = {}
            for item in project.items:
                counts[item.status] = counts.get(item.status, 0) + 1
            print(f"{project.title} · {len(project.items)} features · revision {project.revision}")
            print(f"source: {project.source}")
            print("statuses: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
            return
        serve(descriptor, host=args.host, port=args.port, open_browser=args.open_browser)
    except VibeTracksError as exc:
        raise SystemExit(f"vibetracks: {exc}") from exc

