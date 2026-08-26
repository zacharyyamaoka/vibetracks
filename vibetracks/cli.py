"""Command line interface.

`vibetracks` alone serves the nearest track. Subcommands cover the dispatcher
verbs: `init` a track anywhere, `new` a feature, `status` / `comment` a note,
`inspect` the projection (optionally as JSON for agents), `track` to list the
lanes or brief one per-track agent, and `agent` to print the dispatcher
briefing.

Backwards compatible: `vibetracks path/to/Project.base --open-browser` still
works — a first argument that is not a subcommand is treated as `serve`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .edits import append_feature_comment, create_feature, update_feature_status
from .errors import VibeTracksError
from .project import TrackProject, load_project
from .scaffold import find_descriptors, init_project
from .server import probe_panel, serve
from .tracks import lane_table, track_briefing

SUBCOMMANDS = {"serve", "init", "new", "status", "comment", "inspect", "track", "agent"}


def discover_descriptor(start: Path) -> Path:
    """Find the nearest project descriptor: here, in ancestors, then one level down."""
    for folder in [start, *start.parents]:
        candidates = find_descriptors(folder)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            names = ", ".join(path.name for path in candidates)
            raise VibeTracksError(f"Several descriptors in {folder}; pass one explicitly ({names})")
        if (folder / ".git").exists():
            break  # never walk past a repository boundary — including the start folder's own
    nested = sorted(
        candidate
        for child in start.iterdir()
        if child.is_dir() and not child.name.startswith(".")
        for candidate in find_descriptors(child)
    ) if start.is_dir() else []
    if len(nested) == 1:
        return nested[0]
    raise VibeTracksError(
        "No .vibetrack or .base descriptor found here, above, or one level down. "
        "Run `vibetracks init` to create one, or pass a descriptor path."
    )


def _resolve_descriptor(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return discover_descriptor(Path.cwd()).resolve()


def _current_revision(descriptor: Path, feature_id: str) -> str:
    item = load_project(descriptor).item_by_id(feature_id)
    if item is None:
        raise VibeTracksError(f"Unknown feature: {feature_id}")
    return item.revision


def _print_inspect(project: TrackProject, as_json: bool) -> None:
    if as_json:
        print(json.dumps(project.to_dict(), ensure_ascii=False, indent=2))
        return
    counts: dict[str, int] = {}
    for item in project.items:
        counts[item.status] = counts.get(item.status, 0) + 1
    print(f"{project.title} · {len(project.items)} features · revision {project.revision}")
    print(f"source: {project.source}")
    print("statuses: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    unresolved = [(item.id, token) for item in project.items for token in item.unresolved_dependencies]
    if unresolved:
        print("unresolved dependencies: " + ", ".join(f"{fid}→{token}" for fid, token in unresolved))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vibetracks",
        description="File-first feature tracking: Markdown notes rendered as Graph, Kanban, and Focus.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve_parser = commands.add_parser("serve", help="Serve the browser panel (default)")
    serve_parser.add_argument("descriptor", nargs="?", help="A .base or .vibetrack descriptor")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=None, help="Port (default 8777, walks forward if busy)")
    serve_parser.add_argument("--open-browser", action="store_true")
    serve_parser.add_argument("--inspect", action="store_true", help=argparse.SUPPRESS)

    init_parser = commands.add_parser("init", help="Scaffold a track in a folder")
    init_parser.add_argument("path", nargs="?", default=".", help="Target folder (default: here)")
    init_parser.add_argument("--title", help="Project title (default: folder name)")
    init_parser.add_argument("--base", action="store_true", help="Force a .base descriptor")
    init_parser.add_argument("--vibetrack", action="store_true", help="Force a .vibetrack descriptor")

    new_parser = commands.add_parser("new", help="Create a feature note with the next id")
    new_parser.add_argument("title")
    new_parser.add_argument("--descriptor", help="Descriptor path (default: discovered)")
    new_parser.add_argument("--status", default="ready")
    new_parser.add_argument("--area", action="append", default=[], help="Repeatable")
    new_parser.add_argument("--depends-on", action="append", default=[], help="Repeatable; id or title")
    new_parser.add_argument("--description", default="")
    new_parser.add_argument("--priority")
    new_parser.add_argument("--body", default="", help="Markdown body below the heading")

    fence_help = (
        "Note revision (from an earlier `inspect --json`) the edit is conditioned on; "
        "omitting it fences only against changes during this command"
    )
    status_parser = commands.add_parser("status", help="Set a feature's status")
    status_parser.add_argument("feature_id")
    status_parser.add_argument("status")
    status_parser.add_argument("--descriptor")
    status_parser.add_argument("--expected-revision", help=fence_help)

    comment_parser = commands.add_parser("comment", help="Append a feedback comment to a feature note")
    comment_parser.add_argument("feature_id")
    comment_parser.add_argument("text")
    comment_parser.add_argument("--descriptor")
    comment_parser.add_argument("--author", default="🤖 Agent", help="Callout author label")
    comment_parser.add_argument("--expected-revision", help=fence_help)

    inspect_parser = commands.add_parser("inspect", help="Print a project summary")
    inspect_parser.add_argument("descriptor", nargs="?")
    inspect_parser.add_argument("--json", action="store_true", help="Full snapshot as JSON (for agents)")

    track_parser = commands.add_parser(
        "track", help="List the tracks, or brief one per-track agent on its lane")
    track_parser.add_argument("area", nargs="?", help="Area name; omit to list every track")
    track_parser.add_argument("--descriptor")
    track_parser.add_argument("--panel", help="Panel URL (default: probe for a running one)")

    commands.add_parser("agent", help="Print the dispatcher briefing (AGENT.md)")
    return parser


def _run(args: argparse.Namespace) -> None:
    if args.command == "serve":
        descriptor = _resolve_descriptor(args.descriptor)
        project = load_project(descriptor)
        if args.inspect:
            _print_inspect(project, as_json=False)
            return
        serve(
            descriptor,
            host=args.host,
            port=args.port if args.port is not None else 8777,
            open_browser=args.open_browser,
            port_is_explicit=args.port is not None,
        )
    elif args.command == "init":
        use_base = True if args.base else False if args.vibetrack else None
        descriptor = init_project(args.path, title=args.title, use_base=use_base)
        print(f"Initialized {descriptor}")
        print(f"Serve it with: vibetracks serve {descriptor}")
    elif args.command == "new":
        descriptor = _resolve_descriptor(args.descriptor)
        item = create_feature(
            descriptor,
            args.title,
            status=args.status,
            areas=args.area,
            depends_on=args.depends_on,
            description=args.description,
            priority=args.priority,
            body=args.body,
        )
        print(f"{item.id} · {item.title}")
        print(f"note: {item.path}")
    elif args.command == "status":
        descriptor = _resolve_descriptor(args.descriptor)
        revision = args.expected_revision or _current_revision(descriptor, args.feature_id)
        updated = update_feature_status(descriptor, args.feature_id, args.status, revision)
        print(f"{updated.id} → {updated.status}")
    elif args.command == "comment":
        descriptor = _resolve_descriptor(args.descriptor)
        revision = args.expected_revision or _current_revision(descriptor, args.feature_id)
        append_feature_comment(descriptor, args.feature_id, args.text, revision, author=args.author)
        print(f"Comment appended to {args.feature_id}")
    elif args.command == "inspect":
        descriptor = _resolve_descriptor(args.descriptor)
        _print_inspect(load_project(descriptor), as_json=args.json)
    elif args.command == "track":
        descriptor = _resolve_descriptor(args.descriptor)
        project = load_project(descriptor)
        panel = args.panel or probe_panel(descriptor)
        if args.area:
            print(track_briefing(project, args.area, panel))
        else:
            print(lane_table(project, panel))
    elif args.command == "agent":
        briefing = Path(__file__).resolve().parent / "AGENT.md"
        print(briefing.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["serve"]
    elif arguments[0] not in SUBCOMMANDS and arguments[0] not in {"-h", "--help"}:
        arguments = ["serve", *arguments]
    args = build_parser().parse_args(arguments)
    try:
        _run(args)
    except VibeTracksError as exc:
        raise SystemExit(f"vibetracks: {exc}") from exc
