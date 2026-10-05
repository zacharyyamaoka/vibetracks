# Building a "Needs you" proposal

Five proposals (N1 to N5) share one route, one data contract and one kit. Zach's ask: one click from a track (or from the home table's Needs-you column) should put him on a page where he can **understand each question well enough to answer it**, answer it, and **copy all his answers out** in one go. One proposal is inspired by Sauna AI's zen mode.

A proposal owns **only its own folder**: `clank/src/needs/n1/` … `n5/`. Do not edit the kit files beside it (`clank/src/needs/*.ts(x)`, `needs.css`), `Dashboard.tsx`, the backend or `vibetracks/dashboard/needs.py`. They are the frozen contract. If you need a change there, report it instead of making it.

## Run it

- **Lane (already running, Vite HMR):** `http://127.0.0.1:4390/?vtdash=Agent%20work.vtdash#vt?track=kinsim&needs=1`. Also `track=rig`, and no `track` for every track (`#vt?needs=1`).
- **The chooser:** one pill, `Needs you · N6 · Lane + context ▾`, that opens the list of N1 … N6 upward. It is remembered (`localStorage['vibetracks.dashboard.needsProposal']`). The needs page renders the same whichever of A · B · C is chosen. **Where it sits (the review-bar contract):** `Dashboard.tsx` renders `<div id="vt-review-bar" class="vt-review-bar">` as a sibling *below* the scroll area, and the shell portals the pill into it (`createPortal`), left of the A · B · C pill (`order: -1`); the shell's root then carries `data-chooser="docked"`. In the bar the pill covers nothing, by construction. Only when the bar is absent does the pill float in the bottom-right corner (`data-chooser="floating"`), and then the page keeps its 80 px bottom clearance and `useFitToScroller` its full reserve.
- **The data:** `curl -s 'http://127.0.0.1:4390/api/plugins/vibetracks/needs?track=kinsim' | python3 -m json.tool`, or `cd ~/vibetracks-dashboard && python3 -m vibetracks.dashboard.needs kinsim`.
- **Typecheck:** `/home/bam/clank-workbench/node_modules/.bin/tsc -p /home/bam/vibetracks-dashboard/clank`.
- **Backend tests:** `cd ~/vibetracks-dashboard && python3 -m unittest tests/test_dashboard_needs.py`.
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
| `projection` | the dashboard projection when loaded (pass to `EvidenceLink` so videos and reports open through the media route); may be `null` |
| `route`, `navigate` | the shared hash route (`#vt?track=…&needs=1&…`). Add your own keys (an open item, a mode); they round-trip. Push for a deeper level so Back climbs one |
| `onBack()` | leave the page: steps Back when the dashboard opened it with `openNeeds`, else drops `needs` from the route. The shell already shows a quiet `← Back` above your page |

**Entry points** (for whoever wires the home table cell or a track page; not you): `openNeeds(navigate, route, trackId | null)` from `clank/src/needs`.

## The data: `vibetracks-needs/1`

Served by `GET /needs?track=<id>` (one doc) and `GET /needs` (`vibetracks-needs-all/1`: `{schema, generated_at, tracks: NeedsDoc[]}`). Written by `vibetracks/dashboard/needs.py`, which reads the loops' **live** files on every request (kinsim's worktree is found by its branch). Types: `clank/src/needs/types.ts`.

**Tracks:** the work-track registry's (`vibetracks.dashboard.registry`, workspace `$VIBETRACKS_WORKSPACE`), in its row order, and `track_title` is the registry's `vibe-title`, so a rename shows here too.

- `kinsim` (live triage, answers by `jsonl_append`) and `rig` (live triage, answers by `chat_paste`).
- `grasping`: one `approval` item per model id from `curriculum.py` CELLS with status `needs` whose reason names a download approval, parsed by the grasping adapter's own `needs_cells()`. `local_id` is the model id (`M5.ggcnn`); `ask` is "Approve downloading <model id>?" (the only words not in the file: CELLS carry reasons, not questions); `context_md` is the model's title, licence and notes and the cells it holds by their own reason, verbatim. No default is recorded, so they group `no_default`. `blocks` are `cell`s, not rungs: the adapter's frontier rule counts wave-1 cells and gates only, so an approval never blocks now. Answers go by `chat_paste`, naming model ids verbatim.
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

