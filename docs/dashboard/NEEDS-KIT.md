# Building a "Needs you" proposal

Five proposals (N1 to N5) share one route, one data contract and one kit. Zach's ask: one click from a track (or from the home table's Needs-you column) should put him on a page where he can **understand each question well enough to answer it**, answer it, and **copy all his answers out** in one go. One proposal is inspired by Sauna AI's zen mode.

A proposal owns **only its own folder**: `clank/src/needs/n1/` … `n5/`. Do not edit the kit files beside it (`clank/src/needs/*.ts(x)`, `needs.css`), `Dashboard.tsx`, the backend or `vibetracks/dashboard/needs.py`. They are the frozen contract. If you need a change there, report it instead of making it.

## Run it

- **Lane (already running, Vite HMR):** `http://127.0.0.1:4390/?vtdash=Agent%20work.vtdash#vt?track=kinsim&needs=1`. Also `track=rig`, and no `track` for every track (`#vt?needs=1`).
- **The chooser:** bottom-right, `Needs you · N1 … N5`, stacked above the A · B · C switcher. It is remembered (`localStorage['vibetracks.dashboard.needsProposal']`). The needs page renders the same whichever of A · B · C is chosen.
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
| `answers` | the `AnswerStore` (below): Zach's drafts, persisted per track + item |
| `backend` | `ctx.backend` |
| `projection` | the dashboard projection when loaded (pass to `EvidenceLink` so videos and reports open through the media route); may be `null` |
| `route`, `navigate` | the shared hash route (`#vt?track=…&needs=1&…`). Add your own keys (an open item, a mode); they round-trip. Push for a deeper level so Back climbs one |
| `onBack()` | leave the page: steps Back when the dashboard opened it with `openNeeds`, else drops `needs` from the route. The shell already shows a quiet `← Back` above your page |

**Entry points** (for whoever wires the home table cell or a track page; not you): `openNeeds(navigate, route, trackId | null)` from `clank/src/needs`.

## The data: `vibetracks-needs/1`

Served by `GET /needs?track=<id>` (one doc) and `GET /needs` (`vibetracks-needs-all/1`: `{schema, generated_at, tracks: NeedsDoc[]}`). Written by `vibetracks/dashboard/needs.py`, which reads the loops' **live** files on every request (kinsim's worktree is found by its branch). Types: `clank/src/needs/types.ts`.

**Tracks today:** `kinsim` (57 items, live, answers by `jsonl_append`), `rig` (17 items, live, answers by `chat_paste`), and `grasping`, `detection`, `pyblocks`, which have no structured questions yet. Those return `items: []` with `source.note` saying where their questions live and `answer_channel` saying how an answer would get back. Show that note; never invent items for them.

**Per doc:** `track`, `track_title`, `generated_at`, `iteration {unit, n, phase, finished}`, `source {adapter, paths, commit, live, note}`, `answer_channel {kind, target, row_schema, read_back}`, `counts`, `items`.

`counts`: `open` (raw status open), `blocking_now`, `no_default` (waits for Zach forever), `waiting` (default pending, blocks nothing), `defaulting` (open, but its default is already in effect), `answered`, `defaulted`, `closed`, `total`.

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
| `default {text_md, applies {unit, after}, state}` | what happens if Zach is silent, and when. `applies.unit` `never` = it waits for him. `state` is **computed** (`pending`, `in_effect`, `none`); do not trust `status` alone, since loops leave items open after their default applied |
| `options[]` | the three implicit choices, each with the loop's own words: `accept_recommendation` (detail = recommendation), `use_default` (detail = default; labelled "Keep waiting (no default)" for `never` items), `other` (needs a note) |
| `blocks[] {id, kind, label}` | the rungs or packages it holds, with their titles |
| `blocking_now` | open, unanswered, default not in effect, and blocks something |
| `group` | `blocking`, `no_default`, `waiting`, `defaulting`, `answered`, `done`. `GROUP_LABEL` has the words |
| `evidence[] {label, kind, value, path, line, is_dir}` | paths named in the item's text that exist on disk, as absolute paths; URLs |
| `created {iteration, ts}`, `updated {ts, note}` | from `opened_wave` and the loop's `triage_changed` events |
| `status`, `raw_status` | `status` is effective: an answer row the integrator has not folded yet already reads `answered` |
| `answer` | `{choice, note, ts, by, channel, folded, action_md, quoted}` when the loop has one. `by: null` means the loop closed it without Zach's words; `quoted: false` means the note is the integrator's paraphrase |

