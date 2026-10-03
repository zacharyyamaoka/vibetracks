"""Adapter: BAM's two agent loops (kinsim curriculum, 1-DOF rig) -> the ``vibetracks-dashboard/1`` projection.

The only input is a verified snapshot (``dashboard-prior-art/real-data/1``, built 2026-10-03 from the live loop
files; every block names its source) plus the kinsim curriculum it names, for one column the snapshot does not
carry (each rung's ``kpi_weight``). Every number below is read or derived from those two files; a derivation says
how in its ``provenance.derived``. Media (run videos, wave reports, audit write-ups) are resolved to real files on
disk and listed only when the file exists.

Rules this adapter enforces (docs/dashboard/BRIEF.md, facts.md):

- n = 1 per condition reads "unconfirmed · repeat needed", never "regressed" (no status word here says regressed).
- Day floors are descriptive bands, never verdict thresholds.
- Elapsed hours are wall-clock hours, never agent-hours.
- Missing data is ``value: null, measured: false`` with a note saying why, never a zero.

TODO(live): read the loops' own files (status.json, loop_events.jsonl, runs.jsonl, loop-status.json, the
bam_deployments API) instead of the snapshot. The projection's ``source.live`` is false until then.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from ...sources import load_sources

ADAPTER_ID = "bam_loops"
SNAPSHOT_SCHEMA = "dashboard-prior-art/real-data/1"

#: Where the evidence lives on this machine, from vibetracks/sources.py (``run_media_root``, ``reports_media_dir``).
#: WHY machine paths and not snapshot fields: the snapshot names the run bundles (session period names) and the wave
#: report paths, but not the traj_integration_tests output root. Read once at import: each rebuild is a fresh process.
_SOURCES = load_sources()
TRAJ_OUT = Path(_SOURCES["run_media_root"])
AUDITS_DIR = Path(_SOURCES["reports_media_dir"]) / "audits"
BAM_WS_ROOT = Path("/home/bam/bam_ws")

N1_WORD = "unconfirmed · repeat needed"


# --------------------------------------------------------------------------------------------- small helpers


def _day(ts: str | None) -> str | None:
    return ts[:10] if ts else None


def _hours_between(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 3600.0


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-")


def _value(iteration: str, value: float | int | None, *, n: int | None = None, of: float | int | None = None,
           spread: float | None = None, note: str | None = None, measured: bool | None = None) -> dict[str, Any]:
    return {
        "iteration": iteration,
        "value": value,
        "of": of,
        "n": n,
        "spread": spread,
        "measured": (value is not None) if measured is None else measured,
        "note": note,
        "evidence": [],
    }


def _kpi(kpi_id: str, label: str, slot: str, unit: str, direction: str, values: list[dict[str, Any]], *,
         target: dict[str, Any] | None = None, baseline: dict[str, Any] | None = None,
         status: dict[str, str] | None = None, note: str | None = None,
         provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": kpi_id,
        "label": label,
        "slot": slot,
        "unit": unit,
        "direction": direction,
        "target": target,
        "baseline": baseline,
        "values": values,
        "status": status or {"word": "", "tone": "muted"},
        "note": note,
        "aggregate": None,
        "provenance": provenance,
    }


def _latest_two(values: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    measured = [v for v in values if v["measured"] and v["value"] is not None]
    if not measured:
        return None, None
    return measured[-1], (measured[-2] if len(measured) > 1 else None)


def change_status(values: list[dict[str, Any]], direction: str, unit: str, band: float | None = None) -> dict[str, str]:
    """A calm status for a series whose points are comparable (one held condition, one ruler).

    WHY n is checked before the direction: a change between two single readings is not a finding yet; the rule
    (facts.md) is that it reads "unconfirmed · repeat needed" and is never called a regression. ``band`` is a
    descriptive day floor: a change inside it is described as such, never judged.
    """

    latest, previous = _latest_two(values)
    if latest is None:
        return {"word": "not measured", "tone": "muted"}
    if previous is None:
        return {"word": "one reading", "tone": "muted"}
    if band is not None and abs(latest["value"] - previous["value"]) <= band:
        return {"word": "within day band" + (" · n = 1" if min(latest.get("n") or 0, previous.get("n") or 0) <= 1 else ""), "tone": "muted"}
    if (latest.get("n") or 0) <= 1 or (previous.get("n") or 0) <= 1:
        if latest["value"] == previous["value"]:
            return {"word": "unchanged · n = 1", "tone": "muted"}
        return {"word": N1_WORD, "tone": "warn"}
    if latest["value"] == previous["value"]:
        return {"word": "unchanged", "tone": "muted"}
    up = latest["value"] > previous["value"]
    if direction in ("higher", "lower"):
        better = up == (direction == "higher")
        return {"word": "better than previous" if better else "worse than previous", "tone": "ok" if better else "warn"}
    return {"word": "up" if up else "down", "tone": "muted"}


class MediaIndex:
    """id -> {kind, label, path, mime, bytes}; only files that exist get an id.

    WHY ids and not paths in the projection's references: the backend serves exactly the files listed here
    (an allowlist built from the projection itself), so the page can never ask for a path of its choosing.
    """

    def __init__(self, exists: Callable[[Path], bool] = Path.is_file):
        self.items: dict[str, dict[str, Any]] = {}
        self._by_path: dict[str, str] = {}
        self._exists = exists

    def add(self, path: Path | str, kind: str, label: str, *, media_id: str | None = None) -> str | None:
        resolved = Path(path)
        if not resolved.is_absolute() or not self._exists(resolved):
            return None
        key = str(resolved)
        if key in self._by_path:
            return self._by_path[key]
        base = _slug(media_id or f"{resolved.parent.name}.{resolved.name}")
        candidate, counter = base, 2
        while candidate in self.items:
            candidate, counter = f"{base}.{counter}", counter + 1
        mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if resolved.suffix == ".md":
            mime = "text/plain"
        try:
            size = resolved.stat().st_size
        except OSError:
            size = None
        self.items[candidate] = {"id": candidate, "kind": kind, "label": label, "path": key, "mime": mime, "bytes": size}
        self._by_path[key] = candidate
        return candidate

    def ref(self, media_id: str | None) -> list[dict[str, str]]:
        if media_id is None:
            return []
        item = self.items[media_id]
        return [{"id": media_id, "kind": item["kind"], "label": item["label"]}]


class AuditFiles:
    """Audit write-ups under reports/media/audits, matched to a subject by exact file name pattern only."""

    def __init__(self, directory: Path = AUDITS_DIR):
        try:
            self.names = sorted(p.name for p in directory.iterdir() if p.suffix == ".md")
        except OSError:
            self.names = []
        self.directory = directory

    def kinsim(self, subject: str) -> list[Path]:
        # 2026-10-02-w3-w3-fix-w1-r2.md, 2026-10-02-w3-pin-move-s2.md, 2026-10-01-w1-rb0-climb-codex-report.md
        pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-(?:w\d-)?" + re.escape(subject) + r"(?:-r\d+|-codex-report)?\.md$")
        return [self.directory / n for n in self.names if pattern.match(n) and not n.endswith("-prompt.md")]

    def rig(self, subject: str, max_tick: int) -> list[Path]:
        # 2026-10-02-rig-tick1-r7a-build.md, 2026-10-02-rig-tick2-w0b-acceptance.md
        pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-rig-tick(\d+)-" + re.escape(subject.lower()) + r"(?:-r\d+)?-(?:build|acceptance)\.md$")
        found = []
        for name in self.names:
            match = pattern.match(name)
            if match and int(match.group(1)) <= max_tick:
                found.append(self.directory / name)
        return found


class Evidence:
    """Evidence items of one track, by iteration and by KPI."""

    def __init__(self) -> None:
        self.by_iteration: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.by_kpi: dict[str, list[str]] = defaultdict(list)
        self._ids: set[str] = set()

    def add(self, iteration: str, kind: str, title: str, *, item_id: str | None = None, when: str | None = None,
            metrics: dict[str, Any] | None = None, status: str | None = None, media: list[dict[str, str]] | None = None,
            links: list[dict[str, Any]] | None = None, kpis: list[str] = (), note: str | None = None) -> str:
        base = _slug(item_id or f"{iteration}-{kind}-{title}")[:96]
        candidate, counter = base, 2
        while candidate in self._ids:
            candidate, counter = f"{base}-{counter}", counter + 1
        self._ids.add(candidate)
        self.by_iteration[iteration].append({
            "id": candidate,
            "iteration": iteration,
            "kind": kind,
            "title": title,
            "when": when,
            "metrics": metrics or {},
            "status": status,
            "media": media or [],
            "links": links or [],
            "note": note,
        })
        for kpi_id in kpis:
            self.by_kpi[kpi_id].append(candidate)
        return candidate

    def attach(self, kpis: list[dict[str, Any]]) -> dict[str, Any]:
        """Fill each value's ``evidence`` with the items of that KPI in that iteration, and return the block."""

        iteration_of = {item["id"]: it for it, items in self.by_iteration.items() for item in items}
        for kpi in kpis:
            ids = self.by_kpi.get(kpi["id"], [])
            for value in kpi["values"]:
                value["evidence"] = [i for i in ids if iteration_of.get(i) == value["iteration"]]
        return {"by_iteration": dict(self.by_iteration), "by_kpi": dict(self.by_kpi)}


