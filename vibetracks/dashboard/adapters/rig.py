"""Adapter for the Sim to Real & Trajectory Tracking work track (vibe-id ``rig``), live from the rig loop's own files.

Interface and source map: docs/dashboard/ADAPTERS.md (section ``rig``); the discovery behind it is
docs/dashboard/track-discovery-2026-10-04.json key ``scout:sim2real``.

Inputs, declared in workspace/tracks/rig.md ``vibe-sources`` (the build watches exactly these):

- ``rig_loop_status``: ``loop-status.json`` (loop-status/1): tick, rate, milestone, where[], now[], next[],
  needs_you[], blockers[]. Required: without it the track is honestly "not reporting".
- ``rig_events``: ``loop_events.jsonl`` (bam-loop-event/1), the append-only ledger. The per-tick series are rebuilt
  from it, because loop-status keeps only the last three ``rungs_moved_per_tick`` values.
- ``rig_ladder``: ``ladder.json`` (rig-ladder/1): 6 axes of rungs and the packages mapped to them.
- ``deployments_fixtures_dir``: the bam_deployments API responses (``deployments.json``, ``kpis_session_<id>.json``,
  ``kpis_day_<id>.json``): the contract's own KPI values per session and per day, for the can12/can16 children and
  for the rig's twin-gap KPI.

- ``rig_triage`` / ``rig_roadmap``: ``triage.json`` and ``ROADMAP.md`` next to loop-status (the full questions and
  the disk stop line).
- ``rig_deployments_cache``: the bam_deployments run cache ``/archive/datasets/bam_rig/cache/runs``, one record per
  run, for the run evidence, the held conditions and the twin sessions the frozen fixture predates.
- ``rig_audits_dir``: bam_ws ``reports/media/audits``, listed only to link each package's audit write-ups.
- ``rig_kpi_table``: the bam_deployments contract v2.5 export folder (``kpi_table.json`` + ``kpi_table.csv``, written
  by ``python -m bam_deployments export <dir>``): one row per deployment x backend x settings. It is the ORACLE for
  the robot KPIs: the headline values and the "KPIs by deployment, backend and settings" table are its numbers, never
  re-derived here (only multiplied by its own ``kpi_defs`` display scale).
- ``rig_playbacks``: a ``bam_runtime.playback`` batch folder (``index.json`` + one ``.rrd`` per real run).
- ``rig_rerun_viewer``: the Rerun viewer binary that opens those ``.rrd`` files (stat only; named in each command).
- ``rig_kpi_docs`` / ``rig_living_report``: the KPI doc (bam_deployments ``KPIS.md``) and the loop's living report,
  stat only, linked.

Nothing else is opened (``READS``; tests/test_dashboard_adapters_live.py records every open under an audit hook). A
key the note does not declare is read as missing, never looked up elsewhere: the build would not notice that file
change.

Truth rules (PROJECTION.md): every number names its file; missing is null with a note, never zero; a change resting on
n = 1 reads "unconfirmed · repeat needed"; a day floor is a descriptive band; elapsed hours are wall clock.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .bam_loops import BAM_WS_ROOT, N1_WORD, AuditFiles, BamLoopsAdapter, Evidence, MediaIndex, _kpi, _value, change_status
from .base import local_day, local_time, not_reporting, rung, skeleton

#: The bam_deployments run cache: one ``<bundle>/<run>.json`` per run, written by ``bam_deployments scan``
#: (sources.py ``rig_deployments_cache``).
CACHE_KEY = "rig_deployments_cache"
#: The robot-KPI inputs (appended 2026-10-06, KPI-VIEW brief): the KPI-table export folder, the Rerun playback batch
#: folder, the viewer that opens it, the KPI doc and the living report.
KPI_TABLE_KEY = "rig_kpi_table"
PLAYBACKS_KEY = "rig_playbacks"
VIEWER_KEY = "rig_rerun_viewer"
KPI_DOCS_KEY = "rig_kpi_docs"
REPORT_KEY = "rig_living_report"
#: Every sources.py key this adapter opens, and what it is to the loop (base.py READ_ROLES).
READS = {"rig_loop_status": "heartbeat", "rig_events": "heartbeat", "rig_ladder": "heartbeat",
         "rig_triage": "heartbeat", "rig_roadmap": "heartbeat", "deployments_fixtures_dir": "input",
         CACHE_KEY: "input", "rig_audits_dir": "evidence",
         KPI_TABLE_KEY: "input", PLAYBACKS_KEY: "input", VIEWER_KEY: "input", KPI_DOCS_KEY: "evidence",
         REPORT_KEY: "evidence"}
#: The run cache's records sit in bundle folders (``runs/<bundle>/<run>.json``): the build stamps it two levels deep,
#: so a rewritten record reruns the adapter, not only a new bundle.
DEPTH = {CACHE_KEY: 2}

DEG = 57.29577951308232
COUNT_KEYS = ("real_runs", "sim_runs", "aborted_runs")
REAL_KEYS = ("real_tracking_rms", "real_tracking_p95", "sim_real_gap", "feedback_torque_proxy")
TWIN_KEYS = ("twin_fidelity_gap", "twin_tracking_ratio")
SLOTS = {"real_tracking_rms": "S1", "twin_fidelity_gap": "S2", "real_tracking_p95": "S3", "feedback_torque_proxy": "S3",
         "aborted_runs": "S3", "real_runs": "S4", "sim_runs": "S4", "sim_real_gap": "S5", "floor_real_vs_real": "S5",
         "twin_tracking_ratio": "S5"}

# "/ at 90%", "Disk back at 92%", "Disk / at 78% (194 GB free)": the loop writes disk readings into event prose only.
DISK_RE = re.compile(r"(?:\b[Dd]isk\b[^%\n]{0,30}?|(?:^|[\s;])/\s+(?:is\s+)?(?:back\s+)?at\s+)(\d{1,3}(?:\.\d+)?)\s*%")
FREE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*GB free")
GATE_RE = re.compile(r"≤\s*(\d+(?:\.\d+)?)\s*°")


def _now() -> datetime:
    """The build's clock (patched by tests)."""

    return datetime.now().astimezone()


# --------------------------------------------------------------------------------------------- reading files


def _read_json(path: str | None) -> tuple[Any, str | None]:
    if not path:
        return None, "not declared"
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as error:
        return None, f"unreadable ({type(error).__name__})"


def _read_events(path: str | None) -> tuple[list[dict[str, Any]], int, str | None]:
    """(rows, bad line count, error): every parseable row with a timestamp, in file order."""

    if not path:
        return [], 0, "not declared"
    rows, bad = [], 0
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    row["_ts"] = _ts(row["ts"])
                except (ValueError, KeyError, TypeError):
                    bad += 1
                    continue
                rows.append(row)
    except FileNotFoundError:
        return [], 0, "missing"
    except OSError as error:
        return [], 0, f"unreadable ({type(error).__name__})"
    return rows, bad, None


def _ts(text: str) -> datetime:
    """An aware timestamp; a naive one (the run cache's ``started_at``) is this machine's local time."""

    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.astimezone()


def _stamp(path: str | None, now: datetime) -> dict[str, Any]:
    try:
        modified = datetime.fromtimestamp(os.stat(path).st_mtime).astimezone() if path else None
    except OSError:
        modified = None
    return {"path": path, "exists": modified is not None,
            "modified": modified.isoformat(timespec="seconds") if modified else None,
            "age_h": round((now - modified).total_seconds() / 3600, 1) if modified else None}


def _hm(moment: datetime) -> str:
    return local_time(moment)


def _age(moment: datetime, now: datetime) -> str:
    hours = (now - moment).total_seconds() / 3600
    return f"{hours:.0f} h old" if hours < 48 else f"{hours / 24:.0f} days old"


def _prov(source: str | None, pointer: str | None = None, derived: str | None = None) -> dict[str, Any]:
    return {"snapshot": None, "pointer": pointer, "source": source, "derived": derived}


# --------------------------------------------------------------------------------------------- ticks


@dataclass
class Tick:
    n: int
    events: list[dict[str, Any]] = field(default_factory=list)
    started: datetime | None = None  # wave_started
    finished: datetime | None = None  # wave_finished

    @property
    def first(self) -> datetime | None:
        moments = [e["_ts"] for e in self.events]
        return min(moments) if moments else None

    @property
    def last(self) -> datetime | None:
        moments = [e["_ts"] for e in self.events]
        return max(moments) if moments else None

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("kind") == kind]


class Ticks:
    """The loop's ticks T0..Tn, from the events' ``wave`` field (loop-status ``tick.n`` is the current one).

    WHY windows from first to last event and not from wave_started: only ticks 0, 1 and 3 have a wave_started row
    (tick 2 has no row at all, tick 4 none of its own), so a timestamp between two ticks' events is genuinely
    ambiguous; ``place`` puts it in the later tick and says so instead of guessing silently.
    """

    def __init__(self, events: list[dict[str, Any]], current: int):
        by_n: dict[int, Tick] = {}
        for row in events:
            wave = row.get("wave")
            if not isinstance(wave, int) or wave < 0:
                continue
            tick = by_n.setdefault(wave, Tick(wave))
            tick.events.append(row)
            if row.get("kind") == "wave_started" and tick.started is None:
                tick.started = row["_ts"]
            if row.get("kind") == "wave_finished":
                tick.finished = row["_ts"]
        self.current = max([current, *by_n]) if by_n else current
        self.loop_current = current
        self.ticks = [by_n.get(n, Tick(n)) for n in range(self.current + 1)]
        self.recorded = [t for t in self.ticks if t.events]

    @property
    def ids(self) -> list[str]:
        return [f"T{t.n}" for t in self.ticks]

    def place(self, moment: datetime) -> tuple[int, str | None]:
        """(tick n, note): the tick whose events span ``moment``; between two ticks, the later one, with a note."""

        if not self.recorded:
            return self.current, "no tick has events; placed in the current tick"
        for tick in self.recorded:
            if tick.first <= moment <= tick.last:
                return tick.n, None
        if moment > self.recorded[-1].last:
            last = self.recorded[-1]
            if last.n == self.current:
                return last.n, None
            return self.current, f"after T{last.n}'s last event ({_hm(last.last)}); placed in the current tick"
        if moment < self.recorded[0].first:
            return self.recorded[0].n, f"before the first event ({_hm(self.recorded[0].first)})"
        for before, after in zip(self.recorded, self.recorded[1:]):
            if before.last < moment < after.first:
                skipped = [f"T{n}" for n in range(before.n + 1, after.n)]
                gap = f" ({', '.join(skipped)} recorded no event)" if skipped else ""
                return after.n, (f"between T{before.n}'s last event ({_hm(before.last)}) and T{after.n}'s first "
                                 f"({_hm(after.first)}){gap}; placed in T{after.n}")
        return self.current, None  # unreachable with sorted, non-overlapping windows; kept total


# --------------------------------------------------------------------------------------------- deployments data


def _cache_dir(sources: dict[str, str]) -> str | None:
    """The run cache, only when the note declares it: an undeclared input would change without a rebuild."""

    return sources.get(CACHE_KEY) or None


