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

Derivations mirror the bench's own gallery.py (``headline_runs``, ``is_frozen_protocol``, ``clears_gate``,
``env_verdict``) so the dashboard and the bench's gallery agree on which envs are beaten; the live smoke test in
tests/test_dashboard_adapter_grasping.py checks that against the bench's own code when its venv is on the machine.

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
from typing import Any

from .base import local_time, not_reporting, rung, skeleton

#: Every sources.py key this adapter opens, and what it is to the loop (base.py READ_ROLES).
READS = {"grasping_ledger": "heartbeat", "grasping_curriculum": "heartbeat", "grasping_out_dir": "evidence"}

# --------------------------------------------------------------------------------------------------------------------
# Mirrors of the bench's frozen protocol (grasp_bench/runner.py DEFAULT_PROTOCOLS, contracts.EvalProtocol.seed).
# WHY mirrored and not read: runner.py and contracts.py are not declared sources (only the ledger and curriculum.py
# are), and contracts.py imports numpy, which the dashboard backend does not need. If the bench changes its frozen
# protocol, the live smoke test (which runs the bench's own gallery.env_verdict) goes red.
# --------------------------------------------------------------------------------------------------------------------
FROZEN_EVAL_SEED = 20261004
DEFAULT_PROTOCOLS: dict[str, tuple[str, int]] = {
    "bandit": ("eval-2000", 2000),
    "toy": ("eval-2000", 2000),
    "mujoco": ("eval-200", 200),
    "graspnet1b": ("ts30x8-staggered", 240),
    "gc6d": ("gc6d-30x4", 120),
}
FALLBACK_PROTOCOL = ("eval-200", 200)
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


def frozen_protocol(env_id: str) -> tuple[str, int]:
    return DEFAULT_PROTOCOLS.get(_family(env_id), FALLBACK_PROTOCOL)


def is_frozen(run: Run, cur: Curriculum) -> bool:
    """gallery.is_frozen_protocol: default name/seed/episodes, test split, no options, every episode scored, default k."""

    spec = cur.envs.get(run.env)
    if spec is None:
        return False
    name, episodes = frozen_protocol(run.env)
    frozen_k = max(getattr(spec, "request_k", 1), getattr(spec, "min_grasps", 1), 1)
    protocol = run.protocol
    return (protocol.get("name") == name and protocol.get("seed") == FROZEN_EVAL_SEED
            and protocol.get("episodes") == episodes and protocol.get("split") == "test"
            and not protocol.get("options") and not run.get("env_options") and run.get("n") == episodes
            and protocol.get("k") == frozen_k)


def is_privileged(run: Run, cur: Curriculum) -> bool:
    """gallery._privileged: by the run's recorded input, or by the model's curriculum family."""

    if (run.get("model_info") or {}).get("input") == "privileged":
        return True
    spec = cur.models.get(run.model)
    return spec is not None and spec.family == "privileged"


def model_family(run: Run, cur: Curriculum) -> str | None:
    spec = cur.models.get(run.model)
    return spec.family if spec is not None else None


def clears_gate(run: Run, cur: Curriculum) -> bool:
    gate = cur.gates.get(run.env)
    ci_lo = run.get("ci_lo")
    return (gate is not None and run.get("metric") == "top1_success" and isinstance(ci_lo, (int, float))
            and ci_lo >= gate and not is_privileged(run, cur))


def headline_runs(runs: list[Run], cur: Curriculum) -> dict[str, Run]:
    """gallery.headline_runs: per cell, a frozen run first, then the largest n, then the latest start, then the last written."""

    best: dict[str, tuple[tuple, Run]] = {}
    for run in runs:
        key = (is_frozen(run, cur), run.get("n") or 0, run.started_at, run.index)
        if run.cell_id not in best or key > best[run.cell_id][0]:
            best[run.cell_id] = (key, run)
    return {cell_id: pair[1] for cell_id, pair in best.items()}


def _value(run: Run) -> float | None:
    value = run.get("value")
    return float(value) if isinstance(value, (int, float)) else None


def env_verdict(env_id: str, heads: dict[str, Run], cur: Curriculum) -> tuple[bool, Run | None]:
    """gallery.env_verdict: (beaten, best non-privileged headline). The oracle never beats an env."""

    candidates = [run for run in heads.values()
                  if run.env == env_id and _value(run) is not None and not is_privileged(run, cur)]
    if not candidates:
        return False, None
    best = max(candidates, key=lambda run: (_value(run), run.get("ci_lo") if run.get("ci_lo") is not None else -1))
    winners = [run for run in candidates if clears_gate(run, cur) and is_frozen(run, cur)]
    if winners:
        return True, max(winners, key=lambda run: run.get("ci_lo"))
    return False, best


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


