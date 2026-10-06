// What "Copy answers" puts on the clipboard: one block per track, readable by Zach, quotable by the integrator, and
// machine-appendable where the loop reads rows. Format agreed with the data mapper (docs/dashboard/NEEDS-KIT.md):
//
//   # Answers · Kinematic Sim · 2026-10-04 19:20 PDT
//   <!-- vibetracks-needs/1 · track=kinsim · source=triage.json@eff3ea86 · channel=jsonl_append -> /…/triage_answers.jsonl -->
//
//   ## T47 · Should this robot be expected to pick at 1.0 m/s and above?
//   - **Answer:** Go with the recommendation (accept_recommendation)
//     > Keep the motor settings (your brief) and redefine BT4's gate as …   (the loop's recommendation, verbatim)
//   - **Note:**
//     ```text
//     Keep the motor limits; also log the skip reason per object.
//     ```
//
//   ```jsonl
//   {"ts":"2026-10-04T19:20:11-07:00","triage_id":"T47","choice":"accept_recommendation","note":"…"}
//   ```
//
// Every answer quotes the chosen option's own words under its answer line, on every channel (kinsim's jsonl rows,
// rig's chat paste, detection's note paste, ...).
// WHY every channel: the label alone ("Go with the recommendation") does not say WHAT was approved; a chat-paste
// integrator has nothing else to read, and Zach reading a kinsim block back had only the option key; the
// recommendation it refers to may also have been rewritten by an UPDATE since. The quote is markdown only: rows for
// bam-triage-answer/1 stay exactly {ts, triage_id, choice, note}, because that loop resolves the choice against its
// own file. When the loop recorded no words for the option, the quote says so instead of staying silent.
//
// WHY an `exact title:` (`exact id:`, `exact option label:`, `exact track title:`) twin under a line whose text Markdown
// would change (edge spaces, markup that a parser would actually read as markup): see lineTextTwinLines() below; the
// line itself stays exactly as written.
// WHY every heading carries local_id AND the full title: the integrator must never have to ask which item an answer
// is for (the pyblocks precedent). WHY the jsonl fence only for bam-triage-answer/1 tracks: those rows are appended
// verbatim to triage_answers.jsonl and must validate (exactly {ts, triage_id, choice, note}); a chat-paste loop
// (rig) quotes the markdown instead. Unanswered items are omitted, never exported as blanks.
//
// WHY the note is a fenced block in markdown and the raw string in jsonl (Codex audit 2026-10-04, finding 7): the
// note is Zach's own words and the copy must carry them exactly. The old `note.trim().replace(/\n+/g, ' ')` folded a
// multiline answer with a ```python snippet into one line and dropped its edge whitespace; see noteBlockLines().
// WHY stale drafts are named and never exported (finding 1): a draft bound to an older version of the question, or to
// an item the loop has since settled, is not what Zach approved for the question as it reads now.
// WHY a note with no option is never exported as `other` where the item does not offer `other`: the effective choice
// must be one the item offers. A markdown-only channel carries it as a note with no option chosen; a channel whose
// rows need a choice (bam-triage-answer/1: needs.py reads only rows whose choice is one of the three) cannot, so it is
// named under "Not in the copy".
//
// Import from './answerRules' (pure), never './answers' (React): answers.check.mjs runs this file under plain node.

import {
  draftState,
  effectiveChoice,
  exactLine,
  inlineExact,
  isComplete,
  isNoteOnly,
  markdownIsLossy,
  markdownLines,
  noteBlockLines,
  staleText,
  type AnswerDraft,
} from './answerRules'
import type { Choice, NeedsDoc, NeedsItem } from './types'

export const ANSWER_ROW_SCHEMA = 'bam-triage-answer/1'

// ------------------------------------------------------------------------------------------- inline twins

