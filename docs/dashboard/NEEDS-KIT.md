# The "Needs you" page and its kit

**Current product (2026-10-05):** the dashboard's one layout is A · Drill-down pages (`VARIANTS.md`), and its Needs page opens on **N6 · Lane + context**, the judges' splice of N1 (Zen mode) and N2 (Inbox + reading pane), for anyone who has not picked another. N1 to N5 stay selectable from the one pill in the review bar, which remembers the choice. Zach's ask: one click from a track (or from the home table's Needs-you column) should put him on a page where he can **understand each question well enough to answer it**, answer it, and **copy all his answers out** in one go.

> **Archived 2026-10-04 (the build round):** N1 to N5 were built as competing proposals, each owning only its own folder (`clank/src/needs/n1/` … `n5/`) against a frozen kit, and N6 was spliced from the judges' two favourites. The kit files (`clank/src/needs/*.ts(x)`, `needs.css`), `Dashboard.tsx`, the backend and `vibetracks/dashboard/needs.py` are no longer frozen; they are shared code that other lanes edit, so check `git status` before you touch them.

## Run it

- **Lane (already running, Vite HMR):** `http://127.0.0.1:4390/?vtdash=Agent%20work.vtdash#vt?track=kinsim&needs=1`. Also `track=rig`, and no `track` for every track (`#vt?needs=1`).
- **The chooser:** one pill (a "Needs you" label, then `N6 · Lane + context ▾`) that opens the list of N1 … N6 upward. N6 is the default (`DEFAULT_PROPOSAL`, NeedsShell.tsx); a choice is remembered (`localStorage['vibetracks.dashboard.needsProposal']`). It is the only pill: the A · B · C layout switcher was retired on 2026-10-05. **Where it sits (the review-bar contract):** `Dashboard.tsx` renders `<div id="vt-review-bar" class="vt-review-bar">` as a sibling *below* the scroll area, shown only on the needs page, and the shell portals the pill into it (`createPortal`); the shell's root then carries `data-chooser="docked"`. In the bar the pill covers nothing, by construction. Only when the bar is absent does the pill float in the bottom-right corner (`data-chooser="floating"`), and then the page keeps its 80 px bottom clearance and `useFitToScroller` its full reserve.
- **The data:** `curl -s 'http://127.0.0.1:4390/api/plugins/vibetracks/needs?track=kinsim' | python3 -m json.tool`, or `cd ~/vibetracks-dashboard && python3 -m vibetracks.dashboard.needs kinsim`.
- **Typecheck:** `/home/bam/clank-workbench/node_modules/.bin/tsc -p /home/bam/vibetracks-dashboard/clank`.
- **Backend tests:** `cd ~/vibetracks-dashboard && python3 -m unittest tests/test_dashboard_needs.py tests/test_dashboard_needs_evidence_bound.py`. The evidence link's URL rules: `node --experimental-strip-types --test clank/src/needs/evidence.check.mjs`; on the real page: `node tests/browser/needs_evidence_bound.mjs`.
- **After editing `needs.py`** restart only this plugin's backend (the mount is imported once): `curl -s -X POST http://127.0.0.1:4390/api/plugin-backends/vibetracks/restart`.

## The contract

`clank/src/needs/n<k>/index.tsx` exports `export const NAME = '…'` (the chooser shows `N<k> · NAME`) and `export default function (props: NeedsProposalProps)`. Import the kit from `'../kit'` (not `'../'`, which would form an import cycle through the shell).

