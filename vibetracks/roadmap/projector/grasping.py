"""project_grasping: bam-roadmap/1 for the grasping track, from grasp_bench's curriculum and its ledger, read-only.

Reads (and never writes, imports or runs) ``src/grasp_bench/curriculum.py`` (TIERS, ENVS, MODELS, CELLS, GATES,
PUBLISHED_AP), the dataclass fields of ``src/grasp_bench/contracts.py``, the frozen-protocol table of
``src/grasp_bench/runner.py``, and the append-only ledger ``out/ledger/runs.jsonl`` (one CellRun row per measured
model@env cell); git is asked only for the checkout's head and where each distinct row commit sits in its history.

How the curriculum becomes a roadmap:

- an axis (lane) per tier of TIERS, in order; a rung per environment of ENVS, in its tier's lane, in declared order;
- a gated environment (its id in GATES) has one ``gate_run`` criterion: met when a non-privileged model's best
  headline run on the frozen protocol has Wilson ``ci_lo`` >= GATES[env] (grasp_bench's own ``gallery.env_verdict``).
  Its evidence is that ledger row, bound to the row's own ``git_sha``; a row whose ``git_dirty`` is true (or unstated)
  is ``artifact-dirty``, so only a claim (``evaluate.git_record_binding``);
- an ungated environment (the datasets, the bandits, tiers 5-8) has a ``stated`` criterion: the curriculum gives it
  no bar, only prose, so it is never met, whatever is measured; its runs are shown as context evidence and KPIs;
- CELLS with status "needs" and a named blocker become the rung's blockers ("needs you");
- the loop writes no status of its own, so every rung's claim is ``missing`` (as kinsim reads a missing status.json),
  and no rung can show green until the loop states one. The gate criteria still show what the ledger proves.
"""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import links, model, proof
from .evaluate import Evaluator, Judgement, capped, git_record_binding
from .files import LINE_KEY, ProjectionError, file_sha256, read_jsonl
from .gitinfo import Repo
from .links import EvidenceBook, Roots

