---
vibe-track: feature
vibe-id: VT-063
vibe-status: backlog
vibe-description: 'Record each attempt with its parent, KPI values, session and account, for the experiment views.'
vibe-areas:
- data
vibe-depends-on:
- '[[VT-054 - Derived state from Claude Code''s own files]]'
vibe-priority: medium
vibe-evidence:
- '/home/bam/vibetracks/reports/media/evo-dashboard-study-2026-10-06/index.html'
vibe-origin:
- '/home/bam/vibetracks/reports/media/evo-dashboard-study-2026-10-06/index.html'
- 'vault: PROJECT - Vibe Tracks > Where the sources disagree (how a session joins a track)'
---

# Experiment records with parent, session and account

The experiments views (VT-045, VT-046, VT-047) need every attempt recorded as a row: its parent, KPI values,
the session and account that ran it. The evo study and the Oct 6 callout proposed `session_id` + `account` on each
KPI row; B1 joins sessions by rules instead. Neither is Zach's decision: an open fork to settle here.

## Where it came from

- /home/bam/vibetracks/reports/media/evo-dashboard-study-2026-10-06/index.html
- vault: PROJECT - Vibe Tracks > Where the sources disagree (how a session joins a track)
