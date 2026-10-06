"""``python -m vibetracks.roadmap.projector``: project a loop into bam-roadmap/1, validate a document, show one rung's proof.

    cd ~/vibetracks
    env -u VIRTUAL_ENV uv run --isolated python -m vibetracks.roadmap.projector project kinsim --out /tmp/kinsim.json

Exit codes: 0 valid; 1 the document is invalid (each problem printed); 2 the loop's files could not be read;
3 the document is outdated (the loop moved since it was projected, every rung's status still holds: project it again).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ...sources import load_sources
from . import model
from .files import ProjectionError
from .kinsim import project_kinsim
from .rig import project_rig
from .validate import summarize, validate, validate_document

# WHY the defaults come from vibetracks' sources map: in bam_ws this package sat beside bam_curriculum and bam_rig_loop
# and found them as siblings; moved into vibetracks it reads the same map the dashboard's live /doc reads.
SOURCES = load_sources()
DEFAULT_CURRICULUM_DIR = Path(SOURCES["kinsim_curriculum_dir"])
DEFAULT_DATA_HOME = Path(SOURCES["kinsim_home"])
DEFAULT_RIG_DIR = Path(SOURCES["rig_loop_dir"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(path: Path, document: dict) -> None:
    """Whole-file replace, so a reader never sees half a document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=1, ensure_ascii=False)
        stream.write("\n")
    os.chmod(temporary, 0o644)  # mkstemp makes 0600; a projection is meant to be read by the viewers
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m vibetracks.roadmap.projector", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    project = commands.add_parser("project", help="project a loop's own files into bam-roadmap/1 (read-only)")
    project.add_argument("loop", choices=["kinsim", "rig"])
    project.add_argument("--curriculum-dir", type=Path, default=DEFAULT_CURRICULUM_DIR,
                         help="kinsim: the bam_curriculum package (its checkout's HEAD is what the loop is judged at)")
    project.add_argument("--data-home", type=Path,
                         default=Path(os.environ.get("BAM_CURRICULUM_HOME", str(DEFAULT_DATA_HOME))).expanduser(),
                         help="kinsim: the loop's data home (default $BAM_CURRICULUM_HOME or the sources map's kinsim_home)")
    project.add_argument("--rig-dir", type=Path, default=DEFAULT_RIG_DIR, help="rig: the bam_rig_loop directory")
    project.add_argument("--head", default=None, help="judge at this commit instead of the checkout's HEAD")
    project.add_argument("--now", default=None, help="generated_at (default: now, UTC)")
    project.add_argument("--out", type=Path, default=None, help="write here (default: stdout)")

    validate = commands.add_parser("validate", help="check documents: schema, consistency, and a fresh projection of their loop")
    validate.add_argument("files", type=Path, nargs="+")
    validate.add_argument("--no-sources", action="store_true",
                          help="do not project the loop again (only the schema, the document's own consistency and its links)")
    validate.add_argument("--no-disk", action="store_true", help="with --no-sources: skip re-opening every link on disk")
    validate.add_argument("--head", default=None, help="project the loop again at this commit (default: its checkout's HEAD)")
    validate.add_argument("--details", action="store_true", help="for an outdated document, also print every detail that moved")

    show = commands.add_parser("show", help="print one rung's proof: status, done_when, evidence links")
    show.add_argument("file", type=Path)
    show.add_argument("rung")
    return parser


