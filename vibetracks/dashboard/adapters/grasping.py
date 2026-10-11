"""Adapter for the Grasping work track (vibe-id ``grasping``): the grasp bench's own ledger and curriculum, read live.

Inputs (the note's ``vibe-sources``; docs/dashboard/ADAPTERS.md, section ``grasping``; discovery key ``scout:grasping``):

- ``grasping_ledger``: ``<out>/ledger/runs.jsonl``, append-only, one CellRun per measured model@env run. Every live
  number on the row comes from here. ``<out>`` is the bench's out root (``grasping_out_dir``, its ``$GRASP_BENCH_OUT``),
  outside every checkout since 2026-10-10; the bench's code (``grasping_bench_dir``) is a separate root.
- ``grasping_curriculum``: ``grasp_bench/src/grasp_bench/curriculum.py``, the roadmap as code: TIERS, ENVS, MODELS,
  CELLS (wave1 / wave2 / needs / later / ref), GATES (Wilson-LB thresholds) and PUBLISHED_AP.
- ``grasping_out_dir``: the out root, checked only for the bench's own gallery files to link (evidence).
- ``grasping_scoreboard``: ``<out>/scoreboard/scoreboard.json`` (grasp-scoreboard/1, loop contract v5), the one
  projection every grasping view reads: the champion's four header KPI tiles, gates held, the canaries and the v5 hard
  gates come from it as written, never recomputed. When its ledger hash differs from the runs.jsonl this adapter read,
  every tile says "stale since <time>". Without the file the track keeps the gallery-verdict KPIs below as before.
- ``grasping_queue_status_json``: ``<out>/queue/status.json`` (grasp-runner-status/1), the runner service's own status;
  the runner KPI reads it (``grasping_queue_status``, its STATUS.md, is linked). It replaced the finished evidence
  rebuild's ``<out>/loop/status.json`` on 2026-10-11.
- ``grasping_roadmap_v4``: ``docs/grasping/roadmap_v4.json`` (grasp-roadmap/1) on the loop's branch, or bam_ws main once
  merged: the four milestones, the model and env queues and the loop's decisions, as ``track.milestones``.
- ``grasping_record``: ``<out>/record/report_record_2026-10-06.json``, the results recovered from the Oct 4-6 report
  after the ledger was deleted with its worktree (Oct 6-10). Read-only. Its values are the first iteration, labelled
  "recorded Oct 6, not yet re-proved": they carry no bench verdict, so no gate passes on them and the north star stays
  unmeasured until the rebuilt ledger is judged.

The rung (``track.rung``) is the frontier tier, the lowest tier whose wave-1 cells are not all measured on the frozen
protocol or whose gates are not all beaten, never the tier of the newest run: the loop measures ahead (tier 5 cells
ran while tier 2's gates were still open), so "latest" and "current" are different rungs here.

Verdicts are the bench's own: which run heads each cell, which runs are on the frozen protocol, which are
privileged, which envs are beaten or provisional. grasp_bench_bridge.verdict() runs ``grasp_bench.gallery`` in the
bench's venv over exactly the ledger rows this adapter read, named by the sha256 of their raw lines (``judge``), and
caches the answer. WHY no copy of those rules here: the copy this module used to carry drifted the night the bench
tightened "frozen" (provenance_gap, attestations.jsonl) and read 6 of 10 gated envs beaten against the gallery's 2.
When the bench cannot answer, the verdict KPIs are null with the reason ("bench verdict unavailable: ..."), never a
guess; the same when the ledger kept changing under two reads ("ledger changed during read"), so a number is never
shown beside rows of another ledger version. The bridge's inputs (``grasping_bench_python``, ``grasping_attestations``,
the bench's ``gallery.py`` / ``ledger.py`` / ``runner.py`` / ``contracts.py``, the whole ``src/grasp_bench`` and the
``grasping_verdict_cache`` folder) are declared sources too, so the build reruns this adapter when any of them changes.

Iteration: a **tier phase**, the rows of one curriculum tier under one training seed, in the order the ledger first saw
them (T0, T1, T2, then "T1 · seed 1" when the 3-seed runs land). Each KPI value is the cumulative ledger state once
that phase's rows are in. WHY tiers and not ledger rows: the loop runs a tier at a time (``== tier N`` in its run
scripts), 60 per-row columns would be unreadable, and a tier is the rung Zach asks about ("what is the current rung").
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from vibetracks.benches import grasp_bench_bridge
from .base import local_day, local_time, not_reporting, rung, skeleton

#: Every sources.py key this adapter opens, and what it is to the loop (base.py READ_ROLES). The bench's code, venv and
#: attestations are ``input``: a changed gallery.py changes the verdict but does not mean the loop measured anything.
READS = {"grasping_ledger": "heartbeat", "grasping_curriculum": "heartbeat", "grasping_out_dir": "evidence",
         "grasping_attestations": "input", "grasping_gallery_py": "input", "grasping_ledger_py": "input",
         "grasping_runner_py": "input", "grasping_contracts_py": "input", "grasping_bench_python": "input",
         "grasping_verdict_cache": "input", "grasping_bench_src": "input", "grasping_record": "input",
         "grasping_roadmap_v4": "input", "grasping_scoreboard": "heartbeat", "grasping_queue_status_json": "heartbeat",
         "grasping_queue_status": "heartbeat"}
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
    #: sha256 hex of this row's raw bytes in runs.jsonl without its one terminator (the bridge's ``line_sha256``).
    digest: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        return self.row.get(key, default)

    @property
    def train_seed(self) -> int | None:
        """The training seed this run fitted with, when it trained here (train_summary.seed); else None."""
        seed = (self.row.get("train_summary") or {}).get("seed")
        return seed if isinstance(seed, int) else None


def read_ledger(path: str | os.PathLike[str]) -> tuple[list[Run], int, bytes]:
    """(runs in append order, unreadable line count, the exact bytes they were parsed from), from ONE read.

    WHY bytes and per-line digests: the bench judges rows named by ``line_sha256`` (grasp_bench_bridge.verdict), so
    each Run carries the digest of its own raw line. ``bytes.splitlines`` splits on ``\\n``, ``\\r\\n`` and a lone
    ``\\r`` exactly as a text-mode read does and drops that one terminator, which is the bridge's rule; a UTF-8
    character never contains those bytes, so decoding line by line equals decoding the file.
    """

    data = Path(path).read_bytes()
    runs: list[Run] = []
    bad = 0
    for raw in data.splitlines():
        line = raw.decode("utf-8", errors="replace")
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            runs.append(Run(index=len(runs), row=row, run_id=str(row["run_id"]), cell_id=str(row["cell_id"]),
                            model=str(row["model"]), env=str(row["env"]), tier=int(row["tier"]),
                            started_at=str(row.get("started_at") or ""), protocol=dict(row.get("protocol") or {}),
                            digest=hashlib.sha256(raw).hexdigest()))
        except (ValueError, KeyError, TypeError):
            bad += 1
    return runs, bad, data


def _family(env_id: str) -> str:
    return env_id.split("/", 1)[0]


def _value(run: Run) -> float | None:
    value = run.get("value")
    return float(value) if isinstance(value, (int, float)) else None


# --------------------------------------------------------------------------------------------------------------------
# The bench's own verdict (grasp_bench_bridge), looked up by this adapter's runs
# --------------------------------------------------------------------------------------------------------------------


class Verdict:
    """What ``grasp_bench.gallery`` said about each run and each snapshot; this adapter never decides it itself.

    Every lookup goes through a row's digest (``Run.digest`` = the bridge's ``line_sha256``), never its ledger
    ``run_id``: a run id survives a row being enriched or replaced in place, the digest does not, so a judgement is
    only ever attached to the very bytes the dashboard parsed and displays.
    """

    def __init__(self, doc: dict[str, Any], runs: list[Run]) -> None:
        self.doc = doc
        self.by_digest: dict[str, Run] = {}
        for run in runs:
            self.by_digest.setdefault(run.digest, run)
        self._digest_of: dict[str, str] = {}
        self._judged: dict[str, dict[str, Any]] = {}
        for bench_id, judged in (doc.get("runs") or {}).items():
            if isinstance(judged, dict) and isinstance(judged.get("line_sha256"), str):
                self._digest_of[str(bench_id)] = judged["line_sha256"]
                self._judged.setdefault(judged["line_sha256"], judged)

    @classmethod
    def problem(cls, doc: dict[str, Any], runs: list[Run], subsets: dict[str, list[str]],
                cur: Curriculum) -> tuple[str | None, bool]:
        """``(why doc cannot be the verdict over runs, whether a re-read could fix it)``; ``(None, False)`` when usable.

        The second half is True when the bench's snapshot and the dashboard's read hold different bytes for a row the
        dashboard uses (enriched, replaced or gone in between): the caller re-reads once.
        """

        snapshots = doc.get("snapshots")
        if not isinstance(snapshots, dict):
            return "the bench returned no per-phase verdicts", False
        verdict = cls(doc, runs)
        unjudged = [run.run_id for run in runs if run.digest not in verdict._judged]
        if unjudged:
            return f"the bench did not judge {len(unjudged)} ledger rows the dashboard read (first {unjudged[0]})", True
        for snapshot_id in subsets:
            data = snapshots.get(snapshot_id)
            if not isinstance(data, dict):
                return f"the bench returned no snapshot {snapshot_id}", False
            missing = data.get("missing") or []
            if missing:
                first = next((run.run_id for run in runs if run.digest in set(missing)), missing[0])
                return (f"{len(missing)} ledger rows the dashboard read are not in the bench's snapshot "
                        f"(first {first})"), True
            referenced = [*(data.get("headline") or {}).values(),
                          *((entry or {}).get("best_run") for entry in (data.get("envs") or {}).values())]
            for bench_id in referenced:
                if bench_id is not None and verdict._run(bench_id) is None:
                    return f"the bench's verdict for {snapshot_id} names row {bench_id}, which the dashboard did not read", True
        if sorted(doc.get("envs") or {}) != sorted(cur.gates):
            return "the bench's curriculum.GATES differ from the curriculum.py the dashboard read", False
        return None, False

    def judged(self, run: Run) -> dict[str, Any]:
        return self._judged.get(run.digest) or {}

    def frozen(self, run: Run) -> bool:
        return self.judged(run).get("frozen") is True

    def privileged(self, run: Run) -> bool:
        return self.judged(run).get("privileged") is True

    def clears_gate(self, run: Run) -> bool:
        return self.judged(run).get("clears_gate") is True

    def gap(self, run: Run) -> str:
        """The bench's provenance_gap: why the row cannot vouch for an unchanged env and model ("" when it can)."""
        return str(self.judged(run).get("gap") or "")

    def _run(self, bench_id: Any) -> Run | None:
        digest = self._digest_of.get(str(bench_id)) if bench_id is not None else None
        return self.by_digest.get(digest) if digest is not None else None

    def heads(self, snapshot_id: str) -> dict[str, Run]:
        data = self.doc["snapshots"][snapshot_id]
        heads = {cell_id: self._run(bench_id) for cell_id, bench_id in (data.get("headline") or {}).items()}
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


