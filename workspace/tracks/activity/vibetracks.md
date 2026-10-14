---
vibe-track: activity
vibe-id: vibetracks
vibe-title: Vibe Tracks
vibe-status: running
vibe-priority: 10
vibe-project: vibetracks
vibe-sessions:
  branches: [claude/vibetracks-*, claude/vibe-tracks-*, claude/kincal-track]
  cwds: ["/home/bam/vibetracks*"]
  titles: [vibe tracks, vibetracks, vibe-tracks]
# Codex audit rounds of this track (the track page's Auditor tab; vibetracks/home/detail.py).
vibe-audits: ["/home/bam/vibetracks/reports/media/audits/*.md"]
# The repo's own plan (Project.vibetrack + features/VT-*.md) as this track's roadmap: the `features` projector
# (vibetracks/roadmap/projector/features.py) reads the checkout the sources key names (default the main clone).
vibe-roadmap:
  projector: features
  sources: {features_project_dir: vibetracks_project_dir}
---

# Vibe Tracks (home row)

A home-only note (`vibe-track: activity`): this repo's own work (the dashboard, roadmap, remote and home lanes). No
loop and no KPI adapter, so its row says what its sessions do and nothing else. Its roadmap is the repo's own feature
notes (`features/`), grouped under the five areas plus Data / Backend and Multi-machine (`Project.vibetrack`).
