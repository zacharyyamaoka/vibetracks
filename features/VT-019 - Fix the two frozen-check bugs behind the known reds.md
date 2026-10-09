---
vibe-track: feature
vibe-id: VT-019
vibe-status: waiting
vibe-description: 'Two one-line bugs in frozen acceptance checks and a pre-existing kinsim adapter error keep the suite at 3 reds.'
vibe-areas:
- home
- data
vibe-depends-on:
- '[[VT-017 - Home on derived state, the Linear initiatives table]]'
vibe-priority: high
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-home-b1-2026-10-09/index.html'
vibe-origin:
- 'B1 report > Acceptance 1, 4 and Decision surface'
- 'vault: PROJECT - Vibe Tracks > Open questions 1'
---

# Fix the two frozen-check bugs behind the known reds

The suite runs with 3 known reds on main (543 run on this branch):

- `tests/test_home_live.py:233` reads tuples as dicts (`test_deleting_one_matching_rule_never_loses_the_session`).
- The kinsim spot check reads a transcript's file time, which Claude Code's end-of-session bookkeeping moves
  (`test_kinsim_last_loop_write_and_stale`).
- `test_dashboard_adapter.test_kinsim_burn_up_and_weighted`, a pre-existing error B1 and B2 both carried.

The first two are one-line bugs in frozen acceptance checks, so fixing them touches the ruler: **waits on Zach's
OK** (B1 decision surface). Done when the suite is green or each remaining red is named with its reason.

## Where it came from

- B1 report > Acceptance 1, 4 and Decision surface
- vault: PROJECT - Vibe Tracks > Open questions 1
