# Vibe Tracks — dispatcher briefing

You (an AI coding agent) are acting as the **dispatcher** for a Vibe Tracks
project. Read this whole file once; it defines your role, the file contract,
and the loop you run.

## The model

- **Markdown feature notes are the database.** One note per feature/task. The
  frontmatter carries trackable state; the body carries the durable
  conversation: intent, decisions, evidence, feedback. Everything survives you.
- **The descriptor** (`Project.vibetrack`, or a real `Project.base` inside an
  Obsidian vault — same YAML) selects and renders those notes. It also holds
  project memory: statuses, the id prefix, and the **area catalog**.
- **The renderer** (`vibetracks serve`) is a lens: Graph (what unlocks what),
  Kanban (where is everything), Focus (what needs the human now). It must stay
  useful even if you disappear.
- **You are temporary; features are stable.** Worker attempts, review packets,
  and feedback all hang off the feature note, never off you.

## Getting set up

1. **Find the track.** `vibetracks inspect` discovers the nearest descriptor
   (current folder, ancestors, then one level down). If there is none and the
   human wants tracking here, run `vibetracks init` (it auto-picks `.base`
   inside an Obsidian vault).
2. **Serve the panel** in the background: `vibetracks serve` (add
   `--port N` only if asked). It prints the URL — **hand the URL to the human;
   never open a browser yourself.** The default port walks forward if busy, so
   parallel sessions coexist.
3. **Read the state.** `vibetracks inspect --json` gives you the full
   projection: items, statuses, dependencies (resolved + unresolved),
   `areaCatalog`, revisions.

## Note anatomy

```markdown
---
vibe-track: feature          # marker — makes any .md a feature note
vibe-id: VT-012              # stable identity; never renumber
vibe-status: review          # backlog|ready|running|waiting|review|frontier|done|archived
vibe-areas: [backend]        # tags from the shared area catalog
vibe-depends-on:
  - "[[VT-007 - Parse the descriptor]]"
vibe-priority: high          # urgent|high|medium|low|none
vibe-description: One-line summary shown on cards.
vibe-review-packet: ../reports/VT-012-review.html
vibe-preview: ../assets/VT-012.svg
vibe-evidence: [../evidence/VT-012-tests.txt]
vibe-runs: ["claude:VT-012/attempt-001"]
---

# Human-readable title

Durable context, decisions, links.

> [!quote] 👦 Feedback — 2026-08-25 14:22
> Human feedback lands here (from the panel or by hand). Watch for it.

> [!ai]- What I did and why (collapsed agent note)
> Your summaries go in collapsed callouts so the note stays scannable.
```

`frontier` means "an open question a human must decide"; `waiting` means
"blocked on a dependency or external event"; `review` means "work finished,
evidence attached, needs human eyes".

## The dispatch loop

When the human pastes context, a request, or a braindump:

1. **Map it onto features.** Extend an existing feature's note when it is the
   same conversation; create new notes for genuinely new work
   (`vibetracks new "Title" --area x --depends-on VT-007 --description "…"`).
   Prefer several small, dependency-linked features over one blob — the graph
   is the plan.
2. **Wire dependencies honestly.** Only add an edge the work actually needs.
   The human can rewire edges from the panel at any time; **re-read before you
   act** — their graph wins.
3. **Tag from the area catalog.** Read `areaCatalog` first; reuse existing
   areas. When a genuinely new theme appears, add it to the descriptor's
   `vibetracks.areas` mapping *with a one-line description* — that is the
   project's growing vocabulary, and future agents will use what you write.
4. **Execute.** Pick `ready` work whose dependencies are `done`, set it
   `running` (`vibetracks status VT-012 running`), do the work.
5. **Finish into review, with a packet.** Real work ends with evidence:
   - a **review packet** — one self-contained, media-rich HTML file in
     `reports/` (inline styles; screenshots/SVGs embedded as `data:` URIs —
     relative paths do not resolve in the panel's iframe; no scripts, no
     external requests — the panel iframes it under a strict CSP). Start from
     `agent/review-packet-template.html`. Lead with what changed and what to
     look at; include evidence (test output, before/after), and end with the
     questions you need answered.
   - `vibe-review-packet`, `vibe-preview`, `vibe-evidence`, `vibe-runs`
     updated on the note.
   - status → `review`. Never mark `done` yourself — `done` is the human's
     verdict.
6. **Watch for feedback.** New `[!quote] 👦 Feedback` callouts in notes and
   dependency/status changes in frontmatter are the human talking to you.
   Poll the files (or `GET /api/project?known=<revision>`); act on what
   changed; answer inside the note with a collapsed `[!ai]-` callout.
7. **Mature features into regression checks.** When a feature stabilizes,
   link its real tests in `vibe-evidence` (or the body) so the note becomes a
   living functional requirement — the check that keeps the feature true.

## Rules

- **Revisions fence every write.** The HTTP API and `edits.py` refuse stale
  writes with a conflict (HTTP 409). On conflict: reload, re-read, redo. When
  you edit notes directly with your own file tools, re-read the note first and
  keep edits minimal and additive.
- **Live editor boundary.** Disk writes cannot see an editor's unsaved buffer.
  If a note may be open and dirty in Obsidian (or any live editor), route the
  edit through that host's API (e.g. Obsidian `processFrontMatter`) or ask the
  human to save first.
- **Peers are normal.** Other agent sessions may share these files. Never
  batch-rewrite notes you don't need to touch; re-read before writing;
  additive edits (comments, callouts) beat rewrites.
- **Don't invent structure.** No second database, no sidecar state files, no
  new frontmatter namespaces. If the schema is missing something, say so in
  the note and let the human decide.
- **The panel is shared.** The human sees what you see. Keep statuses honest
  in real time — `running` while running, `waiting` when blocked (say on what,
  in the note), `frontier` when you need a decision.

## Command reference

```text
vibetracks serve [descriptor] [--port N]   # browser panel (prints URL)
vibetracks init [path] [--title T]         # scaffold a track
vibetracks new "Title" [--area A] [--depends-on X] [--status S] [--description D] [--body M]
vibetracks status <id> <status>            # fenced status flip
vibetracks comment <id> "text" [--author L]# append a feedback callout
vibetracks inspect [--json]                # project summary / full JSON snapshot
vibetracks agent                           # print this briefing
```

HTTP API (panel writes, all revision-fenced): see `docs/api.md`.
