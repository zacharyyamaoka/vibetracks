"""Session cards in the Vibe Tracks vault: Claude Code's hook writes them, the home reads them.

    python -I <repo>/vibetracks/remote/card.py < event.json        (the plugin's hook; see hooks/hooks.json)

The share is an Obsidian vault of its own that Obsidian Sync carries between machines (docs/remote/DESIGN.md). It is
found, never configured: ``$VIBETRACKS_SHARE`` (``off`` disables), else the vault in Obsidian's own registry
(``obsidian.json``) whose root holds ``vibetracks-share.md``. A machine without that vault gets no card and no error.

A card is ``hosts/<host>/sessions/<session_id>.md``: a note whose properties are the card's fields (every value a JSON
scalar, which is also YAML) and whose body links the session's Remote Control page. The host is ``$VIBETRACKS_HOST``,
else this machine's entry in the marker note's ``machines`` property (``desktop-ab12cd3: win-a``), else the
lower-case hostname.

WHY stdlib only and no package imports: the hook runs this file by path from the plugin's copy of the repo, on whatever
python the machine has, so it cannot rely on a venv, PyYAML or ``vibetracks`` being importable. The home imports the
same file (``vibetracks.remote.card``), so the writer and the reader share one format.

WHY .md and not .json: Obsidian Sync carries notes and media by default and other file types only when a device opts
in, so a note syncs on every machine with no setting to remember; it also reads as a note in the vault.

WHY it never fails: a hook that exits nonzero (or raises) shows an error in the agent's session on every prompt; a
missing card only costs the home one row. Problems go to stderr as one line, stdout stays empty (a UserPromptSubmit
hook's stdout would land in the prompt).
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

MARKER = "vibetracks-share.md"
HOSTS = "hosts"
SESSIONS = "sessions"
CARD_SUFFIX = ".md"
URL_PREFIX = "https://claude.ai/code/"
TRANSCRIPT_TAIL_BYTES = 256 * 1024
#: A card is rewritten at most this often while its event and fields stay the same. WHY: every prompt and stop would
#: otherwise be a new version in Obsidian Sync's history; the home only needs last_seen to the half minute.
REWRITE_EVERY_S = 30.0
OFF = {"", "0", "off", "none", "false", "no"}
#: A host or session name that is safe as one path segment on every OS (no separators, no leading dot).
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
#: The card's properties, in the order they are written.
FIELDS = ("session_id", "host", "account", "agent", "model", "cwd", "title", "branch", "track", "url", "event",
          "started_at", "last_seen", "ended")


def _note(message: str) -> None:
    print(f"[vibetracks card] {message}", file=sys.stderr)


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


# ------------------------------------------------------------------------------------------------ finding the vault


def obsidian_registries(environ: Mapping[str, str], home: Path) -> list[Path]:
    """Where Obsidian keeps its vault list on Windows, macOS and Linux (native, Flatpak, Snap)."""

    paths = []
    if environ.get("APPDATA"):
        paths.append(Path(environ["APPDATA"]) / "obsidian" / "obsidian.json")
    paths.append(home / "AppData" / "Roaming" / "obsidian" / "obsidian.json")
    paths.append(home / "Library" / "Application Support" / "obsidian" / "obsidian.json")
    paths.append(Path(environ.get("XDG_CONFIG_HOME") or home / ".config") / "obsidian" / "obsidian.json")
    paths.append(home / ".var" / "app" / "md.obsidian.Obsidian" / "config" / "obsidian" / "obsidian.json")
    paths.append(home / "snap" / "obsidian" / "current" / ".config" / "obsidian" / "obsidian.json")
    unique: list[Path] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return unique


def registered_vaults(environ: Mapping[str, str], home: Path) -> list[Path]:
    vaults: list[Path] = []
    for registry in obsidian_registries(environ, home):
        try:
            data = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = data.get("vaults") if isinstance(data, dict) else None
        for entry in (entries.values() if isinstance(entries, dict) else []):
            path = entry.get("path") if isinstance(entry, dict) else None
            if isinstance(path, str) and path and Path(path) not in vaults:
                vaults.append(Path(path))
    return vaults


def find_share(environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path | None:
    """``$VIBETRACKS_SHARE``, else the registered Obsidian vault whose root holds the marker note, else None."""

    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    value = environ.get("VIBETRACKS_SHARE")
    if value is not None:
        return None if value.strip().lower() in OFF else Path(value).expanduser()
    for vault in registered_vaults(environ, home):
        if (vault / MARKER).is_file():
            return vault
    return None


# ------------------------------------------------------------------------------------------------ the note format


def _scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def parse_properties(text: str) -> dict[str, Any]:
    """The note's frontmatter as a dict: ``key: scalar`` lines and one level of ``key:`` + indented ``k: v`` mappings,
    which covers both what ``render_card`` writes and what Obsidian's property editor writes back."""

    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    properties: dict[str, Any] = {}
    open_key: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return properties
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, rest = line.strip().partition(":")
        if not sep:
            continue
        if line[:1] in (" ", "\t") and open_key is not None:
            nested = key.strip()
            properties[open_key][_scalar(nested) if nested[:1] in ('"', "'") else nested] = _scalar(rest)
            continue
        key = key.strip()
        if rest.strip():
            properties[key], open_key = _scalar(rest), None
        else:
            properties[key], open_key = {}, key
    return {}  # no closing ---: not frontmatter


