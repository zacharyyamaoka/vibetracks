"""Reading a cited evidence file and serving art PNGs without following a symlink, within fixed byte limits.

``read_evidence`` serves only a path its caller's allowlist holds (see ``vibetracks.roadmap.citations``), as a regular
file reached through no link; ``art_entries`` and ``read_art`` serve only lowercase ``.png`` regular files inside the
art directory.
"""

from __future__ import annotations

import errno
import os
import posixpath
import re
import stat
from collections.abc import Callable
from pathlib import Path

from ..errors import VibeTracksError


class RoadmapForbidden(VibeTracksError):
    """The caller asked for a file this module will not serve (a path nobody cited, a link, a non-regular file)."""


class RoadmapNotFound(VibeTracksError):
    """The caller asked for a file that does not exist (or an art name that no art file can have)."""


EVIDENCE_READ_LIMIT = 512 * 1024
#: How far ``read_evidence`` scans a file to number its lines: past it, a window's first line number is unknown.
EVIDENCE_SCAN_LIMIT = 64 * 1024 * 1024
#: Lines kept above a requested ``line`` when a file is too big to return whole.
EVIDENCE_CONTEXT_LINES = 40
#: The largest PNG ``read_art`` serves; a bigger one is refused (``RoadmapNotFound``) and never read (Codex audit A11).
ART_READ_LIMIT = 4 * 1024 * 1024
_ART_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*\.png")


def open_without_symlinks(path: str) -> int:
    """A read-only descriptor on the absolute ``path``, opened one component at a time from ``/`` without following a
    symlink at any of them. Raises the ``OSError`` of the first component that is missing (ENOENT), a symlink (ELOOP)
    or not a directory (ENOTDIR). ``path`` is a realpath-checked spelling: no ``.`` or ``..`` component.

    WHY a walk of directory descriptors (Codex audit A09): ``O_NOFOLLOW`` guards only the last component, so a parent
    directory swapped for a symlink between the realpath check and ``open(path)`` redirected the read. Opening each
    component ``O_NOFOLLOW`` from the descriptor of the one before resolves no name through a link, whenever it was
    swapped in.
    """

    *parents, leaf = [part for part in path.split("/") if part]
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for name in parents:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            os.close(directory)
            directory = child
        # O_NONBLOCK: opening a FIFO never waits for a writer (the caller refuses it by its type).
        return os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    finally:
        os.close(directory)


def is_within(root: str, candidate: str) -> bool:
    """Whether the absolute, already-resolved path ``candidate`` is ``root`` or lies under it."""

    return posixpath.commonpath([root, candidate]) == root



def evidence_text(window: bytes, *, truncated: bool) -> str:
    """The text ``read_evidence`` returns from the bytes it read.

    ``window`` is the whole file, or (``truncated``) its last ``EVIDENCE_READ_LIMIT`` bytes preceded by ONE more byte,
    the one before them. The first line of a truncated window is
    dropped unless that byte was a newline, so the text starts at a line boundary, never mid-line or mid-character.
    A window with no newline after its first byte has no line boundary to start at and is returned as read.
    Decoded as UTF-8 with ``errors="replace"``: a log's stray byte shows as U+FFFD, never hides the file.
    """

    if truncated:
        before, window = window[:1], window[1:]
        if before != b"\n":
            newline = window.find(b"\n")
            if newline != -1:
                window = window[newline + 1:]
    return window.decode("utf-8", errors="replace")


