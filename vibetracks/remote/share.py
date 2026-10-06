"""The share: one git repo every machine clones, and the layout inside it.

    hosts/<host>/host.json                   heartbeat: {host, platform, python, vt_sync_version, last_sync, interval_s,
                                             mirrors: [{key, path, bytes, mtime}], skipped: [{key, path, reason}], error}
    hosts/<host>/sources.json                {source_key: path relative to hosts/<host>/}
    hosts/<host>/files/<source_key>/<name>   mirrored copies (a mirrored directory lands at files/<key>/ with its tree)
    hosts/<host>/sessions/<session_id>.json  session cards (session_hook.py)

One writer per host folder: a machine only ever stages ``hosts/<host>/``. WHY: two machines never edit the same path,
so every pull is a fast-forward or a trivial rebase, and a conflict means something wrote where it must not.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOSTS = "hosts"
HOST_JSON = "host.json"
SOURCES_JSON = "sources.json"
FILES = "files"
SESSIONS = "sessions"
VT_SYNC_VERSION = 1

#: A host or source-key name that is safe as one path segment on every OS (no separators, no leading dot).
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def host_dir(share: str | os.PathLike[str], host: str) -> Path:
    if not NAME.match(host):
        raise ValueError(f"host name {host!r} must match {NAME.pattern}")
    return Path(share) / HOSTS / host


def host_dirs(share: str | os.PathLike[str]) -> list[Path]:
    """Every ``hosts/<host>/`` folder in the share, sorted by name; names that are not valid hosts are skipped."""

    root = Path(share) / HOSTS
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return []
    return [entry for entry in entries if entry.is_dir() and NAME.match(entry.name)]


def iso_utc(when: float) -> str:
    return datetime.fromtimestamp(when, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(text: Any) -> float | None:
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def read_json(path: str | os.PathLike[str]) -> Any:
    """The parsed file, or None when it is missing, unreadable or not JSON (a peer may be mid-write)."""

    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def write_json_atomic(path: str | os.PathLike[str], payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json_if_changed(path: str | os.PathLike[str], payload: Any) -> bool:
    """Write only when the content differs, so an unchanged manifest never shows up in ``git status``."""

    if read_json(path) == json.loads(json.dumps(payload)):
        return False
    write_json_atomic(path, payload)
    return True
