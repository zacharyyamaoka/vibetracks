---
vibe-track: worktrack
vibe-id: detection
vibe-title: Object Detection & Hyperspectral
vibe-status: running
vibe-priority: 4
vibe-owner: hyperspectral planning session
vibe-adapter: detection
vibe-sources: [detection_queue_log, detection_logs_dir, detection_wandb_dir, detection_compile_results, detection_queue_script, detection_ladder, detection_plan_note, detection_reports_dir]
vibe-roadmap:
  projector: detection
  sources: [detection_dir]
vibe-children: []
vibe-project: BAM Robotics
vibe-sessions:
  branches: [claude/hyperspectral-*]
  cwds: [/home/bam/spectralwaste-segmentation]
  titles: [hyperspectral, object database, object db]
---

# Object Detection & Hyperspectral

Waste segmentation with hyperspectral input: a 10-rung ladder (H0 plumbing to H9 a real stream), first reproducing the published SpectralWaste results (H1, 2 of 12 configs so far), then mock sensors and sim to real.
Milestone: a valid hyperspectral test mIoU against the paper's 58.2. The loop has not started; the only state today is the July repro queue log.
