# Vibe Tracks HTTP API

The server is a thin lens over the Markdown files. Every read re-derives state
from disk; every write is a narrow, revision-fenced, atomic edit of one note.
The files remain the database — the API never holds state of its own.

All endpoints are JSON unless noted. All `POST` requests **must** send
`Content-Type: application/json`; other content types are rejected with `415`.
Requests whose `Host` header is not a loopback name (or the explicitly bound
host) get `403` — the standard DNS-rebinding guard for a localhost service.
Validation failures not listed per-endpoint surface as `422`; unexpected
internal failures as a JSON `500`.

## GET /api/project

Full project snapshot.

Query parameter `known=<revision>`: when the caller already holds the current
project revision, the server replies
`{"revision": "<same>", "unchanged": true, "now": "<server clock>"}` instead of
the full payload. Clients poll cheaply with this; `now` still rides along so a
panel can keep ageing what it already holds.

```jsonc
{
  "id": "pyblocks-demo",
  "title": "Pyblocks development",
  "description": "…",
  "descriptor": "/abs/path/Project.base",
  "root": "/abs/path",
  "source": "/abs/path/features",
  "statuses": ["backlog", "ready", "running", "waiting", "review", "frontier", "done", "archived"],
  "areaCatalog": [                       // descriptor `vibetracks.areas` ∪ areas found on items
    {"name": "writeback", "description": "Reverse-pass edits that mutate source"},
    {"name": "round-trip", "description": ""}
  ],
  "views": [ {"type": "vibetracks-graph", "name": "Graph"} ],
  "revision": "16-hex project revision",
  "now": "2026-08-25T18:20:41-07:00",    // the server's clock, for ageing `touched`
  "obsidianVault": null,                 // or the vault name for obsidian:// links
  "problems": [                          // notes that could not be parsed (skipped, never fatal)
    {"path": "features/Broken.md", "error": "Invalid YAML frontmatter: …"}
  ],
  "items": [
    {
      "id": "VT-002",
      "title": "Implement literal writer",
      "path": "features/VT-002 - Implement literal writer.md",  // project-relative
      "status": "review",
      "description": "one-line summary",
      "body": "markdown body without frontmatter",
      "areas": ["writeback", "round-trip"],
      "priority": "urgent",              // urgent | high | medium | low | none
      "archived": false,
      "dependencies": ["VT-001"],        // resolved feature ids
      "unresolved_dependencies": [],     // raw tokens that matched nothing
      "dependents": ["VT-004"],          // reverse edges, derived
      "review_packet": "reports/literal-writer-review.html",  // or null
      "preview": "assets/literal-writer-proof.svg",           // or null
      "evidence": ["evidence/literal-writer-tests.txt"],
      "runs": ["codex:literal-writer/attempt-003"],
      "media": [ {"path": "assets/….svg", "kind": "image", "label": "….svg"} ],
      "revision": "16-hex note revision",
      "updated": "2026-08-25T12:00:00-07:00",  // declared `vibe-updated`, else the file's mtime
      "touched": "2026-08-25T12:00:00.412-07:00",  // always the file's mtime, to the ms — a claim cannot forge it
      "obsidian_uri": null
    }
  ]
}
```

## GET /api/media?path=<project-relative>

Serves a file from inside the project root. Paths that resolve outside the
root are rejected with `400`. Every response carries a restrictive
`Content-Security-Policy` and `X-Content-Type-Options: nosniff` — SVG and
XHTML can carry scripts, so nothing served from a note may execute with the
panel's origin. HTML review packets are meant for the sandboxed iframe.

## GET /api/health

`{"ok": true, "descriptor": "/abs/path"}`

## POST /api/features/{id}/status

```json
{"status": "done", "expectedRevision": "<note revision the client last saw>"}
```

Atomically rewrites only the status property (`vibe-status` by default) in the
note's frontmatter. Responds `{"item": {…refreshed item…}}`.

- `409` — the note changed since `expectedRevision` was read. Reload and retry.
- `400` — unknown status, malformed body.
- `404` — unknown feature id.

## POST /api/features/{id}/dependencies

```json
{"dependsOn": ["VT-001", "Some title"], "expectedRevision": "…"}
```

Replaces the note's depends-on list. Each entry that resolves to a known
feature is written as a wikilink to that note's filename (`"[[VT-001 - …]]"`);
unresolved entries are written verbatim so intent is never silently dropped.
Entries that resolve to the feature itself are dropped (the client resends the
full list on every edit, so a stray hand-written self-edge must not block all
subsequent edits). Responds `{"item": {…}}`, with the same `409` fencing as
status; a non-list `dependsOn` is rejected with `422`.

This is the "shared control panel" write: a human can rewire the graph while a
dispatcher is running, and the dispatcher sees the change on its next read.

## POST /api/features/{id}/comment

```json
{"text": "Ship it, but rename the flag.", "expectedRevision": "…"}
```

Appends a feedback callout to the end of the note body:

```markdown
> [!quote] 👦 Feedback — 2026-08-25 14:22
> Ship it, but rename the flag.
```

Responds `{"item": {…}}`, `409`-fenced like the other writes. This is the
human→dispatcher channel: agents watch feature notes for new feedback callouts.

## Write-surface philosophy

The server exposes exactly three mutations — status, dependencies, comment —
because those are the panel gestures. Everything else (creating features,
attaching evidence, review packets, area memory) is done by writing Markdown
directly, by a human or an agent. See `AGENT.md` for the dispatcher protocol.
