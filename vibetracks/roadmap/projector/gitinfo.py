"""Read-only git queries the projection rests on: the head, ancestry, and what changed since.

Every call is ``git -C <checkout> ...`` with a timeout, and every answer is cached per
checkout, because one projection asks the same ancestry question for dozens of evidence items.
Nothing here writes to the repository: no fetch, no checkout, no stash (peer sessions share
the index and the stash stack).
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

GIT_TIMEOUT_S = 30


@lru_cache(maxsize=4096)
def _git(checkout: str, *arguments: str) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", "-C", checkout, *arguments],
            capture_output=True, text=True, errors="replace", timeout=GIT_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    return completed.returncode, completed.stdout


def clear_cache() -> None:
    """Forget cached answers (a test that commits between two projections needs this)."""

    _git.cache_clear()


class Repo:
    """One checkout (a main clone or a worktree) and the head the projection is judged at."""

    def __init__(self, checkout: Path, head: str | None = None) -> None:
        self.checkout = str(checkout)
        code, top = _git(self.checkout, "rev-parse", "--show-toplevel")
        self.root = Path(top.strip()) if code == 0 and top.strip() else None
        self.head = self.full_sha(head or "HEAD") if self.root else None
        code, branch = _git(self.checkout, "rev-parse", "--abbrev-ref", "HEAD")
        self.branch = branch.strip() if code == 0 else None

    @property
    def available(self) -> bool:
        return self.root is not None and self.head is not None

    def full_sha(self, commit: str | None) -> str | None:
        """The full sha a short one names, or None when this repository does not know it."""

        if not commit:
            return None
        code, out = _git(self.checkout, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
        return out.strip() if code == 0 and out.strip() else None

    def in_history(self, commit: str | None) -> bool | None:
        """True when ``commit`` is the head or one of its ancestors; False when it is not; None when unknown."""

        if not self.available or not commit:
            return None
        full = self.full_sha(commit)
        if full is None:
            return False
        code, _out = _git(self.checkout, "merge-base", "--is-ancestor", full, self.head)
        return code == 0

    def changed_since(self, commit: str | None, paths: tuple[str, ...]) -> list[str]:
        """``"<short sha> <subject>"`` of each commit after ``commit`` (up to the head) that touched ``paths``.

        Only repository-relative paths are asked about; an absolute path outside this
        checkout belongs to another repository and has no history here.
        """

        relative = tuple(path for path in paths if path and not path.startswith("/"))
        if not self.available or not commit or not relative:
            return []
        full = self.full_sha(commit)
        if full is None:
            return []
        # WHY from the root: a pathspec is read relative to -C, and these paths are repository-relative.
        # WHY Markdown is excluded: a ROADMAP or README edit changes no behaviour a test could have proven.
        code, out = _git(str(self.root), "log", "--format=%h %s", "-n", "5", f"{full}..{self.head}", "--",
                         *relative, ":(exclude,glob)**/*.md")
        return [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []

    def show(self, commit: str | None, path: str) -> str | None:
        """A file's text as it was at ``commit`` (None when the commit or the path is unknown there)."""

        if not self.available or not commit:
            return None
        code, out = _git(str(self.root), "show", f"{commit}:{path}")
        return out if code == 0 else None

    def other_checkouts(self) -> tuple[Path, ...]:
        """Every other checkout of this repository (the main clone and its worktrees)."""

        if not self.available:
            return ()
        code, out = _git(self.checkout, "worktree", "list", "--porcelain")
        paths = [Path(line.split(" ", 1)[1]) for line in out.splitlines() if line.startswith("worktree ")] if code == 0 else []
        return tuple(path for path in paths if path != self.root)

    def tracked_files(self) -> tuple[str, ...]:
        if not self.available:
            return ()
        # WHY from the root: ls-files run inside a subfolder lists only that subfolder.
        code, out = _git(str(self.root), "ls-files")
        return tuple(out.splitlines()) if code == 0 else ()

    def short(self, commit: str | None) -> str | None:
        return commit[:8] if commit else None
