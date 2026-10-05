"""Adapter for the Grasping work track (vibe-id ``grasping``): the grasp bench's own ledger and curriculum, read live.

Inputs (the note's ``vibe-sources``; docs/dashboard/ADAPTERS.md, section ``grasping``; discovery key ``scout:grasping``):

- ``grasping_ledger``: ``grasp_bench/out/ledger/runs.jsonl``, append-only, one CellRun per measured model@env run. Every
  number on the row comes from here.
- ``grasping_curriculum``: ``grasp_bench/src/grasp_bench/curriculum.py``, the roadmap as code: TIERS, ENVS, MODELS,
  CELLS (wave1 / wave2 / needs / later / ref), GATES (Wilson-LB thresholds) and PUBLISHED_AP.
- ``grasping_out_dir``: ``grasp_bench/out``, checked only for the bench's own gallery files to link (evidence).

The rung (``track.rung``) is the frontier tier, the lowest tier whose wave-1 cells are not all measured on the frozen
protocol or whose gates are not all beaten, never the tier of the newest run: the loop measures ahead (tier 5 cells
ran while tier 2's gates were still open), so "latest" and "current" are different rungs here.

Verdicts are the bench's own: which run heads each cell, which runs are on the frozen protocol, which are
privileged, which envs are beaten or provisional. grasp_bench_bridge.py runs ``grasp_bench.gallery`` in the bench's
venv over exactly the ledger rows this adapter read, and caches the answer. WHY no copy of those rules here: the copy
this module used to carry drifted the night the bench tightened "frozen" (provenance_gap, attestations.jsonl) and read
6 of 10 gated envs beaten against the gallery's 2. When the bench cannot answer, the verdict KPIs are null with the
reason ("bench verdict unavailable: ..."), never a guess. The bridge's inputs (``grasping_bench_python``,
``grasping_attestations``, the bench's ``gallery.py`` / ``ledger.py`` / ``runner.py`` / ``contracts.py`` and the
``grasping_verdict_cache`` folder) are declared sources too, so the build reruns this adapter when any of them changes.

Iteration: a **tier phase**, the rows of one curriculum tier under one training seed, in the order the ledger first saw
them (T0, T1, T2, then "T1 · seed 1" when the 3-seed runs land). Each KPI value is the cumulative ledger state once
that phase's rows are in. WHY tiers and not ledger rows: the loop runs a tier at a time (``== tier N`` in its run
scripts), 60 per-row columns would be unreadable, and a tier is the rung Zach asks about ("what is the current rung").
"""

from __future__ import annotations

import json
import os
import re
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from vibetracks.benches import grasp_bench_bridge
from .base import local_time, not_reporting, rung, skeleton

#: Every sources.py key this adapter opens, and what it is to the loop (base.py READ_ROLES). The bench's code, venv and
#: attestations are ``input``: a changed gallery.py changes the verdict but does not mean the loop measured anything.
READS = {"grasping_ledger": "heartbeat", "grasping_curriculum": "heartbeat", "grasping_out_dir": "evidence",
         "grasping_attestations": "input", "grasping_gallery_py": "input", "grasping_ledger_py": "input",
         "grasping_runner_py": "input", "grasping_contracts_py": "input", "grasping_bench_python": "input",
         "grasping_verdict_cache": "input", "grasping_bench_src": "input"}
#: WHY depth 2 for the bench package: its modules sit one folder down too (models/, envs/, evaluators/), and a change to
#: any module the verdict imports must rerun this adapter (the bridge's own cache re-checks the exact imported set).
DEPTH = {"grasping_bench_src": 2}
UNAVAILABLE = "bench verdict unavailable"
UNCONFIRMED = f"unconfirmed: {UNAVAILABLE}"

#: WHY 1 s: Zach's deck, "All algorithms should run in real-time (<1s)", and BAM KPIs' 1 s computation time
#: (quoted in the loop's docs/grasping/build_proposal.py). curriculum.py carries no latency budget of its own.
LATENCY_LIMIT_MS = 1000.0
#: WHY 3: the loop's "3-seed rule" (run_wave1_seeds.sh; docs/grasping/ladder_data.py: ">= 3 training seeds").
SEED_RULE = 3
FLOOR_FAMILIES = ("floor", "heuristic")      # uniform, masked random, hill
LEARNED_FAMILIES = ("learned",)

# EnvSpec / ModelSpec field order, mirrored from grasp_bench/contracts.py so curriculum.py can be executed without
# importing the bench (numpy, torch). A changed signature raises TypeError -> an honest "not reporting" row.
_ENV_FIELDS = ("id", "title", "tier", "dof", "fidelity", "sensor", "metric", "accepts", "embodiment")
_ENV_DEFAULTS = {"min_grasps": 1, "request_k": 1, "notes": ""}
_MODEL_FIELDS = ("id", "title", "rank", "family", "input", "output", "trains", "licence")
_MODEL_DEFAULTS = {"notes": ""}


def _spec_class(name: str, fields: tuple[str, ...], defaults: dict[str, Any]) -> type:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        names = fields + tuple(defaults)
        if len(args) > len(names):
            raise TypeError(f"{name} takes {len(names)} fields, curriculum.py passed {len(args)}")
        values = dict(defaults)
        values.update(zip(names, args))
        for key, value in kwargs.items():
            if key not in names:
                raise TypeError(f"{name} has no field {key!r} (contracts.py changed?)")
            values[key] = value
        missing = [key for key in fields if key not in values]
        if missing:
            raise TypeError(f"{name} missing {missing}")
        self.__dict__.update(values)

    return type(name, (), {"__init__": __init__, "__repr__": lambda self: f"{name}({self.__dict__.get('id')!r})"})


@dataclass
class Curriculum:
    tiers: dict[int, str]
    envs: dict[str, Any]          # id -> EnvSpec-like, curriculum order
    models: dict[str, Any]        # id -> ModelSpec-like
    cells: list[Any]              # Cell(model, env, status, why)
    gates: dict[str, float]
    published_ap: dict[str, dict[str, float]]

    def tier_name(self, tier: int) -> str:
        text = self.tiers.get(tier, f"tier {tier}")
        return text.split(" - ", 1)[0].strip()

    def wave1(self) -> list[Any]:
        return [cell for cell in self.cells if cell.status == "wave1"]


_CONTRACTS_IMPORT = re.compile(r"^from \.contracts import [^\n]+$", re.MULTILINE)
_RELATIVE_IMPORT = re.compile(r"^\s*from \.\S* import", re.MULTILINE)


