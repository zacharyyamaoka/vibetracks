"""Projects as Codex models them: a name and 1..N source folders (Zach, Oct 6 "Project = Codex model"; Oct 9).

    from vibetracks.home.projects import read_projects
    read_projects("/home/bam/vibetracks/workspace")["BAM Robotics"].roots   # ['/home/bam/bam_ws', ...]

A project IS a small descriptor file, the existing ``.vibetrack`` shape, in ``workspace/projects/``:

    vibetracks:
      version: 1
      kind: project
      name: BAM Robotics                    # optional with ONE root: the name is then that folder's name
      roots: [/home/bam/bam_ws, /home/bam/clank-workbench, /home/bam/viser-3d-viewer]
      north-star:                           # optional; the project's lagging measure as a POINTER, never a value
        milestone-of: rig                   #   the roadmap milestone of that track's loop (title, due, state), or
        kpi: pyblocks/runnable_green        #   a track's projected KPI series (track id / KPI id)

Session -> project (``Project.owns``): a session belongs to a project when its cwd is under ANY of the project's
roots. ``<root>/.claude/worktrees/...`` is under the root by path; a git worktree checked out elsewhere
(``/home/bam/vibetracks-home``) counts as its main checkout's folder, read from its ``.git`` file. A folder may sit in
more than one project: an unpinned session shows under each, until a track's join pins it to that track's project.

WHY a pointer and never a number for the north star: the home derives, it never claims (docs/peps/0001). A north star
with no pointer, or one that resolves to nothing measured, reads "unknown" on the project page.
WHY the descriptors live in this workspace and not inside each root: the roots are other repos (bam_ws, pyblocks);
writing there is their owners' call. Moving each file into one of its roots changes only where this module globs.
Stdlib + PyYAML (already a dependency of descriptor.py).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..activity.join import _under

PROJECTS_DIR = "projects"
SUFFIX = ".vibetrack"


def slug(name: str) -> str:
    return re.sub(r"-+", "-", "".join(ch if ch.isalnum() else "-" for ch in name.casefold())).strip("-") or "project"


@dataclass
class Project:
    name: str
    roots: list[str]
    north_star: dict[str, Any] | None
    path: str
    problems: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return slug(self.name)

    def owns(self, cwd: str | None) -> str | None:
        """The root ``cwd`` is under (the longest), also through its git worktree's main checkout; else None."""

        if not cwd:
            return None
        for candidate in (cwd, main_checkout(cwd)):
            if not candidate:
                continue
            best = None
            for root in self.roots:
                if _under(candidate, root) and (best is None or len(root) > len(best)):
                    best = root
            if best:
                return best
        return None


_MAIN: dict[str, str | None] = {}


def main_checkout(cwd: str) -> str | None:
    """The main checkout of the git worktree holding ``cwd`` (its ``.git`` is a FILE naming
    ``<main>/.git/worktrees/<name>``), mapped to the same relative path inside it; None when ``cwd`` is not inside
    such a worktree. Cached per cwd (a worktree does not move its main checkout)."""

    if cwd in _MAIN:
        return _MAIN[cwd]
    found = None
    path = Path(cwd)
    for parent in [path, *path.parents]:
        dot_git = parent / ".git"
        try:
            if dot_git.is_dir():
                break
            if dot_git.is_file():
                text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
                match = re.match(r"gitdir:\s*(.+)", text)
                if match:
                    gitdir = Path(match.group(1).strip())
                    if not gitdir.is_absolute():
                        gitdir = (parent / gitdir).resolve()
                    parts = gitdir.parts
                    if ".git" in parts and "worktrees" in parts:
                        main = Path(*parts[: parts.index(".git")])
                        found = str(main / path.relative_to(parent)) if path != parent else str(main)
                break
        except OSError:
            break
    if len(_MAIN) > 4096:
        _MAIN.clear()
    _MAIN[cwd] = found
    return found


def _stamp(workspace: Path) -> tuple:
    out = []
    for path in sorted((workspace / PROJECTS_DIR).glob(f"*{SUFFIX}")):
        try:
            info = path.stat()
            out.append((str(path), info.st_mtime_ns, info.st_size))
        except OSError:
            out.append((str(path), None, None))
    return tuple(out)


_CACHE: dict[str, tuple[tuple, tuple[dict[str, Project], list[dict[str, str]]]]] = {}


def parse_project(path: Path) -> tuple[Project | None, str | None]:
    """One descriptor file, or (None, why not)."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        return None, f"not readable YAML: {error}"
    block = raw.get("vibetracks") if isinstance(raw, dict) else None
    if not isinstance(block, dict) or str(block.get("kind", "")) != "project":
        return None, "no vibetracks: block with kind: project"
    roots_raw = block.get("roots")
    roots = [str(r) for r in roots_raw] if isinstance(roots_raw, list) else [str(roots_raw)] if isinstance(roots_raw, str) else []
    roots = [os.path.expanduser(r.strip()).rstrip("/") or "/" for r in roots if str(r).strip()]
    if not roots:
        return None, "a project needs at least one root"
    name = block.get("name")
    name = str(name).strip() if isinstance(name, (str, int, float)) and str(name).strip() else None
    if name is None:
        if len(roots) > 1:
            return None, "a project with several roots needs a name"
        name = os.path.basename(roots[0].rstrip("*")) or roots[0]
    problems = []
    north = None
    star = block.get("north-star")
    if isinstance(star, dict):
        milestone, kpi = star.get("milestone-of"), star.get("kpi")
        if isinstance(milestone, str) and milestone.strip():
            north = {"kind": "milestone", "track": milestone.strip()}
        elif isinstance(kpi, str) and "/" in kpi:
            track, kpi_id = kpi.split("/", 1)
            north = {"kind": "kpi", "track": track.strip(), "kpi": kpi_id.strip()}
        else:
            problems.append("north-star needs milestone-of: <track> or kpi: <track>/<kpi>")
    elif star is not None:
        problems.append("north-star must be a mapping")
    return Project(name=name, roots=roots, north_star=north, path=str(path), problems=problems), None


def read_projects(workspace: str | os.PathLike[str]) -> tuple[dict[str, Project], list[dict[str, str]]]:
    """Every project descriptor by name (cached on the files' mtimes), and the problems met reading them."""

    workspace = Path(workspace)
    key = str(workspace.resolve())
    stamp = _stamp(workspace)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    out: dict[str, Project] = {}
    problems: list[dict[str, str]] = []
    for path_s, _mtime, _size in stamp:
        project, why = parse_project(Path(path_s))
        if project is None:
            problems.append({"path": Path(path_s).name, "error": why or "not a project"})
            continue
        if project.name in out:
            problems.append({"path": Path(path_s).name, "error": f"duplicate project name {project.name!r}; skipped"})
            continue
        out[project.name] = project
        problems += [{"path": Path(path_s).name, "error": text} for text in project.problems]
    _CACHE[key] = (stamp, (out, problems))
    return out, problems


def render_descriptor(name: str | None, roots: list[str]) -> str:
    """The descriptor text the New project dialog would write (the page prints it; nothing writes it yet)."""

    lines = ["vibetracks:", "  version: 1", "  kind: project"]
    if name and not (len(roots) == 1 and os.path.basename(roots[0].rstrip("/")) == name):
        lines.append(f"  name: {json.dumps(name, ensure_ascii=False)}")
    lines.append("  roots: [" + ", ".join(json.dumps(r, ensure_ascii=False) for r in roots) + "]")
    return "\n".join(lines) + "\n"