def evidence_window(read: Callable[[int, int], bytes], size: int, *, line: int | None = None) -> tuple[str, int | None, bool]:
    """``(text, first_line, truncated)``: what ``read_evidence`` returns of a ``size``-byte file read by ``read(n, at)``.

    A file within ``EVIDENCE_READ_LIMIT`` is returned whole from line 1. A bigger one is a window of at most that many
    bytes, starting on a line: around ``line`` (``EVIDENCE_CONTEXT_LINES`` above it) when one is asked for and exists,
    else the file's end, where acceptance logs put their verdict. ``first_line`` is the source line the text starts
    at, counted by scanning up to ``EVIDENCE_SCAN_LIMIT`` bytes, or None past it.

    WHY a true first line (Codex audit B09): a tail window numbered from 1 made a ``:188`` citation highlight whatever
    sat 188 lines into the tail, an unrelated line, while source line 188 was not in the window at all.
    """

    def newline_offsets(limit: int):
        at = 0
        while at < min(size, limit):
            chunk = read(min(1024 * 1024, min(size, limit) - at), at)
            if not chunk:
                return
            index = chunk.find(b"\n")
            while index != -1:
                yield at + index
                index = chunk.find(b"\n", index + 1)
            at += len(chunk)

    if size <= EVIDENCE_READ_LIMIT:
        return read(size, 0).decode("utf-8", errors="replace"), 1, False
    if line is not None and line >= 1:
        # Line starts from the first context line through the line after the cited one (its end).
        first = max(1, line - EVIDENCE_CONTEXT_LINES)
        starts = {1: 0} if first == 1 else {}
        for count, offset in enumerate(newline_offsets(EVIDENCE_SCAN_LIMIT), start=2):
            if count >= first:
                starts[count] = offset + 1
            if count > line:
                break
        if line in starts and starts[line] < size:
            end = starts.get(line + 1, size)
            if end - starts[line] >= EVIDENCE_READ_LIMIT:  # the cited line alone fills the window: show its start
                return read(EVIDENCE_READ_LIMIT, starts[line]).decode("utf-8", errors="replace"), line, True
            # WHY the context gives way to the cited line (Codex C04): 40 long lines above it could fill the window
            # and push the line itself out; the earliest start that still ends past the cited line wins.
            begin = next(number for number in range(first, line + 1) if number in starts and end - starts[number] <= EVIDENCE_READ_LIMIT)
            window = read(min(EVIDENCE_READ_LIMIT, size - starts[begin]), starts[begin])
            if starts[begin] + len(window) < size and b"\n" in window:
                window = window[: window.rfind(b"\n") + 1]
            return window.decode("utf-8", errors="replace"), begin, True
    # The end: the last EVIDENCE_READ_LIMIT bytes, plus the byte before them, which says whether they start a line.
    offset = size - EVIDENCE_READ_LIMIT - 1
    raw = read(EVIDENCE_READ_LIMIT + 1, offset)
    before, window, start = raw[:1], raw[1:], offset + 1
    if before != b"\n" and b"\n" in window:
        cut = window.find(b"\n") + 1
        window, start = window[cut:], start + cut
    text = window.decode("utf-8", errors="replace")
    if start > EVIDENCE_SCAN_LIMIT:
        return text, None, True
    return text, 1 + sum(1 for _ in newline_offsets(start)), True


def evidence_snapshot(stat: Callable[[], tuple[int, int]], read: Callable[[int, int], bytes], *, line: int | None = None,
                      attempts: int = 3) -> tuple[int, str, int | None, bool]:
    """``(size, text, first_line, truncated)`` of a file that may change while it is read; ``stat()`` is (size, mtime_ns).

    WHY re-stat after reading (Codex audit C05): a log truncated between reading its tail and counting the lines before
    it paired old text with the new file's line numbers. A snapshot whose size and mtime held across the read is
    consistent; after ``attempts`` changing reads the text is still served, but no line number is claimed for it.
    """

    for _ in range(attempts):
        size, stamp = stat()
        text, first_line, truncated = evidence_window(read, size, line=line)
        if stat() == (size, stamp):
            return size, text, first_line, truncated
    return size, text, None, truncated


def line_count(text: str) -> int:
    """The number of lines in ``text``: newlines, plus one for an unterminated last line."""

    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def is_art_name(name: str) -> bool:
    """A file name ``read_art`` serves: lowercase, one path segment, ``.png``."""

    return bool(_ART_NAME.fullmatch(name))


