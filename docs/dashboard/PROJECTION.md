# The dashboard projection: `vibetracks-dashboard/1`

One JSON document is everything the dashboard shows. The backend builds it **live** from the work-track registry on every `GET /projection` (`vibetracks/dashboard/build.py` `LiveBuilder`; one adapter per track, docs/dashboard/ADAPTERS.md), and serves it, and every variant reads it through one shared model (`clank/src/shared/model.ts`, which mirrors this page type for type). The research principle behind the single file is "solve the display once": a fixed template, with KPIs bound as data, so every track renders through the same grammar.

- **Build:** `cd ~/vibetracks-dashboard && python3 -m vibetracks.dashboard.build` (live from `workspace/`'s registry, also written to `<data home>/projection.json`; `--workspace W`, `--data-home DIR`, `--snapshot` for the 2026-10-03 snapshot build, `--refresh-sources`).
- **Serve:** `clank/backend/server.py`, through Clank's proxy at `/api/plugins/vibetracks/projection` (`?rebuild=1` drops the adapter cache first) and `/api/plugins/vibetracks/media/<id>`. Without a registry in the workspace it serves `projection.json` from the data home instead.
- **Rename:** `POST /api/plugins/vibetracks/tracks/<id>/title` `{title, revision}` (ADAPTERS.md, "Renaming a track").
- **Machine paths:** `vibetracks/sources.py` `load_sources()` (the data home, the run-media root, `reports/media`, the loop folders). Override any of them in `~/.local/share/vibetracks/sources.json` (or `$VIBETRACKS_SOURCES`); `~` is expanded.
- **Extra backend routes:** `clank/backend/mounts.py`, an append-only list of `(prefix, 'module:callable')`, GET only.
- **Adapters:** one per work track, `vibetracks/dashboard/adapters/<vibe-adapter>.py` (ADAPTERS.md). A track whose adapter is missing, pending or failing is a "Not reporting" row that says why. `vibetracks/dashboard/adapters/bam_loops.py` is the 2026-10-03 snapshot; the rig adapter now draws `can12`/`can16` live, so the live build falls back to the snapshot only for a declared child no adapter returns (marked `source.kind: "snapshot"`, and always stale).

## Truth rules (hold for every adapter)

1. Every number comes from a named source. `provenance` says which file, which JSON pointer, and how it was derived.
2. Missing is explicit: `value: null`, `measured: false` and a `note` saying why. Never a zero.
3. If either side of a change rests on n = 1, the change reads `unconfirmed · repeat needed`. No status word ever says "regressed".
4. A day floor is a descriptive band (`target.kind: "descriptive"`), never a verdict threshold.
5. Elapsed hours are wall-clock hours (`unit: "h elapsed"`), never agent-hours.
6. Every time a person reads is this machine's local time with its zone abbreviation, `10-04 17:55 PDT` (`adapters/base.py` `local_time`). Machine fields (`since`, `when`, `generated_at`, `freshness.*`) stay ISO strings with their offsets. Iteration `date`s are the local calendar day.
7. A stored string is never silently trimmed, normalized or clipped. When geometry forces an abbreviation, the page shows an explicit ellipsis and keeps the full value one hover or click away.

## Top level

| field | type | meaning |
|---|---|---|
| `schema` | `"vibetracks-dashboard/1"` | the contract version |
| `generated_at` | ISO timestamp | when this file was written |
| `as_of` | `YYYY-MM-DD` | the date of the data (the snapshot's day) |
| `source` | object | `{adapter, kind: "snapshot"\|"live", live: bool, registry, snapshot, snapshot_generated_at, curriculum, todo, units_note}`. Live: `adapter: "registry"`, `live: true`, `registry` the descriptor path, `snapshot` the snapshot file a child fell back to (else null), `todo` lists the tracks not reporting and why. |
| `registry` | object | live only: `{descriptor, order: [top-level ids], archived: [{id, title}], problems: [{path, error}]}` |
| `tracks` | `Track[]` | top-level work tracks in `vibe-priority` order, then their children (whose `parent` names their track) |
| `media` | `{[id]: MediaEntry}` | the allowlist: every file the page may open, by id |

## `Track`

| field | type | meaning |
|---|---|---|
| `id` | string | `kinsim`, `rig`, `can12`, `can16`; live: the note's `vibe-id`, which never changes |
| `title` | string | live: the note's `vibe-title`, which Zach can rename |
| `kind` | `"loop"` \| `"deployment"` | a loop is a level-1 row; a deployment is evidence for its parent loop |
| `parent` | string \| null | the loop a deployment belongs to |
| `summary` | string | one sentence |
| `state` | `{word, tone, detail, since}` | the one calm answer: `Paused` · warn · "disk 90.36% · stop line 91.0%" |
| `iteration` | `{unit: "wave"\|"tick"\|"session"\|"day", label}` | what one column is, and the latest one ("wave 3") |
| `rung` | `Rung` \| null | optional, top-level loops: where the loop stands on its ladder (below). null or absent = the adapter does not know, and the page says so |
| `iterations` | `Iteration[]` | the shared x-axis, oldest first. Every KPI's `values` aligns with it one to one. |
| `north_star` | KPI id \| null | the S1 KPI the glance shows; null when the track reports no KPIs |
| `kpis` | `Kpi[]` | in slot order S1 to S7 |
| `needs_you` | `NeedsYou[]` | live: the questions that still want Zach (needs.py groups blocking, no_default, waiting), in needs.py's order (blocking first). Filled by build.py from `vibetracks/dashboard/needs.py`, never from the adapter's own list; `[]` when needs.py has no structured source, and always `[]` on a deployment (child) |
| `evidence` | `{by_iteration, by_kpi}` | level 3 (below) |
| `links` | `Link[]` | reports, commands, paths |
| `provenance` | `Provenance` | plus, on deployments, `counts`, `latest_real_rms`, `videos_resolved`, `videos_flagged` |
| `reporting` | bool | live: false when the adapter could not report (`state.word` "Not reporting", `state.detail` and `summary` say why) |
| `needs_you_count` | `{open, blocking}` | live, top-level: `open` = needs.py's `counts.wants_you`, `blocking` = `counts.blocking_now`, the same two numbers `GET /needs?track=<id>` serves, so the home cell, the track page and the needs page agree ("B blocking · M open"). Both null when needs.py has no structured source for the track (pyblocks today) or could not read it: "not reported", never 0. Deployments (children, rig's `can12` / `can16`) are **always** null/null: needs.py reads no questions per deployment, so a 0/0 the adapter or the 10-03 snapshot carries is dropped, never shown as "nothing open" |
| `needs_you_source` | object | live: `{adapter, live, note}` of the needs.py doc behind the two fields above; `note` says where the questions live, or why there are none. On a deployment: `{adapter: null, live: false, note}`, the note pointing at the parent loop's page |
| `freshness` | object | live: `{newest, newest_source, age_h, stall_hours, stale, note, sources: [{key, path, exists, modified, note}]}`. `stale` is null when no source file exists. A stale track's calm state turns `stale`. `age_h` is wall-clock. |
| `source` | object | live: `{adapter, kind: "live"\|"snapshot"\|"none", live}` for this track |
| `registry` | object | live, top-level only: the note's `{status, priority, owner, adapter, sources, heartbeat, stall_hours, roadmap, children, note_path, revision}`; `revision` fences a rename. `heartbeat` is the effective list: the note's `vibe-heartbeat`, else the sources the adapter's `READS` marks `heartbeat` (ADAPTERS.md) |
| `purpose` | string | live, top-level only: the whole first paragraph of the track's registry note, never cut and with every `*`, `_` and backtick kept (`first_paragraph(body, limit=None, raw=True)`: `pll_filter_hz` stays `pll_filter_hz`); it is inline markdown, which the page renders, and the page clamps it with an explicit ellipsis and a "more" toggle |
| `children` | string[] | live, top-level only: the `vibe-children` ids drawn inside this track |

### `Rung`

`{current: string, next: string | null, source: string}`, validated by `base.problems()` (exactly these three keys).

- `current`: the rung or tier the loop is on now, in the loop's own words ("Tier 2 · MuJoCo physics", "H1 · Published ruler · 2 of 12 reproduced", "LIVE · LV1, LV2, LV3 partial"). It is the **frontier**, the lowest rung or tier not yet passed, never merely the newest thing measured (the grasp bench runs tier-5 cells while tier 2's gates are open).
- `next`: the rung(s) the loop says come after it ("Wave 5 · RB1, SN2, BT2", "Tier 3 · Real images, offline"), or null when its files do not say.
- `source`: the file key or file name it was read from ("ladder.json", "curriculum.py …").
- A fallback only: when the roadmap widget's document is present, the home cell renders the widget and ignores `rung`.

