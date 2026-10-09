"""The hub: check the share, build the real dashboard projection over it, serve a phone-first web app.

    python3 -m vibetracks.remote.hub --share <clone> --workspace <dir> --data-home <dir> [--port 4470]
        [--bind 127.0.0.1] [--allow-host NAME ...] [--host-name NAME] [--check-fast 5] [--check-slow 60]
        [--fast-window 120] [--pull-interval X] [--rebuild-interval 300]

A background thread checks the share: one ``git ls-remote`` compared with the local remote-tracking ref, and only when
they differ a pull (``sync.pull_and_restore``, which carries each worker's write time over as the file's mtime) and a
rebuild. Checks run every ``--check-fast`` seconds for ``--fast-window`` seconds after any change, Refresh or poke,
otherwise every ``--check-slow`` seconds (``--pull-interval X`` sets both to X). WHY adaptive: workers poke after each
push, so the checks are only the safety net, and a quiet share then costs one small request a minute. On every fast
tick the hub also stats this machine's own source files (the projection's freshness sources outside the share) and
rebuilds when one changed, plus a safety rebuild every ``--rebuild-interval`` seconds.

A rebuild writes ``<data-home>/remote-sources.json`` (this machine's sources, then every key the share supplies,
pointed into ``hosts/<host>/files/``) and runs the ordinary ``vibetracks.dashboard.build`` with
``$VIBETRACKS_SOURCES`` naming it. WHY a subprocess: ``load_sources()`` is read at import time in several dashboard
modules, so the only clean way to swap the map is a fresh interpreter.

HTTP: ``/`` (the app), ``/api/state``, ``/api/track/<id>``, ``/api/events`` (SSE: ``revision`` and ``check``
events), ``/api/health``; and two JSON POSTs, ``/api/refresh`` (check + pull + rebuild now, answered when done) and
``/api/poke`` (202 at once, the check follows within a second). POSTs need an allowed Host (403), ``Content-Type:
application/json`` (415) and a body of at most 4 KB (413).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import share as layout
from . import sync
from .. import sources as vt_sources

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/index.html": ("index.html", "text/html; charset=utf-8"),
                "/static/hub.css": ("hub.css", "text/css; charset=utf-8"),
                "/static/hub.js": ("hub.js", "text/javascript; charset=utf-8")}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")
REMOTE_SOURCES = "remote-sources.json"
BUILD_TIMEOUT_S = 600
#: A host is online while its last sync is younger than 3 sync intervals plus this grace, stale up to an hour.
ONLINE_GRACE_S = 30.0
STALE_LIMIT_S = 3600.0
SESSION_LIVE_S = 30 * 60
SSE_KEEPALIVE_S = 15.0
HEADLINE_POINTS = 24
DETAIL_POINTS = 48
#: Per machine on /api/state: its live sessions, then at most this many of its other sessions, newest first.
HOST_RECENT_SESSIONS = 10
MAX_POST_BYTES = 4096
#: Keys whose value moves with the clock alone; the revision ignores them so it changes only when content does.
VOLATILE = {"generated_at", "last_pull", "last_check", "next_check_in_s", "check_mode", "age_s", "age_h"}


# --------------------------------------------------------------------------------------------- reading the share


def _merge(share: str | os.PathLike[str]) -> tuple[dict[str, str], dict[str, str], list[dict[str, Any]]]:
    """({key: absolute path}, {key: host}, problems) over every ``hosts/*/sources.json``."""

    paths: dict[str, str] = {}
    owners: dict[str, str] = {}
    synced: dict[str, float] = {}
    problems: list[dict[str, Any]] = []
    claims: dict[str, list[str]] = {}
    for folder in layout.host_dirs(share):
        host = folder.name
        manifest = layout.read_json(folder / layout.SOURCES_JSON)
        if manifest is None:
            continue
        if not isinstance(manifest, dict):
            problems.append({"kind": "bad_manifest", "host": host, "error": "sources.json is not a JSON object"})
            continue
        heartbeat = layout.read_json(folder / layout.HOST_JSON)
        last = layout.parse_iso(heartbeat.get("last_sync")) if isinstance(heartbeat, dict) else None
        synced[host] = last if last is not None else float("-inf")
        root = folder.resolve()
        for key, relative in manifest.items():
            if not isinstance(relative, str) or not relative:
                problems.append({"kind": "bad_path", "host": host, "key": key, "error": "not a relative path"})
                continue
            target = (root / relative).resolve()
            # WHY refuse an escape: a manifest is data from another machine and must only name files in its folder.
            if Path(relative).is_absolute() or (target != root and root not in target.parents):
                problems.append({"kind": "bad_path", "host": host, "key": key, "error": f"{relative!r} leaves the host folder"})
                continue
            claims.setdefault(key, []).append(host)
            if key not in paths or synced[host] > synced[owners[key]]:
                paths[key], owners[key] = str(target), host
    for key, hosts in sorted(claims.items()):
        if len(hosts) > 1:
            problems.append({"kind": "duplicate_key", "key": key, "hosts": sorted(hosts), "winner": owners[key]})
    return paths, owners, problems


def merge_sources(share: str | os.PathLike[str]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """{source key: absolute path under ``hosts/<host>/``}, and problems. Two hosts giving the same key: the host
    whose host.json ``last_sync`` is newer wins, and a ``duplicate_key`` problem names both."""

    paths, _, problems = _merge(share)
    return paths, problems


def host_status(last_sync: float | None, interval_s: float, now: float, heartbeat_s: float = 0.0) -> str:
    # WHY the heartbeat period counts: an idle worker rewrites host.json only every heartbeat_s (300 s by default),
    # so judging it by interval_s alone painted every healthy, quiet machine "stale" between heartbeats.
    if last_sync is None:
        return "offline"
    age = now - last_sync
    if age <= max(3 * interval_s, heartbeat_s) + ONLINE_GRACE_S:
        return "online"
    if age <= STALE_LIMIT_S:
        return "stale"
    return "offline"


def read_hosts(share: str | os.PathLike[str], now: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, problems = [], []
    for folder in layout.host_dirs(share):
        heartbeat = layout.read_json(folder / layout.HOST_JSON)
        if not isinstance(heartbeat, dict):
            if (folder / layout.HOST_JSON).exists():
                problems.append({"kind": "bad_heartbeat", "host": folder.name, "error": "host.json is not a JSON object"})
            heartbeat = {}
        last = layout.parse_iso(heartbeat.get("last_sync"))
        interval = heartbeat.get("interval_s")
        interval = float(interval) if isinstance(interval, (int, float)) and not isinstance(interval, bool) else 3.0
        beat = heartbeat.get("heartbeat_s")
        beat = float(beat) if isinstance(beat, (int, float)) and not isinstance(beat, bool) else 0.0
        mirrors = heartbeat.get("mirrors") if isinstance(heartbeat.get("mirrors"), list) else []
        skipped = heartbeat.get("skipped") if isinstance(heartbeat.get("skipped"), list) else []
        rows.append({"host": folder.name, "status": host_status(last, interval, now, beat),
                     "last_sync": heartbeat.get("last_sync") if last is not None else None,
                     "age_s": round(now - last, 1) if last is not None else None,
                     "interval_s": interval, "platform": heartbeat.get("platform"), "sessions_live": 0,
                     "files": len(mirrors), "skipped": skipped, "error": heartbeat.get("error")})
    return rows, problems


SESSION_FIELDS = ("session_id", "host", "account", "agent", "model", "cwd", "track", "url", "event", "started_at",
                  "last_seen", "ended", "demo")


def read_sessions(share: str | os.PathLike[str], now: float) -> list[dict[str, Any]]:
    cards = []
    for folder in layout.host_dirs(share):
        try:
            files = sorted((folder / layout.SESSIONS).glob("*.json"))
        except OSError:
            continue
        for file in files:
            data = layout.read_json(file)
            if not isinstance(data, dict):
                continue
            card = {field: data.get(field) for field in SESSION_FIELDS}
            card["host"] = folder.name  # WHY the folder, not the card: one writer per folder is the trust boundary
            card["demo"] = data.get("demo") is True
            seen = layout.parse_iso(card["last_seen"])
            card["live"] = bool(seen is not None and now - seen <= SESSION_LIVE_S and not card["ended"])
            cards.append(card)
    cards.sort(key=lambda card: (not card["live"], -(layout.parse_iso(card["last_seen"]) or 0), card["session_id"] or ""))
    return cards


HOST_SESSION_FIELDS = ("session_id", "host", "account", "agent", "model", "cwd", "project", "track", "url", "demo",
                       "live", "last_seen", "ended")


def project_of(cwd: Any) -> str | None:
    """The last path component of a session's cwd, with either slash (a Windows worker writes ``C:/Users/BAM/x`` or
    ``C:\\Users\\BAM\\x``)."""

    if not isinstance(cwd, str):
        return None
    parts = [part for part in re.split(r"[\\/]+", cwd) if part]
    return parts[-1] if parts else None


def host_sessions(cards: list[dict[str, Any]], host: str) -> list[dict[str, Any]]:
    """A machine's session cards for its row: live first, then at most HOST_RECENT_SESSIONS others (``cards`` comes
    sorted from read_sessions). Every card counts, with or without a track."""

    mine = [card for card in cards if card["host"] == host]
    picked = [card for card in mine if card["live"]] + [card for card in mine if not card["live"]][:HOST_RECENT_SESSIONS]
    return [{field: (project_of(card.get("cwd")) if field == "project" else card.get(field))
             for field in HOST_SESSION_FIELDS} for card in picked]


# --------------------------------------------------------------------------------------------- the state


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numbers(kpi: dict[str, Any]) -> list[float]:
    return [value["value"] for value in kpi.get("values") or []
            if isinstance(value, dict) and _number(value.get("value"))]


def headline(track: dict[str, Any]) -> dict[str, Any] | None:
    for kpi in track.get("kpis") or []:
        if not isinstance(kpi, dict):
            continue
        numbers = _numbers(kpi)
        if numbers:
            return {"label": kpi.get("label"), "unit": kpi.get("unit"), "direction": kpi.get("direction"),
                    "latest": numbers[-1], "values": numbers[-HEADLINE_POINTS:]}
    return None


def track_hosts(track: dict[str, Any], parent: dict[str, Any] | None, owners: dict[str, str], host_name: str) -> list[str]:
    registry = (parent or track).get("registry") or {}
    keys = registry.get("sources") if isinstance(registry.get("sources"), list) else []
    hosts = sorted({owners[key] for key in keys if key in owners})
    return hosts or [host_name]


def _track_row(track: dict[str, Any], parent: dict[str, Any] | None, owners: dict[str, str], host_name: str,
               sessions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": track.get("id"), "title": track.get("title"), "kind": track.get("kind"),
            "summary": track.get("summary"), "state": track.get("state"),
            "needs_you_count": track.get("needs_you_count"), "freshness": track.get("freshness"),
            "headline": headline(track), "hosts": track_hosts(track, parent, owners, host_name),
            "sessions": [card for card in sessions if card.get("track") == track.get("id")]}


def compute_state(projection: dict[str, Any] | None, share: str | os.PathLike[str], host_name: str,
                  hub_info: dict[str, Any], now: float) -> dict[str, Any]:
    """The ``/api/state`` document from the last good projection and the share as it is on disk now."""

    _, owners, problems = _merge(share)
    hosts, host_problems = read_hosts(share, now)
    sessions = read_sessions(share, now)
    live = {}
    for card in sessions:
        if card["live"]:
            live[card["host"]] = live.get(card["host"], 0) + 1
    for row in hosts:
        row["sessions_live"] = live.get(row["host"], 0)
        row["sessions"] = host_sessions(sessions, row["host"])
    tracks = []
    for track in (projection or {}).get("tracks") or []:
        if isinstance(track, dict) and track.get("kind") != "deployment" and not track.get("parent"):
            tracks.append(_track_row(track, None, owners, host_name, sessions))
    for problem in ((projection or {}).get("registry") or {}).get("problems") or []:
        if isinstance(problem, dict):
            problems.append({"kind": "registry", **problem})
    state = {"revision": None, "generated_at": layout.iso_utc(now), "hub": dict(hub_info), "hosts": hosts,
             "tracks": tracks, "problems": problems + host_problems}
    state["revision"] = revision_of(state)
    return state


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip(item) for key, item in value.items() if key not in VOLATILE and key != "revision"}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def revision_of(state: dict[str, Any]) -> str:
    """A short hash of the state minus the clock-only fields: unchanged content keeps its revision."""

    canonical = json.dumps(_strip(state), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def track_detail(projection: dict[str, Any] | None, state: dict[str, Any], track_id: str,
                 share: str | os.PathLike[str], host_name: str) -> dict[str, Any] | None:
    tracks = [t for t in (projection or {}).get("tracks") or [] if isinstance(t, dict)]
    track = next((t for t in tracks if t.get("id") == track_id), None)
    if track is None:
        return None
    row = next((dict(t) for t in state["tracks"] if t["id"] == track_id), None)
    if row is None:  # a deployment: drawn inside its parent, attributed through the parent's sources
        parent = next((t for t in tracks if t.get("id") == track.get("parent")), None)
        _, owners, _ = _merge(share)
        sessions = read_sessions(share, time.time())
        row = _track_row(track, parent, owners, host_name, sessions)
    row["parent"] = track.get("parent")
    row["kpis"] = []
    for kpi in track.get("kpis") or []:
        if not isinstance(kpi, dict):
            continue
        numbers = _numbers(kpi)
        measured = [v for v in kpi.get("values") or [] if isinstance(v, dict) and _number(v.get("value"))]
        note = kpi.get("note") or (measured[-1].get("note") if measured else None)
        row["kpis"].append({"id": kpi.get("id"), "label": kpi.get("label"), "unit": kpi.get("unit"),
                            "direction": kpi.get("direction"), "target": kpi.get("target"),
                            "latest": numbers[-1] if numbers else None, "values": numbers[-DETAIL_POINTS:],
                            "status": kpi.get("status"), "note": note})
    hosts_root = (Path(share) / layout.HOSTS).resolve()
    fresh = dict(track.get("freshness") or {})
    annotated = []
    for source in fresh.get("sources") or []:
        source = dict(source)
        source["host"] = host_name
        if isinstance(source.get("path"), str):
            try:
                relative = Path(source["path"]).resolve().relative_to(hosts_root)
                source["host"] = relative.parts[0] if relative.parts else host_name
            except ValueError:
                pass
        annotated.append(source)
    fresh["sources"] = annotated
    row["freshness"] = fresh
    return row


# --------------------------------------------------------------------------------------------- the hub


def remote_moved(share: str | os.PathLike[str]) -> bool:
    """Does the upstream branch hold commits this clone has not merged? One ``git ls-remote`` (a single small request)
    against the local remote-tracking ref, so a quiet share costs no fetch. Raises ``sync.SyncError`` when the remote
    cannot be reached."""

    share = Path(share)
    upstream = sync._upstream(share)
    if upstream is None:
        return False
    remote, _, branch = upstream.partition("/")
    listed = sync._git(share, "ls-remote", remote, f"refs/heads/{branch}").stdout.split()
    if not listed:
        return False
    tracking = sync._git(share, "rev-parse", "-q", "--verify", f"refs/remotes/{upstream}", check=False).stdout.strip()
    if listed[0] != tracking:
        return True
    behind = sync._git(share, "rev-list", "--count", f"HEAD..{tracking}", check=False).stdout.strip()
    return behind.isdigit() and int(behind) > 0  # fetched earlier but never merged (a pull that failed half way)


def local_source_paths(projection: dict[str, Any] | None, share: str | os.PathLike[str]) -> list[Path]:
    """This machine's own source paths: every track's ``freshness.sources`` path that is not under the share."""

    root = Path(share).resolve()
    paths: dict[str, Path] = {}
    for track in (projection or {}).get("tracks") or []:
        if not isinstance(track, dict):
            continue
        for source in (track.get("freshness") or {}).get("sources") or []:
            path = source.get("path") if isinstance(source, dict) else None
            if not isinstance(path, str) or not path:
                continue
            resolved = Path(path).resolve()
            if resolved == root or root in resolved.parents:
                continue
            paths[str(resolved)] = resolved
    return sorted(paths.values())


def _stat(path: str | os.PathLike[str]) -> tuple[int, int] | None:
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size


def stat_fingerprint(paths: list[Path]) -> dict[str, tuple[int, int] | None]:
    """{path: (mtime_ns, size) or None when missing}; a directory adds its direct children (stat only, no reads)."""

    out: dict[str, tuple[int, int] | None] = {}
    for path in paths:
        out[str(path)] = _stat(path)
        if out[str(path)] is not None and path.is_dir():
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        try:
                            info = entry.stat()
                            out[entry.path] = (info.st_mtime_ns, info.st_size)
                        except OSError:
                            out[entry.path] = None
            except OSError:
                continue
    return out


class Hub:
    def __init__(self, share: str | os.PathLike[str], workspace: str | os.PathLike[str],
                 data_home: str | os.PathLike[str], *, host_name: str, check_fast: float = 5.0,
                 check_slow: float = 60.0, fast_window: float = 120.0, rebuild_interval: float = 300.0,
                 log=None, clock=time.monotonic):
        self.share = Path(share).resolve()
        self.workspace = Path(workspace).resolve()
        self.data_home = Path(data_home).resolve()
        self.host_name = host_name
        self.check_fast = check_fast
        self.check_slow = check_slow
        self.fast_window = fast_window
        self.rebuild_interval = rebuild_interval
        self.clock = clock
        self.log = log or (lambda message: print(f"{time.strftime('%H:%M:%S')} {message}", file=sys.stderr, flush=True))
        self.projection: dict[str, Any] | None = None
        self.share_head: str | None = None
        self.last_pull: float | None = None
        self.last_check: float | None = None
        self.last_build: float | None = None
        self.build_error: str | None = None
        self.pull_error: str | None = None
        self.stop = threading.Event()
        self._changed = threading.Condition()
        self._build_process: subprocess.Popen | None = None
        self._started = False
        self._fast_until = float("-inf")  # on self.clock
        self._next_check = float("-inf")  # on self.clock; the first tick checks
        self._local_stats: dict[str, tuple[int, int] | None] | None = None
        # WHY one lock for all work: the loop, a Refresh and a poke all run git in the same clone.
        self._work = threading.RLock()
        self._wake = threading.Event()
        self._refresh_guard = threading.Lock()
        self._refresh_job: dict[str, Any] | None = None
        self.state = self._compute(time.time())

    # ---------------------------------------------------------------- state
    def check_mode(self) -> str:
        return "fast" if self.clock() < self._fast_until else "slow"

    def next_check_in_s(self) -> float:
        return round(max(0.0, self._next_check - self.clock()), 1)

    def hub_info(self) -> dict[str, Any]:
        return {"host_name": self.host_name, "share_head": self.share_head,
                "last_pull": layout.iso_utc(self.last_pull) if self.last_pull else None,
                "last_check": layout.iso_utc(self.last_check) if self.last_check else None,
                "next_check_in_s": self.next_check_in_s(), "check_mode": self.check_mode(),
                "build_error": self.build_error, "pull_error": self.pull_error}

    def live_state(self) -> dict[str, Any]:
        """The cached state with the clock-only hub fields read now (they are not in the revision)."""

        state = self.state
        return {**state, "hub": {**state["hub"], "next_check_in_s": self.next_check_in_s(),
                                 "check_mode": self.check_mode()}}

    def _compute(self, now: float) -> dict[str, Any]:
        return compute_state(self.projection, self.share, self.host_name, self.hub_info(), now)

    def recompute(self) -> None:
        state = self._compute(time.time())
        with self._changed:
            changed = state["revision"] != self.state["revision"] \
                or state["hub"]["last_check"] != self.state["hub"]["last_check"]
            self.state = state
            if changed:
                self._changed.notify_all()

    def wait_for_change(self, revision: str | None, last_check: str | None, timeout: float) -> tuple[str, str | None]:
        """Block until the revision or the last check moves (or ``timeout``); returns both as they are then."""

        with self._changed:
            self._changed.wait_for(lambda: self.state["revision"] != revision
                                   or self.state["hub"]["last_check"] != last_check or self.stop.is_set(), timeout)
            return self.state["revision"], self.state["hub"]["last_check"]

    # ---------------------------------------------------------------- check, pull and build
    def enter_fast(self) -> None:
        """Check every ``check_fast`` seconds for the next ``fast_window`` seconds, starting from now."""

        now = self.clock()
        self._fast_until = now + self.fast_window
        self._next_check = min(self._next_check, now + self.check_fast)

    def write_sources(self) -> Path:
        paths, _ = merge_sources(self.share)
        local = layout.read_json(vt_sources.sources_file())
        merged = {key: value for key, value in (local if isinstance(local, dict) else {}).items() if isinstance(value, str)}
        merged.update(paths)
        # WHY pin the dashboard data home here: adapters keep caches under ``{dashboard_data_home}`` (the grasping
        # verdict), and the hub must write only its own --data-home, never this machine's real dashboard home.
        merged["dashboard_data_home"] = str(self.data_home)
        target = self.data_home / REMOTE_SOURCES
        layout.write_json_atomic(target, merged)
        return target

    def rebuild(self) -> None:
        started = time.time()
        try:
            sources_file = self.write_sources()
            env = {**os.environ, "VIBETRACKS_SOURCES": str(sources_file),
                   "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")]))}
            self._build_process = subprocess.Popen(
                [sys.executable, "-m", "vibetracks.dashboard.build", "--workspace", str(self.workspace),
                 "--data-home", str(self.data_home)],
                cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace")
            try:
                _, stderr = self._build_process.communicate(timeout=BUILD_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                self._build_process.kill()
                self._build_process.communicate()
                raise RuntimeError(f"build took over {BUILD_TIMEOUT_S} s and was stopped")
            code = self._build_process.returncode
            if code != 0:
                tail = " / ".join(line for line in stderr.strip().splitlines()[-3:])
                raise RuntimeError(f"build exited {code}: {tail}")
            projection = json.loads((self.data_home / "projection.json").read_text(encoding="utf-8"))
            if not isinstance(projection, dict) or not isinstance(projection.get("tracks"), list):
                raise RuntimeError("projection.json has no tracks list")
        except Exception as error:
            if self.build_error != str(error):
                self.log(f"build failed (serving the last good state): {error}")
            self.build_error = str(error)
        else:
            if self.build_error or self.projection is None:
                self.log(f"built {len(projection['tracks'])} tracks in {time.time() - started:.1f} s")
            self.projection = projection
            self.build_error = None
        finally:
            self._build_process = None
            self.last_build = time.time()

    def _rebuild(self) -> None:
        """Rebuild, and re-baseline the local stat fingerprint. WHY read the old paths before the build: a write that
        lands while the build runs must still count as a change on the next tick."""

        before = stat_fingerprint(local_source_paths(self.projection, self.share))
        self.rebuild()
        after = stat_fingerprint(local_source_paths(self.projection, self.share))
        self._local_stats = {path: before[path] if path in before else value for path, value in after.items()}

    def local_changed(self) -> bool:
        """Did one of this machine's own source files change since the last look (stat only)?"""

        current = stat_fingerprint(local_source_paths(self.projection, self.share))
        previous, self._local_stats = self._local_stats, current
        return previous is not None and current != previous

    def check(self) -> list[str]:
        """``ls-remote``; pull and restore mtimes only when the remote moved. Returns the changed paths."""

        changed: list[str] = []
        try:
            if (self.share / ".git").exists():
                if remote_moved(self.share):
                    changed = sync.pull_and_restore(self.share)
                    self.last_pull = time.time()
                head = sync._git(self.share, "rev-parse", "--short", "HEAD", check=False).stdout.strip()
                self.share_head = head or None
            self.pull_error = None
        except Exception as error:
            if self.pull_error != str(error):
                self.log(f"check failed (serving the last good state): {error}")
            self.pull_error = str(error)
        if changed:
            self.log(f"pulled {len(changed)} files")
            self.enter_fast()
        self.last_check = time.time()
        self._next_check = self.clock() + (self.check_fast if self.check_mode() == "fast" else self.check_slow)
        return changed

    def tick(self, *, force_check: bool = False) -> None:
        with self._work:
            if not self._started:
                self._started = True
                force_check = True
                if (self.share / ".git").exists():
                    # WHY restore everything once: the clone's first checkout stamped every file with the clone time.
                    try:
                        sync.restore_mtimes(self.share, [p for p in sync.tracked_files(self.share)
                                                         if p.startswith(layout.HOSTS + "/")])
                    except Exception as error:
                        self.log(f"mtime restore failed: {error}")
            changed: list[str] = []
            if force_check or self.clock() >= self._next_check:
                changed = self.check()
                self.recompute()  # WHY before the build: hosts and session cards come from the share, not the build
            local = self.local_changed()
            if local:
                self.enter_fast()
            due = self.last_build is None or time.time() - self.last_build >= self.rebuild_interval
            if changed or local or due:
                self._rebuild()
            self.recompute()

    def run(self) -> None:
        while not self.stop.is_set():
            poked = self._wake.is_set()
            self._wake.clear()
            try:
                self.tick(force_check=poked)
            except Exception:
                traceback.print_exc(file=sys.stderr)
            # WHY wake every check_fast seconds even when slow: the local stat runs on every fast tick.
            self._wake.wait(max(0.0, min(self._next_check - self.clock(), self.check_fast)))

    def poke(self, host: Any = None) -> None:
        """A worker pushed: check within a second (the loop wakes now) and stay fast for the window."""

        if isinstance(host, str) and layout.NAME.match(host):
            self.log(f"poke from {host}")
        self.enter_fast()
        self._wake.set()

    def refresh_now(self) -> dict[str, Any]:
        """Check + pull + rebuild now and answer when done; a second caller joins the one in flight."""

        with self._refresh_guard:
            job = self._refresh_job
            owner = job is None
            if owner:
                job = self._refresh_job = {"done": threading.Event(), "result": None}
        if not owner:
            job["done"].wait()
            return job["result"]
        started = time.monotonic()
        result: dict[str, Any] = {"ok": False, "revision": None, "changed": [], "took_s": None}
        try:
            with self._work:
                self.enter_fast()
                changed = self.check()
                self.recompute()
                self._rebuild()
                self.recompute()
            result.update(ok=self.pull_error is None and self.build_error is None, changed=changed)
            if self.pull_error:
                result["pull_error"] = self.pull_error
            if self.build_error:
                result["build_error"] = self.build_error
        except Exception as error:
            result["error"] = str(error)
        finally:
            result["revision"] = self.state["revision"]
            result["took_s"] = round(time.monotonic() - started, 2)
            with self._refresh_guard:
                self._refresh_job = None
            job["result"] = result
            job["done"].set()
        return result

    def shutdown(self) -> None:
        self.stop.set()
        self._wake.set()
        with self._changed:
            self._changed.notify_all()
        process = self._build_process
        if process is not None and process.poll() is None:
            process.kill()


# --------------------------------------------------------------------------------------------- HTTP


def host_allowed(header: str | None, allowed: set[str]) -> bool:
    """DNS-rebinding guard (as in vibetracks/server.py): only loopback names, or names passed with ``--allow-host``
    (``tailscale serve`` adds its MagicDNS name there), may address this server; the port is ignored."""

    host = (header or "").strip().lower()
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host in allowed


def make_handler(hub: Hub, allowed: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VibeTracksHub/1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            if not host_allowed(self.headers.get("Host"), allowed):
                self._json({"error": "Forbidden host"}, HTTPStatus.FORBIDDEN)
                return
            path = urlparse(self.path).path
            try:
                if path in STATIC_FILES:
                    name, content_type = STATIC_FILES[path]
                    self._send((STATIC_DIR / name).read_bytes(), content_type)
                elif path == "/api/state":
                    self._json(hub.live_state())
                elif path.startswith("/api/track/"):
                    track_id = unquote(path[len("/api/track/"):])
                    state = hub.state
                    detail = track_detail(hub.projection, state, track_id, hub.share, hub.host_name)
                    if detail is None:
                        self._json({"error": f"no track {track_id!r}"}, HTTPStatus.NOT_FOUND)
                    else:
                        self._json({"revision": state["revision"], "hub": state["hub"], "track": detail})
                elif path == "/api/events":
                    self._events()
                elif path == "/api/health":
                    state = hub.state
                    self._json({"ok": hub.build_error is None and hub.projection is not None,
                                "revision": state["revision"], "last_pull": state["hub"]["last_pull"],
                                "last_check": state["hub"]["last_check"], "build_error": hub.build_error})
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self) -> None:  # noqa: N802
            # WHY these three gates: the POSTs make the hub run git and a build, so a page on another origin must not
            # be able to trigger them. A cross-site form can only send text/plain or form bodies (415), a rebound DNS
            # name fails the Host check (403), and nothing here needs more than a tiny body (413).
            if not host_allowed(self.headers.get("Host"), allowed):
                self._json({"error": "Forbidden host"}, HTTPStatus.FORBIDDEN)
                return
            path = urlparse(self.path).path
            if path not in ("/api/refresh", "/api/poke"):
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            media = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if media != "application/json":
                self._json({"error": "Content-Type must be application/json"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0:
                self._json({"error": "bad Content-Length"}, HTTPStatus.BAD_REQUEST)
                return
            if length > MAX_POST_BYTES:
                self.close_connection = True  # the unread body must not be parsed as the next request
                self._json({"error": f"body over {MAX_POST_BYTES} bytes"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except ValueError:
                payload = None
            if not isinstance(payload, dict):
                self._json({"error": "body must be a JSON object"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                if path == "/api/poke":
                    hub.poke(payload.get("host"))
                    self._json({"ok": True}, HTTPStatus.ACCEPTED)
                else:
                    self._json(hub.refresh_now())
            except (BrokenPipeError, ConnectionResetError):
                return

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            revision, checked = hub.state["revision"], hub.state["hub"]["last_check"]
            self.wfile.write(f"retry: 3000\nevent: revision\ndata: {revision}\n\n".encode())
            self.wfile.flush()
            while not hub.stop.is_set():
                current, now_checked = hub.wait_for_change(revision, checked, SSE_KEEPALIVE_S)
                if hub.stop.is_set():
                    break
                sent = False
                if current != revision:
                    revision, sent = current, True
                    self.wfile.write(f"event: revision\ndata: {revision}\n\n".encode())
                if now_checked != checked:
                    # WHY its own event: a check that finds nothing keeps the revision, but "checked 3 s ago" moves.
                    checked, sent = now_checked, True
                    self.wfile.write(f"event: check\ndata: {checked or ''}\n\n".encode())
                if not sent:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the Vibe Tracks hub over a git share.")
    parser.add_argument("--share", required=True, help="this machine's clone of the share")
    parser.add_argument("--workspace", required=True, help="the workspace whose .vtdash names the work-track registry")
    parser.add_argument("--data-home", required=True, help="where the projection and remote-sources.json are written")
    parser.add_argument("--port", type=int, default=4470, help="0 picks a free port")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                        help="an extra Host header name to answer (e.g. a Tailscale MagicDNS name); repeatable")
    parser.add_argument("--host-name", default=socket.gethostname(), help="this machine's name (default: hostname)")
    parser.add_argument("--check-fast", type=float, default=5.0, help="seconds between checks while fast (default 5)")
    parser.add_argument("--check-slow", type=float, default=60.0, help="seconds between checks otherwise (default 60)")
    parser.add_argument("--fast-window", type=float, default=120.0,
                        help="how long checks stay fast after a change, Refresh or poke (default 120 s)")
    parser.add_argument("--pull-interval", type=float, default=None, metavar="X",
                        help="sets both --check-fast and --check-slow to X")
    parser.add_argument("--rebuild-interval", type=float, default=300.0,
                        help="safety rebuild period in seconds (default 300)")
    args = parser.parse_args(argv)
    if args.pull_interval is not None:
        args.check_fast = args.check_slow = args.pull_interval

    hub = Hub(args.share, args.workspace, args.data_home, host_name=args.host_name, check_fast=args.check_fast,
              check_slow=args.check_slow, fast_window=args.fast_window, rebuild_interval=args.rebuild_interval)
    allowed = LOOPBACK | {name.strip().lower() for name in args.allow_host if name.strip()}
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(hub, allowed))
    server.daemon_threads = True
    shown = "127.0.0.1" if args.bind in ("127.0.0.1", "0.0.0.0", "") else args.bind
    print(f"listening on http://{shown}:{server.server_port}/", flush=True)

    def stop(*_: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    worker = threading.Thread(target=hub.run, name="hub-check", daemon=True)
    worker.start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        hub.shutdown()
        server.server_close()
        worker.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