def load_curriculum(path: str | os.PathLike[str]) -> Curriculum:
    """Execute curriculum.py with stub EnvSpec/ModelSpec (it is pure data) and return its tables."""

    source = Path(path).read_text(encoding="utf-8")
    source, replaced = _CONTRACTS_IMPORT.subn("", source)
    leftover = _RELATIVE_IMPORT.search(source)
    if leftover:
        raise ImportError(f"curriculum.py now imports {leftover.group(0).strip()!r}; the adapter stubs only .contracts")
    module_name = "_vibetracks_grasping_curriculum"
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__dict__["EnvSpec"] = _spec_class("EnvSpec", _ENV_FIELDS, _ENV_DEFAULTS)
    module.__dict__["ModelSpec"] = _spec_class("ModelSpec", _MODEL_FIELDS, _MODEL_DEFAULTS)
    # WHY registered while it runs: @dataclass resolves the module of the class it decorates (Cell) via sys.modules.
    sys.modules[module_name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    finally:
        sys.modules.pop(module_name, None)
    namespace = module.__dict__
    for name in ("TIERS", "ENVS", "MODELS", "CELLS", "GATES"):
        if name not in namespace:
            raise KeyError(f"curriculum.py defines no {name}")
    return Curriculum(
        tiers=dict(namespace["TIERS"]),
        envs={spec.id: spec for spec in namespace["ENVS"]},
        models={spec.id: spec for spec in namespace["MODELS"]},
        cells=list(namespace["CELLS"]),
        gates=dict(namespace["GATES"]),
        published_ap={key: dict(value) for key, value in (namespace.get("PUBLISHED_AP") or {}).items()},
    )


# --------------------------------------------------------------------------------------------------------------------
# The ledger
# --------------------------------------------------------------------------------------------------------------------


@dataclass
class Run:
    index: int
    row: dict[str, Any]
    run_id: str
    cell_id: str
    model: str
    env: str
    tier: int
    started_at: str
    protocol: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.row.get(key, default)

    @property
    def train_seed(self) -> int | None:
        """The training seed this run fitted with, when it trained here (train_summary.seed); else None."""
        seed = (self.row.get("train_summary") or {}).get("seed")
        return seed if isinstance(seed, int) else None


def load_ledger(path: str | os.PathLike[str]) -> tuple[list[Run], int]:
    """(runs in append order, unreadable line count)."""

    runs: list[Run] = []
    bad = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                runs.append(Run(index=len(runs), row=row, run_id=str(row["run_id"]), cell_id=str(row["cell_id"]),
                                model=str(row["model"]), env=str(row["env"]), tier=int(row["tier"]),
                                started_at=str(row.get("started_at") or ""), protocol=dict(row.get("protocol") or {})))
            except (ValueError, KeyError, TypeError):
                bad += 1
    return runs, bad


def _family(env_id: str) -> str:
    return env_id.split("/", 1)[0]


def model_family(run: Run, cur: Curriculum) -> str | None:
    spec = cur.models.get(run.model)
    return spec.family if spec is not None else None


def _value(run: Run) -> float | None:
    value = run.get("value")
    return float(value) if isinstance(value, (int, float)) else None


# --------------------------------------------------------------------------------------------------------------------
# The bench's own verdict (grasp_bench_bridge), looked up by this adapter's runs
# --------------------------------------------------------------------------------------------------------------------


class Verdict:
    """What ``grasp_bench.gallery`` said about each run and each snapshot; this adapter never decides it itself."""

    def __init__(self, doc: dict[str, Any], runs: list[Run]) -> None:
        self.doc = doc
        self.by_id = {run.run_id: run for run in runs}
        self._runs: dict[str, dict[str, Any]] = doc.get("runs") or {}

    @classmethod
    def problem(cls, doc: dict[str, Any], runs: list[Run], subsets: dict[str, list[str]], cur: Curriculum) -> str | None:
        """Why ``doc`` cannot be used as the verdict over ``runs`` (None when it can)."""

        unjudged = [run.run_id for run in runs if run.run_id not in (doc.get("runs") or {})]
        if unjudged:
            return f"the bench did not judge {len(unjudged)} ledger rows the dashboard read (first {unjudged[0]})"
        for snapshot_id in subsets:
            data = (doc.get("snapshots") or {}).get(snapshot_id)
            if not isinstance(data, dict):
                return f"the bench returned no snapshot {snapshot_id}"
            if data.get("missing"):
                return f"the bench's ledger lacks {len(data['missing'])} rows of {snapshot_id} (first {data['missing'][0]})"
        if sorted(doc.get("gated") or []) != sorted(cur.gates):
            return "the bench's curriculum.GATES differ from the curriculum.py the dashboard read"
        return None

    def judged(self, run: Run) -> dict[str, Any]:
        return self._runs.get(run.run_id) or {}

    def frozen(self, run: Run) -> bool:
        return self.judged(run).get("frozen") is True

    def privileged(self, run: Run) -> bool:
        return self.judged(run).get("privileged") is True

    def clears_gate(self, run: Run) -> bool:
        return self.judged(run).get("clears_gate") is True

    def gap(self, run: Run) -> str:
        """The bench's provenance_gap: why the row cannot vouch for an unchanged env and model ("" when it can)."""
        return str(self.judged(run).get("provenance_gap") or "")

    def _run(self, brief: Any) -> Run | None:
        return self.by_id.get(brief.get("run_id")) if isinstance(brief, dict) else None

    def heads(self, snapshot_id: str) -> dict[str, Run]:
        data = self.doc["snapshots"][snapshot_id]
        heads = {cell_id: self._run(brief) for cell_id, brief in (data.get("heads") or {}).items()}
        return {cell_id: run for cell_id, run in heads.items() if run is not None}

    def envs(self, snapshot_id: str) -> dict[str, tuple[bool, bool, Run | None]]:
        """env id -> (beaten, provisional, best run) for every gated env, as gallery.env_verdict/env_provisional said."""
        data = self.doc["snapshots"][snapshot_id]
        return {env_id: (entry.get("beaten") is True, entry.get("provisional") is True, self._run(entry.get("best_run")))
                for env_id, entry in (data.get("envs") or {}).items()}


# --------------------------------------------------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------------------------------------------------


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _local(text: str | None) -> str:
    """A ledger or file time a person reads, local with its zone ("10-04 18:34 PDT"); naive ledger stamps are UTC."""

    return local_time(_parse_time(text))


def _mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100.0, 2)


def _short_env(env_id: str) -> str:
    return env_id.split("/", 1)[1] if "/" in env_id else env_id


def _join(items: list[str]) -> str:
    # WHY every item (audit 2026-10-04, finding 10 generalised): "+4 more" hid which envs; the page folds long text.
    return ", ".join(items)


# --------------------------------------------------------------------------------------------------------------------
# Iterations: tier phases
# --------------------------------------------------------------------------------------------------------------------


@dataclass
class Phase:
    id: str
    tier: int
    seed: int | None
    runs: list[Run]
    label: str = ""


def _phase_key(run: Run) -> tuple[int, int | None]:
    seed = run.train_seed
    # WHY "base" is a training seed equal to the run's own eval seed: the runner defaults the training seed to the
    # protocol seed (runner.py, budget.setdefault("seed", protocol.seed)), so that is the first pass; only the extra
    # 3-seed-rule passes (seeds 1, 2) are a separate phase. Read from the row, not a copied constant.
    return run.tier, (None if seed is None or seed == run.protocol.get("seed") else seed)


def phases(runs: list[Run], cur: Curriculum) -> list[Phase]:
    order: list[tuple[int, int | None]] = []
    grouped: dict[tuple[int, int | None], list[Run]] = {}
    for run in runs:
        key = _phase_key(run)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(run)
    out = []
    for tier, seed in order:
        phase_id = f"T{tier}" if seed is None else f"T{tier}-s{seed}"
        label = f"T{tier} · {cur.tier_name(tier)}" if seed is None else f"T{tier} · seed {seed}"
        out.append(Phase(id=phase_id, tier=tier, seed=seed, runs=grouped[(tier, seed)], label=label))
    return out