def _join(items: list[str], limit: int = 6) -> str:
    return ", ".join(items[:limit]) + (f" +{len(items) - limit} more" if len(items) > limit else "")


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
    # WHY the frozen eval seed reads as "base": the first training pass uses the bench's default seed (20261004); only
    # the extra 3-seed-rule passes (seeds 1, 2) are a separate phase.
    return run.tier, (None if seed in (None, FROZEN_EVAL_SEED) else seed)


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
    runs: list[Run]
    heads: dict[str, Run]
    beaten: list[str]
    gated_measured: list[str]
    wave1_frozen: set[str]
    wave1_any: set[str]


def snapshot(runs: list[Run], cur: Curriculum) -> Snapshot:
    heads = headline_runs(runs, cur)
    beaten, measured = [], []
    for env_id in cur.gates:
        won, best = env_verdict(env_id, heads, cur)
        if best is not None:
            measured.append(env_id)
        if won:
            beaten.append(env_id)
    wave1_ids = {cell.id for cell in cur.wave1()}
    frozen = {run.cell_id for run in runs if run.cell_id in wave1_ids and is_frozen(run, cur)}
    anyp = {run.cell_id for run in runs if run.cell_id in wave1_ids}
    return Snapshot(runs=runs, heads=heads, beaten=beaten, gated_measured=measured, wave1_frozen=frozen, wave1_any=anyp)


def frontier_tier(snap: Snapshot, cur: Curriculum) -> int | None:
    """The lowest tier whose wave-1 cells are not all measured on the frozen protocol or whose gates are not all beaten."""

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


def _best(heads: dict[str, Run], cur: Curriculum, env_id: str, families: tuple[str, ...]) -> Run | None:
    pool = [run for run in heads.values() if run.env == env_id and _value(run) is not None
            and not is_privileged(run, cur) and model_family(run, cur) in families]
    return max(pool, key=lambda run: (_value(run), run.get("ci_lo") or -1)) if pool else None


def _oracle(heads: dict[str, Run], cur: Curriculum, env_id: str) -> Run | None:
    pool = [run for run in heads.values() if run.env == env_id and _value(run) is not None and is_privileged(run, cur)]
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


