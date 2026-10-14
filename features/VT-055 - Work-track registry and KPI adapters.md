---
vibe-track: feature
vibe-id: VT-055
vibe-status: done
vibe-description: 'One note per work track and one adapter per loop, projecting KPIs, freshness and needs.'
vibe-areas:
- data
- model
vibe-depends-on:
- '[[VT-002 - Production refactor and dispatcher protocol]]'
vibe-priority: high
vibe-commits:
- 'b2f66a1'
- '0942c17'
- '5b75610'
vibe-evidence:
- '/home/bam/vibetracks/reports/media/vibetracks-dashboard-2026-10-04.html'
- '/home/bam/vibetracks/reports/media/vibetracks-live-tracks-2026-10-04.html'
vibe-origin:
- 'vault: kinsim-roadmap-lens-bar (Oct 3: all agent management moves into Vibe Tracks)'
- '/home/bam/vibetracks/reports/media/vibetracks-dashboard-2026-10-04.html'
---

# Work-track registry and KPI adapters

One Markdown note per work track (`workspace/tracks/`), read by `vibetracks/dashboard/registry.py`, and one
adapter per loop (kinsim, rig, grasping, detection, pyblocks) projecting KPIs, freshness and needs. The dashboard
merge (`5b75610`) went through Codex rounds 1-4.

## Where it came from

- vault: kinsim-roadmap-lens-bar (Oct 3: all agent management moves into Vibe Tracks)
- /home/bam/vibetracks/reports/media/vibetracks-dashboard-2026-10-04.html
