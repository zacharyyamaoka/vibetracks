"""Evidence links that open: path normalisation, citation parsing, and test locations.

A link in bam-roadmap/1 is ``{path, base, abs, line, exists}``. ``base`` names one of the
document's ``roots`` (``repo``, ``data_home``) or ``abs``, the way SARIF pairs
``artifactLocation.uri`` with a ``uriBaseId``; ``abs`` is the absolute path the UI opens.
A link that does not resolve keeps ``exists: false`` and says why. Nothing is guessed: a bare
file name that matches several tracked files stays unresolved and names how many it matched.

Free-text evidence (the loops' ``evidence`` strings) is parsed here and only here, so the
regex that used to live in each viewer has one tested home until the loops write links.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

WORKTREES_MARKER = "/.claude/worktrees/"
IMAGE_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg")
VIDEO_SUFFIXES = (".mp4", ".webm", ".mov")
LOG_SUFFIXES = (".txt", ".log", ".out")

# ---------------------------------------------------------------- the shared citation rule
# WHY one rule shared with the dashboard (Codex F10, round 1): the API serves, the page links and this
# package proves exactly the same tokens. The rule and its cases are bam-citation-corpus/1
# (src/dev/bam_kinsim_dashboard/tests/api/citation_corpus.json; its reference is cited_tokens() in the
# dashboard's api/dashboard_core.py); tests/test_codex_r1.py runs every case against the JSON file.
# Reimplemented here, never imported: this runtime stays stdlib-only.
CITED_TEXT_SUFFIXES = ("log", "txt", "md", "py", "json", "jsonl", "toml", "yaml", "yml", "cfg", "ini", "xml")
CITED_IMAGE_SUFFIXES = ("png", "webp", "jpg", "jpeg")
# A token is a maximal run between ASCII whitespace [ \t\n\v\f\r] (never str.split(), which also splits on
# U+001C-U+001F; the dashboard's Codex audit B13). Matched, not split, so each token keeps its offset.
_CITED_TOKEN_RUN = re.compile(r"[^ \t\n\v\f\r]+")
_CLAUSE = re.compile(r"(?:[^;]|;(?!\s))+")
_CITED_LEADING = "([{\"'`<"
_CITED_TRAILING = ")]}.,;:\"'`>"
_CITED_QUOTES = "\"'`"
_CITED_TOKEN = re.compile(
    r"(?P<path>/[A-Za-z0-9._~+@%=/-]+?\.(?P<suffix>" + "|".join(CITED_TEXT_SUFFIXES + CITED_IMAGE_SUFFIXES) + r"))"
    r"(?::(?P<line>[0-9]+)(?::[0-9]+)?)?")
_CITED_DOT_SEGMENT = re.compile(r"/\.\.?(?:/|$)")
# A code reference written as a bare file name: "collision.py:238-268", "specs.py:226-248".
_BARE_CODE_REFERENCE = re.compile(
    r"(?<![\w/.-])((?:[\w.-]+/)*[A-Za-z_][\w-]*\.(?:py|mjs|js|ts|sh|urdf|xacro|json|toml|md))(?::(\d+)(?:[-,](\d+))?)?(?![\w/])"
)


@dataclass(frozen=True)
class Roots:
    """Where relative paths resolve. ``repo`` is the checkout being projected."""

    repo: Path
    data_home: Path | None = None
    # Other checkouts of the same repository (main clone, sibling worktrees): a path cited
    # inside one of them is re-based onto ``repo``, since worktrees are swept but the file
    # usually still exists at the same repository-relative path.
    repo_aliases: tuple[Path, ...] = ()

    def as_dict(self) -> dict[str, str]:
        roots = {"repo": str(self.repo)}
        if self.data_home is not None:
            roots["data_home"] = str(self.data_home)
        return roots


@dataclass
class Citation:
    """One path a loop's text cites: the path and its line, never glued together.

    ``kind`` is ``text`` (a file the dashboard serves) or ``image`` (a page link only).
    """

    raw: str
    line: int | None = None
    end_line: int | None = None
    kind: str = "text"


def _cited(stripped: str) -> Citation | None:
    """The citation one stripped, unquoted token makes, or None."""

    if not stripped.startswith("/"):
        return None
    match = _CITED_TOKEN.fullmatch(stripped)
    if match is None or _CITED_DOT_SEGMENT.search(match["path"]):
        return None
    kind = "image" if match["suffix"] in CITED_IMAGE_SUFFIXES else "text"
    return Citation(match["path"], int(match["line"]) if match["line"] else None, None, kind)


def cited_spans(text: str | None) -> list[tuple[Citation, int]]:
    """Every citation in one text with the offset of its token, duplicates kept (bam-citation-corpus/1).

    WHY quotes are delimiters matched across tokens (the dashboard's Codex audits C02/D01, Oct 3): in
    ``"/safe/name.txt /safe/proof.txt copy.log"`` the quote opened before the first path closes after the last
    word, so every token inside is part of one quoted name and none is a citation, the middle one included. A
    token's front quotes open (a stack, left to right); its back quotes, read left to right (innermost first),
    each close the most recent matching open quote, else they are stray; a token that is only punctuation, while
    a quote is open, closes with its quotes instead of opening. A token cites a file only when no quote was open
    before it, none is open after it, and none of its quotes was stray. Quotes never span two texts: callers parse
    an event's ``evidence`` and ``detail`` separately, and split a text into clauses only after parsing it whole.
    """

    if not text:
        return []
    found: list[tuple[Citation, int]] = []
    stack: list[str] = []
    for match in _CITED_TOKEN_RUN.finditer(text):
        raw, position = match.group(0), match.start()
        core = raw.lstrip(_CITED_LEADING)
        stripped = core.rstrip(_CITED_TRAILING)
        front = [char for char in raw[: len(raw) - len(core)] if char in _CITED_QUOTES]
        back = [char for char in core[len(stripped):] if char in _CITED_QUOTES]
        if not core and stack:  # only punctuation, inside a quote: its quotes close, they do not open
            front, back = [], front
        was_open, stray = bool(stack), False
        stack.extend(front)
        for quote in back:
            if quote in stack:
                del stack[len(stack) - 1 - stack[::-1].index(quote):]
            else:
                stray = True
        if was_open or stack or stray:
            continue
        citation = _cited(stripped)
        if citation is not None:
            found.append((citation, position))
    return found


def cited_paths(text: str | None) -> list[Citation]:
    """Every citation in one text, in order; a path cited twice keeps its first spelling."""

    unique_paths: dict[str, Citation] = {}
    for citation, _offset in cited_spans(text):
        unique_paths.setdefault(citation.raw, citation)
    return list(unique_paths.values())


def clauses_with_citations(text: str | None) -> list[tuple[str, list[Citation]]]:
    """``(clause, the citations whose token starts in it)``, the text parsed whole first (see ``cited_spans``)."""

    if not text:
        return []
    citations = cited_spans(text)
    rows = []
    for match in _CLAUSE.finditer(text):
        clause = match.group(0).strip()
        if clause:
            rows.append((clause, [citation for citation, offset in citations if match.start() <= offset < match.end()]))
    return rows


def bare_code_references(text: str | None) -> list[tuple[str, int | None, int | None, str]]:
    """``(name or partial path, line, end line, words before it)`` for each code reference in ``text``.

    Catches ``collision.py:238-268`` and ``scripts/kinematic_gate.sh``; a reference needs a
    line or a folder, so a bare ``notes.md`` in prose is not mistaken for one.
    """

    references = []
    for match in _BARE_CODE_REFERENCE.finditer(text or ""):
        name, line_text = match.group(1), match.group(2)
        if line_text is None and "/" not in name:
            continue
        before = (text or "")[max(0, match.start() - 40):match.start()]
        line = int(line_text) if line_text else None
        end = int(match.group(3)) if match.group(3) else None
        references.append((name, line, end if end and line and end >= line else None, before))
    return references


def split_clauses(text: str | None) -> list[str]:
    """An evidence string's clauses: one command, its result and its cited log each."""

    return [clause.strip() for clause in re.split(r";\s+", text or "") if clause.strip()]


# ---------------------------------------------------------------- normalisation
def classify(path: str) -> str:
    """The evidence kind a cited path is, by what it is (not by where it was cited)."""

    lowered = path.lower()
    if lowered.endswith(IMAGE_SUFFIXES):
        return "image"
    if lowered.endswith(VIDEO_SUFFIXES):
        return "video"
    if lowered.endswith("gate_report.json"):
        return "gate_report"
    if lowered.endswith(".xml") and "junit" in lowered:
        return "junit"
    if "/audits/" in lowered and lowered.endswith(".md"):
        return "audit"
    if lowered.endswith(LOG_SUFFIXES):
        return "log"
    if lowered.endswith("/batch.json") or "/runs/" in lowered and lowered.endswith(".json"):
        return "run"
    return "file"


def normalise(raw: str, roots: Roots) -> tuple[str, str, Path]:
    """``(path, base, absolute)`` for a cited path: repository-relative where it can be.

    A path inside another checkout of the same repository (a lane worktree that may since have
    been swept, or the main clone) is re-based onto ``roots.repo``.
    """

    absolute = Path(raw)
    if not absolute.is_absolute():
        return raw, "repo", roots.repo / raw
    for root, base in ((roots.repo, "repo"), (roots.data_home, "data_home")):
        if root is not None and _is_under(absolute, root):
            relative = absolute.relative_to(root).as_posix()
            return relative, base, root / relative
    text = absolute.as_posix()
    # WHY an existing path stays as written: reports/ and other untracked evidence live only in
    # the main clone, so re-basing them onto this checkout would break a link that works.
    if absolute.exists():
        return text, "abs", absolute
    rebased = []
    if WORKTREES_MARKER in text:
        tail = text.split(WORKTREES_MARKER, 1)[1].split("/", 1)
        if len(tail) == 2:
            rebased.append(tail[1])
    rebased += [absolute.relative_to(alias).as_posix() for alias in roots.repo_aliases if _is_under(absolute, alias)]
    for relative in rebased:
        if (roots.repo / relative).exists():
            return relative, "repo", roots.repo / relative
    return text, "abs", absolute


def repo_relative(raw: str, roots: Roots) -> str | None:
    """A path written in any checkout of this repository (a swept lane worktree included) as a repository-relative
    path of ``roots.repo``, when that file exists here; else None."""

    absolute = Path(raw)
    candidates = []
    if not absolute.is_absolute():
        candidates.append(raw)
    else:
        for root in (roots.repo, *roots.repo_aliases):
            if _is_under(absolute, root):
                candidates.append(absolute.relative_to(root).as_posix())
        text = absolute.as_posix()
        if WORKTREES_MARKER in text:
            tail = text.split(WORKTREES_MARKER, 1)[1].split("/", 1)
            if len(tail) == 2:
                candidates.append(tail[1])
    return next((relative for relative in candidates if (roots.repo / relative).exists()), None)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def link(kind: str, raw: str | None, roots: Roots, *, label: str | None = None, line: int | None = None,
         end_line: int | None = None) -> dict:
    """A link dict for a cited or declared path, resolved against the disk now."""

    if raw is None:
        return {"kind": kind, "label": label, "path": None, "base": None, "abs": None, "line": None,
                "end_line": None, "exists": False, "why_unresolved": "no path recorded"}
    path, base, absolute = normalise(raw, roots)
    exists = absolute.exists()
    why = None
    if not exists:
        why = "file not found" if base != "abs" or absolute.parent.exists() else "folder not found"
        if raw.startswith("/tmp/"):
            why += " (it was under /tmp, which is cleared at reboot)"
    if exists and line is not None and absolute.is_file():
        line_count = count_lines(str(absolute))
        if line_count is not None and line > line_count:
            why, exists = f"line {line} is past the end ({line_count} lines)", False
    return {"kind": kind, "label": label or Path(path.rstrip("/")).name, "path": path, "base": base,
            "abs": str(absolute) if exists else None, "line": line, "end_line": end_line,
            "exists": exists, "why_unresolved": why}


@lru_cache(maxsize=2048)
def count_lines(path: str) -> int | None:
    try:
        with open(path, "rb") as handle:
            return sum(1 for _line in handle)
    except OSError:
        return None


# ---------------------------------------------------------------- bare file names
def resolve_bare_name(name: str, before: str, tracked: Sequence[str], scope_roots: Sequence[str],
                      neighbours: Sequence[str] = ()) -> tuple[str | None, str]:
    """A tracked file for a bare ``name.py`` (or a partial ``scripts/x.sh``), or why there is none.

    In order: a unique match; the only match under the loop's own package roots; the only match
    under a folder named just before it; the only match sharing the deepest folder with a
    sibling reference already resolved from the same sentence. Never a guess among equals.
    """

    suffix = "/" + name
    candidates = [path for path in tracked if path == name or path.endswith(suffix)]
    if not candidates:
        return None, f"no tracked file named {name}"
    if len(candidates) == 1:
        return candidates[0], "unique file name"
    in_scope = [path for path in candidates if any(path.startswith(root.rstrip("/") + "/") for root in scope_roots)]
    if len(in_scope) == 1:
        return in_scope[0], "the only one under the loop's package roots"
    hints = set(re.findall(r"[\w-]+", before)[-3:])
    hinted = [path for path in (in_scope or candidates) if hints & set(path.split("/")[:-1])]
    if len(hinted) == 1:
        return hinted[0], "the only one under the folder named beside it"
    if neighbours:
        pool = in_scope or candidates
        depth = {path: max(_shared_depth(path, neighbour) for neighbour in neighbours) for path in pool}
        best = max(depth.values())
        closest = [path for path, shared in depth.items() if shared == best]
        if best > 0 and len(closest) == 1:
            return closest[0], "the one beside the other files the same sentence cites"
    return None, f"ambiguous: {len(candidates)} tracked files named {name}"


def _shared_depth(left: str, right: str) -> int:
    shared = 0
    for a, b in zip(left.split("/")[:-1], right.split("/")[:-1]):
        if a != b:
            break
        shared += 1
    return shared


# ---------------------------------------------------------------- test locations
@dataclass
class TestFunction:
    """One collectable test function: its pytest-style key ("Class::name" or "name") and def line."""

    key: str
    line: int


@lru_cache(maxsize=512)
def _test_functions_cached(path: str, mtime: float) -> tuple[tuple[str, int], ...]:
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return ()
    functions: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            functions.append((node.name, node.lineno))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                    functions.append((f"{node.name}::{child.name}", child.lineno))
    return tuple(functions)


def test_functions(path: Path) -> list[TestFunction]:
    """The test functions pytest would collect from a ``test_*.py`` / ``*_test.py`` file, with def lines.

    WHY ast and not an import: the projection must never execute the code it reports on.
    """

    if not path.is_file() or path.suffix != ".py":
        return []
    return [TestFunction(key, line) for key, line in _test_functions_cached(str(path), path.stat().st_mtime)]


def node_id(file_path: str, key: str) -> str:
    """pytest's node id: ``path/to/test_file.py::Class::name`` (parameters dropped)."""

    return f"{file_path}::{key}"


def junit_file_for(classname: str, suite_dir: str, exists) -> tuple[str | None, str | None]:
    """``(repository-relative test file, class name or None)`` for a JUnit ``classname``.

    pytest writes ``classname`` as the node id's path with ``/`` -> ``.`` and ``.py`` dropped,
    then ``.Class`` for a method; the path is relative to the rootdir, which for every BAM
    suite is the suite's own cwd. The longest prefix that names an existing ``.py`` file wins.
    """

    parts = classname.split(".")
    for cut in range(len(parts), 0, -1):
        module = "/".join(parts[:cut]) + ".py"
        candidate = f"{suite_dir.rstrip('/')}/{module}" if suite_dir not in ("", ".") else module
        if exists(candidate):
            rest = parts[cut:]
            return candidate, (rest[0] if rest else None)
    return None, None


def strip_parameters(name: str) -> str:
    return name.split("[", 1)[0]


def is_file_target(target: str) -> bool:
    return "." in target.rstrip("/").rsplit("/", 1)[-1]


def target_names(target: str) -> set[str]:
    """The word that names a target in a loop's sentence: its file name, or the package of a ``tests/`` folder."""

    parts = target.rstrip("/").split("/")
    if parts[-1] == "tests" and len(parts) > 1:
        return {parts[-2]}
    names = {parts[-1]}
    stem = parts[-1].rsplit(".", 1)[0]
    if stem.startswith("test_") or stem.endswith("_test"):
        names.add(stem)  # "(16/16 test_mjcf_camera)" names test_mjcf_camera.py
    return names


_SINGLE_TEST_FILE = re.compile(r"(?<![\w.-])(?:test_[\w-]+\.py|[\w-]+_test\.py|[\w-]+\.test\.[jt]s|[\w-]+\.mjs)(?![\w-])")
_CLAUSE_LABEL = re.compile(r"^\s*([\w./-]+):\s")


def names_target(clause: str, target: str) -> bool:
    """Does a clause of a loop's sentence speak for ``target``?

    1. It names the file (``test_x.py``), or the package of a ``tests/`` folder, as a whole word.
    2. It is a whole-package run: the clause is labelled with a folder that contains the target
       (``src/dev/bam_deployments: uv run pytest -q -> 200 passed``) and names no single test file.
    """

    clean = target.rstrip("/")
    if clean in clause:
        return True
    for name in target_names(clean):
        # WHY ".word" also ends no name: test_x.py must not match inside test_x.py.bak (the A02 bug class).
        if re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-]|\.\w)", clause):
            return True
    label = _CLAUSE_LABEL.match(clause)
    if label is None or _SINGLE_TEST_FILE.search(clause):
        return False
    folder = label.group(1).rstrip("/")
    parts = clean.split("/")
    parents = {"/".join(parts[:index]) for index in range(1, len(parts))}
    return folder in parents or ("/" not in folder and folder in parts[:-1])


def unique(items: Iterable) -> list:
    return list(dict.fromkeys(items))


@dataclass
class EvidenceBook:
    """The evidence items of one rung, with stable ids in the order they were first cited."""

    items: list[dict] = field(default_factory=list)
    _by_key: dict[tuple, str] = field(default_factory=dict)

    def add(self, item: dict, key: tuple | None = None) -> str:
        if key is not None and key in self._by_key:
            return self._by_key[key]
        evidence_id = f"e{len(self.items) + 1}"
        self.items.append({"id": evidence_id, **item})
        if key is not None:
            self._by_key[key] = evidence_id
        return evidence_id

    def get(self, evidence_id: str) -> dict:
        return next(item for item in self.items if item["id"] == evidence_id)
