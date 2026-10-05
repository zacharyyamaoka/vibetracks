"""Open a file by a canonical path without following a symlink at ANY component.

    fd = open_no_symlinks("/home/bam/repo/reports/run.html")   # -> an fd on a regular file, or UnsafePath

WHY walk the path one component at a time with ``dir_fd`` (audit 2026-10-05, finding 2): ``O_NOFOLLOW`` guards only
the LAST component. A served file is checked by its canonical path (``os.path.realpath``) and then opened; if a parent
directory is swapped for a symlink between the check and the open, a plain ``os.open(path, O_NOFOLLOW)`` follows that
parent link and streams a file nobody listed, with the listed file's content type (``/proc/self/root/...`` is the
same thing standing still: ``self`` is a symlink). Opening each directory with ``O_NOFOLLOW | O_DIRECTORY`` relative to
the one before closes that gap: every component is checked by the kernel at the moment it is traversed.

WHY refusing every symlink is correct, not over-strict: callers pass the target they recorded as ``realpath`` when
they built their allowlist, so a legitimate canonical path holds no symlink at all; one seen at open time is a
substitution. Linux ``openat2(RESOLVE_NO_SYMLINKS)`` does the same in one call, but the stdlib has no binding for it.

Stdlib only; POSIX only (``dir_fd`` support). A path that is not already canonical (relative, ``.``/``..``/empty
components, a trailing slash) is refused rather than normalised: the caller must open exactly what it recorded.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat

__all__ = ["UnsafePath", "open_no_symlinks"]


class UnsafePath(OSError):
    """The path is not a canonical path to a regular file reachable without a symlink (``errno`` says which way)."""


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
#: WHY O_NONBLOCK on the final open: a FIFO swapped in for the file would otherwise block the open forever, before the
#: fstat below can refuse it. It is cleared again once the fd is known to be a regular file.
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK | getattr(os, "O_NOCTTY", 0)


def _components(canonical_path: str) -> list[str]:
    if not isinstance(canonical_path, str) or not canonical_path.startswith("/"):
        raise UnsafePath(errno.EINVAL, "not an absolute path", canonical_path)
    if "\x00" in canonical_path:
        raise UnsafePath(errno.EINVAL, "path holds a NUL byte", canonical_path)
    parts = canonical_path[1:].split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise UnsafePath(errno.EINVAL, "not a canonical path (empty, '.' or '..' component)", canonical_path)
    return parts


def open_no_symlinks(canonical_path: str) -> int:
    """An fd (``O_RDONLY``, close-on-exec) on the regular file at ``canonical_path``, or ``UnsafePath``.

    Every directory on the way is opened with ``O_NOFOLLOW | O_DIRECTORY`` relative to its parent's fd, and the file
    with ``O_NOFOLLOW``: a symlink at any component fails with ``ELOOP`` (or ``ENOTDIR``) and becomes ``UnsafePath``.
    The opened file must be a regular file (``fstat``: ``S_ISREG``). The caller owns the returned fd.
    """
    parts = _components(canonical_path)
    parent = os.open("/", _DIR_FLAGS)
    try:
        for name in parts[:-1]:
            try:
                child = os.open(name, _DIR_FLAGS, dir_fd=parent)
            except OSError as error:
                _refuse_substitution(error, canonical_path, name)
                raise
            os.close(parent)
            parent = child
        try:
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
        except OSError as error:
            _refuse_substitution(error, canonical_path, parts[-1])
            raise
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafePath(errno.EINVAL, "not a regular file", canonical_path)
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _refuse_substitution(error: OSError, path: str, component: str) -> None:
    """Raise ``UnsafePath`` when ``error`` means a symlink sat at ``component``; otherwise return, and the caller
    re-raises the plain error (ENOENT, EACCES, ...) so "gone" stays distinguishable from "substituted"."""
    if error.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
        raise UnsafePath(error.errno, f"a symlink (or non-directory) at component {component!r}", path) from error
