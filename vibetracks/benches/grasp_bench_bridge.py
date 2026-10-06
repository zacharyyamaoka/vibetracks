# WHY this lives in vibetracks/benches and not under dashboard/ (2026-10-04): the dashboard adapter and the roadmap
# projector both need the bench's verdict, and two readers means two replicas. A replica drifted the same day, when
# grasp_bench tightened is_frozen_protocol with provenance_gap and the dashboard kept the old rule. One module, stdlib
# only, no import from vibetracks.dashboard, so either side can import it alone.
"""The grasp bench's own verdict, read by running the bench's own code in the bench's own venv.

    doc = verdict(bench_dir)                                  # the roadmap projector: the whole ledger
    doc = verdict(bench_dir, subsets={"T1": [sha, ...]})      # the dashboard: also one verdict per row subset
    doc["envs"]["toy/x"]["beaten"]                            # gallery.env_verdict, as the bench computes it

WHY a bridge and not a copy of the rules (2026-10-04): the adapter used to re-implement gallery.py's
``is_frozen_protocol`` / ``clears_gate`` / ``env_verdict`` / ``headline_runs``. That evening the bench tightened its
rule (da80ffe1, "only provenance that can vouch for itself is frozen": ``provenance_gap``, ``schema_version``,
``attestations.jsonl``) and the copy silently kept the old one: the dashboard said 6 of 10 gated envs beaten while
the bench's own gallery said 2. Its protocol table had drifted too (no ``mujoco-cam``). Any copy drifts again, so
there is none: the verdict comes from ``grasp_bench.gallery`` itself, and when that cannot run the caller says
"bench verdict unavailable" instead of falling back to a guess.

One reader, one byte snapshot (Codex r3 finding 2, 2026-10-05): there used to be a second reader, ``bench_verdict()``
(schema grasp-bench-verdict/1), which the dashboard adapter called after reading runs.jsonl itself; it read the ledger
again and was checked against the adapter's rows by run id only, so a sparse row enriched in between produced a
measured "beaten" beside a displayed row with no Top-1. It is gone. ``verdict()`` judges one byte snapshot and digests
every row (``line_sha256``); the dashboard names its rows by those digests (``subsets``), so the bench judges exactly
the bytes the dashboard displays, and a row changed since the dashboard's read comes back under ``missing``.

One subprocess per change: the result is cached in the cache folder (``grasping_verdict_cache``, under the dashboard
data home), keyed on the mtimes and sizes of runs.jsonl, attestations.jsonl (recorded as absent when missing), the
venv's python, the request and the script, plus every grasp_bench module the run imported. That module set is only
known after a run (gallery.py imports registry.py, whose ``env_family`` decides the protocol), so the script reports
it from ``sys.modules``, the entry stores the stamps, and a read re-stamps them: any changed, added-to or vanished
module is a miss. WHY (audit 2026-10-04): a registry.py change moved the bench's own verdict from 6 beaten envs to 2
while a cache that watched a fixed list without registry.py stayed warm.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

TIMEOUT_S = 90.0
REASON_LIMIT = 200
#: Environment variables that would make the bench's interpreter import something other than its own venv.
_SCRUB = ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONSAFEPATH")

#: The module witnesses a verdict must carry: every grasp_bench module a verdict run of the live bench imports, pinned
#: from a real run on 2026-10-05 ("__init__" is the package itself). WHY required and pinned (Codex r2 finding 6): the
#: validator used to check only the entries the subprocess happened to print, so ``modules: {}`` was accepted. Each
#: must be imported from the bench's own src/grasp_bench (exact file), and so must every other module the run reports.
#: If the bench's import graph changes, the bridge answers "bench verdict unavailable" naming the module, and this pin
#: is updated from a new real run; it never silently accepts a verdict whose deciding code it cannot place.
REQUIRED_MODULES = ("__init__", "contracts", "curriculum", "gallery", "grasp", "ledger", "registry", "runner", "stats")


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


def _read_cache(file: Path, key: str) -> dict[str, Any] | None:
    """The cache entry for ``key`` whose recorded module files are all unchanged, else None (a miss).

    WHY two halves: the key covers what is known before a run (script, request, venv python, runs.jsonl,
    attestations.jsonl, declared modules); ``deps`` covers what is only known after it, every grasp_bench module the
    verdict imported. An entry without a ``deps`` list is from before that rule and is a miss.
    """

    try:
        with open(file, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not (isinstance(data, dict) and data.get("key") == key and isinstance(data.get("doc"), dict)):
        return None
    deps = data.get("deps")
    if not isinstance(deps, list) or not deps:
        return None
    for stamp in deps:
        if not (isinstance(stamp, list) and len(stamp) == 3 and isinstance(stamp[0], str)):
            return None
        if _stamp(stamp[0]) != stamp:
            return None
    return data


def _dependencies(doc: dict[str, Any], before: dict[str, list[Any]]) -> tuple[list[list[Any]] | None, str | None]:
    """``(stamps of every module file the run reported, None)``, or ``(None, why they cannot key a cache)``.

    ``before`` holds the stamps of the package's files taken before the run: a file that changed while the bench ran
    may have been imported in either version, so that result is returned but never cached.
    """

    files = doc.get("dependencies")
    if not isinstance(files, list) or not files or not all(isinstance(path, str) and path for path in files):
        return None, "the bench did not report the module files its verdict imported"
    stamps = [_stamp(path) for path in sorted(set(files))]
    for stamp in stamps:
        if stamp[1] is None:
            return None, f"the bench reported an imported module that does not exist: {stamp[0]}"
        if stamp[0] in before and before[stamp[0]] != stamp:
            return None, f"{stamp[0]} changed while the bench ran"
    return stamps, None


def _package_stamps(package: Path) -> dict[str, list[Any]]:
    """Stamps of every .py under the bench package, by realpath, taken before a run."""

    stamps: dict[str, list[Any]] = {}
    try:
        files = sorted(package.rglob("*.py"))
    except OSError:
        return stamps
    for file in files:
        real = _real(str(file))
        stamps[real] = _stamp(real)
    return stamps


def _write_cache(directory: Path, payload: dict[str, Any], name: str) -> None:
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


def _inside(path: str, root: str) -> bool:
    real = _real(path)
    return real == root or real.startswith(root + os.sep)


def _witness_problem(doc: dict[str, Any], code: Path) -> str | None:
    """Why ``doc`` does not prove it was decided by the bench's own src/grasp_bench (``code``), or None when it does.

    A ``dependencies`` list and a ``modules`` map must be present; every entry of both must lie inside ``code``; and
    every one of REQUIRED_MODULES must be in ``modules`` as exactly its file under ``code`` and listed in
    ``dependencies``.
    """

    root = _real(str(code))
    files = doc.get("dependencies")
    if not (isinstance(files, list) and files and all(isinstance(path, str) and path for path in files)):
        return "the bench did not report the module files its verdict imported"
    imported_files = {_real(path) for path in files}
    for path in sorted(imported_files):
        if not _inside(path, root):
            return f"the bench's verdict imported {path}, outside {code}"
    modules = doc.get("modules")
    if not isinstance(modules, dict):
        return "the bench's verdict names none of the modules that decided it"
    for name, path in modules.items():
        if not isinstance(path, str) or not path or not _inside(path, root):
            return f"the bench venv imports grasp_bench {name} from {path}, outside {code}"
    for name in REQUIRED_MODULES:
        expected = _real(str(code / ("__init__.py" if name == "__init__" else f"{name}.py")))
        imported = modules.get(name)
        if not imported or _real(imported) != expected:
            return f"the bench's verdict has no {name} witness at {expected} (got {imported})"
        if expected not in imported_files:
            return f"the bench's verdict does not list {expected} among the modules it imported"
    return None


# ---- verdict(): the one reader the roadmap projector and the dashboard share

VERDICT_SCHEMA = "grasp-bench-verdict/2"
# WHY v3 on the cache and not on the schema: line_sha256 is purely additive to every runs[run_id] entry, so readers of
# /2 keep working; but a cache entry written before the field existed would answer without it, so it must be a miss.
VERDICT_CACHE_SCHEMA = "grasp-bench-verdict/3"
VERDICT_CACHE_NAME = "verdict-v3.json"
#: The cache of subset requests (the dashboard adapter's), beside the whole-ledger one (the roadmap projector's).
VERDICT_SUBSETS_CACHE_NAME = "verdict-v3-subsets.json"
LEDGER_UNALIGNED = "the bench's parse of the runs.jsonl snapshot does not match its lines one for one; row digests unaligned"
#: The dashboard data home's folder for this bridge's cache (sources.py: ``{dashboard_data_home}/grasping-bench-verdict``).
DEFAULT_CACHE_DIR = "~/.local/share/vibetracks/dashboard/grasping-bench-verdict"

# WHY run_id = the row's index in runs.jsonl: the ledger's own run_id strings are free-form file names; the position is
# stable while the ledger is append-only and needs no knowledge of the bench's naming.
VERDICT_SCRIPT = r'''
import hashlib, json, os, sys, tempfile
request = json.load(sys.stdin)
# WHY after the verdict and from sys.modules: the files that decided it are exactly the grasp_bench modules this run
# imported (gallery -> registry, runner -> contracts, ...), which no fixed list can name ahead of time.
def _dependencies():
    found = set()
    for name, module in list(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if path and (name == "grasp_bench" or name.startswith("grasp_bench.")):
            found.add(os.path.realpath(path))
    return sorted(found)

def _modules():
    found = {}
    for name, module in list(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if path and name == "grasp_bench":
            found["__init__"] = os.path.realpath(path)
        elif path and name.startswith("grasp_bench."):
            found[name[len("grasp_bench."):]] = os.path.realpath(path)
    return found

def _answer(document):
    sys.stdout.write("\n" + json.dumps(document) + "\n")
    sys.exit(0)

from grasp_bench import curriculum, gallery
from grasp_bench.ledger import Ledger

# WHY one byte snapshot, parsed by the bench's own Ledger (Codex r2 finding 4, 2026-10-05): the bridge used to read
# runs.jsonl as bytes, let load_runs() read it again, and pair the two by comparing only the keys present in the raw
# row. A legacy sparse row enriched in place between the reads still "aligned", and the old bytes' digest went out
# beside the new row's frozen/beaten judgement. Now runs.jsonl (and attestations.jsonl) are read once, the bytes are
# written into a scratch ledger root, and Ledger(scratch).load_runs() judges exactly those bytes. Each line is then
# parsed alone the same way: a line the bench's parser turns into one run is that run's row, a line it drops (blank, a
# torn tail) is no row, and every row's whole parsed run must equal the snapshot parse's run at the same index. Both
# the judgement and line_sha256 thus come from the same immutable bytes through the bench's own normalisation; nothing
# here re-implements its skip rule. bytes.splitlines splits as the Ledger's text-mode read does (\n, \r\n, lone \r)
# and drops that one terminator, so a CRLF file hashes without its \r.
book = Ledger(request["ledger_root"])
with open(book.runs_path, "rb") as handle:
    data = handle.read()
try:
    with open(book.attestations_path, "rb") as handle:
        attestations = handle.read()
except FileNotFoundError:
    attestations = None

def _shape(run):
    return json.dumps(vars(run) if hasattr(run, "__dict__") else repr(run), sort_keys=True, default=repr)

with tempfile.TemporaryDirectory(prefix="grasp-bench-verdict-") as scratch:
    def _parse(name, runs_bytes):
        root = os.path.join(scratch, name)
        os.mkdir(root)
        ledger = Ledger(root)
        for path, payload in ((ledger.runs_path, runs_bytes), (ledger.attestations_path, attestations)):
            if os.path.dirname(os.path.realpath(str(path))) != os.path.realpath(root):
                _answer({"error": "the bench's Ledger(root) does not read %s inside its root" % path})
            if payload is not None:
                with open(path, "wb") as handle:
                    handle.write(payload)
        return ledger.load_runs()

    loaded = _parse("snapshot", data)
    rows = []
    for number, raw in enumerate(data.splitlines()):
        alone = _parse("line-%d" % number, raw + b"\n")
        if len(alone) > 1:
            _answer({"error": request["unaligned"]})
        if alone:
            rows.append((raw, alone[0]))
if len(rows) != len(loaded) or any(_shape(run) != _shape(alone) for run, (_raw, alone) in zip(loaded, rows)):
    _answer({"error": request["unaligned"]})

index_of = {id(run): str(position) for position, run in enumerate(loaded)}
digest = [hashlib.sha256(raw).hexdigest() for raw, _alone in rows]
runs = {}
for position, run in enumerate(loaded):
    runs[index_of[id(run)]] = {"frozen": bool(gallery.is_frozen_protocol(run)), "gap": str(gallery.provenance_gap(run)),
                               "privileged": bool(gallery._run_privileged(run)), "started_at": run.started_at,
                               "env": run.env, "model": run.model, "clears_gate": bool(gallery.clears_gate(run)),
                               "line_sha256": digest[position]}

def _judge(subset):
    heads = gallery.headline_runs(subset)
    envs = {}
    for env_id in curriculum.GATES:
        beaten, best = gallery.env_verdict(env_id, heads)
        envs[env_id] = {"beaten": bool(beaten), "provisional": bool(gallery.env_provisional(env_id, heads)),
                        "best_run": None if best is None else index_of[id(best)]}
    return envs, {cell: index_of[id(run)] for cell, run in heads.items()}

envs, headline = _judge(loaded)
answer = {"envs": envs, "runs": runs, "headline": headline, "modules": _modules(), "dependencies": _dependencies()}
# WHY subsets name rows by line_sha256 (content), not by index: the caller parsed its own read of runs.jsonl, and an
# index means "whatever row sits there now". A digest names the exact bytes the caller displays, so a row enriched or
# replaced since the caller's read is simply absent from this snapshot and reported under "missing".
if request.get("subsets") is not None:
    answer["snapshots"] = {}
    for snapshot_id, wanted_list in request["subsets"].items():
        wanted = set(wanted_list)
        positions = [position for position in range(len(loaded)) if digest[position] in wanted]   # ledger order
        envs, headline = _judge([loaded[position] for position in positions])
        answer["snapshots"][snapshot_id] = {"envs": envs, "headline": headline,
                                            "missing": sorted(wanted - {digest[position] for position in positions})}
_answer(answer)
'''


def _has_row_digests(doc: dict[str, Any]) -> bool:
    """True when every run in a cached verdict carries its ledger row's digest (an older entry does not: a miss)."""

    runs = doc.get("runs")
    return isinstance(runs, dict) and all(
        isinstance(run, dict) and isinstance(run.get("line_sha256"), str) and len(run["line_sha256"]) == 64
        for run in runs.values())


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


