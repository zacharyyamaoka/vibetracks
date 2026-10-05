---
vibe-track: worktrack
vibe-id: detection
vibe-title: Object Detection & Hyperspectral
vibe-status: running
vibe-priority: 4
vibe-owner: hyperspectral planning session
vibe-adapter: detection
vibe-sources: [detection_queue_log]
vibe-roadmap:
  projector: detection
  sources: [detection_dir]
vibe-children: []
---

# Object Detection & Hyperspectral

Waste segmentation with hyperspectral input: a 10-rung ladder (H0 plumbing to H9 a real stream), first reproducing the published SpectralWaste results (H1, 2 of 12 configs so far), then mock sensors and sim to real.
Milestone: a valid hyperspectral test mIoU against the paper's 58.2. The loop has not started; the only state today is the July repro queue log.
