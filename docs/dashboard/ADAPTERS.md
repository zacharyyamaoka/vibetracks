# Work-track adapters

The dashboard's home page has one row per **work track**, the agent loops Zach runs. Each track is a note in the registry, and each note names an **adapter**: one Python module that reads the loop's own files and returns one `vibetracks-dashboard/1` track (PROJECTION.md). The backend builds the projection **live** from the registry on every `GET /projection`.

This page is the contract for the five adapter lanes. Each lane owns exactly two files: `vibetracks/dashboard/adapters/<id>.py` and `workspace/tracks/<id>.md`. Everything else is shared; if you need a change in it, report it instead of making it (appending a key to `vibetracks/sources.py` is the one exception).

## The registry

- **Descriptor:** `workspace/Work tracks.vibetrack`. It selects `note["vibe-track"] == "worktrack"` notes in `workspace/tracks/`. `workspace/Agent work.vtdash` names it (`"registry": "Work tracks.vibetrack"`); that is how the backend finds it.
- **Reader:** `vibetracks/dashboard/registry.py`. `load_registry(workspace)` returns the ordered `WorkTrack` list; `read_registry` also returns the notes it skipped (`problems`).
- **A note's frontmatter:**

| key | meaning |
|---|---|
| `vibe-track` | `worktrack` (the marker) |
| `vibe-id` | the stable key, `[a-z0-9][a-z0-9_-]*`. Never renamed. |
| `vibe-title` | the display name. Renamed from the page (below). |
| `vibe-status` | `running`, `paused` or `archived`. Archived tracks are left off the page (`projection.registry.archived` lists them). |
| `vibe-priority` | a positive integer, the row order (1 first). Anything else sorts last. |
| `vibe-owner` | a label for the session or agent. It is a label only: liveness comes from file mtimes. |
| `vibe-adapter` | the module name: `adapters/<name>.py` |
| `vibe-sources` | `vibetracks/sources.py` keys: **every** file or folder your adapter opens, the same keys as its `READS` |
| `vibe-heartbeat` | optional: the subset of keys whose mtime says the loop is alive (default: the keys `READS` marks `heartbeat`, else every source) |
| `vibe-stall-hours` | optional: quiet longer than this and the row reads stale (default 24) |
| `vibe-roadmap` | `{projector, sources}` for the roadmap session's `/roadmap` routes, or `null` ("No roadmap reported yet") |
| `vibe-children` | ids drawn inside this track and never on the home page (rig: `[can12, can16]`) |

The body is two or three lines: what the loop is for and its milestone. The build passes its whole first paragraph through as `track.purpose`, uncut (the page clamps it with an explicit ellipsis).

## The interface

```python
# vibetracks/dashboard/adapters/<name>.py
from .base import local_time, not_reporting, rung, skeleton

READS = {"<key>": "heartbeat" | "input" | "evidence", ...}   # every sources.py key you open
DEPTH = {"<key>": 2}                                          # optional: a folder whose files sit one level down

def build_track(work_track, sources: dict[str, str]) -> dict: ...
def build_children(work_track, sources: dict[str, str]) -> list[dict]: ...   # optional, only for vibe-children
```