# --------------------------------------------------------------------------------------------- the adapter


class BamLoopsAdapter:
    def __init__(self, snapshot: dict[str, Any], curriculum: dict[str, Any] | None, *, snapshot_path: str,
                 curriculum_path: str | None, media: MediaIndex | None = None, audits: AuditFiles | None = None,
                 traj_out: Path = TRAJ_OUT):
        if snapshot.get("schema") != SNAPSHOT_SCHEMA:
            raise ValueError(f"snapshot schema {snapshot.get('schema')!r}, expected {SNAPSHOT_SCHEMA!r}")
        self.s = snapshot
        self.curriculum = curriculum
        self.snapshot_path = snapshot_path
        self.curriculum_path = curriculum_path
        self.media = media or MediaIndex()
        self.audits = audits or AuditFiles()
        self.traj_out = traj_out
        self.aliases: dict[str, str] = snapshot.get("path_aliases", {})
        self.as_of = _day(snapshot.get("generated_at")) or date.today().isoformat()

    # ---- provenance
    def expand(self, text: str) -> str:
        for alias, path in sorted(self.aliases.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(alias, path)
        return text

    def prov(self, pointer: str, source: str | None = None, derived: str | None = None) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot_path,
            "pointer": pointer,
            "source": self.expand(source) if source else None,
            "derived": derived,
        }

    # ---- tracks
    def tracks(self) -> list[dict[str, Any]]:
        rig = self.rig_track()
        deployments = [self.deployment_track(i, dep) for i, dep in enumerate(self.s["rig"]["deployments"])]
        return [self.kinsim_track(), rig, *deployments]

    # ================================================================ kinsim
    def kinsim_track(self) -> dict[str, Any]:
        k = self.s["kinsim"]
        prov = k["provenance"]
        waves = k["waves"]
        ev = Evidence()
        status = k["status"]

        rungs = [r for axis in k["axes"] for r in axis["rungs"]]
        done = [r["id"] for r in rungs if r["status"] == "done"]
        green_by_wave: dict[int, list[str]] = defaultdict(list)
        for r in rungs:
            if r["status"] == "green" and r.get("green"):
                green_by_wave[int(r["green"]["wave"])].append(r["id"])
        n_rungs = int(k["n_rungs"])

        # ---- iterations: the start (freeze) + one per wave
        iterations = [{
            "id": "start",
            "label": "Start",
            "date": "2026-09-30",
            "marker": f"freeze 89ece43f · {len(done)} rungs already done",
            "provenance": self.prov("/kinsim/waves/0/started_actual", prov["events"],
                                    "date and freeze commit from waves[0].started_actual; done rungs from axes[].rungs[] status 'done'"),
        }]
        for i, w in enumerate(waves):
            parts = [f"wave closed: {w['packages_landed_of_total']} landed"]
            parked = sum(1 for lane in w["lanes"] if lane["status"] == "parked")
            if parked:
                parts.append(f"{parked} parked")
            for note in w.get("notes", []):
                if note.startswith("pin_move:"):
                    parts.append(f"ruler pinned {note.split(':')[1]}")
                if note.startswith("loop_paused:"):
                    parts.append(f"loop paused ({note.split(':')[1]})")
            parts.append(f"+{len(w['rungs_turned_green'])} rungs")
            iterations.append({
                "id": f"W{w['n']}",
                "label": f"W{w['n']}",
                "date": _day(w["ended"]),
                "marker": " · ".join(parts),
                "provenance": self.prov(f"/kinsim/waves/{i}", prov["events"],
                                        "packages_landed_of_total, lanes[].status, notes[] and rungs_turned_green[] of the wave"),
            })
        ids = [it["id"] for it in iterations]

        # ---- S1 north star: rungs green or done, burn-up
        cumulative, running = [], len(done)
        cumulative.append(running)
        for w in waves:
            running += len(w["rungs_turned_green"])
            cumulative.append(running)
        assert cumulative[-1] == k["rung_status_counts"]["green"] + k["rung_status_counts"]["done"], "burn-up must end at green + done"
        rungs_green_values = [
            _value(it, v, of=n_rungs, note=("done before wave 1: " + ", ".join(done)) if it == "start" else None)
            for it, v in zip(ids, cumulative)
        ]
        kpis = [_kpi(
            "rungs_green", "Rungs green or done", "S1", "rungs", "higher", rungs_green_values,
            target={"value": n_rungs, "kind": "scope", "label": f"of {n_rungs} rungs"},
            baseline={"iteration": "start", "label": "start 09-30", "value": cumulative[0]},
            status={"word": f"+{cumulative[-1] - cumulative[-2]} in {ids[-1]}", "tone": "ok"},
            note=f"{k['rung_status_counts']['green']} green + {k['rung_status_counts']['done']} done; "
                 f"{k['rung_status_counts']['partial']} partial, {k['rung_status_counts']['missing']} missing. No milestone date recorded.",
            provenance=self.prov("/kinsim/waves/*/rungs_turned_green", prov["events"],
                                 "done rungs at the start, plus each wave's rungs_turned_green, cumulated; ends at rung_status_counts green + done"),
        )]

        # ---- S1 weighted capability (kpi_weight from the curriculum the snapshot names)
        weights = {r["rung_id"]: r.get("kpi_weight") for r in (self.curriculum or {}).get("rungs", [])}
        if weights and all(r["id"] in weights for r in rungs):
            total = sum(int(weights[r["id"]] or 0) for r in rungs)
            per = [sum(int(weights[r] or 0) for r in done)]
            for w in waves:
                per.append(per[-1] + sum(int(weights[r] or 0) for r in green_by_wave.get(int(w["n"]), [])))
            weighted_values = [_value(it, v, of=total) for it, v in zip(ids, per)]
            weighted_values[0]["note"] = "the done rungs carry kpi_weight 0"
            kpis.append(_kpi(
                "weighted_capability", "Weighted capability", "S1", "points", "higher", weighted_values,
                target={"value": total, "kind": "scope", "label": f"of {total} points"},
                baseline={"iteration": "start", "label": "start 09-30", "value": per[0]},
                status={"word": f"{round(100 * per[-1] / total)} % of scope", "tone": "muted"},
                note="Rungs green or done, each weighted by its curriculum kpi_weight.",
                provenance=self.prov("/kinsim/axes/*/rungs/*/green/wave", prov["curriculum"],
                                     f"sum of curriculum.json rungs[].kpi_weight ({self.curriculum_path}) over rungs green by each wave"),
            ))

        # ---- S2 frontier gate: BT1 feasible under ruler a2-v2
        judged = k["judged_runs"]
        bt1 = [r for r in judged if r["rung"] == "BT1"]
        bt1_values = []
        for it in ids:
            wave_n = None if it == "start" else int(it[1:])
            runs = [r for r in bt1 if r["wave"] == wave_n]
            if runs:
                last = runs[-1]
                bt1_values.append(_value(it, round(100 * last["feasible"] / last["presented"], 1), n=len(runs),
                                         note=f"{last['feasible']}/{last['presented']} episodes feasible, belt {last['belt_m_s']} m/s, {last['tier']} corpus"))
            else:
                bt1_values.append(_value(it, None, note="no BT1 reading under ruler a2-v2 (pinned in W3)"))
        kpis.append(_kpi(
            "bt1_feasible", "Frontier gate · BT1 feasible", "S2", "%", "higher", bt1_values,
            target={"value": 100, "kind": "gate", "label": "gate 100 % feasible"},
            baseline=None,
            status={"word": "below gate · single reading", "tone": "muted"},
            note=f"BT1 is the only frontier rung with a reading under ruler {status['ruler_id']}. "
                 f"Frontier: {', '.join(status['frontier'])}. {status['stuck']['detail']}.",
            provenance=self.prov("/kinsim/judged_runs", prov["ledger"], "feasible / presented of the BT1 ledger row"),
        ))

        # ---- S3 guardrail: RB0 feasible, only readings that count toward the gate
        history = k["rb0_feasible_history"]
        rb0_values = []
        for it in ids:
            wave_n = None if it == "start" else int(it[1:])
            counted = [h for h in history if h["wave"] == wave_n and h["counts_toward_gate"]]
            exploratory = [h for h in history if h["wave"] == wave_n and not h["counts_toward_gate"]]
            if counted:
                feasible = sum(h["feasible"] for h in counted)
                presented = sum(h["presented"] for h in counted)
                rb0_values.append(_value(it, round(100 * feasible / presented, 1), n=len(counted),
                                         note=", ".join(f"{h['feasible']}/{h['presented']}" for h in counted) + " (regression ×2 + promotion)"))
            else:
                note = "no reading that counts toward the gate"
                if exploratory:
                    note += "; exploratory only: " + "; ".join(f"{h['label']} {h['feasible']}/{h['presented']}" for h in exploratory)
                rb0_values.append(_value(it, None, note=note))
        kpis.append(_kpi(
            "rb0_feasible", "Guardrail · RB0 feasible", "S3", "%", "higher", rb0_values,
            target={"value": 100, "kind": "gate", "label": "gate 100 % feasible"},
            baseline=None,
            status={"word": "holding · 3 readings", "tone": "ok"},
            note="Readings that count toward the gate only (ruler a2-v2). Earlier exploratory readings, under ruler a2-v1 "
                 "or on unmerged lanes, are listed in the evidence and never plotted.",
            provenance=self.prov("/kinsim/rb0_feasible_history", prov["ledger"], "sum of counts_toward_gate readings per wave"),
        ))

        # ---- S3 fast gate runs
        gate_values = [_value("start", None, note="no wave yet")]
        for w in waves:
            runs = w["gate_runs"]
            gate_values.append(_value(f"W{w['n']}", sum(1 for g in runs if g == "pass"), of=len(runs), n=len(runs)))
        kpis.append(_kpi(
            "gate_runs", "Fast gate runs passed", "S3", "runs", "info", gate_values,
            status={"word": f"{gate_values[-1]['value']} of {gate_values[-1]['of']} passed", "tone": "muted"},
            note="Every fast-gate run of the wave, a failed one included; the wave closes on a pass.",
            provenance=self.prov("/kinsim/waves/*/gate_runs", prov["events"], "count of gate_run events per wave"),
        ))

        # ---- S4 delivery: packages landed, rungs moved
        landed_values = [_value("start", None, note="no wave yet")]
        for w in waves:
            landed, total = (int(x) for x in w["packages_landed_of_total"].split("/"))
            landed_values.append(_value(f"W{w['n']}", landed, of=total))
        kpis.append(_kpi(
            "packages_landed", "Packages landed", "S4", "packages", "higher", landed_values,
            status={"word": f"{landed_values[-1]['value']} of {landed_values[-1]['of']} landed", "tone": "muted"},
            note="Barriers and lanes planned for the wave that landed; packages_landed_of_total is authoritative "
                 "(waves[].lanes lists only packages with their own lane_status row).",
            provenance=self.prov("/kinsim/waves/*/packages_landed_of_total", prov["roadmap"]),
        ))
        moved_values = [_value("start", None, note="no wave yet")] + [
            _value(f"W{w['n']}", len(w["rungs_turned_green"]), note=", ".join(w["rungs_turned_green"]) or "no rung advanced")
            for w in waves
        ]
        kpis.append(_kpi(
            "rungs_moved", "Rungs moved per wave", "S4", "rungs", "higher", moved_values,
            status={"word": f"{moved_values[-1]['value']} in {ids[-1]}", "tone": "muted"},
            note="Rate, beside the burn-up's level. A wave that moves nothing is allowed three times in a row by the stop rule.",
            provenance=self.prov("/kinsim/waves/*/rungs_turned_green", prov["events"]),
        ))

        # ---- S5 evidence trust: judged runs, audits
        judged_values = [_value("start", None, note="no wave yet")]
        for w in waves:
            judged_values.append(_value(f"W{w['n']}", sum(1 for r in judged if r["wave"] == w["n"]),
                                        note="ledgered judged runs (runs.jsonl)"))
        kpis.append(_kpi(
            "judged_runs", "Judged runs ledgered", "S5", "runs", "count", judged_values,
            status={"word": f"{judged_values[-1]['value']} in {ids[-1]}", "tone": "muted"},
            note=f"Rows in the run ledger; the ledger began in W3 ({status['ledger_rows_seen']} rows, VOID 0).",
            provenance=self.prov("/kinsim/judged_runs", prov["ledger"], "ledger rows per wave"),
        ))
        for verdict, label in (("fail", "Codex audits · fail"), ("pass", "Codex audits · pass")):
            vals = [_value("start", None, note="no wave yet")]
            for w in waves:
                counts = Counter(a["verdict"] for a in w["audits"])
                vals.append(_value(f"W{w['n']}", counts.get(verdict, 0), of=len(w["audits"]),
                                   note=f"{counts.get('not_run', 0)} not run" if counts.get("not_run") else None))
            kpis.append(_kpi(
                f"audit_{verdict}", label, "S5", "audits", "info", vals,
                status={"word": f"{vals[-1]['value']} in {ids[-1]}", "tone": "muted"},
                note="A fail is the audit doing its job: findings came back and were fixed or parked. 'of' counts every audit row of the wave.",
                provenance=self.prov("/kinsim/waves/*/audits", prov["events"], "audit events per wave by verdict"),
            ))

        # ---- S6 cost: elapsed hours (wall clock)
        elapsed_values = [_value("start", None, note="no wave yet")]
        for w in waves:
            hours = w.get("hours_recorded")
            elapsed_values.append(_value(f"W{w['n']}", hours, note=None if hours is not None else "elapsed hours not recorded"))
        kpis.append(_kpi(
            "elapsed_h", "Elapsed hours per wave", "S6", "h elapsed", "lower", elapsed_values,
            status={"word": f"{elapsed_values[-1]['value']} h wall clock", "tone": "muted"},
            note="Elapsed wall-clock hours, not agent-hours: agent and compute cost are unmetered.",
            provenance=self.prov("/kinsim/waves/*/hours_recorded", prov["roadmap"]),
        ))

        # ---- S7 needs you & health: triage opened, blocking questions, disk
        opened = k["triage"]["opened_by_wave"]
        kpis.append(_kpi(
            "triage_opened", "Questions opened", "S7", "questions", "count",
            [_value("start", None, note="no wave yet")] + [_value(f"W{w['n']}", opened.get(str(w["n"]))) for w in waves],
            status={"word": f"{k['triage']['counts']['open']} open · {k['triage']['counts']['defaulted']} defaulted", "tone": "muted"},
            note="Triage items opened in each wave. Answer rows on 10-03 14:54 were dashboard click-tests, not decisions.",
            provenance=self.prov("/kinsim/triage/opened_by_wave", prov["triage"]),
        ))
        blocking = [it for it in k["triage"]["open_items"] if it["blocks"]]
        kpis.append(_kpi(
            "blocking_questions", "Questions blocking a rung", "S7", "questions", "lower",
            [_value(it, None, note="not recorded per wave") for it in ids[:-1]] + [_value(ids[-1], len(blocking))],
            status={"word": f"{len(blocking)} blocking", "tone": "warn" if blocking else "muted"},
            note="Only the current count is recorded.",
            provenance=self.prov("/kinsim/status/blocking_triage", prov["triage"]),
        ))
        disk = k["disk_and_pause"]
        disk_values = [_value("start", None, note="not recorded"),
                       _value("W1", disk[0]["df_pct"], note=f"df at the wave 2 preflight, {disk[0]['ts'][:16]} UTC (after W1 closed)"),
                       _value("W2", disk[1]["df_pct"], note=f"df at the wave 3 preflight, {disk[1]['ts'][:16]} UTC (after W2 closed)"),
                       _value("W3", disk[2]["df_pct_actual"], note=f"actual at the pause, {disk[2]['ts'][:16]} UTC (df prints {disk[2]['df_pct_printed']} %)")]
        kpis.append(_kpi(
            "disk_pct", "Disk used on /", "S7", "%", "lower", disk_values,
            target={"value": 91.0, "kind": "limit", "label": "stop line 91.0 % actual (df prints 92 %)"},
            status={"word": "Paused · 0.64 pt under the stop line", "tone": "warn"},
            note="The loop stops before the line; other fleets consume about 2 GiB/h, so wave 4 was not dispatched.",
            provenance=self.prov("/kinsim/disk_and_pause", prov["events"], "preflight df readings and the loop_paused event"),
        ))

        # ---- evidence
        start_note = ev.add("start", "note", "Freeze 89ece43f: the curriculum before wave 1", when="2026-09-30",
                            metrics={"rungs done": len(done), "rungs": n_rungs}, status="done",
                            note="Done before wave 1: " + ", ".join(done), kpis=["rungs_green", "weighted_capability"])
        del start_note
        report_ids = {}
        for i, w in enumerate(waves):
            it = f"W{w['n']}"
            report_path = Path(self.expand(w["report"])) if w.get("report") else None
            report_media = self.media.add(report_path, "html", f"Wave {w['n']} report", media_id=f"kinsim.wave{w['n']}.report") if report_path else None
            report_ids[it] = ev.add(
                it, "report", f"Wave {w['n']} report", item_id=f"{it}-report", when=w["ended"],
                metrics={"packages landed": w["packages_landed_of_total"], "rungs moved": len(w["rungs_turned_green"])},
                status="closed", media=self.media.ref(report_media), note=w.get("summary"),
                kpis=["rungs_green", "weighted_capability", "rungs_moved", "packages_landed", "elapsed_h"],
            )
            if w["rung_changes"]:
                ev.add(it, "note", "Rung status changes", when=w["ended"],
                       metrics={r["rung"]: r["status"] for r in w["rung_changes"]},
                       note="Turned green this wave: " + (", ".join(w["rungs_turned_green"]) or "none"),
                       kpis=["rungs_green", "weighted_capability", "rungs_moved"])
            for lane in w["lanes"]:
                media = [m for p in self.audits.kinsim(lane["id"]) for m in self.media.ref(self.media.add(p, "text", p.name))]
                ev.add(it, "lane", lane["id"], status=lane["status"], media=media, kpis=["packages_landed"])
            for j, audit in enumerate(w["audits"]):
                media = [m for p in self.audits.kinsim(audit["subject"]) for m in self.media.ref(self.media.add(p, "text", p.name))]
                ev.add(it, "audit", audit["subject"], item_id=f"{it}-audit-{j + 1}-{audit['subject']}", status=audit["verdict"],
                       media=media, kpis=[f"audit_{audit['verdict']}"] if audit["verdict"] in ("fail", "pass") else [])
            for j, gate in enumerate(w["gate_runs"]):
                ev.add(it, "gate", f"Fast gate run {j + 1}", item_id=f"{it}-gate-{j + 1}", status=gate, kpis=["gate_runs"])
            for change in w["triage"]:
                ev.add(it, "note", f"Triage {change['ids']}", status=change["status"], kpis=["triage_opened"])
            for intervention in w["interventions"]:
                ev.add(it, "note", f"Intervention: {intervention['subject']}", status=intervention["status"])
            for h in history:
                if h["wave"] == w["n"] and not h["counts_toward_gate"]:
                    ev.add(it, "note", f"RB0 exploratory: {h['label']}", metrics={"feasible": h["feasible"], "presented": h["presented"]},
                           status="does not count toward the gate", note=h.get("primary"), kpis=["rb0_feasible"])
        for run in judged:
            it = f"W{run['wave']}"
            kpi_ids = ["judged_runs"]
            if run["rung"] == "BT1":
                kpi_ids.append("bt1_feasible")
            if run["rung"] == "RB0":
                kpi_ids.append("rb0_feasible")
            ev.add(it, "run", f"{run['rung']} · {run['tier']}" + (f" r{run['repeat_index'] + 1}" if run["tier"] == "regression" else ""),
                   item_id=run["run_id"], when=run["started"],
                   metrics={
                       "feasible": f"{run['feasible']}/{run['presented']}",
                       "feasible %": round(100 * run["feasible_rate"], 1),
                       "belt m/s": run["belt_m_s"],
                       "ppm": run["ppm"],
                       "compute p95 s": run["compute_s_p95"],
                       "recovery": run["recovery"],
                       "deadline misses": run["deadline_miss"],
                       "void": run["void"],
                       "primary failures": run["primary_histogram"] or None,
                       "wall s": run["wall_s"],
                       "git": run["git"],
                       "verdict hash": run["verdict_hash"],
                   },
                   status="ok" if run["feasible_rate"] >= 1.0 else "below gate", kpis=kpi_ids)
        for j, d in enumerate(disk):
            it = ["W1", "W2", "W3"][j]
            ev.add(it, "note", d["event"], when=d["ts"],
                   metrics={"df %": d.get("df_pct", d.get("df_pct_printed")), "actual %": d.get("df_pct_actual"), "free GB": d.get("free_gb")},
                   kpis=["disk_pct"])
        evidence = ev.attach(kpis)

        needs = sorted(k["triage"]["open_items"], key=lambda t: (not t["blocks"], int(t["id"][1:])))
        needs_you = [{
            "id": t["id"],
            "q": t["title"],
            "blocks": t["blocks"],
            "default": None,
            "applies": f"after W{t['default_applies_after_wave']}" if t.get("default_applies_after_wave") else None,
        } for t in needs]

        links = []
        for w in waves:
            media_id = f"kinsim.wave{w['n']}.report"
            if media_id in self.media.items:
                links.append({"label": f"Wave {w['n']} report", "kind": "media", "media": media_id})
        links.append({"label": "Roadmap", "kind": "path", "value": self.expand(prov["roadmap"])})

        return {
            "id": "kinsim",
            "title": "Kinsim curriculum loop",
            "kind": "loop",
            "parent": None,
            "summary": f"Kinematic-sim curriculum: {n_rungs} rungs on {k['n_axes']} capability axes, climbed one wave at a time.",
            "state": {
                "word": "Paused",
                "tone": "warn",
                "detail": f"disk {disk[2]['df_pct_actual']:.2f}% · stop line 91.0%",
                "since": status["generated_at"],
            },
            "iteration": {"unit": "wave", "label": f"wave {status['wave']}"},
            "iterations": iterations,
            "north_star": "rungs_green",
            "kpis": kpis,
            "needs_you": needs_you,
            "evidence": evidence,
            "links": links,
            "provenance": self.prov("/kinsim", prov["status_fold"]),
        }

    # ================================================================ rig loop
    def rig_track(self) -> dict[str, Any]:
        r = self.s["rig"]
        prov = r["provenance"]
        ls = r["loop_status"]
        ticks = {t["n"]: t for t in r["ticks"]}
        current = int(ls["tick"]["n"])
        ids = [f"T{n}" for n in range(current + 1)]
        rate = ls["rate"]["rungs_moved_per_tick"]  # ticks 1..current (ticks_note)
        ev = Evidence()
        n_rungs = sum(len(a["rungs"]) for a in r["ladder_axes"])

        iterations = []
        for n, it in enumerate(ids):
            t = ticks.get(n)
            if t is None:
                moved = rate[n - 1] if 1 <= n <= len(rate) else None
                iterations.append({
                    "id": it, "label": it, "date": None,
                    "marker": f"no event recorded · {moved} rungs (loop-status rate)",
                    "provenance": self.prov("/rig/loop_status/rate/rungs_moved_per_tick", prov["loop_status"], r["ticks_note"]),
                })
                continue
            parts = []
            if t["lanes_landed"]:
                parts.append(f"{len(t['lanes_landed'])} landed")
            if t["rungs_green"]:
                parts.append("green " + ", ".join(t["rungs_green"]))
            if t["ended"] is None and n == current:
                parts.insert(0, "running")
            iterations.append({
                "id": it, "label": it, "date": _day(t["started"]),
                "marker": (t["detail"].split(":")[0] + " · " if n == 0 else "") + " · ".join(parts),
                "provenance": self.prov(f"/rig/ticks/{r['ticks'].index(t)}", prov["events"], t["detail"]),
            })

        # rungs green per tick from the ladder's turned_green.tick
        green_at: Counter = Counter()
        for axis in r["ladder_axes"]:
            for rung in axis["rungs"]:
                if rung.get("turned_green"):
                    green_at[int(rung["turned_green"]["tick"])] += 1
        cumulative, running = [], 0
        for n in range(current + 1):
            running += green_at.get(n, 0)
            cumulative.append(running)
        kpis = [_kpi(
            "rungs_green", "Ladder rungs green", "S1", "rungs", "higher",
            [_value(it, v, of=n_rungs, note=("no event recorded; count from loop-status rate" if ticks.get(n) is None else None))
             for n, (it, v) in enumerate(zip(ids, cumulative))],
            target={"value": n_rungs, "kind": "scope", "label": f"of {n_rungs} rungs"},
            baseline={"iteration": "T0", "label": "bootstrap T0", "value": cumulative[0]},
            status={"word": f"+{cumulative[-1] - cumulative[-2]} in {ids[-1]}", "tone": "ok"},
            note=f"Milestone '{r['milestone']['title']}' due {r['milestone']['due']}; episode stop {r['episode']['stop']}.",
            provenance=self.prov("/rig/ladder_axes/*/rungs/*/turned_green/tick", prov["ladder"], "rungs turned green by tick, cumulated"),
        )]

        # S2 frontier gate: TW2 twin fidelity gap (held-out); readings live in the CAN 12 twin sessions
        can12 = next(d for d in r["deployments"] if d.get("twin_replays"))
        twin = next(kp for kp in can12["kpis"] if kp["key"] == "twin_fidelity_gap")
        sessions = can12["periods"]["session"]["rows"]
        twin_readings = [(sessions[i][0], sessions[i][1], v) for i, v in enumerate(twin["session"]) if v is not None]
        tick1_start = ticks[1]["started"][:16]
        tw2_values = []
        for n, it in enumerate(ids):
            if n == 1:
                (_, v0_t, v0), (_, v1_t, v1) = twin_readings[0], twin_readings[-1]
                tw2_values.append(_value(it, v1, n=15, note=f"V1 {v1}° at 10-02 {v1_t[11:16]}, after V0 {v0}° at {v0_t[11:16]}; both inside tick 1 "
                                                         f"(started {tick1_start[5:].replace('T', ' ')}, TW1 green 23:01)"))
            elif n == current:
                tw2_values.append(_value(it, None, note="no new reading; R3 (TW2) in Codex audit"))
            else:
                tw2_values.append(_value(it, None, note="no reading in this tick" if ticks.get(n) else "no event recorded for this tick"))
        kpis.append(_kpi(
            "tw2_twin_gap", "Frontier gate · TW2 twin gap (held-out)", "S2", "deg", "lower", tw2_values,
            target={"value": 0.8, "kind": "gate", "label": "TW2 gate ≤ 0.8°"},
            baseline={"iteration": "T1", "label": "V0 untuned twin", "value": twin_readings[0][2]},
            status={"word": "under gate · audit running", "tone": "muted"},
            note="Held-out twin fidelity gap of the CAN 12 pendulum twin; V0 = untuned, V1 = R3 two-knob fit round 1. "
                 "TW2 stays 'partial' until the Codex audit closes.",
            provenance=self.prov("/rig/deployments/0/kpis/twin_fidelity_gap", prov["deployments + kpis (day/session)"],
                                 "session values of the twin-V0/V1 sessions; placed in tick 1 by their timestamps"),
        ))

        # S4 delivery
        building = {p["id"] for p in r["packages"] if p["status"] == "building"}
        landed_values = []
        for n, it in enumerate(ids):
            t = ticks.get(n)
            landed_values.append(_value(it, len(t["lanes_landed"]) if t else None,
                                        note=None if t else "no event recorded for this tick"))
        if building:
            landed_values[-1]["note"] = "still building: " + ", ".join(sorted(building))
        kpis.append(_kpi(
            "packages_landed", "Packages landed", "S4", "packages", "higher", landed_values,
            status={"word": f"{len(building)} building", "tone": "muted"},
            provenance=self.prov("/rig/ticks/*/lanes_landed", prov["events"]),
        ))
        moved = [green_at.get(0, 0)] + list(rate)
        kpis.append(_kpi(
            "rungs_moved", "Rungs moved per tick", "S4", "rungs", "higher",
            [_value(it, v) for it, v in zip(ids, moved)],
            status={"word": f"{moved[-1]} in {ids[-1]}", "tone": "muted"},
            note=f"About {round(ls['rate']['hours_spent'] / ls['rate']['product_rungs_moved'], 1)} elapsed h per rung so far.",
            provenance=self.prov("/rig/loop_status/rate/rungs_moved_per_tick", prov["loop_status"], "T0 from the ladder (RL0); T1..T3 from loop-status rate"),
        ))

        # S5 audits
        audit_values = []
        for n, it in enumerate(ids):
            t = ticks.get(n)
            audit_values.append(_value(it, len(t["audits"]) if t else None,
                                       note=("; ".join(f"{a['subject']}: {a['verdict']}" for a in t["audits"]) or None) if t else "no event recorded for this tick"))
        kpis.append(_kpi(
            "audits", "Audits closed", "S5", "audits", "count", audit_values,
            status={"word": "R3 audit running", "tone": "muted"},
            provenance=self.prov("/rig/ticks/*/audits", prov["events"]),
        ))

        # S6 elapsed hours, cumulative
        t0 = ticks[0]
        elapsed_values = [_value("T0", round(_hours_between(t0["started"], t0["ended"]), 2), note="tick 0 start to end")]
        for it in ids[1:-1]:
            elapsed_values.append(_value(it, None, note="tick has no end event"))
        elapsed_values.append(_value(ids[-1], ls["rate"]["hours_spent"], note="hours spent over ticks 0–3 (loop-status)"))
        kpis.append(_kpi(
            "elapsed_h", "Elapsed hours (cumulative)", "S6", "h elapsed", "info", elapsed_values,
            status={"word": f"{ls['rate']['hours_spent']} h wall clock", "tone": "muted"},
            note="Elapsed wall-clock hours, not agent-hours.",
            provenance=self.prov("/rig/loop_status/rate/hours_spent", prov["loop_status"], "T0 from its start/end events"),
        ))

        # S7 health: days since a real hardware row, disk, open questions
        last_real = date.fromisoformat(r["last_real_run"])
        days_values = []
        for n, it in enumerate(ids):
            t = ticks.get(n)
            if t:
                days_values.append(_value(it, (date.fromisoformat(t["started"][:10]) - last_real).days,
                                          note=f"tick start {t['started'][:10]} − last real run {r['last_real_run']}"))
            else:
                days_values.append(_value(it, None, note="no event recorded for this tick"))
        days_values[-1]["value"] = ls["rate"]["days_since_real_row"]
        days_values[-1]["note"] = "loop-status days_since_real_row"
        kpis.append(_kpi(
            "days_since_real", "Days since a real hardware row", "S7", "days", "lower", days_values,
            status={"word": "At risk · no rig attached", "tone": "risk"},
            note=f"Blocker: {r['blockers'][0]}. Stop condition by {r['episode']['stop']}: {r['episode']['stop_condition']}.",
            provenance=self.prov("/rig/last_real_run", prov["loop_status"], "tick start date minus the last real run date"),
        ))
        disk_values = []
        for n, it in enumerate(ids):
            in_tick = [d for d in r["disk_events"] if self._tick_of(d["ts"], ticks, current) == n]
            if in_tick:
                last = in_tick[-1]
                disk_values.append(_value(it, last["df_pct"], note=f"df {last['ts'][5:16].replace('T', ' ')}" + (f" · {last['note']}" if last.get("note") else "")))
            else:
                disk_values.append(_value(it, None, note="no disk reading in this tick"))
        kpis.append(_kpi(
            "disk_pct", "Disk used on /", "S7", "%", "lower", disk_values,
            target={"value": 92, "kind": "limit", "label": "loops halt at 92 % (df)"},
            status={"word": "at the halt line · T12 open", "tone": "warn"},
            note="Code-only ticks continue while T12 is open.",
            provenance=self.prov("/rig/disk_events", prov["triage"]),
        ))
        counts = r["triage"]["counts"]
        kpis.append(_kpi(
            "open_questions", "Open questions", "S7", "questions", "lower",
            [_value(it, None, note="not recorded per tick") for it in ids[:-1]] + [_value(ids[-1], counts["open"])],
            status={"word": f"{counts['open']} open · 3 block BN1", "tone": "warn"},
            note=f"{counts['answered']} answered, {counts['defaulted']} defaulted.",
            provenance=self.prov("/rig/triage/counts", prov["triage"]),
        ))

        # ---- evidence
        pkg = {p["id"]: p for p in r["packages"]}
        for n, it in enumerate(ids):
            t = ticks.get(n)
            if not t:
                ev.add(it, "note", "No event carries this tick", note=r["ticks_note"], kpis=["rungs_green", "rungs_moved"])
                continue
            for lane_id in t["lanes_landed"]:
                p = pkg.get(lane_id, {})
                media = [m for path in self.audits.rig(lane_id, current) for m in self.media.ref(self.media.add(path, "text", path.name))]
                ev.add(it, "lane", f"{lane_id} · {p.get('title', '')}".strip(" ·"), item_id=f"{it}-{lane_id}",
                       metrics={"rung": p.get("rung"), "kind": p.get("kind"), "size": p.get("size"), "commit": p.get("commit")},
                       status=p.get("status", "landed"), media=media, note=p.get("note"), kpis=["packages_landed"])
            for j, audit in enumerate(t["audits"]):
                media = [m for path in self.audits.rig(audit["subject"], current) for m in self.media.ref(self.media.add(path, "text", path.name))]
                ev.add(it, "audit", audit["subject"], item_id=f"{it}-audit-{j + 1}", status=audit["verdict"], media=media, kpis=["audits"])
            if t["rungs_green"]:
                ev.add(it, "note", "Rungs turned green", metrics={rid: "green" for rid in t["rungs_green"]},
                       kpis=["rungs_green", "rungs_moved"])
            for tri in t["triage"]:
                ev.add(it, "note", f"Triage {tri['id']}", status=tri["status"], kpis=["open_questions"])
            for note in t["notes"]:
                ev.add(it, "note", note["subject"], status=note["status"], note=note.get("detail"))
            if n == 1:
                for (session, ts, value), label in zip((twin_readings[0], twin_readings[-1]), ("V0 untuned twin", "V1 two-knob fit, round 1")):
                    ev.add(it, "run", f"Twin {label}", item_id=f"{it}-twin-{session.split('__')[1]}", when=ts,
                           metrics={"held-out gap (°)": value, "replays": 15}, status="under gate" if value <= 0.8 else "above gate",
                           note=f"session {session} (CAN 12 deployment)", kpis=["tw2_twin_gap"])
            if n == 0:
                ev.add(it, "note", t["detail"], when=t["started"], kpis=["elapsed_h"])
        for p in r["packages"]:
            if p["status"] == "building":
                media = [m for path in self.audits.rig(p["id"], current) for m in self.media.ref(self.media.add(path, "text", path.name))]
                ev.add(ids[-1], "lane", f"{p['id']} · {p['title']}", item_id=f"{ids[-1]}-{p['id']}",
                       metrics={"rung": p["rung"], "kind": p["kind"], "size": p["size"]}, status="building", media=media, note=p["note"],
                       kpis=["packages_landed"] + (["tw2_twin_gap"] if p["rung"] == "TW2" else []))
        for d in r["disk_events"]:
            n = self._tick_of(d["ts"], ticks, current)
            if n is not None:
                ev.add(ids[n], "note", f"Disk {d['df_pct']} %", when=d["ts"], metrics={"df %": d["df_pct"], "free GB": d.get("free_gb")},
                       note=d.get("note"), kpis=["disk_pct"])
        evidence = ev.attach(kpis)

        defaults = {n["id"]: n for n in ls["needs_you"]}
        items = [t for t in r["triage"]["items"] if t["status"] == "open"]
        items.sort(key=lambda t: (not t["blocks"], int(t["id"][1:])))
        needs_you = []
        for t in items:
            known = defaults.get(t["id"])
            needs_you.append({
                "id": t["id"],
                "q": t["title"],
                "blocks": t["blocks"],
                "default": known["default"] if known else None,
                "applies": f"after T{t['default_applies_after_tick']}" if t.get("default_applies_after_tick") is not None else None,
            })

        links = [{"label": "Deployments dashboard (Clank)", "kind": "command", "value": ls["links"]["dashboard"]}]
        report = BAM_WS_ROOT / ls["links"]["report"]
        report_id = self.media.add(report, "html", "Deployments dashboard report, 10-02", media_id="rig.deployments-report")
        if report_id:
            links.append({"label": "Deployments report 10-02", "kind": "media", "media": report_id})

        return {
            "id": "rig",
            "title": "1-DOF rig loop",
            "kind": "loop",
            "parent": None,
            "summary": "Sim-first climb toward picking up one piece of real waste with the 1-DOF pendulum rig.",
            "state": {
                "word": "At risk",
                "tone": "risk",
                "detail": f"no rig attached · stop {r['episode']['stop'][5:]}",
                "since": ticks[current]["started"],
            },
            "iteration": {"unit": "tick", "label": f"tick {current}"},
            "iterations": iterations,
            "north_star": "rungs_green",
            "kpis": kpis,
            "needs_you": needs_you,
            "evidence": evidence,
            "links": links,
            "provenance": self.prov("/rig/loop_status", prov["loop_status"]),
        }

    @staticmethod
    def _tick_of(ts: str, ticks: dict[int, dict[str, Any]], current: int) -> int | None:
        """The tick whose window holds ``ts``: from its start to its end event, else to the next recorded tick's start."""

        moment = datetime.fromisoformat(ts)
        known = sorted(ticks)
        for position, n in enumerate(known):
            start = datetime.fromisoformat(ticks[n]["started"])
            if ticks[n]["ended"]:
                end = datetime.fromisoformat(ticks[n]["ended"])
            elif position + 1 < len(known):
                end = datetime.fromisoformat(ticks[known[position + 1]]["started"])
            else:
                end = None
            if start <= moment and (end is None or moment < end or (ticks[n]["ended"] and moment == end)):
                return n
        return None

    # ================================================================ deployments (CAN 12, CAN 16)
    def deployment_track(self, index: int, dep: dict[str, Any]) -> dict[str, Any]:
        prov = self.s["rig"]["provenance"]
        sessions = dep["periods"]["session"]["rows"]
        short = "can12" if "can12" in dep["id"] else "can16" if "can16" in dep["id"] else _slug(dep["id"])
        ev = Evidence()
        pointer = f"/rig/deployments/{index}"

        iterations = []
        for i, (name, start, _end, real, sim, aborted) in enumerate(sessions):
            iterations.append({
                "id": name,
                "label": self._session_label(name, start),
                "date": start[:10],
                "marker": f"{real} real · {sim} sim" + (f" · {aborted} aborted" if aborted else ""),
                "provenance": self.prov(f"{pointer}/periods/session/rows/{i}", prov["deployments + kpis (day/session)"]),
            })
        ids = [it["id"] for it in iterations]
        date_of = {it["id"]: it["date"] for it in iterations}

        def age_days(value: dict[str, Any]) -> int:
            return (date.fromisoformat(self.as_of) - date.fromisoformat(date_of[value["iteration"]])).days

        real_n = [row[3] for row in sessions]
        sim_n = [row[4] for row in sessions]

        slots = {
            "real_tracking_rms": "S1", "real_tracking_p95": "S3", "sim_real_gap": "S5", "feedback_torque_proxy": "S3",
            "floor_real_vs_real": "S5", "real_runs": "S4", "sim_runs": "S4", "aborted_runs": "S3",
            "twin_fidelity_gap": "S2", "twin_tracking_ratio": "S5",
        }
        real_keys = {"real_tracking_rms", "real_tracking_p95", "sim_real_gap", "feedback_torque_proxy"}
        twin_keys = {"twin_fidelity_gap", "twin_tracking_ratio"}
        kpis = []
        for j, kp in enumerate(dep["kpis"]):
            key = kp["key"]
            values = []
            for i, v in enumerate(kp["session"]):
                if key in real_keys:
                    n = real_n[i]
                    note = None if v is not None else ("no real runs in this session" if n == 0 else "not computed for this session")
                elif key in twin_keys:
                    n = sim_n[i] if v is not None else None
                    note = None if v is not None else "no twin replay in this session"
                elif key == "floor_real_vs_real":
                    n = None
                    note = "the floor is computed per day (it pools sessions), not per session"
                else:
                    n = None
                    note = None
                values.append(_value(ids[i], v, n=n, note=note))
            target = None
            if kp.get("target"):
                kind = "gate" if key == "twin_fidelity_gap" else "reference"
                target = {"value": kp["target"]["value_display"], "kind": kind,
                          "label": ("TW2 gate ≤ 0.8°" if key == "twin_fidelity_gap" else "reference 1×, no gate")}
            if key == "floor_real_vs_real" and kp["day"] and kp["day"][0] is not None:
                day = dep["periods"]["day"]["rows"][0][0]
                target = {"band": [0, kp["day"][0]], "kind": "descriptive",
                          "label": f"day floor {kp['day'][0]:.3f}° ({day[5:]}, sessions pooled) · descriptive band, never a verdict"}
            first = next((v for v in values if v["measured"]), None)
            baseline = {"iteration": first["iteration"], "label": f"first reading, {self._session_label(first['iteration'], '')}".rstrip(", "),
                        "value": first["value"]} if first and kp["direction"] in ("lower", "higher") else None
            kpi = _kpi(
                key, kp["label"], slots.get(key, "S5"), self._unit(kp["unit"]), kp["direction"], values,
                target=target, baseline=baseline, status=self._session_status(key, values, dep, age_days=age_days), note=kp.get("empty"),
                provenance=self.prov(f"{pointer}/kpis/{j}", prov["deployments + kpis (day/session)"],
                                     "per-session median over runs (bam_deployments); sessions mix trajectories, so session-to-session "
                                     "changes are not like-for-like"),
            )
            # The day value pools the day's sessions: the deployment's own headline number (CAN 12 real RMS 3.49°, the
            # day median). Counts sum over every day instead: the latest day alone (CAN 12: 0 real on 10-02) is not a total.
            days = dep["periods"]["day"]["rows"]
            day_index = max((i for i, v in enumerate(kp["day"]) if v is not None), default=None)
            if key in ("real_runs", "sim_runs", "aborted_runs"):
                kpi["aggregate"] = {"label": "all days", "value": int(sum(v or 0 for v in kp["day"])), "n": None, "period": None}
            elif day_index is not None:
                day_row = days[day_index]
                kind = " median" if key in real_keys else ""
                kpi["aggregate"] = {
                    "label": f"day {day_row[0][5:]}{kind}",
                    "value": kp["day"][day_index],
                    "n": day_row[3] if key in real_keys else None,
                    "period": day_row[0],
                }
            else:
                kpi["aggregate"] = None
            kpis.append(kpi)

        # held conditions: one trajectory + mode + config read in >= 3 sessions (closed loop only)
        columns = dep["runs_real"]["columns"]
        rows = [dict(zip(columns, row)) for row in dep["runs_real"]["rows"]]
        by_condition: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_condition[(row["trajectory"], row["mode"], row["config"])].append(row)
        held = [(cond, runs) for cond, runs in by_condition.items()
                if cond[1] == "ff_fb" and len({r["session_ix"] for r in runs}) >= 3]
        held.sort(key=lambda item: (-len({r["session_ix"] for r in item[1]}), item[0]))
        held_ids: dict[tuple[str, str, str], str] = {}
        for cond, runs in held[:2]:
            kpi_id = "held_" + _slug(f"{cond[0]}-{cond[1]}-{cond[2]}").replace("-", "_")
            held_ids[cond] = kpi_id
            values = []
            for i, sid in enumerate(ids):
                in_session = [r for r in runs if r["session_ix"] == i]
                if in_session:
                    rms = [r["rms_deg"] for r in in_session]
                    values.append(_value(sid, round(sum(rms) / len(rms), 3), n=len(rms),
                                         spread=round(max(rms) - min(rms), 3) if len(rms) > 1 else None))
                else:
                    values.append(_value(sid, None, note="condition not run in this session"))
            config = "" if cond[2] == "default" else f" · {cond[2]}"
            kpis.append(_kpi(
                kpi_id, f"Held condition · {cond[0]} · {cond[1]}{config}", "S3", "deg", "lower", values,
                target=None,
                baseline=next(({"iteration": v["iteration"], "label": "first reading", "value": v["value"]} for v in values if v["measured"]), None),
                status=change_status(values, "lower", "deg", band=dep["latest_nonnull"].get("floor_real_vs_real")),
                note="Real tracking RMS of one trajectory, mode and config held fixed across sessions: the like-for-like comparison. "
                     "n counts runs of this condition in the session. A change inside the day floor "
                     f"({dep['latest_nonnull'].get('floor_real_vs_real')}°, descriptive) is described, never judged.",
                provenance=self.prov(f"{pointer}/runs_real", prov["runs"], "mean rms_deg of the runs of this condition per session"),
            ))

        # ---- evidence: every real run (videos resolved on disk), twin replays, bundle reports
        video_found = 0
        for row in rows:
            i = row["session_ix"]
            sid = ids[i]
            bundle = self.traj_out / sid
            real_video = self.media.add(bundle / "media" / f"{row['trajectory']}__real__{row['mode']}.mp4", "video",
                                        f"Real · {row['trajectory']} · {row['mode']}", media_id=f"{short}.{sid}.{row['trajectory']}.real.{row['mode']}")
            sim_video = self.media.add(bundle / "media" / f"{row['trajectory']}__sim__{row['mode']}.mp4", "video",
                                       f"Sim · {row['trajectory']} · {row['mode']}", media_id=f"{short}.{sid}.{row['trajectory']}.sim.{row['mode']}")
            video_found += 1 if real_video else 0
            kpi_ids = [k for k in real_keys if any(kp["id"] == k for kp in kpis)]
            cond = (row["trajectory"], row["mode"], row["config"])
            if cond in held_ids:
                kpi_ids.append(held_ids[cond])
            ev.add(sid, "run", f"{row['trajectory']} · {row['mode']}" + (f" · {row['config']}" if row["config"] != "default" else ""),
                   item_id=f"{sid}-{row['trajectory']}-{row['mode']}-{row['t']}", when=f"2026-{row['t']}",
                   metrics={
                       "rms (°)": row["rms_deg"], "p95 (°)": row["p95_deg"], "sim–real gap (°)": row["sim_real_gap_deg"],
                       "feedback torque (N·m)": row["fb_torque_nm"], "limiter ticks": row["limiter_ticks"], "peak temp (°C)": row["peak_temp_c"],
                   },
                   status=row["status"], media=self.media.ref(real_video) + self.media.ref(sim_video),
                   note=None if real_video else ("video flagged but no mp4 found in the bundle" if row["video"] else "no video recorded"),
                   kpis=kpi_ids)
        replays = dep.get("twin_replays") or {}
        if replays:
            cols = replays["columns"]
            for raw in replays["rows"]:
                row = dict(zip(cols, raw))
                sid = next((s for s in ids if f"twin-{row['twin_version']}" in s), None)
                if sid is None:
                    continue
                ev.add(sid, "run", f"Twin {row['twin_version']} replay · {row['replays_trajectory']}",
                       item_id=f"{sid}-{row['replays_trajectory']}", when=f"2026-10-02T{row['time_2026-10-02']}",
                       metrics={"gap aligned (°)": row["replay_gap_aligned_deg"], "gap legacy (°)": row["replay_gap_legacy_deg"],
                                "torque gap (N·m)": row["replay_torque_gap_nm"], "tracking rms (°)": row["tracking_rms_deg"]},
                       status="sim replay", note=replays["note"], kpis=["twin_fidelity_gap", "twin_tracking_ratio", "sim_runs"])
        for i, sid in enumerate(ids):
            report = self.media.add(self.traj_out / sid / "report.html", "html", f"Bundle report · {sid}", media_id=f"{short}.{sid}.report")
            if report:
                ev.add(sid, "report", f"Bundle report · {iterations[i]['label']}", item_id=f"{sid}-report",
                       media=self.media.ref(report), kpis=["real_runs", "sim_runs"])
        evidence = ev.attach(kpis)

        latest_rms = dep["latest_nonnull"]["real_tracking_rms"]
        stale_days = (date.fromisoformat(self.as_of) - date.fromisoformat(dep["latest_period"]["real_tracking_rms"])).days
        if any(kp["status"]["word"] == N1_WORD for kp in kpis):
            unconfirmed = sum(1 for kp in kpis if kp["status"]["word"] == N1_WORD)
            state = {"word": "Repeat needed", "tone": "warn", "detail": f"{unconfirmed} change unconfirmed (n = 1) · {stale_days} days since a real run",
                     "since": dep["latest_period"]["real_tracking_rms"]}
        else:
            state = {"word": "Stale", "tone": "stale", "detail": f"last real run {dep['latest_period']['real_tracking_rms'][5:]} · {stale_days} days",
                     "since": dep["latest_period"]["real_tracking_rms"]}
        floor = dep["latest_nonnull"].get("floor_real_vs_real")
        return {
            "id": short,
            "title": dep["title"].replace("1-DOF pendulum", "Pendulum"),
            "kind": "deployment",
            "parent": "rig",
            "summary": dep["summary"],
            "state": state,
            "iteration": {"unit": "session", "label": iterations[-1]["label"]},
            "iterations": iterations,
            "north_star": "real_tracking_rms",
            "kpis": kpis,
            "needs_you": [],
            "evidence": evidence,
            "links": [{"label": "Day-level floor", "kind": "path", "value": f"{floor:.3f}° (descriptive band)"}] if floor is not None else [],
            "provenance": {**self.prov(pointer, prov["deployments + kpis (day/session)"]),
                           "counts": dep["counts"], "latest_real_rms": latest_rms, "videos_resolved": video_found,
                           "videos_flagged": sum(1 for r in rows if r["video"])},
        }

    @staticmethod
    def _unit(unit: str) -> str:
        return {"deg": "deg", "count": "runs", "×": "×"}.get(unit, unit)

    @staticmethod
    def _session_label(name: str, start: str) -> str:
        """'one_dof_gravity_amplitude_ladder_2026-07-29' -> '07-29 gravity amplitude ladder'; twin sessions keep V0/V1."""

        if "__twin-" in name:
            version = name.split("__twin-")[1].split("__")[0]
            day = name.rsplit("__", 1)[-1]
            return f"{day[5:]} twin {version}"
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
        day = f"{match.group(2)}-{match.group(3)}" if match else (start[5:10] if start else "")
        stem = re.sub(r"_?\d{4}-\d{2}-\d{2}", "", name)
        stem = re.sub(r"^one_dof_", "", stem).replace("_", " ").strip()
        return f"{day} {stem}".strip()

    @staticmethod
    def _session_status(key: str, values: list[dict[str, Any]], dep: dict[str, Any],
                        age_days: Callable[[dict[str, Any]], int] = lambda value: 0) -> dict[str, str]:
        measured = [v for v in values if v["measured"]]
        if key in ("real_runs", "sim_runs", "aborted_runs"):
            return {"word": f"{int(sum(v['value'] or 0 for v in values))} total", "tone": "muted"}
        if key == "floor_real_vs_real":
            return {"word": "day band only", "tone": "muted"}
        if not measured:
            return {"word": "not measured", "tone": "muted"}
        if key == "twin_fidelity_gap":
            last = measured[-1]["value"]
            return {"word": "under gate" if last <= 0.8 else "above gate", "tone": "muted" if last <= 0.8 else "warn"}
        label = BamLoopsAdapter._session_label(measured[-1]["iteration"], "")[:5]
        # WHY 'stale' only past two weeks: a reading from the last few days is current, not an exception.
        return {"word": f"last read {label}", "tone": "stale" if age_days(measured[-1]) > 14 else "muted"}


