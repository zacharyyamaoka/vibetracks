# Building a variant

Three proposals share one shell, one data contract and one kit. A variant owns **only its own folder**: `clank/src/variants/a/` for Drill-down pages, `b/` for Shared timeline, `c/` for Three panes. It must not edit `clank/src/shared/`, `Dashboard.tsx`, `plugin.tsx`, the backend or the adapter. Those are the frozen contract. If you need a change there, report it instead of making it.

## Run it

- **Lane (already running, Vite HMR):** `http://127.0.0.1:4390/?vtdash=Agent%20work.vtdash`. Edits under `clank/src` reload in place.
- **Start or reuse it:** `/home/bam/vibetracks-dashboard/scripts/open-dashboard --no-open`.
- **Headless proof:** `node /home/bam/vibetracks-dashboard/scripts/shoot.mjs --variant b --hash '#vt?track=kinsim' --out /abs/shot.png`. It prints JSON facts (the variant shown, console errors, failed requests).
- **The kit on real data:** add `#vt?kit=1` to the URL.
- **Typecheck:** `/home/bam/clank-workbench/node_modules/.bin/tsc -p /home/bam/vibetracks-dashboard/clank`.
- **A file created while Vite runs** may need `touch /home/bam/clank-workbench/src/styles/app.css` before Tailwind scans it (Clank CLAUDE.md §1.5). The kit's own CSS is plain (`calm.css`), so this matters only if you use Tailwind classes.

## The contract

`export default function VariantX(props: VariantProps)` and `export const NAME`. `VariantProps` (`shared/types.ts`):

| prop | what |
|---|---|
| `projection` | the whole projection (`docs/dashboard/PROJECTION.md`) |
| `mediaUrl(id)` | same-origin URL for a media id: `<video src>`, `<iframe src>`, `<a href>` |
| `route`, `navigate(route, 'push' \| 'replace')` | place, kept in the URL hash (`#vt?track=…&kpi=…&iteration=…&item=…`, plus any keys you add). Push for a deeper level so Back climbs a level; replace for a sideways move. All three variants share the route, so the switcher keeps the selection. |
| `reload({rebuild?})` | re-read the projection, or rerun the adapter first |
| `title` | the .vtdash file's title ("Agent work") |
| `backend` | `ctx.backend`, if you need it |
| `settings` | `{ dashboard: DashboardSettings, roadmap: RoadmapSettings }`, the reader's view options from the settings page (below) |
| `setSettings(update)` | merge a change and save it: `setSettings({ dashboard: { xAxis: 'day' } })`. Rarely needed; the settings page is where the reader changes them. |

`routeLevel(route)` gives 1 (no track), 2 (a track) or 3 (an iteration or item open). Use it, or derive levels your own way.

## The kit (`import { … } from '../../shared'`)

**Model helpers (`shared/model.ts`):**

