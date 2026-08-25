# Vibe Tracks

Vibe Tracks renders a folder of ordinary Markdown feature conversations as three interchangeable views:

- **Graph** — causal dependencies and hidden-boundary cues.
- **Kanban** — workflow state over the same feature identities.
- **Focus** — reviews, frontier decisions, and work ready to dispatch.

The files are the backend. Closing the renderer leaves the complete project state readable and editable by humans, Obsidian, scripts, Claude, Codex, or another future dispatcher.

## Run the included project

```bash
cd /home/bam/vibetracks
python3 -m vibetracks examples/pyblocks/Project.base --open-browser
```

The server defaults to <http://127.0.0.1:8777>. It rereads the descriptor and Markdown notes on every snapshot. State changes from the UI atomically edit only `vibe-status` and require the revision the browser actually reviewed.

The standalone writer coordinates its own disk edits, but it is not yet connected to Obsidian's live editor buffer. Do not apply a standalone status change to a note that is actively open and unsaved in Obsidian; the future custom-view plugin should route that mutation through Obsidian's `processFrontMatter` API.

## `.base` or `.vibetrack`?

Use a real `.base` file when the project lives in an Obsidian vault. Vibe Tracks reads ordinary Base `filters` and `views`, while `vibetracks-graph`, `vibetracks-kanban`, and `vibetracks-focus` are custom view types a later Obsidian plugin can register. A plain table view remains a native fallback.

Use `.vibetrack` outside Obsidian. It accepts the same YAML shape and may add the `vibetracks:` host block. There is one parser and one feature-note schema, not two databases.

```yaml
filters:
  and:
    - note["vibe-track"] == "feature"
    - file.inFolder("features")

views:
  - type: vibetracks-graph
    name: Graph
  - type: vibetracks-kanban
    name: Kanban
  - type: vibetracks-focus
    name: Focus

vibetracks:
  title: My project
  vaultRoot: .
  source: features
  obsidianVault: My Vault
```

Feature notes use normal YAML and Markdown:

```markdown
---
vibe-track: feature
vibe-id: VT-042
vibe-status: review
vibe-areas: [backend, evaluator]
vibe-depends-on: ["[[VT-017 - Workspace index]]"]
vibe-review-packet: ../reports/VT-042.html
---

# Close the first round trip

Human-authored intent, agent summaries, decisions, and durable links live here.
```

`obsidianVault` enables standard `obsidian://open` links using each note's path relative to `vaultRoot`.

## Current implementation boundary

Shipped in V0:

- Base-compatible `.base` and `.vibetrack` loading;
- recursive Markdown discovery and frontmatter normalization;
- explicit dependency resolution with unresolved and hidden-boundary cues;
- area/search/archive filtering;
- Graph, Kanban, Focus, feature-conversation, media, evidence, and review-report views;
- polling-based file refresh;
- revision-fenced, atomic status edits;
- configurable Obsidian note links.

Not yet implemented: agent launching, transcript ingestion, background idea curation, automatic dependency inference, feedback delivery, file watching/SSE, drag/drop, note creation, or an Obsidian plugin wrapper.

## Verify

```bash
python3 -m unittest discover -s tests -v
python3 -m vibetracks examples/pyblocks/Project.base --inspect
```

The implementation gallery will live at [`docs/implementation-gallery.html`](docs/implementation-gallery.html).
