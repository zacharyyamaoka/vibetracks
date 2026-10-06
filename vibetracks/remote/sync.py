"""Mirror a machine's loop files into the share and sync it: ``python3 -m vibetracks.remote.sync --config <file.json> [--once]``.

The config (JSON)::

    {"host": "win-a", "share": "C:/Users/BAM/vt-share", "interval_s": 3, "heartbeat_s": 300, "max_file_bytes": 5000000,
     "mirror": [{"key": "kinsim_events", "path": "~/.local/share/bam_curriculum/loop_events.jsonl"},
                {"key": "rig_loop_dir", "path": "D:/rig/loop", "include": ["*.json", "*.jsonl"]}]}

Each round (``sync_once``): copy the changed files into ``hosts/<host>/files/<key>/`` (``shutil.copy2``, which keeps
the worker's mtime), rewrite ``sources.json`` and the ``host.json`` heartbeat, commit ``hosts/<host>/`` only, then
``git pull --rebase`` and ``git push``. The agents on the machine keep writing their own files exactly as before; this
process only reads them.

``pull_and_restore`` is the receiving half (the hub calls it too): after a pull, every changed file's mtime is set to
the author time of the last commit that touched it. WHY: a checkout stamps files with the pull time, and the
dashboard's freshness/stall rule reads mtime, so a loop that stopped yesterday would look alive on every pull. The
commit's author date is the worker's newest write time (set here at commit), so it carries the real time across.
"""

from __future__ import annotations

import argparse
import filecmp
import fnmatch
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from . import share as layout

DEFAULTS = {"interval_s": 3, "heartbeat_s": 300, "max_file_bytes": 5_000_000}
PUSH_ATTEMPTS = 3
GIT_TIMEOUT_S = 120


class SyncError(RuntimeError):
    """A git step failed; nothing local was discarded."""


# --------------------------------------------------------------------------------------------- git


def _git(share: str | os.PathLike[str], *args: str, env: dict[str, str] | None = None, check: bool = True,
         stdin: str | None = None) -> subprocess.CompletedProcess:
    # WHY GIT_TERMINAL_PROMPT=0: an unattended loop must fail on missing credentials, never hang on a prompt.
    full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    try:
        result = subprocess.run(["git", "-C", str(share), *args], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=full_env, input=stdin, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as error:
        raise SyncError(f"git {args[0]}: {error}") from error
    if check and result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip()).splitlines()
        raise SyncError(f"git {' '.join(args[:2])}: {' / '.join(detail[-3:]) or f'exit {result.returncode}'}")
    return result


def _head(share: Path) -> str | None:
    result = _git(share, "rev-parse", "--verify", "-q", "HEAD", check=False)
    return result.stdout.strip() or None


