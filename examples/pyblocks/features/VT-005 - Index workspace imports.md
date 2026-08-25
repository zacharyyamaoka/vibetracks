---
vibe-track: feature
vibe-id: VT-005
vibe-status: running
vibe-priority: high
vibe-areas: [workspace, resolution]
vibe-description: Build rebuildable import and symbol evidence without projecting the entire repository into BlockView.
vibe-runs: [codex:workspace-index/active]
---

# Index workspace imports

The workspace snapshot records modules, imports, aliases, definitions, and revisions. A selected Python file still produces its own BlockView.