LOOP_ID = "grasping"
PACKAGE = Path("src") / "grasp_bench"
LEDGER = Path("out") / "ledger" / "runs.jsonl"
REQUIRED_TABLES = ("TIERS", "ENVS", "MODELS", "CELLS", "GATES")
GATED_METRIC = "top1_success"
CELL_STATUSES = ("wave1", "wave2", "needs", "later", "ref")
UNITS = {"top1_success": "success rate", "ap": "AP", "mean_reward": "fraction of optimal reward"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?(Z|[+-][0-9]{2}:[0-9]{2})?")


# ---------------------------------------------------------------- reading the curriculum without running it
class NotData(ValueError):
    """A construct the curriculum reader does not evaluate: it reads tables, it never runs code."""


@dataclass
class Constructor:
    """A dataclass the tables call (EnvSpec, ModelSpec, Cell): its fields in order and their defaults."""

    name: str
    fields: tuple[str, ...]
    defaults: dict[str, Callable[[], Any]]


class _TableReader:
    """Evaluates the expressions curriculum.py's tables are written in, over an ``ast`` tree, and nothing else.

    WHY an evaluator over the syntax tree, not ``exec`` with a stub ``contracts`` (decision, Oct 4 2026): the file is
    live code another session edits, and ``exec`` would run whatever it says next (an import of torch, a file write)
    inside the dashboard's server. Its tables are not plain literals (``*( ... for e in _TOY for m in (...))``,
    f-strings, ``range``), so ``ast.literal_eval`` cannot read them; this reads exactly those shapes: literals, names
    bound earlier in the module, comprehensions, f-strings, arithmetic, and calls to the dataclasses the tables build
    (read from their class bodies) and to ``range``/``tuple``/``list``/``dict``. Anything else is ``NotData``.
    """

    STEP_LIMIT = 500_000
    BUILTINS: dict[str, Callable[..., Any]] = {"range": range, "tuple": tuple, "list": list, "dict": dict}
    BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
              ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
    COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
               ast.GtE: operator.ge, ast.In: lambda left, right: left in right, ast.NotIn: lambda left, right: left not in right,
               ast.Is: operator.is_, ast.IsNot: operator.is_not}

    def __init__(self) -> None:
        self.names: dict[str, Any] = {}
        self.constructors: dict[str, Constructor] = {}
        self.item_lines: list[int] = []
        self.steps = 0

    def value(self, node: ast.AST, scope: Mapping[str, Any]) -> Any:
        self.steps += 1
        if self.steps > self.STEP_LIMIT:
            raise NotData(f"more than {self.STEP_LIMIT} evaluation steps")
        method = getattr(self, f"_{type(node).__name__}", None)
        if method is None:
            raise NotData(f"line {getattr(node, 'lineno', '?')}: {type(node).__name__} is not table data")
        return method(node, scope)

    def _Constant(self, node: ast.Constant, scope: Mapping[str, Any]) -> Any:
        return node.value

    def _Name(self, node: ast.Name, scope: Mapping[str, Any]) -> Any:
        if node.id in scope:
            return scope[node.id]
        if node.id in self.names:
            return self.names[node.id]
        raise NotData(f"line {node.lineno}: {node.id} is not a table bound earlier in the module")

    def _elements(self, elements: Sequence[ast.expr], scope: Mapping[str, Any]) -> list[Any]:
        values: list[Any] = []
        for element in elements:
            if isinstance(element, ast.Starred):
                values.extend(self._iterable(self.value(element.value, scope), element))
            else:
                values.append(self.value(element, scope))
        return values

    def _Tuple(self, node: ast.Tuple, scope: Mapping[str, Any]) -> tuple:
        return tuple(self._elements(node.elts, scope))

    def _List(self, node: ast.List, scope: Mapping[str, Any]) -> list:
        return self._elements(node.elts, scope)

    def _Dict(self, node: ast.Dict, scope: Mapping[str, Any]) -> dict:
        result: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values):
            if key is None:
                spread = self.value(value, scope)
                if not isinstance(spread, Mapping):
                    raise NotData(f"line {node.lineno}: ** of a non-mapping")
                result.update(spread)
            else:
                result[self.value(key, scope)] = self.value(value, scope)
        return result

    def _JoinedStr(self, node: ast.JoinedStr, scope: Mapping[str, Any]) -> str:
        return "".join(str(self.value(part, scope)) for part in node.values)

    def _FormattedValue(self, node: ast.FormattedValue, scope: Mapping[str, Any]) -> str:
        value = self.value(node.value, scope)
        value = {115: str, 114: repr, 97: ascii}.get(node.conversion, lambda item: item)(value)
        return format(value, self.value(node.format_spec, scope) if node.format_spec is not None else "")

    def _BinOp(self, node: ast.BinOp, scope: Mapping[str, Any]) -> Any:
        function = self.BINARY.get(type(node.op))
        if function is None:
            raise NotData(f"line {node.lineno}: operator {type(node.op).__name__}")
        return function(self.value(node.left, scope), self.value(node.right, scope))

    def _UnaryOp(self, node: ast.UnaryOp, scope: Mapping[str, Any]) -> Any:
        operand = self.value(node.operand, scope)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Not):
            return not operand
        raise NotData(f"line {node.lineno}: operator {type(node.op).__name__}")

    def _Compare(self, node: ast.Compare, scope: Mapping[str, Any]) -> bool:
        left = self.value(node.left, scope)
        for operation, comparator in zip(node.ops, node.comparators):
            right = self.value(comparator, scope)
            if not self.COMPARE[type(operation)](left, right):
                return False
            left = right
        return True

    def _BoolOp(self, node: ast.BoolOp, scope: Mapping[str, Any]) -> Any:
        result: Any = None
        for operand in node.values:
            result = self.value(operand, scope)
            if isinstance(node.op, ast.And) and not result or isinstance(node.op, ast.Or) and result:
                return result
        return result

    def _IfExp(self, node: ast.IfExp, scope: Mapping[str, Any]) -> Any:
        return self.value(node.body if self.value(node.test, scope) else node.orelse, scope)

    def _Subscript(self, node: ast.Subscript, scope: Mapping[str, Any]) -> Any:
        container = self.value(node.value, scope)
        index = node.slice
        if isinstance(index, ast.Slice):
            key: Any = slice(*(self.value(part, scope) if part is not None else None for part in (index.lower, index.upper, index.step)))
        else:
            key = self.value(index, scope)
        try:
            return container[key]
        except (KeyError, IndexError, TypeError) as error:
            raise NotData(f"line {node.lineno}: {error!r}") from error

    def _iterable(self, value: Any, node: ast.AST) -> list[Any]:
        if isinstance(value, Mapping):
            return list(value)
        if isinstance(value, (list, tuple, range, str)):
            if len(value) > self.STEP_LIMIT:
                raise NotData(f"line {getattr(node, 'lineno', '?')}: {len(value)} items")
            return list(value)
        raise NotData(f"line {getattr(node, 'lineno', '?')}: {type(value).__name__} is not iterable table data")

    def _comprehension(self, generators: Sequence[ast.comprehension], scope: Mapping[str, Any],
                       emit: Callable[[Mapping[str, Any]], None]) -> None:
        def loop(index: int, inner: Mapping[str, Any]) -> None:
            if index == len(generators):
                emit(inner)
                return
            generator = generators[index]
            if generator.is_async:
                raise NotData(f"line {generator.iter.lineno}: async comprehension")
            items = self._iterable(self.value(generator.iter, inner), generator.iter)
            # WHY the item's own line: a record built in a comprehension over a written-out tuple ("(0, 'one elongated
            # box', ...)") is declared on that tuple's line, which is where a reader should land.
            literal = isinstance(generator.iter, (ast.Tuple, ast.List)) and not any(
                isinstance(element, ast.Starred) for element in generator.iter.elts)
            for position, item in enumerate(items):
                bound = dict(inner)
                self._bind(generator.target, item, bound)
                if literal:
                    self.item_lines.append(generator.iter.elts[position].lineno)
                try:
                    if all(self.value(condition, bound) for condition in generator.ifs):
                        loop(index + 1, bound)
                finally:
                    if literal:
                        self.item_lines.pop()

        loop(0, scope)

    def _bind(self, target: ast.AST, value: Any, scope: dict[str, Any]) -> None:
        if isinstance(target, ast.Name):
            scope[target.id] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            values = self._iterable(value, target)
            if len(values) != len(target.elts):
                raise NotData(f"line {target.lineno}: cannot unpack {len(values)} values into {len(target.elts)}")
            for element, item in zip(target.elts, values):
                self._bind(element, item, scope)
            return
        raise NotData(f"line {getattr(target, 'lineno', '?')}: {type(target).__name__} as a loop target")

    def _GeneratorExp(self, node: ast.GeneratorExp, scope: Mapping[str, Any]) -> list[Any]:
        values: list[Any] = []
        self._comprehension(node.generators, scope, lambda inner: values.append(self.value(node.elt, inner)))
        return values

    _ListComp = _GeneratorExp

    def _DictComp(self, node: ast.DictComp, scope: Mapping[str, Any]) -> dict:
        values: dict[Any, Any] = {}
        self._comprehension(node.generators, scope,
                            lambda inner: values.__setitem__(self.value(node.key, inner), self.value(node.value, inner)))
        return values

    def _Call(self, node: ast.Call, scope: Mapping[str, Any]) -> Any:
        if not isinstance(node.func, ast.Name):
            raise NotData(f"line {node.lineno}: a call to {ast.unparse(node.func)}")
        arguments = self._elements(node.args, scope)
        keywords: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                raise NotData(f"line {node.lineno}: ** in a call")
            keywords[keyword.arg] = self.value(keyword.value, scope)
        name = node.func.id
        if name in self.constructors:
            return self._construct(self.constructors[name], node, arguments, keywords)
        if name in self.BUILTINS and name not in scope and name not in self.names:
            if name == "range" and (keywords or not all(isinstance(argument, int) for argument in arguments)):
                raise NotData(f"line {node.lineno}: range over non-integers")
            return self.BUILTINS[name](*arguments, **keywords)
        raise NotData(f"line {node.lineno}: a call to {name}")

    def _construct(self, constructor: Constructor, node: ast.Call, arguments: list[Any], keywords: dict[str, Any]) -> dict[str, Any]:
        if len(arguments) > len(constructor.fields):
            raise NotData(f"line {node.lineno}: {constructor.name} takes {len(constructor.fields)} fields, given {len(arguments)}")
        record = dict(zip(constructor.fields, arguments))
        for key, value in keywords.items():
            if key not in constructor.fields or key in record:
                raise NotData(f"line {node.lineno}: {constructor.name} has no field {key} (or it is given twice)")
            record[key] = value
        for name in constructor.fields:
            if name not in record:
                if name not in constructor.defaults:
                    raise NotData(f"line {node.lineno}: {constructor.name} needs {name}")
                record[name] = constructor.defaults[name]()
        record[LINE_KEY] = self.item_lines[-1] if self.item_lines else node.lineno
        return record

    # ------------------------------------------------------------ dataclass bodies
    def dataclasses(self, statements: Iterable[ast.stmt]) -> dict[str, Constructor]:
        """``@dataclass`` classes among ``statements``: their annotated fields, in order, with their defaults."""

        found = {}
        for statement in statements:
            if not isinstance(statement, ast.ClassDef) or not any(_is_dataclass(decorator) for decorator in statement.decorator_list):
                continue
            fields: list[str] = []
            defaults: dict[str, Callable[[], Any]] = {}
            for item in statement.body:
                if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                    continue
                if "ClassVar" in ast.unparse(item.annotation):
                    continue
                fields.append(item.target.id)
                if item.value is not None:
                    defaults[item.target.id] = self._default(item.value)
            found[statement.name] = Constructor(statement.name, tuple(fields), defaults)
        return found

    def _default(self, node: ast.expr) -> Callable[[], Any]:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "field":
            for keyword in node.keywords:
                if keyword.arg == "default_factory" and isinstance(keyword.value, ast.Name) and keyword.value.id in ("dict", "list", "tuple", "set"):
                    factory = {"dict": dict, "list": list, "tuple": tuple, "set": set}[keyword.value.id]
                    return factory
                if keyword.arg == "default":
                    node = keyword.value
                    break
            else:
                return _unreadable(f"line {node.lineno}: a field default this reader does not evaluate")
        try:
            value = self.value(node, {})
        except NotData as error:
            return _unreadable(str(error))
        return lambda: value