#: The tiers whose envs execute a grasp (top-1 success of the grasp the env carries out), as Zach named them on Oct 10:
#: toy, MuJoCo, sim camera, crab claw. WHY not every top1_success tier: kinsim (6) is the kinsim loop's own KPI, and
#: reality (8) is S1's real half, which this bench has never measured.
EXECUTED_TIERS = {1: ("toy", "Toy"), 2: ("mujoco", "MuJoCo"), 5: ("simcam", "Sim camera"), 7: ("claw", "Crab claw")}


def tier_env(cur: Curriculum, tier: int) -> str | None:
    """The tier's hardest executed env: its last top1_success env in curriculum order (mujoco/stage5 for tier 2)."""

    envs = [env_id for env_id, spec in cur.envs.items() if spec.tier == tier and spec.metric == "top1_success"]
    return envs[-1] if envs else None


def dataset_envs(cur: Curriculum) -> list[str]:
    """Per dataset tier, its first AP env in curriculum order with published numbers (GraspNet-1B seen RealSense,
    GraspClutter6D test)."""

    out: list[str] = []
    for env_id, spec in cur.envs.items():
        if spec.metric == "ap" and env_id in cur.published_ap and all(cur.envs[e].tier != spec.tier for e in out):
            out.append(env_id)
    return out


def _executed_key(run: Run) -> tuple[float, float] | None:
    value = _value(run)
    return None if value is None else (value, run.get("ci_lo") if isinstance(run.get("ci_lo"), (int, float)) else -1.0)


def _ap(run: Run) -> float | None:
    return float(run.get("ap")) if isinstance(run.get("ap"), (int, float)) else _value(run)


def _p1(run: Run) -> float | None:
    return float(run.get("precision_at_1")) if isinstance(run.get("precision_at_1"), (int, float)) else None


def _top(heads: dict[str, Run], verdict: Verdict, env_id: str, key: Callable[[Run], Any]) -> Run | None:
    """The best non-privileged headline run on ``env_id`` by ``key`` (a run whose key is None is no candidate)."""

    pool = [run for run in heads.values() if run.env == env_id and not verdict.privileged(run) and key(run) is not None]
    return max(pool, key=key) if pool else None


def _oracle(heads: dict[str, Run], verdict: Verdict, env_id: str) -> Run | None:
    pool = [run for run in heads.values() if run.env == env_id and _value(run) is not None and verdict.privileged(run)]
    return max(pool, key=lambda run: _value(run)) if pool else None


# --------------------------------------------------------------------------------------------------------------------
# The recovered record (report_record_2026-10-06.json): values as the Oct 4-6 report rendered them, never re-judged
# --------------------------------------------------------------------------------------------------------------------


@dataclass
class Record:
    path: str
    runs: list[dict[str, Any]]       # every recovered run, in the report's order
    heads: list[dict[str, Any]]      # the runs the report showed as each cell's headline
    day: str | None                  # local YYYY-MM-DD of its newest run
    label: str                       # "Oct 6 record"
    words: str                       # "recorded Oct 6, not yet re-proved"

    def cells(self) -> set[str]:
        return {run["cell_id"] for run in self.heads}