| track | `current` | `next` | read from |
|---|---|---|---|
| `kinsim` | running: `Wave N · <the wave's open targets>`; otherwise `Frontier · <status.json frontier>` | the next planned wave's open rungs (`curriculum.json` `wave`), else the rest of the frontier | `status.json`, `curriculum.json` |
| `rig` | the rungs `ladder.json` marks `partial`, by axis; with none, each axis's lowest non-green rung | each axis's lowest rung neither green nor partial | `ladder.json` |
| `grasping` | the frontier tier: the lowest tier whose wave-1 cells are not all measured on the frozen protocol or whose gates are not all beaten | the next tier with wave-1 cells | `curriculum.py`, `runs.jsonl` |
| `detection` | the rung `ladder_data.KPIS` S2 names as today's frontier, with its live progress | the rungs whose `needs_rungs` name it | `ladder_data.py`, `queue.log` |
| `pyblocks` | null: the board files carry scoreboards, not a milestone or rung | | |

`tone` is one of `ok | warn | risk | stale | muted`. Colour is only for `warn`, `risk` and `stale`; `ok` and `muted` render grey.

## `Iteration`

| field | type | meaning |
|---|---|---|
| `id` | string | `start`, `W1`; `T0`; a session period name (`baseline_2026-07-28`) |
| `label` | string | `W1`, `T2`, `07-29 gravity amplitude ladder`, `10-02 twin V1` |
| `date` | `YYYY-MM-DD` \| null | null when no event dates it (rig tick 2) |
| `marker` | string | what changed: `wave closed: 7/7 landed · ruler pinned a2-v2 · loop paused (disk) · +9 rungs` |
| `provenance` | `Provenance` | |