# --------------------------------------------------------------------------------------------------------------------
# One cumulative snapshot per phase
# --------------------------------------------------------------------------------------------------------------------


@dataclass
class Snapshot:
    """The ledger up to one phase, with the bench's verdict over it (``judged`` False: the bench could not answer)."""

    runs: list[Run]
    judged: bool
    heads: dict[str, Run]
    beaten: list[str]
    provisional: list[str]
    best: dict[str, Run | None]              # gated env -> gallery.env_verdict's best non-privileged headline
    gated_measured: list[str]
    wave1_frozen: set[str]
    wave1_any: set[str]


def snapshot(snapshot_id: str | None, runs: list[Run], cur: Curriculum, verdict: Verdict | None) -> Snapshot:
    """``runs`` under the bench's own verdict for ``snapshot_id``; without a verdict, only what needs no judgement."""

    wave1_ids = {cell.id for cell in cur.wave1()}
    anyp = {run.cell_id for run in runs if run.cell_id in wave1_ids}
    if verdict is None or snapshot_id is None:
        return Snapshot(runs=runs, judged=False, heads={}, beaten=[], provisional=[], best={}, gated_measured=[],
                        wave1_frozen=set(), wave1_any=anyp)
    envs = verdict.envs(snapshot_id)
    beaten = [env_id for env_id in cur.gates if envs.get(env_id, (False, False, None))[0]]
    provisional = [env_id for env_id in cur.gates if envs.get(env_id, (False, False, None))[1]]
    best = {env_id: envs.get(env_id, (False, False, None))[2] for env_id in cur.gates}
    measured = [env_id for env_id in cur.gates if best[env_id] is not None]
    frozen = {run.cell_id for run in runs if run.cell_id in wave1_ids and verdict.frozen(run)}
    return Snapshot(runs=runs, judged=True, heads=verdict.heads(snapshot_id), beaten=beaten, provisional=provisional,
                    best=best, gated_measured=measured, wave1_frozen=frozen, wave1_any=anyp)


def frontier_tier(snap: Snapshot, cur: Curriculum) -> int | None:
    """The lowest tier whose wave-1 cells are not all measured on the frozen protocol or whose gates are not all beaten.

    Only meaningful on a judged snapshot: both halves of the rule are the bench's verdict.
    """

    tiers = sorted({cur.envs[cell.env].tier for cell in cur.wave1() if cell.env in cur.envs})
    for tier in tiers:
        cells = [cell for cell in cur.wave1() if cur.envs.get(cell.env) and cur.envs[cell.env].tier == tier]
        gated = [env_id for env_id in cur.gates if cur.envs.get(env_id) and cur.envs[env_id].tier == tier]
        if any(cell.id not in snap.wave1_frozen for cell in cells) or any(env_id not in snap.beaten for env_id in gated):
            return tier
    return None


def _rung(cur: Curriculum, tier: int | None, runs: list[Run]) -> dict[str, Any] | None:
    """The frontier tier and the tier after it, in curriculum.py's own names (base.rung)."""

    tiers = sorted({cur.envs[cell.env].tier for cell in cur.wave1() if cell.env in cur.envs})
    if not runs or not tiers:
        return None
    if tier is None:
        return rung(f"Wave 1 complete · tiers {tiers[0]}–{tiers[-1]}", None, "curriculum.py + runs.jsonl")
    following = next((t for t in tiers if t > tier), None)
    return rung(f"Tier {tier} · {cur.tier_name(tier)}",
                f"Tier {following} · {cur.tier_name(following)}" if following is not None else None,
                "curriculum.py (TIERS, wave-1 CELLS, GATES) + runs.jsonl")


def needs_cells(cur: Curriculum) -> tuple[dict[str, list[Any]], dict[str, list[str]]]:
    """curriculum.py CELLS with status ``needs``, split the way the loop words them.

    Returns ``(approvals, other)``: ``approvals`` maps a model id to its cells whose ``why`` names a download approval
    (Zach's call), in CELLS order; ``other`` maps each remaining ``why`` to the cell ids it holds (blocked on something
    other than Zach). WHY one exported parser: the adapter's needs-you row and /needs (vibetracks/dashboard/needs.py)
    must read the same cells the same way, or the home count and the needs page disagree.
    """

    approvals: dict[str, list[Any]] = {}
    other: dict[str, list[str]] = {}
    for cell in cur.cells:
        if cell.status != "needs":
            continue
        if "approval" in (cell.why or ""):
            approvals.setdefault(cell.model, []).append(cell)
        else:
            other.setdefault(cell.why or "unnamed blocker", []).append(cell.id)
    return approvals, other


_APPROVAL_PHRASE = re.compile(r"^(?P<phrase>.*?\bapproval)\b", re.S)


def approval_phrases(cells: list[Any]) -> list[str]:
    """The words each approval cell's ``why`` uses to name the approval, verbatim and de-duplicated in CELLS order.

    ``"download approval (planar classics, BSD-3)"`` and ``"download approval: the bundled checkpoint is ..."`` both
    give ``"download approval"``: the ``why`` up to and including the word "approval" (the same word ``needs_cells``
    routes on), never reworded. WHY: /needs builds the question from these words plus the model id
    ("M5.ggcnn · download approval"); a question the loop never asked ("Approve downloading M5.ggcnn?") read as the
    loop's own words.
    """

    phrases: list[str] = []
    for cell in cells:
        match = _APPROVAL_PHRASE.match((cell.why or "").strip())
        phrase = match.group("phrase").strip() if match else (cell.why or "").strip()
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return phrases


def hardest_gated_env(cur: Curriculum) -> str | None:
    """The last gated env in curriculum order (MuJoCo stage 5 today): the milestone the loop is climbing toward."""

    gated = [env_id for env_id in cur.envs if env_id in cur.gates]
    return gated[-1] if gated else None


def dataset_env(cur: Curriculum) -> str | None:
    """The first AP env in curriculum order with published numbers (GraspNet-1B seen RealSense today)."""

    for env_id, spec in cur.envs.items():
        if spec.metric == "ap" and env_id in cur.published_ap:
            return env_id
    return None


def _best(heads: dict[str, Run], verdict: Verdict, cur: Curriculum, env_id: str, families: tuple[str, ...]) -> Run | None:
    pool = [run for run in heads.values() if run.env == env_id and _value(run) is not None
            and not verdict.privileged(run) and model_family(run, cur) in families]
    return max(pool, key=lambda run: (_value(run), run.get("ci_lo") or -1)) if pool else None


def _oracle(heads: dict[str, Run], verdict: Verdict, env_id: str) -> Run | None:
    pool = [run for run in heads.values() if run.env == env_id and _value(run) is not None and verdict.privileged(run)]
    return max(pool, key=lambda run: _value(run)) if pool else None


# --------------------------------------------------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------------------------------------------------


def _point(iteration: str, value: float | None, *, of: float | None = None, n: int | None = None,
           note: str | None = None, evidence: list[str] | None = None) -> dict[str, Any]:
    return {"iteration": iteration, "value": value, "of": of, "n": n, "spread": None, "measured": value is not None,
            "note": note, "evidence": evidence or []}


