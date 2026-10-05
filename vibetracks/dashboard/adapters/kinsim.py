"""Adapter for the Kinematic Sim work track (vibe-id ``kinsim``): the kinematic-simulator curriculum loop, LIVE.

Interface: docs/dashboard/ADAPTERS.md (section ``kinsim``). Discovery: docs/dashboard/track-discovery-2026-10-04.json
key ``scout:kinsim``. Every number below is read from the loop's own files, which the registry note declares:

- ``kinsim_status``  ~/.local/share/bam_curriculum/status.json  the live fold (bam-curriculum-status/1): rungs[],
  frontier[], blocking_triage[], you_are_here[], phase, wave
- ``kinsim_events``  loop_events.jsonl  the wave lifecycle, gate runs, audits, lanes, rung changes, triage, pin moves
- ``kinsim_runs``    runs.jsonl          the judged-run ledger (bam-ledger/1); a row's wave comes from the
  ``judged_run`` event whose subject is its run_id
- ``kinsim_loop_dir`` the loop checkout's src/dev/bam_curriculum: curriculum.json (rungs, gates, kpi_weight, the wave
  each rung is planned for) and triage.json (the questions for Zach)
- ``reports_media_dir`` bam_ws reports/media, listed only to find the wave reports to link (evidence, not liveness)

The iteration is the wave. ``status.json`` is a snapshot, so the per-wave series is refolded here from the events
plus the ledger, and the refold's last wave is checked against ``status.json``; when they disagree the fold wins and
the KPI says so. Missing data is ``value: null`` with a note, never a zero; elapsed hours are wall clock.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .bam_loops import N1_WORD, Evidence, MediaIndex, _kpi, _value
from .base import local_day, local_time, not_reporting, rung, skeleton

TRACK = "kinsim"
#: Every sources.py key this adapter opens, and what it is to the loop (base.py READ_ROLES).
READS = {"kinsim_status": "heartbeat", "kinsim_events": "heartbeat", "kinsim_runs": "heartbeat",
         "kinsim_loop_dir": "heartbeat", "reports_media_dir": "evidence"}

#: Evidence files the media allowlist may serve, by suffix (the backend's servable set).
_MEDIA_KIND = {".html": "html", ".md": "text", ".txt": "text", ".json": "text", ".png": "image", ".jpg": "image",
               ".jpeg": "image", ".webp": "image", ".gif": "image", ".svg": "image", ".mp4": "video", ".webm": "video"}
_PATH = re.compile(r"(?<![\w/.~-])/[^\s;,()'\"]+")
_PACKAGES = re.compile(r"(\d+) of (\d+) packages landed")
# df readings as the loop writes them: "df 89%", "df -h / 79 %", "df -h / prints 91 %". The stop line is defined on
# the printed df figure, so only printed readings are plotted (an "% actual" figure is a different scale).
_DF = re.compile(r"\bdf(?: -h /)?(?: prints)? (\d+(?:\.\d+)?) ?%")
_STOP_LINE = re.compile(r"stops cleanly at (\d+(?:\.\d+)?) ?%")
_PIN = re.compile(r"->\s*(S\d+)\s+([0-9a-f]{6,})")


# --------------------------------------------------------------------------------------------- readers


def _read_json(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _read_jsonl(path: Path | None) -> tuple[list[dict[str, Any]], int]:
    """(rows, unreadable line count); a torn last line from a writer mid-append is skipped, not fatal."""

    if path is None or not path.is_file():
        return [], 0
    rows, bad = [], 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                bad += 1
    return rows, bad


def _ts(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _short_ts(text: str | None) -> str:
    return local_time(text)


def _wave_of(event: dict[str, Any]) -> int | None:
    wave = event.get("wave")
    return wave if isinstance(wave, int) and not isinstance(wave, bool) else None


def _clip(text: Any, limit: int = 160) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _pct(rate: Any) -> float | None:
    return round(100.0 * rate, 1) if isinstance(rate, (int, float)) and not isinstance(rate, bool) else None


def _last_measured(values: list[dict[str, Any]]) -> dict[str, Any] | None:
    measured = [v for v in values if v["measured"]]
    return measured[-1] if measured else None


# --------------------------------------------------------------------------------------------- the adapter


def build_track(work_track: Any, sources: dict[str, str]) -> dict[str, Any]:
    status_path = Path(sources["kinsim_status"]) if sources.get("kinsim_status") else None
    events_path = Path(sources["kinsim_events"]) if sources.get("kinsim_events") else None
    if status_path is None and events_path is None:
        return not_reporting(work_track, "kinsim_status and kinsim_events are not declared in vibe-sources")
    if not (status_path and status_path.is_file()) and not (events_path and events_path.is_file()):
        return not_reporting(work_track, f"no status.json or loop_events.jsonl at {(status_path or events_path).parent}")
    return _Kinsim(work_track, sources).track()


class _Kinsim:
    def __init__(self, work_track: Any, sources: dict[str, str]):
        self.work_track = work_track
        self.paths = {key: Path(value) for key, value in sources.items()}
        self.status_path = self.paths.get("kinsim_status")
        self.events_path = self.paths.get("kinsim_events")
        self.runs_path = self.paths.get("kinsim_runs")
        loop_dir = self.paths.get("kinsim_loop_dir")
        self.curriculum_path = loop_dir / "curriculum.json" if loop_dir else None
        self.triage_path = loop_dir / "triage.json" if loop_dir else None
        self.roadmap_path = loop_dir / "ROADMAP.md" if loop_dir else None
        self.triage_md_path = loop_dir / "TRIAGE.md" if loop_dir else None

        self.status: dict[str, Any] = _read_json(self.status_path) or {}
        self.events, bad_events = _read_jsonl(self.events_path)
        self.runs, bad_runs = _read_jsonl(self.runs_path)
        self.curriculum: dict[str, Any] | None = _read_json(self.curriculum_path)
        self.triage: dict[str, Any] | None = _read_json(self.triage_path)
        self.unreadable = {"loop_events.jsonl": bad_events, "runs.jsonl": bad_runs}
        # Declared (role "evidence"): a new wave report must rerun the adapter to be linked, but reports/media is
        # shared by every fleet, so it never counts toward this loop's liveness (build.py heartbeat_keys).
        self.reports_dir = self.paths.get("reports_media_dir")
        self.media = MediaIndex()
        self.ev = Evidence()

        self.waves = self._waves()
        self.ids = ["start"] + [f"W{n}" for n in self.waves]
        self.run_wave = self._run_waves()
        self.rung_rows = {r["rung_id"]: r for r in self.status.get("rungs", []) if isinstance(r, dict) and r.get("rung_id")}
        self.n_rungs = len((self.curriculum or {}).get("rungs") or []) or len(self.rung_rows) or None

    # ---------------------------------------------------------------- provenance
    def prov(self, path: Path | None, pointer: str | None = None, derived: str | None = None) -> dict[str, Any]:
        return {"snapshot": None, "pointer": pointer, "source": str(path) if path else None, "derived": derived}

    # ---------------------------------------------------------------- waves, phase, runs
    def _waves(self) -> dict[int, dict[str, Any]]:
        waves: dict[int, dict[str, Any]] = {}
        for event in self.events:
            wave = _wave_of(event)
            if wave is None or wave < 1:
                continue
            row = waves.setdefault(wave, {"started": None, "finished": None, "events": []})
            row["events"].append(event)
            if event.get("kind") == "wave_started":
                row["started"] = event
            elif event.get("kind") == "wave_finished":
                row["finished"] = event
        return dict(sorted(waves.items()))

    def phase(self) -> tuple[int, str, dict[str, Any] | None]:
        """(wave, phase, the event that set it): the loop's own rule (bam_curriculum status.wave_and_phase)."""

        wave, phase, since, before_pause = 0, "not_started", None, None
        for event in self.events:
            kind, event_wave = event.get("kind"), _wave_of(event)
            if kind in ("wave_started", "wave_finished") and event_wave is None:
                continue
            if kind == "wave_started":
                wave, phase, since = event_wave, "running", event
            elif kind == "wave_finished":
                wave, phase, since = event_wave, "between_waves", event
            elif kind == "loop_paused" and phase != "paused":
                before_pause, phase, since = phase, "paused", event
            elif kind == "loop_resumed" and phase == "paused":
                phase, since = before_pause or "running", event
            elif kind == "loop_stopped":
                phase, since = "stopped", event
        return wave, phase, since

    def _run_waves(self) -> dict[str, int]:
        """run_id -> wave, through the judged_run event whose subject is the run_id (runs.jsonl has no wave field)."""

        by_event = {e.get("subject"): _wave_of(e) for e in self.events if e.get("kind") == "judged_run" and _wave_of(e)}
        out = {}
        for row in self.runs:
            run_id = row.get("run_id")
            if run_id in by_event:
                out[run_id] = by_event[run_id]
        return out

    def runs_in(self, wave: int) -> list[dict[str, Any]]:
        return [row for row in self.runs if self.run_wave.get(row.get("run_id")) == wave]

    # ---------------------------------------------------------------- the refold: rungs green or done per wave
    def refold(self) -> tuple[dict[str, set[str]] | None, str | None]:
        """{iteration id: rungs green or done at its end}, and a note when the refold disagrees with status.json.

        Rules (the loop's gate kinds, curriculum.json, as bam_curriculum status._judge_rung applies them): a ``none``
        rung stands at its baseline (done only when the baseline says done); ``infra`` turns green by a
        rung_status_changed event; ``std``/``throughput`` by gated ledger rows (``repeats`` regression rows plus one
        promotion row with gate_met) under the ruler in force at the wave's end; ``ratchet`` by a gated promotion row;
        ``same_as`` follows its rung. WHY the ruler filter: a Pin move VOIDs every earlier reading, so readings only
        count under the ruler they were judged by.
        """

        if not self.curriculum or not isinstance(self.curriculum.get("rungs"), list):
            return None, "curriculum.json not readable, so the per-wave history cannot be refolded"
        gates = {r["rung_id"]: (r.get("gate") or {}) for r in self.curriculum["rungs"] if r.get("rung_id")}
        # Done = a gateless (or not yet evented infra) rung whose recorded baseline is "done"; "later" is not done.
        baseline_done = {r["rung_id"] for r in self.curriculum["rungs"] if r.get("rung_id")
                         and (r.get("baseline") or {}).get("status") == "done"
                         and (r.get("gate") or {}).get("kind") in ("none", "infra")}
        history: dict[str, set[str]] = {"start": set(baseline_done)}
        event_status: dict[str, str] = {}
        rows_so_far: list[dict[str, Any]] = []
        for wave, info in self.waves.items():
            for event in info["events"]:
                if event.get("kind") == "rung_status_changed" and event.get("subject"):
                    event_status[event["subject"]] = event.get("status")
            rows_so_far += self.runs_in(wave)
            ruler = next((r["metrics"].get("ruler_sha256") for r in reversed(rows_so_far) if isinstance(r.get("metrics"), dict)), None)
            gated = Counter((r["metrics"].get("rung_id"), r["metrics"].get("tier")) for r in rows_so_far
                            if isinstance(r.get("metrics"), dict) and r["metrics"].get("ruler_sha256") == ruler
                            and r["metrics"].get("gate_met") is True)
            green = {rung for rung in baseline_done if rung not in event_status}
            for rung, gate in gates.items():
                kind = gate.get("kind")
                if event_status.get(rung) == "green":
                    green.add(rung)
                elif kind in ("std", "throughput") and gate.get("regression_corpus") and gate.get("promotion_corpus"):
                    if gated[(rung, "regression")] >= int(gate.get("repeats") or 1) and gated[(rung, "promotion")] >= 1:
                        green.add(rung)
                elif kind == "ratchet" and gate.get("promotion_corpus") and gated[(rung, "promotion")] >= 1:
                    green.add(rung)
            for rung, gate in gates.items():
                if gate.get("kind") == "same_as" and gate.get("rung") in green:
                    green.add(rung)
            history[f"W{wave}"] = green

        note = None
        fold = {rid for rid, row in self.rung_rows.items() if row.get("status") in ("green", "done")}
        fold_wave = self.status.get("wave")
        key = f"W{fold_wave}"
        if self.rung_rows and key in history and history[key] != fold:
            extra, missing = sorted(history[key] - fold), sorted(fold - history[key])
            note = (f"the refold disagrees with status.json at {key} (refold only: {', '.join(extra) or 'none'}; "
                    f"fold only: {', '.join(missing) or 'none'}); {key} shows the fold")
            history[key] = fold
        return history, note

    # ---------------------------------------------------------------- media
    def evidence_media(self, text: Any) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for raw in _PATH.findall(str(text or "")):
            path = Path(re.sub(r":\d+$", "", raw.rstrip(".:")))
            kind = _MEDIA_KIND.get(path.suffix.lower())
            if kind is None or path.name.endswith("-prompt.md"):
                continue
            media_id = self.media.add(path, kind, path.name, media_id=f"{TRACK}.{path.parent.name}.{path.name}")
            for ref in self.media.ref(media_id):
                if ref not in refs:
                    refs.append(ref)
        return refs

    def wave_report(self, wave: int) -> str | None:
        candidates = (sorted(self.reports_dir.glob(f"kinematic-curriculum-wave{wave}-*.html"))
                      if self.reports_dir is not None and self.reports_dir.is_dir() else [])
        if not candidates:
            return None
        return self.media.add(candidates[-1], "html", f"Wave {wave} report", media_id=f"{TRACK}.wave{wave}.report")

    # ---------------------------------------------------------------- the track
    def track(self) -> dict[str, Any]:
        track = skeleton(self.work_track, unit="wave")
        history, refold_note = self.refold()
        wave, phase, since = self.phase()

        kpis = [
            *self.kpi_rungs(history, refold_note),
            self.kpi_frontier(),
            self.kpi_gate_runs(),
            self.kpi_packages(),
            self.kpi_audits(),
            self.kpi_elapsed(),
            self.kpi_questions(),
            self.kpi_disk(),
        ]
        order = {"S1": 1, "S2": 2, "S3": 3, "S4": 4, "S5": 5, "S6": 6, "S7": 7}
        kpis.sort(key=lambda k: order.get(k["slot"], 9))
        self.add_evidence(history)
        evidence = self.ev.attach(kpis)

        track.update(
            summary=self.summary(wave, phase, history),
            state=self.state(wave, phase, since),
            iteration={"unit": "wave", "label": f"wave {wave}" if wave else "no wave yet"},
            rung=self.rung(wave, phase),
            iterations=self.iterations(history),
            north_star="rungs_green" if any(k["id"] == "rungs_green" for k in kpis) else None,
            kpis=kpis,
            needs_you=self.needs_you(),
            evidence=evidence,
            links=self.links(),
            provenance=self.prov(self.status_path, "/", "status.json for the current position; the per-wave series "
                                 "refolded from loop_events.jsonl + runs.jsonl (joined by judged_run.subject = run_id) "
                                 "and curriculum.json/triage.json in the loop checkout"),
            media=self.media.items,
        )
        return track

    # ---------------------------------------------------------------- iterations
    def iterations(self, history: dict[str, set[str]] | None) -> list[dict[str, Any]]:
        first = self.waves[min(self.waves)]["started"] if self.waves else None
        start_date = re.search(r"on (\d{4}-\d{2}-\d{2})", str((first or {}).get("detail") or ""))
        done = sorted(history["start"]) if history else []
        out = [{
            "id": "start", "label": "Start",
            "date": start_date.group(1) if start_date else None,
            "marker": " · ".join(p for p in (
                f"freeze {first.get('commit')}" if first and first.get("commit") else None,
                f"{len(done)} rungs done at baseline" if history else "rung history not refoldable") if p),
            "provenance": self.prov(self.events_path, None, "the first wave_started event's commit and date; done = baseline status 'done' in curriculum.json"),
        }]
        previous = history["start"] if history else None
        for n, info in self.waves.items():
            parts = []
            finished = info["finished"]
            if finished:
                match = _PACKAGES.search(str(finished.get("detail") or ""))
                parts.append(f"wave closed: {match.group(1)}/{match.group(2)} landed" if match else "wave closed")
            else:
                parts.append("wave in progress")
            for event in info["events"]:
                kind = event.get("kind")
                if kind == "pin_move":
                    pin = _PIN.search(str(event.get("detail") or ""))
                    parts.append(f"ruler pinned {pin.group(1)} {pin.group(2)[:8]}" if pin else "ruler pin moved")
                elif kind == "loop_paused":
                    parts.append(f"loop paused ({event.get('subject')})")
                elif kind == "loop_resumed":
                    parts.append("loop resumed")
            if history is not None:
                now = history[f"W{n}"]
                gained, lost = sorted(now - previous), sorted(previous - now)
                parts.append(f"+{len(gained)} rungs ({', '.join(gained)})" if gained else "no rung moved")
                if lost:
                    parts.append(f"−{len(lost)} ({', '.join(lost)})")
                previous = now
            date = (finished or info["started"] or {}).get("ts")
            out.append({
                "id": f"W{n}", "label": f"W{n}", "date": local_day(date),
                "marker": " · ".join(parts),
                "provenance": self.prov(self.events_path, None, f"events with wave {n}: wave_finished detail, pin_move, loop_paused/resumed; rungs from the refold"),
            })
        return out

    # ---------------------------------------------------------------- KPIs
    def kpi_rungs(self, history: dict[str, set[str]] | None, refold_note: str | None) -> list[dict[str, Any]]:
        counts = Counter(row.get("status") for row in self.rung_rows.values())
        fold_note = (f"status.json now: {counts.get('green', 0)} green + {counts.get('done', 0)} done; "
                     f"{counts.get('partial', 0)} partial, {counts.get('missing', 0)} missing") if self.rung_rows else "status.json not readable"
        lag = self.fold_lag_h()
        if lag is not None and lag > 0.25:
            fold_note += f"; the fold is {lag:.1f} h older than the newest event"
        if history is None:
            fold_count = counts.get("green", 0) + counts.get("done", 0) if self.rung_rows else None
            values = [_value(i, None, note=refold_note) for i in self.ids]
            if fold_count is not None and self.ids[-1] != "start":
                values[-1] = _value(self.ids[-1], fold_count, of=self.n_rungs, note="from status.json")
            moved = [_value(i, None, note=refold_note) for i in self.ids]
        else:
            values, moved = [], []
            previous = None
            for i in self.ids:
                now = history[i]
                values.append(_value(i, len(now), of=self.n_rungs, note=("done before wave 1: " + ", ".join(sorted(now))) if i == "start" else None))
                if previous is None:
                    moved.append(_value(i, None, note="no wave yet"))
                else:
                    gained, lost = sorted(now - previous), sorted(previous - now)
                    note = ", ".join(gained) or "no rung turned green"
                    if lost:
                        note += f"; lost: {', '.join(lost)}"
                    moved.append(_value(i, len(gained), note=note))
                previous = now
            if refold_note:
                values[-1]["note"] = refold_note

        latest, last_id = _last_measured(values), self.ids[-1]
        delta = (values[-1]["value"] - values[-2]["value"]) if len(values) > 1 and values[-1]["measured"] and values[-2]["measured"] else None
        rungs = _kpi(
            "rungs_green", "Rungs green or done", "S1", "rungs", "higher", values,
            target={"value": self.n_rungs, "kind": "scope", "label": f"of {self.n_rungs} rungs"} if self.n_rungs else None,
            baseline={"iteration": "start", "label": "start (freeze)", "value": values[0]["value"]} if values[0]["measured"] else None,
            status={"word": (f"+{delta} in {last_id}" if delta else f"no change in {last_id}") if delta is not None
                    else (f"{latest['value']} of {self.n_rungs}" if latest else "not measured"),
                    "tone": "ok" if delta else "muted"},
            note=fold_note + ". Gate rules per rung kind (curriculum.json); readings count only under the ruler they were judged by.",
            provenance=self.prov(self.status_path, "/rungs/*/status", "refold of rung_status_changed events + gated ledger rows per wave; "
                                 "the fold's wave is checked against status.json rungs[].status"),
        )
        out = [rungs]

        weights = {r["rung_id"]: r.get("kpi_weight") for r in (self.curriculum or {}).get("rungs", []) if r.get("rung_id")}
        if weights and history is not None:
            total = sum(int(w or 0) for w in weights.values())
            per = [sum(int(weights.get(r) or 0) for r in history[i]) for i in self.ids]
            wvalues = [_value(i, v, of=total) for i, v in zip(self.ids, per)]
            wvalues[0]["note"] = "the done rungs carry kpi_weight 0" if per[0] == 0 else None
            out.append(_kpi(
                "weighted_capability", "Weighted capability", "S1", "points", "higher", wvalues,
                target={"value": total, "kind": "scope", "label": f"of {total} points"},
                baseline={"iteration": "start", "label": "start (freeze)", "value": per[0]},
                status={"word": f"{round(100 * per[-1] / total)} % of scope" if total else "no weights", "tone": "muted"},
                note="Rungs green or done, each weighted by its curriculum kpi_weight.",
                provenance=self.prov(self.curriculum_path, "/rungs/*/kpi_weight", "sum of kpi_weight over the refold's rungs green or done per wave"),
            ))
        else:
            out.append(_kpi(
                "weighted_capability", "Weighted capability", "S1", "points", "higher",
                [_value(i, None, note=refold_note or "curriculum.json has no kpi_weight") for i in self.ids],
                status={"word": "not measured", "tone": "muted"}, note="Needs curriculum.json kpi_weight.",
                provenance=self.prov(self.curriculum_path, "/rungs/*/kpi_weight"),
            ))
        moved_last = _last_measured(moved)
        out.append(_kpi(
            "rungs_moved", "Rungs turned green per wave", "S4", "rungs", "higher", moved,
            status={"word": f"{moved_last['value']} in {moved_last['iteration']}" if moved_last else "not measured", "tone": "muted"},
            note="Rate beside the burn-up's level; the stop rule allows three waves in a row that move nothing.",
            provenance=self.prov(self.events_path, None, "difference of the refold's green-or-done sets between waves"),
        ))
        return out

    def frontier_rung(self) -> str | None:
        """The frontier rung with the newest ledgered promotion reading (status.json frontier order breaks ties)."""

        frontier = [r for r in self.status.get("frontier", []) if isinstance(r, str)]
        newest: tuple[str, str] | None = None
        for row in self.runs:
            m = row.get("metrics") or {}
            if m.get("rung_id") in frontier and m.get("tier") == "promotion":
                if newest is None or str(row.get("ts")) > newest[1]:
                    newest = (m["rung_id"], str(row.get("ts")))
        return newest[0] if newest else None

    def kpi_frontier(self) -> dict[str, Any]:
        rung = self.frontier_rung()
        frontier = ", ".join(self.status.get("frontier", [])) or "not recorded"
        if rung is None:
            return _kpi("frontier_feasible", "Frontier rung feasible", "S2", "%", "higher",
                        [_value(i, None, note="no frontier rung has a ledgered promotion reading") for i in self.ids],
                        status={"word": "no reading", "tone": "muted"}, note=f"Frontier: {frontier}.",
                        provenance=self.prov(self.runs_path, "/metrics/feasible_rate"))
        gate = next((r.get("gate") or {} for r in (self.curriculum or {}).get("rungs", []) if r.get("rung_id") == rung), {})
        gate_pct = _pct(gate.get("feasible_rate_min"))
        values, rulers = [_value("start", None, note="no wave yet")], []
        for n in self.waves:
            rows = [r for r in self.runs_in(n) if (r.get("metrics") or {}).get("rung_id") == rung and r["metrics"].get("tier") == "promotion"]
            if not rows:
                values.append(_value(f"W{n}", None, note=f"no {rung} promotion reading in W{n}" + ("; no ledger row is joined to this wave" if not self.runs_in(n) else "")))
                continue
            pcts = [_pct(r["metrics"].get("feasible_rate")) for r in rows]
            last = rows[-1]
            ruler = str(last["metrics"].get("ruler_sha256") or "")[:8]
            rulers.append(ruler)
            totals = last.get("totals") or {}
            recovery = last["metrics"].get("recovery")
            values.append(_value(
                f"W{n}", pcts[-1], n=len(rows), spread=round(max(pcts) - min(pcts), 1) if len(rows) > 1 else None,
                note=f"{totals.get('feasible')}/{totals.get('presented')} feasible, recovery {recovery}, ruler {ruler}"
                     + (f"; {len(rows)} identical readings" if len(set(pcts)) == 1 and len(rows) > 1 else "")))
        measured = [v for v in values if v["measured"]]
        latest = measured[-1] if measured else None
        if latest is None:
            word, tone = "no reading", "muted"
        elif len(measured) > 1 and len(set(rulers[-2:])) > 1:
            word, tone = f"{latest['value']} % · ruler changed since the previous reading, not comparable", "muted"
        elif len(measured) > 1 and min(latest["n"] or 0, measured[-2]["n"] or 0) <= 1 and latest["value"] != measured[-2]["value"]:
            word, tone = N1_WORD, "warn"
        elif gate_pct is not None and latest["value"] < gate_pct:
            word, tone = f"below gate · {latest['value']} % of {gate_pct:g} %", "muted"
        else:
            word, tone = f"{latest['value']} % · gate met", "ok"
        return _kpi(
            "frontier_feasible", f"{rung} feasible", "S2", "%", "higher", values,
            target={"value": gate_pct, "kind": "gate", "label": f"gate {gate_pct:g} % feasible"} if gate_pct is not None else None,
            status={"word": word, "tone": tone},
            note=f"{rung} is the frontier rung with the newest ledgered promotion reading. Frontier now: {frontier}. "
                 f"Readings compare only under one ruler.",
            provenance=self.prov(self.runs_path, "/metrics/feasible_rate", f"the wave's last {rung} promotion row; n = promotion rows in the wave"),
        )

    def _per_wave_events(self, kind: str) -> dict[int, list[dict[str, Any]]]:
        return {n: [e for e in info["events"] if e.get("kind") == kind] for n, info in self.waves.items()}

    def kpi_gate_runs(self) -> dict[str, Any]:
        values = [_value("start", None, note="no wave yet")]
        last_fail = False
        for n, runs in self._per_wave_events("gate_run").items():
            if not runs:
                values.append(_value(f"W{n}", None, note="no gate_run event in this wave"))
                continue
            tiers = Counter((e.get("subject"), e.get("status")) for e in runs)
            note = " · ".join(f"{tier} {tiers[(tier, 'pass')]}/{sum(c for (t, _), c in tiers.items() if t == tier)}"
                              for tier in sorted({t for t, _ in tiers}))
            values.append(_value(f"W{n}", sum(1 for e in runs if e.get("status") == "pass"), of=len(runs), n=len(runs), note=note))
            last_fail = runs[-1].get("status") != "pass"
        latest = _last_measured(values)
        return _kpi(
            "gate_runs", "Regression gate runs passed", "S3", "runs", "info", values,
            status={"word": ("last gate run failed" if last_fail else f"{latest['value']} of {latest['of']} passed · last passed")
                    if latest else "not measured", "tone": "warn" if last_fail else "muted"},
            note="Every gate run of the wave (fast and rungs tiers), failed ones included; a wave closes on a pass.",
            provenance=self.prov(self.events_path, None, "gate_run events per wave by status"),
        )

    def kpi_packages(self) -> dict[str, Any]:
        values = [_value("start", None, note="no wave yet")]
        for n, info in self.waves.items():
            finished = info["finished"]
            match = _PACKAGES.search(str((finished or {}).get("detail") or ""))
            if match:
                values.append(_value(f"W{n}", int(match.group(1)), of=int(match.group(2))))
            else:
                values.append(_value(f"W{n}", None, note="wave in progress" if not finished else "wave_finished names no 'N of M packages landed'"))
        latest = _last_measured(values)
        return _kpi(
            "packages_landed", "Packages landed", "S4", "packages", "higher", values,
            status={"word": f"{latest['value']} of {latest['of']} landed in {latest['iteration']}" if latest else "not measured", "tone": "muted"},
            note="Barriers, builder lanes and research lanes planned for the wave that landed.",
            provenance=self.prov(self.events_path, None, "parsed from the free text 'N of M packages landed' in wave_finished.detail"),
        )

    def kpi_audits(self) -> dict[str, Any]:
        values = [_value("start", None, note="no wave yet")]
        for n, audits in self._per_wave_events("audit").items():
            if not audits:
                values.append(_value(f"W{n}", None, note="no audit event in this wave"))
                continue
            verdicts = Counter(e.get("status") for e in audits)
            other = ", ".join(f"{c} {v.replace('_', ' ')}" for v, c in sorted(verdicts.items()) if v != "pass")
            values.append(_value(f"W{n}", verdicts.get("pass", 0), of=len(audits), n=len(audits), note=other or None))
        latest = _last_measured(values)
        return _kpi(
            "audits_passed", "Audits passed", "S5", "audits", "info", values,
            status={"word": f"{latest['value']} of {latest['of']} passed in {latest['iteration']}" if latest else "not measured", "tone": "muted"},
            note="Independent read-only audits (Codex) recorded in the wave. A fail is the audit doing its job: "
                 "its findings were fixed, parked or sent to triage.",
            provenance=self.prov(self.events_path, None, "audit events per wave by status (pass/fail/not_run)"),
        )

    def kpi_elapsed(self) -> dict[str, Any]:
        values = [_value("start", None, note="no wave yet")]
        for n, info in self.waves.items():
            started, finished = info["started"], info["finished"]
            begin, end = _ts((started or {}).get("ts")), _ts((finished or {}).get("ts"))
            if started is None:
                values.append(_value(f"W{n}", None, note="no wave_started event"))
            elif finished is None:
                values.append(_value(f"W{n}", None, note=f"wave in progress since {_short_ts(started.get('ts'))}"))
            elif "recorded at wave close" in str(started.get("detail") or "") or not (begin and end) or (end - begin).total_seconds() < 300:
                values.append(_value(f"W{n}", None, note="wave_started was written at the close, so the start time is not in the event log"))
            else:
                values.append(_value(f"W{n}", round((end - begin).total_seconds() / 3600.0, 1),
                                     note=f"{_short_ts(started.get('ts'))} → {_short_ts(finished.get('ts'))}"))
        latest = _last_measured(values)
        return _kpi(
            "elapsed_h", "Elapsed hours per wave", "S6", "h elapsed", "lower", values,
            status={"word": f"{latest['value']} h wall clock in {latest['iteration']}" if latest else "not measured", "tone": "muted"},
            note="Wall-clock hours from wave_started to wave_finished, pauses included; not agent-hours (agent and compute cost are unmetered).",
            provenance=self.prov(self.events_path, None, "wave_finished.ts − wave_started.ts"),
        )

    def kpi_questions(self) -> dict[str, Any]:
        items = (self.triage or {}).get("items")
        if not isinstance(items, list):
            return _kpi("questions_opened", "Questions opened", "S7", "questions", "count",
                        [_value(i, None, note="triage.json not readable") for i in self.ids],
                        status={"word": "not measured", "tone": "muted"}, note=None, provenance=self.prov(self.triage_path))
        opened = Counter(item.get("opened_wave") for item in items)
        values = [_value("start", None, note="no wave yet")] + [_value(f"W{n}", opened.get(n, 0)) for n in self.waves]
        open_items = [i for i in items if i.get("status") == "open"]
        blocking = [t for t in self.status.get("blocking_triage", []) if isinstance(t, str)]
        return _kpi(
            "questions_opened", "Questions opened", "S7", "questions", "count", values,
            status={"word": f"{len(open_items)} open · {len(blocking)} blocking a rung", "tone": "warn" if blocking else "muted"},
            note="Triage items by the wave that opened them. Silence keeps the work moving: an unanswered item's default "
                 "applies at the end of the wave it names. Blocking is the loop's own list (status.json blocking_triage).",
            provenance=self.prov(self.triage_path, "/items/*/opened_wave", "count of triage items per opened_wave"),
        )

    def stop_line(self) -> float | None:
        for item in (self.triage or {}).get("items", []) or []:
            match = _STOP_LINE.search(str(item.get("default") or "")) if item.get("triage_id") == "T33" else None
            if match:
                return float(match.group(1))
        return None

    def kpi_disk(self) -> dict[str, Any]:
        line = self.stop_line()
        values = [_value("start", None, note="no wave yet")]
        self.disk_events: list[tuple[str, dict[str, Any]]] = []
        for n, info in self.waves.items():
            readings = []
            for event in info["events"]:
                for match in _DF.finditer(str(event.get("detail") or "")):
                    readings.append((float(match.group(1)), event))
            if not readings:
                values.append(_value(f"W{n}", None, note="no df reading recorded in this wave"))
                continue
            for _, event in readings:
                self.disk_events.append((f"W{n}", event))
            pcts = [r for r, _ in readings]
            peak_event = max(readings, key=lambda reading: reading[0])[1]
            last_reading = (pcts[-1], readings[-1][1])
            # WHY the peak and not the last reading: the stop line is a guardrail, and the wave's closest approach
            # to it is the risk (W3 paused at a printed 91 % before a reboot freed /tmp).
            values.append(_value(
                f"W{n}", max(pcts), n=len(pcts), spread=round(max(pcts) - min(pcts), 1) if len(pcts) > 1 else None,
                note=f"peak printed df, at {peak_event.get('kind')} {_short_ts(peak_event.get('ts'))}"
                     + (f"; readings in order: {', '.join(f'{p:g}' for p in pcts)} %" if len(pcts) > 1 else "")))
        latest = last_reading if self.disk_events else None
        if latest is None:
            word, tone = "not measured", "muted"
        elif line is None:
            word, tone = f"last reading {latest[0]:g} % · stop line not found", "muted"
        else:
            room = line - latest[0]
            word = f"last reading {latest[0]:g} % ({_short_ts(latest[1].get('ts'))}) · {room:g} pt under the stop line"
            tone = "warn" if room <= 2 else "ok"
        return _kpi(
            "disk_pct", "Disk used on / · peak df in the wave", "S7", "%", "lower", values,
            target={"value": line, "kind": "limit", "label": f"stop line: df -h / prints {line:g} %"} if line is not None else None,
            status={"word": word, "tone": tone},
            note="The loop's own df readings (preflight, pause, close), not a live df: the disk moves hourly as other fleets write.",
            provenance=self.prov(self.events_path, None, "printed df percentages parsed from event details; the stop line from triage T33's default"),
        )

    # ---------------------------------------------------------------- evidence
    def add_evidence(self, history: dict[str, set[str]] | None) -> None:
        disk_ids = {id(event) for _, event in getattr(self, "disk_events", [])}
        frontier = self.frontier_rung()
        for n, info in self.waves.items():
            it = f"W{n}"
            report = self.wave_report(n)
            finished = info["finished"]
            if report or finished:
                self.ev.add(it, "report", f"Wave {n} report" if report else f"Wave {n} close", item_id=f"{it}-report",
                            when=(finished or {}).get("ts"), status="closed" if finished else "in progress",
                            metrics={"commit": (finished or {}).get("commit")}, media=self.media.ref(report),
                            note=_clip((finished or {}).get("detail"), 600) or None,
                            kpis=["rungs_green", "weighted_capability", "rungs_moved", "packages_landed", "elapsed_h"])
            for j, event in enumerate(info["events"]):
                kind, subject, status = event.get("kind"), str(event.get("subject") or ""), event.get("status")
                detail = _clip(event.get("detail"), 600) or None
                common = {"when": event.get("ts"), "status": status, "note": detail,
                          "media": self.evidence_media(event.get("evidence"))}
                disk = ["disk_pct"] if id(event) in disk_ids else []
                if kind == "lane_status":
                    self.ev.add(it, "lane", subject, item_id=f"{it}-lane-{subject}", kpis=["packages_landed"], **common)
                elif kind == "audit":
                    self.ev.add(it, "audit", subject, item_id=f"{it}-audit-{j}-{subject}", kpis=["audits_passed"], **common)
                elif kind == "gate_run":
                    self.ev.add(it, "gate", f"{subject} gate · {status}", item_id=f"{it}-gate-{j}",
                                metrics={"commit": event.get("commit")}, kpis=["gate_runs"], **common)
                elif kind == "rung_status_changed":
                    self.ev.add(it, "note", f"{subject} → {status}", item_id=f"{it}-rung-{j}-{subject}",
                                kpis=["rungs_green", "weighted_capability", "rungs_moved"], **common)
                elif kind == "triage_changed":
                    self.ev.add(it, "note", f"Triage {subject} {status}", item_id=f"{it}-triage-{j}", kpis=["questions_opened"], **common)
                elif kind == "wave_started":
                    self.ev.add(it, "note", f"Wave {n} started", item_id=f"{it}-started", metrics={"commit": event.get("commit")},
                                kpis=["elapsed_h", *disk], **common)
                elif kind == "wave_finished":
                    if disk:
                        self.ev.add(it, "note", f"Wave {n} closed", item_id=f"{it}-finished", kpis=disk, **common)
                elif kind in ("pin_move", "loop_paused", "loop_resumed", "intervention", "note", "loop_stopped"):
                    label = {"pin_move": "Pin move", "loop_paused": "Loop paused", "loop_resumed": "Loop resumed",
                             "intervention": "Intervention", "loop_stopped": "Loop stopped"}.get(kind, "Note")
                    self.ev.add(it, "note", f"{label}: {subject}", item_id=f"{it}-{kind}-{j}",
                                metrics={"commit": event.get("commit")}, kpis=disk, **common)
            for row in self.runs_in(n):
                m, totals = row.get("metrics") or {}, row.get("totals") or {}
                rung = m.get("rung_id")
                kpi_ids = ["frontier_feasible"] if rung == frontier and m.get("tier") == "promotion" else []
                if m.get("gate_met"):
                    kpi_ids.append("rungs_green")
                git = row.get("git") or {}
                batch = self.status_path.parent / "runs" / str(row.get("run_id")) / "batch.json" if self.status_path else None
                media_id = self.media.add(batch, "text", f"{row.get('run_id')} batch.json", media_id=f"{TRACK}.run.{row.get('run_id')}") if batch else None
                self.ev.add(it, "run", f"{rung} · {m.get('tier')}", item_id=str(row.get("run_id")), when=row.get("ts"),
                            metrics={
                                "feasible": f"{totals.get('feasible')}/{totals.get('presented')}",
                                "feasible %": _pct(m.get("feasible_rate")),
                                "ppm": round(m["ppm"], 2) if isinstance(m.get("ppm"), (int, float)) else None,
                                "recovery": m.get("recovery"),
                                "compute p95 (s)": round(m["compute_s_p95"], 4) if isinstance(m.get("compute_s_p95"), (int, float)) else None,
                                "void": totals.get("void"),
                                "ruler": str(m.get("ruler_sha256") or "")[:8] or None,
                                "verdict hash": str(m.get("verdict_hash") or "")[:12] or None,
                                "git": (str(git.get("sha") or "")[:8] + (" dirty" if git.get("dirty") else "")) or None,
                            },
                            status="gate met" if m.get("gate_met") else "below gate", media=self.media.ref(media_id),
                            note=row.get("note"), kpis=kpi_ids)

    # ---------------------------------------------------------------- state, summary, needs, links
    def fold_lag_h(self) -> float | None:
        generated = _ts(self.status.get("generated_at"))
        newest = max((t for t in (_ts(e.get("ts")) for e in self.events) if t), default=None)
        if generated is None or newest is None:
            return None
        return max(0.0, (newest - generated).total_seconds() / 3600.0)

    def state(self, wave: int, phase: str, since: dict[str, Any] | None) -> dict[str, Any]:
        when = (since or {}).get("ts")
        frontier = [r for r in self.status.get("frontier", []) if isinstance(r, str)]
        # WHY the whole list: it used to show the first four with no mark, silently hiding half the frontier.
        nxt = f"frontier: {', '.join(frontier)}" if frontier else None
        if phase == "running":
            word, tone, detail = "Running", "ok", f"wave {wave} in progress since {_short_ts(when)}"
        elif phase == "between_waves":
            word, tone, detail = "Between waves", "ok", f"wave {wave} closed {_short_ts(when)} · wave {wave + 1} not started"
        elif phase == "paused":
            word, tone = "Paused", "warn"
            detail = f"{(since or {}).get('subject') or 'paused'}: {_clip(str((since or {}).get('detail') or '').split(';')[0], 120)}"
        elif phase == "stopped":
            word, tone, detail = "Stopped", "muted", _clip((since or {}).get("detail"), 120) or "loop_stopped"
        else:
            word, tone, detail = "Not started", "muted", "no wave event yet"
        parts = [detail, nxt if phase != "paused" else None]
        fold_wave, fold_phase = self.status.get("wave"), self.status.get("phase")
        if self.status and (fold_wave, fold_phase) != (wave, phase):
            parts.append(f"status.json still says wave {fold_wave} {fold_phase}")
        if any(self.unreadable.values()):
            parts.append("skipped unreadable lines: " + ", ".join(f"{k} {v}" for k, v in self.unreadable.items() if v))
        return {"word": word, "tone": tone, "detail": " · ".join(p for p in parts if p), "since": when}

    def rung(self, wave: int, phase: str) -> dict[str, Any] | None:
        """The loop's current rung(s) and what it plans next (base.rung).

        Running: the wave's own targets (curriculum.json ``wave`` == the running wave, not yet green or done in
        status.json). Otherwise the frontier, status.json's list of the lowest rung not yet passed on each axis.
        Next: the next planned wave's rungs that are still open (curriculum.json), else the rest of the frontier.
        WHY the frontier and not the rung with the newest reading: the newest reading is what was last measured, not
        where the loop stands (BT2 was measured last; SN2 and RB1 are just as open).
        """

        frontier = [r for r in self.status.get("frontier", []) if isinstance(r, str)]
        if not self.status or (not frontier and phase != "running"):
            return None
        open_ = lambda rung_id: (self.rung_rows.get(rung_id) or {}).get("status") not in ("green", "done")  # noqa: E731
        planned: dict[int, list[str]] = defaultdict(list)
        for row in (self.curriculum or {}).get("rungs") or []:
            planned_wave = row.get("wave") if isinstance(row, dict) else None
            if isinstance(planned_wave, int) and not isinstance(planned_wave, bool) and row.get("rung_id") and open_(row["rung_id"]):
                planned[planned_wave].append(row["rung_id"])
        if phase == "running" and planned.get(wave):
            current, here = f"Wave {wave} · {', '.join(planned[wave])}", set(planned[wave])
        elif frontier:
            current, here = f"Frontier · {', '.join(frontier)}", set(frontier)
        else:
            return None
        upcoming = next(((n, planned[n]) for n in sorted(planned) if n > wave and planned[n]), None)
        if upcoming:
            nxt = f"Wave {upcoming[0]} · {', '.join(upcoming[1])}"
        else:
            rest = [r for r in frontier if r not in here]
            nxt = ", ".join(rest) or None
        return rung(current, nxt, "kinsim_status (frontier) · curriculum.json (wave plan)")

    def summary(self, wave: int, phase: str, history: dict[str, set[str]] | None) -> str:
        if not wave:
            return "Kinematic-sim curriculum loop: no wave has started."
        counts = Counter(row.get("status") for row in self.rung_rows.values())
        bits = [f"Wave {wave} {'closed' if phase in ('between_waves', 'stopped') else 'in progress' if phase == 'running' else phase}"]
        if self.rung_rows:
            green_done = counts.get("green", 0) + counts.get("done", 0)
            moved = ""
            if history and f"W{wave}" in history:
                previous = history.get(f"W{wave - 1}", history["start"])
                gained = sorted(history[f"W{wave}"] - previous)
                moved = f" (+{len(gained)}: {', '.join(gained)})" if gained else " (none new this wave)"
            bits.append(f"{green_done} of {self.n_rungs} rungs green or done{moved}")
        rung = self.frontier_rung()
        if rung:
            rows = [r for r in self.runs if (r.get("metrics") or {}).get("rung_id") == rung and r["metrics"].get("tier") == "promotion"]
            pct = _pct(rows[-1]["metrics"].get("feasible_rate")) if rows else None
            if pct is not None:
                bits.append(f"frontier {rung} at {pct:g} % feasible")
        items = (self.triage or {}).get("items")
        if isinstance(items, list):
            n_open = sum(1 for i in items if i.get("status") == "open")
            bits.append(f"{n_open} questions open, {len(self.status.get('blocking_triage', []))} blocking a rung")
        return "; ".join(bits) + "."

    def needs_you(self) -> list[dict[str, Any]]:
        items = (self.triage or {}).get("items")
        if not isinstance(items, list):
            return []
        blocking = set(t for t in self.status.get("blocking_triage", []) if isinstance(t, str))
        finished = max((n for n, info in self.waves.items() if info["finished"]), default=0)
        out = []
        for item in items:
            if item.get("status") != "open" or not item.get("triage_id"):
                continue
            after = item.get("default_applies_after_wave")
            applies = None
            if isinstance(after, int):
                applies = f"after W{after}" + (" · in force (W{} closed)".format(after) if finished >= after else "")
            # WHY blocks only for the loop's blocking list: an item whose default is in force no longer holds its
            # rungs (TRIAGE.md), and counting it would show seven blockers where the loop has one.
            out.append({"id": item["triage_id"], "q": _clip(item.get("title"), 200),
                        "blocks": list(item.get("blocks") or []) if item["triage_id"] in blocking else [],
                        "default": _clip(item.get("default"), 300) or None, "applies": applies})

        def number(need: dict[str, Any]) -> int:
            digits = re.sub(r"\D", "", need["id"])
            return int(digits) if digits else 0

        return sorted(out, key=lambda need: (not need["blocks"], number(need)))

    def links(self) -> list[dict[str, Any]]:
        links = []
        for n in sorted(self.waves, reverse=True):
            media_id = f"{TRACK}.wave{n}.report"
            if media_id in self.media.items:
                links.append({"label": f"Wave {n} report", "kind": "media", "media": media_id})
                break
        for label, path in (("Roadmap", self.roadmap_path), ("Triage", self.triage_md_path), ("Live fold", self.status_path),
                            ("Run ledger", self.runs_path), ("Event log", self.events_path)):
            if path is not None and path.is_file():
                links.append({"label": label, "kind": "path", "value": str(path)})
        return links