@dataclass
class Deployments:
    """The bam_deployments data: the frozen API fixtures (the contract's KPI values) plus the run cache (raw runs)."""

    fixtures_dir: str | None
    cache_dir: str
    listing: list[dict[str, Any]]
    sessions: dict[str, dict[str, Any]]  # deployment id -> kpis_session_<id>.json
    days: dict[str, dict[str, Any]]  # deployment id -> kpis_day_<id>.json
    records: dict[str, list[dict[str, Any]]]  # deployment id -> cache records (``record`` blocks)
    stamps: dict[str, dict[str, Any]]
    problems: list[str]

    @classmethod
    def load(cls, sources: dict[str, str], now: datetime) -> "Deployments":
        fixtures = sources.get("deployments_fixtures_dir")
        problems: list[str] = []
        stamps: dict[str, dict[str, Any]] = {}
        listing: list[dict[str, Any]] = []
        sessions: dict[str, dict[str, Any]] = {}
        days: dict[str, dict[str, Any]] = {}
        if fixtures:
            path = os.path.join(fixtures, "deployments.json")
            data, error = _read_json(path)
            stamps["deployments.json"] = _stamp(path, now)
            if error:
                problems.append(f"deployments.json {error}")
            elif isinstance(data, list):
                listing = [d for d in data if isinstance(d, dict) and isinstance(d.get("id"), str)]
            for dep in listing:
                for granularity, target in (("session", sessions), ("day", days)):
                    name = f"kpis_{granularity}_{dep['id']}.json"
                    path = os.path.join(fixtures, name)
                    data, error = _read_json(path)
                    stamps[name] = _stamp(path, now)
                    if error:
                        problems.append(f"{name} {error}")
                    elif isinstance(data, dict):
                        target[dep["id"]] = data
        else:
            problems.append("deployments_fixtures_dir not declared")
        cache = _cache_dir(sources)
        records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        newest = None
        try:
            if cache is None:
                raise FileNotFoundError
            bundles = sorted((entry for entry in os.scandir(cache) if entry.is_dir()), key=lambda e: e.name)
        except OSError:
            bundles = []
            problems.append(f"{CACHE_KEY} not declared in vibe-sources" if cache is None else f"run cache {cache} missing")
        for bundle in bundles:
            for entry in sorted(os.scandir(bundle.path), key=lambda e: e.name):
                if not entry.name.endswith(".json"):
                    continue
                data, error = _read_json(entry.path)
                record = data.get("record") if isinstance(data, dict) else None
                if error or not isinstance(record, dict) or not isinstance(record.get("deployment_id"), str):
                    continue
                record = dict(record)
                record["_cache_path"] = entry.path
                records[record["deployment_id"]].append(record)
                mtime = entry.stat().st_mtime
                newest = mtime if newest is None or mtime > newest else newest
        stamps["run cache"] = _stamp(cache, now)
        if newest is not None:
            moment = datetime.fromtimestamp(newest).astimezone()
            stamps["run cache"].update(modified=moment.isoformat(timespec="seconds"),
                                       age_h=round((now - moment).total_seconds() / 3600, 1))
        return cls(fixtures, cache, listing, sessions, days, dict(records), stamps, problems)

    def deployment(self, child: str) -> dict[str, Any] | None:
        """``can12`` -> the ``can12-…`` deployment."""

        return next((d for d in self.listing if d["id"] == child or d["id"].startswith(child + "-")), None)

    def session_rows(self, dep_id: str) -> list[dict[str, Any]]:
        """Sessions oldest first: the fixture's periods, plus cache sessions the frozen fixture predates.

        Each row: {name, start, end, real, sim, aborted, kpis: {key: raw or None}, from: fixture|cache, note}.
        """

        rows: dict[str, dict[str, Any]] = {}
        for period in (self.sessions.get(dep_id) or {}).get("periods") or []:
            if not isinstance(period, dict) or not isinstance(period.get("period"), str):
                continue
            counts = period.get("counts") or {}
            rows[period["period"]] = {
                "name": period["period"], "start": period.get("start"), "end": period.get("end"),
                "real": counts.get("real"), "sim": counts.get("sim"), "aborted": counts.get("aborted"),
                "kpis": dict(period.get("kpis") or {}), "from": "fixture", "note": None,
            }
        by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in self.records.get(dep_id, []):
            by_session[record.get("session") or record.get("bundle") or "?"].append(record)
        dep = next((d for d in self.listing if d["id"] == dep_id), {}) or {}
        latest, latest_period = dep.get("latest") or {}, dep.get("latest_period") or {}
        fixture_days = {(row["start"] or "")[:10] for row in rows.values()}
        cache_days: dict[str, set[str]] = defaultdict(set)
        for name, recs in by_session.items():
            for rec in recs:
                cache_days[rec.get("day") or ""].add(name)
        for name, recs in by_session.items():
            if name in rows:
                continue
            starts = sorted(r["started_at"] for r in recs if isinstance(r.get("started_at"), str))
            day = recs[0].get("day") or (starts[0][:10] if starts else None)
            real = sum(1 for r in recs if r.get("environment") == "real" and not r.get("aborted"))
            sim = sum(1 for r in recs if r.get("environment") == "sim" and not r.get("aborted"))
            aborted = sum(1 for r in recs if r.get("aborted"))
            kpis: dict[str, Any] = {"real_runs": real, "sim_runs": sim, "aborted_runs": aborted}
            # WHY the day value may stand in for the session: deployments.json's ``latest`` is the newest DAY's
            # value, and when this session is the only one on that day (and the session fixture has none), the
            # day's median over its runs is exactly the session's. Anything else stays a gap.
            only_session = day is not None and cache_days.get(day) == {name} and day not in fixture_days
            used = []
            for key in (*REAL_KEYS, "floor_real_vs_real", *TWIN_KEYS):
                if only_session and latest_period.get(key) == day and latest.get(key) is not None:
                    kpis[key] = latest[key]
                    used.append(key)
                else:
                    kpis[key] = None
            rows[name] = {
                "name": name, "start": starts[0] if starts else None, "end": starts[-1] if starts else None,
                "real": real, "sim": sim, "aborted": aborted, "kpis": kpis, "from": "cache",
                "note": ("not in the kpis_session fixture; counts from the run cache"
                         + (f"; {', '.join(used)} from deployments.json latest (day {day}, its only session)" if used else "")),
                "day_keys": used,
            }
        return sorted(rows.values(), key=lambda row: (row["start"] or "", row["name"]))

    def kpi_defs(self, dep_id: str) -> list[dict[str, Any]]:
        for table in (self.sessions.get(dep_id), self.days.get(dep_id)):
            if isinstance(table, dict) and isinstance(table.get("kpi_defs"), list):
                return [d for d in table["kpi_defs"] if isinstance(d, dict) and isinstance(d.get("key"), str)]
        return []

    def twin_readings(self) -> list[dict[str, Any]]:
        """Every twin session with a held-out gap, over all deployments: {dep, session, version, start, gap, ratio, from}."""

        found = []
        for dep in self.listing:
            for row in self.session_rows(dep["id"]):
                gap = row["kpis"].get("twin_fidelity_gap")
                if gap is None or not row["start"]:
                    continue
                version = row["name"].split("__twin-")[1].split("__")[0] if "__twin-" in row["name"] else row["name"]
                found.append({"dep": dep["id"], "session": row["name"], "version": version, "start": _ts(row["start"]),
                              "gap": round(gap * DEG, 3), "ratio": row["kpis"].get("twin_tracking_ratio"),
                              "from": row["from"], "note": row["note"], "replays": row["sim"]})
        return sorted(found, key=lambda r: r["start"])

    def freshness_note(self, *names: str) -> str:
        parts = []
        for name in names:
            stamp = self.stamps.get(name)
            if stamp and stamp.get("modified"):
                parts.append(f"{name} written {local_time(stamp['modified'])} ({stamp['age_h']} h before this build)")
            else:
                parts.append(f"{name} missing")
        return "; ".join(parts)


# --------------------------------------------------------------------------------------------- the rig track


def _gate_from_ladder(ladder: dict[str, Any] | None) -> tuple[float | None, str | None]:
    """The TW2 gate, parsed from its rung title ("Two-knob twin ≤ 0.8° held-out")."""

    for axis in (ladder or {}).get("axes") or []:
        for rung in axis.get("rungs") or []:
            if rung.get("id") == "TW2":
                match = GATE_RE.search(rung.get("title") or "")
                if match:
                    return float(match.group(1)), rung.get("status")
    return None, None