def read_note_properties(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            return parse_properties(handle.read(64 * 1024))
    except (OSError, UnicodeDecodeError):
        return {}


def read_card(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """A card's fields, or None when the file is not a card (missing, mid-sync, or no usable session_id)."""

    data = read_note_properties(path)
    session = data.get("session_id")
    return data if isinstance(session, str) and NAME.match(session) else None


def render_card(card: Mapping[str, Any]) -> str:
    lines = ["---"] + [f"{key}: {json.dumps(card.get(key), ensure_ascii=False)}" for key in FIELDS] + ["---", ""]
    title = card.get("title") or f"Session {str(card.get('session_id'))[:8]}"
    lines.append(f"# {title}")
    lines.append("")
    url = card.get("url")
    lines.append(f"[Talk to this agent]({url})" if url else "No Remote Control link: Remote Control is off here.")
    lines.append("")
    return "\n".join(lines)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # WHY a .tmp name: it is not a note, so Obsidian Sync never uploads the half-written file.
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------------------------------------ who and where


def host_name(share: Path | None, environ: Mapping[str, str] | None = None, hostname: str | None = None) -> str:
    """``$VIBETRACKS_HOST``, else this machine's entry in the marker note's ``machines``, else the hostname; always a
    valid path segment."""

    environ = os.environ if environ is None else environ
    hostname = (hostname or socket.gethostname()).strip().lower()
    chosen = environ.get("VIBETRACKS_HOST", "").strip()
    if not chosen and share is not None:
        machines = read_note_properties(share / MARKER).get("machines")
        if isinstance(machines, dict):
            for key, value in machines.items():
                if str(key).strip().lower() == hostname and isinstance(value, str) and value.strip():
                    chosen = value.strip()
                    break
    chosen = re.sub(r"[^A-Za-z0-9._-]+", "-", chosen or hostname).strip("-.") or "host"
    return chosen if NAME.match(chosen) else f"h-{chosen}"


def card_path(share: Path, host: str, session_id: str) -> Path:
    return share / HOSTS / host / SESSIONS / f"{session_id}{CARD_SUFFIX}"


def account_of(config_dir: str | None) -> str | None:
    if not config_dir:
        return None
    name = Path(config_dir.rstrip("/\\")).name
    for prefix in (".claude-", "claude-"):
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix):]
    return name.lstrip(".") or None


def _tail_lines(transcript_path: str | None) -> list[bytes]:
    if not transcript_path:
        return []
    try:
        with open(transcript_path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TRANSCRIPT_TAIL_BYTES))
            tail = handle.read()
    except OSError:
        return []
    lines = tail.split(b"\n")
    return lines[1:] if size > TRANSCRIPT_TAIL_BYTES else lines  # the first line of a mid-file read is torn