def command_project(args: argparse.Namespace) -> int:
    now = args.now or _now()
    try:
        if args.loop == "kinsim":
            document = project_kinsim(args.curriculum_dir, args.data_home, now=now, head=args.head)
        else:
            document = project_rig(args.rig_dir, now=now, head=args.head)
    except ProjectionError as error:
        print(f"bam_roadmap: {error}", file=sys.stderr)
        return 2
    # WHY not against its sources: this document IS the projection of its sources a moment ago; projecting a
    # second time here would only double the cost. ``validate`` does that for a document read back later.
    problems = validate_document(document, against_sources=False)
    if problems:
        # WHY refuse to write: a projection that fails its own validator would teach the UI a wrong shape.
        print(f"bam_roadmap: the projection is invalid ({len(problems)} problems); nothing written", file=sys.stderr)
        for problem in problems[:40]:
            print(f"  {problem}", file=sys.stderr)
        return 1
    if args.out is None:
        json.dump(document, sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _write(args.out, document)
        print(f"wrote {args.out} ({args.out.stat().st_size:,} bytes)", file=sys.stderr)
    print(summarize(document), file=sys.stderr)
    return 0


def command_validate(args: argparse.Namespace) -> int:
    worst = 0
    for path in args.files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            print(f"{path}: unreadable: {error}")
            worst = 1
            continue
        result = validate(document, check_disk=not args.no_disk, against_sources=not args.no_sources, head=args.head)
        if result.verdict == "invalid":
            worst = 1
            print(f"{path}: INVALID, {len(result.problems)} problem(s)")
            for problem in result.problems:
                print(f"  {problem}")
        elif result.verdict == "outdated":
            worst = worst or 3
            # WHY one line, not every detail (Codex round 3): the details of an outdated document are what moved;
            # listing sixty of them buried the one thing to do, which is to project it again.
            print(f"{path}: OUTDATED. The loop moved since it was projected ({'; '.join(result.moved)}); every rung keeps its "
                  f"status and claim, {len(result.differences)} detail(s) differ. Project it again.")
            if args.details:
                for difference in result.differences:
                    print(f"  {difference}")
        else:
            print(f"{path}: valid. {summarize(document)}")
    return worst


def command_show(args: argparse.Namespace) -> int:
    document = json.loads(args.file.read_text(encoding="utf-8"))
    rung = next((item for item in document["rungs"] if item["id"] == args.rung), None)
    if rung is None:
        print(f"no rung {args.rung} in {args.file}", file=sys.stderr)
        return 1
    evidence = {item["id"]: item for item in rung["evidence"]}
    print(f"{rung['id']} {rung['title']}: {rung['status'].upper()} (the loop says {rung['claimed_status']})")
    print(f"  {rung['status_reason']}")
    support = rung["support"]
    if support["runs"] or support["events"] or support["rungs"]:
        events = ", ".join(f"line {reference['line']} ({reference['kind']})" for reference in support["events"])
        print(f"  rests on: runs [{', '.join(support['runs'])}]; events [{events}]; rungs [{', '.join(support['rungs'])}]")
    print(f"  done_when ({rung['done_when']['rule']}): {rung['done_when']['text']}")
    for criterion in rung["criteria"]:
        how = (f"method {criterion['method']}" if criterion["method"] else
               "structural" if criterion["kind"] in model.STRUCTURAL_KINDS else "prose only, nothing typed to check")
        print(f"  - [{criterion['verdict']}{'/' + criterion['strength'] if criterion['strength'] else ''}] "
              f"{criterion['title']} ({criterion['kind']}, {how})")
        for target in criterion["targets"]:
            print(f"      {target['verdict']:7} {target['label']}: {target['note']}")
            for evidence_id in target["evidence"]:
                item = evidence[evidence_id]
                place = item["abs"] or item["path"] or "(no file)"
                # WHY "(line N)" and never "path:N": a glued suffix is what a scraper mangles (Codex A02).
                line = f" (line {item['line']})" if item["line"] else ""
                commit = f" at {item['commit'][:8]} ({item['commit_source']})" if item["commit"] else " (no commit)"
                print(f"               {evidence_id} {item['kind']} {item['result'] or '-'} [{item['strength']}] {place}{line}{commit}")
    for blocker in rung["blockers"]:
        print(f"  blocked by {blocker['id']}: {blocker['title']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"project": command_project, "validate": command_validate, "show": command_show}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
