"""Reading the loops' files: JSON, JSONL and file digests. Read-only, stdlib only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ProjectionError(RuntimeError):
    """The loop's own files are missing or unreadable, so nothing honest can be projected."""


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ProjectionError(f"cannot read {path}: {error}") from error


LINE_KEY = "_line"


def read_jsonl(path: Path, *, numbered: bool = False) -> list[dict]:
    """Rows of a JSONL file; a line that is not a JSON object (a crash fragment) is skipped, as the loops' readers do.

    ``numbered`` stamps each row with its physical 1-based line under ``_line``: an append-only
    log has no ids, and its line number is the one name for a row that never changes.
    WHY split on "\\n" only: the loops write one row per "\\n"; str.splitlines would also split
    inside a row at U+2028 (the bug the kinsim loop's own reader had, audit B, wave 3).
    """

    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            if numbered:
                row[LINE_KEY] = number
            rows.append(row)
    return rows


def read_json_quiet(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def canonical_sha256(payload: Any) -> str:
    """bam_eval's rule (log_v2.canonical_json): sorted keys, compact separators, UTF-8, no NaN."""

    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