def _disk_readings(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    readings = []
    for row in events:
        if row.get("kind") not in ("triage_changed", "note"):
            continue
        detail = row.get("detail") or ""
        match = DISK_RE.search(detail)
        if not match:
            continue
        free = FREE_RE.search(detail)
        # WHY the "triage" prefix: triage ids (T1, T12) and tick ids (T1, T4) share a letter; unprefixed, "T1" reads as a tick
        subject = f"triage {row.get('subject')}" if row.get("kind") == "triage_changed" else str(row.get("subject"))
        readings.append({"ts": row["_ts"], "pct": float(match.group(1)), "free_gb": float(free.group(1)) if free else None,
                         "detail": detail, "subject": subject})
    return readings


def _disk_limit(roadmap: str | None, triage: dict[str, Any] | None) -> tuple[float | None, str | None]:
    """The disk stop line: ROADMAP.md's preflight ("`/` under 92%"), else triage T1's title ("halt at 92%")."""

    try:
        text = Path(roadmap).read_text(encoding="utf-8") if roadmap else ""
    except OSError:
        text = ""
    match = re.search(r"under\s+(\d{1,3})\s*%", text)
    if match:
        return float(match.group(1)), "ROADMAP.md tick preflight"
    for item in (triage or {}).get("items") or []:
        match = re.search(r"halt at (\d{1,3})\s*%", item.get("title") or "")
        if match:
            return float(match.group(1)), f"triage {item.get('triage_id')}"
    return None, None


def _needs_you(status: dict[str, Any], triage: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    """(needs_you, needs_you_count or None to let the build count, source): every open triage item, no-default first."""

    items = [i for i in (triage or {}).get("items") or [] if isinstance(i, dict) and i.get("status") == "open"]
    if items:
        def no_default(item: dict[str, Any]) -> bool:
            return str(item.get("default") or "").lower().startswith("no default") or not item.get("default")

        def order(item: dict[str, Any]) -> tuple:
            digits = re.sub(r"\D", "", str(item.get("triage_id"))) or "0"
            return (not no_default(item), not item.get("blocks"), int(digits))

        out = []
        for item in sorted(items, key=order):
            after = item.get("default_applies_after_wave")
            out.append({
                "id": item.get("triage_id"),
                "q": item.get("title") or item.get("question") or "",
                "blocks": list(item.get("blocks") or []),
                "default": None if no_default(item) else item.get("default"),
                "applies": f"after T{after}" if isinstance(after, int) and not no_default(item) else None,
            })
        return out, None, "triage.json"
    # Fallback: loop-status keeps three no-default slots; an overflowing one is listed as a blocker ("Needs you, no
    # default: T17 …"). It does not carry the defaulting questions' text, so the open total is unknown here.
    out = [{"id": n.get("id"), "q": n.get("q") or "", "blocks": [], "default": None, "applies": None}
           for n in status.get("needs_you") or [] if isinstance(n, dict)]
    for blocker in status.get("blockers") or []:
        match = re.match(r"Needs you, no default:\s*(T\d+)\s*(.*)", str(blocker))
        if match:
            out.append({"id": match.group(1), "q": match.group(2), "blocks": [], "default": None, "applies": None})
    return out, {"open": None, "blocking": None}, "loop-status.json (triage.json unreadable)"


# --------------------------------------------------------------------------------------------- robot KPIs (KPI table)

KPI_TABLE_SCHEMA = "bam-deployments/kpi-table/1"
PLAYBACK_SCHEMA = "bam-playback-index/1"
TWIN_BACKEND = "mujoco_twin_replay"
REAL_BACKEND = "real"
#: Zach's robot KPIs, in his order (KPI-VIEW brief, 2026-10-06; DP - Reality as Oracle l.162-164): net tracking error
#: (RMS, p95), the feedback term (its proxy), the sim-to-real gap (twin fidelity, with its gate), the repeatability
#: floor, and how long since reality was last asked. The first five are export keys; the last is computed from the
#: export's real rows' dates.
ROBOT_KPIS = ("real_tracking_rms", "real_tracking_p95", "feedback_torque_proxy", "twin_fidelity_gap",
              "floor_real_vs_real", "days_since_real_run")
ROBOT_SLOTS = {"real_tracking_rms": "S1", "real_tracking_p95": "S3", "feedback_torque_proxy": "S3",
               "twin_fidelity_gap": "S2", "floor_real_vs_real": "S5", "days_since_real_run": "S3"}
#: The loop's own numbers (rungs green, packages landed, audits, elapsed hours, disk, open questions) stay, in a
#: collapsed "Loop health" group under the robot KPIs.
KPI_GROUPS = (
    {"id": "robot", "label": "Robot KPIs", "collapsed": False,
     "note": "What the rig is for: tracking error, the feedback term, the twin's gap to reality, the floor."},
    {"id": "loop_health", "label": "Loop health", "collapsed": True,
     "note": "The agent loop's own numbers: rungs, packages, audits, hours, disk, open questions."},
)
#: A KPI the export does not carry is still listed (truth rule 2); this is its label then.
ROBOT_FALLBACK_LABELS = {"real_tracking_rms": "Real tracking error (RMS)", "real_tracking_p95": "Real tracking error (p95)",
                         "feedback_torque_proxy": "Feedback torque (proxy)",
                         "twin_fidelity_gap": "Twin fidelity gap (held-out)", "floor_real_vs_real": "Floor (relative repeat)"}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _deployment_label(child: str) -> str:
    """``can12`` -> ``CAN 12`` (the rig's servo naming); any other id verbatim."""

    match = re.fullmatch(r"can(\d+)", child)
    return f"CAN {match.group(1)}" if match else child


def _belongs(deployment_id: Any, child: str) -> bool:
    return isinstance(deployment_id, str) and (deployment_id == child or deployment_id.startswith(child + "-"))


def _export_command(folder: str, docs: str | None) -> str:
    """The one line that (re)writes the export: bam_deployments lives beside its KPIS.md (``rig_kpi_docs``)."""

    if docs:
        return (f"env -u VIRTUAL_ENV uv run --directory {os.path.dirname(docs)} python -m bam_deployments export "
                f"{folder}")
    return f"python -m bam_deployments export {folder}"


def _playback_command(folder: str, viewer: str | None, deployment_id: str) -> str:
    """The one line that (re)writes the batch: bam_runtime is the project whose venv holds the viewer."""

    if viewer:
        runtime = Path(viewer).parents[2]
        return (f"env -u VIRTUAL_ENV uv run --directory {runtime} --extra viz python -m bam_runtime.playback "
                f"{deployment_id} --out {folder}")
    return f"python -m bam_runtime.playback {deployment_id} --out {folder}"


def _kpi_table(sources: dict[str, str], children: list[str]) -> dict[str, Any]:
    """The projection's ``kpi_table`` block: the export's rows and defs VERBATIM, plus where they came from.

    ``state`` is ``ok``, ``missing`` (not declared, or no ``kpi_table.json`` yet) or ``unreadable`` (not JSON, not the
    kpi-table schema, no rows/kpi_defs list); a block that is not ``ok`` has no rows and its ``message`` says why,
    with ``command`` the line that writes the export.
    """

    folder = sources.get(KPI_TABLE_KEY)
    block: dict[str, Any] = {
        "state": "missing", "dir": folder, "json": None, "csv": None, "message": None, "command": None,
        "schema": None, "contract": None, "granularity": None, "generated_at": None, "generated_label": None,
        "cache": None, "kpi_defs": [], "settings_keys": [], "rows": [], "deployments": {}, "headline": None, "doc": None,
    }
    if not folder:
        block["message"] = f"{KPI_TABLE_KEY} is not declared in vibe-sources, so no KPI table is read."
        return block
    block["command"] = _export_command(folder, sources.get(KPI_DOCS_KEY))
    path = os.path.join(folder, "kpi_table.json")
    block["json"] = path
    doc, error = _read_json(path)
    if error == "missing":
        block["message"] = f"No KPI table export at {folder} yet."
        return block
    if error:
        reason = error
    elif not isinstance(doc, dict):
        reason = "is not a JSON object"
    elif doc.get("schema") != KPI_TABLE_SCHEMA:
        reason = f"has schema {doc.get('schema')!r}, not {KPI_TABLE_SCHEMA!r}"
    elif not isinstance(doc.get("rows"), list) or not isinstance(doc.get("kpi_defs"), list):
        reason = "has no rows or kpi_defs list"
    else:
        reason = None
    if reason:
        block.update(state="unreadable", message=f"kpi_table.json {reason}.")
        return block
    rows = doc["rows"]
    settings_keys: list[str] = []
    for row in rows:
        settings = row.get("settings") if isinstance(row, dict) else None
        for key in settings if isinstance(settings, dict) else ():
            if key not in settings_keys:
                settings_keys.append(key)
    deployments: dict[str, str] = {}
    for row in rows:
        dep = row.get("deployment_id") if isinstance(row, dict) else None
        if isinstance(dep, str) and dep not in deployments:
            deployments[dep] = next((child for child in children if _belongs(dep, child)), dep)
    csv = os.path.join(folder, "kpi_table.csv")
    generated = doc.get("generated_at")
    block.update(
        state="ok", csv=csv if os.path.isfile(csv) else None, schema=doc.get("schema"), contract=doc.get("contract"),
        granularity=doc.get("granularity"), generated_at=generated,
        generated_label=local_time(generated) if isinstance(generated, str) else None, cache=doc.get("cache"),
        kpi_defs=doc["kpi_defs"], settings_keys=settings_keys, rows=rows, deployments=deployments,
    )
    return block


def _headline_rows(rows: list[Any], child: str) -> dict[str, Any]:
    """The rows the headline reads, by index: the newest twin replay, the oldest one, and the real row.

    The real row is the one at the newest twin's own setting (same control mode, settings equal): the setting the twin
    is held to, so tracking error, feedback term, floor and twin gap are like for like. Without such a row (or without
    a twin row), the real row with the most real runs (ties: the newest end, then the later row).
    """

    mine = [(index, row) for index, row in enumerate(rows) if isinstance(row, dict) and _belongs(row.get("deployment_id"), child)]
    twins = [(index, row) for index, row in mine if row.get("backend") == TWIN_BACKEND]
    reals = [(index, row) for index, row in mine
             if row.get("backend") == REAL_BACKEND and (_number((row.get("counts") or {}).get("real")) or 0) > 0]
    newest = max(twins, key=lambda pair: (str(pair[1].get("end") or ""), pair[0])) if twins else None
    oldest = min(twins, key=lambda pair: (str(pair[1].get("start") or ""), pair[0])) if twins else None

    def most(pairs: list[tuple[int, dict[str, Any]]]) -> tuple[int, dict[str, Any]]:
        return max(pairs, key=lambda pair: (_number((pair[1].get("counts") or {}).get("real")) or 0,
                                            str(pair[1].get("end") or ""), pair[0]))

    real, rule = None, None
    if newest is not None:
        same = [pair for pair in reals if pair[1].get("control_mode") == newest[1].get("control_mode")
                and pair[1].get("settings") == newest[1].get("settings")]
        if same:
            real, rule = most(same), "twin setting"
    if real is None and reals:
        real, rule = most(reals), "most real runs"
    return {"real": real[0] if real else None, "rule": rule, "twin": newest[0] if newest else None,
            "twin_baseline": oldest[0] if oldest and newest and oldest[0] != newest[0] else None}


def _settings_words(row: dict[str, Any]) -> str:
    """'ff_fb · gravity · torque cap 6.3754 N·m · kp 43.3253 · kd 10.8313 · friction FF on (Coulomb 0.65 N·m)'."""

    settings = row.get("settings") if isinstance(row.get("settings"), dict) else {}
    parts = [str(row.get("control_mode"))] if row.get("control_mode") else []
    if settings.get("mounting") is not None:
        parts.append(str(settings["mounting"]))
    if settings.get("torque_cap_nm") is not None:
        parts.append(f"torque cap {settings['torque_cap_nm']} N·m")
    for gain in ("kp", "kd"):
        if settings.get(gain) is not None:
            parts.append(f"{gain} {settings[gain]}")
    if settings.get("friction_ff") is not None:
        parts.append("friction FF " + ("on" if settings["friction_ff"] else "off")
                     + (f" (Coulomb {settings['coulomb_friction_nm']} N·m)" if settings.get("coulomb_friction_nm") is not None else ""))
    return " · ".join(parts)


def _days_between(day_text: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(day_text)[:10])).days
    except ValueError:
        return None


def _robot_kpis(table: dict[str, Any], child: str, ids: list[str], ticks: "Ticks", now: datetime,
                gate: float | None, tw2_status: str | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The six robot KPIs (group ``robot``), and the headline block for ``kpi_table.headline``.

    Each export KPI holds ONE reading, the export's current value, at the latest iteration (the column the page
    emphasises); every earlier tick is null with a note, because the export keeps no per-tick history (the history of
    settings and twin versions is the table itself). Days since a real run has a per-tick series: each tick's last
    event day (the current tick: today) minus the newest real row's end day at or before it.
    """

    latest = ids[-1]
    who = _deployment_label(child)
    rows = table["rows"]
    ok = table["state"] == "ok"
    defs = {d["key"]: d for d in table["kpi_defs"] if isinstance(d, dict) and isinstance(d.get("key"), str)}
    pick = _headline_rows(rows, child) if ok else {"real": None, "rule": None, "twin": None, "twin_baseline": None}
    real = rows[pick["real"]] if pick["real"] is not None else None
    twin = rows[pick["twin"]] if pick["twin"] is not None else None
    base_twin = rows[pick["twin_baseline"]] if pick["twin_baseline"] is not None else None
    computed = table.get("generated_label") or "time not recorded"
    missing_note = f"not measured: {table['message'] or 'no KPI table'}"
    earlier_note = "the KPI table holds today's reading only (no per-tick history); its rows are the history"
    kpis: list[dict[str, Any]] = []
    for key in ROBOT_KPIS[:5]:
        spec = defs.get(key) or {}
        label = f"{spec.get('label') or ROBOT_FALLBACK_LABELS[key]} · {who}"
        unit = BamLoopsAdapter._unit(str(spec.get("unit") or ("N·m" if key == "feedback_torque_proxy" else "deg")))
        scale = _number(spec.get("scale")) or 1.0
        source_row = twin if key == "twin_fidelity_gap" else real
        row_index = pick["twin"] if key == "twin_fidelity_gap" else pick["real"]
        raw = _number((source_row or {}).get("kpis", {}).get(key)) if isinstance((source_row or {}).get("kpis"), dict) else None
        value = raw * scale if raw is not None else None
        values = [_value(it, None, note=(missing_note if not ok else earlier_note)) for it in ids[:-1]]
        n = None
        if source_row is None:
            note = missing_note if not ok else (f"not measured: the KPI table has no {'twin replay' if key == 'twin_fidelity_gap' else 'real'} row for {who}")
            values.append(_value(latest, None, note=note))
        elif value is None:
            values.append(_value(latest, None, note=f"not measured: the KPI table's {source_row.get('period')} row has no {key}"))
        else:
            if key in ("real_tracking_rms", "real_tracking_p95", "feedback_torque_proxy"):
                n = _number((source_row.get("counts") or {}).get("real"))
                n = int(n) if n is not None else None
            when = local_time(source_row.get("start")) + " – " + local_time(source_row.get("end"))
            values.append(_value(latest, value, n=n, note=(
                f"current reading: {who} {source_row.get('backend')}"
                + (f" {source_row.get('twin_version')}" if source_row.get("twin_version") else "")
                + f" · {_settings_words(source_row)} · runs {when} · KPI table computed {computed}")))
        today = now.date()
        age = _days_between(source_row.get("end"), today) if source_row and value is not None else None
        day = str(source_row.get("end"))[5:10] if source_row and isinstance(source_row.get("end"), str) else None
        target, baseline = None, None
        if value is None:
            status = {"word": "not measured" + ("" if ok else " · no KPI table export" if table["state"] == "missing"
                                                 else " · KPI table unreadable"), "tone": "muted"}
        elif key == "twin_fidelity_gap":
            under = gate is not None and value <= gate
            status = {"word": ("under gate" if under else "above gate" if gate is not None else "no gate parsed")
                      + (" · TW2 green" if tw2_status == "green" else "") + f" · twin {source_row.get('twin_version')} · {day}",
                      "tone": "muted" if under or gate is None else "warn"}
            if gate is not None:
                target = {"value": gate, "kind": "gate", "label": f"TW2 gate ≤ {gate:g}°"}
            base_raw = _number((base_twin or {}).get("kpis", {}).get(key)) if base_twin and isinstance(base_twin.get("kpis"), dict) else None
            if base_raw is not None:
                placed = ticks.place(_ts(base_twin["start"]))[0] if isinstance(base_twin.get("start"), str) else 0
                baseline = {"iteration": ids[min(placed, len(ids) - 1)], "label": f"twin {base_twin.get('twin_version')}",
                            "value": base_raw * scale}
        elif key == "floor_real_vs_real":
            status = {"word": f"descriptive · measured {day}", "tone": "muted"}
            target = {"band": [0, value], "kind": "descriptive", "label": "descriptive band, never a verdict"}
        else:
            status = {"word": f"measured {day} · {age} days ago", "tone": "stale" if age is not None and age > 14 else "muted"}
        direction = "info" if key == "floor_real_vs_real" else "lower"
        if not ok:
            kpi_note = missing_note
        elif source_row is None:
            kpi_note = None
        else:
            why_row = ("the newest twin replay" if key == "twin_fidelity_gap" else
                       "the real row at the newest twin's own setting, so it is like for like with the twin gap"
                       if pick["rule"] == "twin setting" else "the real row with the most real runs")
            kpi_note = (f"From the KPI table (bam_deployments contract {table.get('contract')}, one row per deployment × "
                        f"backend × settings), row {source_row.get('period')}: {why_row}. Every other setting and backend "
                        "is in the table below.")
        kpi = _kpi(
            key, label, ROBOT_SLOTS[key], unit, direction, values, target=target, baseline=baseline, status=status,
            note=kpi_note,
            provenance=_prov(table.get("json"), f"/rows/{row_index}/kpis/{key}" if row_index is not None else None,
                             (f"kpi_defs scale {scale:g} × the export's value; headline row rule: "
                              + ("newest mujoco_twin_replay row by end" if key == "twin_fidelity_gap" else str(pick["rule"])))
                             if source_row is not None else "no KPI table row read" if ok else missing_note),
        )
        kpi["group"] = "robot"
        kpis.append(kpi)

    # days since a real run, per tick, from the export's real rows
    real_ends = sorted(str(row["end"])[:10] for row in rows if isinstance(row, dict) and row.get("backend") == REAL_BACKEND
                       and isinstance(row.get("end"), str) and (_number((row.get("counts") or {}).get("real")) or 0) > 0) if ok else []
    days_values = []
    for n_tick, it in enumerate(ids):
        tick = ticks.ticks[n_tick]
        if not ok:
            days_values.append(_value(it, None, note=missing_note))
            continue
        if it == latest:
            day = now.date()
            how = "today"
        elif tick.events:
            day = tick.last.date()
            how = f"the tick's last event ({day.isoformat()[5:]})"
        else:
            days_values.append(_value(it, None, note="no event recorded for this tick"))
            continue
        before = [end for end in real_ends if end <= day.isoformat()]
        if not before:
            days_values.append(_value(it, None, note="no real run in the KPI table at or before this tick"))
            continue
        days_values.append(_value(it, (day - date.fromisoformat(before[-1])).days,
                                  note=f"{how} − the newest real row's end ({before[-1][5:]})"))
    last_days = days_values[-1]["value"]
    kpi = _kpi(
        "days_since_real_run", "Days since a real run", ROBOT_SLOTS["days_since_real_run"], "days", "lower", days_values,
        status={"word": f"{last_days} days · last real run {real_ends[-1][5:]}" if last_days is not None and real_ends else "not measured",
                "tone": "warn" if last_days is not None and last_days > 14 else "muted"},
        note="Days since reality was last asked: the newest end of any real row in the KPI table (every deployment). "
             "Only a bench window moves the real KPIs above." if ok else missing_note,
        provenance=_prov(table.get("json"), "/rows/*/end", "tick day minus the newest real row's end day (rows with real runs)"),
    )
    kpi["group"] = "robot"
    kpis.append(kpi)
    headline = None
    if ok:
        headline = {"deployment": child, "label": who, "real_row": pick["real"], "twin_row": pick["twin"],
                    "twin_baseline_row": pick["twin_baseline"], "rule": pick["rule"]}
    return kpis, headline


def _playbacks(sources: dict[str, str], media: MediaIndex, deployment_id: str) -> dict[str, Any]:
    """The projection's ``playbacks`` block: one entry per ``index.json`` run, grouped by session (first-appearance
    order; runs in index order), each with the one-line command that opens its ``.rrd`` in the Rerun viewer."""

    folder = sources.get(PLAYBACKS_KEY)
    viewer = sources.get(VIEWER_KEY)
    block: dict[str, Any] = {
        "state": "missing", "dir": folder, "index": None, "viewer": viewer,
        "viewer_exists": bool(viewer) and os.path.isfile(viewer), "message": None, "command": None,
        "schema": None, "deployment_id": None, "count": 0, "group_by": "session", "groups": [],
    }
    if not folder:
        block["message"] = f"{PLAYBACKS_KEY} is not declared in vibe-sources, so no playbacks are read."
        return block
    path = os.path.join(folder, "index.json")
    block["index"] = path
    doc, error = _read_json(path)
    dep = doc.get("deployment_id") if isinstance(doc, dict) and isinstance(doc.get("deployment_id"), str) else deployment_id
    block["command"] = _playback_command(folder, viewer, dep)
    if error == "missing":
        block["message"] = f"No Rerun playbacks at {folder} yet."
        return block
    if error:
        reason = error
    elif not isinstance(doc, dict):
        reason = "is not a JSON object"
    elif doc.get("schema") != PLAYBACK_SCHEMA:
        reason = f"has schema {doc.get('schema')!r}, not {PLAYBACK_SCHEMA!r}"
    elif not isinstance(doc.get("runs"), list):
        reason = "has no runs list"
    else:
        reason = None
    if reason:
        block.update(state="unreadable", message=f"index.json {reason}.")
        return block
    groups: dict[str, dict[str, Any]] = {}
    count = 0
    for run in doc["runs"]:
        if not isinstance(run, dict) or not isinstance(run.get("run_id"), str):
            continue
        session = str(run.get("session") or run["run_id"].split("/")[0])
        file = run.get("file")
        rrd = os.path.join(folder, file) if isinstance(file, str) and file else None
        video_path = run.get("video_path") if isinstance(run.get("video_path"), str) else None
        video = media.add(video_path, "video", f"Real · {run.get('trajectory')}",
                          media_id=f"rig.playback.{run['run_id'].replace('/', '.')}") if video_path else None
        entry = {
            "run_id": run["run_id"], "trajectory": run.get("trajectory"), "session": run.get("session"),
            "started_at": run.get("started_at"),
            "started_label": local_time(run.get("started_at")) if isinstance(run.get("started_at"), str) else None,
            "control_mode": (run.get("settings") or {}).get("control_mode") if isinstance(run.get("settings"), dict) else None,
            "twin_versions": run.get("twin_versions") if isinstance(run.get("twin_versions"), list) else [],
            "twin_vs_real_rms_rad": run.get("twin_vs_real_rms_rad") if isinstance(run.get("twin_vs_real_rms_rad"), dict) else {},
            "file": file, "rrd": rrd, "rrd_exists": bool(rrd) and os.path.isfile(rrd), "size_bytes": run.get("size_bytes"),
            "command": f"{viewer} {rrd}" if viewer and rrd else None,
            "video_path": video_path, "video": video,
        }
        group = groups.setdefault(session, {"id": session, "label": BamLoopsAdapter._session_label(session, ""),
                                            "count": 0, "twin_runs": 0, "runs": []})
        group["runs"].append(entry)
        group["count"] += 1
        group["twin_runs"] += 1 if entry["twin_versions"] else 0
        count += 1
    block.update(state="ok", schema=doc.get("schema"), deployment_id=doc.get("deployment_id"), count=count,
                 groups=list(groups.values()))
    if not block["viewer_exists"]:
        block["message"] = (f"The Rerun viewer is not at {viewer}; the commands name it anyway." if viewer
                            else f"{VIEWER_KEY} is not declared in vibe-sources, so no command names a viewer.")
    return block


def _doc_links(sources: dict[str, str], table: dict[str, Any], media: MediaIndex) -> list[dict[str, Any]]:
    """The KPI doc, the KPI table CSV and the living report, in that order (a file that is not there says so)."""

    links: list[dict[str, Any]] = []
    docs = sources.get(KPI_DOCS_KEY)
    if docs:
        doc_id = media.add(docs, "text", "KPI doc (KPIS.md)", media_id="rig.kpis-doc")
        links.append({"label": "KPI doc (KPIS.md)", "kind": "media", "media": doc_id} if doc_id else
                     {"label": "KPI doc (KPIS.md, not written yet)", "kind": "path", "value": docs})
    if table.get("csv"):
        links.append({"label": "KPI table CSV", "kind": "path", "value": table["csv"]})
    report = sources.get(REPORT_KEY)
    if report:
        report_id = media.add(report, "html", "Living report", media_id="rig.living-report")
        links.append({"label": "Living report", "kind": "media", "media": report_id} if report_id else
                     {"label": "Living report (missing)", "kind": "path", "value": report})
    return links


def build_track(work_track: Any, sources: dict[str, str]) -> dict[str, Any]:
    now = _now()
    status_path = sources.get("rig_loop_status")
    status, error = _read_json(status_path)
    if error or not isinstance(status, dict):
        return not_reporting(work_track, f"loop-status.json {error or 'is not an object'}")
    tick_block = status.get("tick") or {}
    if not isinstance(tick_block.get("n"), int):
        return not_reporting(work_track, "loop-status.json has no tick.n")
    events, bad_lines, events_error = _read_events(sources.get("rig_events"))
    ladder, ladder_error = _read_json(sources.get("rig_ladder"))
    ladder = ladder if isinstance(ladder, dict) else None
    triage, _ = _read_json(sources.get("rig_triage"))
    triage = triage if isinstance(triage, dict) else None
    deployments = Deployments.load(sources, now)

    ticks = Ticks(events, tick_block["n"])
    ids = ticks.ids
    current = ticks.current
    phase = tick_block.get("phase") or "unknown"
    rate = (status.get("rate") or {})
    moved_rate = rate.get("rungs_moved_per_tick") if isinstance(rate.get("rungs_moved_per_tick"), list) else []
    ev = Evidence()
    media = MediaIndex()
    # WHY no default folder: an undeclared folder can change without the build noticing (ADAPTERS.md).
    audits_dir = AuditFiles(Path(sources["rig_audits_dir"]) if sources.get("rig_audits_dir") else None)
    events_src = sources.get("rig_events")
    ladder_src = sources.get("rig_ladder")

    def rate_for(n: int) -> int | None:
        # rungs_moved_per_tick holds the LAST len(rate) ticks, ending at loop-status tick.n
        index = n - (ticks.loop_current - len(moved_rate) + 1)
        return moved_rate[index] if 0 <= index < len(moved_rate) else None

    def media_for(rel: str | None, label: str) -> list[dict[str, str]]:
        if not rel or not isinstance(rel, str) or rel.endswith("-prompt.md"):
            return []
        path = Path(rel) if rel.startswith("/") else BAM_WS_ROOT / rel
        if path.suffix not in (".md", ".html", ".png", ".webp", ".jpg", ".mp4", ".json", ".txt"):
            return []
        return media.ref(media.add(path, "text" if path.suffix in (".md", ".txt", ".json") else
                                   "html" if path.suffix == ".html" else "video" if path.suffix == ".mp4" else "image",
                                   label, media_id=f"rig.{path.stem}"))

    # ---------------------------------------------------------------- rungs green per tick
    rungs = {r["id"]: (axis, r) for axis in (ladder or {}).get("axes") or [] for r in axis.get("rungs") or []
             if isinstance(r, dict) and isinstance(r.get("id"), str)}
    packages = {p["id"]: p for p in (ladder or {}).get("packages") or [] if isinstance(p, dict) and isinstance(p.get("id"), str)}
    rung_changes: dict[str, list[tuple[int, str, datetime]]] = defaultdict(list)
    for tick in ticks.ticks:
        for row in tick.of("rung_status_changed"):
            rung_changes[str(row.get("subject"))].append((tick.n, str(row.get("status")), row["_ts"]))
    placed_green: dict[str, tuple[int, str]] = {}  # ladder-green rungs with no event: tick + why
    for rung_id, (_axis, rung) in rungs.items():
        if rung.get("status") == "green" and not any(s == "green" for _, s, _ in rung_changes.get(rung_id, [])):
            landed = [_ts(packages[p]["updated"]) for p in rung.get("packages") or []
                      if p in packages and packages[p].get("status") == "landed" and packages[p].get("updated")]
            if landed:
                n, note = ticks.place(max(landed))
                placed_green[rung_id] = (n, f"{rung_id}: no rung_status_changed event; placed by its last package landing "
                                            f"({_hm(max(landed))})" + (f", {note}" if note else ""))
            else:
                placed_green[rung_id] = (current, f"{rung_id}: no event and no landed package; counted at the current tick")
    green_series: list[int | None] = []
    for n in range(current + 1):
        count = 0
        for rung_id in set(rung_changes) | set(placed_green):
            states = [s for t, s, _ in rung_changes.get(rung_id, []) if t <= n]
            if rung_id in placed_green and placed_green[rung_id][0] <= n:
                states.append("green")
            if states and states[-1] == "green":
                count += 1
        green_series.append(count)
    total_rungs = len(rungs) or None
    ladder_green = sum(1 for _, r in rungs.values() if r.get("status") == "green") if rungs else None
    # WHY (audit 2026-10-04, finding 4): with no ladder rungs and no rung_status_changed event, the fold above counts
    # nothing and green_series is all 0. That 0 was emitted as measured ("0 of None"), with a note citing the status
    # file's rate, a source the count never used. Unknown is null, said with its reason.
    ladder_why = f"ladder.json {ladder_error}" if ladder_error else ("ladder.json has no rungs" if ladder is not None
                                                                     else "ladder.json is not an object")
    events_why = (f"loop_events.jsonl {events_error}" if events_error
                  else "loop_events.jsonl has no rung_status_changed event")
    green_established = bool(rungs) or bool(rung_changes)
    unmeasured_note = f"not measured: {ladder_why} and {events_why}, so no rung count can be established"
    green_values = []
    for n, it in enumerate(ids):
        tick = ticks.ticks[n]
        if not green_established:
            green_values.append(_value(it, None, note=unmeasured_note))
            continue
        note = None
        if not tick.events and n > 0:
            note = "no event recorded for this tick; carried from the previous tick" + (
                f" (loop-status rate: {rate_for(n)} rungs moved)" if rate_for(n) is not None else "")
        placed_here = [why for (t, why) in placed_green.values() if t == n]
        if placed_here:
            note = "; ".join(filter(None, [note, *placed_here]))
        green_values.append(_value(it, green_series[n], of=total_rungs, note=note))
    if ladder_green is not None and green_series and green_series[-1] != ladder_green:
        green_values[-1]["value"] = ladder_green
        green_values[-1]["note"] = "; ".join(filter(None, [green_values[-1]["note"],
                                                           f"ladder.json says {ladder_green}; the events rebuild {green_series[-1]}"]))
    axis_line = " · ".join(f"{axis.get('id')} {sum(1 for r in axis.get('rungs') or [] if r.get('status') == 'green')}/{len(axis.get('rungs') or [])}"
                           for axis in (ladder or {}).get("axes") or [])
    where_line = " · ".join(f"{w.get('axis')} at {w.get('here')}" + (f" → {w['next']}" if w.get("next") else " (done)")
                            for w in status.get("where") or [] if isinstance(w, dict))
    last_green, previous_green = (green_values[-1]["value"] if green_values else None,
                                  green_values[-2]["value"] if len(green_values) > 1 else None)
    delta = last_green - previous_green if last_green is not None and previous_green is not None else None
    if last_green is None:
        green_word = "not measured"
    else:
        green_word = (f"{last_green} of {total_rungs}" if total_rungs else f"{last_green} green (no ladder total)") + (
            f" · +{delta} in {ids[-1]}" if delta else "")
    kpis = [_kpi(
        "rungs_green", "Ladder rungs green", "S1", "rungs", "higher", green_values,
        target={"value": total_rungs, "kind": "scope", "label": f"of {total_rungs} rungs"} if total_rungs else None,
        baseline=({"iteration": "T0", "label": "bootstrap T0", "value": green_values[0]["value"]}
                  if green_values and green_values[0]["measured"] else None),
        status={"word": green_word, "tone": "ok" if delta else "muted"},
        note=(f"By axis: {axis_line}. Frontier: {where_line}." if axis_line else
              unmeasured_note if not green_established else f"{ladder_why}: no axis breakdown"),
        provenance=_prov(events_src, "/kind=rung_status_changed",
                         "rungs whose latest rung_status_changed at or before the tick is green; ladder-only greens placed "
                         "by their packages' landing time; the current tick is ladder.json's count"),
    )]

    # ---------------------------------------------------------------- robot KPIs: the KPI-table export (the oracle)
    # WHY these lead and the loop's numbers fold away (Zach, Daily Note - Oct 6 2026: "When I started this work we had
    # set up some very clear KPIs ... right now at a glance I cannot see that at all"): the page used to lead with 6
    # loop numbers (rungs, packages, audits, hours, disk, questions); his KPIs sat one click down per deployment.
    gate, tw2_status = _gate_from_ladder(ladder)
    headline_child = work_track.children[0] if work_track.children else "can12"
    table = _kpi_table(sources, list(work_track.children))
    robot, headline = _robot_kpis(table, headline_child, ids, ticks, now, gate, tw2_status)
    table["headline"] = headline
    blockers = [str(b) for b in status.get("blockers") or []]
    hardware_blocker = next((b for b in blockers if not b.startswith("Needs you")), None)
    days_kpi = robot[-1]
    days_kpi["note"] = "; ".join(filter(None, [days_kpi["note"], f"Blocker: {hardware_blocker}" if hardware_blocker else None,
                                               _episode_line(ladder)])) or None
    kpis = robot + kpis
    # Twin readings stay evidence, placed in the tick they happened in (the robot twin KPI holds today's reading).
    readings = deployments.twin_readings()
    by_tick: dict[int, list[tuple[dict[str, Any], str | None]]] = defaultdict(list)
    for reading in readings:
        n, note = ticks.place(reading["start"])
        by_tick[n].append((reading, note))

    # ---------------------------------------------------------------- delivery: packages landed per tick
    landed_by_tick: dict[int, list[tuple[str, str | None]]] = defaultdict(list)
    landed_seen: set[str] = set()
    for tick in ticks.ticks:
        for row in tick.of("lane_status"):
            subject = str(row.get("subject"))
            if row.get("status") == "landed" and subject not in landed_seen:
                landed_seen.add(subject)
                landed_by_tick[tick.n].append((subject, None))
    for pid, package in packages.items():
        if package.get("status") == "landed" and pid not in landed_seen and package.get("updated"):
            n, note = ticks.place(_ts(package["updated"]))
            landed_by_tick[n].append((pid, f"{pid}: no landed event; placed by ladder.json updated {_hm(_ts(package['updated']))}"
                                           + (f", {note}" if note else "")))
    total_packages = len(packages) or None
    building = sorted(pid for pid, p in packages.items() if p.get("status") == "building")
    landed_values = []
    for n, it in enumerate(ids):
        tick = ticks.ticks[n]
        here = landed_by_tick.get(n, [])
        if not tick.events and not here:
            landed_values.append(_value(it, None, note="no event recorded for this tick"))
            continue
        notes = [why for _, why in here if why]
        if here:
            notes.insert(0, ", ".join(pid for pid, _ in here))
        if n == current and building:
            notes.append("still building: " + ", ".join(building))
        landed_values.append(_value(it, len(here), of=total_packages, note="; ".join(notes) or None))
    landed_total = sum(1 for p in packages.values() if p.get("status") == "landed")
    kpis.append(_kpi(
        "packages_landed", "Packages landed", "S4", "packages", "count", landed_values,
        target={"value": total_packages, "kind": "scope", "label": f"of {total_packages} packages"} if total_packages else None,
        status={"word": f"{landed_total} of {total_packages} landed · {len(building)} building" if total_packages
                else f"no package total: {ladder_why}", "tone": "muted"},
        provenance=_prov(events_src, "/kind=lane_status,status=landed",
                         "first landed event per package; ladder-landed packages with no event placed by their updated time"),
    ))

    # ---------------------------------------------------------------- evidence trust: Codex audits per tick
    verdicts_all: dict[str, int] = defaultdict(int)
    audit_values = []
    for n, it in enumerate(ids):
        tick = ticks.ticks[n]
        rows = tick.of("audit")
        verdicts: dict[str, int] = defaultdict(int)
        for row in rows:
            verdicts[str(row.get("status"))] += 1
            verdicts_all[str(row.get("status"))] += 1
        if not tick.events:
            audit_values.append(_value(it, None, note="no event recorded for this tick"))
        else:
            audit_values.append(_value(it, len(rows), note=" · ".join(f"{v} {k}" for k, v in sorted(verdicts.items(), key=lambda kv: -kv[1])) or None))
    last_audit = next((row for row in reversed(events) if row.get("kind") == "audit"), None)
    kpis.append(_kpi(
        "audits", "Codex audits", "S5", "audits", "count", audit_values,
        status={"word": (f"last: {last_audit.get('subject')} {last_audit.get('status')} {_hm(last_audit['_ts'])}" if last_audit else "no audit yet"),
                "tone": "muted"},
        note=("All ticks: " + " · ".join(f"{v} {k}" for k, v in sorted(verdicts_all.items(), key=lambda kv: -kv[1])) + ". An UNSOUND verdict "
              "opens another round; it is the loop working, not a failure.") if verdicts_all else None,
        provenance=_prov(events_src, "/kind=audit", "audit rows per tick, by verdict"),
    ))

    # ---------------------------------------------------------------- cost: elapsed wall-clock hours, cumulative
    origin = ticks.recorded[0].first if ticks.recorded else None
    elapsed_values = []
    for n, it in enumerate(ids):
        tick = ticks.ticks[n]
        if n == ticks.loop_current and isinstance(rate.get("hours_spent"), (int, float)):
            elapsed_values.append(_value(it, rate["hours_spent"], note="loop-status rate.hours_spent"))
            continue
        if origin is None or not tick.events:
            elapsed_values.append(_value(it, None, note="no event recorded for this tick"))
            continue
        if tick.finished:
            end, how = tick.finished, "its wave_finished event"
        elif n + 1 < len(ticks.ticks) and ticks.ticks[n + 1].events:
            nxt = ticks.ticks[n + 1]
            end = nxt.started or nxt.first
            how = f"T{n + 1}'s " + ("wave_started" if nxt.started else "first event (it has no wave_started)")
        else:
            elapsed_values.append(_value(it, None, note=f"T{n + 1} recorded no event, so T{n}'s end is unknown"
                                        if n + 1 < len(ticks.ticks) else "tick still open"))
            continue
        elapsed_values.append(_value(it, round((end - origin).total_seconds() / 3600, 1), note=f"T0 start to {how}"))
    kpis.append(_kpi(
        "elapsed_h", "Elapsed hours (cumulative)", "S6", "h elapsed", "info", elapsed_values,
        status={"word": f"{rate.get('hours_spent')} h wall clock" if rate.get("hours_spent") is not None else "not reported",
                "tone": "muted"},
        note="Elapsed wall-clock hours since the bootstrap tick, never agent-hours."
             + (f" About {round(rate['hours_spent'] / rate['product_rungs_moved'], 1)} h elapsed per rung moved."
                if isinstance(rate.get("hours_spent"), (int, float)) and rate.get("product_rungs_moved") else ""),
        provenance=_prov(status_path, "/rate/hours_spent", "past ticks: T0's first event to the tick's end event"),
    ))

    # ---------------------------------------------------------------- health: disk, from the loop's own prose
    limit, limit_source = _disk_limit(sources.get("rig_roadmap"), triage)
    disk = _disk_readings(events)
    disk_by_tick: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for reading in disk:
        disk_by_tick[ticks.place(reading["ts"])[0]].append(reading)
    disk_values = []
    for n, it in enumerate(ids):
        here = disk_by_tick.get(n)
        if here:
            last = here[-1]
            disk_values.append(_value(it, last["pct"], note=f"{last['subject']} · {_hm(last['ts'])}"
                                      + (f" · {last['free_gb']:g} GB free" if last["free_gb"] is not None else "")))
        else:
            disk_values.append(_value(it, None, note="no disk reading in this tick"))
    if disk:
        newest = disk[-1]
        disk_status = {"word": f"{newest['pct']:g} % at {_hm(newest['ts'])} · {_age(newest['ts'], now)}",
                       "tone": "warn" if limit is not None and newest["pct"] >= limit else "muted"}
    else:
        disk_status = {"word": "not measured", "tone": "muted"}
    kpis.append(_kpi(
        "disk_pct", "Disk used on /", "S7", "%", "lower", disk_values,
        target={"value": limit, "kind": "limit", "label": f"ticks need / under {limit:g} % ({limit_source})"} if limit is not None else None,
        status=disk_status,
        note="The loop records df only in triage and note prose; this series parses it. No reading means none was written, not 0.",
        provenance=_prov(events_src, "/kind=triage_changed|note/detail", "percent parsed from 'Disk … N%' / '/ at N%' in event detail"),
    ))

    # ---------------------------------------------------------------- needs you
    needs_you, needs_count, needs_source = _needs_you(status, triage)
    no_default = sum(1 for n in needs_you if n["default"] is None)
    open_values = [_value(it, None, note="not recorded per tick") for it in ids[:-1]]
    open_values.append(_value(ids[-1], len(needs_you) if needs_count is None else None,
                              note=None if needs_count is None else "triage.json unreadable; only the no-default slots are known"))
    # WHY the adapter's count is provisional: build.py replaces this row's latest value and status with /needs'
    # counts (audit 2026-10-04, finding 5); len(needs_you) counts defaulting items too.
    kpis.append(_kpi(
        "open_questions", "Open questions", "S7", "questions", "lower", open_values,
        status={"word": f"{len(needs_you)} open · {no_default} with no default", "tone": "warn" if no_default else "muted"},
        note=f"From {needs_source}; the latest value is the Needs-you count. A question with no default holds its work "
             "until you answer it.",
        provenance=_prov(sources.get("rig_triage"), "/items/*/status", "items with status open, now"),
    ))

    # ---------------------------------------------------------------- evidence per tick
    for tick in ticks.ticks:
        it = f"T{tick.n}"
        if not tick.events:
            ev.add(it, "note", "No event carries this tick",
                   note=f"loop-status rate says {rate_for(tick.n)} rungs moved" if rate_for(tick.n) is not None else None,
                   kpis=["rungs_green"])
            continue
        for row in tick.of("wave_started") + tick.of("wave_finished"):
            ev.add(it, "note", f"{row.get('subject')} {row.get('status')}", when=row["ts"], note=row.get("detail"),
                   kpis=["elapsed_h"])
        for row in tick.of("rung_status_changed"):
            ev.add(it, "gate", f"{row.get('subject')} → {row.get('status')}", when=row["ts"], status=row.get("status"),
                   metrics={"commit": row.get("commit")} if row.get("commit") else None,
                   note=" · ".join(filter(None, [row.get("detail"), row.get("evidence")])), kpis=["rungs_green"])
        last_lane: dict[str, dict[str, Any]] = {}
        for row in tick.of("lane_status"):
            last_lane[str(row.get("subject"))] = row
        for subject, row in last_lane.items():
            package = packages.get(subject, {})
            files = [m for path in audits_dir.rig(subject, 99) for m in media.ref(media.add(path, "text", path.name, media_id=f"rig.{path.stem}"))]
            files += media_for(row.get("evidence"), str(row.get("evidence")))
            ev.add(it, "lane", f"{subject} · {package.get('title', '')}".strip(" ·"), when=row["ts"], status=row.get("status"),
                   metrics={k: v for k, v in (("rung", package.get("rung")), ("kind", package.get("kind")), ("commit", row.get("commit"))) if v},
                   media=files, note=row.get("detail"), kpis=["packages_landed"])
        for row in tick.of("audit"):
            ev.add(it, "audit", f"{row.get('subject')} audit", when=row["ts"], status=row.get("status"),
                   metrics={"commit": row.get("commit")} if row.get("commit") else None,
                   media=media_for(row.get("evidence"), str(row.get("evidence"))), note=row.get("detail"), kpis=["audits"])
        for row in tick.of("triage_changed"):
            ev.add(it, "note", f"Triage {row.get('subject')} {row.get('status')}", when=row["ts"], status=row.get("status"),
                   note=row.get("detail"), kpis=["open_questions"] + (["disk_pct"] if DISK_RE.search(row.get("detail") or "") else []))
        for row in tick.of("note"):
            ev.add(it, "note", f"{row.get('subject')} · {row.get('status')}", when=row["ts"], note=row.get("detail"),
                   kpis=["disk_pct"] if DISK_RE.search(row.get("detail") or "") else [])
    for n, items in landed_by_tick.items():
        for pid, why in items:
            if why:
                package = packages.get(pid, {})
                files = [m for path in audits_dir.rig(pid, 99) for m in media.ref(media.add(path, "text", path.name, media_id=f"rig.{path.stem}"))]
                ev.add(f"T{n}", "lane", f"{pid} · {package.get('title', '')}".strip(" ·"), when=package.get("updated"), status="landed",
                       metrics={k: v for k, v in (("rung", package.get("rung")), ("commit", package.get("commit"))) if v},
                       media=files, note="; ".join(filter(None, [package.get("note"), why])), kpis=["packages_landed"])
    for n, items in by_tick.items():
        for reading, note in items:
            ev.add(f"T{n}", "run", f"Twin {reading['version']} · held-out replays", when=reading["start"].isoformat(timespec="seconds"),
                   metrics={"held-out gap (°)": reading["gap"], "tracking ratio (×)": round(reading["ratio"], 3) if reading["ratio"] is not None else None,
                            "replays": reading["replays"]},
                   status=("under gate" if gate is not None and reading["gap"] <= gate else "above gate" if gate is not None else None),
                   note="; ".join(filter(None, [f"session {reading['session']} ({reading['dep']})", reading["note"], note])),
                   kpis=["twin_fidelity_gap"])
    if ladder:
        ev.add(ids[-1], "note", "Ladder by axis", metrics={a.get("id"): f"{sum(1 for r in a.get('rungs') or [] if r.get('status') == 'green')}/{len(a.get('rungs') or [])}"
                                                           for a in ladder.get("axes") or []},
               note=where_line or None, kpis=["rungs_green"])
    if table["state"] == "ok" and headline is not None:
        # One evidence item at the latest tick: the KPI-table rows the headline reads (a click on a robot cell opens it).
        rows = table["rows"]
        used = [(role, headline[key]) for role, key in (("real", "real_row"), ("twin", "twin_row"), ("twin baseline", "twin_baseline_row"))
                if headline[key] is not None]
        ev.add(ids[-1], "note", f"KPI table · {headline['label']} headline rows", item_id="rig-kpi-table-headline",
               when=table["generated_at"],
               metrics={f"{role} row": str(rows[index].get("period")) for role, index in used},
               links=[link for link in ([{"label": "KPI table CSV", "kind": "path", "value": table["csv"]}] if table["csv"] else [])
                      + [{"label": "kpi_table.json", "kind": "path", "value": table["json"]}]],
               note=f"Read from the export computed {table['generated_label'] or 'time not recorded'}; headline rule: {headline['rule']}.",
               kpis=list(ROBOT_KPIS))
    for kpi in kpis:
        kpi.setdefault("group", "loop_health")
    evidence = ev.attach(kpis)

    # ---------------------------------------------------------------- iterations
    iterations = []
    for tick in ticks.ticks:
        it = f"T{tick.n}"
        if not tick.events:
            moved = rate_for(tick.n)
            iterations.append({"id": it, "label": it, "date": None,
                               "marker": "no event recorded" + (f" · {moved} rungs moved (loop-status rate)" if moved is not None else ""),
                               "provenance": _prov(status_path, "/rate/rungs_moved_per_tick", "no row in loop_events.jsonl carries this wave")})
            continue
        parts = []
        if tick.n == ticks.loop_current and phase != "finished":
            parts.append(phase)
        elif tick.finished:
            parts.append("closed")
        greens = [str(r.get("subject")) for r in tick.of("rung_status_changed") if r.get("status") == "green"]
        greens += [rid for rid, (t, _) in placed_green.items() if t == tick.n]
        if landed_by_tick.get(tick.n):
            parts.append(f"{len(landed_by_tick[tick.n])} landed")
        if greens:
            parts.append("green " + ", ".join(greens))
        if tick.of("audit"):
            count = len(tick.of("audit"))
            parts.append(f"{count} audit" + ("s" if count != 1 else ""))
        iterations.append({"id": it, "label": it, "date": local_day(tick.started or tick.first),
                           "marker": " · ".join(parts),
                           "provenance": _prov(events_src, f"/wave={tick.n}",
                                               None if tick.started else "no wave_started row; dated by its first event")})

    # ---------------------------------------------------------------- state, summary, links
    now_lanes = [n for n in status.get("now") or [] if isinstance(n, dict)]
    current_tick = ticks.ticks[ticks.loop_current] if ticks.loop_current < len(ticks.ticks) else None
    since = (current_tick.started or current_tick.first).isoformat(timespec="seconds") if current_tick and current_tick.events else None
    word = {"running": "Running", "paused": "Paused", "idle": "Idle", "finished": "Finished"}.get(phase, phase.capitalize())
    detail_parts = [f"tick {ticks.loop_current}", f"{len(now_lanes)} lanes building" if now_lanes else None,
                    f"blocker: {blockers[0]}" if blockers else None]
    state = {"word": word, "tone": "warn" if blockers else ("ok" if phase == "running" else "muted"),
             "detail": " · ".join(p for p in detail_parts if p), "since": since}
    milestone = status.get("milestone") or (ladder or {}).get("milestone") or {}
    nxt = (status.get("next") or [None])[0]
    summary = (f"Tick {ticks.loop_current} {phase}: "
               + (f"{last_green} of {total_rungs} rungs green" if last_green is not None and total_rungs
                  else f"{last_green} rungs green (no ladder total)" if last_green is not None
                  else "rungs green not measured")
               + (f"; next: {nxt}" if nxt else "")
               + (f"; milestone '{milestone.get('title')}' due {milestone.get('due')}" if milestone.get("title") else "") + ".")
    links = []
    status_links = status.get("links") or {}
    if status_links.get("report"):
        report = Path(status_links["report"]) if str(status_links["report"]).startswith("/") else BAM_WS_ROOT / status_links["report"]
        report_id = media.add(report, "html", "Deployments dashboard report", media_id="rig.deployments-report")
        if report_id:
            links.append({"label": "Deployments dashboard report", "kind": "media", "media": report_id})
    if status_links.get("dashboard"):
        links.append({"label": "Deployments dashboard (Clank)", "kind": "command", "value": status_links["dashboard"]})
    if sources.get("rig_roadmap"):
        links.append({"label": "Roadmap (ROADMAP.md)", "kind": "path", "value": sources["rig_roadmap"]})
    # The KPI doc, the KPI table CSV and the living report lead the links (KPI-VIEW brief, item 4).
    links = _doc_links(sources, table, media) + links
    docs = sources.get(KPI_DOCS_KEY)
    table["doc"] = {"path": docs, "media": media.add(docs, "text", "KPI doc (KPIS.md)", media_id="rig.kpis-doc") if docs else None}
    deployment_id = next((dep for dep, child in table["deployments"].items() if child == headline_child), None) or (
        (deployments.deployment(headline_child) or {}).get("id") or headline_child)
    playbacks = _playbacks(sources, media, deployment_id)

    track = skeleton(work_track, unit="tick")
    inputs = [{"key": key, **_stamp(sources.get(key), now)} for key in ("rig_loop_status", "rig_events", "rig_ladder",
                                                                         "rig_triage", "rig_roadmap")]
    inputs += [{"key": f"deployments · {name}", **stamp} for name, stamp in deployments.stamps.items()]
    track.update(
        summary=summary,
        state=state,
        iteration={"unit": "tick", "label": f"tick {ticks.loop_current}" + (f" ({phase})" if phase else "")},
        rung=_rung(ladder),
        iterations=iterations,
        north_star="real_tracking_rms",
        kpis=kpis,
        kpi_groups=[dict(group) for group in KPI_GROUPS],
        kpi_table=table,
        playbacks=playbacks,
        needs_you=needs_you,
        evidence=evidence,
        links=links,
        media=media.items,
        provenance=_prov(status_path, "/", f"loop-status/1 generated {status.get('generated_at')}; head {tick_block.get('head')}"),
        source={"kind": "live", "live": True, "computed_at": now.isoformat(timespec="seconds"), "inputs": inputs,
                "problems": [p for p in ([f"loop_events.jsonl {events_error}" if events_error else None,
                                          f"{bad_lines} unparseable event lines" if bad_lines else None,
                                          f"ladder.json {ladder_error}" if ladder_error else None] + deployments.problems) if p]},
    )
    if needs_count is not None:
        track["needs_you_count"] = needs_count
    return track


def _rung(ladder: dict[str, Any] | None) -> dict[str, Any] | None:
    """The ladder's current rungs and the next ones, from ladder.json (base.rung).

    Current: the rungs ladder.json marks ``partial``, the ones being built, by axis ("LIVE · LV1, LV2, LV3 partial").
    With none partial, the frontier: each unfinished axis's lowest rung not green. Next: each axis's lowest rung that
    is neither green nor partial. WHY ladder.json and not loop-status ``where``: ``where`` is a per-tick projection
    that lags the ladder (it still said CS2 partial after CS2 turned green).
    """

    axes = [axis for axis in (ladder or {}).get("axes") or [] if isinstance(axis, dict)]
    partial: list[str] = []
    frontier: list[str] = []
    upcoming: list[str] = []
    for axis in axes:
        rungs = [r for r in axis.get("rungs") or [] if isinstance(r, dict) and isinstance(r.get("id"), str)]
        name = str(axis.get("id") or axis.get("title") or "?")
        building = [r["id"] for r in rungs if r.get("status") == "partial"]
        if building:
            partial.append(f"{name} · {', '.join(building)} partial")
        lowest = next((r["id"] for r in rungs if r.get("status") != "green"), None)
        if lowest:
            frontier.append(f"{name} {lowest}")
        after = next((r["id"] for r in rungs if r.get("status") not in ("green", "partial")), None)
        if after:
            upcoming.append(after)
    if not axes:
        return None
    current = " · ".join(partial) if partial else ("frontier " + ", ".join(frontier) if frontier else "every rung green")
    return rung(current, ", ".join(upcoming) or None, "ladder.json")


def _episode_line(ladder: dict[str, Any] | None) -> str | None:
    episode = (ladder or {}).get("episode") or {}
    if not episode.get("stop"):
        return None
    return f"Episode stop {episode['stop']}: {episode.get('stop_condition') or 'no stop condition recorded'}"


# --------------------------------------------------------------------------------------------- deployments (children)


def build_children(work_track: Any, sources: dict[str, str]) -> list[dict[str, Any]]:
    now = _now()
    deployments = Deployments.load(sources, now)
    ladder, _ = _read_json(sources.get("rig_ladder"))
    gate, _ = _gate_from_ladder(ladder if isinstance(ladder, dict) else None)
    out = []
    for child in work_track.children:
        dep = deployments.deployment(child)
        if dep is None:
            continue  # the build falls back to the snapshot, then to "not reporting"
        out.append(_deployment_track(child, dep, deployments, gate, now))
    return out


def _deployment_track(child: str, dep: dict[str, Any], deployments: Deployments, gate: float | None, now: datetime) -> dict[str, Any]:
    dep_id = dep["id"]
    rows = deployments.session_rows(dep_id)
    defs = deployments.kpi_defs(dep_id)
    records = deployments.records.get(dep_id, [])
    media = MediaIndex()
    ev = Evidence()
    session_file = os.path.join(deployments.fixtures_dir or "", f"kpis_session_{dep_id}.json")
    freshness = deployments.freshness_note(f"kpis_session_{dep_id}.json", "deployments.json", "run cache")

    iterations = []
    for row in rows:
        iterations.append({
            "id": row["name"], "label": BamLoopsAdapter._session_label(row["name"], row["start"] or ""),
            "date": (row["start"] or "")[:10] or None,
            "marker": f"{row['real']} real · {row['sim']} sim" + (f" · {row['aborted']} aborted" if row["aborted"] else "")
                      + (" · newer than the session fixture" if row["from"] == "cache" else ""),
            "provenance": _prov(session_file if row["from"] == "fixture" else deployments.cache_dir,
                                f"/periods/period={row['name']}" if row["from"] == "fixture" else f"/{row['name']}", row["note"]),
        })
    ids = [it["id"] for it in iterations]
    as_of = now.date()

    def age_days(value: dict[str, Any]) -> int:
        day = next((it["date"] for it in iterations if it["id"] == value["iteration"]), None)
        return (as_of - date.fromisoformat(day)).days if day else 0

    day_table = (deployments.days.get(dep_id) or {}).get("periods") or []
    latest, latest_period = dep.get("latest") or {}, dep.get("latest_period") or {}
    kpis = []
    for spec in defs:
        key, scale = spec["key"], float(spec.get("scale") or 1.0)
        values = []
        for row in rows:
            raw = row["kpis"].get(key)
            value = round(raw * scale, 3) if isinstance(raw, (int, float)) and key not in COUNT_KEYS else raw
            if key in REAL_KEYS:
                n = row["real"]
                note = None if value is not None else ("no real runs in this session" if not n else
                                                       "not in the session fixture" if row["from"] == "cache" else "not computed for this session")
            elif key in TWIN_KEYS:
                n = None
                note = None if value is not None else ("no twin replay in this session" if not ("__twin-" in row["name"]) else
                                                       "twin session newer than the session fixture; no single-session value")
            elif key == "floor_real_vs_real":
                n = None
                note = None if value is not None else "the floor is computed per day (it pools sessions), not per session"
            else:
                n = None
                note = None if value is not None else "count missing"
            if value is not None and key in row.get("day_keys", []):
                note = f"deployments.json latest (day {latest_period.get(key)}; this is that day's only session)"
            values.append(_value(row["name"], value, n=n, note=note))
        lower = spec.get("lower_is_better")
        direction = "lower" if lower is True else "higher" if lower is False else ("count" if key in COUNT_KEYS else "info")
        target = None
        if key == "twin_fidelity_gap" and gate is not None:
            target = {"value": gate, "kind": "gate", "label": f"TW2 gate ≤ {gate}°"}
        elif key == "twin_tracking_ratio":
            target = {"value": 1.0, "kind": "reference", "label": "reference 1×, no gate"}
        day_values = [(p.get("period"), (p.get("kpis") or {}).get(key), (p.get("counts") or {}).get("real")) for p in day_table if isinstance(p, dict)]
        day_values = [d for d in day_values if d[1] is not None]
        if key == "floor_real_vs_real" and day_values:
            band = round(day_values[-1][1] * scale, 3)
            target = {"band": [0, band], "kind": "descriptive",
                      "label": f"day floor {band:.3f}° ({day_values[-1][0][5:]}, sessions pooled) · descriptive band, never a verdict"}
        first = next((v for v in values if v["measured"]), None)
        baseline = ({"iteration": first["iteration"], "label": "first reading, " + BamLoopsAdapter._session_label(first["iteration"], ""),
                     "value": first["value"]} if first and direction in ("lower", "higher") else None)
        status = BamLoopsAdapter._session_status(key, values, dep, age_days=age_days)
        if key == "twin_fidelity_gap" and gate is not None and any(v["measured"] for v in values):
            last = [v for v in values if v["measured"]][-1]["value"]
            status = {"word": "under gate" if last <= gate else "above gate", "tone": "muted" if last <= gate else "warn"}
        kpi = _kpi(key, spec.get("label") or key, SLOTS.get(key, "S5"), BamLoopsAdapter._unit(spec.get("unit") or ""), direction, values,
                   target=target, baseline=baseline, status=status,
                   provenance=_prov(session_file, f"/periods/*/kpis/{key}",
                                    f"bam_deployments per-session value × {scale:g}; sessions mix trajectories, so session-to-session "
                                    f"changes are not like-for-like. {freshness}"))
        if key in COUNT_KEYS:
            total = (dep.get("counts") or {}).get(key.split("_")[0])
            kpi["aggregate"] = {"label": "all days", "value": total, "n": None, "period": None} if total is not None else None
        elif latest.get(key) is not None:
            period = latest_period.get(key)
            day_n = next((d[2] for d in day_values if d[0] == period), None)
            kpi["aggregate"] = {"label": f"day {str(period)[5:]}" + (" median" if key in REAL_KEYS else ""),
                                "value": round(latest[key] * scale, 3), "n": day_n if key in REAL_KEYS else None, "period": period}
        kpis.append(kpi)

    # held conditions: one trajectory + mode + config, closed loop, read in >= 3 sessions (the like-for-like series)
    real = [r for r in records if r.get("environment") == "real" and not r.get("aborted")]
    by_condition: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in real:
        by_condition[(str(record.get("trajectory_name")), str(record.get("control_mode")), str(record.get("config")))].append(record)
    held = [(cond, runs) for cond, runs in by_condition.items() if cond[1] == "ff_fb" and len({r.get("session") for r in runs}) >= 3]
    held.sort(key=lambda item: (-len({r.get("session") for r in item[1]}), item[0]))
    floor = latest.get("floor_real_vs_real")
    floor_deg = round(floor * DEG, 3) if isinstance(floor, (int, float)) else None
    held_ids: dict[tuple[str, str, str], str] = {}
    for cond, runs in held[:2]:
        kpi_id = "held_" + re.sub(r"[^a-z0-9]+", "_", f"{cond[0]}-{cond[1]}-{cond[2]}".lower()).strip("_")
        held_ids[cond] = kpi_id
        values = []
        for sid in ids:
            rms = [r["metrics"]["tracking_rms_rad"] * DEG for r in runs
                   if r.get("session") == sid and isinstance((r.get("metrics") or {}).get("tracking_rms_rad"), (int, float))]
            if rms:
                values.append(_value(sid, round(sum(rms) / len(rms), 3), n=len(rms),
                                     spread=round(max(rms) - min(rms), 3) if len(rms) > 1 else None))
            else:
                values.append(_value(sid, None, note="condition not run in this session"))
        config = "" if cond[2] == "default" else f" · {cond[2]}"
        kpis.append(_kpi(
            kpi_id, f"Held condition · {cond[0]} · {cond[1]}{config}", "S3", "deg", "lower", values,
            baseline=next(({"iteration": v["iteration"], "label": "first reading", "value": v["value"]} for v in values if v["measured"]), None),
            status=change_status(values, "lower", "deg", band=floor_deg),
            note="Real tracking RMS of one trajectory, mode and config held fixed across sessions: the like-for-like comparison. "
                 "n counts runs of this condition in the session."
                 + (f" A change inside the day floor ({floor_deg}°, descriptive) is described, never judged." if floor_deg is not None else ""),
            provenance=_prov(deployments.cache_dir, f"/*/{cond[0]}__real__{cond[1]}.json",
                             "mean of record.metrics.tracking_rms_rad × 57.2958 over this condition's runs per session"),
        ))

    # evidence: every real run (videos resolved on disk), twin replays, bundle reports
    sims = {(r.get("session"), r.get("trajectory_name"), r.get("control_mode"), r.get("config")): r
            for r in records if r.get("environment") == "sim" and not r.get("replay_of")}
    real_kpis = [k for k in REAL_KEYS if any(kp["id"] == k for kp in kpis)]
    videos = 0
    for record in sorted(real, key=lambda r: r.get("started_at") or ""):
        sid = record.get("session")
        if sid not in ids:
            continue
        cond = (str(record.get("trajectory_name")), str(record.get("control_mode")), str(record.get("config")))
        base = f"{child}.{sid}.{cond[0]}.{cond[1]}"
        real_video = media.add(record["video_path"], "video", f"Real · {cond[0]} · {cond[1]}", media_id=f"{base}.real") if record.get("video_path") else None
        sim = sims.get((sid, *cond))
        sim_video = media.add(sim["video_path"], "video", f"Sim · {cond[0]} · {cond[1]}", media_id=f"{base}.sim") if sim and sim.get("video_path") else None
        videos += 1 if real_video else 0
        m = record.get("metrics") or {}

        def deg(name: str) -> float | None:
            return round(m[name] * DEG, 3) if isinstance(m.get(name), (int, float)) else None

        ev.add(sid, "run", f"{cond[0]} · {cond[1]}" + (f" · {cond[2]}" if cond[2] != "default" else ""),
               item_id=f"{sid}-{cond[0]}-{cond[1]}-{record.get('started_at')}", when=record.get("started_at"),
               metrics={"rms (°)": deg("tracking_rms_rad"), "p95 (°)": deg("tracking_p95_rad"), "sim–real gap (°)": deg("sim_real_gap_rad"),
                        "feedback torque (N·m)": m.get("feedback_torque_rms_nm"), "limiter ticks": m.get("limiter_ticks"),
                        "peak temp (°C)": m.get("peak_temperature_c")},
               status="aborted" if record.get("aborted") else "ok", media=media.ref(real_video) + media.ref(sim_video),
               note=None if real_video else ("video path recorded but no file on disk" if record.get("video_path") else "no video recorded"),
               kpis=real_kpis + ([held_ids[cond]] if cond in held_ids else []))
    for record in sorted((r for r in records if r.get("replay_of")), key=lambda r: r.get("started_at") or ""):
        sid = record.get("session")
        if sid not in ids:
            continue
        m = record.get("metrics") or {}
        ev.add(sid, "run", f"Twin replay · {record.get('trajectory_name')}", item_id=f"{sid}-{record.get('trajectory_name')}-replay",
               when=record.get("started_at"),
               metrics={"gap aligned (°)": round(m["replay_gap_aligned_rad"] * DEG, 3) if isinstance(m.get("replay_gap_aligned_rad"), (int, float)) else None,
                        "gap legacy (°)": round(m["replay_gap_legacy_rad"] * DEG, 3) if isinstance(m.get("replay_gap_legacy_rad"), (int, float)) else None,
                        "gap receipt (°)": round(m["replay_gap_receipt_rad"] * DEG, 3) if isinstance(m.get("replay_gap_receipt_rad"), (int, float)) else None,
                        "torque gap (N·m)": m.get("replay_torque_gap_aligned_nm"),
                        "tracking rms (°)": round(m["tracking_rms_rad"] * DEG, 3) if isinstance(m.get("tracking_rms_rad"), (int, float)) else None},
               status="sim replay", note=f"replays {record.get('replay_of')}", kpis=["twin_fidelity_gap", "twin_tracking_ratio", "sim_runs"])
    for sid in ids:
        report = next((r.get("report_path") for r in records if r.get("session") == sid and r.get("report_path")), None)
        report_id = media.add(report, "html", f"Bundle report · {sid}", media_id=f"{child}.{sid}.report") if report else None
        if report_id:
            ev.add(sid, "report", f"Bundle report · {BamLoopsAdapter._session_label(sid, '')}", item_id=f"{sid}-report",
                   media=media.ref(report_id), kpis=["real_runs", "sim_runs"])
    evidence = ev.attach(kpis)

    last_real_day = latest_period.get("real_tracking_rms")
    stale_days = (as_of - date.fromisoformat(last_real_day)).days if last_real_day else None
    unconfirmed = sum(1 for kp in kpis if kp["status"]["word"] == N1_WORD)
    if unconfirmed:
        state = {"word": "Repeat needed", "tone": "warn",
                 "detail": f"{unconfirmed} change unconfirmed (n = 1)" + (f" · {stale_days} days since a real run" if stale_days is not None else ""),
                 "since": last_real_day}
    elif last_real_day:
        state = {"word": "Stale" if stale_days > 14 else "Current", "tone": "stale" if stale_days > 14 else "muted",
                 "detail": f"last real run {last_real_day[5:]} · {stale_days} days", "since": last_real_day}
    else:
        state = {"word": "No real runs", "tone": "muted", "detail": "no real run recorded", "since": None}
    track = {
        "id": child,
        "title": dep.get("title") or child,
        "kind": "deployment",
        "parent": None,
        "summary": dep.get("summary") or dep.get("title") or child,
        "state": state,
        "iteration": {"unit": "session", "label": iterations[-1]["label"] if iterations else "none reported"},
        "iterations": iterations,
        "north_star": "real_tracking_rms" if any(k["id"] == "real_tracking_rms" for k in kpis) else None,
        "kpis": kpis,
        "needs_you": [],
        "evidence": evidence,
        "links": ([{"label": "Day-level floor", "kind": "path", "value": f"{floor_deg:.3f}° (descriptive band)"}] if floor_deg is not None else []),
        "media": media.items,
        "provenance": {**_prov(os.path.join(deployments.fixtures_dir or "", "deployments.json"), f"/id={dep_id}", freshness),
                       "counts": dep.get("counts"), "latest_real_rms": latest.get("real_tracking_rms"),
                       "videos_resolved": videos, "videos_flagged": sum(1 for r in real if r.get("video_path"))},
        "source": {"kind": "live", "live": True, "computed_at": now.isoformat(timespec="seconds"),
                   "inputs": [{"key": name, **stamp} for name, stamp in deployments.stamps.items()],
                   "problems": deployments.problems},
    }
    return track