def _upstream(share: Path) -> str | None:
    result = _git(share, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _ahead(share: Path) -> int:
    result = _git(share, "rev-list", "--count", "@{u}..HEAD", check=False)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _rebasing(share: Path) -> bool:
    git_dir = Path(_git(share, "rev-parse", "--absolute-git-dir").stdout.strip())
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def _names(output: str) -> list[str]:
    return [name for name in output.split("\0") if name]


def last_author_times(share: str | os.PathLike[str], paths: Iterable[str], rev: str = "HEAD") -> dict[str, int]:
    """{path: author time (epoch s) of the last commit at or before ``rev`` that touched it}, one ``git log`` pass.

    Reads the log newest first and stops as soon as every path is found, so a recent change costs a few commits of
    history however long the share has run.
    """

    wanted = set(paths)
    found: dict[str, int] = {}
    if not wanted:
        return found
    process = subprocess.Popen(["git", "-C", str(share), "log", "--format=%x01%at", "--name-only", "-z", rev],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    current: int | None = None
    pending = b""
    try:
        assert process.stdout is not None
        while len(found) < len(wanted):
            chunk = process.stdout.read(65536)
            if not chunk:
                break
            tokens = (pending + chunk).split(b"\0")
            pending = tokens.pop()
            for token in tokens:
                text = token.decode("utf-8", "surrogateescape").lstrip("\n")
                if text.startswith("\x01"):
                    current = int(text[1:].strip() or 0)
                elif text and current is not None and text in wanted and text not in found:
                    found[text] = current
    finally:
        process.kill()
        process.wait()
    return found


def restore_mtimes(share: str | os.PathLike[str], paths: Iterable[str], rev: str = "HEAD") -> int:
    """Set each existing path's mtime to the author time of its last commit; returns how many were set.

    The same job as MestreLion's ``git-restore-mtime`` (git-tools), limited to the paths a pull changed.
    """

    share = Path(share)
    times = last_author_times(share, paths, rev)
    restored = 0
    for path, when in times.items():
        full = share / path
        try:
            if full.is_file():
                os.utime(full, (when, when))
                restored += 1
        except OSError:
            continue
    return restored


def tracked_files(share: str | os.PathLike[str]) -> list[str]:
    return _names(_git(share, "ls-files", "-z").stdout)


def pull_and_restore(share: str | os.PathLike[str]) -> list[str]:
    """Pull (fast-forward, or rebase when there are local commits), restore the mtimes of what changed, return the
    changed repo-relative paths. Raises ``SyncError`` on failure, with a conflicted rebase already aborted."""

    share = Path(share)
    if _upstream(share) is None:
        return []
    old = _head(share)
    if old is not None and _ahead(share) > 0:
        # WHY --autostash: the session hook writes cards into this clone at any moment, and a dirty tracked file
        # would otherwise make every pull refuse until the next commit.
        result = _git(share, "pull", "-q", "--rebase", "--autostash", check=False)
        if result.returncode != 0:
            if _rebasing(share):
                _git(share, "rebase", "--abort", check=False)
            detail = (result.stderr.strip() or result.stdout.strip()).splitlines()
            raise SyncError("git pull --rebase failed and was aborted (local commits kept): "
                            + " / ".join(detail[-3:]))
    else:
        _git(share, "pull", "-q", "--ff-only")
    new = _head(share)
    if new is None or new == old:
        return []
    if old is None:
        changed = tracked_files(share)
    else:
        changed = _names(_git(share, "diff", "--name-only", "-z", old, new).stdout)
    restore_mtimes(share, [path for path in changed if (share / path).is_file()], new)
    return changed


# --------------------------------------------------------------------------------------------- mirroring


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return config


def _settings(config: dict[str, Any]) -> dict[str, Any]:
    out = {**DEFAULTS, **config}
    for key in ("host", "share"):
        if not isinstance(out.get(key), str) or not out[key]:
            raise ValueError(f"config needs a non-empty {key!r}")
    layout.host_dir(out["share"], out["host"])  # validates the host name
    if not isinstance(out.get("mirror", []), list):
        raise ValueError("config 'mirror' must be a list")
    return out


def _included(relative: str, include: list[str] | None) -> bool:
    if not include:
        return True
    name = relative.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(name, pattern) for pattern in include)


def _source_files(source: Path, include: list[str] | None) -> dict[str, Path]:
    """{path relative to the mirror folder: source file} for a file or a directory tree."""

    if source.is_file():
        return {source.name: source}
    files: dict[str, Path] = {}
    for folder, dirs, names in os.walk(source):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for name in sorted(names):
            full = Path(folder) / name
            relative = full.relative_to(source).as_posix()
            if _included(relative, include) and full.is_file():
                files[relative] = full
    return files


def _same(source: Path, dest: Path, source_stat: os.stat_result) -> bool:
    try:
        dest_stat = dest.stat()
    except OSError:
        return False
    if dest_stat.st_size != source_stat.st_size:
        return False
    if dest_stat.st_mtime_ns == source_stat.st_mtime_ns:
        return True
    if filecmp.cmp(source, dest, shallow=False):
        # WHY fix the stamp and call it unchanged: a rebase rewrites this clone's own files with the pull time, and a
        # byte-identical copy is not news (it would cost a heartbeat commit after every pull).
        os.utime(dest, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        return True
    return False


def _prune(root: Path, keep: set[str]) -> int:
    removed = 0
    if not root.is_dir():
        return 0
    for folder, dirs, names in os.walk(root, topdown=False):
        for name in names:
            full = Path(folder) / name
            if full.relative_to(root).as_posix() not in keep:
                full.unlink()
                removed += 1
        for name in dirs:
            try:
                (Path(folder) / name).rmdir()
            except OSError:
                pass
    return removed


def mirror(settings: dict[str, Any]) -> dict[str, Any]:
    """Copy the configured files into the host folder; returns what changed and what host.json should say."""

    base = layout.host_dir(settings["share"], settings["host"])
    files_root = base / layout.FILES
    limit = int(settings["max_file_bytes"])
    mirrors: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    errors: list[str] = []
    sources: dict[str, str] = {}
    copied: list[str] = []
    removed = 0
    keys: set[str] = set()
    previous = layout.read_json(base / layout.SOURCES_JSON)
    previous = previous if isinstance(previous, dict) else {}
    for entry in settings.get("mirror", []):
        key = entry.get("key") if isinstance(entry, dict) else None
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(key, str) or not layout.NAME.match(key) or not isinstance(path, str):
            skipped.append({"key": str(key), "path": str(path), "reason": "bad mirror entry (needs key and path)"})
            continue
        keys.add(key)
        source = Path(path).expanduser()
        dest_root = files_root / key
        if not source.exists():
            # WHY keep the old copy: a drive that is briefly unmounted must not erase the hub's last good reading.
            skipped.append({"key": key, "path": str(source), "reason": "missing on this machine"})
            if dest_root.exists() and isinstance(previous.get(key), str):
                sources[key] = previous[key]
            continue
        try:
            wanted = _source_files(source, entry.get("include"))
        except OSError as error:
            errors.append(f"{key}: {error}")
            continue
        sources[key] = (Path(layout.FILES) / key / source.name).as_posix() if source.is_file() \
            else (Path(layout.FILES) / key).as_posix()
        keep: set[str] = set()
        for relative, file in wanted.items():
            try:
                info = file.stat()
                if info.st_size > limit:
                    skipped.append({"key": key, "path": str(file),
                                    "reason": f"{info.st_size} bytes is over max_file_bytes {limit}"})
                    continue
                dest = dest_root / relative
                keep.add(relative)
                if not _same(file, dest, info):
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, dest)
                    copied.append(f"{key}/{relative}")
                mirrors.append({"key": key, "path": (Path(layout.FILES) / key / relative).as_posix(),
                                "bytes": info.st_size, "mtime": layout.iso_utc(info.st_mtime)})
            except OSError as error:
                errors.append(f"{key}/{relative}: {error}")
        try:
            removed += _prune(dest_root, keep)
        except OSError as error:
            errors.append(f"{key}: prune: {error}")
    if files_root.is_dir():
        for stale in files_root.iterdir():
            if stale.name not in keys:
                # a key dropped from the config stops being shared
                shutil.rmtree(stale, ignore_errors=True) if stale.is_dir() else stale.unlink()
                removed += 1
    sources_changed = layout.write_json_if_changed(base / layout.SOURCES_JSON, sources)
    return {"copied": copied, "removed": removed, "mirrors": mirrors, "skipped": skipped,
            "error": "; ".join(errors) or None, "sources_changed": sources_changed}


def heartbeat(settings: dict[str, Any], mirrored: dict[str, Any], now: float, force: bool) -> bool:
    """Rewrite host.json when ``force`` (something changed), its content would differ, or heartbeat_s has elapsed."""

    path = layout.host_dir(settings["share"], settings["host"]) / layout.HOST_JSON
    payload = {
        "host": settings["host"],
        "platform": platform.platform(),
        "python": platform.python_version(),
        "vt_sync_version": layout.VT_SYNC_VERSION,
        "last_sync": layout.iso_utc(now),
        "interval_s": settings["interval_s"],
        "mirrors": mirrored["mirrors"],
        "skipped": mirrored["skipped"],
        "error": mirrored["error"],
    }
    existing = layout.read_json(path)
    if isinstance(existing, dict) and not force:
        last = layout.parse_iso(existing.get("last_sync"))
        same = {k: v for k, v in existing.items() if k != "last_sync"} == \
            json.loads(json.dumps({k: v for k, v in payload.items() if k != "last_sync"}))
        if same and last is not None and now - last < float(settings["heartbeat_s"]):
            return False
    layout.write_json_atomic(path, payload)
    return True


def _commit(settings: dict[str, Any], share: Path, host_rel: str) -> bool:
    if not _git(share, "status", "--porcelain", "-z", "--", host_rel).stdout.strip("\0"):
        return False
    _git(share, "add", "--", host_rel)
    staged = _names(_git(share, "diff", "--cached", "--name-only", "-z", "--", host_rel).stdout)
    if not staged:
        return False
    # WHY the newest mirrored file and not now: the hub restores mtimes from the author date, and freshness must
    # read when the worker wrote its loop file. host.json, sources.json and session cards are written now by this
    # machine's own bookkeeping; counting them would stamp every loop file in the commit as just written.
    newest = None
    for name in staged:
        if not name.startswith(f"{host_rel}/{layout.FILES}/"):
            continue
        try:
            stamp = (share / name).stat().st_mtime
        except OSError:
            continue  # a deletion
        newest = stamp if newest is None else max(newest, stamp)
    env = {"GIT_AUTHOR_DATE": f"{int(newest)} +0000"} if newest is not None else None
    host = settings["host"]
    message = f"vt-sync {host}: {len(staged)} files\n\nVibe-Host: {host}\n"
    _git(share, "commit", "-q", "--no-verify", "-F", "-", "--", host_rel, env=env, stdin=message)
    return True


def _push(share: Path) -> bool:
    upstream = _upstream(share)
    if upstream is None:
        _git(share, "push", "-q", "-u", "origin", "HEAD")
        return True
    if _ahead(share) == 0:
        return False
    remote, _, branch = upstream.partition("/")
    _git(share, "push", "-q", remote, f"HEAD:{branch}")
    return True


def sync_once(config: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """One round: mirror, heartbeat, commit, pull --rebase, push. Never raises for a git problem; returns
    ``{"committed", "pushed", "pulled", "error"}`` plus ``copied`` (what this round copied, for the log line)."""

    settings = _settings(config)
    share = Path(settings["share"])
    host_rel = f"{layout.HOSTS}/{settings['host']}"
    result: dict[str, Any] = {"committed": False, "pushed": False, "pulled": [], "error": None, "copied": []}
    try:
        mirrored = mirror(settings)
        result["copied"] = mirrored["copied"]
        changed = bool(mirrored["copied"] or mirrored["removed"] or mirrored["sources_changed"])
        heartbeat(settings, mirrored, time.time() if now is None else now, changed)
        result["committed"] = _commit(settings, share, host_rel)
        result["pulled"] = pull_and_restore(share)
        for attempt in range(PUSH_ATTEMPTS):
            try:
                result["pushed"] = _push(share)
                break
            except SyncError:
                # WHY retry through a pull: another machine pushed between our pull and our push (non-fast-forward).
                if attempt == PUSH_ATTEMPTS - 1:
                    raise
                result["pulled"] += pull_and_restore(share)
    except (SyncError, OSError, ValueError) as error:
        result["error"] = str(error)
    return result


# --------------------------------------------------------------------------------------------- the loop


def _log(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def run_loop(config: dict[str, Any]) -> None:
    settings = _settings(config)
    interval = float(settings["interval_s"])
    backoff = interval
    while True:
        result = sync_once(config)
        if result["error"]:
            _log(f"error: {result['error']} (retrying in {backoff:g} s)")
            time.sleep(backoff)
            backoff = min(backoff * 2, 300.0)  # WHY back off: a dead network must not spin git every 3 s
            continue
        backoff = interval
        if result["copied"] or result["committed"] or result["pulled"]:
            parts = []
            if result["copied"]:
                parts.append(f"copied {', '.join(result['copied'][:5])}"
                             + (f" (+{len(result['copied']) - 5})" if len(result["copied"]) > 5 else ""))
            if result["committed"]:
                parts.append("committed" + (" + pushed" if result["pushed"] else ""))
            if result["pulled"]:
                parts.append(f"pulled {len(result['pulled'])} files")
            _log(" · ".join(parts))
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mirror this machine's loop files into the Vibe Tracks share.")
    parser.add_argument("--config", required=True, help="the JSON config (see the module docstring)")
    parser.add_argument("--once", action="store_true", help="one round, then exit (nonzero on error)")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.once:
        result = sync_once(config)
        print(json.dumps({k: result[k] for k in ("committed", "pushed", "pulled", "error")}), flush=True)
        return 1 if result["error"] else 0
    try:
        run_loop(config)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