- **`READS`** names every `sources.py` key the adapter opens, with its role: `heartbeat` (the loop's own output: its mtime says the loop moved), `input` (read for numbers or words but written by someone else: a plan, a script, a run cache) or `evidence` (a shared folder listed only to find media to link, like bam_ws `reports/`). The note's `vibe-sources` lists the same keys. Without `vibe-heartbeat`, liveness watches only the `heartbeat` keys, so another fleet writing a shared folder never makes a stopped loop look alive. `tests/test_dashboard_adapters_live.py` runs every adapter under a Python audit hook and fails on any file opened or folder listed outside the declared paths.
- **`DEPTH`**: a declared folder is stamped one level deep (its entries' mtimes). If your files sit one folder further down (the rig's run cache, `runs/<bundle>/<run>.json`), set `DEPTH = {key: 2}`; the build stamps that folder two levels deep and the reads test holds you to exactly that depth.
- **Read only what you are handed.** Never fall back to `load_sources()`, a hard-coded path or a file beside a declared one: an input the note does not declare changes without the build rerunning you. A key that is not declared reads as missing (null with a note, or "not reporting" when nothing honest can be said).

- **`work_track`** is the registry row (`registry.WorkTrack`): `id, title, status, priority, owner, adapter, sources, roadmap, children, note_path, revision, heartbeat, stall_hours, purpose`.
- **`sources`** maps each key in your note's `vibe-sources` to its absolute path. **Only declared keys are passed.** The build caches your output and reruns you only when your note, your module file, or one of those declared files changes (mtime and size; a directory counts its own entries, one level deep unless `DEPTH` says two). An input you read but did not declare can change without the dashboard noticing. The keys live in `vibetracks/sources.py` (`WORKTRACK_SOURCES`, below). A new input gets a new key **appended** there; never rename or remove one (other sessions read them). A worktree-resident path hangs off its folder's key (`"{rig_loop_dir}/triage.json"`) or uses the `@worktree:<repo>:<branch>:<sub>|<fallback>` form, so a moved worktree is one line. To point a key somewhere else on this machine, set it in `~/.local/share/vibetracks/sources.json`.
- **Return** a Track (PROJECTION.md). Start from `skeleton(work_track, unit="wave"|"tick"|"session"|"day")`, which has every field present with honest empties, and fill:
  - `state` `{word, tone, detail, since}`, the one calm answer;
  - `summary`, one sentence;
  - `iteration` and `iterations`, the shared x-axis, oldest first;
  - `rung` `{current, next, source}` or null (PROJECTION.md `Rung`): the **frontier**, the lowest rung or tier not yet passed, in the loop's own words, never the newest thing measured. Build it with `base.rung(current, next, source)`;
  - `kpis` (slot S1 to S7) and `north_star`; every KPI's `values` aligns one to one with `iterations`. A KPI `label` never starts with its slot's group header ("Frontier gate · …", "North star · …"): the page prints the header above it;
  - `needs_you`. The build counts it into `needs_you_count` `{open, blocking}`. Set `needs_you_count` yourself only when the loop reports counts but not the questions;
  - `evidence` `{by_iteration, by_kpi}` and `links`;
  - optionally `media` `{id: MediaEntry}`. The build lifts it into the projection's allowlist and drops it from the track. Prefix ids with your track id, and list only files that exist.
  - optionally `source` `{kind, live, ...}` if your output is not live (for example, a snapshot you fall back to).
- **The build owns** `id` (= `vibe-id`), `title` (= `vibe-title`), `kind`, `parent`, `children`, `registry`, `purpose`, `freshness` and `reporting`. Whatever you put there is overwritten. Never hard-code a title: Zach renames tracks.
- **Children:** `build_children` returns tracks whose `id` is in `vibe-children`. The build sets `parent` and `kind: "deployment"`, lists them after the top-level rows, and never puts them on the home page. Ids you return that are not declared are dropped. A declared child you do not return falls back to the `bam_loops` snapshot (`can12`, `can16`, marked `source.kind: "snapshot"`), and otherwise reads "not reporting".
- **Failure is honest, never a crash.** A missing module, an import error, an exception in `build_track`, or a track that `base.problems()` rejects all become a "Not reporting" row: `state.detail` and `summary` say why (`not reporting · adapter error · KeyError: 'rungs'`), there are no numbers, and `needs_you_count` is null. The traceback goes to the backend's log.
- **Freshness is the build's.** For each track, the build stats its heartbeat files on every request. If the newest one is older than `vibe-stall-hours`, the track's `freshness.stale` is true, and a calm (`ok` or `muted`) state turns `stale` with "sources quiet 3 days · stall rule 24 h" appended. When no file exists, `stale` is null: unknown, never fine.

### The truth rules (PROJECTION.md, enforced in review)

1. Every number comes from a named file; `provenance` says which file and how it was derived.
2. Missing is `value: null, measured: false` with a `note`. Never a zero. A KPI with no source today is still listed, with gaps that say "not emitted".
3. If either side of a change rests on n = 1, the change reads `unconfirmed · repeat needed`.
4. A day floor is a descriptive band, never a verdict.
5. Elapsed hours are wall-clock hours (`h elapsed`), never agent-hours.
6. Every time a person reads goes through `base.local_time` ("10-04 17:55 PDT"); never print a bare clock time, a UTC time or a raw offset in a sentence. ISO fields keep their offsets. Iteration dates are `base.local_day`.
7. Never trim, clip or abbreviate a stored string in an adapter: send it whole (event details, triage titles and defaults, env lists). The page folds long text; a display-only abbreviation is the UI's, with an explicit ellipsis and the full value one click away. Commit and hash prefixes (`abc1234`) are identifiers, not text, and stay short.

### Working on one

- **Run your adapter in place:** `cd ~/vibetracks-dashboard && python3 -m vibetracks.dashboard.build --data-home /tmp/vt-home`. It prints one line per track.
- **Against the running page:** the backend reloads your module when its file changes, so no restart is needed. Open `http://127.0.0.1:4390/?vtdash=Agent%20work.vtdash`, or fetch `curl -s http://127.0.0.1:4390/api/plugins/vibetracks/projection`. `?rebuild=1` drops the cache.
- **Tests:** add `tests/test_dashboard_adapter_<id>.py`. `base.problems(track)` must be `[]`. Pin a few numbers you checked by hand against the loop's files.

## Renaming a track

`POST /api/plugins/vibetracks/tracks/<id>/title` with `Content-Type: application/json` and `{"title": "...", "revision": "<registry.revision from the projection>"}`.

- It changes only the `vibe-title` line of `workspace/tracks/<id>.md`, through `edits.apply_note_edit` and `replace_frontmatter_entry`: fenced on the revision, atomic (temp file plus `os.replace`), and every other byte of the note kept.
- It answers `{ok, id, title, revision}`, where `revision` is the note's new revision; fence the next rename on it.
- The title is stored exactly as typed: never trimmed, never normalised, no length cap (`"  Grasping  "` is stored with its spaces, as a quoted YAML scalar). The splice keeps a BOM, every line ending (CRLF stays CRLF), the `---` delimiters exactly as written (trailing spaces included) and every byte outside the `vibe-title` value; the revision is the hash of the note's exact text, so a CRLF note fences correctly. `tests/test_dashboard_registry.py` and `tests/test_edits.py` hold byte-exact BOM + CRLF round trips.
- Errors: 400 only for an empty or whitespace-only title, one containing a line break (LF, CR, VT, FF, U+001C-U+001E, NEL, U+2028, U+2029), or a bad body; 404 for an unknown id; 409 when the note changed since `revision` (the body carries the current revision); 415 when the content type is not JSON.
- `vibe-id`, the cache key, the roadmap key and every URL stay the same. The next `GET /projection` shows the new title.

## Source map, per track

From `docs/dashboard/track-discovery-2026-10-04.json` (`scout:<key>`). Read that file's entry for your track before you start: it has every path, the KPIs with their exact sources, the roadmap, the gaps and the owner sessions. The keys below are already in `vibetracks/sources.py`.

### `kinsim`: Kinematic Sim (`scout:kinsim`)

- **Keys:** `kinsim_status` (`~/.local/share/bam_curriculum/status.json`, the live fold: `rungs[]`, `you_are_here[]`, `frontier[]`, `blocking_triage[]`), `kinsim_events` (`loop_events.jsonl`: `wave_started` and `wave_finished`, `gate_run`, `rung_status_changed`, `audit`), `kinsim_runs` (`runs.jsonl`, the judged-run ledger), `kinsim_loop_dir` (the current loop checkout, `wave-3-handoff-af2b9b/src/dev/bam_curriculum`: `curriculum.json`, `triage.json`, `ROADMAP.md`), `reports_media_dir` (evidence: the wave reports to link). `kinsim_curriculum_dir` is the roadmap session's older checkout; do not rely on it for live state.
- **Rung:** running, the wave's open targets (`curriculum.json` `wave`); otherwise the `status.json` frontier. Next: the next planned wave's open rungs.
- **Iteration:** the wave (W1 to W4 closed; wave 5 not started).
- **KPIs:** green rungs of 62; RB0 and SN1 promotion PPM and feasibility; belt-speed frontier BT1 to BT4; packages landed per wave (free text in `wave_finished.detail`, so parse it); the fast regression gate; open triage.
- **Roadmap:** projector `kinsim` (the roadmap session's).
- **Gaps:** `status.json` has no per-wave series, so refold it from events plus runs. Ledger-driven greens emit no `rung_status_changed`.

### `rig`: Sim to Real & Trajectory Tracking (`scout:sim2real`)

- **Keys:** `rig_loop_status` (`loop-status.json`, schema `loop-status/1`: `tick`, `where[]`, `next[]`, `needs_you[]`, `rate`), `rig_events` (`loop_events.jsonl`), `rig_ladder` (`ladder.json`, 6 axes), `rig_triage` (`triage.json`), `rig_roadmap` (`ROADMAP.md`, the disk stop line), `deployments_fixtures_dir` (the bam_deployments API fixtures, input), `rig_deployments_cache` (`/archive/datasets/bam_rig/cache/runs`, input, `DEPTH` 2), `rig_audits_dir` (bam_ws `reports/media/audits`, evidence). `rig_loop_dir` is the folder.
- **Rung:** the `partial` rungs of `ladder.json` by axis ("LIVE · LV1, LV2, LV3 partial"); next, each axis's lowest missing rung.
- **Iteration:** the loop tick (`tick.n`, 0 to 4). The deployment KPIs are per session or day.
- **Rungs green (north star):** when neither `ladder.json` (its rungs) nor `loop_events.jsonl` (a `rung_status_changed` row) can establish the count, every value is null with a note naming both reasons, the status is "not measured" and there is no baseline, target or delta; with events but no ladder the count reads "N green (no ladder total)", never "of None".
- **KPIs:** twin fidelity gap (held-out, deg, gate ≤ 0.8°); twin tracking ratio; real tracking RMS; sim-real gap; floor (descriptive); feedback torque; loop progress rate; rungs green; audit verdicts; needs-you.
- **Children:** `can12`, `can16`, drawn live by `build_children` from the deployments fixtures and run cache.
- **Roadmap:** projector `rig`.
- **Gaps:** there are no per-tick KPI rows (`loop-status` keeps the last 3 values), so rebuild them from events. The deployment KPIs live in `/archive/datasets/bam_rig/cache`.

### `grasping`: Grasping (`scout:grasping`)

- **Keys:** `grasping_ledger` (`grasp_bench/out/ledger/runs.jsonl`, one CellRun per row, live), `grasping_curriculum` (`curriculum.py`, code-as-roadmap: tiers, models, `GATES`), `grasping_out_dir` (`grasp_bench/out`, evidence: the bench's gallery files). `grasping_bench_dir` is the folder. The verdict bridge adds, all `input`: `grasping_bench_python` (the bench's `.venv/bin/python`), `grasping_attestations` (`out/ledger/attestations.jsonl`, beside the ledger; absent today), `grasping_gallery_py`, `grasping_ledger_py`, `grasping_runner_py`, `grasping_contracts_py` (the bench code the verdict runs), `grasping_verdict_cache` (`<dashboard data home>/grasping-bench-verdict/`, the bridge's cache) and `grasping_bench_src` (the whole `src/grasp_bench` package, `DEPTH` 2, so a change to any bench module reruns the adapter).
- **Verdict: the bench's own, never a copy.** Which run heads each cell, which runs are frozen or privileged, which envs are beaten or provisional: `benches/grasp_bench_bridge.py` runs `grasp_bench.gallery` (`headline_runs`, `env_verdict`, `env_provisional`, `is_frozen_protocol`, `clears_gate`, `provenance_gap`) in the bench's venv (`python -I`, cwd the bench, `VIRTUAL_ENV`/`PYTHONPATH` removed, 90 s timeout) over exactly the ledger rows the adapter read, one cumulative subset per tier phase. It refuses an answer whose imported `gallery.py`/`ledger.py`/`curriculum.py`/`runner.py`/`contracts.py` or attestations path is not the declared one. The answer is cached, keyed on the mtime and size of the venv's python, `runs.jsonl`, `attestations.jsonl` (stamped absent when missing), the declared modules, the request and the bridge script, plus every `grasp_bench` module the run imported: the script reports them from `sys.modules` after the verdict, the cache entry stores their stamps, and a read re-stamps them, so a change to any of them (`registry.py`, which `gallery.py` imports and whose `env_family` decides the protocol) is a miss. A module that changed while the bench ran is returned but never cached. Both caches (`verdict.json`, `verdict-v3.json`) follow this rule; `tests/test_grasp_bench_bridge_deps.py` mutates only a fake bench's `registry.py` and requires a recomputed verdict. About 0.5 s cold, 0.01 s warm. WHY: the adapter's copy of these rules drifted the night the bench tightened "frozen" (da80ffe1, provenance that can vouch for itself; `attestations.jsonl`) and showed 6 of 10 gated envs beaten against the gallery's 2; its protocol table was missing `mujoco-cam` too. `tests/test_dashboard_adapter_grasping.py::NoReplicaTest` fails if any of those functions comes back.
- **`verdict()` row digests (`line_sha256`, additive to `grasp-bench-verdict/2`).** Every `runs[run_id]` also carries `line_sha256`: the sha256 hex of that ledger row's exact bytes in `runs.jsonl`, without its one line terminator (`\n`, or `\r\n` when the file uses CRLF; nothing else is stripped, so re-serialising a row changes its digest). `run_id` is the row's 0-based index among the rows `Ledger.load_runs()` returns, which skips blank lines and lines that are not valid JSON (a torn trailing line); the digest follows that same indexing. **Alignment is guaranteed inside the bench subprocess, by construction:** it reads `runs.jsonl` as bytes once, splits it as the Ledger's text-mode read does (`bytes.splitlines`: `\n`, `\r\n`, lone `\r`), applies the Ledger's skip rule, then requires the parsed rows to equal what `load_runs()` held (same count, and each row's `run_id` and every field the loaded run has). On a mismatch (the file grew between the two reads) it re-reads once; a second mismatch returns `error` = "ledger changed during read; row digests unaligned" with empty `envs`/`runs`/`headline`, never a misaligned digest, and is not cached. The digest and the frozen/gap judgement therefore describe the same row. The cache entry is `grasp-bench-verdict/3` (file `verdict-v3.json`, its schema in the key); an older entry, or any entry whose runs lack a `line_sha256`, is a miss. The returned `schema` stays `grasp-bench-verdict/2`. WHY: the roadmap projector pins a verdict to the exact ledger rows it judged; `started_at`/`env`/`model` do not identify a row (re-measures share them). Tests: `tests/test_grasp_bench_bridge.py::RowDigestTest` (fake bench) and `LiveBenchTest` (live ledger).
- **No verdict:** when the bridge cannot run (no venv, an import error, a timeout, a mismatched module), there is no fallback. The north star (`envs_beaten`) is null on every iteration with the note `bench verdict unavailable: <reason>`; `mujoco_beaten`, `hardest_lb`, `hardest_margin`, `dataset_ap`, `latency_p95` and `wave1_cells` are null with `unconfirmed: bench verdict unavailable`; the state reads "Bench verdict unavailable" (warn), the rung is null, and `track.source.problems` carries the reason (`track.source.bench_verdict` has `{ok, reason, cached, seconds, bench_seconds}`). `seed_rule` and `dirty_share` stay measured: they count raw ledger fields the gallery does not judge.
- **Rung:** the frontier tier (the state word says the same), from the bench's verdict; next, the following tier.
- **Iteration:** a ledger row; the coarser unit is the tier or wave phase.
- **KPIs:** envs beaten (Wilson lower bound against the gate); wave-1 cells measured of planned; best learned top-1 per env; margin over floors; dataset AP against the oracle and published; latency p50 and p95; the `git_dirty` share.
- **Roadmap:** `null` for now.
- **Gaps:** everything is in an agent worktree whose `out/` is gitignored, and there is no status file, so the frontier must be derived.

### `detection`: Object Detection & Hyperspectral (`scout:detection`)

- **Keys:** `detection_queue_log` (`spectralwaste-segmentation/logs/queue.log`, the July repro queue), `detection_logs_dir` (the per-run logs, required), `detection_wandb_dir`, `detection_compile_results` and `detection_queue_script` (inputs), `detection_ladder` (`ladder_data.py`, the H0 to H9 plan; untracked; input), `detection_plan_note` (the vault plan's Needs you list; input), `detection_reports_dir` (bam_ws `reports/`, evidence). The plan, ladder and scripts are `input`, not `heartbeat`: a plan written today must not make a July run history read as a live loop.
- **Rung:** the rung `ladder_data.KPIS` S2 names as today's frontier (H1), with its live progress; next, the rungs that need it (H4, H7).
- **Iteration:** planned as a loop tick; today only the July training runs exist.
- **KPIs:** S1 hyperspectral test mIoU (no valid value yet; the CMX run is invalid with a NaN loss; target 58.2); S2 H1 configs reproduced, 2 of 12; S3 to S6 are not emitted anywhere, so list them with gaps that say so.
- **Roadmap:** `null`.
- **Gaps:** the loop has never started. The heartbeat is about 86 days old, so the row reads stale, which is true.

### `pyblocks`: Pyblocks (`scout:pyblocks`)

- **Keys:** `pyblocks_board_dir` (`reports/media/board/<commit7>.json`, the scoreboard per merge window), `pyblocks_windows` (`windows.jsonl`). `pyblocks_repo` is the folder.
- **Rung:** null. The board files carry scoreboards, not the milestone the loop is on.
- **Iteration:** a merge window, keyed by main's commit.
- **KPIs:** runnable goldens green of 55; easy-18 green; L0 passes; adversarial green of 132; the fast gate; ledgered reds.
- **Roadmap:** `null` (M1, then M2, then M3, in `final-plan.json`).
- **Gaps:** the board series stops at b07c38b (10-01). The 10-02 numbers exist only in an HTML summary: show them as not emitted, never copied in.