**Live today (2026-10-04):** kinsim has 1 blocking (T47 → BT3, BT4, default after wave 5), 2 with no default (T12, T33), and 8 open items whose default is already in effect (T11, T15, T52–T57). Rig has 2 blocking (T2 → BN1, T14 → HW1, both no default), 2 more with no default (T15, T17), 2 pending (T13, T16) and 5 defaulting.

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
| `<EvidenceLink backend doc item index projection? />` | one evidence entry: opens through the projection's media route when the path is a known media file, else through `/needs/evidence` (which serves only paths the backend itself extracted from that item); a directory or unservable file is shown as its path with a copy button, never as a dead link. A `/needs/evidence` link checks before it opens: when the backend answers 409 it shows "This changed since you opened it: reload" beside the link (the reload button re-reads /needs through the mounted `useNeeds`); it never retries with a newer revision on its own. Another refusal (403, 404) shows "Not opened: <the backend's reason>" |
| `evidenceHref(...)`, `evidenceUrl(...)`, `evidencePath(doc, item, index)` | the href alone; the backend path `/needs/evidence?track&item&eid&rev` (null for a URL, a directory, or an entry without `eid`) |
| **`/needs/evidence` is bound to what Zach reviewed** | the URL carries `track`, `item`, `eid` and `rev` (the doc's `evidence_rev`), never an index. The backend rebuilds the doc: a different `evidence_rev` answers **409** `{"error": "the document changed; reload"}` and serves nothing; otherwise it looks the entry up by `eid` and opens only its recorded `target`, through `vibetracks.safe_open.open_no_symlinks` (a symlink at ANY component of the path refuses with 403, not only the last; the `/media/<id>` route opens its files the same way). `requestNeedsReload()` (api.ts) is the reload |
| `headerCounts(doc)`, `headerSummary(docs)`, `notReportedText(doc)` | the header's two numbers and their disjoint parts, from needs.py; `null` / `notReported` for a track that reports none (see the counts contract above) |
| `useFitToScroller(rootRef, reserve?, min?)` | fits your page to the rest of `.vt-scroll` so your panes scroll inside it, less `reserve` (default `CHOOSER_RESERVE`, 56 px) while the pill floats, and only `DOCKED_RESERVE` (12 px) once it is docked in the review bar. Give the root the class `vt-needs-framed` too; the shell then drops its own bottom padding. N2, N3, N4 and N5 use it. Use it for any bar that must stay in view (see CSS) |
| `hoverTime(iso)` | a stamp for a `title` attribute: `formatLocal(iso, {year: true})` ("2026-10-03 21:25 PDT"), or undefined. Never put a raw ISO stamp in a title or in text |
| `questionText(item)`, `questionMd(item)`, `askExtendsTitle(item)` | the question for a row (plain text) or a heading (markdown): the whole ask when the title is only its bold lead (detection: title `Data.`, ask `**Data.** The Seagate … run udisksctl …`), else the title. Rows clamp it with a visible ellipsis and carry it whole in the hover title |
| `<PlaceholderList {...props} label />` | the placeholder every folder starts with. Delete it from your folder once your page renders |

**The export format** (what Copy answers produces; one block per track, unanswered items omitted). For a track whose loop reads rows (`row_schema` `bam-triage-answer/1`: kinsim):

````markdown
# Answers · Kinematic Sim · 2026-10-04 19:19 PDT
<!-- vibetracks-needs/1 · track=kinsim · source=triage.json@eff3ea86 · channel=jsonl_append -> /home/bam/.local/share/bam_curriculum/triage_answers.jsonl -->

## T47 · Should this robot be expected to pick at 1.0 m/s and above?
- **Answer:** Go with the recommendation (accept_recommendation)
  > Keep the motor settings (your brief) and redefine BT4's gate as 'every object scored, 0 exceptions, every skip logged'; …
- **Note:**
  ```text
  Keep the motor limits; also log the skip reason per object.
  ```

```jsonl
{"ts":"2026-10-04T19:19:06-07:00","triage_id":"T47","choice":"accept_recommendation","note":"Keep the motor limits; also log the skip reason per object."}
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
  …
  ```
````

"Something else" quotes nothing (the note is the answer). An option the loop recorded no words for reads `> (the loop recorded no words for this option)`.

**The note** is a fenced block (info `text`) inside the `- **Note:**` item, its fence one backtick longer than the longest backtick run in the note (at least three), every line indented by the item's two spaces. CommonMark strips that indent again, so the block's literal is exactly the note plus one final newline: multiline text, pasted code fences and leading or trailing whitespace all survive, and nothing in the note can end the block or restyle the markdown around it. In the jsonl row, `note` is the raw string.

**A note with no option** (an item that offers no "Something else") is never exported as `other`. On a markdown-only channel (`chat_paste`, `note_paste`) it goes out as `- **Answer:** no option chosen (note only)` plus its note; on a channel whose rows need a choice (`bam-triage-answer/1`: needs.py reads only rows whose choice is one of the three) it is left out and named: "note only, this loop needs an option".

## CSS

Use `calm.css` (`vt-page`, `vt-h1`…, `vt-muted`, `vt-faint`, `vt-small`, `vt-chip-btn`, the `--vt-*` tokens; see `VARIANT-KIT.md`). Root your own rules in `.vt-dash .vt-needs-n<k>` inside `@layer base`, in a CSS file in your folder. The page sits inside `.vt-scroll`. The pills live in the review bar below it and cover nothing; if the bar is absent the N pill floats over the bottom-right ~90 px, so a page that is not framed keeps bottom padding under `.vt-needs[data-chooser='floating']` (the shell's 80 px does this for you).

**No `position: sticky` bar over scrolling content.** A sticky bar covers whatever scrolls under it: measured with `elementFromPoint` at 1440x900, N3's review bar sat over kinsim T54's card head and N4's stack over option 1 at max scroll. A bar that must stay in view goes above a pane that scrolls on its own: frame the page with `useFitToScroller` (N3, N4 do; N2 and N5 fit themselves the same way).

## Rules (from Zach's memory)

- **Calm is the container; the research is the content.** The question, its why, the recommendation and the default carry the page. No decoration that competes.
- **View settings go on the settings page, never in a toolbar** (`VARIANT-KIT.md`, "Settings"). A density or "show defaulted" option is a settings item; report it rather than adding a header toggle.
- **No fake controls.** Every button does something real. Answering is local drafts plus Copy answers; there is no "Send" (the backend is read-only, and the loops read answers from their own channels).
- **Truthful rendering.** Show the loop's words verbatim; fold long text, never truncate it silently. A computed state (default in effect) is labelled as computed.