| prop | what |
|---|---|
| `track` | the routed track id, or `null` for every track |
| `docs` | `NeedsDoc[]`: `[doc]` for one track, every track otherwise. Items arrive **sorted**: blocking now, no default, default pending (by when it fires), defaulting without you, answered, done |
| `doc` | the one track's doc when a track is routed, else `null` |
| `loading`, `error`, `reload()` | fetch state; `reload()` re-reads the loops' live files |
| `answers` | the `AnswerStore` (below): Zach's drafts, persisted per track + item. Render `<StaleDraftNotice answers doc item />` in every card's answer area |
| `includeDefaulting` | the settings page's "Needs you · Include questions whose default is already in effect" (off by default). A lane that queues only what wants Zach adds the `defaulting` group when it is on. **Never a page button or a route flag**: it is a view option, and view options live only on the settings page |
| `openSettings()` | opens the dashboard's settings page over this route (closing it lands back here). Use it through `<IncludeDefaultingPointer openSettings />`, the plain-text pointer beside "N more are defaulting without you" |
| `backend` | `ctx.backend` |
| `projection` | the dashboard projection when loaded; may be `null`. **Never** used for an evidence link: `EvidenceLink` takes no projection, and nothing on the Needs page opens `/media` (see `EvidenceLink` below) |
| `route`, `navigate` | the shared hash route (`#vt?track=…&needs=1&…`). Add your own keys (an open item, a mode); they round-trip. Push for a deeper level so Back climbs one |
| `onBack()` | leave the page: steps Back when the dashboard opened it with `openNeeds`, else drops `needs` from the route. The shell already shows a quiet `← Back` above your page |

**Entry points** (for whoever wires the home table cell or a track page; not you): `openNeeds(navigate, route, trackId | null)` from `clank/src/needs`.

## The data: `vibetracks-needs/1`

Served by `GET /needs?track=<id>` (one doc) and `GET /needs` (`vibetracks-needs-all/1`: `{schema, generated_at, tracks: NeedsDoc[]}`). Written by `vibetracks/dashboard/needs.py`, which reads the loops' **live** files on every request (kinsim's worktree is found by its branch). Types: `clank/src/needs/types.ts`.

**Tracks:** the work-track registry's (`vibetracks.dashboard.registry`, workspace `$VIBETRACKS_WORKSPACE`), in its row order, and `track_title` is the registry's `vibe-title`, so a rename shows here too.