def build_track(work_track: Any, sources: dict[str, str]) -> dict[str, Any]:
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

    # ---- iterations + cumulative snapshots
    iterations: list[dict[str, Any]] = []
    snaps: list[Snapshot] = []
    cumulative: list[Run] = []
    for phase in all_phases:
        before = snaps[-1] if snaps else snapshot([], cur)
        cumulative = cumulative + phase.runs
        snap = snapshot(sorted(cumulative, key=lambda run: run.index), cur)
        snaps.append(snap)
        new_cells = len(snap.wave1_frozen - before.wave1_frozen)
        gained = [env_id for env_id in snap.beaten if env_id not in before.beaten]
        lost = [env_id for env_id in before.beaten if env_id not in snap.beaten]
        parts = [f"{len(phase.runs)} runs", f"+{new_cells} wave-1 cells"]
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
                                + "; marker compares the cumulative ledger before and after this phase"),
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
            privileged = is_privileged(run, cur)
            frozen = is_frozen(run, cur)
            if gate is None:
                status = "privileged" if privileged else "measured"
            elif privileged:
                status = "privileged (cannot beat an env)"
            elif clears_gate(run, cur):
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
            notes = [text for text in (
                run.get("notes") or None,
                f"protocol {run.protocol.get('name')} seed {run.protocol.get('seed')}" if not frozen else None,
                f"train seed {run.train_seed}" if run.train_seed is not None else None,
                "checkpoint trained elsewhere" if (run.get("train_summary") or {}).get("trained_here") is False else None,
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

    kpis: list[dict[str, Any]] = []

    # S1 · envs beaten
    values = []
    for phase, snap in zip(all_phases, snaps):
        note = ("beaten: " + _join([_short_env(e) for e in snap.beaten], 10)) if snap.beaten else "none beaten yet"
        values.append(_point(phase.id, float(len(snap.beaten)), of=gated_total, note=note, evidence=ev("envs_beaten", phase)))
    kpis.append({
        "id": "envs_beaten", "label": "Gated envs beaten", "slot": "S1", "unit": "envs", "direction": "higher",
        "target": {"value": gated_total, "kind": "scope", "label": f"of {gated_total} gated envs"},
        "baseline": None, "values": values, "status": _delta_status(values, labels),
        "note": ("Beaten = a non-privileged headline run on the frozen eval protocol whose Wilson 95% lower bound is at or "
                 "above the env's gate (curriculum.GATES); the oracle cannot beat an env. Same rule as the bench's gallery."),
        "aggregate": None,
        "provenance": _prov(ledger_path, "gallery.env_verdict over headline runs (frozen first, then largest n, then latest)",
                            curriculum=curriculum_path, pointer="GATES"),
    })

    # S2 · MuJoCo stages beaten
    values = []
    for phase, snap in zip(all_phases, snaps):
        measured = [e for e in mujoco_gated if e in snap.gated_measured]
        beaten = [e for e in mujoco_gated if e in snap.beaten]
        if not measured:
            values.append(_point(phase.id, None, of=len(mujoco_gated), note="no MuJoCo stage in the ledger yet",
                                 evidence=ev("mujoco_beaten", phase)))
            continue
        below = [e for e in measured if e not in beaten]
        note = ("below gate: " + _join([_short_env(e) for e in below])) if below else "every measured stage clears its gate"
        values.append(_point(phase.id, float(len(beaten)), of=len(mujoco_gated), note=note, evidence=ev("mujoco_beaten", phase)))
    kpis.append({
        "id": "mujoco_beaten", "label": "MuJoCo stages beaten", "slot": "S2", "unit": "stages", "direction": "higher",
        "target": {"value": len(mujoco_gated), "kind": "scope", "label": f"of {len(mujoco_gated)} stages"},
        "baseline": None, "values": values, "status": _delta_status(values, labels),
        "note": "Tier 2, the track's milestone: clear the MuJoCo stages, then the dataset envs.",
        "aggregate": None,
        "provenance": _prov(ledger_path, "env_verdict per mujoco/* env in GATES", curriculum=curriculum_path, pointer="GATES"),
    })

    # S2 · hardest gated env: best non-privileged Wilson LB vs its gate
    hardest_gate = cur.gates.get(hardest) if hardest else None
    values = []
    hardest_seed_note = None
    for phase, snap in zip(all_phases, snaps):
        _, best = env_verdict(hardest, snap.heads, cur) if hardest else (False, None)
        if best is None or best.get("ci_lo") is None:
            values.append(_point(phase.id, None, note=f"{hardest} not in the ledger yet", evidence=ev("hardest_lb", phase)))
            continue
        trained_elsewhere = (best.get("train_summary") or {}).get("trained_here") is False
        hardest_seed_note = ("one checkpoint, trained elsewhere (bam_grasp July); not a seed spread" if trained_elsewhere
                             else None)
        values.append(_point(
            phase.id, _pct(best.get("ci_lo")), n=best.get("n"),
            note=(f"{best.model}: {_pct(_value(best))}% [{_pct(best.get('ci_lo'))}, {_pct(best.get('ci_hi'))}] on "
                  f"{best.protocol.get('name')}" + (f" · {hardest_seed_note}" if hardest_seed_note else "")),
            evidence=ev("hardest_lb", phase)))
    status = _delta_status(values, labels, unit=" pts", digits=1)
    if values and values[-1]["measured"] and hardest_gate is not None:
        gap = values[-1]["value"] - hardest_gate * 100
        status = {"word": (f"clears gate by {gap:.1f} pts" if gap >= 0 else f"{-gap:.1f} pts below gate"),
                  "tone": "ok" if gap >= 0 else "muted"}
    kpis.append({
        "id": "hardest_lb", "label": f"Hardest gated env · {hardest} · best Wilson LB" if hardest else "Hardest gated env",
        "slot": "S2", "unit": "%", "direction": "higher",
        "target": ({"gate": round(hardest_gate * 100, 2), "value": round(hardest_gate * 100, 2), "kind": "gate",
                    "label": f"gate LB ≥ {hardest_gate * 100:.0f} %"} if hardest_gate is not None else None),
        "baseline": None, "values": values, "status": status,
        "note": "The best non-privileged model's Wilson 95% lower bound on the last gated env in curriculum order.",
        "aggregate": None,
        "provenance": _prov(ledger_path, f"env_verdict({hardest}) best run's ci_lo × 100", curriculum=curriculum_path),
    })

    # S2 · margin of the best learned model over the best floor on the hardest env
    values = []
    for phase, snap in zip(all_phases, snaps):
        learned = _best(snap.heads, cur, hardest, LEARNED_FAMILIES) if hardest else None
        floor = _best(snap.heads, cur, hardest, FLOOR_FAMILIES) if hardest else None
        if learned is None or floor is None:
            missing = "a learned run" if learned is None else "a floor run"
            values.append(_point(phase.id, None, note=f"{hardest}: no {missing} yet", evidence=ev("hardest_margin", phase)))
            continue
        oracle = _oracle(snap.heads, cur, hardest)
        note = (f"{learned.model} {_pct(_value(learned))}% − {floor.model} {_pct(_value(floor))}%"
                + (f" · oracle {oracle.model} {_pct(_value(oracle))}%" if oracle else " · no oracle run yet")
                + " · difference of headline rates (the bench's paired test is stats.paired_proportion_diff)")
        values.append(_point(phase.id, round((_value(learned) - _value(floor)) * 100, 2), n=learned.get("n"), note=note,
                             evidence=ev("hardest_margin", phase)))
    kpis.append({
        "id": "hardest_margin", "label": f"Learned over best floor · {_short_env(hardest) if hardest else '?'}",
        "slot": "S2", "unit": "pts", "direction": "higher",
        "target": {"value": 0, "kind": "reference", "label": "above 0 = beats uniform, masked and hill"},
        "baseline": None, "values": values, "status": _delta_status(values, labels, unit=" pts", digits=1),
        "note": "Best learned model's top-1 minus the best of the floors (uniform, masked random, hill) on the same env and protocol.",
        "aggregate": None,
        "provenance": _prov(ledger_path, "max learned value − max floor/heuristic value, headline runs", curriculum=curriculum_path),
    })

    # S2 · dataset AP (first dataset env), beside oracle and published
    published = cur.published_ap.get(data_env or "", {})
    best_published = max(published.items(), key=lambda item: item[1]) if published else None
    values = []
    for phase, snap in zip(all_phases, snaps):
        pool = [run for run in snap.heads.values() if run.env == data_env and not is_privileged(run, cur)
                and (run.get("ap") is not None or _value(run) is not None)]
        if not pool:
            values.append(_point(phase.id, None, note=f"no {data_env} row in runs.jsonl yet (smoke numbers outside the ledger are not used)",
                                 evidence=ev("dataset_ap", phase)))
            continue
        best = max(pool, key=lambda run: run.get("ap") if run.get("ap") is not None else _value(run))
        ap = best.get("ap") if best.get("ap") is not None else _value(best)
        oracle = _oracle(snap.heads, cur, data_env)
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
        "baseline": None, "values": values, "status": _delta_status(values, labels, digits=1),
        "note": "Dataset envs are ungated: progress is AP above the previous best, beside the oracle and the published rows "
                "(curriculum.PUBLISHED_AP).",
        "aggregate": None,
        "provenance": _prov(ledger_path, "max non-privileged headline ap", curriculum=curriculum_path, pointer="PUBLISHED_AP"),
    })

    # S3 · latency guardrail: slowest non-privileged p95
    values = []
    for phase, snap in zip(all_phases, snaps):
        pool = [run for run in snap.heads.values() if not is_privileged(run, cur)
                and isinstance(run.get("latency_ms_p95"), (int, float))]
        if not pool:
            values.append(_point(phase.id, None, note="no latency recorded yet", evidence=ev("latency_p95", phase)))
            continue
        slowest = max(pool, key=lambda run: run.get("latency_ms_p95"))
        over = [run.cell_id for run in pool if run.get("latency_ms_p95") > LATENCY_LIMIT_MS]
        note = f"slowest: {slowest.cell_id}" + (f" · over 1 s: {_join(over)}" if over else "")
        values.append(_point(phase.id, round(slowest.get("latency_ms_p95"), 1), n=slowest.get("n"), note=note,
                             evidence=ev("latency_p95", phase)))
    status = _delta_status(values, labels, unit=" ms")
    if values and values[-1]["measured"]:
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
        "provenance": _prov(ledger_path, "max latency_ms_p95 over non-privileged headline runs"),
    })

    # S4 · wave-1 cells measured on the frozen protocol
    values = []
    for phase, snap in zip(all_phases, snaps):
        extra = len(snap.wave1_any) - len(snap.wave1_frozen)
        note = f"{extra} more measured only off the frozen protocol" if extra else None
        values.append(_point(phase.id, float(len(snap.wave1_frozen)), of=wave1_total, note=note, evidence=ev("wave1_cells", phase)))
    kpis.append({
        "id": "wave1_cells", "label": "Wave-1 cells measured", "slot": "S4", "unit": "cells", "direction": "higher",
        "target": {"value": wave1_total, "kind": "scope", "label": f"of {wave1_total} wave-1 cells"},
        "baseline": None, "values": values, "status": _delta_status(values, labels),
        "note": "A cell counts once it has a run on its env's frozen eval protocol (curriculum.cells('wave1')).",
        "aggregate": None,
        "provenance": _prov(ledger_path, "distinct wave-1 cell_ids with a frozen-protocol run", curriculum=curriculum_path,
                            pointer="CELLS"),
    })

    # S5 · 3-seed rule on cells trained here
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

    # S5 · evidence trust: share of rows from a dirty tree
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
    approvals: dict[str, list[str]] = {}
    other_needs: dict[str, list[str]] = {}
    for cell in cur.cells:
        if cell.status != "needs":
            continue
        (approvals if "approval" in (cell.why or "") else other_needs).setdefault(
            cell.model if "approval" in (cell.why or "") else (cell.why or "unnamed blocker"), []).append(cell.id)
    needs = []
    for model_id, cell_ids in approvals.items():
        spec = cur.models.get(model_id)
        title = spec.title if spec else model_id
        detail = f" {spec.notes}" if spec and spec.notes else ""
        licence = f" Licence: {spec.licence}." if spec else ""
        needs.append({"id": f"grasping:download:{model_id}", "q": f"Approve the {title} download?{detail}{licence}",
                      "blocks": cell_ids, "default": None, "applies": None})
    track["needs_you"] = needs

    # ---- state + summary
    latest = snaps[-1] if snaps else snapshot([], cur)
    tier = frontier_tier(latest, cur)
    last_run = max(runs, key=lambda run: run.started_at) if runs else None
    toy_gated = [e for e in cur.gates if _family(e) == "toy"]
    if not runs:
        track["state"] = {"word": "No runs yet", "tone": "muted", "detail": f"runs.jsonl is empty · written {_local(ledger_mtime)}",
                          "since": None}
        track["summary"] = f"no ledger rows yet · {wave1_total} wave-1 cells planned"
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
                detail_bits.append(f"{len(tier_envs) - len(below)} of {len(tier_envs)} gates cleared"
                                   + (f" (open: {_join([_short_env(e) for e in below])})" if below else ""))
            next_tier = next((t for t in sorted({cur.envs[c.env].tier for c in cur.wave1()}) if t > tier), None)
            if next_tier is not None:
                next_cells = [c for c in cur.wave1() if cur.envs[c.env].tier == next_tier]
                next_done = sum(1 for c in next_cells if c.id in latest.wave1_frozen)
                detail_bits.append(f"next tier {next_tier} {cur.tier_name(next_tier)}: {next_done} of {len(next_cells)} cells")
            tier_runs = [run.started_at for run in runs if run.tier == tier and run.started_at]
            since = min(tier_runs) if tier_runs else None
        detail_bits.append(f"last run started {_local(last_run.started_at)}" if last_run else "")
        detail_bits.append(f"ledger written {_local(ledger_mtime)}")
        if bad_lines:
            detail_bits.append(f"{bad_lines} unreadable ledger lines skipped")
        track["state"] = {"word": word, "tone": "ok", "detail": " · ".join(bit for bit in detail_bits if bit), "since": since}
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
    track["rung"] = _rung(cur, tier, runs)

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
            "links": [], "note": " · ".join(f"{why}: {_join(cells, 4)}" for why, cells in other_needs.items()),
        })
    track["provenance"] = {
        "snapshot": None, "pointer": None, "source": ledger_path,
        "derived": (f"{len(runs)} ledger rows (written {ledger_mtime}) grouped into tier phases; curriculum.py "
                    f"(written {curriculum_mtime}) for tiers, wave-1 cells, gates and published AP; verdicts mirror "
                    "grasp_bench/gallery.py"),
    }
    return track