/** CommonMark's Unicode whitespace (Zs plus tab, LF, FF, CR), and markdown-it's \v. */
const MD_WHITESPACE = /[\t\n\v\f\r    -   　]/
/** CommonMark 0.31's Unicode punctuation: general categories P and S (ASCII punctuation is all P or S). */
const MD_PUNCTUATION = /[\p{P}\p{S}]/u
/** An entity or numeric character reference, the only `&` a CommonMark parser decodes (spec §2.5). */
const ENTITY_REFERENCE = /&(#\d+|#x[0-9a-f]+|[a-z][a-z0-9]*);/i

/**
 * True when some `*` or `_` delimiter run in `text` can open or close emphasis under CommonMark's flanking rules
 * (spec §6.2), with the text's ends read as whitespace (on every line the exporter writes, each loop text sits between
 * spaces or at a line end). A run that can do neither is literal in every parse; one that can do either is flagged
 * even when nothing pairs with it (conservative: pairing also depends on the neighbours on the line).
 */
export function emphasisCanApply(text: string): boolean {
  const chars = Array.from(text)
  for (let start = 0; start < chars.length; ) {
    const marker = chars[start]
    if (marker !== '*' && marker !== '_') {
      start++
      continue
    }
    let end = start
    while (end < chars.length && chars[end] === marker) end++
    const before = start > 0 ? chars[start - 1] : ' '
    const after = end < chars.length ? chars[end] : ' '
    const beforeSpace = MD_WHITESPACE.test(before)
    const afterSpace = MD_WHITESPACE.test(after)
    const beforePunct = MD_PUNCTUATION.test(before)
    const afterPunct = MD_PUNCTUATION.test(after)
    const left = !afterSpace && (!afterPunct || beforeSpace || beforePunct)
    const right = !beforeSpace && (!beforePunct || afterSpace || afterPunct)
    // `*` opens when left-flanking and closes when right-flanking; `_` also refuses to open or close inside a word.
    const canOpen = marker === '*' ? left : left && (!right || beforePunct)
    const canClose = marker === '*' ? right : right && (!left || afterPunct)
    if (canOpen || canClose) return true
    start = end
  }
  return false
}

/**
 * True when loop text set on one Markdown line (a heading, the answer line) may not parse back as the same characters:
 * edge whitespace (a heading drops it, and a line's ends are trimmed), a backslash, backtick, bracket, `<`, `>` or `~`
 * (escapes, code, links, raw HTML and autolinks, strikethrough), an `&` that starts an entity reference, a `*` or `_`
 * run that can open or close emphasis, or a heading's closing `#` run.
 *
 * WHY precise for `&`, `*` and `_` (verifier, 2026-10-05, item f): the old test flagged any `&` or `_`, so
 * "Sim to Real & Trajectory Tracking" and ids like "M5.contact_graspnet" carried a twin on every copy although every
 * CommonMark parser reads them back unchanged; a twin on every line teaches the reader to skip twins. An `&` is read
 * only as the start of a reference, and an intraword `_` never opens or closes emphasis. The remaining characters stay
 * flagged on sight: a twin too many costs one line, a twin too few loses what Zach reviewed.
 * WHY here and not answerRules.inlineIsLossy (the older, flag-on-sight test, still exported there): the exporter is
 * the one writer of these lines, and answers.check.mjs measures this rule against markdown-it.
 */
export function lineTextIsLossy(text: string): boolean {
  return (
    text !== text.trim() ||
    /[\\`[\]<>~]/.test(text) ||
    ENTITY_REFERENCE.test(text) ||
    emphasisCanApply(text) ||
    /(^|\s)#+$/.test(text)
  )
}

/**
 * The `exact <label>: "<JSON>"` twin for loop text on a Markdown line, or [] when the line already carries it exactly.
 * WHY the same rule as notes and option words (verifier, 2026-10-05): an item title with edge spaces lost them in the
 * parsed heading, exactly the loss the `exact:` twin already repairs for a note and an option's words. inlineExact()
 * already shows a line ending or a CR/NUL as JSON on the line itself, so those need no twin.
 */
export function lineTextTwinLines(text: string, label: string): string[] {
  if (/[\r\n]/.test(text) || markdownIsLossy(text)) return []
  return lineTextIsLossy(text) ? [exactLine(text, label)] : []
}

const CHOICE_LABEL: Record<Choice, string> = {
  accept_recommendation: 'Go with the recommendation',
  approve: 'Approve',
  use_default: 'Let the default apply',
  other: 'Something else',
}

/** ISO-8601 with the local offset (`2026-10-04T19:20:11-07:00`), as bam-triage-answer/1 requires. */
export function isoWithOffset(date: Date): string {
  const pad = (n: number) => String(Math.abs(n)).padStart(2, '0')
  const offset = -date.getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `${sign}${pad(Math.trunc(offset / 60))}:${pad(offset % 60)}`
  )
}

function headingTime(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  let zone = ''
  try {
    zone = new Intl.DateTimeFormat('en-US', { timeZoneName: 'short' }).formatToParts(date).find((part) => part.type === 'timeZoneName')?.value ?? ''
  } catch {
    zone = ''
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}${zone ? ` ${zone}` : ''}`
}

/** The option's own label from the doc when it has one ("Keep waiting (no default)"), else the generic one. */
export function choiceLabel(item: NeedsItem | null, choice: Choice): string {
  const option = item?.options.find((candidate) => candidate.key === choice)
  return choice === 'other' ? CHOICE_LABEL.other : (option?.label ?? CHOICE_LABEL[choice])
}

export interface ExportResult {
  markdown: string
  /** Items exported, as `<track>:<local_id>`. */
  exported: string[]
  /** Drafts left out, with why: stale (the question changed, or the loop settled it), `other` with a blank note, or
   * a note with no option on a channel whose rows need one. */
  skipped: { id: string; reason: string }[]
}

/** Pass the store's `stored` (every saved draft, live or stale) so stale ones are named; `get` also works. */
type DraftLookup = (track: string, localId: string) => AnswerDraft | null

/** The reason Copy names for a note with no option on a channel whose rows need one. */
export const NOTE_ONLY_NEEDS_OPTION = 'note only, this loop needs an option'

/** The chosen option's own words as markdown quote lines under the answer bullet, or [] for "Something else" (the note
 * is the answer). Every line of the loop's text is kept; blank lines stay as a bare `>` so paragraphs survive. */
export function optionQuoteLines(item: NeedsItem, choice: Choice): string[] {
  if (choice === 'other') return []
  const option = item.options.find((candidate) => candidate.key === choice)
  // WHY no trim() (Codex round 2 finding 3): these are the loop's own words; edge spaces and blank lines are part of
  // what was approved, and the quote keeps each line's characters after its `  > ` prefix.
  const text = option?.detail_md ?? ''
  if (text === '') return ['  > (the loop recorded no words for this option)']
  const lines = markdownLines(text).map((line) => (line === '' ? '  >' : `  > ${line}`))
  // A quote cannot hold a CR, CRLF or NUL as such, and a parser drops the text's edge whitespace (whitespace-only words
  // render as nothing): then the exact twin follows. WHY the blank line before it: without one, the next line would
  // continue the quote's paragraph (lazy continuation) and read as the loop's words.
  if (markdownIsLossy(text) || text !== text.trim()) lines.push('', exactLine(text, 'exact option words'))
  return lines
}

/** A value inside the header's HTML comment: as is, or as a JSON string when it holds a line ending or `-->` (either
 * could end the comment and spill the rest into the copy as markup). Never trimmed. */
function commentField(value: string): string {
  return /[\r\n]|-->/.test(value) || markdownIsLossy(value) ? JSON.stringify(value).replace(/>/g, '\\u003e') : value
}

/** One track's block, or null when nothing in it is answered. */
export function exportTrack(doc: NeedsDoc, draftOf: DraftLookup, now: Date = new Date()): ExportResult | null {
  const exported: string[] = []
  const skipped: { id: string; reason: string }[] = []
  const sections: string[] = []
  const rows: string[] = []
  const ts = isoWithOffset(now)
  const rowsCarryChoice = doc.answer_channel.row_schema === ANSWER_ROW_SCHEMA
  for (const item of doc.items) {
    // The store applies the same rules; checked again here because any lookup may be passed.
    const state = draftState(draftOf(doc.track, item.local_id), item)
    if (state.stale) {
      const has = state.stale.draft.choice || state.stale.draft.note.trim()
      if (has) skipped.push({ id: item.id, reason: `${staleText(state.stale)}; ${state.stale.reconfirmable ? 'reconfirm or discard it' : 'discard it'}` })
      continue
    }
    const draft = state.live
    if (!draft) continue
    const choice = effectiveChoice(draft)
    const noteOnly = isNoteOnly(draft)
    if (!choice && !noteOnly) continue
    if (choice && !isComplete(draft)) {
      skipped.push({ id: item.id, reason: '"Something else" needs a note' })
      continue
    }
    if (noteOnly && rowsCarryChoice) {
      skipped.push({ id: item.id, reason: NOTE_ONLY_NEEDS_OPTION })
      continue
    }
    // The note exactly as typed (never trimmed); a whitespace-only note is still shown, since it is what was saved.
    const note = draft.note
    const answer = choice ? `${inlineExact(choiceLabel(item, choice))} (${choice})` : 'no option chosen (note only)'
    // WHY inlineExact on the loop's id, title and label: each must stay on its one Markdown line; a title holding a line
    // ending would otherwise end the heading and spill the rest into the copy as markup.
    // WHY the twins under the heading and the answer line: a parser drops a heading's edge spaces and reads `*`, `_`,
    // `<`... as markup, so the parsed copy would not say exactly what was reviewed; the twin gives the text back.
    const lines = [
      `## ${inlineExact(item.local_id)} · ${inlineExact(item.title)}`,
      ...lineTextTwinLines(item.local_id, 'exact id'),
      ...lineTextTwinLines(item.title, 'exact title'),
      `- **Answer:** ${answer}`,
    ]
    if (choice) {
      const labelTwin = lineTextTwinLines(choiceLabel(item, choice), 'exact option label')
      // The blank line ends the answer line's paragraph; without it the twin would continue it (lazy continuation).
      if (labelTwin.length) lines.push('', ...labelTwin)
      lines.push(...optionQuoteLines(item, choice))
    }
    if (note) lines.push(...noteBlockLines(note))
    // WHY the exact twin only where no JSONL row carries the note (Codex round 2 finding 3): a bam-triage-answer/1 row
    // holds the raw string already; a chat or note paste has nothing else that can give back a CR, CRLF or NUL.
    const rowCarriesNote = rowsCarryChoice && choice !== null
    if (note && !rowCarriesNote && markdownIsLossy(note)) lines.push(exactLine(note))
    sections.push(lines.join('\n'))
    exported.push(item.id)
    // Key order matters for a reader comparing rows by eye; JSON.stringify keeps insertion order. `note` is the raw
    // string. Only reached with a choice: a note-only draft on a row channel was skipped above.
    if (rowsCarryChoice && choice) rows.push(JSON.stringify({ ts, triage_id: item.local_id, choice, note }))
  }
  if (!sections.length) return skipped.length ? { markdown: '', exported, skipped } : null
  const channel = doc.answer_channel
  const source = doc.source.paths[0] ? `${doc.source.paths[0].split('/').pop()}${doc.source.commit ? `@${doc.source.commit}` : ''}` : doc.source.adapter
  const header = [
    `# Answers · ${inlineExact(doc.track_title)} · ${headingTime(now)}`,
    `<!-- vibetracks-needs/1 · track=${commentField(doc.track)} · source=${commentField(source)} · channel=${commentField(channel.kind)}${channel.target ? ` -> ${commentField(channel.target)}` : ''} -->`,
  ]
  // WHY after the comment and a blank line: a reader with raw HTML off parses the comment line as a paragraph, and a
  // twin right under it would continue that paragraph instead of standing on its own.
  const trackTwin = lineTextTwinLines(doc.track_title, 'exact track title')
  if (trackTwin.length) header.push('', ...trackTwin)
  let markdown = `${header.join('\n')}\n\n${sections.join('\n\n')}`
  if (rowsCarryChoice) markdown += `\n\n\`\`\`jsonl\n${rows.join('\n')}\n\`\`\``
  return { markdown, exported, skipped }
}

/** Every track's block, joined; tracks with nothing answered are left out. */
export function exportAnswers(docs: NeedsDoc[], draftOf: DraftLookup, now: Date = new Date()): ExportResult {
  const parts = docs.map((doc) => exportTrack(doc, draftOf, now)).filter((part): part is ExportResult => part !== null)
  return {
    markdown: parts.map((part) => part.markdown).filter(Boolean).join('\n\n'),
    exported: parts.flatMap((part) => part.exported),
    skipped: parts.flatMap((part) => part.skipped),
  }
}
