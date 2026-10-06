"""Claude Code command hook: record this session as a card in the share, so the hub can offer "talk to this agent".

    python3 -m vibetracks.remote.session_hook --share <clone> --host <host> [--track <id>] [--tracks-map <json>]

Claude Code passes the hook event on stdin (``session_id``, ``cwd``, ``hook_event_name``, ``transcript_path``). The
card is ``hosts/<host>/sessions/<session_id>.json``; sync.py commits it with the rest of the host folder.

- ``url``: ``https://claude.ai/code/<CLAUDE_CODE_BRIDGE_SESSION_ID>``, which exists only while Remote Control is on
  for the session (``remoteControlAtStartup``); otherwise null.
- ``account``: ``CLAUDE_CONFIG_DIR``'s folder name without ``.claude-`` (``~/.claude-bam`` -> ``bam``).
- ``model``: ``message.model`` of the transcript's last assistant line (only the last 256 KB are read).
- ``track``: ``--track``, else the first ``--tracks-map`` entry ``{track_id: [cwd prefixes]}`` that matches ``cwd``.
  ``--tracks-map`` is the JSON itself or a path to a JSON file.

WHY it never fails: a hook that exits nonzero (or raises) shows an error in the agent's session on every prompt; a
missing card only costs the hub one row. Problems go to stderr as one line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from . import share as layout

TRANSCRIPT_TAIL_BYTES = 256 * 1024
URL_PREFIX = "https://claude.ai/code/"


def _note(message: str) -> None:
    print(f"[vibetracks session_hook] {message}", file=sys.stderr)


def account_of(config_dir: str | None) -> str | None:
    if not config_dir:
        return None
    name = Path(config_dir.rstrip("/\\")).name
    for prefix in (".claude-", "claude-"):
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix):]
    return name.lstrip(".") or None


def model_of(transcript_path: str | None) -> str | None:
    """``message.model`` of the last assistant line in the transcript's tail, or None."""

    if not transcript_path:
        return None
    try:
        with open(transcript_path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TRANSCRIPT_TAIL_BYTES))
            tail = handle.read()
    except OSError:
        return None
    lines = tail.split(b"\n")
    if size > TRANSCRIPT_TAIL_BYTES:
        lines = lines[1:]  # the first line of a mid-file read is torn
    for raw in reversed(lines):
        if b'"assistant"' not in raw:
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row, dict) and row.get("type") == "assistant" else None
        model = message.get("model") if isinstance(message, dict) else None
        # WHY skip "<synthetic>": Claude Code writes that for messages it made itself (an API error, an interrupt).
        if isinstance(model, str) and model and not model.startswith("<"):
            return model
    return None


def _tracks_map(value: str | None) -> dict[str, list[str]]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except ValueError:
        try:
            data = json.loads(Path(value).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            _note(f"ignoring --tracks-map: {error}")
            return {}
    if not isinstance(data, dict):
        _note("ignoring --tracks-map: expected {track_id: [cwd prefixes]}")
        return {}
    return {str(track): [p for p in (prefixes if isinstance(prefixes, list) else [prefixes]) if isinstance(p, str)]
            for track, prefixes in data.items()}


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expanduser(path)))


def track_of(cwd: str | None, track: str | None, tracks_map: dict[str, list[str]]) -> str | None:
    if track:
        return track
    if not cwd:
        return None
    here = _norm(cwd)
    for track_id, prefixes in tracks_map.items():
        for prefix in prefixes:
            root = _norm(prefix)
            if here == root or here.startswith(root.rstrip(os.sep) + os.sep):
                return track_id
    return None


def main(argv: list[str] | None, stdin_text: str, environ: Mapping[str, str]) -> int:
    parser = argparse.ArgumentParser(prog="vibetracks.remote.session_hook", add_help=True)
    parser.add_argument("--share", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--track")
    parser.add_argument("--tracks-map")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 0
    try:
        event = json.loads(stdin_text)
    except (TypeError, ValueError):
        _note("stdin is not JSON; no card written")
        return 0
    session_id = event.get("session_id") if isinstance(event, dict) else None
    if not isinstance(session_id, str) or not layout.NAME.match(session_id):
        _note("no usable session_id on stdin; no card written")
        return 0
    try:
        folder = layout.host_dir(args.share, args.host) / layout.SESSIONS
        path = folder / f"{session_id}.json"
        existing = layout.read_json(path)
        existing = existing if isinstance(existing, dict) else {}
        now = layout.iso_utc(time.time())
        bridge = environ.get("CLAUDE_CODE_BRIDGE_SESSION_ID")
        hook_event = event.get("hook_event_name")
        cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
        card: dict[str, Any] = {
            "session_id": session_id,
            "host": args.host,
            "account": account_of(environ.get("CLAUDE_CONFIG_DIR")),
            "agent": environ.get("AI_AGENT") or "claude-code",
            "model": model_of(event.get("transcript_path") if isinstance(event.get("transcript_path"), str) else None),
            "cwd": cwd,
            "track": track_of(cwd, args.track, _tracks_map(args.tracks_map)),
            "url": f"{URL_PREFIX}{bridge}" if bridge else None,
            "event": hook_event if isinstance(hook_event, str) else None,
            "started_at": existing.get("started_at") or now,
            "last_seen": now,
            "ended": hook_event == "SessionEnd",
        }
        layout.write_json_atomic(path, card)
    except Exception as error:  # WHY catch-all: see the module docstring, a hook must never fail its session
        _note(f"no card written: {type(error).__name__}: {error}")
    return 0


if __name__ == "__main__":
    # WHY bytes: Windows' console encoding is not UTF-8, and Claude Code writes the event as UTF-8.
    sys.exit(main(sys.argv[1:], sys.stdin.buffer.read().decode("utf-8", "replace"), os.environ))
