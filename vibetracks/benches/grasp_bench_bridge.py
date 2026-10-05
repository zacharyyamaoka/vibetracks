# WHY this lives in vibetracks/benches and not under dashboard/ (2026-10-04): the dashboard adapter and the roadmap
# projector both need the bench's verdict, and two readers means two replicas. A replica drifted the same day, when
# grasp_bench tightened is_frozen_protocol with provenance_gap and the dashboard kept the old rule. One module, stdlib
# only, no import from vibetracks.dashboard, so either side can import it alone.
"""The grasp bench's own verdict, read by running the bench's own code in the bench's own venv.

    result = bench_verdict(BenchPaths(...), {"T1": [run_id, ...], "T2": [...]})
    result.doc["snapshots"]["T2"]["envs"]["toy/x"]["beaten"]   # gallery.env_verdict, as the bench computes it

WHY a bridge and not a copy of the rules (2026-10-04): the adapter used to re-implement gallery.py's
``is_frozen_protocol`` / ``clears_gate`` / ``env_verdict`` / ``headline_runs``. That evening the bench tightened its
rule (da80ffe1, "only provenance that can vouch for itself is frozen": ``provenance_gap``, ``schema_version``,
``attestations.jsonl``) and the copy silently kept the old one: the dashboard said 6 of 10 gated envs beaten while
the bench's own gallery said 2. Its protocol table had drifted too (no ``mujoco-cam``). Any copy drifts again, so
there is none: the verdict comes from ``grasp_bench.gallery`` itself, and when that cannot run the dashboard says
"bench verdict unavailable" instead of falling back to a guess.

One subprocess per change: the result is cached in ``grasping_verdict_cache`` (a folder under the dashboard data
home), keyed on the mtimes and sizes of every file the verdict depends on (the ledger, attestations.jsonl,
gallery.py, ledger.py, curriculum.py, runner.py, contracts.py, the venv's python), the request and this script.

The request names each snapshot by the ledger ``run_id``s it holds (the adapter's cumulative tier phases), so the
bench judges exactly the rows the adapter read even if the ledger grows in between. The document printed back:

    {"schema": "grasp-bench-verdict/1",
     "modules": {"gallery": <realpath>, ...},          # checked against the declared paths
     "attestations_path": <realpath>, "ledger_rows": int, "duplicate_run_ids": [...],
     "gated": [env ids, curriculum.GATES order],
     "runs": {run_id: {frozen, privileged, clears_gate, provenance_gap, schema_version}},
     "snapshots": {id: {"heads": {cell_id: Brief}, "missing": [run_ids the bench did not find],
                        "envs": {env_id: {beaten, provisional, best_run: Brief | null}}}}}
    Brief = {run_id, cell_id, model, env, value, ci_lo, n, started_at, frozen, privileged}
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "grasp-bench-verdict/1"
TIMEOUT_S = 90.0
CACHE_NAME = "verdict.json"
REASON_LIMIT = 200
#: Environment variables that would make the bench's interpreter import something other than its own venv.
_SCRUB = ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONSAFEPATH")

#: The bench modules whose code decides the verdict, as the bridge reports them, against the declared path keys.
MODULE_KEYS = {"gallery": "gallery_py", "ledger": "ledger_py", "curriculum": "curriculum_py", "runner": "runner_py",
               "contracts": "contracts_py"}

# WHY ``gallery._run_privileged``, a private name: it is the exact predicate env_verdict uses. If the bench renames it
# the bridge fails with an AttributeError and the dashboard says "bench verdict unavailable", which is the truth.
SCRIPT = r'''
import json, os, sys
request = json.load(sys.stdin)
from grasp_bench import contracts, curriculum, gallery, runner
from grasp_bench import ledger as ledger_module
from grasp_bench.ledger import Ledger

book = Ledger(request["ledger_root"])
runs = book.load_runs()
seen, duplicates = set(), []
for run in runs:
    if run.run_id in seen:
        duplicates.append(run.run_id)
    seen.add(run.run_id)

def brief(run):
    if run is None:
        return None
    return {"run_id": run.run_id, "cell_id": run.cell_id, "model": run.model, "env": run.env, "value": run.value,
            "ci_lo": run.ci_lo, "n": run.n, "started_at": run.started_at,
            "frozen": gallery.is_frozen_protocol(run), "privileged": gallery._run_privileged(run)}

judged = {run.run_id: {"frozen": gallery.is_frozen_protocol(run), "privileged": gallery._run_privileged(run),
                       "clears_gate": gallery.clears_gate(run), "provenance_gap": gallery.provenance_gap(run),
                       "schema_version": run.schema_version} for run in runs}
snapshots = {}
for snapshot_id, run_ids in request["subsets"].items():
    wanted = set(run_ids)
    subset = [run for run in runs if run.run_id in wanted]   # ledger order, as the gallery sees it
    heads = gallery.headline_runs(subset)
    envs = {}
    for env_id in curriculum.GATES:
        beaten, best = gallery.env_verdict(env_id, heads)
        envs[env_id] = {"beaten": bool(beaten), "provisional": bool(gallery.env_provisional(env_id, heads)),
                        "best_run": brief(best)}
    snapshots[snapshot_id] = {"heads": {cell: brief(run) for cell, run in heads.items()}, "envs": envs,
                              "missing": sorted(wanted - {run.run_id for run in subset})}
modules = {name: os.path.realpath(module.__file__) for name, module in (
    ("gallery", gallery), ("ledger", ledger_module), ("curriculum", curriculum), ("runner", runner),
    ("contracts", contracts))}
document = {"schema": "grasp-bench-verdict/1", "modules": modules,
            "attestations_path": os.path.realpath(str(book.attestations_path)), "ledger_rows": len(runs),
            "duplicate_run_ids": duplicates, "gated": list(curriculum.GATES), "runs": judged, "snapshots": snapshots}
sys.stdout.write("\n" + json.dumps(document) + "\n")
'''


@dataclass(frozen=True)
class BenchPaths:
    """Every file the verdict depends on, from the note's declared sources (None = not declared)."""

    python: str | None
    ledger: str | None
    attestations: str | None
    gallery_py: str | None
    ledger_py: str | None
    curriculum_py: str | None
    runner_py: str | None
    contracts_py: str | None
    cache_dir: str | None

    def missing(self) -> list[str]:
        return [name for name, value in self.__dict__.items() if not value]