def _record_time(run: dict[str, Any]) -> datetime | None:
    # WHY UTC: "started" is the report's rendering of the ledger's started_at, which the run_id stamps with Z
    # (20261006T194133Z_... -> "2026-10-06 19:41").
    try:
        return datetime.strptime(str(run.get("started") or ""), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _record_iso(run: dict[str, Any]) -> str | None:
    moment = _record_time(run)
    return moment.isoformat() if moment else None


def load_record(path: str | os.PathLike[str]) -> tuple[Record | None, str | None]:
    """``(the record, None)``, ``(None, None)`` when there is no file, or ``(None, why it cannot be read)``."""

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as error:
        return None, f"record unreadable · {path}: {error}"
    runs = data.get("runs") if isinstance(data, dict) else None
    if not isinstance(runs, list) or not runs or not all(
            isinstance(run, dict) and all(isinstance(run.get(key), str) for key in ("run_id", "cell_id", "model", "env"))
            for run in runs):
        return None, f"record has no readable runs · {path}"
    newest = max((moment for moment in map(_record_time, runs) if moment), default=None)
    when = f"{newest.astimezone():%b} {newest.astimezone().day}" if newest else "earlier"
    return Record(path=str(path), runs=runs, heads=[run for run in runs if run.get("headline") is True],
                  day=local_day(newest), label=f"{when} record", words=f"recorded {when}, not yet re-proved"), None


def _rec_num(run: dict[str, Any], key: str) -> float | None:
    value = run.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _rec_privileged(run: dict[str, Any]) -> bool:
    return "privileged" in (run.get("flags") or [])


def _rec_top(record: Record, env_id: str, key: Callable[[dict[str, Any]], Any]) -> dict[str, Any] | None:
    """The best non-privileged headline run of the record on ``env_id`` by ``key`` (privileged as the report flagged)."""

    pool = [run for run in record.heads if run["env"] == env_id and not _rec_privileged(run) and key(run) is not None]
    return max(pool, key=key) if pool else None


def _rec_executed_key(run: dict[str, Any]) -> tuple[float, float] | None:
    value = _rec_num(run, "value")
    return None if value is None else (value, _rec_num(run, "ci_lo") if _rec_num(run, "ci_lo") is not None else -1.0)


_LATENCY_TEXT = re.compile(r"^\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)\s*$")


def _rec_p95_ms(run: dict[str, Any]) -> float | None:
    """The record's ``latency_p95_text`` ("4.49 ms", "12380 ms") in ms; None for any other wording."""

    match = _LATENCY_TEXT.match(str(run.get("latency_p95_text") or ""))
    if not match:
        return None
    return float(match.group("number")) * (1000.0 if match.group("unit") == "s" else 1.0)


def _rec_item_id(run: dict[str, Any]) -> str:
    return f"record:{run['run_id']}"


def _rec_ci(run: dict[str, Any], scale: float = 100.0) -> str:
    lo, hi = _rec_num(run, "ci_lo"), _rec_num(run, "ci_hi")
    return f" [{round(lo * scale, 2):g}, {round(hi * scale, 2):g}]" if lo is not None and hi is not None else ""


def bench_lane(bench: Path) -> str | None:
    """The phrase "bench code lives on an agent lane (worktree X), not on bam_ws main" when the code sits in one.

    WHY said on the page: the Oct 6-10 evidence loss was a swept worktree; the code half of this track is in the same
    place until grasp_bench is merged into bam_ws main.
    """

    parts = bench.parts
    for index, part in enumerate(parts[:-2]):
        if part == ".claude" and parts[index + 1] == "worktrees":
            return f"bench code lives on an agent lane (worktree {parts[index + 2]}), not on bam_ws main"
    return None


# --------------------------------------------------------------------------------------------------------------------
# The four-milestone roadmap (roadmap_v4.json), the scoreboard (grasp-scoreboard/1) and the runner (grasp-runner-status/1)
# --------------------------------------------------------------------------------------------------------------------

ROADMAP_SCHEMA = "grasp-roadmap/1"
SCOREBOARD_SCHEMA = "grasp-scoreboard/1"
RUNNER_STATUS_SCHEMA = "grasp-runner-status/1"
#: WHY three: work order v4 section 7, "S7: at most three surfaced at once"; the queues show their next three too.
SHOWN = 3
#: Queue statuses that are not "next" (vocab.queue_status): sequenced after something else, or not runnable yet.
NOT_NEXT = ("later", "watch")
#: The header tiles, in the contract's order (loop_contract_v5.json kpis), and the slot each sits in. WHY picks per hour
#: is the north star (KPI note 4a): it is the time to clear a bin; success and computation time are its two inputs and
#: stay beside it, and the bench score with gates held is the frontier tile.
HEADER_KPIS = ("picks_per_hour", "holdout_success", "grasp_time_p95_ms", "bench_score")
HEADER_SLOTS = {"picks_per_hour": "S1", "holdout_success": "S1", "grasp_time_p95_ms": "S3", "bench_score": "S2"}
#: The runner's heartbeat age past which the loop's preflight restarts it (loop contract v5, tick step 1).
RUNNER_STALE_S = 600


def load_scoreboard(path: str | os.PathLike[str]) -> tuple[dict[str, Any] | None, str | None]:
    """``(grasp-scoreboard/1, None)``, ``(None, None)`` when the runner has not written it, or ``(None, why unusable)``."""

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as error:
        return None, f"scoreboard.json unreadable · {path}: {error}"
    if not isinstance(data, dict) or data.get("schema") != SCOREBOARD_SCHEMA or not isinstance(data.get("header"), dict) \
            or not isinstance(data["header"].get("kpis"), list) or not isinstance(data.get("ledger"), dict):
        return None, f"scoreboard.json is not {SCOREBOARD_SCHEMA} with a header and a ledger · {path}"
    return data, None


def scoreboard_staleness(doc: dict[str, Any], live_sha: str | None, runs: list[Run], ledger_mtime: str | None) -> dict[str, Any]:
    """Loop contract v5 views_rule: a view says "stale since <time>" when the scoreboard's ledger hash differs from the
    live runs.jsonl. ``since`` is the start of the first row the scoreboard did not read (the ledger is append-only, so
    those are the rows past ``ledger.rows``), else the ledger's mtime."""

    ledger = doc.get("ledger") or {}
    if not ledger.get("sha256") or not live_sha:
        return {"stale": None, "since": None, "new_rows": None}
    if ledger["sha256"] == live_sha:
        return {"stale": False, "since": None, "new_rows": 0}
    rows = ledger.get("rows")
    new = runs[rows:] if isinstance(rows, int) and 0 <= rows <= len(runs) else []
    starts = sorted(run.started_at for run in new if run.started_at)
    return {"stale": True, "since": starts[0] if starts else ledger_mtime, "new_rows": len(new) if new else None}


def load_runner_status(path: str | os.PathLike[str]) -> tuple[dict[str, Any] | None, str | None]:
    """``(grasp-runner-status/1, None)``, ``(None, None)`` when the runner has not started, or ``(None, why unusable)``."""

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as error:
        return None, f"queue/status.json unreadable · {path}: {error}"
    if not isinstance(data, dict) or data.get("schema") != RUNNER_STATUS_SCHEMA:
        return None, f"queue/status.json is not {RUNNER_STATUS_SCHEMA} · {path}"
    return data, None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else (len(value) if isinstance(value, list) else None)


def runner_reading(status: dict[str, Any], now: float | None = None) -> tuple[str, str, str]:
    """(status word, tone, note) for the runner KPI, in the runner's own words: state, what runs, queue, last 24 h,
    heartbeat. WHY warn on a heartbeat older than 10 min or a failure in 24 h: the loop's preflight restarts a silent
    runner and a failing job needs a look; anything else is calm."""

    state = str(status.get("state") or "unknown")
    current = [c for c in status.get("current") or [] if isinstance(c, dict)]
    running = ", ".join(str(c.get("cell") or "?") + (f" s{c['training_seed']}" if c.get("training_seed") is not None else "")
                        for c in current) or "nothing"
    queued, done, failed = _count(status.get("queued")), _count(status.get("done_24h")), _count(status.get("failed_24h"))
    beat = _parse_time(status["heartbeat_at"]) if isinstance(status.get("heartbeat_at"), str) else None
    age = ((now if now is not None else time.time()) - beat.timestamp()) if beat else None
    canary = status.get("last_canary") if isinstance(status.get("last_canary"), dict) else None
    bits = [state, f"running {running}", f"{queued if queued is not None else '?'} queued",
            f"{done if done is not None else '?'} done · {failed if failed is not None else '?'} failed in 24 h",
            f"heartbeat {_local(status['heartbeat_at'])}" if beat else "no heartbeat",
            (f"canary {'green' if canary.get('green') else 'red'} {_local(str(canary.get('at') or '') or None)}"
             if canary else ""),
            (f"stopped: {status['stop_reason']}" if status.get("stop_reason") else "")]
    word = " · ".join(bit for bit in bits if bit)
    tone = "warn" if (failed or (age is not None and age > RUNNER_STALE_S and state != "stopping")
                      or (canary is not None and canary.get("green") is False)) else "ok" if state == "running" else "muted"
    return word, tone, word


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pct_ci(ci: Any, unit: str) -> str:
    if not (isinstance(ci, list) and len(ci) == 2 and all(_num(x) for x in ci)):
        return ""
    scale = 100.0 if unit == "%" else 1.0
    return f"95% interval [{ci[0] * scale:.1f}, {ci[1] * scale:.1f}]"


def scoreboard_kpis(board: dict[str, Any], stale: dict[str, Any] | None, iterations: list[dict[str, Any]], path: str,
                    by_iteration: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The champion's four header tiles, gates held, the canaries and the v5 hard gates, as the scoreboard wrote them.

    Loop contract v5 (kpi_header_rule): each tile names its status (estimate / stand-in / measured / sealed) and, when
    another eligible model is better on it, names that model in one line (``best_other``, in the status word). Nothing
    here is computed: a rate tile is printed in percent and that is all. The scoreboard projects the whole current
    ledger, so each value sits on the latest column; earlier columns say why they are empty. A ledger the scoreboard
    has not read yet turns every tile's status into "stale since <time>" (views_rule).
    """

    if not iterations:
        return []
    last_id = iterations[-1]["id"]
    latest_items = {item["id"] for item in by_iteration.get(last_id, [])}
    generated = board.get("generated_at")
    ledger = board.get("ledger") or {}
    champion = (board.get("header") or {}).get("champion") or {}
    stale_word = (f"stale since {_local(stale['since'])}" + (f" ({stale['new_rows']} new runs)" if stale.get("new_rows") else "")
                  if stale and stale.get("stale") else "")
    early = "the scoreboard projects the whole current ledger: no reading for this phase"
    prov = lambda derived: {"snapshot": generated, "pointer": None, "source": path,  # noqa: E731
                            "derived": f"{derived} of grasp-scoreboard/1 generated {generated} over runs.jsonl "
                                       f"({ledger.get('rows')} rows, sha {str(ledger.get('sha256') or '')[:12]})"}

    def column(latest: dict[str, Any]) -> list[dict[str, Any]]:
        return [_point(item["id"], None, note=early) for item in iterations[:-1]] + [latest]

    def staled(status: dict[str, str]) -> dict[str, str]:
        return {"word": f"{stale_word} · {status['word']}", "tone": "warn"} if stale_word else status

    out: list[dict[str, Any]] = []
    tiles = {tile.get("id"): tile for tile in board["header"]["kpis"] if isinstance(tile, dict)}
    gates_held = board.get("gates_held") if isinstance(board.get("gates_held"), dict) else None
    for kpi_id in HEADER_KPIS:
        tile = tiles.get(kpi_id)
        if tile is None:
            continue
        unit = str(tile.get("unit") or "")
        raw = tile.get("value")
        # WHY x100 and nothing else: the scoreboard stores rates as 0-1 and the page prints percent.
        value = (round(raw * 100.0, 6) if unit == "%" else raw) if _num(raw) else None
        status = str(tile.get("status") or "status unknown")
        better = f"better elsewhere: {tile['best_other']}" if tile.get("best_other") else "no eligible model is better"
        ci = _pct_ci(tile.get("ci95"), unit)
        bits = [f"{tile.get('model')} (champion, {champion.get('how') or 'how unknown'})", str(tile.get("basis") or ""),
                " ".join(str(x) for x in (tile.get("env"), tile.get("protocol")) if x), ci]
        note = " · ".join(bit for bit in bits if bit)
        target = None
        if kpi_id == "grasp_time_p95_ms":
            goal = tile.get("target") if _num(tile.get("target")) else 1000
            target = {"value": goal, "kind": "limit", "label": f"target ≤ {goal:,} ms"}
        elif kpi_id == "bench_score" and gates_held:
            target = {"kind": "reference", "label": f"gates held {gates_held.get('k')} of {gates_held.get('n')} beside it, never averaged in"}
        evidence = [run_id for run_id in tile.get("run_ids") or [] if run_id in latest_items]
        out.append({
            "id": kpi_id, "label": str(tile.get("title") or kpi_id), "slot": HEADER_SLOTS[kpi_id],
            "unit": {"%": "%", "ms": "ms", "picks/h": "picks/h", "0-100": "points"}.get(unit, unit), "level": "header",
            "direction": "lower" if kpi_id == "grasp_time_p95_ms" else "higher", "target": target, "baseline": None,
            "values": column(_point(last_id, value, note=note or None, evidence=evidence) if value is not None else
                             _point(last_id, None, note=f"the scoreboard has no value · {note}", evidence=evidence)),
            "status": staled({"word": f"{status} · {better}",
                              "tone": "ok" if status in ("measured", "sealed", "real") else "muted"}),
            "note": f"{note}. Status '{status}': " + {
                "estimate": "computed on a stand-in environment by the contract's constant-time identity; no interval.",
                "stand-in": "a labelled, non-sealed number shown until the sealed hold-out version exists.",
                "measured": "measured on the KPI's own environment, public seeds.",
                "sealed": "measured by the runner on the sealed hold-out."}.get(status, "as the scoreboard states it."),
            "aggregate": None, "provenance": prov(f"header.kpis[{kpi_id}]"),
        })

    gates = [gate for gate in board.get("gates") or [] if isinstance(gate, dict) and gate.get("kind", "gate") == "gate"]
    if gates_held:
        counts: dict[str, int] = {}
        for gate in gates:
            counts[str(gate.get("status"))] = counts.get(str(gate.get("status")), 0) + 1
        words = " · ".join(f"{n} {word.replace('_', ' ')}" for word, n in sorted(counts.items()))
        out.append({
            "id": "gates_held", "label": "Gates held", "slot": "S2", "unit": "gates", "direction": "higher",
            "level": "header", "target": {"value": gates_held.get("n"), "kind": "scope", "label": f"of {gates_held.get('n')} gates"},
            "baseline": None,
            "values": column(_point(last_id, float(gates_held["k"]) if _num(gates_held.get("k")) else None,
                                    of=gates_held.get("n"), note=words or "no gates in the scoreboard")),
            "status": staled({"word": f"{gates_held.get('k')} of {gates_held.get('n')} held · {words}", "tone": "ok"}),
            "note": ("A gate is beaten when some non-privileged model family has a clean run for every training seed whose "
                     "Wilson 95% lower bound clears the bar, on the gate protocol (MuJoCo at n = 1,000); held = beaten "
                     "and not since failed the guard. The scoreboard's own verdicts, each gate a hard gate below."),
            "aggregate": None, "provenance": prov("gates_held"),
        })
    canaries = [c for c in board.get("canaries") or [] if isinstance(c, dict)]
    if canaries:
        green = [str(c.get("env")) for c in canaries if c.get("status") == "green"]
        other = [f"{c.get('env')} {c.get('status')}" for c in canaries if c.get("status") != "green"]
        out.append({
            "id": "canaries", "label": "Pipeline canaries (not gates)", "slot": "S5", "unit": "canaries",
            "direction": "higher", "level": "header",
            "target": {"value": len(canaries), "kind": "scope", "label": f"of {len(canaries)} canaries green"},
            "baseline": None,
            "values": column(_point(last_id, float(len(green)), of=len(canaries),
                                    note=" · ".join(bit for bit in [f"green: {', '.join(green)}" if green else "",
                                                                   ", ".join(other)] if bit))),
            "status": staled({"word": " · ".join(bit for bit in [f"green: {', '.join(green)}" if green else "",
                                                                  ", ".join(other)] if bit),
                              "tone": "warn" if any(c.get("status") == "red" for c in canaries) else "ok"}),
            "note": ("Former gates that random-on-object already passes (toy/x, toy/xy): a check that the pipeline still "
                     "works, never counted in gates held."),
            "aggregate": None, "provenance": prov("canaries"),
        })
    for gate in gates:
        env_id, bar = str(gate.get("env")), gate.get("bar")
        protocol = gate.get("protocol") if isinstance(gate.get("protocol"), dict) else {"name": gate.get("protocol")}
        state = str(gate.get("status") or "unknown")
        v4 = gate.get("v4") if isinstance(gate.get("v4"), dict) else None
        v4_words = ""
        if v4:
            lb = f", worst-seed LB {v4['worst_seed_lb'] * 100:.2f} %" if _num(v4.get("worst_seed_lb")) else ""
            v4_words = (f"v4 {v4.get('protocol')}: " + (f"beaten by {v4.get('holder')}{lb}" if v4.get("beaten")
                                                           else f"not beaten{lb}"))
        lb = gate.get("worst_seed_lb")
        if state == "beaten":
            why = f"beaten · {gate.get('holder')}" + ("" if gate.get("held", True) else " · not held (failed the guard)")
            verdict = bool(gate.get("held", True))
        elif state == "not_beaten":
            why, verdict = f"not beaten · best {gate.get('best') or 'none'}", False
        elif state == "awaiting_protocol":
            why, verdict = f"awaiting {protocol.get('name')} runs" + (f" · {v4_words}" if v4_words else ""), None
        else:
            why, verdict = state.replace("_", " "), None
        note = " · ".join(bit for bit in [why, f"worst-seed Wilson LB {lb * 100:.2f} %" if _num(lb) else "",
                                         v4_words if state != "awaiting_protocol" else ""] if bit)
        latest = _point(last_id, _pct(lb) if _num(lb) else None, note=note)
        latest["verdict"] = {"pass": verdict, "why": why}
        gate_pct = round(bar * 100.0, 6) if _num(bar) else None
        out.append({
            "id": f"gate_{env_id.replace('/', '_')}", "label": env_id, "slot": "S2", "unit": "%", "direction": "higher",
            "level": "header",
            "target": {"value": gate_pct, "gate": gate_pct, "kind": "gate",
                       "label": f"worst-seed Wilson LB ≥ {gate_pct:g} % · {protocol.get('name')}"
                                + (f" (n {protocol['episodes']:,})" if _num(protocol.get("episodes")) else "")
                                + " · every training seed"},
            "baseline": None, "values": column(latest),
            "status": staled({"word": why, "tone": "ok" if verdict else "muted"}),
            "note": "The scoreboard's gate verdict (loop contract v5 gates); the v4 n = 200 verdict is shown beside it.",
            "aggregate": None, "provenance": prov(f"gates[{env_id}]"),
        })
    return out


def scoreboard_sentence(board: dict[str, Any], stale: dict[str, Any] | None) -> tuple[str, bool]:
    """(the header in one line, whether anything wants a look): champion, the four tiles with their status words,
    gates held, canaries, stale. Copied from the scoreboard; numbers are only formatted."""

    champ = ((board.get("header") or {}).get("champion") or {}).get("model")
    tiles = {t.get("id"): t for t in (board.get("header") or {}).get("kpis") or [] if isinstance(t, dict)}

    def tile(kpi_id: str, label: str) -> str:
        t = tiles.get(kpi_id)
        if not t or not _num(t.get("value")):
            return f"{label} not measured"
        value, unit = t["value"], t.get("unit")
        text = (f"{value * 100:.1f}%" if unit == "%" else f"{value:,.0f} ms" if unit == "ms" else
                f"{value:,.0f}" if unit == "picks/h" else f"{value:.1f}")
        ci = t.get("ci95")
        if isinstance(ci, list) and len(ci) == 2 and all(_num(x) for x in ci) and unit != "%":
            text += f" [{ci[0]:.1f}, {ci[1]:.1f}]"
        return f"{label} {text} ({t.get('status')})"

    held = board.get("gates_held") if isinstance(board.get("gates_held"), dict) else {}
    canaries = [c for c in board.get("canaries") or [] if isinstance(c, dict)]
    red = [str(c.get("env")) for c in canaries if c.get("status") == "red"]
    bits = [f"champion {champ}" if champ else "no champion yet", tile("picks_per_hour", "picks/h"),
            tile("holdout_success", "hold-out"), tile("grasp_time_p95_ms", "decision p95"), tile("bench_score", "bench"),
            f"gates held {held.get('k')} of {held.get('n')}" if held else "",
            (f"canaries red: {', '.join(red)}" if red else "canaries green") if canaries else "",
            f"scoreboard stale since {_local(stale['since'])}" if stale and stale.get("stale") else ""]
    return " · ".join(bit for bit in bits if bit), bool(red) or bool(stale and stale.get("stale"))


def load_roadmap(path: str | os.PathLike[str]) -> tuple[dict[str, Any] | None, str | None]:
    """``(grasp-roadmap/1, None)``, ``(None, None)`` when there is no file, or ``(None, why it is unusable)``."""

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as error:
        return None, f"roadmap_v4.json unreadable · {path}: {error}"
    if not isinstance(data, dict) or data.get("schema") != ROADMAP_SCHEMA or not isinstance(data.get("milestones"), list):
        return None, f"roadmap_v4.json is not {ROADMAP_SCHEMA} with milestones · {path}"
    return data, None


def _recorded(current: dict[str, Any]) -> bool:
    # WHY the value's own source and not the file's as_of.evidence: the real-world milestones' zeros come from the KPI
    # note and the rig loop, not the recovered record, and "not yet re-proved" would be false for them.
    return str(current.get("source") or "").startswith("record")


def milestones(roadmap: dict[str, Any], path: str) -> dict[str, Any]:
    """The track page's milestone ladder (``vibetracks-milestones/1``) from grasp-roadmap/1, read as written.

    Per milestone: its current rung (the first rung, in the file's order, whose status is not ``green`` or ``done``;
    status words are bam-roadmap/1's), today's value (``current.display``), its bar (the done rung's ``done_when``) and
    ``blocked_by``. A value whose source is the recovered record is labelled "recorded <as_of>, not yet re-proved";
    a published comparison is shown as comparable only when ``current.comparable_to_published`` is true. Unknown
    fields are ignored (section 6: "a consumer ignores unknown fields").
    """

    as_of = roadmap.get("as_of") if isinstance(roadmap.get("as_of"), dict) else {}
    items = []
    for milestone in sorted((m for m in roadmap["milestones"] if isinstance(m, dict)), key=lambda m: m.get("order") or 0):
        rungs = [rung for rung in milestone.get("rungs") or [] if isinstance(rung, dict)]
        open_rung = next((rung for rung in rungs if rung.get("status") not in ("green", "done")), None)
        done = next((rung for rung in rungs if rung.get("id") == milestone.get("done_rung")), None)
        current = milestone.get("current") if isinstance(milestone.get("current"), dict) else {}
        recorded = _recorded(current)
        items.append({
            "id": milestone.get("id"), "order": milestone.get("order"), "title": milestone.get("title"),
            "status": milestone.get("status"), "owner": milestone.get("owner"),
            "rung": ({"id": open_rung.get("id"), "title": open_rung.get("title"), "status": open_rung.get("status"),
                      "comparison": open_rung.get("comparison"), "gap": open_rung.get("gap"),
                      "today": (open_rung.get("current") or {}).get("display")} if open_rung else None),
            "rungs": [{"id": rung.get("id"), "title": rung.get("title"), "status": rung.get("status")} for rung in rungs],
            "today": {"display": current.get("display"), "value": current.get("value"), "metric": current.get("metric"),
                      "as_of": current.get("as_of"), "source": current.get("source"),
                      "comparable_to_published": current.get("comparable_to_published") is True,
                      "label": (f"recorded {current.get('as_of') or 'earlier'}, not yet re-proved" if recorded
                                else f"as of {current.get('as_of') or 'unknown'}")},
            "bar": ({"rung": done.get("id"), "title": done.get("title"), "metric": done.get("metric"),
                     "comparison": done.get("comparison"),
                     "done_when": [str(text) for text in done.get("done_when") or []]} if done else None),
            "blocked_by": [str(item) for item in milestone.get("blocked_by") or []],
        })

    def next_of(queue: Any) -> list[dict[str, Any]]:
        entries = sorted((q for q in queue or [] if isinstance(q, dict)), key=lambda q: q.get("order") or 0)
        return [{"id": q.get("id"), "title": q.get("title"), "status": q.get("status"),
                 "unlocks": q.get("unlocks") or []}
                for q in entries if q.get("status") and q.get("status") not in NOT_NEXT][:SHOWN]

    needs = [{"id": n.get("id"), "q": n.get("q"), "blocks": n.get("blocks") or [], "default": n.get("default"),
              "applies": n.get("applies")} for n in roadmap.get("needs_you") or [] if isinstance(n, dict)]
    return {
        "schema": "vibetracks-milestones/1", "source": path, "generated_at": roadmap.get("generated_at"),
        "as_of": {"evidence": as_of.get("evidence"), "note": as_of.get("note")},
        "items": items,
        # WHY truncated with a count: the page shows at most three decisions; the rest stay one click away in the file
        "needs_you": needs[:SHOWN], "needs_you_total": len(needs),
        "model_queue": next_of(roadmap.get("model_queue")), "env_queue": next_of(roadmap.get("env_queue")),
    }


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


#: Where each declared bridge input must sit inside the bench (``grasping_bench_python`` = <bench>/.venv/bin/python
#: names the bench) and inside its out root (``grasping_out_dir``). WHY checked: verdict() reads the bench's own files
#: by layout, and the build reruns this adapter only when a DECLARED source changes, so a declared path elsewhere would
#: be watched while the bench read another.
BENCH_LAYOUT = {
    "grasping_curriculum": "src/grasp_bench/curriculum.py", "grasping_gallery_py": "src/grasp_bench/gallery.py",
    "grasping_ledger_py": "src/grasp_bench/ledger.py", "grasping_runner_py": "src/grasp_bench/runner.py",
    "grasping_contracts_py": "src/grasp_bench/contracts.py", "grasping_bench_src": "src/grasp_bench",
}
OUT_LAYOUT = {"grasping_ledger": "ledger/runs.jsonl", "grasping_attestations": "ledger/attestations.jsonl"}
BRIDGE_KEYS = ("grasping_bench_python", *BENCH_LAYOUT, "grasping_out_dir", *OUT_LAYOUT, "grasping_verdict_cache")
LEDGER_CHANGED = "ledger changed during read"


def bench_dir(sources: dict[str, str]) -> tuple[Path | None, Path | None, str | None]:
    """``(the grasp_bench folder, its out root, None)`` from the declared sources, or ``(None, None, why the bridge
    cannot be asked)``."""

    missing = [key for key in BRIDGE_KEYS if not sources.get(key)]
    if missing:
        return None, None, f"vibe-sources lacks {', '.join(missing)}"
    bench = Path(sources["grasping_bench_python"]).parent.parent.parent
    out = Path(sources["grasping_out_dir"])
    for root, layout in ((bench, BENCH_LAYOUT), (out, OUT_LAYOUT)):
        for key, relative in layout.items():
            if os.path.realpath(sources[key]) != os.path.realpath(root / relative):
                return None, None, f"{key} {sources[key]} is not the bench's {root / relative}"
    return bench, out, None


#: grasp_bench_bridge.verdict's shape; tests pass a fake (no bench venv needed).
Bridge = Callable[..., dict[str, Any]]


@dataclass
class Judged:
    """One read of runs.jsonl and the bench's verdict over exactly those bytes (``verdict`` None: ``unavailable`` says why)."""

    runs: list[Run]
    bad_lines: int
    all_phases: list[Phase]
    cumulative: list[list[Run]]
    verdict: Verdict | None
    unavailable: str | None
    info: dict[str, Any] | None
    #: sha256 of the bytes this read parsed (the scoreboard's staleness compares its ledger hash to it).
    sha256: str | None = None


def judge(ledger_path: str, sources: dict[str, str], cur: Curriculum, bridge: Bridge | None) -> Judged:
    """Read the ledger once, ask the bench to judge exactly those rows, and re-read once if the ledger moved between.

    WHY one read and digests (Codex r3 finding 2, 2026-10-05): this adapter used to read runs.jsonl, then call
    bench_verdict(), which read it again, and checked the two against each other by run id only. A legacy sparse row
    enriched in place between the reads kept its id, so the page showed a measured "beaten" beside that run's row with
    no Top-1 and no Wilson LB. Now every phase subset is named by the rows' ``line_sha256`` digests, the bench judges
    one byte snapshot, and any row of this read that the snapshot does not hold byte for byte comes back ``missing``.
    Then the ledger is read again and judged again, once; if it moved a second time the north star is null with
    "ledger changed during read" rather than numbers from one version beside rows from another.
    """

    previous: bytes | None = None
    started = time.monotonic()
    for attempt in (1, 2):
        # WHY an absent ledger is an empty one: until the rebuild writes its first row the out root has no ledger/, and
        # the record is what the page shows; there is nothing for the bench to judge.
        runs, bad_lines, data = read_ledger(ledger_path) if Path(ledger_path).is_file() else ([], 0, b"")
        all_phases = phases(runs, cur)
        cumulative_runs: list[list[Run]] = []
        cumulative: list[Run] = []
        for phase in all_phases:
            cumulative = sorted(cumulative + phase.runs, key=lambda run: run.index)
            cumulative_runs.append(cumulative)
        digest = hashlib.sha256(data).hexdigest() if Path(ledger_path).is_file() else None
        if not runs:
            return Judged(runs, bad_lines, all_phases, cumulative_runs, None, None, None, digest)
        bench, out, unavailable = bench_dir(sources)
        info: dict[str, Any] = {}
        if bench is not None:
            subsets = {phase.id: [run.digest for run in held] for phase, held in zip(all_phases, cumulative_runs)}
            doc = (bridge or grasp_bench_bridge.verdict)(bench, out_dir=out, cache_dir=sources["grasping_verdict_cache"],
                                                         subsets=subsets, info=info)
            if doc.get("error"):
                unavailable = str(doc["error"])
            else:
                unavailable, moved = Verdict.problem(doc, runs, subsets, cur)
                if unavailable is None:
                    info.update(ok=True, reason=None, attempts=attempt, seconds=time.monotonic() - started)
                    return Judged(runs, bad_lines, all_phases, cumulative_runs, Verdict(doc, runs), None, info, digest)
                if moved and attempt == 1:
                    previous = data
                    continue
                if moved and previous != data:
                    unavailable = f"{LEDGER_CHANGED} ({unavailable})"
        info.update(ok=False, reason=unavailable, attempts=attempt, seconds=time.monotonic() - started)
        return Judged(runs, bad_lines, all_phases, cumulative_runs, None, unavailable, info, digest)
    raise AssertionError("unreachable")


def _unconfirmed(phase_id: str, evidence: list[str]) -> dict[str, Any]:
    return _point(phase_id, None, note=UNCONFIRMED, evidence=evidence)


UNCONFIRMED_STATUS = {"word": UNCONFIRMED, "tone": "muted"}


def build_track(work_track: Any, sources: dict[str, str], *, bridge: Bridge | None = None) -> dict[str, Any]:
    """The Grasping track. ``bridge`` is grasp_bench_bridge.verdict; tests pass a fake (no bench venv needed)."""

    ledger_path = sources.get("grasping_ledger")
    curriculum_path = sources.get("grasping_curriculum")
    if not ledger_path or not curriculum_path:
        missing = [key for key in ("grasping_ledger", "grasping_curriculum") if not sources.get(key)]
        return not_reporting(work_track, f"vibe-sources lacks {', '.join(missing)}")
    if not Path(curriculum_path).is_file():
        return not_reporting(work_track, f"curriculum.py missing · {curriculum_path}")
    record, record_problem = load_record(sources["grasping_record"]) if sources.get("grasping_record") else (None, None)
    if not Path(ledger_path).is_file() and record is None:
        return not_reporting(work_track, f"ledger missing · {ledger_path}" + (f" · {record_problem}" if record_problem else ""))

    cur = load_curriculum(curriculum_path)
    judged = judge(ledger_path, sources, cur, bridge)
    runs, bad_lines, all_phases, cumulative_runs = judged.runs, judged.bad_lines, judged.all_phases, judged.cumulative
    verdict, unavailable, bridge_info = judged.verdict, judged.unavailable, judged.info
    ledger_file, curriculum_file = Path(ledger_path), Path(curriculum_path)
    ledger_mtime, curriculum_mtime = _mtime_iso(ledger_file), _mtime_iso(curriculum_file)
    bench_root = curriculum_file.parent.parent.parent
    lane = bench_lane(bench_root)
    queue_md = Path(sources["grasping_queue_status"]) if sources.get("grasping_queue_status") else None
    queue_md_mtime = _mtime_iso(queue_md) if queue_md is not None and queue_md.is_file() else None
    runner, runner_problem = (load_runner_status(sources["grasping_queue_status_json"])
                              if sources.get("grasping_queue_status_json") else (None, None))
    board, board_problem = (load_scoreboard(sources["grasping_scoreboard"]) if sources.get("grasping_scoreboard")
                            else (None, None))
    stale = scoreboard_staleness(board, judged.sha256, judged.runs, ledger_mtime) if board is not None else None
    roadmap, roadmap_problem = (load_roadmap(sources["grasping_roadmap_v4"]) if sources.get("grasping_roadmap_v4")
                                else (None, None))

    track = skeleton(work_track, unit="wave")
    wave1_ids = {cell.id for cell in cur.wave1()}
    wave1_total = len(wave1_ids)
    gated_total = len(cur.gates)
    mujoco_gated = [env_id for env_id in cur.gates if _family(env_id) == "mujoco"]

    unavailable_note = f"{UNAVAILABLE}: {unavailable}" if unavailable else None

    # ---- iterations: the recovered record first (when there is one), then the rebuilt ledger's tier phases
    record_id = f"record-{record.day}" if record is not None and record.day else "record"
    iterations: list[dict[str, Any]] = []
    by_iteration: dict[str, list[dict[str, Any]]] = {}
    if record is not None:
        iterations.append({
            "id": record_id, "label": f"{record.label} · not re-proved", "date": record.day,
            "marker": (f"{len(record.runs)} runs, {len(record.cells())} headline cells recovered from the rendered report; "
                       "values as recorded, no bench verdict"),
            "provenance": _prov(record.path, "report_record: each run as the Oct 4-6 report rendered it "
                                             "(docs/grasping/extract_report_record.py); read-only, never re-judged"),
        })
        by_iteration[record_id] = [{
            "id": _rec_item_id(run), "iteration": record_id, "kind": "run", "title": run["cell_id"],
            "when": _record_iso(run),
            "metrics": {"value (as rendered)": run.get("value_text"), "n episodes": run.get("n"),
                        "latency p95": run.get("latency_p95_text"), "protocol": run.get("protocol"),
                        "git sha": run.get("git_sha")},
            "status": "recorded (not re-proved)", "media": [],
            "links": [{"label": "recovered record (json)", "kind": "path", "value": record.path}],
            "note": " · ".join([record.words] + ([f"flags: {', '.join(run['flags'])}"] if run.get("flags") else [])),
        } for run in record.heads]
    labels = ([f"{record.label} · not re-proved"] if record is not None else []) + [phase.label for phase in all_phases]

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

    # ---- evidence: one item per ledger run, in the phase it belongs to
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
                metrics["AP"] = _ap(run)
                metrics["label-judged top-1 (%)"] = _pct(_p1(run))
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

    # ---- KPI helpers: one value per iteration, the record's column first
    def column(record_point: Callable[[Record], dict[str, Any]],
               phase_point: Callable[[Phase, Snapshot], dict[str, Any]]) -> list[dict[str, Any]]:
        return ([record_point(record)] if record is not None else []) + [
            phase_point(phase, snap) for phase, snap in zip(all_phases, snaps)]

    def on_env(phase: Phase, env_id: str | None) -> list[str]:
        return [run.run_id for run in phase.runs if run.env == env_id]

    def status_of(values: list[dict[str, Any]], **kwargs: Any) -> dict[str, str]:
        """The calm reading of the last change; a value last seen only in the record says so, never "first reading"."""
        measured = [point for point in values if point["measured"]]
        if record is not None and measured and measured[-1]["iteration"] == record_id:
            return {"word": record.words, "tone": "muted"}
        return _delta_status(values, labels, **kwargs)

    def verdict_status(values: list[dict[str, Any]], **kwargs: Any) -> dict[str, str]:
        # WHY "or not runs": with no ledger row there is nothing for the bench to judge, which is not "unavailable".
        return status_of(values, **kwargs) if verdict is not None or not runs else dict(UNCONFIRMED_STATUS)

    bridge_prov = ("grasp_bench.gallery run in the bench's own venv over these ledger rows (grasp_bench_bridge)"
                   if verdict is not None else f"{UNAVAILABLE}: {unavailable}" if unavailable else "no ledger rows")
    record_prov = f" · first column: {record.path} ({record.words})" if record is not None else ""
    kpis: list[dict[str, Any]] = []

    # S2 · envs beaten: the bench's own count, never recomputed here; the record carries no verdict to count
    values = column(
        lambda rec: _point(record_id, None, of=gated_total,
                           note=f"{rec.words}: the record carries values, not the bench's verdicts"),
        lambda phase, snap: (
            _point(phase.id, None, of=gated_total, note=unavailable_note,
                   evidence=[run.run_id for run in phase.runs if run.env in cur.gates]) if not snap.judged else
            _point(phase.id, float(len(snap.beaten)), of=gated_total,
                   note=(("beaten: " + _join([_short_env(e) for e in snap.beaten])) if snap.beaten else "none beaten yet")
                   + (" · provisional: " + _join([_short_env(e) for e in snap.provisional]) if snap.provisional else ""),
                   evidence=[run.run_id for run in phase.runs if run.env in cur.gates])))
    if verdict is not None:
        status = _delta_status(values, labels)
    elif unavailable:
        status = {"word": UNAVAILABLE, "tone": "warn"}
    else:
        status = {"word": "not yet re-proved" if record is not None else "not measured yet", "tone": "muted"}
    kpis.append({
        "id": "envs_beaten", "label": "Gated envs beaten", "slot": "S2", "unit": "envs", "direction": "higher",
        "target": {"value": gated_total, "kind": "scope", "label": f"of {gated_total} gated envs"},
        "baseline": None, "values": values, "status": status,
        "note": ("The bench's own verdict (grasp_bench.gallery.env_verdict): beaten = a non-privileged headline run on "
                 "the frozen eval protocol, with provenance that can vouch for itself, whose Wilson 95% lower bound is at "
                 "or above the env's gate (curriculum.GATES), on every frozen training seed of a learned model. "
                 "Provisional = clears the gate only on a smoke protocol or on some seeds. Each env is a hard gate below."),
        "aggregate": None,
        "provenance": _prov(ledger_path, f"gallery.env_verdict per gated env · {bridge_prov}",
                            curriculum=curriculum_path, pointer="GATES"),
    })

    # S1 / S2 · best executed grasp success per tier, on the tier's hardest env (the crab claw is S1's sim half)
    tier_best: dict[int, tuple[str, list[dict[str, Any]], dict[str, Any], list[Run | dict[str, Any] | None]]] = {}
    for tier, (short, word) in EXECUTED_TIERS.items():
        env_id = tier_env(cur, tier)
        if env_id is None:
            continue
        chosen: list[Run | dict[str, Any] | None] = []

        def rec_point(rec: Record, env_id: str = env_id, chosen: list = chosen) -> dict[str, Any]:
            best = _rec_top(rec, env_id, _rec_executed_key)
            chosen.append(best)
            if best is None:
                return _point(record_id, None, note=f"{rec.words}: no non-privileged headline run on {env_id}")
            return _point(record_id, _pct(_rec_num(best, "value")), n=best.get("n"),
                          note=f"{rec.words} · {best['model']} {best.get('value_text')}{_rec_ci(best)} on {best.get('protocol')}",
                          evidence=[_rec_item_id(best)])

        def phase_point(phase: Phase, snap: Snapshot, env_id: str = env_id, chosen: list = chosen) -> dict[str, Any]:
            if not snap.judged:
                chosen.append(None)
                return _unconfirmed(phase.id, on_env(phase, env_id))
            best = _top(snap.heads, verdict, env_id, _executed_key)
            chosen.append(best)
            if best is None:
                return _point(phase.id, None, note=f"{env_id} not in the ledger yet", evidence=on_env(phase, env_id))
            return _point(phase.id, _pct(_value(best)), n=best.get("n"),
                          note=(f"{best.model} {_pct(_value(best))}% [{_pct(best.get('ci_lo'))}, {_pct(best.get('ci_hi'))}] "
                                f"on {best.protocol.get('name')}" + ("" if verdict.frozen(best) else " (not the frozen protocol)")),
                          evidence=on_env(phase, env_id))

        values = column(rec_point, phase_point)
        gate = cur.gates.get(env_id)
        kpi = {
            "id": f"tier_best_{short}", "label": f"{word} · executed top-1 · {_short_env(env_id)}",
            "slot": "S1" if tier == 7 else "S2", "unit": "%", "direction": "higher",
            "target": ({"value": round(gate * 100, 2), "kind": "reference",
                        "label": f"gate LB ≥ {gate * 100:g} % · hard gate below"} if gate is not None else None),
            "baseline": None, "values": values, "status": verdict_status(values, unit=" pts", digits=1),
            "note": (f"Top-1 success of an executed grasp, best non-privileged headline run (the bench's own headline per "
                     f"cell) on tier {tier}'s hardest env, {env_id}: {cur.envs[env_id].title}."
                     + (" S1's simulated half (the crab claw); real verified picks are not measured by this bench."
                        if tier == 7 else "")),
            "aggregate": None,
            "provenance": _prov(ledger_path, f"max non-privileged headline value on {env_id} over gallery.headline_runs · "
                                f"{bridge_prov}{record_prov}", curriculum=curriculum_path, pointer="ENVS"),
        }
        kpis.append(kpi)
        tier_best[tier] = (env_id, values, kpi, chosen)

    # S2 · the datasets: label-judged top-1 and AP, two KPIs each, never mixed with executed success
    for env_id in dataset_envs(cur):
        family = _family(env_id)
        published = cur.published_ap.get(env_id, {})
        best_published = max(published.items(), key=lambda item: item[1]) if published else None

        def rec_ap(rec: Record, env_id: str = env_id) -> dict[str, Any]:
            best = _rec_top(rec, env_id, lambda run: _rec_num(run, "value"))
            if best is None:
                return _point(record_id, None, note=f"{rec.words}: no non-privileged headline run on {env_id}")
            assisted = " · GT-assisted inputs (†)" if "GT-assisted" in (best.get("flags") or []) else ""
            return _point(record_id, round(_rec_num(best, "value"), 3), n=best.get("n"),
                          note=f"{rec.words} · {best['model']} AP {_rec_num(best, 'value'):g}{_rec_ci(best, 1.0)} on "
                               f"{best.get('protocol')}{assisted}", evidence=[_rec_item_id(best)])

        def phase_ap(phase: Phase, snap: Snapshot, env_id: str = env_id) -> dict[str, Any]:
            if not snap.judged:
                return _unconfirmed(phase.id, on_env(phase, env_id))
            best = _top(snap.heads, verdict, env_id, _ap)
            if best is None:
                return _point(phase.id, None, note=f"no {env_id} row in runs.jsonl yet (smoke numbers outside the ledger "
                                                   "are not used)", evidence=on_env(phase, env_id))
            ci = (f" [{best.get('ap_ci_lo'):.3f}, {best.get('ap_ci_hi'):.3f}]"
                  if isinstance(best.get("ap_ci_lo"), (int, float)) and isinstance(best.get("ap_ci_hi"), (int, float)) else "")
            oracle = _oracle(snap.heads, verdict, env_id)
            return _point(phase.id, round(_ap(best), 3), n=best.get("n"),
                          note=f"{best.model} AP {_ap(best):.3f}{ci} on {best.protocol.get('name')} (AP on the 0-100 scale)"
                               + (f" · oracle {_ap(oracle)}" if oracle else " · no oracle run yet"),
                          evidence=on_env(phase, env_id))

        values = column(rec_ap, phase_ap)
        kpis.append({
            "id": f"dataset_ap_{family}", "label": f"AP · {family}", "slot": "S2", "unit": "AP",
            "direction": "higher",
            "target": ({"value": best_published[1], "kind": "reference",
                        "label": f"published best {best_published[0]} {best_published[1]}"} if best_published else None),
            "baseline": None, "values": values, "status": verdict_status(values, digits=1),
            "note": f"AP on {env_id} over the dataset's grasp labels (no grasp executed). Dataset envs are ungated: progress is AP above "
                    "the previous best, beside the oracle and the published rows (curriculum.PUBLISHED_AP).",
            "aggregate": None,
            "provenance": _prov(ledger_path, f"max non-privileged headline ap on {env_id} · {bridge_prov}{record_prov}",
                                curriculum=curriculum_path, pointer="PUBLISHED_AP"),
        })

        def rec_p1(rec: Record, env_id: str = env_id) -> dict[str, Any]:
            best = _rec_top(rec, env_id, lambda run: _rec_num(run, "precision_at_1"))
            if best is None:
                return _point(record_id, None, note=f"{rec.words}: no non-privileged headline P@1 on {env_id}")
            return _point(record_id, _pct(_rec_num(best, "precision_at_1")), n=best.get("n"),
                          note=f"{rec.words} · {best['model']} P@1 {_rec_num(best, 'precision_at_1'):g} on "
                               f"{best.get('protocol')}", evidence=[_rec_item_id(best)])

        def phase_p1(phase: Phase, snap: Snapshot, env_id: str = env_id) -> dict[str, Any]:
            if not snap.judged:
                return _unconfirmed(phase.id, on_env(phase, env_id))
            best = _top(snap.heads, verdict, env_id, _p1)
            if best is None:
                return _point(phase.id, None, note=f"no {env_id} row with precision_at_1 yet", evidence=on_env(phase, env_id))
            return _point(phase.id, _pct(_p1(best)), n=best.get("n"),
                          note=f"{best.model} P@1 {_p1(best):g} on {best.protocol.get('name')}", evidence=on_env(phase, env_id))

        values = column(rec_p1, phase_p1)
        kpis.append({
            "id": f"dataset_p1_{family}", "label": f"Label-judged top-1 · {family}", "slot": "S2", "unit": "%",
            "direction": "higher", "target": None, "baseline": None, "values": values,
            "status": verdict_status(values, unit=" pts", digits=1),
            "note": f"precision@1 on {env_id}: the share of scenes whose top-ranked grasp the dataset's labels call a "
                    "success. No grasp is executed, so it is a separate KPI from executed top-1 success and from AP, never averaged with them.",
            "aggregate": None,
            "provenance": _prov(ledger_path, f"max non-privileged headline precision_at_1 on {env_id} · {bridge_prov}"
                                f"{record_prov}", curriculum=curriculum_path),
        })

    # S3 · decision time: p95 latency of the run each tier-best KPI shows
    for tier, (env_id, best_values, best_kpi, chosen) in tier_best.items():
        short, word = EXECUTED_TIERS[tier]
        values = []
        for point, best in zip(best_values, chosen):
            if point["iteration"] == record_id:
                p95 = _rec_p95_ms(best) if isinstance(best, dict) else None
                values.append(_point(record_id, p95, n=best.get("n") if isinstance(best, dict) else None,
                                     note=(f"{record.words} · {best['model']} p95 {best.get('latency_p95_text')}"
                                           if isinstance(best, dict) else point["note"]), evidence=point["evidence"]))
            elif isinstance(best, Run) and isinstance(best.get("latency_ms_p95"), (int, float)):
                values.append(_point(point["iteration"], round(best.get("latency_ms_p95"), 2), n=best.get("n"),
                                     note=f"{best.model} p95 {best.get('latency_ms_p95'):g} ms (p50 {best.get('latency_ms_p50')})",
                                     evidence=point["evidence"]))
            else:
                values.append(_point(point["iteration"], None, note=point["note"] if not point["measured"] else
                                     f"{best.model if isinstance(best, Run) else 'the best run'} recorded no latency",
                                     evidence=point["evidence"]))
        status = verdict_status(values, unit=" ms", direction="lower")
        last = next((point for point in reversed(values) if point["measured"]), None)
        if last is not None and last["iteration"] != record_id and (verdict is not None or not runs):
            status = ({"word": f"over 1 s · {last['value']:.0f} ms", "tone": "warn"} if last["value"] > LATENCY_LIMIT_MS
                      else {"word": f"within 1 s · {last['value']:g} ms", "tone": "ok"})
        kpis.append({
            "id": f"latency_{short}", "label": f"{word} · decision time p95", "slot": "S3", "unit": "ms",
            "direction": "lower",
            "target": {"value": LATENCY_LIMIT_MS, "kind": "limit", "label": "< 1 s (Zach's deck; BAM KPIs)"},
            "baseline": None, "values": values, "status": status,
            "note": (f"Per-prediction latency (p95) of the run shown by '{best_kpi['label']}', as the runner measured it, "
                     "in sim; the real camera capture time is not included."),
            "aggregate": None,
            "provenance": _prov(ledger_path, f"latency_ms_p95 of the tier-best run on {env_id} · {bridge_prov}{record_prov}"),
        })

    # S4 · wave-1 cells measured on the frozen protocol (frozen = the bench's is_frozen_protocol)
    values = column(
        lambda rec: _point(record_id, float(len(rec.cells() & wave1_ids)), of=wave1_total,
                           note=f"{rec.words}: wave-1 cells with a headline in the record (frozen protocol not re-checked)"),
        lambda phase, snap: (
            _unconfirmed(phase.id, [run.run_id for run in phase.runs if run.cell_id in wave1_ids]) if not snap.judged else
            _point(phase.id, float(len(snap.wave1_frozen)), of=wave1_total,
                   note=(f"{len(snap.wave1_any) - len(snap.wave1_frozen)} more measured only off the frozen protocol"
                         if len(snap.wave1_any) > len(snap.wave1_frozen) else None),
                   evidence=[run.run_id for run in phase.runs if run.cell_id in wave1_ids])))
    kpis.append({
        "id": "wave1_cells", "label": "Wave-1 cells measured", "slot": "S4", "unit": "cells", "direction": "higher",
        "target": {"value": wave1_total, "kind": "scope", "label": f"of {wave1_total} wave-1 cells"},
        "baseline": None, "values": values, "status": verdict_status(values),
        "note": "A cell counts once it has a run the bench calls frozen (gallery.is_frozen_protocol) "
                "(curriculum.cells('wave1')).",
        "aggregate": None,
        "provenance": _prov(ledger_path, f"distinct wave-1 cell_ids with a frozen-protocol run · {bridge_prov}{record_prov}",
                            curriculum=curriculum_path, pointer="CELLS"),
    })

    # S5 · evidence rebuild: recorded headline cells with a row in the rebuilt ledger (raw cell ids; no verdict needed).
    # WHY the ledger-vs-record count only since 2026-10-11: the rebuild loop finished (loop/status.json, all 9 steps);
    # what runs now is the runner service, which has its own KPI below (queue/status.json).
    recorded_cells = record.cells() if record is not None else set()
    if record is not None:
        values = column(
            lambda rec: _point(record_id, 0.0, of=len(recorded_cells), note="the rebuild starts from this record"),
            lambda phase, snap: _point(
                phase.id, float(len(recorded_cells & {run.cell_id for run in snap.runs})), of=len(recorded_cells),
                note="recorded headline cells with a rebuilt ledger row",
                evidence=[run.run_id for run in phase.runs if run.cell_id in recorded_cells]))
        rebuilt, planned = int(values[-1]["value"]), len(recorded_cells)
        kpis.append({
            "id": "rebuild_progress", "label": "Evidence rebuild · cells re-run", "slot": "S5", "unit": "cells",
            "direction": "higher", "target": {"value": planned, "kind": "scope", "label": f"of {planned} recorded cells"},
            "baseline": None, "values": values,
            "status": {"word": f"{rebuilt} of {planned} re-run", "tone": "ok" if rebuilt == planned else "muted"},
            "note": ("Recorded headline cells with at least one row in the rebuilt ledger. Whether a re-run reproduces "
                     "its recorded value is the rebuild's own comparison (docs/grasping/compare_rebuild.py), not this count."),
            "aggregate": None,
            "provenance": _prov(ledger_path, "distinct cell_ids of the record's headline runs present in runs.jsonl"
                                + f" · {record.path}"),
        })

    # S4 · the runner service (loop contract v5 section 4): its own status file, read as written, on the latest column.
    if sources.get("grasping_queue_status_json") and iterations:
        early = "the runner reports only its current state, not a reading per phase"
        if runner is not None:
            word, tone, note = runner_reading(runner)
            done = _count(runner.get("done_24h"))
            latest = _point(iterations[-1]["id"], float(done) if done is not None else None, note=note
                            if done is not None else f"{note} · done_24h not reported")
            status = {"word": word, "tone": tone}
        else:
            reason = runner_problem or "runner not started yet (no out/queue/status.json)"
            latest = _point(iterations[-1]["id"], None, note=reason)
            status = {"word": "runner not started" if runner_problem is None else "runner status unreadable",
                      "tone": "muted" if runner_problem is None else "warn"}
        kpis.append({
            "id": "runner_queue", "label": "Runner · runs done in 24 h", "slot": "S4", "unit": "runs", "direction": "higher",
            "target": None, "baseline": None,
            "values": [_point(item["id"], None, note=early) for item in iterations[:-1]] + [latest],
            "status": status,
            "note": ("The runner service (queue_service.py) runs every requested experiment: its state, what is running, "
                     "the queue, runs done and failed in the last 24 h, its heartbeat and the last B0 canary, as it wrote "
                     "them in queue/status.json (grasp-runner-status/1). It stops itself after 2 h idle or on STOP."),
            "aggregate": None,
            "provenance": _prov(sources["grasping_queue_status_json"], "grasp-runner-status/1 fields, read as written"),
        })

    # S5 · 3-seed rule on cells trained here. WHY still measured without the bench's verdict: it counts
    # train_summary.seed per cell, a raw ledger field the gallery does not judge.
    def seed_point(phase: Phase, snap: Snapshot) -> dict[str, Any]:
        seeds: dict[str, set[int]] = {}
        for run in snap.runs:
            if run.train_seed is not None and run.cell_id in wave1_ids:
                seeds.setdefault(run.cell_id, set()).add(run.train_seed)
        evidence = [run.run_id for run in phase.runs if run.train_seed is not None]
        if not seeds:
            return _point(phase.id, None, note="no cell trained here yet", evidence=evidence)
        done = sum(1 for found in seeds.values() if len(found) >= SEED_RULE)
        counts = sorted({len(found) for found in seeds.values()})
        return _point(phase.id, float(done), of=len(seeds),
                      note=f"seeds per trained cell: {', '.join(str(c) for c in counts)}", evidence=evidence)

    values = column(lambda rec: _point(record_id, None, note=f"{rec.words}: the record carries no training seeds"),
                    seed_point)
    status = status_of(values)
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
    def dirty_point(phase: Phase, snap: Snapshot) -> dict[str, Any]:
        total = len(snap.runs)
        dirty = sum(1 for run in snap.runs if run.get("git_dirty") is True)
        return _point(phase.id, round(100.0 * dirty / total, 1) if total else None, n=total,
                      note=f"{dirty} of {total} rows git_dirty", evidence=[run.run_id for run in phase.runs])

    def dirty_record(rec: Record) -> dict[str, Any]:
        dirty = sum(1 for run in rec.runs if str(run.get("git_sha") or "").endswith(" dirty"))
        return _point(record_id, round(100.0 * dirty / len(rec.runs), 1), n=len(rec.runs),
                      note=f"{rec.words}: {dirty} of {len(rec.runs)} recorded runs from a dirty tree")

    values = column(dirty_record, dirty_point)
    kpis.append({
        "id": "dirty_share", "label": "Runs from a dirty tree", "slot": "S5", "unit": "%", "direction": "lower",
        "target": None, "baseline": None, "values": values,
        "status": status_of(values, unit=" pts", digits=1, direction="lower"),
        "note": "A dirty run cannot be reproduced from its git_sha alone.",
        "aggregate": None,
        "provenance": _prov(ledger_path, f"count(git_dirty) / rows, cumulative{record_prov}"),
    })

    # Hard gates · one per gated env: the bench's env_verdict (beaten on every frozen seed), stated on the point so the
    # page never recomputes pass/fail from value against target. A recorded value states "not yet re-proved".
    # WHY only without a scoreboard: the scoreboard's v5 gates (eval-1000, canaries apart) replace these v4 gallery
    # verdicts, and carry each v4 verdict beside them; two verdict sets on one page would contradict each other.
    for env_id, gate in (cur.gates.items() if board is None else ()):
        gate_pct = round(gate * 100, 2)

        def rec_gate(rec: Record, env_id: str = env_id, gate_pct: float = gate_pct) -> dict[str, Any]:
            best = _rec_top(rec, env_id, _rec_executed_key)
            if best is None or _rec_num(best, "ci_lo") is None:
                return _point(record_id, None, note=f"{rec.words}: no non-privileged headline run on {env_id}")
            lb = _pct(_rec_num(best, "ci_lo"))
            note = f"{rec.words} · {best['model']} Wilson LB {lb:g} % on {best.get('protocol')} (gate {gate_pct:g} %)"
            # WHY the short why: the page prints it on one line beside "now <LB>"; the model and protocol stay in the note
            return {**_point(record_id, lb, n=best.get("n"), note=note, evidence=[_rec_item_id(best)]),
                    "verdict": {"pass": None, "why": f"{rec.words} · {best['model']}"}}

        def phase_gate(phase: Phase, snap: Snapshot, env_id: str = env_id) -> dict[str, Any]:
            if not snap.judged:
                return {**_unconfirmed(phase.id, on_env(phase, env_id)), "verdict": {"pass": None, "why": UNCONFIRMED}}
            best = snap.best.get(env_id)
            if best is None:
                # WHY no verdict here: the env is simply not rebuilt yet, so the record's column (if any) still speaks.
                return _point(phase.id, None, note=f"{env_id} not in the rebuilt ledger yet", evidence=on_env(phase, env_id))
            lb = _pct(best.get("ci_lo")) if isinstance(best.get("ci_lo"), (int, float)) else None
            measured = f"{best.model} Wilson LB {lb:g} % on {best.protocol.get('name')}" if lb is not None else \
                f"{best.model} has no Wilson LB"
            if env_id in snap.beaten:
                why, note = f"beaten · {best.model}", f"beaten · {measured}; every frozen seed clears (the bench's env_verdict)"
            elif env_id in snap.provisional:
                why, note = (f"provisional · {best.model}",
                             f"provisional · {measured}; clears only off the frozen protocol or on some training seeds")
            else:
                why, note = f"not beaten · best {best.model}", f"not beaten · best {measured}"
            return {**_point(phase.id, lb, n=best.get("n"), note=note, evidence=on_env(phase, env_id)),
                    "verdict": {"pass": env_id in snap.beaten, "why": why}}

        values = column(rec_gate, phase_gate)
        decisive = next((point for point in reversed(values) if "verdict" in point), None)
        if decisive is None:
            status = {"word": "not measured yet", "tone": "muted"}
        elif decisive["iteration"] == record_id:
            status = {"word": record.words, "tone": "muted"}
        elif decisive["verdict"]["pass"] is None:
            status = dict(UNCONFIRMED_STATUS)
        else:
            status = {"word": decisive["verdict"]["why"].split(" · ")[0], "tone": "ok" if decisive["verdict"]["pass"] else "muted"}
        kpis.append({
            "id": f"gate_{env_id.replace('/', '_')}", "label": env_id, "slot": "S2", "unit": "%", "direction": "higher",
            "target": {"value": gate_pct, "gate": gate_pct, "kind": "gate",
                       "label": f"Wilson LB ≥ {gate_pct:g} % · frozen protocol · every training seed"},
            "baseline": None, "values": values, "status": status,
            "note": (f"{cur.envs[env_id].title}. Pass/fail is the bench's own gallery.env_verdict, read through "
                     "grasp_bench_bridge; the value is the Wilson 95% lower bound of the run it names."),
            "aggregate": None,
            "provenance": _prov(ledger_path, f"gallery.env_verdict({env_id}) · {bridge_prov}{record_prov}",
                                curriculum=curriculum_path, pointer="GATES"),
        })

    if board is not None:
        # WHY demoted, not deleted (contract P-W2): the gallery-verdict KPIs stay on the track page as detail under the
        # champion's header; ``level`` says which is which for a page that folds detail away.
        header = scoreboard_kpis(board, stale, iterations, sources["grasping_scoreboard"], by_iteration)
        for kpi in kpis:
            kpi["level"] = "detail"
        kpis = header + kpis
    track["kpis"] = kpis
    track["north_star"] = "picks_per_hour" if board is not None and any(k["id"] == "picks_per_hour" for k in kpis) \
        else "envs_beaten"
    if roadmap is not None:
        track["milestones"] = milestones(roadmap, sources["grasping_roadmap_v4"])
    by_kpi = {kpi["id"]: [evidence for point in kpi["values"] for evidence in point["evidence"]] for kpi in kpis}
    track["evidence"] = {"by_iteration": by_iteration, "by_kpi": by_kpi}

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
    if roadmap is not None:
        # WHY the roadmap's decisions replace the per-model approvals (coordinator, 2026-10-10): the eight download cells
        # are one question, D1, and at most three decisions are surfaced at once (needs.py reads the same file).
        needs = [dict(need) for need in milestones(roadmap, sources["grasping_roadmap_v4"])["needs_you"]]
    track["needs_you"] = needs
    needs_words = f"{len(needs)} " + ("decisions open (roadmap_v4.json)" if roadmap is not None else "download approvals open")

    # ---- state + summary
    latest = snaps[-1] if snaps else snapshot(None, [], cur, None)
    tier = frontier_tier(latest, cur) if latest.judged else None
    last_run = max(runs, key=lambda run: run.started_at) if runs else None
    toy_gated = [e for e in cur.gates if _family(e) == "toy"]
    rebuild = (f"{len(recorded_cells & {run.cell_id for run in runs})} of {len(recorded_cells)} recorded cells re-run"
               if record is not None else "")
    tail = [f"last run started {_local(last_run.started_at)}" if last_run else "",
            f"ledger written {_local(ledger_mtime)}" if ledger_mtime else "no ledger file yet",
            f"{bad_lines} unreadable ledger lines skipped" if bad_lines else "", lane or ""]
    if not runs and record is not None:
        # WHY its own state: the ledger was deleted with its worktree and is being rebuilt; until it is, the page shows
        # the recovered record, labelled as such, and never "0 of N beaten".
        track["state"] = {"word": "Rebuilding evidence", "tone": "warn",
                          "detail": " · ".join(bit for bit in [
                              "the rebuilt ledger has no rows yet",
                              f"KPIs show the {record.label} ({len(record.runs)} runs), not yet re-proved",
                              rebuild] + tail if bit),
                          "since": None}
        track["summary"] = " · ".join(bit for bit in [
            f"evidence rebuild: {rebuild}", f"values are the {record.label}, not yet re-proved", lane or "",
            needs_words if needs else ""] if bit)
    elif not runs:
        track["state"] = {"word": "No runs yet", "tone": "muted", "detail": f"runs.jsonl is empty · written {_local(ledger_mtime)}",
                          "since": None}
        track["summary"] = f"no ledger rows yet · {wave1_total} wave-1 cells planned"
    elif verdict is None:
        # WHY no frontier and no counts: both are the bench's verdict, and a guess would read as the bench's word.
        track["state"] = {"word": "Bench verdict unavailable", "tone": "warn",
                          "detail": " · ".join(bit for bit in [unavailable or "", f"{len(runs)} ledger rows"] + tail if bit),
                          "since": None}
        track["summary"] = (f"{UNAVAILABLE}: {unavailable} · {len(runs)} ledger rows · {wave1_total} wave-1 cells planned"
                            + (f" · evidence rebuild: {rebuild}" if rebuild else "")
                            + (f" · {needs_words}" if needs else ""))
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
        if rebuild:
            detail_bits.append(f"evidence rebuild: {rebuild}")
        track["state"] = {"word": word, "tone": "ok", "detail": " · ".join(bit for bit in detail_bits + tail if bit),
                          "since": since}
        mujoco_beaten = [e for e in mujoco_gated if e in latest.beaten]
        toy_beaten = [e for e in toy_gated if e in latest.beaten]
        summary = (f"{len(latest.beaten)} of {gated_total} gated envs beaten (toy {len(toy_beaten)}/{len(toy_gated)}, "
                   f"MuJoCo {len(mujoco_beaten)}/{len(mujoco_gated)}) · {len(latest.wave1_frozen)} of {wave1_total} "
                   f"wave-1 cells measured")
        if tier is not None:
            summary += f" · frontier tier {tier} ({cur.tier_name(tier)})"
        if rebuild:
            summary += f" · evidence rebuild: {rebuild}"
        if needs:
            summary += f" · {needs_words}"
        if lane:
            summary += f" · {lane}"
        track["summary"] = summary
    if board is not None and runs:
        # WHY the champion is the one calm answer once a scoreboard exists (loop contract v5, kpi_header_rule): the
        # header is the champion's four tiles; the frontier tier stays in the rung and the gallery counts in detail.
        sentence, worry = scoreboard_sentence(board, stale)
        runner_word = runner_reading(runner)[0] if runner is not None else "runner not started"
        champ = ((board.get("header") or {}).get("champion") or {})
        track["state"] = {"word": f"Champion {champ.get('model')}" if champ.get("model") else "No champion yet",
                          "tone": "warn" if worry else "ok",
                          "detail": " · ".join(bit for bit in [sentence, f"runner: {runner_word}"] + tail if bit),
                          "since": champ.get("since") if isinstance(champ.get("since"), str) else None}
        track["summary"] = " · ".join(bit for bit in [sentence, needs_words if needs else "", lane or ""] if bit)
    track["iteration"] = {"unit": "wave", "label": labels[-1] if labels else "none reported"}
    track["rung"] = _rung(cur, tier, runs) if verdict is not None else None

    # ---- links + provenance
    out_root = Path(sources["grasping_out_dir"]) if sources.get("grasping_out_dir") else ledger_file.parent.parent
    track["links"] = (
        [{"label": label, "kind": "media", "media": media_id} for media_id, _, label, _ in gallery_refs]
        + [{"label": "Ledger (runs.jsonl)", "kind": "path", "value": ledger_path},
           {"label": "Curriculum (curriculum.py)", "kind": "path", "value": curriculum_path}]
        + ([{"label": f"Recovered record ({record.label})", "kind": "path", "value": record.path}] if record else [])
        + ([{"label": "Scoreboard (scoreboard.json)", "kind": "path", "value": sources["grasping_scoreboard"]}]
           if board is not None else [])
        + ([{"label": "Runner status (queue/STATUS.md)", "kind": "path", "value": str(queue_md)}] if queue_md_mtime else [])
        + ([{"label": "Runner status (queue/status.json)", "kind": "path", "value": sources["grasping_queue_status_json"]}]
           if runner is not None else [])
        + ([{"label": "Milestones (roadmap_v4.json)", "kind": "path", "value": sources["grasping_roadmap_v4"]}]
           if roadmap else [])
        + [{"label": "Rebuild the bench gallery", "kind": "command",
            "value": f"cd {bench_root} && env -u VIRTUAL_ENV GRASP_BENCH_OUT={out_root} .venv/bin/grasp-bench gallery"}]
    )
    if other_needs and iterations:
        last_id = iterations[-1]["id"]
        by_iteration[last_id].append({
            "id": "grasping:blocked-cells", "iteration": last_id, "kind": "note",
            "title": "Cells blocked on something other than you", "when": curriculum_mtime,
            "metrics": {why: len(cells) for why, cells in other_needs.items()}, "status": "blocked", "media": [],
            "links": [], "note": " · ".join(f"{why}: {_join(cells)}" for why, cells in other_needs.items()),
        })
    # WHY source.problems (the rig adapter's field; the build merges an adapter's source block): a missing verdict is
    # a problem with the track's inputs, and the page's source panel is where an input problem is read.
    track["source"] = {"problems": [p for p in (unavailable_note,
                                                f"{bad_lines} unreadable ledger lines skipped" if bad_lines else None,
                                                record_problem, runner_problem, board_problem, roadmap_problem) if p],
                       "bench_verdict": bridge_info}
    track["provenance"] = {
        "snapshot": None, "pointer": None, "source": ledger_path,
        "derived": (f"{len(runs)} ledger rows (written {ledger_mtime or 'never'}) grouped into tier phases; curriculum.py "
                    f"(written {curriculum_mtime}) for tiers, wave-1 cells, gates and published AP; verdicts: "
                    f"{bridge_prov}{record_prov}"),
    }
    return track
