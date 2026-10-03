"""Where the dashboard's inputs live on this machine: one small, overridable map of paths.

    from vibetracks.sources import load_sources
    load_sources()["run_media_root"]  # -> "/home/bam/bam_ws/src/core/mdp/.../traj_integration_tests/out"

``~/.local/share/vibetracks/sources.json`` (or ``$VIBETRACKS_SOURCES``) may override any key with a string path; a
missing or unreadable file means the defaults below. Every value comes back as an absolute string with ``~`` expanded.
Keys the file adds beyond the defaults are passed through (expanded the same way), so a new adapter can name its own
input without a code change here.

WHY one file outside the repo and not constants in each module: the adapter, the backend and the roadmap session all
read the same loop folders, and those folders are worktrees that move (a lane lands, a worktree is swept). One map
outside the checkout lets a move be fixed by editing a JSON line instead of patching three modules on three branches.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Mapping

SOURCES_FILE = "~/.local/share/vibetracks/sources.json"

#: The verified locations as of 2026-10-03. Paths into ``.claude/worktrees/`` are the lanes the data lives on today.
DEFAULT_SOURCES: dict[str, str] = {
    "kinsim_home": "~/.local/share/bam_curriculum",
    "kinsim_curriculum_dir": "/home/bam/bam_ws/.claude/worktrees/roadmap-curriculum-viz-8dc08a/src/dev/bam_curriculum",
    "rig_loop_dir": "/home/bam/bam_ws/.claude/worktrees/rig-loop-work-continue-cb3c52/src/dev/bam_rig_loop",
    "deployments_fixtures_dir": "/home/bam/bam_ws/.claude/worktrees/rig-loop-work-continue-cb3c52/src/dev/bam_deployments/fixtures/api-real",
    "run_media_root": "/home/bam/bam_ws/src/core/mdp/agent/actor/trajectory_generation/traj_integration_tests/out",
    "reports_media_dir": "/home/bam/bam_ws/reports/media",
    "dashboard_data_home": "~/.local/share/vibetracks/dashboard",
}


def sources_file(environ: Mapping[str, str] = os.environ) -> Path:
    return Path(environ.get("VIBETRACKS_SOURCES") or SOURCES_FILE).expanduser()


def load_sources(path: str | os.PathLike[str] | None = None, environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """The defaults, overridden by the sources file's string values; ``~`` expanded everywhere.

    A file that is not a JSON object, or a key whose value is not a non-empty string, is ignored with one line on
    stderr. WHY warn and fall back rather than raise: the backend calls this at startup, and a typo in a local
    override must not take the dashboard down; the default paths still render real data.
    """

    merged = dict(DEFAULT_SOURCES)
    file = Path(path).expanduser() if path is not None else sources_file(environ)
    try:
        raw = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        raw = None
    except OSError as error:
        print(f"[vibetracks] ignoring {file}: {error}", file=sys.stderr)
        raw = None
    if raw is not None:
        try:
            data = json.loads(raw)
        except ValueError as error:
            print(f"[vibetracks] ignoring {file}: not JSON ({error})", file=sys.stderr)
            data = {}
        if not isinstance(data, dict):
            print(f"[vibetracks] ignoring {file}: expected a JSON object", file=sys.stderr)
            data = {}
        for key, value in data.items():
            if isinstance(value, str) and value.strip():
                merged[key] = value
            else:
                print(f"[vibetracks] ignoring {file} key {key!r}: expected a non-empty string path", file=sys.stderr)
    return {key: str(Path(value).expanduser()) for key, value in merged.items()}