@dataclass
class BridgeResult:
    doc: dict[str, Any] | None
    reason: str | None = None          # why there is no verdict ("bench venv missing: ...")
    cached: bool = False
    seconds: float = 0.0               # wall time of this call (the subprocess when cold, the cache read when warm)
    run_seconds: float | None = None   # the subprocess's own time, when it ran (cold) or when the cache was written
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.doc is not None

    def info(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "cached": self.cached, "seconds": round(self.seconds, 3),
                "bench_seconds": None if self.run_seconds is None else round(self.run_seconds, 3), **self.extra}


def _clip(text: str) -> str:
    text = " ".join(text.split())
    # WHY an explicit ellipsis: truth rule 7, a shortened stored string says it was shortened.
    return text if len(text) <= REASON_LIMIT else text[:REASON_LIMIT - 1] + "…"


def _stamp(path: str | None) -> list[Any]:
    try:
        info = os.stat(path) if path else None
    except OSError:
        info = None
    return [path, info.st_mtime_ns if info else None, info.st_size if info else None]


def _real(path: str) -> str:
    return os.path.realpath(path)


def _cache_key(paths: BenchPaths, request: dict[str, Any]) -> str:
    stamps = [_stamp(getattr(paths, name)) for name in ("python", "ledger", "attestations", "gallery_py", "ledger_py",
                                                         "curriculum_py", "runner_py", "contracts_py")]
    blob = json.dumps({"script": SCRIPT, "schema": SCHEMA, "stamps": stamps, "request": request}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _read_cache(file: Path, key: str) -> dict[str, Any] | None:
    try:
        with open(file, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("key") == key and isinstance(data.get("doc"), dict):
        return data
    return None


def _write_cache(directory: Path, payload: dict[str, Any], name: str = CACHE_NAME) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=name + ".", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, directory / name)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError:
        pass  # WHY swallow: a read-only data home costs a re-run next time, never the verdict itself


def _check(doc: Any, paths: BenchPaths) -> str | None:
    """Why ``doc`` is not the verdict of the declared bench, or None when it is."""

    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return "the bench printed no grasp-bench-verdict/1 document"
    for name, attribute in MODULE_KEYS.items():
        imported = (doc.get("modules") or {}).get(name)
        declared = getattr(paths, attribute)
        if not imported or _real(imported) != _real(declared):
            return f"the bench venv imports {name}.py from {imported}, not the declared {declared}"
    if _real(doc.get("attestations_path") or "") != _real(paths.attestations):
        return (f"the bench reads attestations from {doc.get('attestations_path')}, not the declared "
                f"{paths.attestations}")
    if not isinstance(doc.get("runs"), dict) or not isinstance(doc.get("snapshots"), dict):
        return "the bench's verdict document has no runs or snapshots"
    return None


def bench_verdict(paths: BenchPaths, subsets: dict[str, list[str]], *, timeout: float = TIMEOUT_S) -> BridgeResult:
    """Run grasp_bench.gallery over ``subsets`` (snapshot id -> ledger run_ids) in the bench's venv, or say why not."""

    started = time.monotonic()

    def fail(reason: str) -> BridgeResult:
        return BridgeResult(None, _clip(reason), seconds=time.monotonic() - started)

    missing = paths.missing()
    if missing:
        return fail(f"vibe-sources lacks {', '.join(missing)}")
    if not Path(paths.python).is_file():
        return fail(f"bench venv missing: {paths.python}")
    if not Path(paths.ledger).is_file():
        return fail(f"ledger missing: {paths.ledger}")
    request = {"ledger_root": str(Path(paths.ledger).parent), "subsets": subsets}
    if _real(str(Path(paths.ledger).parent / "attestations.jsonl")) != _real(paths.attestations):
        # WHY: Ledger(root) reads attestations.jsonl beside runs.jsonl; a declared path elsewhere would be watched
        # by the build while the bench read another file.
        return fail(f"grasping_attestations {paths.attestations} is not beside the declared ledger {paths.ledger}")
    key = _cache_key(paths, request)
    cache_dir = Path(paths.cache_dir)
    hit = _read_cache(cache_dir / CACHE_NAME, key)
    if hit is not None:
        return BridgeResult(hit["doc"], cached=True, seconds=time.monotonic() - started,
                            run_seconds=hit.get("run_seconds"), extra={"computed_at": hit.get("computed_at")})

    env = {name: value for name, value in os.environ.items() if name not in _SCRUB}
    bench_dir = Path(paths.python).parent.parent.parent  # <bench>/.venv/bin/python
    run_started = time.monotonic()
    try:
        done = subprocess.run([paths.python, "-I", "-c", SCRIPT], input=json.dumps(request), cwd=bench_dir, env=env,
                              capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return fail(f"the bench's gallery did not answer within {timeout:.0f} s")
    except OSError as error:
        return fail(f"could not start the bench venv: {error}")
    run_seconds = time.monotonic() - run_started
    if done.returncode != 0:
        lines = [line for line in done.stderr.splitlines() if line.strip()]
        return fail(f"the bench's gallery exited {done.returncode}: {lines[-1] if lines else 'no stderr'}")
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    try:
        doc = json.loads(lines[-1]) if lines else None
    except ValueError:
        doc = None
    problem = _check(doc, paths)
    if problem:
        return fail(problem)
    computed_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_cache(cache_dir, {"key": key, "doc": doc, "run_seconds": run_seconds, "computed_at": computed_at})
    return BridgeResult(doc, seconds=time.monotonic() - started, run_seconds=run_seconds,
                        extra={"computed_at": computed_at})


# ---- verdict(): the one-call reader the roadmap projector and the dashboard share

VERDICT_SCHEMA = "grasp-bench-verdict/2"
VERDICT_CACHE_NAME = "verdict-v2.json"
#: The dashboard data home's folder for this bridge's cache (sources.py: ``{dashboard_data_home}/grasping-bench-verdict``).
DEFAULT_CACHE_DIR = "~/.local/share/vibetracks/dashboard/grasping-bench-verdict"

# WHY run_id = the row's index in runs.jsonl: the ledger's own run_id strings are free-form file names; the position is
# stable while the ledger is append-only and needs no knowledge of the bench's naming.
VERDICT_SCRIPT = r'''
import json, os, sys
request = json.load(sys.stdin)
from grasp_bench import curriculum, gallery
from grasp_bench import ledger as ledger_module
from grasp_bench.ledger import Ledger

book = Ledger(request["ledger_root"])
loaded = book.load_runs()
index_of = {id(run): str(position) for position, run in enumerate(loaded)}
runs = {}
for run in loaded:
    runs[index_of[id(run)]] = {"frozen": bool(gallery.is_frozen_protocol(run)), "gap": str(gallery.provenance_gap(run)),
                               "privileged": bool(gallery._run_privileged(run)), "started_at": run.started_at,
                               "env": run.env, "model": run.model}
heads = gallery.headline_runs(loaded)
envs = {}
for env_id in curriculum.GATES:
    beaten, best = gallery.env_verdict(env_id, heads)
    envs[env_id] = {"beaten": bool(beaten), "provisional": bool(gallery.env_provisional(env_id, heads)),
                    "best_run": None if best is None else index_of[id(best)]}
document = {"envs": envs, "runs": runs, "headline": {cell: index_of[id(run)] for cell, run in heads.items()},
            "modules": {"gallery": os.path.realpath(gallery.__file__), "ledger": os.path.realpath(ledger_module.__file__),
                        "curriculum": os.path.realpath(curriculum.__file__)}}
sys.stdout.write("\n" + json.dumps(document) + "\n")
'''


def _verdict_failure(reason: str, bench_head: str | None) -> dict[str, Any]:
    return {"schema": VERDICT_SCHEMA, "envs": {}, "runs": {}, "headline": {}, "bench_head": bench_head,
            "error": _clip(reason)}


def _bench_head(bench_dir: Path) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(bench_dir), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    head = done.stdout.strip()
    return head if done.returncode == 0 and head else None


def verdict(bench_dir: str | Path, *, cache_dir: str | Path | None = None, timeout: float = TIMEOUT_S) -> dict[str, Any]:
    """The bench's verdict over its whole ledger, computed by its own code in its own venv (grasp-bench-verdict/2).

    ``bench_dir`` is the grasp_bench package root. Never a replica: when the bench cannot run, ``error`` says why and
    ``envs``/``runs``/``headline`` are empty.
    """

    bench = Path(bench_dir)
    head = _bench_head(bench)
    python = bench / ".venv" / "bin" / "python"
    ledger_root = bench / "out" / "ledger"
    code = bench / "src" / "grasp_bench"
    if not python.is_file():
        return _verdict_failure(f"bench venv missing: {python}", head)
    if not (ledger_root / "runs.jsonl").is_file():
        return _verdict_failure(f"ledger missing: {ledger_root / 'runs.jsonl'}", head)

    request = {"ledger_root": str(ledger_root)}
    watched = [ledger_root / "runs.jsonl", ledger_root / "attestations.jsonl", code / "gallery.py",
               code / "curriculum.py", code / "ledger.py", code / "runner.py", python]
    blob = json.dumps({"script": VERDICT_SCRIPT, "schema": VERDICT_SCHEMA, "request": request,
                       "stamps": [_stamp(str(path)) for path in watched]}, sort_keys=True)
    key = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    directory = Path(cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR).expanduser()
    hit = _read_cache(directory / VERDICT_CACHE_NAME, key)
    if hit is not None:
        return {**hit["doc"], "bench_head": head}

    env = {name: value for name, value in os.environ.items() if name not in _SCRUB}
    try:
        done = subprocess.run([str(python), "-I", "-c", VERDICT_SCRIPT], input=json.dumps(request), cwd=bench, env=env,
                              capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return _verdict_failure(f"the bench's gallery did not answer within {timeout:.0f} s", head)
    except OSError as error:
        return _verdict_failure(f"could not start the bench venv: {error}", head)
    if done.returncode != 0:
        lines = [line for line in done.stderr.splitlines() if line.strip()]
        return _verdict_failure(f"the bench's gallery exited {done.returncode}: {lines[-1] if lines else 'no stderr'}",
                                head)
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    try:
        raw = json.loads(lines[-1]) if lines else None
    except ValueError:
        raw = None
    if not isinstance(raw, dict) or not all(isinstance(raw.get(name), dict) for name in ("envs", "runs", "headline")):
        return _verdict_failure("the bench printed no verdict document", head)
    for name, imported in (raw.get("modules") or {}).items():
        if not imported or _real(imported) != _real(str(code / f"{name}.py")):
            return _verdict_failure(f"the bench venv imports {name}.py from {imported}, not from {code}", head)
    doc = {"schema": VERDICT_SCHEMA, "envs": raw["envs"], "runs": raw["runs"], "headline": raw["headline"],
           "bench_head": None, "error": None}
    _write_cache(directory, {"key": key, "doc": doc}, VERDICT_CACHE_NAME)
    return {**doc, "bench_head": head}