Helpers: `openAsks(doc)` (blocking + no default + pending), `itemsInGroup(doc, group)`, `describeDefault(item)`.

**Live today (2026-10-04):** kinsim has 1 blocking (T47 → BT3, BT4, default after wave 5), 2 with no default (T12, T33), and 8 open items whose default is already in effect (T11, T15, T52–T57). Rig has 2 blocking (T2 → BN1, T14 → HW1, both no default), 2 more with no default (T15, T17), 2 pending (T13, T16) and 5 defaulting.

## The kit (`import { … } from '../kit'`)

| part | use |
|---|---|
| `useNeeds(backend, track)` | `{docs, doc, loading, error, reload}`. The shell already calls it and passes the result; call it yourself only for another track |
| `useAnswerStore()` / `props.answers` | `get(track, localId)` → `{choice, note, updated}` or null; `set(track, localId, {choice?, note?})` merges and saves; `clear(track, localId?)`. One `localStorage` entry per track + item (`vibetracks.needs.answer:<track>:<id>`), every access try/catch wrapped |
| `effectiveChoice(draft)`, `isComplete(draft)` | a click wins; a **note alone** answers as `other`; `other` needs a non-blank note. A thumbs-up maps to `accept_recommendation`, "let it default" to `use_default` |
| `<CopyOut docs answers label? />` | the one copy action. It builds the export, tries the clipboard, and **always** ends with the text in a pre-selected textarea (the clipboard is often refused on Clank origins). It disables itself when nothing is answered, and names items left out |
| `exportAnswers(docs, answers.get)`, `exportTrack(doc, …)` | the export text, if you need it without the button |
| `<EvidenceLink backend doc item index projection? />` | one evidence entry: opens through the projection's media route when the path is a known media file, else through `/needs/evidence` (which serves only paths the backend itself extracted from that item); a directory or unservable file is shown as its path with a copy button, never as a dead link |
| `evidenceHref(...)`, `evidenceUrl(...)` | the href alone |
| `<PlaceholderList {...props} label />` | the placeholder every folder starts with. Delete it from your folder once your page renders |

**The export format** (what Copy answers produces; one block per track, unanswered items omitted):

````markdown
# Answers · Kinematic Sim · 2026-10-04 19:19 PDT
<!-- vibetracks-needs/1 · track=kinsim · source=triage.json@eff3ea86 · channel=jsonl_append -> /home/bam/.local/share/bam_curriculum/triage_answers.jsonl -->

## T47 · Should this robot be expected to pick at 1.0 m/s and above?
- **Answer:** Go with the recommendation (accept_recommendation)
- **Note:** Keep the motor limits; also log the skip reason per object.

```jsonl
{"ts":"2026-10-04T19:19:06-07:00","triage_id":"T47","choice":"accept_recommendation","note":"Keep the motor limits; also log the skip reason per object."}
```
````

The `jsonl` fence appears only when the track's `answer_channel.row_schema` is `bam-triage-answer/1` (kinsim). Those rows are exactly `{ts, triage_id, choice, note}`, so the integrator can append them verbatim to `triage_answers.jsonl`. Rig and the others get the same markdown without the fence, for a chat paste. Every heading carries `local_id` and the full title, so the integrator never has to ask which item.

## CSS

Use `calm.css` (`vt-page`, `vt-h1`…, `vt-muted`, `vt-faint`, `vt-small`, `vt-chip-btn`, the `--vt-*` tokens; see `VARIANT-KIT.md`). Root your own rules in `.vt-dash .vt-needs-n<k>` inside `@layer base`, in a CSS file in your folder. The page sits inside `.vt-scroll`; the chooser and the A · B · C switcher cover the bottom-right ~90 px, so leave bottom padding.

## Rules (from Zach's memory)

- **Calm is the container; the research is the content.** The question, its why, the recommendation and the default carry the page. No decoration that competes.
- **View settings go on the settings page, never in a toolbar** (`VARIANT-KIT.md`, "Settings"). A density or "show defaulted" option is a settings item; report it rather than adding a header toggle.
- **No fake controls.** Every button does something real. Answering is local drafts plus Copy answers; there is no "Send" (the backend is read-only, and the loops read answers from their own channels).
- **Truthful rendering.** Show the loop's words verbatim; fold long text, never truncate it silently. A computed state (default in effect) is labelled as computed.
