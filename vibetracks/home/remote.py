"""Other machines on the home (r3, 2026-10-09; Zach: "so I can start like using this across machines").

The remote layer (docs/remote/DESIGN.md) already publishes every worker machine into the share, one folder per host:
``hosts/<host>/host.json`` (the heartbeat: ``last_sync``), ``hosts/<host>/sessions/<id>.json`` (session cards the
Claude Code hook writes: account, cwd, track, Remote Control link, last hook event; title and branch since r3) and
``hosts/<host>/sources.json`` + ``files/`` (mirrored loop files). This module reads them for the home:

    view = read_share(share, now, own=this_host_names())
    merged = merged_sources(share, own)          # this machine's sources map, with other machines' keys on top

Read-only. The hub is what pulls the share (``vibetracks.remote.hub``); here the clone is read as it is on disk, and
every reading says how old it is.

WHY "current as of", never "live" (docs/peps/0003): a session on another machine has no pid this machine can check,
so the home never calls it live. Its card is ``current`` as of its host's last report: ``as_of`` is the newer of the
host's ``last_sync`` and the card's ``last_seen``; it counts while the host still reports (online or stale per
``hub.host_status``, not offline), the card is not ended, and its last hook event is at most ``SESSION_LIVE_S``
(30 min, the hub's rule for a live card) older than ``as_of``. The page prints "as of 3 min ago" beside it.

WHY skip this machine's own folder: when this machine also runs the worker, its cards and mirrors are copies of what
the home already reads from its own files (and fresher there); a local session id always wins over any card.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..remote import share as layout
from ..remote.hub import SESSION_LIVE_S, host_status, merge_sources

#: Cards whose last hook event is older than this are not read at all (the home's transcript window).
WINDOW_S = 7 * 86400
SHARE_DIR = "vibetracks-share"
OFF = {"", "0", "off", "none", "false", "no"}


# ------------------------------------------------------------------------------------------------ where, and who am I


def default_share(environ: Mapping[str, str] = os.environ, home: Path | None = None) -> Path | None:
    """``$VIBETRACKS_SHARE`` (``off`` disables), else ``~/vibetracks-share`` when it is a share clone; else None."""

    value = environ.get("VIBETRACKS_SHARE")
    if value is not None:
        return None if value.strip().lower() in OFF else Path(value).expanduser()
    candidate = (home or Path.home()) / SHARE_DIR
    return candidate if (candidate / layout.HOSTS).is_dir() or (candidate / ".git").exists() else None


def this_host_names(environ: Mapping[str, str] = os.environ, home: Path | None = None) -> set[str]:
    """Every name this machine may publish under, lower-cased: its hostname, the ``host`` of its worker config
    (``~/.vibetracks/remote.json``, ``sync.json``) and ``$VIBETRACKS_HOST``."""

    names = {socket.gethostname().lower()}
    base = (home or Path.home()) / ".vibetracks"
    for name in ("remote.json", "sync.json"):
        data = layout.read_json(base / name)
        if isinstance(data, dict) and isinstance(data.get("host"), str) and data["host"].strip():
            names.add(data["host"].strip().lower())
    if environ.get("VIBETRACKS_HOST", "").strip():
        names.add(environ["VIBETRACKS_HOST"].strip().lower())
    return names


def merged_sources(share: str | os.PathLike[str], own: Iterable[str], base: Mapping[str, str] | None = None) -> dict[str, str]:
    """This machine's sources map (``vibetracks.sources.load_sources``) with every key another machine supplies
    pointed at its copy in the share (the hub's rule: a key the share supplies wins). This machine's own folder never
    overrides its own files."""

    if base is None:
        from ..sources import load_sources  # noqa: PLC0415

        base = load_sources()
    paths, _ = merge_sources(share, exclude={name.lower() for name in own})
    return {**dict(base), **paths}


# ------------------------------------------------------------------------------------------------ reading the share


@dataclass
class Card:
    """One session card from another machine, judged against its host's last report."""

    host: str
    data: dict[str, Any]
    path: str
    last_seen: float | None
    as_of: float | None
    host_status: str
    host_last_sync: float | None
    ended: bool
    current: bool

    @property
    def session(self) -> str:
        return str(self.data.get("session_id"))

    def text(self, key: str) -> str | None:
        value = self.data.get(key)
        return value if isinstance(value, str) and value.strip() else None

    @property
    def word(self) -> str:
        """The session's state word, Claude's meanings: a prompt with no Stop since is working; anything not current
        is reported but not vouched for, so it reads idle (its as-of age says how old)."""

        if self.ended:
            return "ended"
        if self.current and self.data.get("event") == "UserPromptSubmit":
            return "working"
        return "idle"


def _number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def read_share(share: str | os.PathLike[str], now: float, own: Iterable[str]) -> dict[str, Any]:
    """``{"hosts": [row], "cards": [Card], "owners": {source key: host}, "problems": [...]}`` for every host folder
    except this machine's own."""

    own = {name.lower() for name in own}
    hosts: list[dict[str, Any]] = []
    cards: list[Card] = []
    problems: list[dict[str, Any]] = []
    for folder in layout.host_dirs(share):
        name = folder.name
        if name.lower() in own:
            continue
        beat = layout.read_json(folder / layout.HOST_JSON)
        if not isinstance(beat, dict):
            if (folder / layout.HOST_JSON).exists():
                problems.append({"path": f"hosts/{name}/host.json", "error": "not a JSON object"})
            beat = {}
        last_sync = layout.parse_iso(beat.get("last_sync"))
        status = host_status(last_sync, _number(beat.get("interval_s"), 3.0), now, _number(beat.get("heartbeat_s"), 0.0))
        mine: list[Card] = []
        try:
            files = sorted((folder / layout.SESSIONS).glob("*.json"))
        except OSError:
            files = []
        for file in files:
            data = layout.read_json(file)
            if not isinstance(data, dict) or not isinstance(data.get("session_id"), str) or not layout.NAME.match(data["session_id"]):
                continue
            seen = layout.parse_iso(data.get("last_seen"))
            if seen is not None and now - seen > WINDOW_S:
                continue
            ended = data.get("ended") is True or data.get("event") == "SessionEnd"
            stamps = [t for t in (last_sync, seen) if t is not None]
            as_of = max(stamps) if stamps else None
            current = (not ended and status in ("online", "stale") and seen is not None and as_of is not None
                       and as_of - seen <= SESSION_LIVE_S)
            mine.append(Card(host=name, data=data, path=f"{layout.HOSTS}/{name}/{layout.SESSIONS}/{file.name}",
                             last_seen=seen, as_of=as_of, host_status=status, host_last_sync=last_sync, ended=ended,
                             current=current))
        cards += mine
        hosts.append({"host": name, "status": status, "last_sync": beat.get("last_sync") if last_sync is not None else None,
                      "age_s": None if last_sync is None else max(0, int(now - last_sync)), "platform": beat.get("platform"),
                      "error": beat.get("error"), "sessions_current": sum(1 for c in mine if c.current),
                      "sessions_seen": len(mine)})
    from ..remote.hub import _merge  # noqa: PLC0415 - the hub's own manifest reader, so both agree on every key

    _, owners, merge_problems = _merge(share, exclude=own)
    problems += [{"path": "share", "error": json.dumps(p, sort_keys=True)} for p in merge_problems]
    return {"hosts": hosts, "cards": cards, "owners": owners, "problems": problems}
