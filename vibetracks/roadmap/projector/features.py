"""project_features: bam-roadmap/1 for a file-first Vibe Tracks project, from its own feature notes.

A Vibe Tracks project (``Project.vibetrack`` and its ``features/*.md``, ``vibe-track: feature``) is a plan, not a
loop: there are no events, ledgers or gate runs to read. This projector reads the descriptor and its notes
(``vibetracks.project.load_project``) and git, and writes nothing. It is how the Vibe Tracks track shows the repo's
own roadmap on its track page (``workspace/tracks/activity/vibetracks.md`` declares ``vibe-roadmap: {projector:
features}``).

- **Axes** are the descriptor's ``vibetracks.roadmap.axes`` (area id -> title, in order). A feature sits on the first
  of its ``vibe-areas`` that is an axis; one that names none sits on ``other``. Its other areas stay in ``x.areas``.
- **Rungs** are the features (``archived`` ones are left out and counted in a warning), ordered within an axis done
  first, then open work in dependency order.
- **depends_on** is ``vibe-depends-on`` resolved by ``load_project``: a ``prerequisites`` criterion and an edge each.
- **The claim** is the note's ``vibe-status``: ``done`` -> done; ``running`` and ``review`` -> partial (built or being
  built, not accepted); everything else -> missing.
- **The proof** of a done feature is ``vibe-commits``: each commit must be the head or an ancestor of it in this
  checkout (``Evaluator.judge_commit``, the rig loop's "landed" rule). A done note that names no commit stays
  ``claimed``, and so does one naming a commit this repository does not know; a known commit outside this history
  (an unmerged branch) makes it ``stale``. That proves the work landed, not that it still behaves; a feature's tests
  are not read.
- **The frontier** is every open feature whose prerequisites are all done and whose note has left ``backlog``
  (``ready``, ``frontier``, ``running``, ``waiting``, ``review``): what can move now, as the plan schedules it.
- ``vibe-evidence`` (reports, review packets) and ``vibe-review-packet`` are context evidence: shown, never part of
  the verdict. ``vibe-origin`` (where the item came from) is kept in ``x.origin``.

WHY a plan's word is believed only this far: the format's one rule (``model.derive_status``) is that a rung is done
only on recorded proof. For a feature note the only record git can check is that the commits it names landed here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ...edits import read_note_exact
from ...errors import VibeTracksError
from ...notes import parse_frontmatter, string_list
from ...project import TrackItem, TrackProject, load_project
from . import links, model, proof
from .evaluate import Evaluator
from .files import ProjectionError, file_sha256
from .gitinfo import Repo
from .links import EvidenceBook, Roots

LOOP_ID = "features"
OTHER_AXIS = "other"
COMMITS_KEY = "vibe-commits"
ORIGIN_KEY = "vibe-origin"
#: A note's vibe-status as the format's claim: done is a claimed done (proof decides), work in hand is partial.
CLAIM_OF_STATUS = {"done": "done", "running": "partial", "review": "partial"}
#: Statuses that have left the backlog: an unblocked feature in one of these is on the frontier.
SCHEDULED = ("ready", "frontier", "running", "waiting", "review")
#: Open work first in this order within one axis (then dependency order, then id).
OPEN_ORDER = {"running": 0, "review": 1, "waiting": 2, "ready": 3, "frontier": 3, "backlog": 5}


def project_features(descriptor: Path, *, now: str, head: str | None = None) -> dict[str, Any]:
    """bam-roadmap/1 for the project ``descriptor`` describes, judged at ``head`` (default: the checkout's HEAD)."""

    path = Path(descriptor).expanduser().resolve()
    try:
        project = load_project(path)
    except VibeTracksError as error:
        raise ProjectionError(f"cannot read {path}: {error}") from error
    repo = Repo(path.parent, head)
    if not repo.available:
        raise ProjectionError(f"{path.parent} is not inside a git checkout")
    roots = Roots(repo=repo.root, repo_aliases=repo.other_checkouts())
    return _FeaturesProjector(path, project, repo, roots).document(now)


def roadmap_axes(descriptor: Path) -> dict[str, str]:
    """``vibetracks.roadmap.axes`` of the descriptor: area id -> axis title, in declared order (empty when absent)."""

    try:
        raw = yaml.safe_load(Path(descriptor).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise ProjectionError(f"cannot read {descriptor}: {error}") from error
    meta = raw.get("vibetracks") if isinstance(raw, Mapping) else None
    roadmap = meta.get("roadmap") if isinstance(meta, Mapping) else None
    axes = roadmap.get("axes") if isinstance(roadmap, Mapping) else None
    if not isinstance(axes, Mapping):
        return {}
    return {str(area): str(title or area) for area, title in axes.items()}


class _FeaturesProjector:
    def __init__(self, descriptor: Path, project: TrackProject, repo: Repo, roots: Roots) -> None:
        self.descriptor, self.project, self.repo, self.roots = descriptor, project, repo, roots
        self.evaluator = Evaluator(repo, roots)
        self.warnings: list[str] = []
        self.declared_axes = roadmap_axes(descriptor)
        self.archived = [item for item in project.items if item.status == "archived" or item.archived]
        self.items = {item.id: item for item in project.items if item not in self.archived}
        self.frontmatter = {feature_id: self._frontmatter(item) for feature_id, item in self.items.items()}
        self.needs = {feature_id: self._needs(item) for feature_id, item in self.items.items()}
        self.axis_of = {feature_id: self._axis(item) for feature_id, item in self.items.items()}
        self.topo = self._topological_order()
        self.derived: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------ reading
    def _frontmatter(self, item: TrackItem) -> dict[str, Any]:
        try:
            return parse_frontmatter(read_note_exact(Path(item.absolute_path)))[0]
        except (OSError, UnicodeDecodeError, VibeTracksError):
            return {}

    def _needs(self, item: TrackItem) -> list[str]:
        archived = {other.id for other in self.archived}
        kept = [dependency for dependency in item.dependencies if dependency in self.items]
        dropped = [dependency for dependency in item.dependencies if dependency in archived]
        if dropped:
            self.warnings.append(f"{item.id} depends on archived {', '.join(dropped)}; that edge is not drawn")
        if item.unresolved_dependencies:
            self.warnings.append(f"{item.id}: vibe-depends-on names {', '.join(item.unresolved_dependencies)}, which "
                                 "no feature note matches; dropped")
        return links.unique(kept)

    def _axis(self, item: TrackItem) -> str:
        return next((area for area in item.areas if area in self.declared_axes), OTHER_AXIS)

    def _topological_order(self) -> dict[str, int]:
        """Each feature's position in one dependency order (prerequisites first, ties by id); a cycle refuses."""

        order: dict[str, int] = {}
        state: dict[str, str] = {}

        def visit(feature_id: str, stack: tuple[str, ...]) -> None:
            if state.get(feature_id) == "done":
                return
            if state.get(feature_id) == "open":
                raise ProjectionError(f"feature dependency cycle through {' -> '.join((*stack, feature_id))}")
            state[feature_id] = "open"
            for parent in sorted(self.needs[feature_id]):
                visit(parent, (*stack, feature_id))
            state[feature_id] = "done"
            order[feature_id] = len(order)

        for feature_id in sorted(self.items):
            visit(feature_id, ())
        return order

    # ------------------------------------------------------------ the document
    def document(self, now: str) -> dict[str, Any]:
        for feature_id in sorted(self.items, key=lambda name: self.topo[name]):
            self._rung(feature_id)
        used = set(self.axis_of.values())
        axis_ids = [axis for axis in self.declared_axes if axis in used] + ([OTHER_AXIS] if OTHER_AXIS in used else [])
        axes = [{"id": axis, "title": self.declared_axes.get(axis, "Other areas"), "order": order}
                for order, axis in enumerate(axis_ids)]
        rungs = []
        for axis in axis_ids:
            mine = sorted((rung for rung in self.derived.values() if rung["axis"] == axis), key=self._sort_key)
            for order, rung in enumerate(mine):
                rung["order"] = order
            rungs += mine
        edges = [{"from": parent, "to": rung["id"], "kind": "prerequisite", "via": None}
                 for rung in rungs for parent in rung["depends_on"]]
        frontier = [rung["id"] for rung in rungs if rung["frontier"]]
        return {
            "schema": model.SCHEMA_ID,
            "loop": LOOP_ID,
            "title": f"{self.project.title} roadmap",
            "generated_at": now,
            "as_of": {"head": self.repo.head, "branch": self.repo.branch, "context": {}},
            "roots": self.roots.as_dict(),
            "sources": self._sources(),
            "rules": {"proof_strengths": list(model.PROOF_STRENGTHS), "status_rule": "bam_roadmap.model.derive_status",
                      "loop_rules": proof.source_link(self.descriptor, self.roots, "roadmap:", "/vibetracks/roadmap")},
            "summary": {"wave": None, "phase": self._phase(rungs), "frontier": frontier, "milestone": None, "links": {},
                        "blockers": [f"{rung['id']} {rung['title']}" for rung in rungs
                                     if rung["x"]["vibe_status"] == "waiting"]},
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

    def _sort_key(self, rung: Mapping[str, Any]) -> tuple:
        # WHY done first: where_rows reads "here" as the end of an axis's leading run of satisfied rungs, so the banked
        # features lead and "next" is the first open one, in the order the plan can build them.
        done = rung["claimed_status"] == "done"
        rank = 0 if done else 1 + OPEN_ORDER.get(rung["x"]["vibe_status"], 4)
        return (0 if done else 1, self.topo[rung["id"]] if not done else 0, rank, rung["id"])

    def _phase(self, rungs: list[dict[str, Any]]) -> str:
        done = sum(1 for rung in rungs if rung["claimed_status"] == "done")
        moving = sum(1 for rung in rungs if rung["x"]["vibe_status"] in ("running", "review"))
        return f"plan: {len(rungs)} features, {done} done, {moving} in hand, {len(rungs) - done - moving} open"

    def _sources(self) -> list[dict[str, Any]]:
        entry = links.link("file", str(self.descriptor), self.roots)
        entry.update({"role": "descriptor", "sha256": file_sha256(self.descriptor)})
        rows = [entry]
        for feature_id in sorted(self.items):
            path = Path(self.items[feature_id].absolute_path)
            note = links.link("file", str(path), self.roots)
            note.update({"role": f"feature {feature_id}", "sha256": file_sha256(path)})
            rows.append(note)
        return rows

    def _warnings(self) -> list[str]:
        warnings = []
        if not self.declared_axes:
            warnings.append(f"{self.descriptor.name} declares no vibetracks.roadmap.axes, so every feature sits on "
                            "one 'other' axis")
        if self.archived:
            warnings.append(f"{len(self.archived)} archived feature(s) not drawn: "
                            + ", ".join(sorted(item.id for item in self.archived)))
        tracked = set(self.repo.tracked_files())
        untracked = sorted(feature_id for feature_id, item in self.items.items()
                           if Path(item.absolute_path).relative_to(self.repo.root).as_posix() not in tracked)
        if untracked:
            warnings.append(f"untracked feature note(s), with no history in git: {', '.join(untracked)}")
        for problem in self.project.problems:
            warnings.append(f"{problem.get('path')}: {problem.get('error')} (skipped)")
        return warnings + self.warnings

    # ------------------------------------------------------------ one rung
    def _rung(self, feature_id: str) -> dict[str, Any]:
        item = self.items[feature_id]
        frontmatter = self.frontmatter[feature_id]
        note = Path(item.absolute_path)
        claimed = CLAIM_OF_STATUS.get(item.status, "missing")
        book = EvidenceBook()
        id_line = proof.source_link(note, self.roots, "vibe-id:", "")
        status_line = proof.source_link(note, self.roots, "vibe-status:", "")
        criteria: list[dict[str, Any]] = []
        if self.needs[feature_id]:
            criteria.append(self._prerequisites_criterion(feature_id, id_line))
        commits = string_list(frontmatter.get(COMMITS_KEY))
        if claimed == "done" and commits:
            criteria.append(self._landed_criterion(feature_id, commits, book, proof.source_link(note, self.roots, f"{COMMITS_KEY}:", "")))
        elif commits:
            # Work in hand that names commits: shown, not judged (the note does not claim it done).
            for commit in commits:
                book.add(self._commit_item(feature_id, commit), key=("commit", commit))
        for raw in [item.review_packet, *string_list(frontmatter.get(self.project.properties["evidence"]))]:
            self._context_file(book, raw, note)
        status, reason = model.derive_status(claimed, criteria)
        open_parents = [parent for parent in self.needs[feature_id]
                        if not model.satisfied(self.derived.get(parent, {}).get("status"))]
        rung = {
            "id": feature_id, "axis": self.axis_of[feature_id], "title": item.title, "adds": None, "order": 0, "wave": None,
            "depends_on": list(self.needs[feature_id]), "alias_of": None, "status": status, "claimed_status": claimed,
            "status_reason": reason, "claimed_by": {"source": status_line, "event": None},
            "frontier": claimed != "done" and not open_parents and item.status in SCHEDULED,
            "done_when": {"rule": "all" if criteria else "none", "text": item.description, "source": id_line},
            "criteria": criteria, "support": None, "evidence": book.items, "history": [], "blockers": [], "kpis": [],
            "notes": [], "x": {"vibe_status": item.status, "areas": list(item.areas), "priority": item.priority,
                               "path": item.path, "origin": string_list(frontmatter.get(ORIGIN_KEY)),
                               "blocked_by": open_parents},
        }
        self.derived[feature_id] = proof.finish_rung(rung, book)
        return self.derived[feature_id]

    def _prerequisites_criterion(self, feature_id: str, source: dict[str, Any]) -> dict[str, Any]:
        statuses = {parent: self.derived[parent]["status"] for parent in self.needs[feature_id]}
        verdict, strength, reason = model.prerequisites_verdict(statuses)
        targets = [proof.rung_target(parent, status, True) for parent, status in statuses.items()]
        return proof.criterion(criterion_id=f"{feature_id}#prerequisites", kind="prerequisites", method=None,
                               title="every prerequisite done", text="every prerequisite is green or done",
                               source=source, targets=targets, verdict=verdict, strength=strength, reason=reason,
                               evidence=[])

    def _commit_item(self, feature_id: str, commit: str) -> dict[str, Any]:
        full = self.repo.full_sha(commit)
        return {"kind": "commit", "label": f"{feature_id} @ {commit[:8]}", "path": None, "base": None, "abs": None,
                "line": None, "end_line": None, "exists": full is not None,
                "why_unresolved": None if full else "commit not found in this repository",
                "result": None, "strength": "record" if full else "claim", "commit": full or commit, "ts": None,
                "origin": "ladder", "facts": {"feature": feature_id}, "as_cited": commit, "event": None,
                "commit_source": "citation"}

    def _landed_criterion(self, feature_id: str, commits: list[str], book: EvidenceBook,
                          source: dict[str, Any]) -> dict[str, Any]:
        targets = []
        for commit in commits:
            item = self._commit_item(feature_id, commit)
            judgement = self.evaluator.judge_commit(item)
            item["result"] = judgement.result
            evidence_id = book.add(item, key=("commit", commit))
            target = {"kind": "package", "label": commit[:8], "path": None, "base": None, "abs": None, "line": None,
                      "end_line": None, "exists": True, "why_unresolved": None}
            targets.append(proof.target_entry(target, judgement, [evidence_id]))
        return proof.reduce(f"{feature_id}#landed", "package", "inspection", "landed in this history",
                            f"{COMMITS_KEY}: {', '.join(commits)}", source, targets, empty_reason="no commit named")

    def _context_file(self, book: EvidenceBook, raw: str | None, note: Path) -> None:
        if not raw or "://" in str(raw):
            return
        candidate = Path(str(raw)).expanduser()
        if not candidate.is_absolute():
            local = (note.parent / candidate).resolve()
            candidate = local if local.exists() else (self.project.root / candidate).resolve()
        # WHY only file/image/video: a context item is shown, never judged, so it must not read as a gate or an audit.
        kind = links.classify(str(candidate))
        target = links.link(kind if kind in ("image", "video") else "file", str(candidate), self.roots)
        book.add({**target, "result": None, "strength": "claim", "commit": None, "ts": None, "origin": "ladder",
                  "facts": {}, "as_cited": str(raw), "event": None, "commit_source": None},
                 key=("file", str(candidate)))


__all__ = ["LOOP_ID", "project_features", "roadmap_axes"]
