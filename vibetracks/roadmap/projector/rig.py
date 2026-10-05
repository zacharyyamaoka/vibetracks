"""project_rig: bam-roadmap/1 from the rig loop's own files, read-only.

Reads (and never writes) ``ladder.json`` (rig-ladder/1), ``loop_events.jsonl``, ``triage.json`` and
``loop-status.json`` in the rig loop's directory, every log or audit their events cite, and git.

The rig loop's own rule (``bam_rig_loop.state.recompute_rung``) is that a rung with packages is
green when every package has landed with a commit. ``done_when`` keeps that rule and adds what
the packages themselves declare. Each package gives its rung:

- ``package``: it landed at a commit in this history (git is asked, ``evaluate.Evaluator.judge_commit``);
- ``test``: its ``acceptance_paths`` passed, with nothing in their freshness scope changed since
  (the test, its package and declared dependencies, its import closure, and the package's
  ``write_set``; ``scope.CodeIndex``);
- ``stated``: its ``acceptance`` sentence, unknown until the ladder says the paths are that
  sentence (``acceptance_is_tests: true``, the declaration this format proposes; Codex F11).

A package's ``depends_on`` is build order, not a prerequisite: the ladder declares no rung
prerequisites, and lifted to rungs the package graph is cyclic (TW1 needs H1 in RL1, RL1's H2 needs
R2 in TW1). So rig rungs have an empty ``depends_on``; the relation is kept as ``edges`` of kind
``package`` and as ``x.needs``. A rung with no packages is hand-managed by the loop, so it declares
nothing to check.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import links, model, proof
from .evaluate import Evaluator
from .files import ProjectionError, file_sha256, read_json, read_jsonl
from .gitinfo import Repo
from .links import EvidenceBook, Roots
from .scope import CodeIndex


def project_rig(rig_loop_dir: Path, *, now: str, head: str | None = None) -> dict[str, Any]:
    """bam-roadmap/1 for the rig loop, judged at ``head`` (default: the checkout's HEAD)."""

    rig_dir = Path(rig_loop_dir).resolve()
    ladder = read_json(rig_dir / "ladder.json")
    if ladder.get("schema") != "rig-ladder/1":
        raise ProjectionError(f"{rig_dir / 'ladder.json'} is {ladder.get('schema')!r}, not rig-ladder/1")
    repo = Repo(rig_dir, head)
    if not repo.available:
        raise ProjectionError(f"{rig_dir} is not inside a git checkout")
    roots = Roots(repo=repo.root, repo_aliases=repo.other_checkouts())
    triage_path = rig_dir / "triage.json"
    status_path = rig_dir / "loop-status.json"
    return _RigProjector(
        rig_dir=rig_dir, ladder=ladder, events=read_jsonl(rig_dir / "loop_events.jsonl", numbered=True),
        triage=read_json(triage_path) if triage_path.exists() else {"items": []},
        loop_status=read_json(status_path) if status_path.exists() else None, repo=repo, roots=roots,
    ).document(now)


class _RigProjector:
    def __init__(self, *, rig_dir: Path, ladder: Mapping[str, Any], events: list[dict], triage: Mapping[str, Any],
                 loop_status: Mapping[str, Any] | None, repo: Repo, roots: Roots) -> None:
        self.rig_dir, self.ladder, self.triage = rig_dir, ladder, triage
        self.events = proof.EventLog(rig_dir / "loop_events.jsonl", roots, rows=events)
        self.loop_status, self.repo, self.roots = loop_status, repo, roots
        self.ladder_path = rig_dir / "ladder.json"
        self.packages = {package["id"]: package for package in ladder.get("packages") or []}
        self.package_index = {package["id"]: index for index, package in enumerate(ladder.get("packages") or [])}
        self.rung_of = {package["id"]: package.get("rung") for package in ladder.get("packages") or []}
        self.evaluator = Evaluator(repo, roots)
        self.code = CodeIndex(repo)
        acceptance = [path for package in ladder.get("packages") or [] for path in package.get("acceptance_paths") or []]
        self.test_index = proof.TestIndex(roots, acceptance, self.events)
        for event in events:
            self.test_index.add_event(event, origin="event")
        self.landed_events = {str(event.get("subject")): event for event in events
                              if event.get("kind") == "lane_status" and event.get("status") == "landed"}
        self.layout: dict[str, tuple[Mapping[str, Any], int, Mapping[str, Any], int]] = {}
        for axis_index, axis in enumerate(ladder.get("axes") or []):
            for rung_index, rung in enumerate(axis.get("rungs") or []):
                self.layout[rung["id"]] = (axis, axis_index, rung, rung_index)
        self.derived: dict[str, dict[str, Any]] = {}

    def needs(self, rung: Mapping[str, Any]) -> list[str]:
        """The rungs a rung's packages need landed first (build order, never a prerequisite)."""

        return links.unique(self.rung_of[dependency] for package_id in rung.get("packages") or []
                            for dependency in (self.packages.get(package_id) or {}).get("depends_on") or []
                            if self.rung_of.get(dependency) and self.rung_of.get(dependency) != rung["id"])

    def document(self, now: str) -> dict[str, Any]:
        for rung_id in self.layout:
            self._rung(rung_id)
        axes = [{"id": axis["id"], "title": axis["title"], "order": axis_index}
                for axis_index, axis in enumerate(self.ladder.get("axes") or [])]
        rungs = [self.derived[rung_id] for rung_id in self.layout]
        edges = []
        seen: dict[tuple[str, str], list[str]] = {}
        for package in self.ladder.get("packages") or []:
            for dependency in package.get("depends_on") or []:
                source, target = self.rung_of.get(dependency), package.get("rung")
                if source and target and source != target:
                    seen.setdefault((source, target), []).append(f"{package['id']} needs {dependency}")
        for (source, target), reasons in seen.items():
            edges.append({"from": source, "to": target, "kind": "package", "via": "; ".join(reasons)})
        status = self.loop_status or {}
        return {
            "schema": model.SCHEMA_ID,
            "loop": str(self.ladder.get("loop") or "rig"),
            "title": "Rig loop",
            "generated_at": now,
            "as_of": {"head": self.repo.head, "branch": self.repo.branch, "context": {}},
            "roots": self.roots.as_dict(),
            "sources": self._sources(),
            "rules": {"proof_strengths": list(model.PROOF_STRENGTHS), "status_rule": "bam_roadmap.model.derive_status",
                      "loop_rules": proof.source_link(self.rig_dir / "ROADMAP.md", self.roots, "Acceptance first", "")},
            "summary": {"wave": (status.get("tick") or {}).get("n"), "phase": (status.get("tick") or {}).get("phase"),
                        "frontier": [row.get("next") for row in status.get("where") or [] if row.get("next")],
                        "milestone": self.ladder.get("milestone"), "links": self.ladder.get("links") or {},
                        "episode": self.ladder.get("episode"), "blockers": self.ladder.get("blockers") or []},
            "counts": proof.counts(rungs),
            "warnings": self._warnings(),
            "axes": axes,
            "where": proof.where_rows(axes, rungs),
            "rungs": rungs,
            "edges": edges,
            "work": self._work(),
            "unresolved": proof.unresolved_list(rungs),
            "scopes": {},
        }

    def _sources(self) -> list[dict[str, Any]]:
        rows = []
        for name, role in (("ladder.json", "ladder"), ("loop_events.jsonl", "loop events"), ("triage.json", "triage"),
                           ("loop-status.json", "loop-status/1 (one screen)")):
            path = self.rig_dir / name
            entry = links.link("file", str(path), self.roots)
            entry.update({"role": role, "sha256": file_sha256(path) if path.is_file() else None})
            rows.append(entry)
        return rows

    def _warnings(self) -> list[str]:
        warnings = []
        listed = {package_id for axis in self.ladder.get("axes") or [] for rung in axis.get("rungs") or []
                  for package_id in rung.get("packages") or []}
        for package_id, rung_id in self.rung_of.items():
            if package_id not in listed:
                warnings.append(f"package {package_id} names rung {rung_id}, but that rung does not list it")
        for rung_id, (_axis, _axis_index, rung, _rung_index) in self.layout.items():
            latest = self.events.latest_status_event(rung_id)
            if latest is not None and rung.get("status") in model.CLAIMED_STATUSES and latest.get("status") != rung.get("status"):
                warnings.append(f"{rung_id}: ladder.json says {rung.get('status')}, its latest status event "
                                f"(loop_events.jsonl line {latest.get('_line')}) says {latest.get('status')}; the lower one governs")
        return warnings

    # ------------------------------------------------------------ one rung
    def _rung(self, rung_id: str) -> dict[str, Any]:
        axis, axis_index, rung, rung_index = self.layout[rung_id]
        book = EvidenceBook()
        ladder_word = rung.get("status") if rung.get("status") in model.CLAIMED_STATUSES else "missing"
        latest = self.events.latest_status_event(rung_id)
        # WHY the lower of the ladder and the latest status event (Codex F02): either is the loop's word, and a
        # later revocation must never be outvoted by a cached green.
        claimed = model.lowest_claim(ladder_word, latest.get("status") if latest else None)
        rung_source = proof.source_link(self.ladder_path, self.roots, f'"id": "{rung_id}"',
                                        f"/axes/{axis_index}/rungs/{rung_index}")
        history = proof.history(book, self.events, rung_id, self.roots)

        criteria: list[dict[str, Any]] = []
        for package_id in rung.get("packages") or []:
            package = self.packages.get(package_id)
            if package is None:
                continue
            source = proof.source_link(self.ladder_path, self.roots, f'"id": "{package_id}"',
                                       f"/packages/{self.package_index[package_id]}")
            criteria.append(self._landed_criterion(package, book, source))
            if package.get("acceptance_paths"):
                criteria.append(self._acceptance_criterion(package, book, source))
            if (package.get("acceptance") or "").strip() and package.get("acceptance_is_tests") is not True:
                criteria.append(proof.stated_criterion(criterion_id=f"{package_id}#stated", text=package.get("acceptance") or "",
                                                       source=source, audit=False))
        for event in self.events.rows:
            if event.get("kind") == "audit" and event.get("subject") in (rung.get("packages") or []):
                for citation in links.cited_paths(event.get("evidence")):
                    proof.evidence_from_citation(book, citation, self.roots, commit=event.get("commit"), ts=event.get("ts"),
                                                 origin="audit_event", event=self.events.ref(event))

        status, reason = model.derive_status(claimed, criteria)
        claimed_by = {"source": rung_source, "event": self.events.ref(latest)}
        rung_entry = {
            "id": rung_id, "axis": axis["id"], "title": rung["title"], "adds": None, "order": rung_index, "wave": None,
            "depends_on": [], "alias_of": None, "status": status, "claimed_status": claimed, "status_reason": reason,
            "claimed_by": claimed_by,
            "frontier": any(row.get("next") == rung_id for row in (self.loop_status or {}).get("where") or []),
            "done_when": {"rule": "all" if criteria else "none",
                          "text": "; ".join(f"{package_id}: {(self.packages.get(package_id) or {}).get('acceptance', '')}"
                                            for package_id in rung.get("packages") or []),
                          "source": rung_source},
            "criteria": criteria, "support": None, "evidence": book.items, "history": history,
            "blockers": proof.blockers_from_triage(self.triage, rung_id, None, self.roots, str(self.rig_dir / "triage.json")),
            "kpis": [], "notes": [],
            "x": {"packages": list(rung.get("packages") or []), "ladder_status": rung.get("status"), "needs": self.needs(rung)},
        }
        self.derived[rung_id] = proof.finish_rung(rung_entry, book)
        return self.derived[rung_id]

    def _landed_criterion(self, package: Mapping[str, Any], book: EvidenceBook, source: dict) -> dict[str, Any]:
        package_id, commit, status = package["id"], package.get("commit"), package.get("status")
        target_link = {"kind": "package", "label": package_id, "path": None, "base": None, "abs": None, "line": None,
                       "end_line": None, "exists": True, "why_unresolved": None}
        if status != "landed":
            judgement, evidence = self.evaluator.judge_package(package, None), []
        else:
            full = self.repo.full_sha(commit) if commit else None
            item = {"kind": "commit", "label": f"{package_id} @ {commit}", "path": None, "base": None, "abs": None,
                    "line": None, "end_line": None, "exists": full is not None,
                    "why_unresolved": None if full else ("no commit recorded" if not commit else "commit not found in this repository"),
                    "result": None, "strength": "record" if full else "claim", "commit": full or commit,
                    "ts": package.get("updated"), "origin": "ladder", "facts": {"package": package_id, "status": status},
                    "as_cited": None, "event": self.events.ref(self.landed_events.get(package_id)), "commit_source": "citation"}
            judgement = self.evaluator.judge_package(package, item if commit else None)
            item["result"] = judgement.result
            evidence = [book.add(item, key=("commit", package_id, commit))] if commit else []
        target = proof.target_entry(target_link, judgement, evidence)
        return proof.reduce(f"{package_id}#landed", "package", "inspection", f"{package_id} landed", package.get("title") or "",
                            source, [target], empty_reason="")

    def _acceptance_criterion(self, package: Mapping[str, Any], book: EvidenceBook, source: dict) -> dict[str, Any]:
        package_id = package["id"]
        targets = list(package.get("acceptance_paths") or [])
        write_set = [path for path in package.get("write_set") or [] if path]
        scopes = {target: self.code.scope(target, write_set) for target in targets}
        return proof.test_criterion(criterion_id=f"{package_id}#acceptance", title=f"{package_id} acceptance passes",
                                    text=package.get("acceptance") or "", source=source, targets=targets, index=self.test_index,
                                    evaluator=self.evaluator, book=book, roots=self.roots, scopes=scopes, context={})

    # ------------------------------------------------------------ packages
    def _work(self) -> list[dict[str, Any]]:
        audits: dict[str, list[Mapping[str, Any]]] = {}
        for event in self.events.rows:
            if event.get("kind") == "audit":
                audits.setdefault(str(event.get("subject")), []).append(event)
        work = []
        for package in self.ladder.get("packages") or []:
            work.append({
                "id": package["id"], "title": package.get("title") or package["id"], "rung": package.get("rung"),
                "kind": package.get("kind") or "lane", "status": package.get("status") or "todo", "commit": package.get("commit"),
                "updated": package.get("updated"), "note": package.get("note") or "", "depends_on": list(package.get("depends_on") or []),
                "acceptance": package.get("acceptance"),
                "targets": [links.link("test", path, self.roots) for path in package.get("acceptance_paths") or []],
                "write_set": list(package.get("write_set") or []),
                "audits": [proof.audit_summary(audit, self.roots, self.events) for audit in audits.get(package["id"], [])],
                "x": {"size": package.get("size"), "needs_hardware": package.get("needs_hardware")},
            })
        return work


__all__ = ["project_rig"]