## `Kpi`

| field | type | meaning |
|---|---|---|
| `id` | string | unique within the track |
| `label` | string | "BT1 feasible". Never repeats its slot's group header ("Frontier gate · …"): the page prints the header above the row |
| `slot` | `S1`…`S7` | North star · Frontier gate · Guardrails · Delivery rate · Evidence trust · Cost · Needs you & health |
| `unit` | string | `rungs`, `points`, `%`, `deg`, `N·m`, `runs`, `packages`, `audits`, `questions`, `days`, `h elapsed`, `×` |
| `direction` | `higher` \| `lower` \| `info` \| `count` | which way is better; `info` and `count` have no better |
| `target` | `Target` \| null | null reads "no target set" |
| `baseline` | `{iteration, label, value}` \| null | the named, pinned baseline deltas compare against ("start 09-30", "V0 untuned twin") |
| `values` | `KpiValue[]` | one per iteration, same order as `track.iterations` |
| `status` | `{word, tone}` | the KPI's calm reading ("+9 in W3", "unconfirmed · repeat needed") |
| `note` | string \| null | context a reader needs (what counts, what is excluded) |
| `aggregate` | `{label, value, n, period}` \| null | a period summary beside the series. Deployments: the latest day's median ("day 07-29 median" 3.49°, n 57); counts: "all days" totals. Loops: null. |
| `provenance` | `Provenance` | |

### `Target`

