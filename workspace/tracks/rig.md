---
vibe-track: worktrack
vibe-id: rig
vibe-title: Sim to Real & Trajectory Tracking
vibe-status: running
vibe-priority: 2
vibe-owner: hardware rig loop session
vibe-adapter: rig
vibe-sources: [rig_loop_status, rig_events, rig_ladder, deployments_fixtures_dir, rig_triage, rig_roadmap, rig_deployments_cache, rig_audits_dir]
vibe-roadmap:
  projector: rig
  sources: [rig_loop_dir]
vibe-children: [can12, can16]
vibe-project: BAM Robotics
vibe-target: 2026-10-22
vibe-sessions:
  branches: [claude/rig-loop-work-continue-*, claude/traj-tracking-sim-to-real-*, claude/one-dof-agent-plan-*]
  cwds: []
  titles: [traj tracking, trajectory tracking, sim to real]
---

# Sim to Real & Trajectory Tracking

The hardware rig loop: the 1-DOF CAN 12 pendulum, then the five-bar, then the arm, with a twin that must replay real runs within the TWIN gate. Six rung ladders (twin, control, camera, bench, ruler, live) in `ladder.json`, projected each tick into `loop-status.json`.
Milestone: pick up a single piece of real waste (due 2026-10-22). The CAN 12 and CAN 16 deployments are its evidence, drawn inside this track.
