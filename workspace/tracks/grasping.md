---
vibe-track: worktrack
vibe-id: grasping
vibe-title: Grasping
vibe-status: running
vibe-priority: 3
vibe-owner: grasp-bench session
vibe-adapter: grasping
vibe-sources: [grasping_ledger, grasping_curriculum, grasping_out_dir, grasping_attestations, grasping_gallery_py, grasping_ledger_py, grasping_runner_py, grasping_contracts_py, grasping_bench_python, grasping_verdict_cache, grasping_bench_src, grasping_record, grasping_rebuild_status]
vibe-roadmap:
  projector: grasping
  sources: [grasp_bench_dir, grasp_bench_out]
vibe-children: []
vibe-project: BAM Robotics
vibe-sessions:
  branches: [claude/grasping-agent-roadmap-*, claude/grasp-bench-*, claude/grasping-evidence-rebuild-*]
  cwds: []
  titles: [grasping agent roadmap, grasp bench]
# Codex audit rounds of this track (the track page's Auditor tab; vibetracks/home/detail.py).
vibe-audits: ["/home/bam/bam_ws/reports/media/audits/*-grasp*.md"]
---

# Grasping

The grasp bench: a models × environments grid (bandit sanity, toy images, MuJoCo stages, GraspNet-1B, GraspClutter6D, live sim camera, kinsim, crab claw, reality), each cell judged on a frozen eval protocol with a Wilson lower bound against its gate. Since Oct 10 the evidence is being rebuilt: the old ledger was deleted with its worktree, so until the rebuilt ledger is judged the KPIs show the Oct 6 record, labelled "not yet re-proved". The bench's code lives on an unmerged lane (`claude/grasping-evidence-rebuild-cb787d`, a worktree a sweep can delete); its data lives outside every checkout, in `~/.local/share/grasp_bench/out`.

Hard gates: each gated environment, beaten on every training seed by the bench's own verdict. Soft KPIs: best executed grasp success per tier (toy, MuJoCo, sim camera, crab claw), dataset AP and label-judged top-1 kept apart, decision time p95 per tier, cells measured, evidence rebuild progress. The ledger is `~/.local/share/grasp_bench/out/ledger/runs.jsonl`, one row per model@env run.
