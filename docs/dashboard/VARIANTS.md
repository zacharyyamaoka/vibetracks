# The dashboard layout: A · Drill-down pages (current), and the archived proposals

**Current product (2026-10-05):** one layout ships, **A · Drill-down pages** (`clank/src/variants/a/`). There is no layout switcher. The "Needs you" page under it is documented in `NEEDS-KIT.md`; its default proposal is **N6 · Lane + context**. The three-proposal text further down is **archived**: it is the 2026-10-03 brief as written, kept for its reasoning, and it does not describe the product.

## Current: A · Drill-down pages

One level per page, a breadcrumb on every page, and the place kept in the URL hash, so Back, Forward and the mouse back button climb exactly one level. The level map, verbatim from `clank/src/variants/a/index.tsx`:

```text
//   L1  Work tracks table ("The Table"), no deployments    #vt
//   L2  Track page: state, Needs you →, KPIs, Roadmap       #vt?track=kinsim
//   L3  Iteration page: what changed, KPI deltas, evidence  #vt?track=kinsim&iteration=W3[&kpi=…]
//       → one item (run metrics + video, report, audit)    #vt?track=can16&item=…
```

- **L1, the work-tracks table** (`TracksPage.tsx`). One quiet row per **work track**, in the registry's order. The columns, as the lane renders them: `Name · Status · Progress · Current rung → next · Last moved · Needs you`, then a `⋯` row menu. **No deployments on this page:** CAN 12 and CAN 16 are evidence inside the rig track and are listed on its page (Zach, 2026-10-04: "you can get rid of the deployments on the first page"). A track that is not reporting says why in grey and claims no numbers; its Needs-you cell reads `not reported`, never 0. The Needs-you cell (`N blocking · M open`) opens that track's Needs page, `#vt?track=<id>&needs=1`.
- **L2, the track page** (`TrackPage.tsx`), in Zach's order:
  1. the name (double-click to rename), one line of state, and the link `Needs you · 1 blocking · 3 open →` (kinsim on the lane, 2026-10-05);
  2. the scorecard: KPI rows by slot, one column per iteration, the latest column emphasised;
  3. the **Roadmap** section. `clank/src/roadmap/` is still the agreed stub, owned by the roadmap session; it renders "Roadmap widget pending (roadmap session)";
  4. for the rig loop only, its deployments as a quiet sub-list (heading "Deployments", grey note "evidence for this track"), each opening its own page through the same template.
- **L3, the iteration page** (`IterationPage.tsx`): what changed (the change marker and its provenance), each KPI's value and its change against the previous iteration, then the evidence grouped by kind. **One item** (`ItemPage.tsx`): a run's metrics and its video (real and sim side by side when both exist), a report in a frame, or an audit write-up as text, plus "This feeds", the KPI points it stands behind.
- **Media** opens through `/media/<id>?rev=<media_rev>`, bound to the projection revision the page was given (PROJECTION.md, Media). A 409 shows "This changed since you opened it: reload". **The Needs page never uses `/media`:** every evidence link there goes through `/needs/evidence`, bound to the Needs document's `evidence_rev` and the entry's `eid` (NEEDS-KIT.md).
- **Settings, not toolbars.** A quiet gear at the right end of the header opens the settings page (`#vt?…&settings=1`; Back or Esc closes it). Its Dashboard section has three items, titled verbatim from `shared/settings.ts`: `X axis`, `Show deltas`, and `Needs you · Include questions whose default is already in effect`. The Roadmap section has none yet.
- **The review bar** (`#vt-review-bar`, below the scroll area) is shown only on the Needs page, where it holds the one N pill (`Needs you · N6 · Lane + context ▾`). Elsewhere it takes no space.
- **The retired switcher.** `Dashboard.tsx` removes the old `localStorage['vibetracks.dashboard.variant']` choice on load; nothing reads it.

## Rules every page keeps