def _delta_status(values: list[dict[str, Any]], labels: list[str], *, unit: str = "", digits: int = 0,
                  direction: str = "higher") -> dict[str, str]:
    """A calm reading of the last change. Never says "regressed"; only a move in the KPI's good direction reads ok."""

    measured = [(index, point) for index, point in enumerate(values) if point["measured"]]
    if not values or not values[-1]["measured"]:
        return {"word": "not measured yet", "tone": "muted"}
    if len(measured) == 1:
        return {"word": f"first reading in {labels[measured[0][0]].split(' · ')[0]}", "tone": "muted"}
    (_, prev), (last_index, last) = measured[-2], measured[-1]
    delta = last["value"] - prev["value"]
    where = labels[last_index].split(" · ")[0] if last_index < len(labels) else ""
    if abs(delta) < 10 ** -(digits + 1):
        return {"word": f"no change in {where}", "tone": "muted"}
    text = f"{delta:+.{digits}f}" if digits else f"{delta:+.0f}"
    good = (delta > 0 and direction == "higher") or (delta < 0 and direction == "lower")
    return {"word": f"{text}{unit} in {where}", "tone": "ok" if good else "muted"}


def _prov(ledger: str, derived: str, *, curriculum: str | None = None, pointer: str | None = None) -> dict[str, Any]:
    source = ledger if curriculum is None else f"{ledger} + {curriculum}"
    return {"snapshot": None, "pointer": pointer, "source": source, "derived": derived}


def bench_paths(sources: dict[str, str]) -> grasp_bench_bridge.BenchPaths:
    """The bridge's inputs, from the declared sources only (an undeclared key is None and the bridge says so)."""

    return grasp_bench_bridge.BenchPaths(
        python=sources.get("grasping_bench_python"), ledger=sources.get("grasping_ledger"),
        attestations=sources.get("grasping_attestations"), gallery_py=sources.get("grasping_gallery_py"),
        ledger_py=sources.get("grasping_ledger_py"), curriculum_py=sources.get("grasping_curriculum"),
        runner_py=sources.get("grasping_runner_py"), contracts_py=sources.get("grasping_contracts_py"),
        cache_dir=sources.get("grasping_verdict_cache"))


Bridge = Callable[[grasp_bench_bridge.BenchPaths, dict[str, list[str]]], grasp_bench_bridge.BridgeResult]


def _unconfirmed(phase_id: str, evidence: list[str]) -> dict[str, Any]:
    return _point(phase_id, None, note=UNCONFIRMED, evidence=evidence)


UNCONFIRMED_STATUS = {"word": UNCONFIRMED, "tone": "muted"}


