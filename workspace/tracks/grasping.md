---
vibe-track: worktrack
vibe-id: grasping
vibe-title: Grasping
vibe-status: running
vibe-priority: 3
vibe-owner: grasp-bench session
vibe-adapter: grasping
vibe-sources: [grasping_ledger, grasping_curriculum, grasping_out_dir]
vibe-roadmap:
  projector: grasping
  sources: [grasp_bench_dir]
vibe-children: []
---

# Grasping

The grasp bench: a models × environments grid (bandit sanity, toy images, MuJoCo stages, GraspNet-1B, GraspClutter6D, live sim camera, kinsim, crab claw, reality), each cell judged on a frozen eval protocol with a Wilson lower bound against its gate.
Milestone: clear the MuJoCo stages, then the dataset envs. The ledger is `out/ledger/runs.jsonl`, one row per model@env run.
