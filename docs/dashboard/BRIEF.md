# Vibe Tracks dashboard: three-level proposals (brief and frozen criteria, 2026-10-03)

> **Archived 2026-10-05: Zach chose A; B and C removed in 56c75c0.** This is the brief for the 2026-10-03 round, which asked for three proposals; it is kept as written. The research principles, the design language and the hard gates G1-G4 below still govern the one layout that ships, A · Drill-down pages. For what the product does now, read `VARIANTS.md` ("Current") and `NEEDS-KIT.md`.

## What Zach asked for (verbatim, 2026-10-03)
> "These all still suck. I don't feel like you are implementing any of the ideas you got from the prior art research. The Numbers and the Table are the only proposals that seem a bit similar to prior art. One thing I do like is how minimal and clean and quiet it is. Keep that design language, but now the actual content needs to be improved. I like how in the prior art … people converged on seeing the data at 3 levels of resolution. … at the top level I am selecting between different agent loops… or work tracks… that top level can potentially be like different tabs… or honestly even just the table as you have. At the next level though now I probably want to see maybe like another table, and this one now has like the same thing but for each KPI! and perhaps now I see like how those KPIs are progressing over like some time period. … Please look at the principles you extract from this work and make sure we are using those ideas. Please come up with 3 more proposals. And build them as fully fleshed out apps I can open up."

He also renamed the project **Vibe Tracks** and moved this work into this repo.

He attached three things:
1. A screenshot of the liked calm table, "The Table" from the previous round (`reports/media/dashboard-babble-2026-10-03/variants/v2/preview.html`): one quiet row per loop (Name · Status · Progress with sparkline · Last moved · Needs you).
2. The research's universal pattern **"Entity × period scorecard matrix: latest column emphasised, trend and status chip at the end of each row"** (Antioch release regression suite, SRE compliance report, PyTorch HUD).
3. The universal pattern **"Three-level drill-down: glance, then series or compare, then per-run evidence"**.

## The research principles every proposal must apply
Source: `reports/media/dashboard-prior-art-2026-10-03.html` §4. The structured list is `reports/media/dashboard-prior-art-2026-10-03/context/workflow-results.json` → `synth:convergence.patterns`. The ones that matter here:
- **Solve the display once:** a fixed template, with KPIs bound as data. Every track renders through the same grammar.
- **Three levels:** (1) glance: pick a track; (2) that track's KPIs over iterations; (3) per-run or per-iteration evidence that links back to the change.
- **Scorecard matrix:** rows = KPIs, columns = iterations (wave / tick / session), latest column emphasised, trend + status at the row's end, grey for never-measured.
- **One object per KPI:** number, trend and context (target or band, direction-aware delta vs a named pinned baseline) together.
- **Small multiples / sparklines on a shared, aligned x-axis.**
- **Change markers:** what happened at each iteration (wave closed, ruler changed, tick) runs through every chart or column.
- **Provenance:** every point is a change, and clicking it reaches its evidence.
- **Missing or not-measured data is an explicit state,** never an empty chart.
- **Uncertainty travels with the number:** n, spread, unconfirmed. n=1 per condition reads "unconfirmed · repeat needed"; day floors are descriptive bands, never verdict thresholds.
- **Progress = level + rate:** burn-up against scope or target.
- **Identity colour only for compare; status colour only for exceptions.**

## Design language (keep it)
The calm Notion/Obsidian language of round 2:
- one system sans-serif;
- near-black on white, grey secondary text, hairline dividers at most;
- generous whitespace and a clear typographic scale;
- one accent; colour only for exceptions (paused, at risk, unconfirmed);
- no chip walls, no boxes everywhere.

The global memory rule `feedback_calm_ui_progressive_disclosure` applies: one calm answer first, detail one deliberate click deeper.

## Frozen criteria (fixed before any build)
| id | name | weight | pass condition |
|---|---|---|---|
| fr1 | Three clean levels | 25 | L1 tracks → L2 that track's KPIs over time → L3 per-run/per-iteration evidence. Each level is one deliberate action away, keeps place (URL/back works), and is reversible. |
| fr2 | Research principles applied | 25 | Visibly uses the principles above, especially the scorecard or shared-axis series, latest emphasis, trend + status, target or band, change markers, evidence via provenance, explicit missing data, and n / unconfirmed. |
| fr3 | Calm design language | 20 | Reads like the liked Table: minimal, quiet, colour only for exceptions. |
| fr4 | KPI progress over time is legible | 15 | At L2, how each KPI moved across iterations reads at a glance. |
| fr5 | Real and working | 15 | Real data end to end. Evidence actually opens (run videos, wave reports, run metrics). No dead ends. |

Score anchors: 1 = absent or broken, 3 = present but partial or busy, 5 = exemplary.

**Hard gates:**
- **G1 truthful data:** every number is from the projection; n=1 never "regressed"; elapsed hours never "agent-hours".
- **G2 no fake controls:** every clickable thing does something.
- **G3 local-only:** loopback server, no network, no external fonts or scripts.
- **G4 one command:** `scripts/open-dashboard` starts or reuses the server and opens it.