- **Data:** real data only, from the projection (`PROJECTION.md`) and, for Needs you, from `/needs` (`NEEDS-KIT.md`).
- **Honesty:** n=1 is "unconfirmed · repeat needed"; elapsed hours are elapsed.
- **Missing data:** shown explicitly, never as an empty chart or a 0.
- **Controls:** no dead controls. Every track renders through the same template: kinsim, rig, its deployments CAN 12 and CAN 16, grasping, detection, pyblocks.
- **View options** live on the settings page, never on a toolbar (Zach, 2026-10-03: "it's important that the tool bar is actually usable").

## Archived 2026-10-05: the three proposals of 2026-10-03

> **Archived 2026-10-05: Zach chose A; B and C removed in 56c75c0.** Everything below is the 2026-10-03 proposal as it was written, before the build. It names three active layouts, an A · B · C chooser, deployments as rows on A's home page, and roadmap placements for B and C; none of that is current (A's roadmap section on the track page is). Git keeps B and C's code at 8369c05. For the product, read the sections above.

### Three proposals: same three levels, same principles, different composition

All three share the levels:
- **L1** pick a track;
- **L2** that track's KPIs over its iterations;
- **L3** per-iteration or per-run evidence.

They also share the research principles (BRIEF.md), the data (PROJECTION.md) and the calm language ("The Table"). They differ ONLY in how the three levels are composed on screen, so Zach can judge the composition itself.

### A · Drill-down pages (asv grid → benchmark page → regressions; PyTorch HUD; Statuspage)
One level per page, a breadcrumb at the top (`Agent work › Kinsim curriculum › Wave 3 › run rb0-regression-…`), and URL-hash routing so Back/Forward and the mouse back button work.
- **L1, the Tracks table.** "The Table": one quiet row per track; deployments are indented rows under the 1-DOF rig loop. Columns:
  - Name
  - Status (dot + word + grey detail)
  - Progress (north-star value / scope + sparkline)
  - Last moved
  - Needs you (N blocking · M open)
  
  Clicking a row opens L2.
- **L2, the Track page.**
  - A one-sentence state and a collapsed "Needs you (N)" line that expands to its list.
  - Then **the scorecard**: rows are KPIs grouped by slot (north star first, then frontier, guardrails, delivery, trust, cost). Columns are the iterations (Start, W1, W2, W3 / T0…T3 / sessions), and the **latest column is emphasised**: bold, with a faint wash.
  - Each cell shows its value. A cell is "—" in grey when not measured, and n is shown when it matters.
  - Trailing columns: trend sparkline · target or band · status word.
  - Colour appears only on exceptions vs target or pinned baseline.
  - Column headers carry the change marker on a second grey line ("7/7 landed · ruler a2-v2").
  - Clicking a column header opens that iteration (L3). Clicking a cell opens L3 scrolled to that KPI.
- **L3, the Iteration page.**
  - What changed (marker + provenance), then each KPI's value and its delta vs the previous iteration (one quiet list).
  - Then the evidence list: runs, lanes, audits, gates, the report.
  - Clicking a run opens its run detail: metrics + VideoPlayer. Real and sim side by side if both exist; n=1 labelled.
  - Wave reports open as links. Media comes through the backend's /media/<id>.

### B · Shared timeline (Grafana annotations + intervals.icu header readout + Rerun's single cursor + Tufte small multiples)
- **L1, tabs** across the top, one per loop: Kinsim curriculum · 1-DOF rig loop. The rig's deployments are secondary tabs (CAN 12 · CAN 16) shown when the rig is selected. Each tab carries a state dot. Under the tabs sits one grey sentence of state.
- **L2, the KPI wall.** One row per KPI, all rows sharing ONE aligned x-axis of the track's iterations. Each row:
  - label
  - latest value with a direction-aware delta vs baseline
  - a wide SeriesChart strip: target band, gaps for not-measured, n annotations
  - status word
  
  **Change markers** are thin vertical hairlines running through every row, labelled once at the top ("W2 · 0 rungs moved", "W3 · 7/7 landed").
  
  **Hovering or clicking an iteration** places one vertical cursor through all rows, and every row prints its value at the cursor. That is "associations at a glance": you see what moved together in one wave.