def _unreadable(why: str) -> Callable[[], Any]:
    def default() -> Any:
        raise NotData(why)
    return default


def _is_dataclass(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return (isinstance(target, ast.Name) and target.id == "dataclass") or (isinstance(target, ast.Attribute) and target.attr == "dataclass")


def _parse(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError) as error:
        raise ProjectionError(f"cannot read {path}: {error}") from error


@dataclass
class Curriculum:
    """curriculum.py's tables, the line each is assigned on, its ``#:`` comment, and what could not be read."""

    tables: dict[str, Any]
    lines: dict[str, int]
    comments: dict[str, str]
    skipped: dict[str, str]
    contracts: dict[str, Constructor] = field(default_factory=dict)
    key_lines: dict[str, dict[Any, int]] = field(default_factory=dict)  # a dict table's entries: GATES["toy/x"] -> its line


def read_curriculum(curriculum_path: Path, contracts_path: Path) -> Curriculum:
    """The curriculum's tables, read from its syntax tree (``_TableReader``); nothing in either file is executed."""

    reader = _TableReader()
    contracts = reader.dataclasses(_parse(contracts_path).body) if contracts_path.is_file() else {}
    tree = _parse(curriculum_path)
    source_lines = curriculum_path.read_text(encoding="utf-8").split("\n")
    tables: dict[str, Any] = {}
    lines: dict[str, int] = {}
    comments: dict[str, str] = {}
    skipped: dict[str, str] = {}
    key_lines: dict[str, dict[Any, int]] = {}
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and (statement.module or "").split(".")[-1] == "contracts":
            for alias in statement.names:
                if alias.name in contracts:
                    reader.constructors[alias.asname or alias.name] = contracts[alias.name]
            continue
        if isinstance(statement, ast.ClassDef):
            reader.constructors.update(reader.dataclasses([statement]))
            continue
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            name, value = statement.targets[0].id, statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value is not None:
            name, value = statement.target.id, statement.value
        else:
            continue
        lines[name] = statement.lineno
        comments[name] = _comment_above(source_lines, statement.lineno)
        if isinstance(value, ast.Dict):
            key_lines[name] = {node.value: node.lineno for node in value.keys if isinstance(node, ast.Constant)}
        try:
            tables[name] = reader.names[name] = reader.value(value, {})
        except (NotData, TypeError, ValueError, ZeroDivisionError, RecursionError) as error:
            skipped[name] = str(error)
            tables.pop(name, None)
            reader.names.pop(name, None)
    for name in REQUIRED_TABLES:
        if name not in tables:
            why = f": {skipped[name]}" if name in skipped else ""
            raise ProjectionError(f"{curriculum_path}: {name} is not table data (or is missing), so it is not read{why}")
    return Curriculum(tables, lines, comments, skipped, contracts, key_lines)


def _comment_above(source_lines: Sequence[str], line: int) -> str:
    """The ``#:`` comment block directly above a 1-based line (the module's documentation for that table)."""

    found: list[str] = []
    index = line - 2
    while index >= 0 and source_lines[index].lstrip().startswith("#:"):
        found.insert(0, source_lines[index].lstrip()[2:].strip())
        index -= 1
    return " ".join(found)


@dataclass
class FrozenProtocols:
    """runner.py's ``DEFAULT_PROTOCOLS`` (family -> (name, episodes)) and ``FALLBACK_PROTOCOL``, and EvalProtocol's seed."""

    defaults: dict[str, tuple[str, int]]
    fallback: tuple[str, int]
    seed: Any
    lines: dict[str, int]


def read_frozen_protocols(runner_path: Path, contracts: Mapping[str, Constructor]) -> FrozenProtocols:
    """The frozen eval protocol as grasp_bench's code defines it, read as literals (Oct 4 2026).

    WHY these three places: ``gallery.is_frozen_protocol`` compares a run's protocol with ``runner.default_protocol``,
    whose name and episodes come from ``runner.DEFAULT_PROTOCOLS`` by env family (else ``FALLBACK_PROTOCOL``) and whose
    seed is ``contracts.EvalProtocol``'s default; the split must be "test" and k is ``runner.default_k``.
    """

    tables: dict[str, Any] = {}
    lines: dict[str, int] = {}
    for statement in _parse(runner_path).body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            name, value = statement.targets[0].id, statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value is not None:
            name, value = statement.target.id, statement.value
        else:
            continue
        if name in ("DEFAULT_PROTOCOLS", "FALLBACK_PROTOCOL"):
            try:
                tables[name], lines[name] = ast.literal_eval(value), statement.lineno
            except (ValueError, TypeError, SyntaxError) as error:
                raise ProjectionError(f"{runner_path}: {name} is not literal data ({error})") from error
    if "DEFAULT_PROTOCOLS" not in tables or "FALLBACK_PROTOCOL" not in tables:
        raise ProjectionError(f"{runner_path} defines no DEFAULT_PROTOCOLS / FALLBACK_PROTOCOL, so no run can be shown frozen")
    protocol = contracts.get("EvalProtocol")
    if protocol is None or "seed" not in protocol.defaults:
        raise ProjectionError("contracts.py's EvalProtocol states no default seed, so no run can be shown frozen")
    try:
        seed = protocol.defaults["seed"]()
    except NotData as error:
        raise ProjectionError(f"contracts.py's EvalProtocol seed: {error}") from error
    defaults = {str(family): (str(pair[0]), int(pair[1])) for family, pair in dict(tables["DEFAULT_PROTOCOLS"]).items()}
    fallback = tables["FALLBACK_PROTOCOL"]
    return FrozenProtocols(defaults, (str(fallback[0]), int(fallback[1])), seed, lines)


# ---------------------------------------------------------------- grasp_bench's own rules, restated over plain rows
def env_family(env_id: str) -> str:
    """``registry.env_family``: the env id's first path segment."""

    return env_id.split("/", 1)[0]


def frozen_protocol(env: Mapping[str, Any], protocols: FrozenProtocols) -> dict[str, Any]:
    """``runner.default_protocol(env)`` plus ``runner.default_k(spec)``, as ``gallery.is_frozen_protocol`` compares them."""

    name, episodes = protocols.defaults.get(env_family(str(env["id"])), protocols.fallback)
    k = max(int(env.get("request_k") or 1), int(env.get("min_grasps") or 1), 1)
    return {"name": name, "seed": protocols.seed, "episodes": episodes, "split": "test", "k": k}


def is_frozen(row: Mapping[str, Any], frozen: Mapping[str, Any] | None) -> bool:
    """``gallery.is_frozen_protocol``: the frozen name, seed and episodes, the test split, no protocol or env options,
    every episode scored, and the default k."""

    if frozen is None:
        return False
    protocol = row.get("protocol") if isinstance(row.get("protocol"), Mapping) else {}
    return (protocol.get("name") == frozen["name"] and protocol.get("seed") == frozen["seed"]
            and protocol.get("episodes") == frozen["episodes"] and protocol.get("split") == "test"
            and not protocol.get("options") and not row.get("env_options") and row.get("n") == frozen["episodes"]
            and protocol.get("k") == frozen["k"])


def is_privileged(row: Mapping[str, Any], families: Mapping[str, str]) -> bool:
    """``gallery._privileged``: privileged by the curriculum's spec OR by the input the run recorded it read."""

    return (row.get("model_info") or {}).get("input") == "privileged" or families.get(str(row.get("model"))) == "privileged"


def clears_gate(row: Mapping[str, Any], gate: float | None, families: Mapping[str, str]) -> bool:
    """``gallery.clears_gate``: a non-privileged top-1 run whose Wilson lower bound reaches its env's gate."""

    ci_lo = _number(row.get("ci_lo"))
    return (gate is not None and row.get("metric") == GATED_METRIC and ci_lo is not None and ci_lo >= gate
            and not is_privileged(row, families))


def headline_runs(rows: Sequence[Mapping[str, Any]], frozen_of: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """``gallery.headline_runs``: one row per cell: a frozen-protocol row first, then the largest n, then the latest
    start, then the last written. (A smoke written after the frozen eval never replaces it; a frozen re-run does.)"""

    best: dict[str, tuple[tuple, Mapping[str, Any]]] = {}
    for index, row in enumerate(rows):
        cell_id = str(row.get("cell_id"))
        key = (is_frozen(row, frozen_of.get(str(row.get("env")))), _count(row.get("n")), str(row.get("started_at") or ""), index)
        if cell_id not in best or key > best[cell_id][0]:
            best[cell_id] = (key, row)
    return {cell_id: pair[1] for cell_id, pair in best.items()}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value else None


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


# ---------------------------------------------------------------- the projection
def project_grasping(grasp_bench_dir: Path, *, now: str, head: str | None = None,
                     ledger_path: Path | None = None) -> dict[str, Any]:
    """bam-roadmap/1 for the grasping track, judged at ``head`` (default: the checkout's HEAD).

    ``ledger_path`` defaults to ``<grasp_bench_dir>/out/ledger/runs.jsonl``, the ledger's own default (``$GRASP_BENCH_OUT``
    is not read here: the projection must depend only on the paths it is given, so the validator can project it again).
    """

    bench = Path(grasp_bench_dir).resolve()
    package = bench / PACKAGE
    curriculum_path = package / "curriculum.py"
    if not curriculum_path.is_file():
        raise ProjectionError(f"{curriculum_path} does not exist: {bench} is not a grasp_bench package")
    curriculum = read_curriculum(curriculum_path, package / "contracts.py")
    protocols = read_frozen_protocols(package / "runner.py", curriculum.contracts)
    ledger = Path(ledger_path).resolve() if ledger_path is not None else bench / LEDGER
    repo = Repo(bench, head)
    if not repo.available:
        raise ProjectionError(f"{bench} is not inside a git checkout")
    roots = Roots(repo=repo.root, data_home=ledger.parent.parent, repo_aliases=repo.other_checkouts())
    return _GraspingProjector(bench=bench, curriculum=curriculum, protocols=protocols, ledger=ledger, repo=repo,
                              roots=roots).document(now)


def rung_id_of(env_id: str) -> str:
    """An env id as a bam-roadmap/1 identifier: "toy/xy_rz" -> "toy.xy_rz" (the env id stays verbatim in ``x.env``)."""

    return env_id.replace("/", ".")


def _pointer(*parts: Any) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


class _GraspingProjector:
    def __init__(self, *, bench: Path, curriculum: Curriculum, protocols: FrozenProtocols, ledger: Path, repo: Repo,
                 roots: Roots) -> None:
        self.bench, self.curriculum, self.protocols, self.ledger, self.repo, self.roots = bench, curriculum, protocols, ledger, repo, roots
        self.package = bench / PACKAGE
        self.curriculum_path = self.package / "curriculum.py"
        self.evaluator = Evaluator(repo, roots)
        self.warnings: list[str] = []
        tables = curriculum.tables
        self.tiers = self._tiers(tables["TIERS"])
        self.envs = self._envs(tables["ENVS"])
        self.env_index = {env["id"]: position for position, env in enumerate(self.envs)}
        self.families = {str(row.get("id")): str(row.get("family")) for row in tables["MODELS"] if isinstance(row, Mapping)}
        self.cells = [cell for cell in tables["CELLS"] if isinstance(cell, Mapping) and cell.get("env") in self.env_index]
        self.gates = {str(env_id): float(gate) for env_id, gate in dict(tables["GATES"]).items()
                      if isinstance(gate, (int, float)) and env_id in self.env_index}
        self.published = tables.get("PUBLISHED_AP") if isinstance(tables.get("PUBLISHED_AP"), Mapping) else {}
        self.frozen_of = {env["id"]: frozen_protocol(env, protocols) for env in self.envs}
        self.rows = read_jsonl(ledger, numbered=True) if ledger.is_file() else []
        self.heads = headline_runs(self.rows, self.frozen_of)
        self.verdicts = {env["id"]: self._verdict(env["id"]) for env in self.envs}
        self.depends = self._dependencies()
        self.frontier = self._frontier()
        self.derived: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------ the tables
    def _tiers(self, tiers: Any) -> dict[int, str]:
        if not isinstance(tiers, Mapping) or not all(isinstance(tier, int) for tier in tiers):
            raise ProjectionError(f"{self.curriculum_path}: TIERS must map tier numbers to titles")
        return {tier: str(tiers[tier]) for tier in sorted(tiers)}

    def _envs(self, envs: Any) -> list[Mapping[str, Any]]:
        rows = [env for env in envs if isinstance(env, Mapping) and isinstance(env.get("id"), str) and isinstance(env.get("tier"), int)]
        if not rows or len(rows) != len(envs):
            raise ProjectionError(f"{self.curriculum_path}: ENVS must be EnvSpec rows that each carry an id and a tier")
        ids = [rung_id_of(env["id"]) for env in rows]
        bad = [env["id"] for env in rows if not _IDENTIFIER.fullmatch(rung_id_of(env["id"]))]
        if bad or len(set(ids)) != len(ids):
            raise ProjectionError(f"{self.curriculum_path}: env ids {bad or ids} do not map to unique rung ids")
        unknown = sorted({env["tier"] for env in rows} - set(self.tiers))
        if unknown:
            raise ProjectionError(f"{self.curriculum_path}: ENVS name tiers {unknown} that TIERS does not have")
        return rows

    def _env_ids(self, tier: int) -> list[str]:
        return [env["id"] for env in self.envs if env["tier"] == tier]

    def _dependencies(self) -> dict[str, list[str]]:
        """What each env waits on.

        WHY this rule (the dispatcher's brief, Oct 4 2026, plus the two calls it left open): a tier whose envs are all
        gated is a ladder, beaten rung by rung in its declared order (toy x -> xy -> xy_rz -> xy_rz_w, MuJoCo stages
        0 -> 5: GATES gives each its own bar), so each env past the first waits on the one before it. Every other env
        (the first of a ladder, every env of an ungated tier: dataset splits and sim tracks measured side by side)
        waits on the gated envs of the nearest lower tier that has any. Not just "the previous tier": an ungated tier
        is measured, never beaten, so it cannot hold the next tier back, while the last gates below it still do
        ("get it working for simple cases first"). Reversible: the rule is this one function.
        """

        depends: dict[str, list[str]] = {}
        gated_below: list[str] = []
        for tier in self.tiers:
            envs = self._env_ids(tier)
            ladder = bool(envs) and all(env_id in self.gates for env_id in envs)
            for position, env_id in enumerate(envs):
                depends[env_id] = [envs[position - 1]] if ladder and position > 0 else list(gated_below)
            gated = [env_id for env_id in envs if env_id in self.gates]
            if gated:
                gated_below = gated
        return depends

    def _cells_of(self, env_id: str) -> list[Mapping[str, Any]]:
        return [cell for cell in self.cells if cell.get("env") == env_id]

    def _cell_counts(self, env_id: str) -> dict[str, Any]:
        cells = self._cells_of(env_id)
        cell_ids = [f"{cell.get('model')}@{env_id}" for cell in cells]  # curriculum.Cell.id
        wave1 = [cell_id for cell, cell_id in zip(cells, cell_ids) if cell.get("status") == "wave1"]
        by_status: dict[str, int] = {}
        for cell in cells:
            by_status[str(cell.get("status"))] = by_status.get(str(cell.get("status")), 0) + 1
        return {"wave1_planned": len(wave1), "wave1_measured": sum(1 for cell_id in wave1 if cell_id in self.heads),
                "planned": len(cells), "measured": sum(1 for cell_id in cell_ids if cell_id in self.heads),
                "by_status": {status: by_status[status] for status in (*CELL_STATUSES, *sorted(set(by_status) - set(CELL_STATUSES)))
                              if status in by_status},
                "wave1_unmeasured": [cell_id for cell_id in wave1 if cell_id not in self.heads]}

    # ------------------------------------------------------------ beaten (gallery.env_verdict)
    def _verdict(self, env_id: str) -> dict[str, Any]:
        """gallery.env_verdict and env_provisional over the headline rows: the env's candidates, winners and best run."""

        heads = [row for row in self.heads.values() if row.get("env") == env_id]
        candidates = [row for row in heads if _number(row.get("value")) is not None and not is_privileged(row, self.families)]
        gate = self.gates.get(env_id)
        frozen = self.frozen_of[env_id]
        winners = [row for row in candidates if clears_gate(row, gate, self.families) and is_frozen(row, frozen)]
        best = max(candidates, key=lambda row: (_number(row.get("value")), _number(row.get("ci_lo")) if _number(row.get("ci_lo")) is not None else -1),
                   default=None)
        if winners:
            best = max(winners, key=lambda row: _number(row.get("ci_lo")))
        provisional = not winners and any(clears_gate(row, gate, self.families) and not is_frozen(row, frozen) for row in heads)
        return {"beaten": bool(winners), "winners": winners, "best": best, "provisional": provisional, "heads": heads,
                "frozen_runs": [row for row in candidates if is_frozen(row, frozen)]}

    def _frontier(self) -> list[str]:
        """The lowest tier whose wave-1 cells are incomplete or whose gated envs are not all beaten: its unbeaten envs.

        WHY the unmeasured envs when every env there is beaten: then the tier is unfinished only because a wave-1 cell
        has no row yet, and an empty frontier would read as "nothing left" while the loop still has that tier to run.
        """

        for tier in self.tiers:
            envs = self._env_ids(tier)
            incomplete = [env_id for env_id in envs if self._cell_counts(env_id)["wave1_unmeasured"]]
            unbeaten = [env_id for env_id in envs if not self.verdicts[env_id]["beaten"]]
            if incomplete or any(env_id in self.gates for env_id in unbeaten):
                return [rung_id_of(env_id) for env_id in (unbeaten or incomplete)]
        return []

    # ------------------------------------------------------------ document
    def document(self, now: str) -> dict[str, Any]:
        for env in self.envs:
            self._rung(env["id"])
        rungs = [self.derived[env["id"]] for env in self.envs]
        axes = [{"id": f"tier-{tier}", "title": f"Tier {tier} · {_tier_short(title)}", "order": position}
                for position, (tier, title) in enumerate(self.tiers.items())]
        edges = [{"from": rung_id_of(parent), "to": rung_id_of(env_id), "kind": "prerequisite",
                  "via": (f"tier {self._tier(env_id)} order" if self._tier(parent) == self._tier(env_id)
                          else f"the gated envs of tier {self._tier(parent)}")}
                 for env_id in self.env_index for parent in self.depends[env_id]]
        gated = [env["id"] for env in self.envs if env["id"] in self.gates]
        wave1 = [self._cell_counts(env["id"]) for env in self.envs]
        return {
            "schema": model.SCHEMA_ID,
            "loop": LOOP_ID,
            "title": "Grasping curriculum",
            "generated_at": now,
            "as_of": {"head": self.repo.head, "branch": self.repo.branch, "context": {}},
            "roots": self.roots.as_dict(),
            "sources": self._sources(),
            "rules": {"proof_strengths": list(model.PROOF_STRENGTHS), "status_rule": "bam_roadmap.model.derive_status",
                      "loop_rules": {**self._link_at("file", self.package / "gallery.py",
                                                     proof.json_line_of(self.package / "gallery.py", "def env_verdict")), "pointer": ""}},
            # WHY wave and phase are null: the loop states neither (no status file; its phase lives only in a scratch
            # run log), and the schema requires the keys.
            "summary": {"wave": None, "phase": None, "frontier": self.frontier, "milestone": None, "links": {},
                        "beaten": [rung_id_of(env_id) for env_id in gated if self.verdicts[env_id]["beaten"]],
                        "gated": [rung_id_of(env_id) for env_id in gated],
                        "cells": {"wave1_planned": sum(row["wave1_planned"] for row in wave1),
                                  "wave1_measured": sum(row["wave1_measured"] for row in wave1),
                                  "planned": sum(row["planned"] for row in wave1), "measured": sum(row["measured"] for row in wave1),
                                  "ledger_rows": len(self.rows)}},
            "counts": proof.counts(rungs),
            "warnings": self._warnings(),
            "axes": axes,
            "where": proof.where_rows(axes, rungs),
            "rungs": rungs,
            "edges": edges,
            "work": [],
            "unresolved": proof.unresolved_list(rungs),
            "scopes": {},
        }

    def _link_at(self, kind: str, path: Path, line: int | None, *, label: str | None = None) -> dict[str, Any]:
        """A link to a line this projection has just read in ``path`` (a ledger row, a table entry).

        WHY the line is set here and not passed to ``links.link``: that checks the line against ``links.count_lines``,
        which is cached per path for the life of the process, and the ledger grows by a row every few seconds; in the
        dashboard's long-lived server a new row would read "past the end" and its proof would fall to a claim. The
        line was read from the file moments ago (``read_jsonl``'s numbering, the syntax tree), so it is known to exist.
        """

        found = links.link(kind, str(path), self.roots, label=label)
        found["line"] = line if found["exists"] else None
        return found

    def _tier(self, env_id: str) -> int:
        return self.envs[self.env_index[env_id]]["tier"]

    def _sources(self) -> list[dict[str, Any]]:
        rows = []
        for path, role in ((self.curriculum_path, "curriculum"), (self.package / "contracts.py", "contracts"),
                           (self.package / "runner.py", "frozen protocol"), (self.ledger, "ledger")):
            entry = links.link("file", str(path), self.roots)
            entry.update({"role": role, "sha256": file_sha256(path) if path.is_file() else None})
            rows.append(entry)
        return rows

    def _warnings(self) -> list[str]:
        warnings = ["the loop writes no status of its own: every rung's claim reads missing, so none can show green; "
                    "each gate criterion still shows what the ledger proves"]
        if not self.ledger.is_file():
            warnings.append(f"no ledger at {self.ledger}: nothing is measured yet")
        warnings += [f"curriculum.py {name} is not table data, so it was skipped ({why})"
                     for name, why in self.curriculum.skipped.items()]
        strays = sorted({str(row.get("env")) for row in self.rows if row.get("env") not in self.env_index})
        if strays:
            warnings.append(f"ledger rows name envs the curriculum does not have: {', '.join(strays)}")
        dirty = sum(1 for row in self.rows if row.get("git_dirty") is not False)
        if dirty:
            warnings.append(f"{dirty} of {len(self.rows)} ledger rows ran on a dirty or unrecorded tree, so they are claims")
        unnamed = [f"{cell.get('model')}@{cell.get('env')}" for cell in self.cells if cell.get("status") == "needs" and not str(cell.get("why") or "").strip()]
        if unnamed:
            warnings.append(f"needs cells with no named blocker (not shown as blockers): {', '.join(unnamed)}")
        return warnings + self.warnings

    # ------------------------------------------------------------ one rung
    def _rung(self, env_id: str) -> dict[str, Any]:
        env = self.envs[self.env_index[env_id]]
        rung_id = rung_id_of(env_id)
        book = EvidenceBook()
        gate = self.gates.get(env_id)
        verdict = self.verdicts[env_id]
        if gate is not None:
            done_source = self._source("GATES", _pointer("GATES", env_id), key=env_id)
            text = (f"the best non-privileged headline run on the frozen protocol ({self.frozen_of[env_id]['name']}) has "
                    f"a Wilson 95% lower bound >= {gate:g}")
            criteria = [self._gate_criterion(env_id, rung_id, gate, text, done_source, book)]
        else:
            done_source = self._source("GATES", _pointer("GATES"))
            text = self._ungated_text(env)
            criteria = [self._measured_criterion(env, rung_id, text, done_source)]
        for row in sorted(verdict["heads"], key=lambda row: (-(_number(row.get("value")) or 0.0), row.get(LINE_KEY) or 0)):
            book.add(self._run_item(row, None), key=("run", str(row.get("run_id"))))
        if self.depends[env_id]:
            criteria.append(self._prerequisites_criterion(env_id, rung_id, done_source))
        claimed = "missing"  # WHY: the loop writes no status of its own (kinsim reads a missing status.json the same way)
        status, reason = model.derive_status(claimed, criteria)
        counts = self._cell_counts(env_id)
        best = verdict["best"]
        self.derived[env_id] = proof.finish_rung({
            "id": rung_id, "axis": f"tier-{env['tier']}", "title": f"{env_id} · {env.get('title') or ''}".rstrip(" ·"),
            "adds": f"{env.get('dof')} DoF, {env.get('fidelity')}, {env.get('sensor')}" if env.get("dof") else None,
            "order": self.env_index[env_id], "wave": None,
            "depends_on": [rung_id_of(parent) for parent in self.depends[env_id]], "alias_of": None,
            "status": status, "claimed_status": claimed, "status_reason": reason,
            "claimed_by": {"source": None, "event": None},
            "frontier": rung_id in self.frontier,
            "done_when": {"rule": "all", "text": text, "source": done_source},
            "criteria": criteria, "support": None, "evidence": book.items, "history": [],
            "blockers": self._blockers(env_id),
            "kpis": self._kpis(env_id),
            "notes": [note for note in (env.get("notes"),) if note],
            "x": {"env": env_id, "tier": env["tier"], "metric": env.get("metric"), "dof": env.get("dof"),
                  "fidelity": env.get("fidelity"), "sensor": env.get("sensor"), "gate": gate,
                  "frozen_protocol": self.frozen_of[env_id], "beaten": verdict["beaten"], "provisional": verdict["provisional"],
                  "best": self._best_facts(best, verdict["beaten"]), "cells": counts,
                  "published_ap": dict(self.published.get(env_id) or {})},
        }, book)
        return self.derived[env_id]

    def _source(self, name: str, pointer: str, *, key: Any = None) -> dict[str, Any]:
        """A link to curriculum.py at the line a table (or one of its entries) is written on, with its pointer."""

        line = (self.curriculum.key_lines.get(name) or {}).get(key) if key is not None else None
        found = self._link_at("file", self.curriculum_path, line or self.curriculum.lines.get(name))
        found["pointer"] = pointer
        return found

    def _ungated_text(self, env: Mapping[str, Any]) -> str:
        rule = self.curriculum.comments.get("PUBLISHED_AP") if env.get("metric") == "ap" else ""
        base = f"no gate in curriculum.GATES for {env['id']}: measured ({env.get('metric')}), never beaten"
        return f"{base}. {rule}" if rule else base

    def _gate_criterion(self, env_id: str, rung_id: str, gate: float, text: str, source: dict, book: EvidenceBook) -> dict[str, Any]:
        """The gate on the ledger rows themselves (gallery.env_verdict), judged by the shared evaluator.

        WHY the strongest winner, not the gallery's highest ci_lo: any frozen non-privileged run at or above the gate
        beats the env, and a clean-tree one proves it at record strength where a dirty one is only the loop's word, so
        the target rests on the strongest proof (``proof.choose``'s order), then the highest Wilson lower bound.
        """

        verdict = self.verdicts[env_id]
        frozen = self.frozen_of[env_id]
        label = f"{env_id}: Wilson LB >= {gate:g} on {frozen['name']} (n={frozen['episodes']}, seed {frozen['seed']})"
        target_link = {**self._source("GATES", _pointer("GATES", env_id), key=env_id),
                       "kind": "gate", "label": label}
        target_link.pop("pointer")
        spec = {"rule": "wilson_lb", "gate": gate, "metric": GATED_METRIC, "protocol": frozen, "privileged_counts": False,
                "via": "grasp_bench gallery.env_verdict"}
        if verdict["winners"]:
            judged = [(row, self._judge(row, "passed", f"{row.get('run_id')} ({row.get('model')}): Wilson LB "
                                                       f"{_number(row.get('ci_lo')):.4f} >= {gate:g} over n={row.get('n')}"))
                      for row in verdict["winners"]]
            row, judgement = min(judged, key=lambda pair: (proof.standing(pair[1]), not pair[1].placed,
                                                           model.STRENGTHS.index(pair[1].strength) if pair[1].strength else 9,
                                                           -(_number(pair[0].get("ci_lo")) or 0.0), pair[0].get(LINE_KEY) or 0))
            if len(judged) > 1:
                judgement.note += f"; {len(judged) - 1} other frozen run(s) also clear it"
            evidence = [book.add(self._run_item(row, "passed"), key=("run", str(row.get("run_id"))))]
        elif verdict["frozen_runs"]:
            row = max(verdict["frozen_runs"], key=lambda row: (_number(row.get("ci_lo")) if _number(row.get("ci_lo")) is not None else -1.0,
                                                               _number(row.get("value")) or 0.0))
            ci_lo = _number(row.get("ci_lo"))
            judgement = self._judge(row, "failed", f"best frozen run {row.get('run_id')} ({row.get('model')}): Wilson LB "
                                                   f"{f'{ci_lo:.4f}' if ci_lo is not None else 'none'} < {gate:g}")
            evidence = [book.add(self._run_item(row, "failed"), key=("run", str(row.get("run_id"))))]
        else:
            why = f"no non-privileged run on the frozen {frozen['name']} protocol yet"
            if verdict["provisional"]:
                why += "; a smoke or re-seeded run clears it (provisional, not proof)"
            judgement, evidence = Judgement("unknown", None, [], why), []
        target = proof.target_entry(target_link, judgement, evidence, spec=spec)
        return proof.reduce(f"{rung_id}#gate", "gate_run", "test", f"Wilson LB >= {gate:g} on {frozen['name']}", text,
                            source, [target], empty_reason="")

    def _judge(self, row: Mapping[str, Any], result: str, note: str) -> Judgement:
        """One ledger row at the commit its own ``git_sha`` names, capped by its own ``git_dirty`` (Codex G04, H02)."""

        binding = git_record_binding({"sha": row.get("git_sha") or None, "dirty": row.get("git_dirty")}, f"{row.get('run_id')}'s ledger row")
        return self.evaluator.finish(result, "record", binding.commit, (), {}, notes=[note, binding.note], source=binding.source)

    def _measured_criterion(self, env: Mapping[str, Any], rung_id: str, text: str, source: dict) -> dict[str, Any]:
        """An ungated env: what is measured, as a ``stated`` criterion that stays unknown.

        WHY stated, not a typed target: the curriculum gives these envs no bar (GATES has none; for the datasets its
        rule is prose: AP above the previous best with a paired, bootstrapped CI), and any target would have to invent
        one. The format's ``stated`` kind is exactly a condition the loop writes only in prose, unknown until declared,
        so the env reads as measured (its runs as context evidence and KPIs), never green.
        """

        counts = self._cell_counts(env["id"])
        best = self.verdicts[env["id"]]["best"]
        measured = (f"; best {best.get('model')} {env.get('metric')} {_number(best.get('value')):g} ({best.get('run_id')})"
                    if best is not None and _number(best.get("value")) is not None else "")
        reason = (f"measured, never gated: no bar in curriculum.GATES; {counts['wave1_measured']} of {counts['wave1_planned']} "
                  f"wave-1 cells and {counts['measured']} of {counts['planned']} cells measured{measured}")
        return proof.criterion(criterion_id=f"{rung_id}#measured", kind="stated", method=None,
                               title="measured, no gate", text=text, source=source, targets=[], verdict="unknown",
                               strength=None, reason=reason, evidence=[])

    def _prerequisites_criterion(self, env_id: str, rung_id: str, source: dict) -> dict[str, Any]:
        parents = [rung_id_of(parent) for parent in self.depends[env_id]]
        statuses = {parent: self.derived[env]["status"] if env in self.derived else "missing"
                    for parent, env in zip(parents, self.depends[env_id])}
        verdict, strength, reason = model.prerequisites_verdict(statuses)
        targets = [proof.rung_target(parent, status, env in self.derived)
                   for (parent, status), env in zip(statuses.items(), self.depends[env_id])]
        return proof.criterion(criterion_id=f"{rung_id}#prerequisites", kind="prerequisites", method=None,
                               title="every prerequisite green", text="every prerequisite is green or done",
                               source=source, targets=targets, verdict=verdict, strength=strength, reason=reason, evidence=[])

    def _run_item(self, row: Mapping[str, Any], result: str | None) -> dict[str, Any]:
        """One ledger row as evidence: the row itself (runs.jsonl at its line) is the record the gate reads."""

        run_id = str(row.get("run_id"))
        binding = git_record_binding({"sha": row.get("git_sha") or None, "dirty": row.get("git_dirty")}, "the ledger row")
        item = self._link_at("run", self.ledger, row.get(LINE_KEY), label=run_id)
        started = str(row.get("started_at") or "")
        protocol = row.get("protocol") if isinstance(row.get("protocol"), Mapping) else {}
        facts = {"cell": row.get("cell_id"), "model": row.get("model"), "env": row.get("env"), "metric": row.get("metric"),
                 "value": _number(row.get("value")), "ci_lo": _number(row.get("ci_lo")), "ci_hi": _number(row.get("ci_hi")),
                 "n": row.get("n"), "protocol": dict(protocol), "frozen": is_frozen(row, self.frozen_of.get(str(row.get("env")))),
                 "privileged": is_privileged(row, self.families), "git_dirty": row.get("git_dirty"),
                 "latency_ms_p50": _number(row.get("latency_ms_p50")), "latency_ms_p95": _number(row.get("latency_ms_p95")),
                 "lost_in_conversion": row.get("lost_in_conversion"), "ledger_line": row.get(LINE_KEY),
                 "episodes": (row.get("artifacts") or {}).get("episodes") if isinstance(row.get("artifacts"), Mapping) else None}
        return {**item, "result": result, "strength": capped("record", binding.source) if item["exists"] else "claim",
                "commit": binding.commit, "ts": started if _TIMESTAMP.fullmatch(started) else None, "origin": "ledger",
                "facts": facts, "run_id": run_id, "as_cited": None, "event": None, "commit_source": binding.source}

    def _blockers(self, env_id: str) -> list[dict[str, Any]]:
        """CELLS with status "needs" and a named blocker: what only Zach can unblock (a download approval, hardware)."""

        rows = []
        for cell in self._cells_of(env_id):
            why = str(cell.get("why") or "").strip()
            if cell.get("status") != "needs" or not why:
                continue
            rows.append({"id": f"{cell.get('model')}@{env_id}", "title": f"{cell.get('model')} needs {why}", "default": None,
                         "default_applies_after_wave": None,
                         "source": self._link_at("file", self.curriculum_path, cell.get(LINE_KEY))})
        return rows

    def _kpis(self, env_id: str) -> list[dict[str, Any]]:
        """The best non-privileged headline and the privileged ceiling beside it, each naming the run it was read from."""

        verdict = self.verdicts[env_id]
        unit = UNITS.get(str(self.envs[self.env_index[env_id]].get("metric")))
        rows = []
        best = verdict["best"]
        if best is not None:
            rows.append(self._kpi(f"best {best.get('model')}", _number(best.get("value")), unit, best))
            rows.append(self._kpi(f"best {best.get('model')} 95% CI low", _number(best.get("ci_lo")), unit, best))
        ceiling = max((row for row in verdict["heads"] if is_privileged(row, self.families) and _number(row.get("value")) is not None),
                      key=lambda row: _number(row.get("value")), default=None)
        if ceiling is not None:
            rows.append(self._kpi(f"ceiling {ceiling.get('model')} (privileged)", _number(ceiling.get("value")), unit, ceiling))
        return rows

    @staticmethod
    def _kpi(name: str, value: float | None, unit: str | None, row: Mapping[str, Any]) -> dict[str, Any]:
        started = str(row.get("started_at") or "")
        return {"name": name, "value": value, "unit": unit, "run": str(row.get("run_id")),
                "ts": started if _TIMESTAMP.fullmatch(started) else None}

    @staticmethod
    def _best_facts(row: Mapping[str, Any] | None, beaten: bool) -> dict[str, Any] | None:
        if row is None:
            return None
        return {"model": row.get("model"), "value": _number(row.get("value")), "ci_lo": _number(row.get("ci_lo")),
                "ci_hi": _number(row.get("ci_hi")), "n": row.get("n"), "run_id": row.get("run_id"),
                "protocol": (row.get("protocol") or {}).get("name") if isinstance(row.get("protocol"), Mapping) else None,
                "git_dirty": row.get("git_dirty"), "clears_gate": beaten}


def _tier_short(title: str) -> str:
    """``gallery._tier_short``: "Toy grasping - synthetic images, ..." -> "Toy grasping"."""

    return title.split(" - ")[0].split(" (")[0]


__all__ = ["project_grasping", "read_curriculum", "read_frozen_protocols", "rung_id_of", "NotData", "ProjectionError"]