def verdict(bench_dir: str | Path, *, cache_dir: str | Path | None = None, timeout: float = TIMEOUT_S,
            subsets: dict[str, list[str]] | None = None, info: dict[str, Any] | None = None) -> dict[str, Any]:
    """The bench's verdict over its whole ledger, computed by its own code in its own venv (grasp-bench-verdict/2).

    ``bench_dir`` is the grasp_bench package root. Never a replica: when the bench cannot run, ``error`` says why and
    ``envs``/``runs``/``headline`` are empty. Every ``runs[run_id]`` carries ``line_sha256``: the sha256 hex of that
    ledger row's exact bytes in runs.jsonl, without its one line terminator (``\\n`` or ``\\r\\n``), computed in the
    bench subprocess from the one byte snapshot the bench's own Ledger parsed for the judgement. When the bench's parse
    does not match the snapshot's lines one for one, ``error`` is LEDGER_UNALIGNED. A document without the required
    module witnesses (REQUIRED_MODULES, each inside the bench's src/grasp_bench) is an error too; neither is cached.

    Additive (2026-10-05, for the dashboard adapter; the roadmap projector passes neither and gets the same document
    as before):

    - every ``runs[run_id]`` also carries ``clears_gate`` (``gallery.clears_gate``);
    - ``subsets`` (snapshot id -> ``line_sha256`` digests) adds ``snapshots``: per id, the gallery's verdict over the
      snapshot's rows whose digest is listed, in ledger order: ``{"envs": {...as above}, "headline": {cell: run_id},
      "missing": [listed digests no row of this snapshot has]}``. ``run_id``s are this document's own;
    - ``info``, a dict the caller owns, is filled with ``cached``, ``seconds`` (this call), ``bench_seconds`` (the
      subprocess, cold or when the cache entry was written) and ``computed_at``; the returned document is unchanged.
    """

    started = time.monotonic()
    meta: dict[str, Any] = info if info is not None else {}
    meta.update(cached=False, seconds=0.0, bench_seconds=None, computed_at=None)

    def done_(document: dict[str, Any]) -> dict[str, Any]:
        meta["seconds"] = time.monotonic() - started
        return document

    bench = Path(bench_dir)
    head = _bench_head(bench)
    python = bench / ".venv" / "bin" / "python"
    ledger_root = bench / "out" / "ledger"
    code = bench / "src" / "grasp_bench"
    if not python.is_file():
        return done_(_verdict_failure(f"bench venv missing: {python}", head))
    if not (ledger_root / "runs.jsonl").is_file():
        return done_(_verdict_failure(f"ledger missing: {ledger_root / 'runs.jsonl'}", head))

    request: dict[str, Any] = {"ledger_root": str(ledger_root), "unaligned": LEDGER_UNALIGNED}
    if subsets is not None:
        request["subsets"] = {str(name): sorted(set(digests)) for name, digests in subsets.items()}
    # WHY a second cache file for subset requests: the projector (whole ledger) and the dashboard (subsets) share the
    # cache folder, and one file would make each evict the other on every build.
    cache_name = VERDICT_CACHE_NAME if subsets is None else VERDICT_SUBSETS_CACHE_NAME
    # WHY these and not the module list: runs.jsonl, attestations.jsonl (stamped absent when missing) and the venv
    # python are known before the run; every grasp_bench module the verdict imports is checked from the cache entry.
    watched = [ledger_root / "runs.jsonl", ledger_root / "attestations.jsonl", python]
    blob = json.dumps({"script": VERDICT_SCRIPT, "schema": VERDICT_CACHE_SCHEMA, "request": request,
                       "stamps": [_stamp(str(path)) for path in watched]}, sort_keys=True)
    key = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    directory = Path(cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR).expanduser()
    hit = _read_cache(directory / cache_name, key)
    if hit is not None and _has_row_digests(hit["doc"]) and (subsets is None or isinstance(hit["doc"].get("snapshots"), dict)):
        meta.update(cached=True, bench_seconds=hit.get("run_seconds"), computed_at=hit.get("computed_at"))
        return done_({**hit["doc"], "bench_head": head})

    env = {name: value for name, value in os.environ.items() if name not in _SCRUB}
    before = _package_stamps(code)
    run_started = time.monotonic()
    try:
        done = subprocess.run([str(python), "-I", "-c", VERDICT_SCRIPT], input=json.dumps(request), cwd=bench, env=env,
                              capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return done_(_verdict_failure(f"the bench's gallery did not answer within {timeout:.0f} s", head))
    except OSError as error:
        return done_(_verdict_failure(f"could not start the bench venv: {error}", head))
    run_seconds = time.monotonic() - run_started
    meta["bench_seconds"] = run_seconds
    if done.returncode != 0:
        lines = [line for line in done.stderr.splitlines() if line.strip()]
        return done_(_verdict_failure(
            f"the bench's gallery exited {done.returncode}: {lines[-1] if lines else 'no stderr'}", head))
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    try:
        raw = json.loads(lines[-1]) if lines else None
    except ValueError:
        raw = None
    if isinstance(raw, dict) and raw.get("error"):
        return done_(_verdict_failure(str(raw["error"]), head))  # never cached: the next call reads the ledger afresh
    if not isinstance(raw, dict) or not all(isinstance(raw.get(name), dict) for name in ("envs", "runs", "headline")):
        return done_(_verdict_failure("the bench printed no verdict document", head))
    if subsets is not None and not (isinstance(raw.get("snapshots"), dict)
                                    and all(isinstance(raw["snapshots"].get(name), dict) for name in request["subsets"])):
        return done_(_verdict_failure("the bench printed no verdict for the requested subsets", head))
    problem = _witness_problem(raw, code)
    if problem:
        return done_(_verdict_failure(problem, head))  # never cached: nothing below runs
    doc = {"schema": VERDICT_SCHEMA, "envs": raw["envs"], "runs": raw["runs"], "headline": raw["headline"],
           "bench_head": None, "error": None}
    if subsets is not None:
        doc["snapshots"] = raw["snapshots"]
    computed_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    meta["computed_at"] = computed_at
    deps, _uncached = _dependencies(raw, before)
    if deps is not None:  # WHY no error when deps cannot be stamped: the verdict is still the bench's; it is just not cached
        _write_cache(directory, {"key": key, "cache_schema": VERDICT_CACHE_SCHEMA, "deps": deps, "doc": doc,
                                 "run_seconds": run_seconds, "computed_at": computed_at}, cache_name)
    return done_({**doc, "bench_head": head})
