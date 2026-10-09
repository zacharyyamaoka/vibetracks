---
vibe-track: worktrack
vibe-id: kinsim
vibe-title: Kinematic Sim
vibe-status: running
vibe-priority: 1
vibe-owner: Kinematic Sim (AGENT) session
vibe-adapter: kinsim
vibe-sources: [kinsim_status, kinsim_events, kinsim_runs, kinsim_loop_dir, reports_media_dir]
vibe-roadmap:
  projector: kinsim
  sources: [kinsim_curriculum_dir, kinsim_home]
vibe-children: []
vibe-project: BAM Robotics
vibe-sessions:
  branches: [claude/kinematic-simulator-waste-sorting-*, claude/wave-3-handoff-*, claude/kinematic-simulator-loop-*, claude/roadmap-curriculum-viz-*]
  cwds: []
  titles: [Kinematic Sim (AGENT), Traj Gen and Kinematic Sim]
# Codex audit rounds of this track (the track page's Auditor tab; vibetracks/home/detail.py).
vibe-audits: ["/home/bam/bam_ws/reports/media/audits/*-kinsim-*.md", "/home/bam/bam_ws/reports/media/audits/*-w[0-9]-*.md"]
---

# Kinematic Sim

The kinematic-simulator curriculum loop: one wave per tick climbs a ladder of 62 rungs over 9 axes (robots, objects, scene, grasping and perception, multi-robot, belt speed, eval, regression, visualization).
Milestone: pick up a single piece of waste in sim. Its live fold is `status.json` in the curriculum home, with `runs.jsonl` as the judged-run ledger.
