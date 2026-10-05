"""project_detection: bam-roadmap/1 for the detection track (object detection and hyperspectral), from its planned ladder.

No loop runs this track yet, so there are no events, ledger, tests or runs to read: the only structured source is
``ladder_data.py`` in the planning session's ``docs/hyperspectral`` folder (RUNGS, plus the KPI table that names the
current rung). This projector reads it and nothing else, and writes nothing. Every rung is therefore unproven:

- a rung's claim is ``missing`` unless the ladder itself gives the rung a ``status`` (it does not today), and a
  claimed green shows as ``claimed``, never ``green``, because its gate is only a ``stated`` criterion: a condition
  written in prose, unknown until a loop declares it as data (the same rule kinsim and rig follow);
- ``needs_rungs`` are real prerequisites (the ladder's own DAG), so they become ``depends_on``, a ``prerequisites``
  criterion and ``prerequisite`` edges, exactly as kinsim does for its curriculum;
- the current rung is the one the ladder's KPI table names in its "Frontier gate" row (``today``: "H1: 2 of 12 ..."),
  and that progress is kept in the rung's ``x.progress``. It is the plan's word, not a proof, and it moves no status.

WHY the ladder is parsed with ``ast`` and never imported: it is a file another session owns, and importing runs its
code. Its tables are literals except that each rung is written ``dict(id=..., ...)``, so those calls (and only those)
are rewritten into dict displays before ``ast.literal_eval``; any other call refuses the table.

The loop may move to the Windows box (the hyperspectral camera is there), but this projector reads whatever
``detection_dir`` points at, so only the sources map has to change when it does.
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import links, model, proof
from .files import ProjectionError, file_sha256
from .gitinfo import Repo
from .links import EvidenceBook, Roots

LADDER_FILE = "ladder_data.py"
LOOP_ID = "detection"
AXIS_ID = "hyperspectral"
PHASE = "planned: no loop has run"
#: "H1: 2 of 12 configs reproduced": the rung a KPI row's ``today`` text starts with, and its progress when it has one.
_CURRENT_RUNG = re.compile(r"^\s*(?P<rung>[A-Za-z][A-Za-z0-9_.-]*):\s*(?:(?P<done>\d+)\s+of\s+(?P<of>\d+))?")


def project_detection(detection_dir: Path, *, now: str, head: str | None = None) -> dict[str, Any]:
    """bam-roadmap/1 for the detection track, judged at ``head`` (default: the checkout's HEAD)."""

    directory = Path(detection_dir).resolve()
    ladder_path = directory / LADDER_FILE
    tables, skipped = read_ladder_tables(ladder_path)
    repo = Repo(directory, head)
    if not repo.available:
        raise ProjectionError(f"{directory} is not inside a git checkout")
    roots = Roots(repo=repo.root, repo_aliases=repo.other_checkouts())
    return _DetectionProjector(ladder_path=ladder_path, tables=tables, skipped=skipped, repo=repo, roots=roots).document(now)


# ---------------------------------------------------------------- reading the ladder without running it
class _DictCalls(ast.NodeTransformer):
    """``dict(a=1, b=2)`` becomes ``{"a": 1, "b": 2}``; every other call is left for ``literal_eval`` to refuse."""

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "dict" and not node.args and all(keyword.arg for keyword in node.keywords):
            return ast.Dict(keys=[ast.Constant(keyword.arg) for keyword in node.keywords], values=[keyword.value for keyword in node.keywords])
        return node


def read_ladder_tables(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """(the module's literal tables by name, why each non-literal one was skipped). Nothing in the file is executed."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError) as error:
        raise ProjectionError(f"cannot read {path}: {error}") from error
    tables: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            name, value = statement.targets[0].id, statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value is not None:
            name, value = statement.target.id, statement.value
        else:
            continue
        try:
            expression = ast.fix_missing_locations(ast.Expression(body=_DictCalls().visit(value)))
            tables[name] = ast.literal_eval(expression)
        except (ValueError, TypeError, SyntaxError, RecursionError) as error:
            skipped[name] = f"{error}"
    if "RUNGS" not in tables:
        why = f": {skipped['RUNGS']}" if "RUNGS" in skipped else ""
        raise ProjectionError(f"{path}: RUNGS is not literal data (or is missing), so it is not read{why}")
    return tables, skipped


# ---------------------------------------------------------------- the projection
class _DetectionProjector:
    def __init__(self, *, ladder_path: Path, tables: Mapping[str, Any], skipped: Mapping[str, str], repo: Repo, roots: Roots) -> None:
        self.ladder_path, self.tables, self.skipped, self.repo, self.roots = ladder_path, tables, skipped, repo, roots
        self.warnings: list[str] = []
        rungs = tables["RUNGS"]
        if not isinstance(rungs, list) or not all(isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] for row in rungs):
            raise ProjectionError(f"{ladder_path}: RUNGS must be a list of rungs that each carry an id")
        self.rungs = rungs
        self.index = {row["id"]: position for position, row in enumerate(rungs)}
        if len(self.index) != len(rungs):
            raise ProjectionError(f"{ladder_path}: RUNGS repeats a rung id")
        self.needs = {row["id"]: self._needs(row) for row in rungs}
        self.frontier, self.progress = self._current_rung()
        self.derived: dict[str, dict[str, Any]] = {}

    def _needs(self, row: Mapping[str, Any]) -> list[str]:
        named = links.unique(row.get("needs_rungs") or [])
        unknown = [name for name in named if name not in self.index]
        if unknown:
            self.warnings.append(f"{row['id']}: needs_rungs names {', '.join(unknown)}, which "
                                 f"{'is' if len(unknown) == 1 else 'are'} not in this ladder; dropped")
        return [name for name in named if name in self.index]

    def _current_rung(self) -> tuple[list[str], dict[str, Any]]:
        """The rung the ladder's KPI table names as the frontier, and the progress its ``today`` text states."""

        for row in self.tables.get("KPIS") or []:
            slot, today = (row[0], row[3]) if isinstance(row, (list, tuple)) and len(row) >= 4 else (None, None)
            if not isinstance(slot, str) or "frontier" not in slot.lower() or not isinstance(today, str):
                continue
            found = _CURRENT_RUNG.match(today)
            if found and found["rung"] in self.index:
                progress = {}
                if found["done"] is not None:
                    progress = {found["rung"]: {"done": int(found["done"]), "of": int(found["of"]),
                                                "text": today.strip(), "source": f"KPIS {slot}, today"}}
                return [found["rung"]], progress
        return [], {}

    def document(self, now: str) -> dict[str, Any]:
        for rung_id in self.index:
            self._rung(rung_id, ())
        rungs = [self.derived[rung_id] for rung_id in self.index]
        axes = [{"id": AXIS_ID, "title": f"Hyperspectral ladder ({rungs[0]['id']} to {rungs[-1]['id']})", "order": 0}]
        edges = [{"from": parent, "to": rung_id, "kind": "prerequisite",
                  "via": (self.rungs[self.index[rung_id]].get("needs_detail") or {}).get(parent)}
                 for rung_id in self.index for parent in self.needs[rung_id]]
        return {
            "schema": model.SCHEMA_ID,
            "loop": LOOP_ID,
            "title": "Object detection and hyperspectral",
            "generated_at": now,
            "as_of": {"head": self.repo.head, "branch": self.repo.branch, "context": {}},
            "roots": self.roots.as_dict(),
            "sources": self._sources(),
            "rules": {"proof_strengths": list(model.PROOF_STRENGTHS), "status_rule": "bam_roadmap.model.derive_status",
                      "loop_rules": proof.source_link(self.ladder_path, self.roots, "Gate thresholds are starting values", "")},
            "summary": {"wave": None, "phase": PHASE, "frontier": self.frontier, "milestone": None, "links": {},
                        "kpis": self._kpis()},
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

    def _sources(self) -> list[dict[str, Any]]:
        entry = links.link("file", str(self.ladder_path), self.roots)
        entry.update({"role": "ladder", "sha256": file_sha256(self.ladder_path)})
        return [entry]

    def _kpis(self) -> list[dict[str, Any]]:
        rows = []
        for row in self.tables.get("KPIS") or []:
            if isinstance(row, (list, tuple)) and len(row) >= 5:
                rows.append({"slot": row[0], "kpi": row[1], "today": row[3], "target": row[4]})
        return rows

    def _warnings(self) -> list[str]:
        warnings = ["planned ladder; no loop has run: every rung is unproven and none can be green"]
        relative = os.path.relpath(self.ladder_path, self.repo.root)
        if relative not in set(self.repo.tracked_files()):
            warnings.append(f"{LADDER_FILE} is untracked in {self.repo.root}: git gives it no history, so it binds no commit "
                            "and a worktree sweep or a peer's stash -u can lose it")
        warnings += [f"{name} is not literal data, so it was skipped ({why})" for name, why in self.skipped.items() if name in ("KPIS",)]
        if not self.frontier:
            warnings.append("the ladder names no current rung (its KPIS 'Frontier gate' row is missing or names no rung)")
        return warnings + self.warnings

    # ------------------------------------------------------------ one rung
    def _rung(self, rung_id: str, stack: tuple[str, ...]) -> dict[str, Any]:
        if rung_id in self.derived:
            return self.derived[rung_id]
        if rung_id in stack:
            raise ProjectionError(f"ladder cycle through {' -> '.join((*stack, rung_id))}")
        for parent in self.needs[rung_id]:
            self._rung(parent, (*stack, rung_id))
        position = self.index[rung_id]
        row = self.rungs[position]
        source = proof.source_link(self.ladder_path, self.roots, f'id="{rung_id}"', f"/RUNGS/{position}")
        gate = str(row.get("gate") or "")
        criteria: list[dict[str, Any]] = []
        if self.needs[rung_id]:
            criteria.append(self._prerequisites_criterion(rung_id, source))
        if gate.strip():
            criteria.append(proof.stated_criterion(criterion_id=f"{rung_id}#stated", text=gate, source=source, audit=False))
        # WHY the ladder's word only when it gives one: the planned ladder has no status field, so every rung is missing;
        # a future ladder that adds one is still only believed as far as derive_status lets a claim stand.
        claimed = row.get("status") if row.get("status") in model.CLAIMED_STATUSES else "missing"
        status, reason = model.derive_status(claimed, criteria)
        book = EvidenceBook()
        needs_detail = row.get("needs_detail") or {}
        rung = {
            "id": rung_id, "axis": AXIS_ID, "title": str(row.get("short") or rung_id), "adds": None, "order": position, "wave": None,
            "depends_on": list(self.needs[rung_id]), "alias_of": None, "status": status, "claimed_status": claimed,
            "status_reason": reason, "claimed_by": {"source": source, "event": None}, "frontier": rung_id in self.frontier,
            "done_when": {"rule": "all" if criteria else "none", "text": gate, "source": source},
            "criteria": criteria, "support": None, "evidence": book.items, "history": [], "blockers": [], "kpis": [], "notes": [],
            "x": {"kind": row.get("kind"), "question": row.get("question"), "gate_short": row.get("gate_short"),
                  "ruler": row.get("ruler"), "needs": row.get("needs"), "needs_detail": needs_detail,
                  "ladder_status": row.get("status"), **({"progress": self.progress[rung_id]} if rung_id in self.progress else {})},
        }
        self.derived[rung_id] = proof.finish_rung(rung, book)
        return self.derived[rung_id]

    def _prerequisites_criterion(self, rung_id: str, source: dict[str, Any]) -> dict[str, Any]:
        statuses = {parent: self.derived[parent]["status"] for parent in self.needs[rung_id]}
        verdict, strength, reason = model.prerequisites_verdict(statuses)
        targets = [proof.rung_target(parent, status, True) for parent, status in statuses.items()]
        return proof.criterion(criterion_id=f"{rung_id}#prerequisites", kind="prerequisites", method=None,
                               title="every prerequisite green", text="every prerequisite is green or done",
                               source=source, targets=targets, verdict=verdict, strength=strength, reason=reason, evidence=[])


__all__ = ["project_detection", "read_ladder_tables"]
