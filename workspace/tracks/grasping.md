---
vibe-track: worktrack
vibe-id: grasping
vibe-title: Grasping
vibe-status: running
vibe-priority: 3
vibe-owner: grasp-bench session
vibe-adapter: grasping
vibe-sources: [grasping_ledger, grasping_curriculum, grasping_out_dir, grasping_attestations, grasping_gallery_py, grasping_ledger_py, grasping_runner_py, grasping_contracts_py, grasping_bench_python, grasping_verdict_cache, grasping_bench_src, grasping_record, grasping_roadmap_v4, grasping_scoreboard, grasping_queue_status_json, grasping_queue_status, grasping_triage]
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

The grasp bench: a models × environments grid (bandit sanity, toy images, MuJoCo stages, GraspNet-1B, GraspClutter6D, live sim camera, kinsim, crab claw, reality), each cell judged on a frozen eval protocol with a Wilson lower bound against its gate. The evidence rebuild finished on Oct 11 (all 9 steps, 0 failures), and the loop's runner service now runs every requested experiment. The header's four tiles (picks per hour, hold-out success, decision time p95, bench score with gates held) and the hard gates come from `~/.local/share/grasp_bench/out/scoreboard/scoreboard.json`, which the runner rewrites as runs finish; a tile says "stale since" while the scoreboard has not read the newest runs. The bench's code lives on an unmerged lane (`claude/grasping-evidence-rebuild-cb787d`, a worktree a sweep can delete); its data lives outside every checkout, in `~/.local/share/grasp_bench/out`.

Hard gates: the scoreboard's eight v5 gates, each beaten only when one model family clears the bar on every training seed (three for a learned model, one for a deterministic one). Soft KPIs: the champion's four header tiles; under them, folded, the v4 gallery's detail (best single seed per tier, dataset AP and label-judged top-1, decision time per tier). Decisions come from the loop's `~/.local/share/grasp_bench/loop/triage.json`; answers go to `triage_answers.jsonl` beside it. The ledger is `~/.local/share/grasp_bench/out/ledger/runs.jsonl`, one row per model@env run.
