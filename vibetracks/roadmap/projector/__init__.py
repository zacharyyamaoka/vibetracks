"""bam-roadmap/1: one roadmap + proof-of-done format for every BAM agent loop.

A loop's roadmap (axes, rungs, dependency edges) and, for every rung, ``done_when``: typed
criteria (test, gate_run, audit, inspection, demonstration, package, prerequisites, alias),
each resolved to evidence links that open (a test's file:line, a JUnit record, a ledger run,
an audit's verdict line), and a status *derived* from that evidence. It is a projection of
files the loops already write; nothing here writes to a loop.

Moved from bam_ws ``src/dev/bam_roadmap`` @ 553a66f0 (module names, behaviour, WHY comments and Codex ids unchanged).
``vibetracks.roadmap.api`` projects ``/doc`` live with ``project_kinsim`` and ``project_rig``.

    cd ~/vibetracks
    env -u VIRTUAL_ENV uv run --isolated python -m vibetracks.roadmap.projector --help
"""

from .files import ProjectionError
from .kinsim import project_kinsim
from .model import SCHEMA_ID, derive_status
from .rig import project_rig

__all__ = ["SCHEMA_ID", "ProjectionError", "derive_status", "project_kinsim", "project_rig"]