`{value?: number, band?: [low, high], gate?: number, kind, label}`. `kind` is one of:

- `scope`: the total to burn up against (`of 62 rungs`).
- `gate`: pass at or past `value` in the KPI's direction (`gate 100 % feasible`, `TW2 gate ≤ 0.8°`).
- `limit`: stay under `value` (`stop line 91.0 % actual`).
- `reference`: a guide with no verdict (`reference 1×, no gate`).
- `descriptive`: a `band` that describes and never judges (`day floor 0.734°`).

### `KpiValue`

| field | type | meaning |
|---|---|---|
| `iteration` | string | the iteration id |
| `value` | number \| null | null when not measured |
| `of` | number \| null | the denominator of "x of y" values (16 of 62, 7 of 9) |
| `n` | number \| null | the sample size behind the value (runs, readings); null when not a sampled quantity |
| `spread` | number \| null | max − min of the n readings, when n > 1 and the adapter has them |
| `measured` | bool | false means draw a gap, never a zero |
| `note` | string \| null | why it is missing, or what it pools |
| `evidence` | string[] | ids of the evidence items behind this point; a click on the point opens these |

## `NeedsYou`

`{id, q, blocks: string[], default: string | null, applies: string | null}`, mapped by `needs.needs_you_rows()` from a needs.py item: `id` is the loop's own id (`T47`, `M5.ggcnn`, `plan-1`), `q` the item's ask, in the source's own words (markdown, verbatim): the triage title for kinsim and rig; for grasping the model id plus the CELLS `why` words for the ask (`M5.ggcnn · download approval`, never a framed "Approve …?"); for detection the plan note's bold lead plus the first sentence (or bullet) after it (`**Data.** The Seagate … yourself.`). `blocks` lists what the question holds: rungs or packages for the triage loops and detection, curriculum **cells** for grasping's download approvals (empty = holds nothing). Whether an item blocks *now* is needs.py's `blocking_now`, counted in `needs_you_count.blocking`; never infer it from `blocks` being non-empty (rig T4 names BN1 but its default is in effect). The rule: an open, unanswered item whose default is not in effect blocks only when a block's kind is `rung`, `package` or `gate` (`needs.GATING_KINDS`). A cell-only item never blocks: grasping's download approvals hold only that model's cells and no tier gate waits on them, so they read 0 blocking. `tests/test_dashboard_needs_truth.py` pins both directions. `applies` says when the default takes effect ("after W4"), "not stated" when the source gives a default but no time (the detection plan), null when there is no default. A null `default` reads "no default recorded".

## Evidence (level 3)

`evidence.by_iteration[<iteration id>]` is that iteration's items in a stable order. `evidence.by_kpi[<kpi id>]` lists item ids per KPI. `KpiValue.evidence` is their intersection, filled by the adapter.

| field | type | meaning |
|---|---|---|
| `id` | string | unique within the track |
| `iteration` | string | the iteration it belongs to |
| `kind` | `run` \| `lane` \| `audit` \| `gate` \| `report` \| `video` \| `note` | |
| `title` | string | "BT1 · regression r1", "gentle_step · ff_fb", "w3-fix-w1" |
| `when` | ISO string \| null | |
| `metrics` | `{[label]: number \| string \| bool \| null \| {[k]: number}}` | labels carry units ("rms (°)"); nulls are skipped by the kit |
| `status` | string \| null | the item's own word: `pass`, `fail`, `landed`, `parked`, `ok`, `below gate`, `building` |
| `media` | `{id, kind, label}[]` | references into the top-level `media` allowlist |
| `links` | `Link[]` | |
| `note` | string \| null | |

## Media

`media[<id>] = {id, kind: "video"|"html"|"image"|"text", label, path, mime, bytes}`. `text` is an audit write-up (markdown served as plain text). The backend streams a file only when its id is in this map, its path is absolute, its suffix is servable (`.mp4 .webm .html .png .jpg .jpeg .webp .gif .svg .md .txt .json`) and it is a regular file. Everything else is a 404. Videos support HTTP Range so `<video>` seeks. The adapter lists a file only if it exists when the projection is built.