def build_track(work_track: Any, sources: dict[str, str], *, bridge: Bridge | None = None) -> dict[str, Any]:
    """The Grasping track. ``bridge`` is grasp_bench_bridge.bench_verdict; tests pass a fake (no bench venv needed)."""

    ledger_path = sources.get("grasping_ledger")
    curriculum_path = sources.get("grasping_curriculum")
    if not ledger_path or not curriculum_path:
        missing = [key for key in ("grasping_ledger", "grasping_curriculum") if not sources.get(key)]
        return not_reporting(work_track, f"vibe-sources lacks {', '.join(missing)}")
    if not Path(curriculum_path).is_file():
        return not_reporting(work_track, f"curriculum.py missing · {curriculum_path}")
    if not Path(ledger_path).is_file():
        return not_reporting(work_track, f"ledger missing · {ledger_path}")

    cur = load_curriculum(curriculum_path)
    runs, bad_lines = load_ledger(ledger_path)
    ledger_file, curriculum_file = Path(ledger_path), Path(curriculum_path)
    ledger_mtime, curriculum_mtime = _mtime_iso(ledger_file), _mtime_iso(curriculum_file)

    track = skeleton(work_track, unit="wave")
    all_phases = phases(runs, cur)
    labels = [phase.label for phase in all_phases]
    wave1_ids = {cell.id for cell in cur.wave1()}
    wave1_total = len(wave1_ids)
    gated_total = len(cur.gates)
    mujoco_gated = [env_id for env_id in cur.gates if _family(env_id) == "mujoco"]
    hardest = hardest_gated_env(cur)
    data_env = dataset_env(cur)

    # ---- the bench's own verdict over each cumulative phase (grasp_bench_bridge)
    cumulative_runs: list[list[Run]] = []
    cumulative: list[Run] = []
    for phase in all_phases:
        cumulative = sorted(cumulative + phase.runs, key=lambda run: run.index)
        cumulative_runs.append(cumulative)
    subsets = {phase.id: [run.run_id for run in held] for phase, held in zip(all_phases, cumulative_runs)}
    verdict: Verdict | None = None
    unavailable: str | None = None
    bridge_info: dict[str, Any] | None = None
    if runs:
        result = (bridge or grasp_bench_bridge.bench_verdict)(bench_paths(sources), subsets)
        bridge_info = result.info()
        if result.ok:
            unavailable = Verdict.problem(result.doc, runs, subsets, cur)
            verdict = None if unavailable else Verdict(result.doc, runs)
        else:
            unavailable = result.reason or "no reason given"
        if unavailable:
            bridge_info.update(ok=False, reason=unavailable)
    unavailable_note = f"{UNAVAILABLE}: {unavailable}" if unavailable else None

    # ---- iterations + cumulative snapshots
    iterations: list[dict[str, Any]] = []
    snaps: list[Snapshot] = []
    for phase, held in zip(all_phases, cumulative_runs):
        before = snaps[-1] if snaps else snapshot(None, [], cur, None)
        snap = snapshot(phase.id, held, cur, verdict)
        snaps.append(snap)
        parts = [f"{len(phase.runs)} runs"]
        if snap.judged:
            gained = [env_id for env_id in snap.beaten if env_id not in before.beaten]
            lost = [env_id for env_id in before.beaten if env_id not in snap.beaten]
            parts.append(f"+{len(snap.wave1_frozen - before.wave1_frozen)} wave-1 cells")
            if gained:
                parts.append("beaten: " + _join([_short_env(env_id) for env_id in gained]))
            elif any(env_id in cur.gates for env_id in {run.env for run in phase.runs}):
                parts.append("no gate newly cleared")
            if lost:
                parts.append("no longer clears: " + _join([_short_env(env_id) for env_id in lost]))
        first = min((run.started_at for run in phase.runs if run.started_at), default=None)
        moment = _parse_time(first)
        iterations.append({
            "id": phase.id, "label": phase.label,
            "date": moment.astimezone().date().isoformat() if moment else None,
            "marker": " · ".join(parts),
            "provenance": _prov(ledger_path, f"ledger rows with tier {phase.tier}"
                                + (f" and train_summary.seed {phase.seed}" if phase.seed is not None else "")
                                + "; marker compares the bench's verdict over the cumulative ledger before and after "
                                  "this phase"),
        })
    track["iterations"] = iterations

    # ---- evidence: one item per run, in the phase it belongs to
    by_iteration: dict[str, list[dict[str, Any]]] = {}
    by_kpi: dict[str, list[str]] = {key: [] for key in (
        "envs_beaten", "mujoco_beaten", "hardest_lb", "hardest_margin", "dataset_ap", "wave1_cells", "latency_p95",
        "seed_rule", "dirty_share")}
    for phase in all_phases:
        items = []
        for run in phase.runs:
            gate = cur.gates.get(run.env)
            if verdict is None:
                privileged = frozen = None
                status = UNAVAILABLE if gate is not None else "measured"
            else:
                privileged, frozen = verdict.privileged(run), verdict.frozen(run)
                if gate is None:
                    status = "privileged" if privileged else "measured"
                elif privileged:
                    status = "privileged (cannot beat an env)"
                elif verdict.clears_gate(run):
                    status = "pass" if frozen else "provisional"
                else:
                    status = "below gate"
            metrics: dict[str, Any] = {}
            if run.get("metric") == "top1_success":
                metrics["top-1 (%)"] = _pct(_value(run))
                metrics["Wilson LB (%)"] = _pct(run.get("ci_lo"))
                metrics["Wilson UB (%)"] = _pct(run.get("ci_hi"))
            elif run.get("metric") == "ap":
                metrics["AP"] = run.get("ap") if run.get("ap") is not None else _value(run)
            else:
                metrics[str(run.get("metric") or "value")] = _value(run)
            metrics["gate LB (%)"] = _pct(gate)
            metrics["n episodes"] = run.get("n")
            metrics["latency p50 (ms)"] = run.get("latency_ms_p50")
            metrics["latency p95 (ms)"] = run.get("latency_ms_p95")
            metrics["frozen protocol"] = frozen
            metrics["git dirty"] = run.get("git_dirty")
            episodes = (run.get("artifacts") or {}).get("episodes")
            gap = verdict.gap(run) if verdict is not None else ""
            notes = [text for text in (
                run.get("notes") or None,
                (f"not frozen: protocol {run.protocol.get('name')} seed {run.protocol.get('seed')}"
                 + (f" · {gap}" if gap else "")) if frozen is False else None,
                f"train seed {run.train_seed}" if run.train_seed is not None else None,
                "checkpoint trained elsewhere" if (run.get("train_summary") or {}).get("trained_here") is False else None,
                unavailable_note if verdict is None and gate is not None else None,
            ) if text]
            items.append({
                "id": run.run_id, "iteration": phase.id, "kind": "run", "title": run.cell_id,
                "when": run.started_at or None, "metrics": metrics, "status": status, "media": [],
                "links": ([{"label": "episodes (jsonl)", "kind": "path", "value": episodes}] if episodes else [])
                + ([{"label": "git sha", "kind": "path", "value": run.get("git_sha")}] if run.get("git_sha") else []),
                "note": " · ".join(notes) or None,
            })
            if gate is not None:
                by_kpi["envs_beaten"].append(run.run_id)
                if _family(run.env) == "mujoco":
                    by_kpi["mujoco_beaten"].append(run.run_id)
            if run.env == hardest:
                by_kpi["hardest_lb"].append(run.run_id)
                by_kpi["hardest_margin"].append(run.run_id)
            if run.env == data_env:
                by_kpi["dataset_ap"].append(run.run_id)
            if run.cell_id in wave1_ids:
                by_kpi["wave1_cells"].append(run.run_id)
            if not privileged and run.get("latency_ms_p95") is not None:
                by_kpi["latency_p95"].append(run.run_id)
            if run.train_seed is not None:
                by_kpi["seed_rule"].append(run.run_id)
            by_kpi["dirty_share"].append(run.run_id)
        by_iteration[phase.id] = items

    # ---- the bench's gallery as media, on the latest phase (only files that exist)
    media: dict[str, Any] = {}
    # WHY the declared folder and not ledger.parent.parent: a gallery rebuilt without a new ledger row must still rerun
    # the adapter, and the build only watches what the note declares.
    out_dir = Path(sources["grasping_out_dir"]) if sources.get("grasping_out_dir") else None
    gallery_refs = []
    for media_id, name, kind, mime, label in (
            ("grasping:gallery", "gallery.html", "html", "text/html", "Grasp bench gallery"),
            ("grasping:gallery-preview", "gallery-preview.html", "html", "text/html", "Gallery preview (HTML)"),
            ("grasping:gallery-preview-png", "gallery-preview.png", "image", "image/png", "Gallery preview (PNG)")):
        file = out_dir / name if out_dir is not None else None
        if file is not None and file.is_file():
            media[media_id] = {"id": media_id, "kind": kind, "label": label, "path": str(file), "mime": mime,
                               "bytes": file.stat().st_size}
            gallery_refs.append((media_id, kind, label, file))
    if gallery_refs and all_phases:
        newest = max(file.stat().st_mtime for *_, file in gallery_refs)
        lag_min = (ledger_file.stat().st_mtime - newest) / 60.0
        by_iteration[all_phases[-1].id].append({
            "id": "grasping:gallery-report", "iteration": all_phases[-1].id, "kind": "report",
            "title": "Grasp bench gallery (models × environments)",
            "when": datetime.fromtimestamp(newest, tz=timezone.utc).astimezone().isoformat(timespec="seconds"),
            "metrics": {}, "status": None,
            "media": [{"id": media_id, "kind": kind, "label": label} for media_id, kind, label, _ in gallery_refs],
            "links": [],
            "note": (f"written {lag_min:.0f} min before the ledger's last write; it may miss the newest rows"
                     if lag_min > 1 else "written by grasp-bench gallery from the same ledger"),
        })
    if media:
        track["media"] = media
    track["evidence"] = {"by_iteration": by_iteration, "by_kpi": by_kpi}

    def ev(kpi_id: str, phase: Phase) -> list[str]:
        wanted = set(by_kpi[kpi_id])
        return [run.run_id for run in phase.runs if run.run_id in wanted]

    def verdict_status(values: list[dict[str, Any]], **kwargs: Any) -> dict[str, str]:
        return _delta_status(values, labels, **kwargs) if verdict is not None else dict(UNCONFIRMED_STATUS)

    bridge_prov = ("grasp_bench.gallery run in the bench's own venv over these ledger rows (grasp_bench_bridge)"
                   if verdict is not None else f"{UNAVAILABLE}: {unavailable}" if unavailable else "no ledger rows")
    kpis: list[dict[str, Any]] = []

    # S1 · envs beaten: the bench's own count, never recomputed here
    values = []
    for phase, snap in zip(all_phases, snaps):
        if not snap.judged:
            values.append(_point(phase.id, None, of=gated_total, note=unavailable_note, evidence=ev("envs_beaten", phase)))
            continue
        note = ("beaten: " + _join([_short_env(e) for e in snap.beaten])) if snap.beaten else "none beaten yet"
        if snap.provisional:
            note += " · provisional: " + _join([_short_env(e) for e in snap.provisional])
        values.append(_point(phase.id, float(len(snap.beaten)), of=gated_total, note=note, evidence=ev("envs_beaten", phase)))
    kpis.append({
        "id": "envs_beaten", "label": "Gated envs beaten", "slot": "S1", "unit": "envs", "direction": "higher",
        "target": {"value": gated_total, "kind": "scope", "label": f"of {gated_total} gated envs"},
        "baseline": None, "values": values,
        "status": _delta_status(values, labels) if verdict is not None else {"word": UNAVAILABLE, "tone": "warn"},
        "note": ("The bench's own verdict (grasp_bench.gallery.env_verdict): beaten = a non-privileged headline run on "
                 "the frozen eval protocol, with provenance that can vouch for itself, whose Wilson 95% lower bound is at "
                 "or above the env's gate (curriculum.GATES). Provisional = clears the gate only on a smoke protocol."),
        "aggregate": None,
        "provenance": _prov(ledger_path, f"gallery.env_verdict per gated env · {bridge_prov}",
                            curriculum=curriculum_path, pointer="GATES"),
    })

    # S2 · MuJoCo stages beaten
    values = []
    for phase, snap in zip(all_phases, snaps):
        if not snap.judged:
            values.append(_unconfirmed(phase.id, ev("mujoco_beaten", phase)))
            continue
        measured = [e for e in mujoco_gated if e in snap.gated_measured]
        beaten = [e for e in mujoco_gated if e in snap.beaten]
        if not measured:
            values.append(_point(phase.id, None, of=len(mujoco_gated), note="no MuJoCo stage in the ledger yet",
                                 evidence=ev("mujoco_beaten", phase)))
            continue
        below = [e for e in measured if e not in beaten]
        note = ("not beaten: " + _join([_short_env(e) for e in below])) if below else "every measured stage is beaten"
        values.append(_point(phase.id, float(len(beaten)), of=len(mujoco_gated), note=note, evidence=ev("mujoco_beaten", phase)))
    kpis.append({
        "id": "mujoco_beaten", "label": "MuJoCo stages beaten", "slot": "S2", "unit": "stages", "direction": "higher",
        "target": {"value": len(mujoco_gated), "kind": "scope", "label": f"of {len(mujoco_gated)} stages"},
        "baseline": None, "values": values, "status": verdict_status(values),
        "note": "Tier 2, the track's milestone: clear the MuJoCo stages, then the dataset envs.",
        "aggregate": None,
        "provenance": _prov(ledger_path, f"gallery.env_verdict per mujoco/* env in GATES · {bridge_prov}",
                            curriculum=curriculum_path, pointer="GATES"),
    })

    # S2 · hardest gated env: the bench's best non-privileged headline, its Wilson LB vs the gate
    hardest_gate = cur.gates.get(hardest) if hardest else None
    values = []
    for phase, snap in zip(all_phases, snaps):
        if not snap.judged:
            values.append(_unconfirmed(phase.id, ev("hardest_lb", phase)))
            continue
        best = snap.best.get(hardest) if hardest else None
        if best is None or best.get("ci_lo") is None:
            values.append(_point(phase.id, None, note=f"{hardest} not in the ledger yet", evidence=ev("hardest_lb", phase)))
            continue
        trained_elsewhere = (best.get("train_summary") or {}).get("trained_here") is False
        seed_note = "one checkpoint, trained elsewhere (bam_grasp July); not a seed spread" if trained_elsewhere else None
        values.append(_point(
            phase.id, _pct(best.get("ci_lo")), n=best.get("n"),
            note=(f"{best.model}: {_pct(_value(best))}% [{_pct(best.get('ci_lo'))}, {_pct(best.get('ci_hi'))}] on "
                  f"{best.protocol.get('name')}" + ("" if verdict.frozen(best) else " (not the frozen protocol)")
                  + (f" · {seed_note}" if seed_note else "")),
            evidence=ev("hardest_lb", phase)))
    status = verdict_status(values, unit=" pts", digits=1)
    if verdict is not None and values and values[-1]["measured"] and hardest_gate is not None:
        gap = values[-1]["value"] - hardest_gate * 100
        status = {"word": (f"clears gate by {gap:.1f} pts" if gap >= 0 else f"{-gap:.1f} pts below gate"),
                  "tone": "ok" if gap >= 0 else "muted"}
    kpis.append({
        "id": "hardest_lb", "label": f"Hardest gated env · {hardest} · best Wilson LB" if hardest else "Hardest gated env",
        "slot": "S2", "unit": "%", "direction": "higher",
        "target": ({"gate": round(hardest_gate * 100, 2), "value": round(hardest_gate * 100, 2), "kind": "gate",
                    "label": f"gate LB ≥ {hardest_gate * 100:.0f} %"} if hardest_gate is not None else None),
        "baseline": None, "values": values, "status": status,
        "note": "The Wilson 95% lower bound of the bench's best non-privileged headline run on the last gated env in "
                "curriculum order.",
        "aggregate": None,
        "provenance": _prov(ledger_path, f"gallery.env_verdict({hardest}) best run's ci_lo × 100 · {bridge_prov}",
                            curriculum=curriculum_path),
    })

    # S2 · margin of the best learned model over the best floor on the hardest env (over the bench's headline runs)
    values = []
    for phase, snap in zip(all_phases, snaps):
        if not snap.judged:
            values.append(_unconfirmed(phase.id, ev("hardest_margin", phase)))
            continue
        learned = _best(snap.heads, verdict, cur, hardest, LEARNED_FAMILIES) if hardest else None
        floor = _best(snap.heads, verdict, cur, hardest, FLOOR_FAMILIES) if hardest else None
        if learned is None or floor is None:
            missing = "a learned run" if learned is None else "a floor run"
            values.append(_point(phase.id, None, note=f"{hardest}: no {missing} yet", evidence=ev("hardest_margin", phase)))
            continue
        oracle = _oracle(snap.heads, verdict, hardest)
        note = (f"{learned.model} {_pct(_value(learned))}% − {floor.model} {_pct(_value(floor))}%"
                + (f" · oracle {oracle.model} {_pct(_value(oracle))}%" if oracle else " · no oracle run yet")
                + " · difference of headline rates (the bench's paired test is stats.paired_proportion_diff)")
        values.append(_point(phase.id, round((_value(learned) - _value(floor)) * 100, 2), n=learned.get("n"), note=note,
                             evidence=ev("hardest_margin", phase)))
    kpis.append({
        "id": "hardest_margin", "label": f"Learned over best floor · {_short_env(hardest) if hardest else '?'}",
        "slot": "S2", "unit": "pts", "direction": "higher",
        "target": {"value": 0, "kind": "reference", "label": "above 0 = beats uniform, masked and hill"},
        "baseline": None, "values": values, "status": verdict_status(values, unit=" pts", digits=1),
        "note": "Best learned model's top-1 minus the best of the floors (uniform, masked random, hill) on the same env, "
                "over the bench's headline runs.",
        "aggregate": None,
        "provenance": _prov(ledger_path, f"max learned value − max floor/heuristic value over gallery.headline_runs · "
                            f"{bridge_prov}", curriculum=curriculum_path),
    })

    # S2 · dataset AP (first dataset env), beside oracle and published
    published = cur.published_ap.get(data_env or "", {})
    best_published = max(published.items(), key=lambda item: item[1]) if published else None
    values = []
    for phase, snap in zip(all_phases, snaps):
        if not snap.judged:
            values.append(_unconfirmed(phase.id, ev("dataset_ap", phase)))
            continue
        pool = [run for run in snap.heads.values() if run.env == data_env and not verdict.privileged(run)
                and (run.get("ap") is not None or _value(run) is not None)]
        if not pool:
            values.append(_point(phase.id, None, note=f"no {data_env} row in runs.jsonl yet (smoke numbers outside the ledger are not used)",
                                 evidence=ev("dataset_ap", phase)))
            continue
        best = max(pool, key=lambda run: run.get("ap") if run.get("ap") is not None else _value(run))
        ap = best.get("ap") if best.get("ap") is not None else _value(best)
        oracle = _oracle(snap.heads, verdict, data_env)
        ci = (f" [{best.get('ap_ci_lo'):.3f}, {best.get('ap_ci_hi'):.3f}]"
              if isinstance(best.get("ap_ci_lo"), (int, float)) and isinstance(best.get("ap_ci_hi"), (int, float)) else "")
        note = f"{best.model} AP {ap:.3f}{ci} on {best.protocol.get('name')} (AP on the 0-100 scale)" + (
            f" · oracle {oracle.get('ap') if oracle.get('ap') is not None else _value(oracle)}" if oracle else " · no oracle run yet")
        values.append(_point(phase.id, round(ap, 3), n=best.get("n"), note=note, evidence=ev("dataset_ap", phase)))
    kpis.append({
        "id": "dataset_ap", "label": f"Dataset AP · {data_env}" if data_env else "Dataset AP", "slot": "S2", "unit": "AP",
        "direction": "higher",
        "target": ({"value": best_published[1], "kind": "reference",
                    "label": f"published best {best_published[0]} {best_published[1]}"} if best_published else None),
        "baseline": None, "values": values, "status": verdict_status(values, digits=1),
        "note": "Dataset envs are ungated: progress is AP above the previous best, beside the oracle and the published rows "
                "(curriculum.PUBLISHED_AP).",
        "aggregate": None,
        "provenance": _prov(ledger_path, f"max non-privileged headline ap · {bridge_prov}", curriculum=curriculum_path,
                            pointer="PUBLISHED_AP"),
    })

    # S3 · latency guardrail: slowest non-privileged p95
    values = []
    for phase, snap in zip(all_phases, snaps):
        if not snap.judged:
            values.append(_unconfirmed(phase.id, ev("latency_p95", phase)))
            continue
        pool = [run for run in snap.heads.values() if not verdict.privileged(run)
                and isinstance(run.get("latency_ms_p95"), (int, float))]
        if not pool:
            values.append(_point(phase.id, None, note="no latency recorded yet", evidence=ev("latency_p95", phase)))
            continue
        slowest = max(pool, key=lambda run: run.get("latency_ms_p95"))
        over = [run.cell_id for run in pool if run.get("latency_ms_p95") > LATENCY_LIMIT_MS]
        note = f"slowest: {slowest.cell_id}" + (f" · over 1 s: {_join(over)}" if over else "")
        values.append(_point(phase.id, round(slowest.get("latency_ms_p95"), 1), n=slowest.get("n"), note=note,
                             evidence=ev("latency_p95", phase)))
    status = verdict_status(values, unit=" ms")
    if verdict is not None and values and values[-1]["measured"]:
        last = values[-1]["value"]
        status = ({"word": f"over 1 s · {last:.0f} ms", "tone": "warn"} if last > LATENCY_LIMIT_MS
                  else {"word": f"within 1 s · {last:.0f} ms", "tone": "ok"})
    kpis.append({
        "id": "latency_p95", "label": "Slowest p95 latency (non-privileged)", "slot": "S3", "unit": "ms",
        "direction": "lower",
        "target": {"value": LATENCY_LIMIT_MS, "kind": "limit", "label": "< 1 s (Zach's deck; BAM KPIs)"},
        "baseline": None, "values": values, "status": status,
        "note": "Per-prediction latency as the runner measured it, in sim; the real camera capture time is not included.",
        "aggregate": None,
        "provenance": _prov(ledger_path, f"max latency_ms_p95 over non-privileged headline runs · {bridge_prov}"),
    })

    # S4 · wave-1 cells measured on the frozen protocol (frozen = the bench's is_frozen_protocol)
    values = []
    for phase, snap in zip(all_phases, snaps):
        if not snap.judged:
            values.append(_unconfirmed(phase.id, ev("wave1_cells", phase)))
            continue
        extra = len(snap.wave1_any) - len(snap.wave1_frozen)
        note = f"{extra} more measured only off the frozen protocol" if extra else None
        values.append(_point(phase.id, float(len(snap.wave1_frozen)), of=wave1_total, note=note, evidence=ev("wave1_cells", phase)))
    kpis.append({
        "id": "wave1_cells", "label": "Wave-1 cells measured", "slot": "S4", "unit": "cells", "direction": "higher",
        "target": {"value": wave1_total, "kind": "scope", "label": f"of {wave1_total} wave-1 cells"},
        "baseline": None, "values": values, "status": verdict_status(values),
        "note": "A cell counts once it has a run the bench calls frozen (gallery.is_frozen_protocol) "
                "(curriculum.cells('wave1')).",
        "aggregate": None,
        "provenance": _prov(ledger_path, f"distinct wave-1 cell_ids with a frozen-protocol run · {bridge_prov}",
                            curriculum=curriculum_path, pointer="CELLS"),
    })

    # S5 · 3-seed rule on cells trained here. WHY still measured without the bench's verdict: it counts
    # train_summary.seed per cell, a raw ledger field the gallery does not judge.
    values = []
    for phase, snap in zip(all_phases, snaps):
        seeds: dict[str, set[int]] = {}
        for run in snap.runs:
            if run.train_seed is not None and run.cell_id in wave1_ids:
                seeds.setdefault(run.cell_id, set()).add(run.train_seed)
        if not seeds:
            values.append(_point(phase.id, None, note="no cell trained here yet", evidence=ev("seed_rule", phase)))
            continue
        done = sum(1 for found in seeds.values() if len(found) >= SEED_RULE)
        counts = sorted({len(found) for found in seeds.values()})
        values.append(_point(phase.id, float(done), of=len(seeds),
                             note=f"seeds per trained cell: {', '.join(str(c) for c in counts)}", evidence=ev("seed_rule", phase)))
    status = _delta_status(values, labels)
    if values and values[-1]["measured"] and values[-1]["value"] < (values[-1]["of"] or 0):
        status = {"word": "unconfirmed · repeat needed", "tone": "muted"}
    kpis.append({
        "id": "seed_rule", "label": f"Trained cells with ≥ {SEED_RULE} seeds", "slot": "S5", "unit": "cells",
        "direction": "higher", "target": None, "baseline": None, "values": values, "status": status,
        "note": ("Cells whose model trained in this bench (train_summary.seed). A learned result on one training seed is "
                 "unconfirmed until the 3-seed rule runs. MuJoCo bandit checkpoints were trained elsewhere and are not counted."),
        "aggregate": None,
        "provenance": _prov(ledger_path, "distinct train_summary.seed per wave-1 cell"),
    })

    # S5 · evidence trust: share of rows from a dirty tree (a raw ledger field; no verdict involved)
    values = []
    for phase, snap in zip(all_phases, snaps):
        total = len(snap.runs)
        dirty = sum(1 for run in snap.runs if run.get("git_dirty") is True)
        values.append(_point(phase.id, round(100.0 * dirty / total, 1) if total else None, n=total,
                             note=f"{dirty} of {total} rows git_dirty", evidence=ev("dirty_share", phase)))
    kpis.append({
        "id": "dirty_share", "label": "Runs from a dirty tree", "slot": "S5", "unit": "%", "direction": "lower",
        "target": None, "baseline": None, "values": values, "status": _delta_status(values, labels, unit=" pts", digits=1, direction="lower"),
        "note": "A dirty run cannot be reproduced from its git_sha alone.",
        "aggregate": None,
        "provenance": _prov(ledger_path, "count(git_dirty) / rows, cumulative"),
    })

    track["kpis"] = kpis
    track["north_star"] = "envs_beaten"

    # ---- needs you: download approvals named in curriculum.py "needs" cells
    approval_cells, other_needs = needs_cells(cur)
    needs = []
    for model_id, cells in approval_cells.items():
        spec = cur.models.get(model_id)
        title = spec.title if spec else model_id
        detail = f" {spec.notes}" if spec and spec.notes else ""
        licence = f" Licence: {spec.licence}." if spec else ""
        needs.append({"id": f"grasping:download:{model_id}", "q": f"Approve the {title} download?{detail}{licence}",
                      "blocks": [cell.id for cell in cells], "default": None, "applies": None})
    track["needs_you"] = needs

    # ---- state + summary
    latest = snaps[-1] if snaps else snapshot(None, [], cur, None)
    tier = frontier_tier(latest, cur) if latest.judged else None
    last_run = max(runs, key=lambda run: run.started_at) if runs else None
    toy_gated = [e for e in cur.gates if _family(e) == "toy"]
    tail = [f"last run started {_local(last_run.started_at)}" if last_run else "", f"ledger written {_local(ledger_mtime)}",
            f"{bad_lines} unreadable ledger lines skipped" if bad_lines else ""]
    if not runs:
        track["state"] = {"word": "No runs yet", "tone": "muted", "detail": f"runs.jsonl is empty · written {_local(ledger_mtime)}",
                          "since": None}
        track["summary"] = f"no ledger rows yet · {wave1_total} wave-1 cells planned"
    elif verdict is None:
        # WHY no frontier and no counts: both are the bench's verdict, and a guess would read as the bench's word.
        track["state"] = {"word": "Bench verdict unavailable", "tone": "warn",
                          "detail": " · ".join(bit for bit in [unavailable or "", f"{len(runs)} ledger rows"] + tail if bit),
                          "since": None}
        track["summary"] = (f"{UNAVAILABLE}: {unavailable} · {len(runs)} ledger rows · {wave1_total} wave-1 cells planned"
                            + (f" · {len(needs)} download approvals open" if needs else ""))
    else:
        if tier is None:
            word, detail_bits = "Wave 1 complete", ["every wave-1 cell measured and every gate beaten"]
            since = None
        else:
            tier_envs = [e for e in cur.gates if cur.envs[e].tier == tier]
            tier_cells = [c for c in cur.wave1() if cur.envs.get(c.env) and cur.envs[c.env].tier == tier]
            done_cells = sum(1 for c in tier_cells if c.id in latest.wave1_frozen)
            word = f"Tier {tier} · {cur.tier_name(tier)}"
            detail_bits = [f"{done_cells} of {len(tier_cells)} tier-{tier} cells measured"]
            if tier_envs:
                below = [e for e in tier_envs if e not in latest.beaten]
                detail_bits.append(f"{len(tier_envs) - len(below)} of {len(tier_envs)} gates beaten"
                                   + (f" (open: {_join([_short_env(e) for e in below])})" if below else ""))
            next_tier = next((t for t in sorted({cur.envs[c.env].tier for c in cur.wave1()}) if t > tier), None)
            if next_tier is not None:
                next_cells = [c for c in cur.wave1() if cur.envs[c.env].tier == next_tier]
                next_done = sum(1 for c in next_cells if c.id in latest.wave1_frozen)
                detail_bits.append(f"next tier {next_tier} {cur.tier_name(next_tier)}: {next_done} of {len(next_cells)} cells")
            tier_runs = [run.started_at for run in runs if run.tier == tier and run.started_at]
            since = min(tier_runs) if tier_runs else None
        track["state"] = {"word": word, "tone": "ok", "detail": " · ".join(bit for bit in detail_bits + tail if bit),
                          "since": since}
        mujoco_beaten = [e for e in mujoco_gated if e in latest.beaten]
        toy_beaten = [e for e in toy_gated if e in latest.beaten]
        summary = (f"{len(latest.beaten)} of {gated_total} gated envs beaten (toy {len(toy_beaten)}/{len(toy_gated)}, "
                   f"MuJoCo {len(mujoco_beaten)}/{len(mujoco_gated)}) · {len(latest.wave1_frozen)} of {wave1_total} "
                   f"wave-1 cells measured")
        if tier is not None:
            summary += f" · frontier tier {tier} ({cur.tier_name(tier)})"
        if needs:
            summary += f" · {len(needs)} download approvals open"
        track["summary"] = summary
    track["iteration"] = {"unit": "wave", "label": all_phases[-1].label if all_phases else "none reported"}
    track["rung"] = _rung(cur, tier, runs) if verdict is not None else None

    # ---- links + provenance
    bench_dir = curriculum_file.parent.parent.parent
    track["links"] = (
        [{"label": label, "kind": "media", "media": media_id} for media_id, _, label, _ in gallery_refs]
        + [{"label": "Ledger (runs.jsonl)", "kind": "path", "value": ledger_path},
           {"label": "Curriculum (curriculum.py)", "kind": "path", "value": curriculum_path},
           {"label": "Rebuild the bench gallery", "kind": "command",
            "value": f"cd {bench_dir} && env -u VIRTUAL_ENV .venv/bin/grasp-bench gallery"}]
    )
    if other_needs and all_phases:
        by_iteration[all_phases[-1].id].append({
            "id": "grasping:blocked-cells", "iteration": all_phases[-1].id, "kind": "note",
            "title": "Cells blocked on something other than you", "when": curriculum_mtime,
            "metrics": {why: len(cells) for why, cells in other_needs.items()}, "status": "blocked", "media": [],
            "links": [], "note": " · ".join(f"{why}: {_join(cells)}" for why, cells in other_needs.items()),
        })
    # WHY source.problems (the rig adapter's field; the build merges an adapter's source block): a missing verdict is
    # a problem with the track's inputs, and the page's source panel is where an input problem is read.
    track["source"] = {"problems": [p for p in (unavailable_note,
                                                f"{bad_lines} unreadable ledger lines skipped" if bad_lines else None) if p],
                       "bench_verdict": bridge_info}
    track["provenance"] = {
        "snapshot": None, "pointer": None, "source": ledger_path,
        "derived": (f"{len(runs)} ledger rows (written {ledger_mtime}) grouped into tier phases; curriculum.py "
                    f"(written {curriculum_mtime}) for tiers, wave-1 cells, gates and published AP; verdicts: "
                    f"{bridge_prov}"),
    }
    return track
