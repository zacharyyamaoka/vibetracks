"""Freshness scopes: what must not have changed since a piece of evidence for it to still hold (Codex F08).

A test's proof goes stale when the test changes, and also when the code it exercises changes. The
loops rarely declare that code (the rig declares ``write_set`` per package; the kinsim curriculum
declares nothing), so this module derives a conservative scope from the code itself:

- the target file, the ``conftest.py`` files pytest loads for it, and its package's manifests;
- the static import closure of those files, resolved against the repository's tracked ``.py`` files;
- for a non-Python target (a ``.mjs`` journey), its whole package folder;
- a declared write set, when the loop gives one, is added on top (it never narrows the scope).

WHY this default, and why it is reversible: a scope that is too wide only turns a green into
``stale`` until the evidence is re-run, which costs a re-run; a scope that is too narrow lets a
changed implementation keep a green it no longer earned, which is the failure Codex found (VZ2
stayed green after ``visualize_collision_scenarios.py``, which its acceptance imports, changed).
When the closure is large, it collapses to whole package folders, which is broader, never narrower.
Code a test reaches only through a subprocess or a dynamic import is outside the closure; the
package-folder fallback for non-Python targets is the conservative answer for journeys, and a loop
that needs more declares it in its write set.

A measured reading is different (Codex G08): it was produced by one command and scored by one
library, so its scope is that command's execution path (``execution_scope``): the import closure
from the command's entry module, following imports inside functions too and modules named in
strings (``importlib`` targets, ``pkg.mod:attr`` entry points), but not the handlers of the
command's other subcommands (an argparse ``set_defaults(handler=...)`` for a subparser the command
line did not select). A replay viewer or another subcommand's code is then outside the scope of a
reading it never ran.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath

from .gitinfo import Repo

MAX_SCOPE_FILES = 60      # beyond this the scope collapses to package folders
CLOSURE_LIMIT = 800       # files visited before the closure gives up and collapses
MANIFESTS = ("pyproject.toml", "uv.lock", "package.json")
# What marks a folder as a package root (a pytest.ini-only package, like the kinsim dashboard, counts).
ROOT_MARKERS = ("pyproject.toml", "package.json", "pytest.ini", "setup.py", "setup.cfg")
SUFFIX_DEPTH = 6
AMBIGUOUS_LIMIT = 3       # a module name matching more files than this is someone else's (stdlib, third party)
# Tracked trees that are never the code under test: vendored environments, archives, copied references.
NOT_PROJECT_SEGMENTS = ("site-packages", "node_modules", "archive", "external")


def _is_project_code(path: str) -> bool:
    parts = path.split("/")
    if any(part.startswith(".") or part.endswith(".egg-info") for part in parts[:-1]):
        return False
    if any(part in NOT_PROJECT_SEGMENTS for part in parts):
        return False
    # WHY build/lib: a tracked setuptools build copy (five_bar_kin_dyn/src/build/lib) is not the code that runs.
    if any(part == "build" and index + 1 < len(parts) and parts[index + 1].startswith("lib") for index, part in enumerate(parts)):
        return False
    return "/docs/ref/" not in path


@lru_cache(maxsize=4096)
def _imports_of(path: str, mtime: float) -> tuple[tuple[str | None, int, tuple[str, ...]], ...]:
    """``(module, level, names)`` for every import statement in a Python file (never executed)."""

    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return ()
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, 0, ()))
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module, node.level or 0, tuple(alias.name for alias in node.names if alias.name != "*")))
    return tuple(found)


_ENTRY_POINT = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
_MODULE_NAME = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_IMPORTERS = ("import_module", "__import__", "run_module")


@dataclass(frozen=True)
class ModuleFacts:
    """What a module can load: at import time, inside each top-level function, and which functions are subcommand handlers."""

    module_imports: tuple[tuple[str | None, int, tuple[str, ...]], ...]
    module_strings: tuple[str, ...]
    functions: tuple[tuple[str, tuple[tuple[str | None, int, tuple[str, ...]], ...], tuple[str, ...]], ...]
    handlers: tuple[tuple[str, tuple[str, ...], bool], ...]  # (function, subcommand path, absolute path?)


def _imports_in(node: ast.AST) -> list[tuple[str | None, int, tuple[str, ...]]]:
    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            found += [(alias.name, 0, ()) for alias in child.names]
        elif isinstance(child, ast.ImportFrom):
            found.append((child.module, child.level or 0, tuple(alias.name for alias in child.names if alias.name != "*")))
    return found


def _module_strings_in(node: ast.AST) -> list[str]:
    """Module names a function loads by string: ``import_module("x")``, ``module_name="x"``, ``"pkg.mod:attr"``, ``["-m", "x"]``."""

    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = child.func.attr if isinstance(child.func, ast.Attribute) else getattr(child.func, "id", "")
            if name in _IMPORTERS and child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str):
                found.append(child.args[0].value)
            for keyword in child.keywords:
                if keyword.arg and "module" in keyword.arg and isinstance(keyword.value, ast.Constant) \
                        and isinstance(keyword.value.value, str):
                    found.append(keyword.value.value)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str) and _ENTRY_POINT.match(child.value):
            found.append(child.value.split(":", 1)[0])
        elif isinstance(child, (ast.List, ast.Tuple)):
            values = [element.value if isinstance(element, ast.Constant) else None for element in child.elts]
            found += [str(values[index + 1]) for index in range(len(values) - 1)
                      if values[index] == "-m" and isinstance(values[index + 1], str)]
    return [value for value in found if _MODULE_NAME.match(value)]


def _handlers_in(function: ast.AST) -> list[tuple[str, tuple[str, ...], bool]]:
    """argparse subcommand handlers registered in one function: ``(handler, subcommand path, absolute?)``.

    Follows the idiom ``P = argparse.ArgumentParser()``, ``S = P.add_subparsers()``, ``Q = S.add_parser("run")``,
    ``Q.set_defaults(handler=_command_run)``. A parser that arrives as a parameter has an unknown prefix, so its
    paths are relative (matched anywhere in the command line's words).
    """

    paths: dict[str, tuple[tuple[str, ...], bool]] = {}
    if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for argument in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]:
            paths[argument.arg] = ((), False)

    def path_of(node: ast.AST) -> tuple[tuple[str, ...], bool] | None:
        if isinstance(node, ast.Name):
            return paths.get(node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = path_of(node.func.value)
            if node.func.attr == "add_subparsers":
                return owner
            if node.func.attr == "add_parser" and owner is not None and node.args and isinstance(node.args[0], ast.Constant):
                return ((*owner[0], str(node.args[0].value)), owner[1])
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name == "ArgumentParser":
                return ((), True)
        return None

    handlers = []
    nodes = sorted((node for node in ast.walk(function) if isinstance(node, (ast.Assign, ast.Call))),
                   key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)))
    for node in nodes:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            found = path_of(node.value)
            if found is not None:
                paths[node.targets[0].id] = found
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_defaults":
            owner = path_of(node.func.value)
            if owner is None:
                continue
            handlers += [(keyword.value.id, owner[0], owner[1]) for keyword in node.keywords if isinstance(keyword.value, ast.Name)]
    return handlers


@lru_cache(maxsize=4096)
def _facts_of(path: str, mtime: float) -> ModuleFacts:
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return ModuleFacts((), (), (), ())
    module_imports, module_strings, functions, handlers = [], [], [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append((node.name, tuple(_imports_in(node)), tuple(_module_strings_in(node))))
            handlers += _handlers_in(node)
        else:
            # WHY class bodies count as import time: a class's methods run whenever the class is used, and
            # telling which methods a run calls is beyond a static reading; keeping them all is the safe side.
            module_imports += _imports_in(node)
            module_strings += _module_strings_in(node)
            handlers += _handlers_in(node)
    return ModuleFacts(tuple(module_imports), tuple(module_strings), tuple(functions), tuple(handlers))


def _selected(path: tuple[str, ...], absolute: bool, words: tuple[str, ...]) -> bool:
    if not path:
        return True
    if absolute:
        return tuple(words[:len(path)]) == path
    return any(tuple(words[index:index + len(path)]) == path for index in range(len(words) - len(path) + 1))


def command_entry(argv: list[str]) -> tuple[str | None, list[str]]:
    """``(module, subcommand words)`` of a ``python -m module word word --option ...`` command line."""

    module, words = None, []
    for index, token in enumerate(argv[:-1]):
        if token == "-m" and not argv[index + 1].startswith("-"):
            module, rest = argv[index + 1], argv[index + 2:]
            words = []
            for word in rest:
                if word.startswith("-") or word.startswith("[") or word.startswith("{"):
                    break
                words.append(word)
    return module, words


def _shared_depth(left: str, right: str) -> int:
    shared = 0
    for a, b in zip(left.split("/")[:-1], right.split("/")[:-1]):
        if a != b:
            break
        shared += 1
    return shared


class CodeIndex:
    """The repository's tracked files, indexed for import resolution and package lookup."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self.root = repo.root
        self.tracked = frozenset(repo.tracked_files())
        self.by_suffix: dict[str, list[str]] = {}
        for path in self.tracked:
            if not path.endswith(".py") or not _is_project_code(path):
                continue
            parts = path.split("/")
            for depth in range(1, min(SUFFIX_DEPTH, len(parts)) + 1):
                self.by_suffix.setdefault("/".join(parts[-depth:]), []).append(path)
        self.manifest_dirs = frozenset(str(PurePosixPath(path).parent) for path in self.tracked
                                       if PurePosixPath(path).name in ROOT_MARKERS and _is_project_code(path))
        self._dependencies: dict[str, frozenset[str]] = {}

    # ------------------------------------------------------------ packages
    def package_root(self, path: str) -> str | None:
        """The nearest folder above ``path`` that holds a package manifest (pyproject.toml, package.json)."""

        folder = PurePosixPath(path).parent
        # WHY the parent check: an absolute path (a target in another repository) climbs to "/", whose parent is itself.
        while str(folder) not in ("", ".") and folder != folder.parent:
            if str(folder) in self.manifest_dirs:
                return str(folder)
            folder = folder.parent
        return None

    def conftests(self, path: str) -> list[str]:
        root = self.package_root(path)
        found = []
        folder = PurePosixPath(path).parent
        while str(folder) not in ("", ".") and folder != folder.parent:
            candidate = f"{folder}/conftest.py"
            if candidate in self.tracked:
                found.append(candidate)
            if root is not None and str(folder) == root:
                break
            folder = folder.parent
        return found

    def dependency_roots(self, root: str | None) -> frozenset[str]:
        """The package folders ``root`` declares as path dependencies (``[tool.uv.sources]``), transitively.

        WHY these and nothing else: they are what the package's environment actually imports, so a
        module name that also exists in an unrelated copy elsewhere in the repository is never taken.
        """

        if root is None:
            return frozenset()
        if root in self._dependencies:
            return self._dependencies[root]
        self._dependencies[root] = frozenset()  # a cycle in the declarations ends here
        found: set[str] = set()
        try:
            manifest = tomllib.loads((self.root / root / "pyproject.toml").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        sources = ((manifest.get("tool") or {}).get("uv") or {}).get("sources") or {}
        for source in sources.values():
            if isinstance(source, dict) and isinstance(source.get("path"), str):
                folder = os.path.normpath(f"{root}/{source['path']}")
                dependency = folder if folder in self.manifest_dirs else self.package_root(f"{folder}/x")
                if dependency:
                    found.add(dependency)
                    found |= self.dependency_roots(dependency)
        self._dependencies[root] = frozenset(found)
        return self._dependencies[root]

    def manifests(self, root: str | None) -> list[str]:
        if root is None:
            return []
        return [f"{root}/{name}" for name in MANIFESTS if f"{root}/{name}" in self.tracked]

    # ------------------------------------------------------------ imports
    def _lookup(self, dotted: str) -> list[str]:
        """Tracked files that ``import dotted`` could load: never a standard-library name, and only a file whose
        folder above the dotted path is not itself a package (``import mujoco`` is not bam_homing's mujoco.py)."""

        if dotted.split(".", 1)[0] in sys.stdlib_module_names:
            return []
        relative = dotted.replace(".", "/")
        found = []
        for suffix in (relative + ".py", relative + "/__init__.py"):
            for path in self.by_suffix.get(suffix, []):
                source_root = path[: -len(suffix)].rstrip("/")
                if f"{source_root}/__init__.py" not in self.tracked:
                    found.append(path)
        return found

    def _closest(self, candidates: list[str], importer: str) -> list[str]:
        """The candidates the importer's environment would import: its own package, then its declared path dependencies."""

        if not candidates:
            return []
        root = self.package_root(importer)
        same_package = [path for path in candidates if root is not None and self.package_root(path) == root]
        if same_package:
            return same_package
        dependencies = self.dependency_roots(root)
        declared = [path for path in candidates if self.package_root(path) in dependencies]
        if declared:
            return declared
        # WHY an undeclared import of project code still counts: the kinsim producer reaches bam_collision, its
        # own engine, through a sys.path insert (physical.py, log_replay.py), never through its manifest. Leaving
        # it out would let an engine change keep a green (Codex F08); counting it only costs a re-run.
        # WHY a cap: a name that matches many tracked files (``utils``) is not one of them for certain.
        if len(candidates) > AMBIGUOUS_LIMIT:
            return []
        # WHY the nearest copy: a sys.path insert points at a neighbouring folder, so of two ur_kinematics the
        # one beside the importer is the one it runs (the other is like_keras's copy).
        nearest = max(_shared_depth(path, importer) for path in candidates)
        return [path for path in candidates if _shared_depth(path, importer) == nearest]

    def resolve(self, module: str | None, level: int, names: tuple[str, ...], importer: str) -> list[str]:
        if level:
            base = PurePosixPath(importer).parent
            for _ in range(level - 1):
                base = base.parent
            stems = [f"{module}.{name}" for name in names] + [module] if module else list(names)
            found = []
            for stem in stems:
                relative = stem.replace(".", "/") if stem else ""
                for candidate in (f"{base}/{relative}.py", f"{base}/{relative}/__init__.py"):
                    if candidate in self.tracked:
                        found.append(candidate)
            if not found and f"{base}/__init__.py" in self.tracked:
                found.append(f"{base}/__init__.py")
            return found
        if not module:
            return []
        found: list[str] = []
        for name in names or (None,):
            hit = self._lookup(f"{module}.{name}") if name else []
            found += self._closest(hit or self._lookup(module), importer)
        return list(dict.fromkeys(found))

    def imports(self, path: str) -> list[str]:
        absolute = self.root / path
        try:
            mtime = absolute.stat().st_mtime
        except OSError:
            return []
        found: list[str] = []
        for module, level, names in _imports_of(str(absolute), mtime):
            found += self.resolve(module, level, names, path)
        return list(dict.fromkeys(found))

    def closure(self, seeds: list[str], limit: int = CLOSURE_LIMIT) -> tuple[set[str], bool]:
        """Every tracked Python file the seeds import, transitively; ``True`` when it stopped at the limit."""

        seen: set[str] = set()
        stack = [seed for seed in seeds if seed.endswith(".py")]
        while stack:
            path = stack.pop()
            if path in seen:
                continue
            seen.add(path)
            if len(seen) > limit:
                return seen, True
            stack.extend(child for child in self.imports(path) if child not in seen)
        return seen, False

    # ------------------------------------------------------------ the scope
    def scope(self, target: str, extra: tuple[str, ...] | list[str] = ()) -> list[str]:
        """The paths whose change after a piece of evidence for ``target`` makes it stale (``dir/`` = a whole folder).

        The rule: the target, its own package, every package that package declares as a path dependency
        (transitively), any file its static import closure reaches outside those, and a declared write set.
        WHY whole packages (Codex F08): acceptance tests reach their code through subprocesses and dynamic
        imports that no static reading sees (VZ2's teardown test runs visualize_collision_scenarios.py in a
        subprocess); the package and its declared dependencies are what the test's environment can run.
        """

        clean = target.rstrip("/")
        entries: set[str] = {target}
        own = self.package_root(clean)
        folders: set[str] = set()
        parts = PurePosixPath(clean).parts
        if own is not None:
            folders.add(own)
            folders |= self.dependency_roots(own)
        elif "tests" in parts[:-1] and parts.index("tests") > 0:
            # WHY the folder that holds tests/: with no manifest to name the package, pytest's own convention
            # does; the bare tests/ folder would leave the code under test out of the scope.
            last = len(parts) - 1 - parts[::-1].index("tests")
            folders.add("/".join(parts[:last]))
        elif PurePosixPath(clean).suffix:
            folders.add(str(PurePosixPath(clean).parent))
        else:
            folders.add(clean)
        if clean.endswith(".py") and clean in self.tracked:
            files, truncated = self.closure([clean, *self.conftests(clean)])
            outside = {path for path in files if self.package_root(path) not in folders}
            if truncated or len(outside) > MAX_SCOPE_FILES:
                folders |= {root for root in (self.package_root(path) for path in outside) if root}
                entries.update(path for path in outside if self.package_root(path) is None)
            else:
                entries.update(outside)
        entries.update(f"{folder}/" for folder in folders)
        entries.update(path for path in extra if path)
        return sorted(entries)

    # ------------------------------------------------------------ a command's execution path (Codex G08)
    def facts(self, path: str) -> ModuleFacts:
        absolute = self.root / path
        try:
            return _facts_of(str(absolute), absolute.stat().st_mtime)
        except OSError:
            return ModuleFacts((), (), (), ())

    def execution_closure(self, seeds: list[str], words: list[str] | None = None) -> set[str]:
        """Every tracked Python file a run that starts at ``seeds`` can load (see the module docstring).

        ``words`` are the command line's subcommand words (``kinematic-pick run``); with them, a function
        registered as the handler of another subcommand is not followed. Without them nothing is pruned.
        """

        selected_words = tuple(words) if words is not None else None
        seen: set[str] = set()
        stack = sorted(seed for seed in seeds if seed.endswith(".py"))
        while stack:
            path = stack.pop()
            if path in seen:
                continue
            seen.add(path)
            facts = self.facts(path)
            imports = list(facts.module_imports)
            strings = list(facts.module_strings)
            kept = {name for name, sub, absolute in facts.handlers
                    if selected_words is None or _selected(sub, absolute, selected_words)}
            foreign = {name for name, _sub, _absolute in facts.handlers} - kept
            for name, function_imports, function_strings in facts.functions:
                if name in foreign:
                    continue  # the handler of a subcommand this command line does not run
                imports += function_imports
                strings += function_strings
            children: list[str] = []
            for module, level, names in imports:
                children += self.resolve(module, level, names, path)
            for module in strings:
                children += self.resolve(module, 0, (), path)
            stack.extend(sorted(child for child in set(children) if child not in seen))
        return seen

    def entry_files(self, module: str, package_dir: str) -> list[str]:
        """The files ``python -m module`` runs from ``package_dir``: the module (or package) and its ``__main__``."""

        relative = module.replace(".", "/")
        found = []
        for suffix in (f"{relative}.py", f"{relative}/__init__.py", f"{relative}/__main__.py"):
            found += [path for path in self.by_suffix.get(suffix, []) if path.startswith(package_dir.rstrip("/") + "/")]
        return sorted(set(found))

    def external_imports(self, path: str, package_dir: str) -> list[str]:
        """The files ``path`` imports (anywhere in it) from outside ``package_dir``."""

        facts = self.facts(path)
        imports = list(facts.module_imports) + [entry for _name, function_imports, _strings in facts.functions for entry in function_imports]
        found = []
        for module, level, names in imports:
            found += [child for child in self.resolve(module, level, names, path)
                      if not child.startswith(package_dir.rstrip("/") + "/")]
        return sorted(set(found))

    def compress(self, files: set[str]) -> list[str]:
        """``files`` as few entries as possible: a folder stands for its files when every tracked Python file under it
        is in the set (never above a file's own package root, so a folder never adds another package's files)."""

        under = self._python_under()
        chosen: list[str] = []
        candidates = set()
        for path in files:
            root = self.package_root(path) or str(PurePosixPath(path).parent)
            folder = PurePosixPath(path).parent
            while str(folder) not in ("", ".") and (str(folder) == root or str(folder).startswith(root + "/")):
                candidates.add(str(folder))
                folder = folder.parent
        for folder in sorted(candidates, key=lambda value: (value.count("/"), value)):
            if any(folder.startswith(done + "/") for done in chosen):
                continue
            if under.get(folder) and under[folder] <= files:
                chosen.append(folder)
        rest = sorted(path for path in files if not any(path.startswith(folder + "/") for folder in chosen))
        return sorted([f"{folder}/" for folder in chosen] + rest)

    def _python_under(self) -> dict[str, frozenset[str]]:
        if not hasattr(self, "_under"):
            collected: dict[str, set[str]] = {}
            for path in self.tracked:
                if not path.endswith(".py") or not _is_project_code(path):
                    continue
                folder = PurePosixPath(path).parent
                while str(folder) not in ("", "."):
                    collected.setdefault(str(folder), set()).add(path)
                    folder = folder.parent
            self._under = {folder: frozenset(paths) for folder, paths in collected.items()}
        return self._under

    def folders_scope(self, folders: list[str]) -> list[str]:
        """Whole packages a gate tier or a producer runs: each package, its declared path dependencies, and every
        package its own code imports (the import closure of all its Python files, as package folders).

        WHY the closure too: a producer can reach its engine without declaring it (kinsim's traj_integration_tests
        imports bam_collision through a sys.path insert), and that engine is exactly what a reading depends on.
        """

        found: set[str] = set()
        seeds: list[str] = []
        for folder in folders:
            if not folder:
                continue
            root = self.package_root(f"{folder.rstrip('/')}/x") or folder.rstrip("/")
            found.add(root)
            found |= self.dependency_roots(root)
            seeds += [path for path in self.tracked if path.startswith(f"{root}/") and path.endswith(".py") and _is_project_code(path)]
        files, _truncated = self.closure(seeds, limit=max(CLOSURE_LIMIT, len(seeds) * 4))
        for path in files:
            owner = self.package_root(path)
            if owner is not None and not any(owner == known or owner.startswith(f"{known}/") for known in found):
                found.add(owner)
        return sorted(f"{folder}/" for folder in found)
