# Vibe Tracks

File-first feature tracking for humans and AI agents working in parallel.

Ordinary Markdown notes are the database — one note per feature, frontmatter
for trackable state, body for the durable conversation. Vibe Tracks renders
that folder as three interchangeable lenses:

- **Graph** — what unlocks what (dependency topology).
- **Kanban** — where is everything (state sweep).
- **Focus** — what needs the human now (reviews, frontier decisions, ready work).

Closing the renderer loses nothing: the complete project state stays readable
and editable by humans, Obsidian, scripts, Claude, Codex, or any future
dispatcher. The panel is the shared control surface where a human and a
dispatch agent coordinate: the agent lays out features and dependencies, the
human rewires edges, flips statuses, and drops feedback — all through the same
files.

## Quick start

```bash
git clone https://github.com/zacharyyamaoka/vibetracks.git
cd vibetracks
bash agent/install.sh          # CLI + /vibetracks skill for Claude Code & Codex
```

```bash
vibetracks serve examples/pyblocks/Project.base   # try the included example
```

```bash
cd ~/your/repo && vibetracks init && vibetracks serve   # track your own repo
```

Or, with zero installation: `python3 -m vibetracks …` from this checkout.

## Working with an agent

Type `/vibetracks` in Claude Code or Codex. The agent installs itself as the
project's **dispatcher**: it finds (or scaffolds) the nearest track, serves the
panel, hands you the URL, and from then on turns whatever context you paste
into feature notes with honest dependencies — executing ready work, finishing
each piece into `review` with a media-rich HTML review packet, and watching the
files for your feedback. The full protocol is [`vibetracks/AGENT.md`](vibetracks/AGENT.md)
(printed by `vibetracks agent`).

Concepts stay separate by design: the **feature** is the stable identity;
worker **attempts**, **review packets/evidence**, **human feedback**, and the
current projected **status** all hang off the feature note. Agents are
temporary; the files are not.

## CLI

```text
vibetracks serve [descriptor] [--port N] [--host H]   # browser panel (default command)
vibetracks init [path] [--title T] [--base|--vibetrack]
vibetracks new "Title" [--area A]… [--depends-on X]… [--status S] [--description D] [--priority P] [--body M]
vibetracks status <id> <status>
vibetracks comment <id> "text" [--author L]
vibetracks inspect [descriptor] [--json]
vibetracks agent
```

Descriptor discovery: current folder → ancestors (stopping at the repo
boundary) → one level down. The default port walks forward when busy so
parallel sessions coexist.

## `.base` or `.vibetrack`?

One schema, two host-facing extensions. Inside an Obsidian vault use a real
`.base` file — Vibe Tracks reads ordinary Base `filters`/`views`, and
`vibetracks-graph|kanban|focus` are custom view types a future Obsidian
plugin can register, with a native table view as fallback. Outside a vault,
`.vibetrack` accepts the same YAML plus the `vibetracks:` host block. One
parser, one feature-note schema, never two databases.

```yaml
filters:
  and:
    - 'note["vibe-track"] == "feature"'
    - 'file.inFolder("features")'

vibetracks:
  title: My project
  source: features
  idPrefix: VT
  statuses: [backlog, ready, running, waiting, review, frontier, done, archived]
  areas:                # project memory: the shared tagging vocabulary
    backend: Server, model, and storage work
  obsidianVault: My Vault   # enables obsidian:// note links
```

Feature notes are plain Markdown ([full anatomy](vibetracks/AGENT.md)):

```markdown
---
vibe-track: feature
vibe-id: VT-042
vibe-status: review
vibe-areas: [backend]
vibe-depends-on: ["[[VT-017 - Workspace index]]"]
vibe-review-packet: ../reports/VT-042-review.html
---

# Close the first round trip

Human intent, agent summaries, decisions, and feedback callouts live here.
```

## Safety model

- **Files are the source of truth**; the server re-derives every response from
  disk and holds no state.
- **Three narrow writes** (status, dependencies, feedback comment), each
  revision-fenced: the client sends the note revision it reviewed, the server
  rechecks it immediately before an atomic replace, and stale writes get HTTP
  409 instead of silently clobbering newer work. Only the intended span
  changes — untouched frontmatter and body keep their exact formatting.
  API details: [`docs/api.md`](docs/api.md).
- **Boundary:** disk writes cannot see a live editor's unsaved buffer. Don't
  mutate a note that is open and dirty in Obsidian; a future embedded Base
  view should write through Obsidian's `processFrontMatter`.
- Media serving is confined to the project root; embedded HTML review packets
  render in a sandboxed iframe under a restrictive CSP with scripts disabled.

## Verify

```bash
python3 -m unittest discover -s tests -v
```

```bash
python3 -m vibetracks inspect examples/pyblocks/Project.base
```

## Design explorations

- [Track-layout prototypes](docs/track-layout-prototypes-2026-08-25.html) —
  five browser-verified ways to make a dependency DAG read as parallel work
  tracks. The provisional splice is derived, borderless corridors at rest plus
  selected-lineage focus; this is design evidence, not a production UI change.

## Status

V0.2. Implemented: descriptor loading, recursive note discovery, dependency
resolution, all three views + feature rail + detail panel, area catalog
memory, review-packet embedding, polling with cheap unchanged checks, fenced
writes, scaffolding, the dispatcher CLI verbs, and the `/vibetracks` agent
skill. Not yet: file watching/SSE, drag-and-drop, automatic dependency
inference, transcript ingestion, or the Obsidian plugin wrapper.