- Lookups: `trackById`, `topLevelTracks`, `childrenOf`, `kpiById`, `northStar`, `iterationById`, `latestIteration`, `valueAt`, `kpisBySlot` (with `SLOT_NAMES`).
- Values: `measuredValues`, `latestValue`, `previousValue`, `deltaVsBaseline`, `deltaVsPrevious` (direction-aware `better`, and `unconfirmed` when n ≤ 1), `targetState`, `valueDomain`.
- Evidence: `allEvidence`, `evidenceAt`, `evidenceById`, `evidenceForValue(track, kpi, iterationId)` (the provenance click), `evidenceForKpi`, `blockingQuestions`.
- Formatting: `formatValue(value, unit, of)`, `formatKpiValue`, `formatDelta`, `formatN`, `describeDelta` (writes the n = 1 rule's words for you), `formatTargetLabel`, `formatDay`, `shortDay`.
- Tone: `isException`, `toneClass`, `deltaTone`. The constant `N1_WORD` is `unconfirmed · repeat needed`.

**Components:**

| component | use |
|---|---|
| `<StatusWord status detail? />` | a dot plus a word; colour only for warn, risk and stale |
| `<Sparkline values target? domain? selected? step? />` | a 64 × 18 glyph; gaps break the line; the latest point is emphasised |
| `<SeriesChart kpi iterations selected onSelectIteration compact? domain? leftMargin? readout? />` | one KPI on the aligned x-axis: target line or band, change-marker hairlines (marker text in the readout and tooltip), n labels, hollow points for n ≤ 1, gaps for unmeasured iterations, a clickable column per iteration. Keep `leftMargin` equal across stacked charts so their columns line up. |
| `<EvidenceList items mediaUrl openMedia? onOpenMedia? selectedItem? onSelectItem? />` | level-3 rows with metrics; media open in place (video, report frame, audit text) plus "Open in new tab" |
| `<MediaView media url />`, `<VideoPlayer src />` | one media item on its own |
| `<Breadcrumb items />` | every crumb but the last is a button |

**CSS (`shared/calm.css`, rooted in `.vt-dash`):** `vt-page`, `vt-h1`, `vt-h2`, `vt-h3`, `vt-sub`, `vt-muted`, `vt-faint`, `vt-small`, `vt-num`, `vt-strong`, `vt-label`, `vt-table` (`tr.vt-row-link`, `tr.vt-group`, `.vt-latest`, `.vt-gap`), `vt-btn` (an unstyled button), `vt-chip-btn`, `vt-tone-*`. The colour tokens are `--vt-fg`, `--vt-grey`, `--vt-faint`, `--vt-line`, `--vt-hover`, `--vt-press`, `--vt-accent`, `--vt-band`, `--vt-warn`, `--vt-risk` and `--vt-stale`. Root any CSS of your own in `.vt-dash .vt-<your variant>` inside `@layer base`, and import it from your folder.

## Settings: view options go on the settings page, never in a toolbar

Zach, 2026-10-03: *"it's important that the tool bar is actually usable. This line setting should instead be in a settings page."* So:

- **The rule.** A view option (x-axis unit, density, show deltas, line style, ...) is an item in `DASHBOARD_SETTINGS_SECTION` (`shared/settings.ts`). It is never a button, toggle or select in a variant's header or toolbar. Headers and toolbars carry only navigation and actions.
- **Where the reader changes them.** The shell's slim header has one quiet gear at its right end (`Dashboard.tsx`). It opens the settings page (`shared/SettingsView.tsx`, route key `settings=1`, so Back or Esc closes it). The page lists `[DASHBOARD_SETTINGS_SECTION, ROADMAP_SETTINGS_SECTION]`.
- **The shape.** The sections use Clank's own `SettingsSection` / `SettingsItem` from `@clank/api`, so they can later move into Clank's plugin settings page through `ctx.registerSettings`. The page renders `boolean` (checkbox), `enum` (select; Clank's name for a select), `number` (number field, honouring `min`/`max`) and `string` items.
- **Storage.** One localStorage key, `vibetracks.dashboard.settings`, holding `{dashboard: {...}, roadmap: {...}}`. Every access is wrapped in try/catch, so blocked storage falls back to the defaults. A stored value an item rejects (an unknown enum option, a number out of range) falls back to that item's default.
- **What a variant reads.** `props.settings.dashboard` and `props.settings.roadmap`. Pass `props.settings.roadmap` to `<RoadmapWidget settings>`.

**The dashboard items today:**

| key | type | default | meaning |
|---|---|---|---|
| `xAxis` | `'iteration' \| 'day'` | `'iteration'` | One column per iteration (the track's own wave, tick or session), or per calendar day. With `day`, iterations that share a date share a column, and an iteration with `date: null` (rig tick 2) is shown as undated, never dropped. |
| `showDeltas` | boolean | `true` | Show each KPI's change beside its latest value (`deltaVsBaseline` / `deltaVsPrevious`, with the n = 1 wording). Off hides the delta text only; status words and exceptions stay. |

To add one: add the field to `DashboardSettings` and `defaultDashboardSettings`, add an item to `DASHBOARD_SETTINGS_SECTION`, and document it in this table. These are shared files, so report the addition instead of making it from a variant folder.

## The roadmap widget

`import { RoadmapWidget, useRoadmap } from '../../roadmap'`. Until the roadmap session lands, it is a stub with the agreed signatures (`clank/src/roadmap/index.tsx`): `RoadmapWidget` takes `{track, doc, state, onState, onOpenRung, onOpenEvidence, density, settings}` and renders one grey line, and `useRoadmap(backend, track)` returns `{doc: null, loading: false, error: null}`. Placement and routing are in `VARIANTS.md` ("Roadmap widget slot"). The backend gains its `/roadmap` routes through `clank/backend/mounts.py`.

## The criteria you are judged on

These are in `BRIEF.md`. Three clean levels (L1 tracks, L2 that track's KPIs over iterations, L3 evidence), the research principles visibly applied, the calm language of The Table, KPI progress legible at a glance, and real, working evidence. The hard gates: truthful data (G1), no fake controls (G2), local only (G3), and one command (G4).