def title_and_branch(transcript_path: str | None) -> tuple[str | None, str | None]:
    """(newest custom-title, else newest agent-name; gitBranch of the newest line carrying one) from the tail."""

    title = agent_name = branch = None
    for raw in reversed(_tail_lines(transcript_path)):
        if b'"custom-title"' not in raw and b'"agent-name"' not in raw and b'"gitBranch"' not in raw:
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if title is None and row.get("type") == "custom-title" and isinstance(row.get("customTitle"), str) and row["customTitle"].strip():
            title = row["customTitle"].strip()
        if agent_name is None and row.get("type") == "agent-name" and isinstance(row.get("agentName"), str) and row["agentName"].strip():
            agent_name = row["agentName"].strip()
        if branch is None and isinstance(row.get("gitBranch"), str) and row["gitBranch"]:
            branch = row["gitBranch"]
        if title is not None and branch is not None:
            break
    return title or agent_name, branch


def model_of(transcript_path: str | None) -> str | None:
    """``message.model`` of the last assistant line in the transcript's tail, or None."""

    for raw in reversed(_tail_lines(transcript_path)):
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


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expanduser(path)))


def track_of(cwd: str | None, track: str | None, tracks_map: Mapping[str, Iterable[str]]) -> str | None:
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


# ------------------------------------------------------------------------------------------------ the hook


def build_card(event: Mapping[str, Any], existing: Mapping[str, Any], host: str, environ: Mapping[str, str],
               now: float) -> dict[str, Any]:
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    transcript = event.get("transcript_path") if isinstance(event.get("transcript_path"), str) else None
    title, branch = title_and_branch(transcript)
    bridge = environ.get("CLAUDE_CODE_BRIDGE_SESSION_ID")
    hook_event = event.get("hook_event_name")
    return {
        "session_id": event["session_id"],
        "host": host,
        "account": account_of(environ.get("CLAUDE_CONFIG_DIR")),
        "agent": environ.get("AI_AGENT") or "claude-code",
        "model": model_of(transcript) or existing.get("model"),
        "cwd": cwd,
        "title": title or existing.get("title"),
        "branch": branch or existing.get("branch"),
        "track": track_of(cwd, environ.get("VIBETRACKS_TRACK"), {}) or existing.get("track"),
        "url": f"{URL_PREFIX}{bridge}" if bridge else existing.get("url"),
        "event": hook_event if isinstance(hook_event, str) else None,
        "started_at": existing.get("started_at") or iso_utc(now),
        "last_seen": iso_utc(now),
        "ended": hook_event == "SessionEnd",
    }


def record(event: Any, environ: Mapping[str, str], home: Path | None = None, now: float | None = None,
           hostname: str | None = None) -> Path | None:
    """Write (or refresh) this session's card; the path written, or None when nothing was written."""

    now = time.time() if now is None else now
    session_id = event.get("session_id") if isinstance(event, dict) else None
    if not isinstance(session_id, str) or not NAME.match(session_id):
        _note("no usable session_id on stdin; no card written")
        return None
    share = find_share(environ, home)
    if share is None or not share.is_dir():
        return None  # WHY silent: a machine without the Vibe Tracks vault is not a worker, and that is fine
    host = host_name(share, environ, hostname)
    path = card_path(share, host, session_id)
    existing = read_card(path) or {}
    card = build_card(event, existing, host, environ, now)
    seen = parse_iso(existing.get("last_seen"))
    same = all(card.get(key) == existing.get(key) for key in FIELDS if key != "last_seen")
    if same and seen is not None and 0 <= now - seen < REWRITE_EVERY_S:
        return None
    write_atomic(path, render_card(card))
    return path


def main(stdin_text: str, environ: Mapping[str, str]) -> int:
    try:
        event = json.loads(stdin_text)
    except (TypeError, ValueError):
        _note("stdin is not JSON; no card written")
        return 0
    try:
        record(event, environ)
    except Exception as error:  # WHY catch-all: see the module docstring, a hook must never fail its session
        _note(f"no card written: {type(error).__name__}: {error}")
    return 0


if __name__ == "__main__":
    # WHY bytes: Windows' console encoding is not UTF-8, and Claude Code writes the event as UTF-8.
    sys.exit(main(sys.stdin.buffer.read().decode("utf-8", "replace"), os.environ))