## `Link` and `Provenance`

- `Link = {label, kind: "media"|"path"|"command", media?: id, value?: string}`. A `media` link opens through the allowlist; `path` and `command` are shown as text to copy.
- `Provenance = {snapshot, pointer, source, derived}`. `pointer` is a JSON pointer into the snapshot (`*` means every element); `source` is the live file the snapshot block names; `derived` says how a number was computed when it is not a plain read.

## The BAM adapter (`bam_loops`)

**Inputs, both copied once into `~/.local/share/vibetracks/dashboard/sources/`:**

- `bam-loops-snapshot-2026-10-03.json`, from `/home/bam/vibetracks/reports/media/dashboard-prior-art-2026-10-03/context/real-data.json`.
- `kinsim-curriculum-2026-10-03.json`, the curriculum the snapshot names. It supplies only each rung's `kpi_weight`, the one column the snapshot does not carry. It reproduces the snapshot's 25 of 118.

| track | iterations | KPIs | evidence |
|---|---|---|---|
| `kinsim` (loop) | start, W1, W2, W3 | 14: rungs green or done 4→7→7→16 of 62 · weighted capability 0→9→9→25 of 118 · BT1 feasible (W3 only, 73.4 %, gate 100 %) · RB0 feasible (counted readings only) · fast gate runs · packages landed 7/9, 2/6, 7/7 · rungs moved 3, 0, 9 · judged runs · Codex audits fail and pass · elapsed h (–, 22.2, 9.3) · questions opened · questions blocking a rung · disk % against the 91.0 % stop line | 70 items: wave reports (HTML), lanes and audits (with the audit write-ups that match by exact file name), gate runs, the 8 judged runs, rung changes, exploratory RB0 readings, disk events |
| `rig` (loop) | T0, T1, T2 (no event), T3 | 9: ladder rungs green 1→5→5→6 of 16 · TW2 twin gap (V1 0.639° in T1, baseline V0 3.526°, gate ≤ 0.8°) · packages landed · rungs moved · audits · elapsed h (cumulative, 12.2 at T3) · days since a real row · disk % against 92 % · open questions | 28 items: landed and building packages with their tick audit write-ups, audits, twin V0/V1 readings, rung and triage changes, disk events |
| `can12` (deployment of `rig`) | 17 sessions, 07-29 and the 10-02 twin replays | 12: the 10 bam_deployments session KPIs (real RMS, p95, sim–real gap, feedback torque, floor as a descriptive band, run counts, twin gap, twin ratio) plus 2 held conditions | 99 items: 57 real runs (44 with real video; sim videos where they exist), 30 twin replays, 12 bundle reports |
| `can16` (deployment of `rig`) | 4 sessions on 07-28 | 11: the same 10 plus held condition `gentle_step · ff_fb` 2.78 → 2.78 → 9.03 (n = 1 each: unconfirmed · repeat needed) | 26 items: 22 real runs, all with real and sim video, 4 bundle reports |

**Media:** 167 files, all checked to exist: 123 videos (66 real, 57 sim, 2.8 GiB), 20 HTML (3 wave reports, the deployments report, 16 bundle reports) and 24 audit write-ups.

**Placements that need a word:**

- **Rig tick 2** has no event. Its rung count comes from loop-status `rungs_moved_per_tick` (0). Every other tick-2 value is a gap that says so.
- **The twin gap V0 → V1** happened inside tick 1. Both replay sessions are at 22:39 and 23:02 on 10-02, and TW1 turned green at 23:01. So the rig loop shows V1 at T1 against the V0 baseline. The V0 → V1 step is drawn session by session in the `can12` track.
- **Kinsim disk** readings are preflight readings taken after the previous wave closed. Each value's note says so.
- **Held conditions** are one trajectory, mode and config read in at least three sessions, closed loop only. They are the like-for-like comparison. A session-median KPI mixes trajectories, which its provenance says.
