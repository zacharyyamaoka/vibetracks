"""Build the dashboard projection: ``python3 -m vibetracks.dashboard.build [--workspace W] [--data-home DIR] [--snapshot]``.

**Live (the default when the workspace names a registry):** ``LiveBuilder`` reads the work-track registry
(registry.py), runs each track's adapter (adapters/<name>.py, docs/dashboard/ADAPTERS.md) over the files its note
declares, and assembles ``vibetracks-dashboard/1`` with ``source.live: true``. The backend calls it on every
``GET /projection``; an adapter reruns only when its note, its module or one of its declared source files changed
(mtime and size), and each track's freshness (newest source mtime against its stall rule) is recomputed every time.

**Needs you (live):** every top-level track's ``needs_you`` and ``needs_you_count`` come from
``vibetracks/dashboard/needs.py`` (the /needs route's own doc for that track), never from the adapter's list: one
source, so the home cell, the track page and the needs page show the same "B blocking · M open". A deployment
(child) has no needs-you source at all, so it reads null/null and an empty list ("not reported"), whatever its
adapter or the snapshot carried.

**Snapshot (``--snapshot``, and the fallback for the rig's can12/can16 children until the rig adapter draws them):**
the data home (default ``~/.local/share/vibetracks/dashboard``, or ``dashboard_data_home`` in vibetracks/sources.py) holds:

- ``sources/bam-loops-snapshot-2026-10-03.json``: the verified snapshot of both BAM loops (copied once from the
  research context; the adapter reads only this copy),
- ``sources/kinsim-curriculum-2026-10-03.json``: the kinsim curriculum the snapshot names, for each rung's
  ``kpi_weight`` (the one column the snapshot does not carry),
- ``projection.json``: the output, schema ``vibetracks-dashboard/1`` (docs/dashboard/PROJECTION.md).

WHY a copy in the data home and not a read of the research folder: the research folder is a report's evidence and
may be moved or rewritten; the dashboard's input must stay put and be named in the projection's ``source`` block.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import traceback
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from . import needs as needs_source
from .adapters import base
from .adapters.bam_loops import build_projection, load_json
from .registry import Registry, WorkTrack, read_registry
from ..sources import load_sources

_SOURCES = load_sources()
#: The data home when neither ``--data-home`` nor ``$VIBETRACKS_DASHBOARD_HOME`` names one (vibetracks/sources.py).
DEFAULT_HOME = Path(_SOURCES["dashboard_data_home"])
SNAPSHOT_NAME = "bam-loops-snapshot-2026-10-03.json"
CURRICULUM_NAME = "kinsim-curriculum-2026-10-03.json"
#: Where the sources were verified (2026-10-03). Read only to seed the data home. The snapshot is a dated research
#: artifact, not a live loop folder, so it stays a constant; the curriculum comes from ``kinsim_curriculum_dir``.
SNAPSHOT_ORIGIN = Path("/home/bam/vibetracks/reports/media/dashboard-prior-art-2026-10-03/context/real-data.json")
CURRICULUM_ORIGIN = Path(_SOURCES["kinsim_curriculum_dir"]) / "curriculum.json"


def data_home(value: str | os.PathLike[str] | None = None) -> Path:
    return Path(value or os.environ.get("VIBETRACKS_DASHBOARD_HOME") or load_sources()["dashboard_data_home"]).expanduser()


def seed_sources(home: Path, *, refresh: bool = False, snapshot_origin: Path = SNAPSHOT_ORIGIN,
                 curriculum_origin: Path = CURRICULUM_ORIGIN) -> tuple[Path, Path | None]:
    sources = home / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    snapshot = sources / SNAPSHOT_NAME
    curriculum = sources / CURRICULUM_NAME
    if refresh or not snapshot.exists():
        if not snapshot_origin.is_file():
            raise FileNotFoundError(f"no snapshot at {snapshot} and none to copy from {snapshot_origin}")
        shutil.copyfile(snapshot_origin, snapshot)
    if (refresh or not curriculum.exists()) and curriculum_origin.is_file():
        shutil.copyfile(curriculum_origin, curriculum)
    return snapshot, (curriculum if curriculum.exists() else None)


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def build(home: Path, *, refresh: bool = False) -> dict:
    snapshot_path, curriculum_path = seed_sources(home, refresh=refresh)
    projection = build_projection(
        load_json(snapshot_path),
        load_json(curriculum_path) if curriculum_path else None,
        snapshot_path=str(snapshot_path),
        curriculum_path=str(curriculum_path) if curriculum_path else None,
    )
    write_json_atomic(home / "projection.json", projection)
    return projection


# --------------------------------------------------------------------------------------------- live, from the registry

#: The workspace the backend is started with (Clank passes ``--workspace``); the CLI's default.
DEFAULT_WORKSPACE = Path(__file__).resolve().parents[2] / "workspace"
ADAPTER_PACKAGE = "vibetracks.dashboard.adapters"
#: A directory source is stamped by its own entries, never recursively, and at most this many of them.
DIR_SCAN_LIMIT = 5000
REASON_LIMIT = 240


def source_stamp(path: str, depth: int = 1) -> tuple | None:
    """``(kind, newest mtime_ns, size or entry count)`` for a file or directory; None when it does not exist.

    WHY a directory's newest entry and not its own mtime: a directory's mtime moves only when an entry is added or
    removed, so a loop rewriting status.json in place would look idle. One level deep by default: a run-media tree has
    thousands of files and the build runs on every GET. An adapter whose files sit one folder further down (the rig's
    run cache, ``<bundle>/<run>.json``) asks for ``depth`` 2 through its module's ``DEPTH`` map.
    """

    try:
        info = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        return ("file", info.st_mtime_ns, info.st_size)
    newest, count = info.st_mtime_ns, 0
    folders = [(path, 1)]
    while folders and count <= DIR_SCAN_LIMIT:
        folder, level = folders.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    count += 1
                    if count > DIR_SCAN_LIMIT:
                        break
                    try:
                        newest = max(newest, entry.stat().st_mtime_ns)
                        if level < depth and entry.is_dir(follow_symlinks=False):
                            folders.append((entry.path, level + 1))
                    except OSError:
                        continue
        except OSError:
            pass
    return ("dir", newest, count)


def _iso(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1e9).astimezone().isoformat(timespec="seconds")


def _quiet(hours: float) -> str:
    return f"{hours / 24:.0f} days" if hours >= 48 else f"{hours:.0f} h"


def freshness(keys: list[str], paths: dict[str, str], stall_hours: float, now: float,
              stamps: dict[str, tuple | None] | None = None) -> dict[str, Any]:
    """How recently the loop's own files changed: the newest mtime among ``keys`` against the stall rule.

    ``stale`` is null (not false) when no file exists: liveness is then unknown, never assumed. ``age_h`` is wall-clock
    hours since that file changed (truth rule 5: never agent-hours).
    """

    rows, newest, newest_key = [], None, None
    for key in keys:
        path = paths.get(key)
        if path is None:
            rows.append({"key": key, "path": None, "exists": False, "modified": None, "note": "not a sources.py key"})
            continue
        stamped = stamps[key] if stamps is not None and key in stamps else source_stamp(path)
        rows.append({"key": key, "path": path, "exists": stamped is not None,
                     "modified": _iso(stamped[1]) if stamped else None, "note": None if stamped else "missing on disk"})
        if stamped and (newest is None or stamped[1] > newest):
            newest, newest_key = stamped[1], key
    if newest is None:
        return {"newest": None, "newest_source": None, "age_h": None, "stall_hours": stall_hours, "stale": None,
                "note": "no source file found · liveness unknown", "sources": rows}
    age_h = max(0.0, (now - newest / 1e9) / 3600.0)
    stale = age_h > stall_hours
    return {"newest": _iso(newest), "newest_source": newest_key, "age_h": round(age_h, 1), "stall_hours": stall_hours,
            "stale": stale, "note": f"sources quiet {_quiet(age_h)} · stall rule {stall_hours:g} h" if stale else None,
            "sources": rows}


def snapshot_freshness(path: str | None, generated_at: str | None, stall_hours: float, now: float) -> dict[str, Any]:
    """Freshness of a frozen snapshot, dated by the snapshot's own ``generated_at``.

    WHY not the file's mtime: the data home's copy is re-made whenever the data home is seeded, so its mtime says
    when it was copied, not when its numbers were read; a fresh copy of 10-03 data must still read stale.
    """

    try:
        when = datetime.fromisoformat(generated_at).timestamp() if generated_at else None
    except ValueError:
        when = None
    if when is None:
        return {"newest": None, "newest_source": None, "age_h": None, "stall_hours": stall_hours, "stale": None,
                "note": "snapshot has no generated_at · liveness unknown",
                "sources": [{"key": "snapshot", "path": path, "exists": path is not None, "modified": None,
                             "note": "a frozen snapshot, not a live file"}]}
    fresh = freshness(["snapshot"], {"snapshot": path or ""}, stall_hours, now, {"snapshot": ("file", int(when * 1e9), 0)})
    fresh["sources"][0]["note"] = "a frozen snapshot, dated by its generated_at"
    if fresh["stale"]:
        fresh["note"] = f"snapshot of {generated_at[:10]} · {fresh['note']}"
    return fresh


def heartbeat_keys(work_track: WorkTrack, module: ModuleType | None) -> list[str]:
    """The keys whose mtime says this loop moved: the note's ``vibe-heartbeat`` when it sets one, else the declared
    sources the adapter's ``READS`` marks ``heartbeat`` (a key it does not list counts), else every declared source.

    WHY narrow the default: an adapter also lists shared folders (bam_ws ``reports/``) to find evidence media, and
    plans or scripts another session writes. Any fleet writing there would otherwise make a stopped loop look alive.
    """

    if work_track.heartbeat_declared:
        return list(work_track.heartbeat)
    reads = getattr(module, "READS", None)
    if not isinstance(reads, dict):
        return list(work_track.sources)
    alive = [key for key in work_track.sources if reads.get(key, "heartbeat") == "heartbeat"]
    return alive or list(work_track.sources)


def _truncate(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= REASON_LIMIT else text[:REASON_LIMIT - 1] + "…"


def _media_ids(track: dict[str, Any]) -> set[str]:
    """Every media id a track's evidence and links point at (the allowlist entries it needs)."""

    ids: set[str] = set()
    for link in track.get("links") or []:
        if isinstance(link, dict) and link.get("media"):
            ids.add(link["media"])
    for items in (track.get("evidence") or {}).get("by_iteration", {}).values():
        for item in items:
            for ref in item.get("media") or []:
                if isinstance(ref, dict) and ref.get("id"):
                    ids.add(ref["id"])
            for link in item.get("links") or []:
                if isinstance(link, dict) and link.get("media"):
                    ids.add(link["media"])
    return ids


