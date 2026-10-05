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
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping

SOURCES_FILE = "~/.local/share/vibetracks/sources.json"

#: The work-track registry's input files (workspace/tracks/<id>.md ``vibe-sources``), from the track discovery of
#: 2026-10-04 (docs/dashboard/track-discovery-2026-10-04.json). Keys are prefixed with the track id that reads them.
#: A value may start with ``{other_key}``, which expands to that key's value, so moving a loop folder is one line.
#: WHY declared here once, ahead of the adapters: five adapter lanes build in parallel next, and a shared map they all
#: append to is a write collision; with the keys in place each lane edits only its own adapter and track note.
WORKTRACK_SOURCES: dict[str, str] = {
    "kinsim_status": "{kinsim_home}/status.json",
    "kinsim_events": "{kinsim_home}/loop_events.jsonl",
    "kinsim_runs": "{kinsim_home}/runs.jsonl",
    "kinsim_loop_dir": "{kinsim_curriculum_dir}",
    "rig_loop_status": "{rig_loop_dir}/loop-status.json",
    "rig_events": "{rig_loop_dir}/loop_events.jsonl",
    "rig_ladder": "{rig_loop_dir}/ladder.json",
    "grasping_bench_dir": "/home/bam/bam_ws/.claude/worktrees/grasping-agent-roadmap-ab12d8/src/core/mdp/agent/actor/policy/grasp_bench",
    "grasping_ledger": "{grasping_bench_dir}/out/ledger/runs.jsonl",
    "grasping_curriculum": "{grasping_bench_dir}/src/grasp_bench/curriculum.py",
    "detection_repo": "/home/bam/spectralwaste-segmentation",
    "detection_queue_log": "{detection_repo}/logs/queue.log",
    "detection_ladder": "/home/bam/bam_ws/.claude/worktrees/hyperspectral-synthetic-data-ddb809/docs/hyperspectral/ladder_data.py",
    "pyblocks_repo": "/home/bam/pyblocks",
    "pyblocks_board_dir": "{pyblocks_repo}/reports/media/board",
    "pyblocks_windows": "{pyblocks_repo}/reports/media/board/windows.jsonl",
    # Names agreed with the roadmap session (its grasping/detection projectors read these); aliases of the above.
    "grasp_bench_dir": "{grasping_bench_dir}",
    "detection_dir": "/home/bam/bam_ws/.claude/worktrees/hyperspectral-synthetic-data-ddb809/docs/hyperspectral",
}
_REFERENCE = re.compile(r"^\{(?P<key>[a-z0-9_]+)\}")

#: The verified locations as of 2026-10-03. Paths into ``.claude/worktrees/`` are the lanes the data lives on today.
DEFAULT_SOURCES: dict[str, str] = {
    "kinsim_home": "~/.local/share/bam_curriculum",
    # WHY resolved from git, not a fixed path: the kinsim loop's checkout is whichever worktree holds its branch, and
    # that worktree moves (cc14d6 -> 5a3df8 -> wave-3-handoff-af2b9b in three days). The old default pointed at the
    # roadmap lane, whose history lacks the loop's newest readings, so every live kinsim status read wrong-stale.
    "kinsim_curriculum_dir": "@worktree:/home/bam/bam_ws:claude/kinematic-simulator-waste-sorting-cc14d6:src/dev/bam_curriculum"
                             "|/home/bam/bam_ws/.claude/worktrees/wave-3-handoff-af2b9b/src/dev/bam_curriculum",
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

    merged = {**WORKTRACK_SOURCES, **DEFAULT_SOURCES}
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
    merged = {key: _resolve_worktree(value) for key, value in merged.items()}
    return {key: str(Path(_expand_reference(key, value, merged)).expanduser()) for key, value in merged.items()}


_WORKTREE = re.compile(r"^@worktree:(?P<repo>[^:]+):(?P<branch>[^:]+):(?P<sub>[^|]*)\|(?P<fallback>.+)$")
_WORKTREE_CACHE: dict[tuple[str, str], tuple[float, str | None]] = {}
_WORKTREE_TTL_S = 60.0


def _resolve_worktree(value: str) -> str:
    """``@worktree:<repo>:<branch>:<subdir>|<fallback>`` -> the checkout of ``branch`` + subdir, else the fallback.

    Reads ``git worktree list --porcelain`` (cached 60 s, since the backend reloads per request). WHY a fallback and
    not an error: git missing or the branch momentarily unchecked-out must not blank the dashboard.
    """

    match = _WORKTREE.match(value)
    if not match:
        return value
    repo, branch, sub, fallback = match.group("repo", "branch", "sub", "fallback")
    now = time.monotonic()
    cached = _WORKTREE_CACHE.get((repo, branch))
    if cached is None or now - cached[0] > _WORKTREE_TTL_S:
        cached = (now, _worktree_of(repo, branch))
        _WORKTREE_CACHE[(repo, branch)] = cached
    root = cached[1]
    return str(Path(root) / sub) if root else fallback


def _worktree_of(repo: str, branch: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", repo, "worktree", "list", "--porcelain"], capture_output=True, text=True,
                             timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}" and path:
            return path
    return None


def _expand_reference(key: str, value: str, merged: Mapping[str, str]) -> str:
    """``{other}/rest`` -> ``<other's value>/rest``, one level deep; an unknown or self reference stays verbatim."""

    match = _REFERENCE.match(value)
    if not match or match.group("key") == key or match.group("key") not in merged:
        return value
    base = merged[match.group("key")]
    if _REFERENCE.match(base):
        return value  # WHY one level only: a chain (or a cycle) of references is a typo, and verbatim says so
    return base + value[match.end():]