- **L3, the drawer.** Clicking the cursor's iteration (or pressing Enter) opens a bottom drawer: that iteration's marker + provenance, its evidence list, and a run's metrics + video inline. Esc or × closes it. Only one drawer at a time.

### C · Three panes (Linear / Superhuman / Apple Mail master-detail; Miller columns)
All three levels are visible at once, each in its own pane, with selection driving everything:
- **Pane 1 (L1, narrow):** the tracks list, each with a state dot, its name and its north-star value. Deployments are indented under the rig.
- **Pane 2 (L2, medium):** the selected track's KPI table. Columns: KPI · latest · Δ vs baseline · sparkline · status. Rows are grouped by slot, and the selected KPI is highlighted.
- **Pane 3 (L3, wide):** the selected KPI's detail.
  - A large SeriesChart over iterations with target, markers and n.
  - **Clicking a point** selects that iteration.
  - Below the chart: the evidence for the selected iteration (runs, lanes, audits, report), and the run detail (metrics + video) when a run is selected.
- **Keyboard:** ↑/↓ moves within a pane, ←/→ moves between panes, Enter drills, Esc goes up. The selection is reflected in the URL hash.
- A thin header line answers the glance: "2 loops · 1 paused · 1 at risk · 7 questions block a rung".

### Common to all three
- **Data:** real data only, from the projection.
- **Honesty:** n=1 is "unconfirmed · repeat needed"; elapsed hours are elapsed.
- **Missing data:** shown explicitly, never as an empty chart.
- **Controls:** no dead controls. Each variant works for every track: kinsim, rig, CAN 12, CAN 16.

### Roadmap widget slot (agreed with the "Roadmap and curriculum visualization" session, 2026-10-03)
Zach: "the roadmap is just like one widget that is part of the dashboard which is kinda more about like layout etc."
- **Placement:** every variant places `<RoadmapWidget>` (from `clank/src/roadmap/`, owned by the roadmap session; a stub until they land) at **L2**, under the KPI view. It's a quiet, collapsed "Roadmap" section: closed it shows `density='calm'`, expanded it shows `density='full'` in place.
- **State:** `{lens, orient, card, sel}` is controlled and lives in the URL hash under `rm` (JSON), so one history covers the whole dashboard.
- **Routing:** `onOpenRung(rungId)` goes to L3 evidence for that rung's latest judged run (or a rung note if none). `onOpenEvidence({path, line})` goes to the L3 file view.
- **Variant placement:**
  - A puts the section on the Track page.
  - B puts it under the KPI wall.
  - C makes it a tab or section in pane 2 next to the KPI table. It must not crowd the glance.

### Settings live on a settings page, never on toolbars (Zach, 2026-10-03)
"it's important that the tool bar is actually usable. This line setting should instead be in a settings page, so that eventually, when you deploy in a Clank workbench or something else, you can put access to it in the plugin settings page."
- **One SettingsView** (`src/shared/SettingsView.tsx`), opened from a quiet gear at the right end of the dashboard header. It renders `[DASHBOARD_SETTINGS_SECTION, ROADMAP_SETTINGS_SECTION]` in Clank's `SettingsSection` shape.
- **Storage:** values persist in the dashboard's view state (localStorage, wrapped). The roadmap slice is passed down as the widget's `settings` prop.
- **Variant builders:** put any view option (x-axis unit session/wave/day, density, show-deltas, etc.) in `DASHBOARD_SETTINGS_SECTION`, never in a toolbar. Headers and toolbars carry only navigation and actions.
- **The A/B/C switcher** (bottom-right) is the temporary prototype chooser and goes away once Zach picks.