class LiveBuilder:
    """The live projection for one workspace's registry, rebuilt per call and cached per track.

    Thread-safe (the backend serves from a ThreadingHTTPServer). ``build()`` always rereads the registry notes and
    stats the declared sources (cheap); an adapter reruns only when its cache key moved:
    ``(note revision, adapter module stamp, declared source stamps)``.
    """

    def __init__(self, workspace: str | os.PathLike[str], home: str | os.PathLike[str] | None = None, *,
                 sources: Callable[[], dict[str, str]] = load_sources, clock: Callable[[], float] | None = None,
                 package: str = ADAPTER_PACKAGE):
        self.workspace = Path(workspace)
        self.home = data_home(home)
        self._sources = sources
        self._clock = clock or (lambda: datetime.now().timestamp())
        self._package = package
        self._lock = threading.Lock()
        self._modules: dict[str, tuple[tuple | None, ModuleType]] = {}
        self._tracks: dict[str, tuple[tuple, dict[str, Any], list[dict[str, Any]], dict[str, Any]]] = {}
        self._snapshot: tuple[tuple, dict[str, dict[str, Any]], dict[str, Any], str, str | None] | None = None
        self.adapter_runs = 0  # how many times an adapter actually ran (tests read it to prove the cache)

    # -------------------------------------------------------------------------------- adapters

    def _module(self, name: str | None) -> tuple[ModuleType | None, tuple | None, str | None]:
        """(module, stamp of its file, None) or (None, None, the reason it cannot run)."""

        if name is None:
            return None, None, "no adapter declared (vibe-adapter)"
        if name == "base" or not name.replace("_", "").isalnum() or not name[0].isalpha() or name != name.lower():
            return None, None, f"no adapter named {name!r}"
        full = f"{self._package}.{name}"
        cached = self._modules.get(name)
        try:
            if cached is None:
                importlib.invalidate_caches()  # WHY: a module file created after startup is otherwise invisible
                module = importlib.import_module(full)
            else:
                module = cached[1]
            file = getattr(module, "__file__", None)
            stamp = source_stamp(file) if file else None
            if cached is not None and stamp != cached[0]:
                # WHY reload on a changed file: adapter lanes iterate against the running backend; a restart per
                # edit would be the only other way to see their change.
                module = importlib.reload(module)
                stamp = source_stamp(file) if file else None
        except ModuleNotFoundError as error:
            self._modules.pop(name, None)
            if error.name == full:
                return None, None, f"no adapter module adapters/{name}.py"
            return None, None, _truncate(f"adapter failed to import · {type(error).__name__}: {error}")
        except Exception as error:  # a SyntaxError or a raising import inside the adapter
            self._modules.pop(name, None)
            traceback.print_exc(file=sys.stderr)
            return None, None, _truncate(f"adapter failed to import · {type(error).__name__}: {error}")
        self._modules[name] = (stamp, module)
        if not callable(getattr(module, "build_track", None)):
            return None, stamp, f"adapter {name} has no build_track"
        return module, stamp, None

    def _run(self, work_track: WorkTrack, module: ModuleType | None, reason: str | None,
             sources: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        """(track, adapter children, media): the adapter's output, or an honest not-reporting track."""

        if module is None:
            return base.not_reporting(work_track, reason or "no adapter"), [], {}
        self.adapter_runs += 1
        try:
            track = module.build_track(work_track, dict(sources))
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            return base.not_reporting(work_track, _truncate(f"adapter error · {type(error).__name__}: {error}")), [], {}
        found = base.problems(track)
        if found:
            return base.not_reporting(work_track, _truncate(f"adapter output invalid · {'; '.join(found[:3])}")), [], {}
        track = dict(track)
        media = track.pop("media", None) or {}
        children: list[dict[str, Any]] = []
        build_children = getattr(module, "build_children", None)
        if callable(build_children) and work_track.children:
            try:
                produced = build_children(work_track, dict(sources))
            except Exception as error:
                traceback.print_exc(file=sys.stderr)
                produced = []
                reason_children = _truncate(f"adapter error in build_children · {type(error).__name__}: {error}")
                children = [base.not_reporting(self._child(work_track, child), reason_children) | {"id": child}
                            for child in work_track.children]
            else:
                for child in produced if isinstance(produced, list) else []:
                    if isinstance(child, dict) and child.get("id") in work_track.children:
                        child_found = base.problems(child)
                        if child_found:
                            child = base.not_reporting(self._child(work_track, child["id"]),
                                                       _truncate(f"adapter output invalid · {'; '.join(child_found[:3])}"))
                        child = dict(child)
                        media.update(child.pop("media", None) or {})
                        children.append(child)
        return track, children, media

    @staticmethod
    def _child(parent: WorkTrack, child_id: str) -> WorkTrack:
        return replace(parent, id=child_id, title=child_id, children=[], roadmap=None)

    # -------------------------------------------------------------------------------- the snapshot fallback

    def _snapshot_tracks(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any], str | None, str | None, str | None]:
        """({id: deployment track}, media, snapshot path, its generated_at, reason) from the bam_loops snapshot,
        cached by the snapshot's stamp."""

        try:
            snapshot_path, curriculum_path = seed_sources(self.home)
        except (OSError, FileNotFoundError) as error:
            return {}, {}, None, None, _truncate(f"snapshot unavailable · {error}")
        stamp = (source_stamp(str(snapshot_path)), source_stamp(str(curriculum_path)) if curriculum_path else None)
        if self._snapshot is not None and self._snapshot[0] == stamp:
            return self._snapshot[1], self._snapshot[2], self._snapshot[3], self._snapshot[4], None
        try:
            projection = build_projection(
                load_json(snapshot_path), load_json(curriculum_path) if curriculum_path else None,
                snapshot_path=str(snapshot_path), curriculum_path=str(curriculum_path) if curriculum_path else None)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            return {}, {}, str(snapshot_path), None, _truncate(f"snapshot adapter error · {type(error).__name__}: {error}")
        tracks = {track["id"]: track for track in projection["tracks"] if track.get("kind") == "deployment"}
        generated_at = projection["source"].get("snapshot_generated_at")
        self._snapshot = (stamp, tracks, projection.get("media") or {}, str(snapshot_path),
                          generated_at if isinstance(generated_at, str) else None)
        return tracks, self._snapshot[2], str(snapshot_path), self._snapshot[4], None

    # -------------------------------------------------------------------------------- needs you

    @staticmethod
    def _apply_needs(out: dict[str, Any], work_track: WorkTrack, paths: dict[str, str],
                     problems: list[dict[str, str]]) -> None:
        """Set ``needs_you``, ``needs_you_count`` and ``needs_you_source`` from needs.py's doc for this track.

        WHY not the adapter's own ``needs_you``: the adapters counted "blocking" as "names a rung" while /needs
        computes ``blocking_now`` (open, unanswered, default not in effect), and grasping and detection had items here
        but none on the needs page, so the home cell said "7 blocking / 7 open" and opened an empty page. A track
        needs.py has no structured source for reads null/null ("not reported"), never 0, and an empty list.
        """

        try:
            doc = needs_source.build_track(work_track.id, paths, title=work_track.title)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            problems.append({"path": Path(work_track.note_path).name,
                             "error": _truncate(f"needs.py error · {type(error).__name__}: {error}")})
            doc = None
        out["needs_you_count"] = needs_source.needs_you_count(doc)
        out["needs_you"] = needs_source.needs_you_rows(doc)
        source = (doc or {}).get("source") or {}
        out["needs_you_source"] = {"adapter": source.get("adapter"), "live": bool(source.get("live")),
                                   "note": source.get("note") if doc is not None else "needs.py could not build this track"}

    @staticmethod
    def _child_needs(out: dict[str, Any], parent: WorkTrack) -> None:
        """A deployment's needs-you fields: null/null, an empty list, and a note saying where its questions live.

        WHY not the child's own count: the 2026-10-03 snapshot's CAN 12 / CAN 16 rows carried 0/0, so their cells read
        "Needs you · nothing open" while needs.py, the one source, reports nothing for a deployment (its page said
        "not reported"). A count with no source is unknown, never 0 (truth rule); the parent loop's questions are on
        the parent's page.
        """

        out["needs_you_count"] = {"open": None, "blocking": None}
        out["needs_you"] = []
        out["needs_you_source"] = {"adapter": None, "live": False,
                                   "note": f"needs.py reads no questions per deployment; the {parent.title} loop's "
                                           f"questions are on its own page"}

    # -------------------------------------------------------------------------------- assembling

    @staticmethod
    def _finish(track: dict[str, Any], work_track: WorkTrack, *, parent: WorkTrack | None, source: dict[str, Any],
                fresh: dict[str, Any]) -> dict[str, Any]:
        """A shallow copy with the fields the build owns set; the cached adapter output is never mutated."""

        out = dict(track)
        reporting = out.pop("reporting", True) is not False
        if parent is None:
            out.update(id=work_track.id, title=work_track.title, kind="loop", parent=None,
                       registry=work_track.to_dict(), purpose=work_track.purpose,
                       children=list(work_track.children))
        else:
            out.update(kind="deployment", parent=parent.id)
        out["reporting"] = reporting
        out["source"] = {**source, **(out.get("source") if isinstance(out.get("source"), dict) else {})} \
            if reporting else {**source, "kind": "none", "live": False}
        # WHY no count derived here: needs.py is the one source of every Needs-you number. A top-level track gets its
        # fields from _apply_needs right after this; a child gets null/null from _child_needs. The old fallback
        # ("blocking" = "names a rung", open = list length) was the second source that disagreed with /needs.
        if parent is None:
            out["needs_you_count"] = {"open": None, "blocking": None}
            out["needs_you"] = []
        else:
            LiveBuilder._child_needs(out, parent)
        out["freshness"] = fresh
        state = dict(out.get("state") or {})
        if fresh.get("stale") and state.get("tone") in ("ok", "muted"):
            # WHY the build and not each adapter: "quiet past its stall rule" is one rule for every track, and an
            # adapter reading a file that stopped changing has no way to know that from the file alone.
            state["tone"] = "stale"
            state["detail"] = " · ".join(part for part in (state.get("detail"), fresh["note"]) if part)
        out["state"] = state
        return out

    def build(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            return self._build(force)

    def _build(self, force: bool) -> dict[str, Any]:
        now = self._clock()
        registry: Registry = read_registry(self.workspace)
        paths = self._sources()
        if force:
            self._tracks.clear()
            self._snapshot = None
        problems = [dict(problem) for problem in registry.problems]
        top: list[dict[str, Any]] = []
        children_out: list[dict[str, Any]] = []
        media: dict[str, Any] = {}
        pending: list[str] = []
        snapshot_used: str | None = None

        def add_media(entries: dict[str, Any], owner: str) -> None:
            for media_id, entry in entries.items():
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                    problems.append({"path": owner, "error": f"media {media_id!r} has no path; dropped"})
                elif media_id in media and media[media_id].get("path") != entry["path"]:
                    problems.append({"path": owner, "error": f"media id {media_id!r} is already another file; dropped"})
                else:
                    media[media_id] = entry

        live_ids = [track.id for track in registry.tracks if not track.archived]
        for track_id in list(self._tracks):
            if track_id not in live_ids:
                del self._tracks[track_id]
        for work_track in registry.tracks:
            if work_track.archived:
                continue
            declared = {key: paths[key] for key in work_track.sources if key in paths}
            for key in work_track.sources:
                if key not in paths:
                    problems.append({"path": Path(work_track.note_path).name, "error": f"vibe-sources key {key!r} is not in sources.py"})
            module, module_stamp, reason = self._module(work_track.adapter)
            depth = getattr(module, "DEPTH", None) or {}
            stamps = {key: source_stamp(path, int(depth.get(key, 1))) for key, path in declared.items()}
            work_track = replace(work_track, heartbeat=heartbeat_keys(work_track, module))
            key = (work_track.revision, work_track.adapter, module_stamp, reason, tuple(sorted(stamps.items())))
            cached = self._tracks.get(work_track.id)
            if cached is not None and cached[0] == key:
                track, adapter_children, track_media = cached[1], cached[2], cached[3]
            else:
                track, adapter_children, track_media = self._run(work_track, module, reason, declared)
                self._tracks[work_track.id] = (key, track, adapter_children, track_media)
            add_media(track_media, Path(work_track.note_path).name)
            heartbeat_stamps = {k: stamps[k] for k in work_track.heartbeat if k in stamps}
            fresh = freshness(work_track.heartbeat, paths, work_track.stall_hours, now, heartbeat_stamps)
            source = {"adapter": work_track.adapter, "kind": "live", "live": True}
            finished = self._finish(track, work_track, parent=None, source=source, fresh=fresh)
            self._apply_needs(finished, work_track, paths, problems)
            if not finished["reporting"]:
                pending.append(f"{work_track.id} ({finished['state'].get('detail') or 'not reporting'})")
            top.append(finished)

            by_id = {child.get("id"): child for child in adapter_children}
            for child_id in work_track.children:
                child_track = self._child(work_track, child_id)
                if child_id in by_id:
                    children_out.append(self._finish(by_id[child_id], child_track, parent=work_track, source=source, fresh=fresh))
                    continue
                snapshot_tracks, snapshot_media, snapshot_path, snapshot_at, snapshot_reason = self._snapshot_tracks()
                if child_id in snapshot_tracks:
                    snapshot_used = snapshot_path
                    child = snapshot_tracks[child_id]
                    add_media({mid: snapshot_media[mid] for mid in _media_ids(child) if mid in snapshot_media}, "bam_loops snapshot")
                    child_fresh = snapshot_freshness(snapshot_path, snapshot_at, work_track.stall_hours, now)
                    children_out.append(self._finish(
                        child, child_track, parent=work_track, fresh=child_fresh,
                        source={"adapter": "bam_loops", "kind": "snapshot", "live": False, "snapshot": snapshot_path}))
                else:
                    reason = snapshot_reason or f"the {work_track.adapter} adapter does not draw {child_id} yet"
                    children_out.append(self._finish(base.not_reporting(child_track, reason), child_track,
                                                     parent=work_track, source=source, fresh=fresh))

        generated = datetime.fromtimestamp(now).astimezone()
        return {
            "schema": "vibetracks-dashboard/1",
            "generated_at": generated.isoformat(timespec="seconds"),
            "as_of": generated.date().isoformat(),
            "source": {
                "adapter": "registry",
                "kind": "live",
                "live": True,
                "registry": str(registry.descriptor),
                "snapshot": snapshot_used,
                "snapshot_generated_at": None,
                "curriculum": None,
                "todo": ("not reporting: " + "; ".join(pending)) if pending else "",
                "units_note": None,
            },
            "registry": {
                "descriptor": str(registry.descriptor),
                "order": [track["id"] for track in top],
                "archived": [{"id": t.id, "title": t.title} for t in registry.tracks if t.archived],
                "problems": problems,
            },
            "tracks": top + children_out,
            "media": media,
        }


def build_live(workspace: str | os.PathLike[str], home: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """One live build, written to ``<data home>/projection.json`` as well (the CLI's path)."""

    builder = LiveBuilder(workspace, home)
    projection = builder.build()
    write_json_atomic(builder.home / "projection.json", projection)
    return projection


def stats(projection: dict) -> str:
    lines = []
    for track in projection["tracks"]:
        items = sum(len(v) for v in track["evidence"]["by_iteration"].values())
        lines.append(f"  {track['id']:<9} {track['kind']:<10} {len(track['iterations']):>2} iterations · {len(track['kpis']):>2} KPIs · "
                     f"{items:>3} evidence items · {len(track['needs_you'])} needs-you")
    kinds: dict[str, int] = {}
    for item in projection["media"].values():
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    lines.append("  media: " + ", ".join(f"{n} {kind}" for kind, n in sorted(kinds.items())))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Vibe Tracks dashboard projection.")
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE),
                        help=f"the folder whose .vtdash names the work-track registry (default {DEFAULT_WORKSPACE})")
    parser.add_argument("--data-home", help=f"default: $VIBETRACKS_DASHBOARD_HOME or {DEFAULT_HOME}")
    parser.add_argument("--snapshot", action="store_true", help="build the 2026-10-03 bam_loops snapshot instead of live")
    parser.add_argument("--refresh-sources", action="store_true", help="re-copy the snapshot and curriculum from their origins")
    args = parser.parse_args(argv)
    home = data_home(args.data_home)
    from .registry import find_registry
    if args.snapshot or find_registry(args.workspace) is None:
        projection = build(home, refresh=args.refresh_sources)
    else:
        if args.refresh_sources:
            seed_sources(home, refresh=True)
        projection = build_live(args.workspace, home)
    print(f"wrote {home / 'projection.json'}")
    print(stats(projection))
    return 0


if __name__ == "__main__":
    sys.exit(main())
