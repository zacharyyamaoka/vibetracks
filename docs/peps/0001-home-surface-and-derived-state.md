# 0001 · The home is a page beside Clank, over a derived-state document

- **Date:** 2026-10-09
- **Status:** accepted for slice B1 (branch `claude/vibetracks-home`); recorded at merge
- **Source:** proposal B of `reports/media/vibetracks-linear-integration-2026-10-09/` (scored 84 against A 74 and C 61);
  Zach, Oct 9: "operational asap, with real data; we can fine-tune the presentation layer for a long time after that."

## Decision

1. **Surface.** The home (projects → tracks → sessions, the accepted Oct 6 Linear mock) is a thin static page,
   `vibetracks/home/static/`, served by the dashboard backend's `/home` mount (`clank/backend/mounts.py`). Through
   Clank's plugin proxy it is `/api/plugins/vibetracks/home/` on Stable, Preview and every lane. It sits **beside**
   the Clank plugin, not inside it: it owns only the home, and every row links into Clank's existing track pages
   and review (`/?vtdash=Agent%20work.vtdash#vt?track=<id>[&needs=1]`). A bare `/` (what the dock icon opens) is
   replaced by the home in `clank/src/plugin.tsx`; any query or hash keeps Clank.
2. **One read API.** The page reads one document, `vibetracks-home/1` (`GET /home`), and nothing else, so its look
   can change for weeks without touching data. The document is composed by `vibetracks/home/compose.py`.
3. **State is derived, never claimed.** Every state word, health colour, "worked" figure and last action comes from
   files the harness or the loops write: `~/.claude-*/sessions/<pid>.json` (live only when `/proc/<pid>/stat`
   field 22 equals `procStart`), the transcripts under `~/.claude-*/projects/` including subagent and workflow
   transcripts (which count toward their parent session), the dashboard projection (progress, loop freshness,
   `reporting`) and needs.py (the Needs-you counts). A note's `vibe-status` counts only as `done` or `archived`.
   Rule order: done/archived > needs you > error > stale > working > idle (`vibetracks/activity/derive.py`).
4. **Every session records how it was matched.** Tracks declare `vibe-sessions` (branches, cwds, titles); each
   session carries `join.by` and the rule that matched. A live session no rule matches is listed under "Other
   sessions"; none is ever dropped.
5. **No hooks.** Day 1 reads only what Claude Code already writes. A hook stays a possible second writer (B3).

## Why

- **Beside Clank, against "never a new shell":** the accepted design is a whole-app shell (an always-on sidebar, the
  account button bottom-left, a phone drawer); inside Clank it would be a second sidebar next to Clank's file tree,
  and Clank's shell measured unusable at 390 px. The page reuses Clank for everything except the home. Reversible:
  the same document can be rendered by a Clank viewer later (option A) without changing the backend.
- **Derived over claimed:** Zach's Oct 6 intent ("derived never claimed", "automate the agents stuff instead of
  depending on it"). Harness files are written by Claude Code, not by the agent, and cover 7 days of history today.
- **Transcripts over hooks:** no change to the settings all 5 accounts share. Cost: the transcript format is internal
  to Claude Code (2.1.284 today) and may change; the fixtures in `tests/fixtures/home/` pin the shapes read.

## Consequences

- The transcript index folds ~2,000 files / 4.6 GB on a cold start (~12 s) and persists in
  `~/.local/share/vibetracks/home/` (3.5 MB), so a restarted backend is warm in ~0.1 s; a warm `/home` measured
  p50 20 ms, p95 23 ms.
- The sps chip is not injected into the home (it is served through the `/api/` proxy, which the runtime passes
  through); the chip stays on Clank's pages. Fixing that is a runtime change, not an app change.
- Activity-only tracks (no KPI adapter yet) are notes with `vibe-track: activity` under `workspace/tracks/activity/`;
  the work-track registry ignores them. When an adapter lands (fivebar, kincal), the work-track note is the row and
  borrows any home key it lacks from the activity note of the same id.