- `kinsim` (live triage, answers by `jsonl_append`) and `rig` (live triage, answers by `chat_paste`).
- `grasping`: one `approval` item per model id from `curriculum.py` CELLS with status `needs` whose reason names a download approval, parsed by the grasping adapter's own `needs_cells()`. `local_id` is the model id and `title` the model's own title; `ask` is the model id plus the cells' own approval phrases, joined by ` / ` (`f"{model_id} · {' / '.join(phrases)}"`, needs.py `build_grasping`). On the lane (2026-10-05): `local_id` `M5.ggcnn`, `title` `GG-CNN (planar, Cornell)`, `ask` `M5.ggcnn · download approval`. **No question is framed:** CELLS carry a reason, never a question, and a made-up "Approve downloading …?" would read as the loop's words. `context_md` is the model's title, licence and notes and the cells it holds by their own reason, verbatim. The options are the dashboard's: `Approve the download`, `Keep waiting (no default)`, `Something else (write it)`. No default is recorded, so they group `no_default`. `blocks` are `cell`s, not rungs: the adapter's frontier rule counts wave-1 cells and gates only, so an approval never blocks now. Answers go by `chat_paste`, naming model ids verbatim.
- `detection`: the vault plan note's `## Needs you` items, parsed by the detection adapter's own `parse_needs_section()`, every field verbatim (`context_md` is the whole item, nested bullets and wikilinks included). `blocks` are the rungs the item says it blocks. A stated default has `applies.unit` `unstated` (the note never says when it fires), state `pending`; an item with no `*Default if silent:*` has unit `never` ("no default recorded").
- `pyblocks` and any registry track needs.py has no source for: `items: []`, `source.note` saying where the questions live, and **every count null** ("not reported", never 0).
- A track /needs does not know (a rig deployment such as `can16`) answers `404 {"error": "unknown track 'can16'"}`. The shell (`NeedsShell.tsx`) then looks the id up in the projection (a loop or a loop's deployment) and hands the proposal `unreportedDoc(...)`: the projection's title, every count null, `source.note` "This deployment has no needs-you source.", `answer_channel.kind` `none`. So a proposal never sees that error or the raw id; an id the projection does not know either keeps the error.

**Per doc:** `track`, `track_title`, `generated_at`, `iteration {unit, n, phase, finished}`, `source {adapter, paths, commit, live, note}`, `answer_channel {kind, target, row_schema, read_back}`, `counts`, `items`.

`counts`: `open` (raw status open), `blocking_now`, **`wants_you`** (groups blocking + no_default + waiting: open items whose default is NOT already in effect), `no_default` (waits for Zach forever), `waiting` (default pending, blocks nothing), `defaulting` (open, but its default is already in effect), `answered`, `defaulted`, `closed`, `total`. Every value is null on a doc with no structured source.

**The frozen counts contract.** needs.py is the ONE source of every Needs-you number. The projection's `needs_you_count` is `{open: counts.wants_you, blocking: counts.blocking_now}` for the same track (build.py fills it from this doc, and its `needs_you` list from these items), so a page header must show exactly `B blocking · M open` with `B = counts.blocking_now`, `M = counts.wants_you`, and "not reported" when they are null. `tests/test_dashboard_needs_counts.py` pins it.

**Read the header numbers through `headerCounts(doc)`** (or `headerSummary(docs)` for every track), never by adding count fields: it returns `{blocking, open, parts: {blocking, noDefault, waiting}, defaulting}` or `null` for a not-reported doc. `parts` is `open` split by item group, so each item is counted once and the three sum to `open`. **`counts.no_default` is not one of them:** it also counts blocking items that have no default (rig T2, T14), and "2 blocking now · 4 no default · 2 default pending" summed to 8 against rig's 6. The shared header line is `M open: B blocking now · N waiting with no default · P default pending` (then `· D more defaulting without you`). A null doc reads `notReportedText(doc)`: "Not reported: " plus its `source.note`, verbatim.

**Per item** (every field the source has, verbatim):

| field | meaning |
|---|---|
| `id`, `local_id` | `kinsim:T47`, `T47`. Use `local_id` in anything Zach or the integrator reads |
| `title`, `ask` | the one-line question; `ask` falls back to `title` |
| `context_md` | the loop's full question text, verbatim: the why, measured numbers, file refs. **Fold it by default** |
| `context_lead_md` | the first sentence that says why: a verbatim slice, never a summary. The short "why it matters" line |
| `provenance_md` | a leading "Filed at wave-N close from …" sentence, split off verbatim |
| `context_base_md`, `updates[]` | rig items grow by appended `UPDATE <header>: …` paragraphs (rig T2 is ~3.9 KB, 5 updates). `updates` holds them oldest first; the newest matters most |
| `context_summary` | only when a loop emits one; always `null` today. The dashboard never invents one |
| `recommendation_md` | the loop's recommendation, verbatim |
| `default {text_md, applies {unit, after}, state}` | what happens if Zach is silent, and when. `applies.unit` `never` = it waits for him (`text_md` is `""`); `unstated` = there is a default but the source never says when it fires (`after` null; say "when: not stated", never "after unstated null"). `state` is **computed** (`pending`, `in_effect`, `none`); do not trust `status` alone, since loops leave items open after their default applied |
| `options[]` | the choices, in order: any leading ones (grasping's `approve`, "Approve the download"), then the implicit ones: `accept_recommendation` (detail = recommendation; **absent** when the source records no recommendation, as for grasping and detection), `use_default` (detail = default; labelled "Keep waiting (no default)" for `never` items), `other` (needs a note). Every option has `source: "dashboard"`: its `label` is the dashboard's words, and `detail_md` is the only loop text (or null). Never assume a key is there: a key or ↵ that picks `accept_recommendation` on an item without it files an answer to a choice the loop never gave |
| `blocks[] {id, kind, label}` | what it holds, with titles: rungs or packages (triage, detection), `cell`s (grasping, label "env title · tier N"). `blocking_now`, not a non-empty `blocks`, says whether it blocks now |
| `blocking_now` | open, unanswered, default not in effect, and blocks something |
| `group` | `blocking`, `no_default`, `waiting`, `defaulting`, `answered`, `done`. `GROUP_LABEL` has the words |
| `evidence[] {label, kind, value, path, target, line, is_dir, eid}` | paths named in the item's text that exist on disk, as absolute paths; URLs. `target` is the canonical file the path resolved to when the doc was built (`realpath`). `eid` is the entry's stable id: a hash of the item id and the entry as written (kind, label, value), never its list index, so reordering keeps it |
| `evidence_rev` (on the doc) | a hash over every item's evidence entries, in order, each with its `target`. It changes when evidence is added, removed, reordered or rewritten, or when a listed path now resolves to a different file. Evidence URLs carry it |
| `created {iteration, ts}`, `updated {ts, note}` | from `opened_wave` and the loop's `triage_changed` events |
| `status`, `raw_status` | `status` is effective: an answer row the integrator has not folded yet already reads `answered` |
| `answer` | `{choice, note, ts, by, channel, folded, action_md, quoted}` when the loop has one. `by: null` means the loop closed it without Zach's words; `quoted: false` means the note is the integrator's paraphrase |

Helpers: `openAsks(doc)` (blocking + no default + pending), `itemsInGroup(doc, group)`, `describeDefault(item)`, `appliesAfter(item)` ("after wave 5", or `null` when the source does not say when), `hasDefault(item)`, and the words `NO_DEFAULT_RECORDED` ("no default recorded", unit `never`) and `WHEN_NOT_STATED` ("when: not stated", unit `unstated`). Never print `applies.unit`/`applies.after` raw: that produced "after unstated null".

**Live on the lane (2026-10-05 05:38 PDT, `GET /needs`):** kinsim has 1 blocking (T47 → BT3, BT4, default after wave 5), 2 with no default (T12, T33), and 8 open items whose default is already in effect (T11, T15, T52–T57). Rig has 2 blocking (T2 → BN1, T14 → HW1, both no default), 2 more with no default (T15, T17), 2 pending (T13, T16) and 5 defaulting. Grasping has 7 with no default (M5.ggcnn, M5.grconvnet, M5.contact_graspnet, M5.rngnet, M5.cgn_gc6d, M5.hggd, M5.vgn_giga_edge) and 0 blocking. Detection has 1 blocking (plan-1) and 2 pending (plan-2, plan-3). Pyblocks is not reported (every count null).

## The kit (`import { … } from '../kit'`)

| part | use |
|---|---|
| `useNeeds(backend, track)` | `{docs, doc, loading, error, reload}`. The shell already calls it and passes the result; call it yourself only for another track |
| `useAnswerStore(docs)` / `props.answers` | `get(track, localId)` → the **live** draft `{choice, note, updated, fingerprint, status}` or null; `stale(track, localId)` → `{draft, reason, status, reconfirmable}` or null; `stored(track, localId)` → the saved draft, live or stale; `set(track, localId, {choice?, note?})` merges, binds and saves; `reconfirm(track, localId)`; `clear(track, localId?)`. One `localStorage` entry per track + item (`vibetracks.needs.answer:<track>:<id>`), every access try/catch wrapped. The rules are pure functions in `answerRules.ts`, shared with the exporter and checked by `answers.check.mjs` |
| **Drafts are bound to what Zach reviewed** | every draft stores `fingerprint` = `reviewedFingerprint(item)`: the title, ask and full `context_md` (UPDATEs included), every option's key, label and `detail_md`, the default's text and when it applies, and the status. Computed fields (group, `default.state`, `blocking_now`, timestamps) are left out, so a wave closing does not invalidate drafts. A draft is **stale** when the fingerprint no longer matches (`changed`), when it has none (`unbound`: saved before binding), or when the item is no longer `open` (`settled`: answered, closed, superseded, defaulted). A stale draft never comes out of `get()`, is never exported, and is named under "Not in the copy"; `<StaleDraftNotice>` quotes it whole with **Reconfirm** (re-binds it to the question as it reads now; offered only while the item is open and still offers the drafted option) and **Discard**. A `set()` on an item with a stale draft starts a new draft (the stale words are not carried in unreconfirmed). A settled item takes no draft at all, so show it without answer controls |
| **Offered choices** | a choice the item does not offer never comes out of `get()` and is never recorded by `set()`; the note is kept. `exportTrack` applies the same rules to whatever lookup it is given |
| `effectiveChoice(draft)`, `isComplete(draft)`, `isNoteOnly(draft)` | a click wins; a **note alone** answers as `other` **only where the item offers `other`**; `other` needs a non-blank note. A note alone on an item without `other` is `isNoteOnly`: no option. A thumbs-up maps to `accept_recommendation`, "let it default" to `use_default` |
| `<StaleDraftNotice answers doc item />` | the calm notice for a stale draft (renders nothing otherwise): the reason, the draft quoted whole (`white-space: pre-wrap`), Reconfirm and Discard |
| `<CopyOut docs answers label? />` | the one copy action. It builds the export from `answers.stored`, tries the clipboard, and **always** ends with the text in a pre-selected textarea (the clipboard is often refused on Clank origins). It disables itself when nothing is answered, and lists every draft it leaves out under "Not in the copy:" with why (stale, "Something else" without a note, a note with no option on a loop that needs one) |
| `exportAnswers(docs, answers.stored)`, `exportTrack(doc, …)` | the export text, if you need it without the button |
| **Zach's note is never altered** | store and export it exactly as typed: never `trim()` it for storage or display (`trim()` only tests for blankness), never fold its lines. Show it with `white-space: pre-wrap` |
| `<EvidenceLink backend doc item index />` | one evidence entry. **Every file opens through `/needs/evidence`**, bound to this document's `evidence_rev` and the entry's `eid`, which serves only paths the backend itself extracted from that item; a URL entry opens as itself; a directory or unservable file is shown as its path with a copy button, never as a dead link. **Never `/media`, and no projection** (Codex audit 2026-10-05 round 3, finding 1: a path also listed in `projection.media` used to open as `/media/<id>?rev=<projection rev>`, so an old document beside a newer projection opened the new file and skipped the 409 below). The link checks before it opens (`checkEvidence`, one byte: `Range: bytes=0-0`): when the backend answers 409 it shows "This changed since you opened it: reload" beside the link (the reload button re-reads /needs through the mounted `useNeeds`); it never retries with a newer revision on its own. Another refusal (403, 404) shows "Not opened: <the backend's reason>" |
| `evidenceHref(backend, doc, item, index)`, `evidenceUrl(...)`, `evidencePath(doc, item, index)` | pure, in `evidence.ts` (re-exported by `api.ts` and the kit): the href alone; the backend path `/needs/evidence?track&item&eid&rev` (null for a URL, a directory, an unserved suffix, or an entry or doc without `eid` / `evidence_rev`) |
| **`/needs/evidence` is bound to what Zach reviewed** | the URL carries `track`, `item`, `eid` and `rev` (the doc's `evidence_rev`), never an index. The backend rebuilds the doc: a different `evidence_rev` answers **409** `{"error": "the document changed; reload"}` and serves nothing; otherwise it looks the entry up by `eid` and opens only its recorded `target`, through `vibetracks.safe_open.open_no_symlinks` (a symlink at ANY component of the path refuses with 403, not only the last). It serves what `/media` serves, so a Needs page never needs `/media`: video, images, HTML, Markdown and text with the same content types, `Range` answered with 206 / 416 (a video seeks), and no size cap. (`/media/<id>?rev=` opens its files the same way, bound to the projection's `media_rev` as this route is to `evidence_rev`: PROJECTION.md, Media.) `requestNeedsReload()` (api.ts) is the reload |
| `headerCounts(doc)`, `headerSummary(docs)`, `notReportedText(doc)` | the header's two numbers and their disjoint parts, from needs.py; `null` / `notReported` for a track that reports none (see the counts contract above) |
| `useFitToScroller(rootRef, reserve?, min?)` | fits your page to the rest of `.vt-scroll` so your panes scroll inside it, less `reserve` (default `CHOOSER_RESERVE`, 56 px) while the pill floats, and only `DOCKED_RESERVE` (12 px) once it is docked in the review bar. Give the root the class `vt-needs-framed` too; the shell then drops its own bottom padding. N2, N3, N4 and N5 use it. Use it for any bar that must stay in view (see CSS) |
| `hoverTime(iso)` | a stamp for a `title` attribute: `formatLocal(iso, {year: true})` ("2026-10-03 21:25 PDT"), or undefined. Never put a raw ISO stamp in a title or in text |
| `questionText(item)`, `questionMd(item)`, `askExtendsTitle(item)` | the question for a row (plain text) or a heading (markdown): the whole ask when the title is only its bold lead (detection: title `Data.`, ask `**Data.** The Seagate … run udisksctl …`), else the title. Rows clamp it with a visible ellipsis and carry it whole in the hover title |
| `<PlaceholderList {...props} label />` | the placeholder every folder starts with. Delete it from your folder once your page renders |

**The export format** (what Copy answers produces; one block per track, unanswered items omitted). The examples in this section are the real exporter's output (`exportTrack`, exportAnswers.ts) for the lane's live kinsim T47 and rig T2 as read on 2026-10-05, with the note shown typed as the answer; `answers.check.mjs` regenerates each one from the same inputs and compares it to this file. For a track whose loop reads rows (`row_schema` `bam-triage-answer/1`: kinsim):

````markdown
# Answers · Kinematic Sim · 2026-10-05 05:42 PDT
<!-- vibetracks-needs/1 · track=kinsim · source=triage.json@eff3ea86 · channel=jsonl_append -> /home/bam/.local/share/bam_curriculum/triage_answers.jsonl -->

## T47 · Should this robot be expected to pick at 1.0 m/s and above?
- **Answer:** Go with the recommendation (accept_recommendation)
  > Keep the motor settings (your brief) and redefine BT4's gate as 'every object scored, 0 exceptions, every skip logged'; BT3's 1.0 m/s end follows the same rule, while its 0.5 m/s end keeps the ratchet. K1 already meets 'every object scored, 0 exceptions' (1000/1000 scored, exit 0).
- **Note:**
  ```text
  Keep the motor limits; also log the skip reason per object.
  ```

```jsonl
{"ts":"2026-10-05T05:42:00-07:00","triage_id":"T47","choice":"accept_recommendation","note":"Keep the motor limits; also log the skip reason per object."}
```
````

The `jsonl` fence appears only when the track's `answer_channel.row_schema` is `bam-triage-answer/1` (kinsim). Those rows are exactly `{ts, triage_id, choice, note}`, so the integrator can append them verbatim to `triage_answers.jsonl`; the loop resolves the choice against its own file. Every heading carries `local_id` and the full title, so the integrator never has to ask which item.

Every other track (rig's `chat_paste`, detection's `note_paste`, …) gets no fence. **Every track, kinsim included, quotes the chosen option's own words under the answer line**, every line of the loop's text, because the label alone ("Go with the recommendation") does not say what was approved, a chat-paste integrator has nothing else to read, and the recommendation may have been rewritten by an UPDATE since. The quote is markdown only; the jsonl rows are unchanged:

````markdown
## T2 · Flash diff on controller 192551cb (plan D2)
- **Answer:** Go with the recommendation (accept_recommendation)
  > Approve the diff the first bench window shows you; until then RAM-only config with readback.
- **Note:**
  ```text
  ok, but log the readback
  ```
````

"Something else" quotes nothing (the note is the answer). An option the loop recorded no words for reads `> (the loop recorded no words for this option)`.

**The note** is a fenced block (info `text`) inside the `- **Note:**` item, its fence one backtick longer than the longest backtick run in the note (at least three), every line indented by the item's two spaces. CommonMark strips that indent again, so the block's literal is exactly the note plus one final newline: multiline text, pasted code fences and leading or trailing whitespace all survive, and nothing in the note can end the block or restyle the markdown around it. In the jsonl row, `note` is the raw string.

**A note with no option** (an item that offers no "Something else") is never exported as `other`. On a markdown-only channel (`chat_paste`, `note_paste`) it goes out as `- **Answer:** no option chosen (note only)` plus its note; on a channel whose rows need a choice (`bam-triage-answer/1`: needs.py reads only rows whose choice is one of the three) it is left out and named: "note only, this loop needs an option".

**`exact …:` lines.** Markdown cannot give every text back as typed: CommonMark turns a CR or CRLF into LF and NUL into U+FFFD, a lone surrogate cannot be written as UTF-8, a quote drops its text's leading and trailing whitespace, and a heading or answer line reads some characters as markup. When that would happen, the copy adds one line that carries the text losslessly: the label, then the text as a JSON string in a code span (no Markdown reader unescapes inside one), so `JSON.parse` of the span gives back exactly what was typed or written (`exactLine`, answerRules.ts). Ordinary answers carry none. These are every such line the exporter (`exportAnswers.ts`) can write, two spaces in, in the order they appear:

| Line | Where it sits | When it is written |
|---|---|---|
| `exact track title:` | after the header's `<!-- … -->` comment and a blank line | the track's title would not read back from the `# Answers · … ·` heading as written (rule below) |
| `exact id:` | right under the item's `## <id> · <title>` heading | the item's `local_id` would not read back from the heading as written |
| `exact title:` | under the heading, after `exact id:` when both are there | the item's title would not read back from the heading as written |
| `exact option label:` | after the `- **Answer:**` line and a blank line, before the option's quote | the chosen option's label would not read back from the answer line as written |
| `exact option words:` | after the option's quote and a blank line | the option's words hold a CR, NUL or lone surrogate, or have leading or trailing whitespace. Every channel, kinsim included |
| `exact:` | right after the note's fenced block | the note holds a CR, NUL or lone surrogate (the fence keeps edge whitespace already). Only where no JSONL row carries the note: the markdown-only channels (`chat_paste`, `note_paste`). On `bam-triage-answer/1` the row's `note` is the raw string, so there is no `exact:` line |

Each blank line before a twin keeps it out of the paragraph or quote above it (lazy continuation would otherwise make it read as the loop's words or as part of the answer).

**When a line's text "would not read back as written"** (`lineTextIsLossy`, exportAnswers.ts; for the track title, id, title and option label). It is lossy when it:
- has leading or trailing whitespace (a heading drops it, and a line's ends are trimmed);
- holds a backslash, a backtick, `[`, `]`, `<`, `>` or `~` (escapes, code spans, links, raw HTML and autolinks, strikethrough);
- holds an `&` that starts an entity reference (`&amp;`, `&#38;`, `&#x26;`). Any other `&` is literal: "Sim to Real & Trajectory Tracking" gets no twin;
- holds a `*` or `_` run that can open or close emphasis under CommonMark's flanking rules, with the text's ends read as whitespace. An intraword `_` never can: "M5.contact_graspnet" and "slow_step_045deg" get no twin, while `*a*`, `_why_` and `__init__` do;
- ends in a `#` run that starts the text or follows whitespace (a heading's closing sequence).

A text that holds a line ending, CR, NUL or lone surrogate never gets a twin: it is written on its line itself as a JSON string in a code span (`inlineExact`), so it cannot break the line. `answers.check.mjs` sweeps every string up to four characters over the hazard alphabet through the exporter and markdown-it and finds no lossy text without its twin; `tests/browser/export_twins_live.mjs` does the same for every live title and id on the lane and expects no redundant twin either.

The real exporter's output for a `chat_paste` track whose title holds `<…>`, an item whose id and title have emphasis runs, and an option label in `*…*` (track, id, title and label each get their twin; the `&` gets none):

````markdown
# Answers · Rig <can16> & bench · 2026-10-05 12:40 PDT
<!-- vibetracks-needs/1 · track=rig · source=chat · channel=chat_paste -->

  exact track title: `"Rig <can16> & bench"`

## __init__ · Keep *slow_step* as the gate?
  exact id: `"__init__"`
  exact title: `"Keep *slow_step* as the gate?"`
- **Answer:** Keep *waiting* (use_default)

  exact option label: `"Keep *waiting*"`
  > Stay on slow_step until the bench is back.
- **Note:**
  ```text
  fine
  ```
````

The real exporter's output for rig T2 (a `chat_paste` track) with its recommendation's words replaced by `"  Approve the diff.\r\nThen read it back.  "` (two leading spaces, a CRLF, two trailing spaces), and a note that contains a CRLF:

````markdown
## T2 · Flash diff on controller 192551cb (plan D2)
- **Answer:** Go with the recommendation (accept_recommendation)
  >   Approve the diff.
  > Then read it back.  

  exact option words: `"  Approve the diff.\r\nThen read it back.  "`
- **Note:**
  ```text
  ok, but log
  the readback
  ```
  exact: `"ok, but log\r\nthe readback"`
````

A reader that needs the exact text takes the code span after any `exact …:` label and `JSON.parse`s it. The heading, the answer line, the quote and the fenced block stay the readable form. A heading's title or an answer label that holds a line break or a character Markdown cannot carry is written inline the same way, as a JSON string in a code span (`inlineExact`), so it cannot break its line.

## CSS

Use `calm.css` (`vt-page`, `vt-h1`…, `vt-muted`, `vt-faint`, `vt-small`, `vt-chip-btn`, the `--vt-*` tokens; see `VARIANT-KIT.md`). Root your own rules in `.vt-dash .vt-needs-n<k>` inside `@layer base`, in a CSS file in your folder. The page sits inside `.vt-scroll`. The N pill lives in the review bar below it and covers nothing; if the bar is absent it floats over the bottom-right ~90 px, so a page that is not framed keeps bottom padding under `.vt-needs[data-chooser='floating']` (the shell's 80 px does this for you).

**No `position: sticky` bar over scrolling content.** A sticky bar covers whatever scrolls under it: measured with `elementFromPoint` at 1440x900, N3's review bar sat over kinsim T54's card head and N4's stack over option 1 at max scroll. A bar that must stay in view goes above a pane that scrolls on its own: frame the page with `useFitToScroller` (N3, N4 do; N2 and N5 fit themselves the same way).

## Rules (from Zach's memory)

- **Calm is the container; the research is the content.** The question, its why, the recommendation and the default carry the page. No decoration that competes.
- **View settings go on the settings page, never in a toolbar** (`VARIANT-KIT.md`, "Settings"). A density or "show defaulted" option is a settings item; report it rather than adding a header toggle.
- **No fake controls.** Every button does something real. Answering is local drafts plus Copy answers; there is no "Send" (the backend is read-only, and the loops read answers from their own channels).
- **Truthful rendering.** Show the loop's words verbatim; fold long text, never truncate it silently. A computed state (default in effect) is labelled as computed.