def read_evidence(path: str, allowlist: frozenset[str], line: int | None = None) -> dict:
    """A file the caller's ``allowlist`` cites, read without following a symlink; at most 512 KiB of it.

    A bigger file is a window starting on a line: around ``line`` when one is asked for, else its end; the
    response's ``first_line`` is the source line the text starts at (``evidence_window``). The response is
    ``{path, size, mtime, lines, first_line, truncated, text}``.

    Raises ``RoadmapForbidden`` for a path ``allowlist`` does not hold verbatim, one that resolves elsewhere (a symlink
    at it or above it), and anything not a regular file; ``RoadmapNotFound`` for a cited path that does not exist.
    WHY the realpath must BE the cited spelling, and the open walks the path ``O_NOFOLLOW`` and is checked on its
    descriptor (the kinsim dashboard's write-path hardening, ported): a cited log replaced by a symlink to
    ``~/.ssh/id_ed25519`` must not be read through, and a check on the name alone can be swapped between the check
    and the open. The realpath check is the fast refusal; ``open_without_symlinks`` is what holds when a component
    (the file or any directory above it) is swapped for a link after it, and the descriptor's own (st_dev, st_ino)
    must also be the file the cited name resolves to after the open.
    """

    if path not in allowlist:
        raise RoadmapForbidden(f"{path!r} is not an evidence file anything cites")
    if os.path.realpath(path) != path:
        raise RoadmapForbidden(f"{path} resolves to {os.path.realpath(path)}, not to the cited path itself")
    try:
        descriptor = open_without_symlinks(path)
    except FileNotFoundError as error:
        raise RoadmapNotFound(f"cited evidence {path} (it does not exist)") from error
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise RoadmapForbidden(f"cited evidence {path} has a symlink or a non-directory on its path") from error
        raise RoadmapForbidden(f"cited evidence {path} cannot be read: {os.strerror(error.errno)}") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RoadmapForbidden(f"cited evidence {path} is not a regular file")
        try:
            named = os.stat(path, follow_symlinks=False)
        except OSError as error:
            raise RoadmapNotFound(f"cited evidence {path} (it was removed while being opened)") from error
        if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
            raise RoadmapForbidden(f"cited evidence {path} was replaced while being opened")

        def read(count: int, at: int) -> bytes:
            chunks, done = [], 0
            while done < count:
                chunk = os.pread(descriptor, count - done, at + done)
                if not chunk:  # the file shrank while being read: serve what was there
                    break
                chunks.append(chunk)
                done += len(chunk)
            return b"".join(chunks)

        def stat_now() -> tuple[int, int]:
            now = os.fstat(descriptor)
            return now.st_size, now.st_mtime_ns

        size, text, first_line, truncated = evidence_snapshot(stat_now, read, line=line)
        info = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    return {"path": path, "size": size, "mtime": info.st_mtime, "lines": line_count(text),
            "first_line": first_line, "truncated": truncated, "text": text}


def art_entries(art_dir: Path) -> dict:
    """The sorted names ``read_art`` serves; ``missing`` names the directory when it does not exist.

    WHY only the names a fetch would serve (lowercase ``.png``, a regular file, not a symlink, within
    ``ART_READ_LIMIT``): the page builds one
    ``<img>`` per entry, and a listed name that 404s would be a broken image, not a missing one.
    """

    try:
        names = os.listdir(art_dir)
    except (FileNotFoundError, NotADirectoryError):
        return {"entries": [], "missing": str(art_dir)}
    entries = []
    for name in names:
        if not is_art_name(name):
            continue
        try:
            info = os.stat(art_dir / name, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_size <= ART_READ_LIMIT:
            entries.append(name)
    return {"entries": sorted(entries)}


def read_art(art_dir: Path, name: str) -> bytes:
    """The bytes of ``<art dir>/<name>``; ``RoadmapNotFound`` for a bad name or anything but a regular file inside.

    WHY opened from the art directory's own descriptor with ``O_NOFOLLOW`` and checked by realpath too (the kinsim
    dashboard's write-path hardening, ported): ``is_art_name`` already makes the name one segment, so the
    kernel refuses a symlink at it (ELOOP), the descriptor's type refuses a FIFO or a directory, and the realpath
    check pins that what was opened lies inside the art directory however that directory is itself reached.
    WHY a size cap read from the descriptor (Codex audit A11): the whole file is held in memory to be sent, so one
    over ``ART_READ_LIMIT`` is refused unread, and the read stops one byte past the admitted size; a file
    that grew past it while being read is refused too, never served cut short.
    """

    if not is_art_name(name):
        raise RoadmapNotFound(f"art {name!r} (names are lowercase [a-z0-9_.-] ending in .png)")
    try:
        directory = os.open(art_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as error:
        raise RoadmapNotFound(f"art {name} (the art directory {art_dir} cannot be opened)") from error
    try:
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
        except OSError as error:
            raise RoadmapNotFound(f"art {name} ({os.strerror(error.errno)})") from error
        try:
            info = os.fstat(descriptor)
            real = os.path.realpath(art_dir / name)
            if not stat.S_ISREG(info.st_mode) or not is_within(os.path.realpath(art_dir), real):
                raise RoadmapNotFound(f"art {name} (not a regular file inside {art_dir})")
            if info.st_size > ART_READ_LIMIT:
                raise RoadmapNotFound(f"art {name} ({info.st_size} bytes, over the {ART_READ_LIMIT}-byte limit)")
            chunks, read = [], 0
            while read <= info.st_size and (chunk := os.read(descriptor, info.st_size + 1 - read)):
                chunks.append(chunk)
                read += len(chunk)
            if read > info.st_size:
                raise RoadmapNotFound(f"art {name} (it grew while being read)")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
