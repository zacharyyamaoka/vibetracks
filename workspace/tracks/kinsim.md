---
vibe-track: worktrack
vibe-id: kinsim
vibe-title: Kinematic Sim
vibe-status: running
vibe-priority: 1
vibe-owner: Kinematic Sim (AGENT) session
vibe-adapter: kinsim
vibe-sources: [kinsim_status, kinsim_events, kinsim_runs, kinsim_loop_dir]
vibe-roadmap:
  projector: kinsim
  sources: [kinsim_curriculum_dir, kinsim_home]
vibe-children: []
---

# Kinematic Sim

The kinematic-simulator curriculum loop: one wave per tick climbs a ladder of 62 rungs over 9 axes (robots, objects, scene, grasping and perception, multi-robot, belt speed, eval, regression, visualization).
Milestone: pick up a single piece of waste in sim. Its live fold is `status.json` in the curriculum home, with `runs.jsonl` as the judged-run ledger.