def build_projection(snapshot: dict[str, Any], curriculum: dict[str, Any] | None, *, snapshot_path: str,
                     curriculum_path: str | None, generated_at: str | None = None,
                     media: MediaIndex | None = None, audits: AuditFiles | None = None,
                     traj_out: Path = TRAJ_OUT) -> dict[str, Any]:
    adapter = BamLoopsAdapter(snapshot, curriculum, snapshot_path=snapshot_path, curriculum_path=curriculum_path,
                              media=media, audits=audits, traj_out=traj_out)
    tracks = adapter.tracks()
    return {
        "schema": "vibetracks-dashboard/1",
        "generated_at": generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "as_of": adapter.as_of,
        "source": {
            "adapter": ADAPTER_ID,
            "kind": "snapshot",
            "live": False,
            "snapshot": snapshot_path,
            "snapshot_generated_at": snapshot.get("generated_at"),
            "curriculum": curriculum_path,
            "todo": "TODO(live): read the loops' own files (kinsim status.json + loop_events.jsonl + runs.jsonl, rig "
                    "loop-status.json + loop_events.jsonl, the bam_deployments API) instead of this snapshot.",
            "units_note": snapshot.get("units_note"),
        },
        "tracks": tracks,
        "media": adapter.media.items,
    }


def load_json(path: str | os.PathLike[str]) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
