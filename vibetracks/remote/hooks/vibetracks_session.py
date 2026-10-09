#!/usr/bin/env python3
"""Claude Code hook wrapper for a settings.json that several machines share (stdlib only, imports nothing of ours).

settings.json runs it through one line, the same on every machine, by way of a per-machine launcher
``~/.vibetracks/hook`` (``exec "<python>" "<this file>"``) that ``python -m vibetracks.remote.sync hook-config`` writes::

    [ ! -x "$HOME/.vibetracks/hook" ] || exec "$HOME/.vibetracks/hook"

``~/.vibetracks/remote.json`` is machine-local, written by ``hook-config``::

    {"python": "<the interpreter that has vibetracks installed>", "share": "<clone>", "host": "win-a",
     "tracks_map": null | {track_id: [cwd prefixes]} | "<path to such a JSON file>"}

With it, this runs ``<python> -m vibetracks.remote.session_hook --share <share> --host <host> [--tracks-map ...]``,
passing the hook's stdin and environment through (so ``CLAUDE_CODE_BRIDGE_SESSION_ID`` arrives), with a 5 s timeout.
Without it, or when it is unreadable, it does nothing.

WHY a wrapper and not the module itself in settings.json: the file is identical on every machine (a symlink into the
vault), so it cannot name one machine's python, share or host; those live in remote.json, and a machine without one
skips the hook entirely. WHY it always exits 0: a failing hook shows an error in the agent's session on every prompt.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TIMEOUT_S = 5.0


def main() -> int:
    try:
        config = json.loads((Path.home() / ".vibetracks" / "remote.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(config, dict):
        return 0
    python, share, host = config.get("python"), config.get("share"), config.get("host")
    if not all(isinstance(value, str) and value for value in (python, share, host)):
        return 0
    command = [python, "-m", "vibetracks.remote.session_hook", "--share", share, "--host", host]
    tracks_map = config.get("tracks_map")
    if isinstance(tracks_map, dict):
        command += ["--tracks-map", json.dumps(tracks_map)]
    elif isinstance(tracks_map, str) and tracks_map:
        command += ["--tracks-map", tracks_map]
    try:
        event = sys.stdin.buffer.read() if sys.stdin is not None else b""
    except (OSError, ValueError):
        event = b""
    try:
        # WHY stdout to DEVNULL: a UserPromptSubmit hook's stdout is added to the agent's prompt.
        subprocess.run(command, input=event, stdout=subprocess.DEVNULL, timeout=TIMEOUT_S, env=os.environ.copy())
    except (OSError, subprocess.SubprocessError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
