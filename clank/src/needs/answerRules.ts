// The rules every draft answer obeys, as pure functions (no React, no storage), so the answer store, the exporter and
// the node:test checks (answers.check.mjs) all run the SAME code. answers.ts keeps the store; exportAnswers.ts the text.
//
// WHY a draft is bound to what Zach reviewed (Codex audit 2026-10-04, finding 1): a draft is a decision about one
// version of a question. An old "Go with the recommendation" survived the recommendation changing from 44 V to 46 V,
// and Copy then quoted 46 V as approved; a draft on an item the loop had since answered still exported. So every draft
// carries a fingerprint of the question, the options in their own words, the default and the status it was drafted
// against, and a draft that no longer matches is STALE: never shown as answered, never exported, and shown on the card
// with Reconfirm / Discard. WHY stale and not silently deleted: the draft is Zach's own words; only he may drop them.

import { CHOICES, type Choice, type NeedsItem } from './types'

export interface AnswerDraft {
  /** null = no option clicked yet. A note alone answers as `other` only where the item offers `other`. */
  choice: Choice | null
  /** Zach's words exactly as typed: never trimmed or normalized anywhere (trim() only ever TESTS for blankness). */
  note: string
  /** ISO time of the last edit. */
  updated: string
  /** reviewedFingerprint(item) when this draft was written or reconfirmed; null on a draft saved before drafts were
   * bound, which therefore cannot say what it answered. */
  fingerprint: string | null
  /** The item's status when this draft was written (always `open`: settled items take no drafts). */
  status: string | null
  /** Transient, never stored: false when the item offers no "Something else", so a note alone chooses nothing.
   * Set by liveDraft() (the store's get() and the exporter); undefined means "assume it does". */
  offersOther?: boolean
}

// ------------------------------------------------------------------------------------------- the fingerprint

/** 53-bit string hash (cyrb53, public domain). Not cryptographic: it only has to notice that the words changed. */
function cyrb53(text: string, seed: number): string {
  let h1 = 0xdeadbeef ^ seed
  let h2 = 0x41c6ce57 ^ seed
  for (let i = 0; i < text.length; i++) {
    const ch = text.charCodeAt(i)
    h1 = Math.imul(h1 ^ ch, 2654435761)
    h2 = Math.imul(h2 ^ ch, 1597334677)
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909)
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909)
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16).padStart(14, '0')
}

/**
 * What Zach reviewed when he drafted an answer to `item`: its question text (title, ask and the full verbatim context,
 * UPDATE paragraphs included), every option it offers (key, the dashboard's label and the loop's own words), its
 * default (text and when it applies) and its status. Anything that changes one of these makes an older draft stale.
 *
 * WHY not the computed fields (group, default.state, blocking_now, updated.ts, generated_at): they move as the loop
 * progresses without the question changing; binding to them would turn every draft stale at every wave close.
 */
export function reviewedFingerprint(item: NeedsItem): string {
  const reviewed = JSON.stringify([
    'vibetracks-draft/1',
    item.local_id,
    item.title,
    item.ask,
    item.context_md,
    item.options.map((option) => [option.key, option.label, option.detail_md ?? null]),
    [item.default.text_md, item.default.applies.unit, item.default.applies.after ?? null],
    item.status,
  ])
  return `v1:${cyrb53(reviewed, 1)}${cyrb53(reviewed, 2)}`
}

// ------------------------------------------------------------------------------------------- live or stale

/** An item takes drafts only while the loop still has it open. */
export function isAnswerable(item: NeedsItem): boolean {
  return item.status === 'open'
}

export type StaleReason = 'changed' | 'settled' | 'unbound'

export interface StaleDraft {
  draft: AnswerDraft
  reason: StaleReason
  /** The item's status now. */
  status: NeedsItem['status']
  /** Reconfirm can re-bind it: the item is open and still offers the drafted option (or the draft has no option). */
  reconfirmable: boolean
}

export interface DraftState {
  /** The draft as it may be shown as answered and exported, or null. */
  live: AnswerDraft | null
  /** The draft Zach must reconfirm or discard first, or null. */
  stale: StaleDraft | null
}

function offeredKeys(item: NeedsItem): Set<Choice> {
  return new Set(item.options.map((option) => option.key))
}

/**
 * A stored draft as `keys` allows it: a choice the item does not offer is dropped, the note stays (as a note with no
 * option: effectiveChoice() decides whether that is "something else"); a draft left with neither is null.
 *
 * WHY the note stays even where `other` is not offered (finding 7): a draft's words are Zach's and are never dropped
 * behind his back; a note with no option is exported as exactly that where the channel can carry it, and named under
 * "Not in the copy" where it cannot. WHY a read-side rule and not a cleanup sweep: a view must never rewrite what Zach
 * saved; the next edit of that item writes the cleaned draft.
 */
export function offeredDraft(draft: AnswerDraft | null, keys: Set<Choice> | undefined): AnswerDraft | null {
  if (!draft) return null
  const withOther = keys ? { ...draft, offersOther: keys.has('other') } : draft
  if (!keys || !draft.choice || keys.has(draft.choice)) return withOther
  return draft.note ? { ...withOther, choice: null } : null
}

/** Live (bound to the item as it reads now, and the item still open) or stale, for one stored draft. */
export function draftState(draft: AnswerDraft | null | undefined, item: NeedsItem): DraftState {
  if (!draft) return { live: null, stale: null }
  const keys = offeredKeys(item)
  const reconfirmable = isAnswerable(item) && (!draft.choice || keys.has(draft.choice))
  if (!isAnswerable(item)) return { live: null, stale: { draft, reason: 'settled', status: item.status, reconfirmable: false } }
  if (!draft.fingerprint) return { live: null, stale: { draft, reason: 'unbound', status: item.status, reconfirmable } }
  if (draft.fingerprint !== reviewedFingerprint(item)) return { live: null, stale: { draft, reason: 'changed', status: item.status, reconfirmable } }
  return { live: offeredDraft(draft, keys), stale: null }
}

/** The draft that may be shown as answered and exported, or null (none, or stale). */
export function liveDraft(draft: AnswerDraft | null | undefined, item: NeedsItem): AnswerDraft | null {
  return draftState(draft, item).live
}

/** The calm sentence for a stale draft's reason (the card notice and Copy's "Not in the copy" list). */
export function staleText(stale: Pick<StaleDraft, 'reason' | 'status'>): string {
  if (stale.reason === 'settled') return `the loop settled this (${stale.status}) since you drafted it`
  if (stale.reason === 'unbound') return 'drafted before the dashboard recorded which version of the question you saw'
  return 'the question changed since you drafted it'
}

// ------------------------------------------------------------------------------------------- what the draft says

/** The choice an export carries: an explicit click wins; a note alone means `other` where the item offers it;
 * otherwise nothing (a note alone on an item without `other` is a note with no option: isNoteOnly). */
export function effectiveChoice(draft: AnswerDraft | null | undefined): Choice | null {
  if (!draft) return null
  if (draft.choice) return draft.choice
  return draft.note.trim() && draft.offersOther !== false ? 'other' : null
}

/** A draft is exportable as an answer when it has a choice, and `other` carries a non-blank note (the note IS the
 * answer). A note with no option (isNoteOnly) is not an answer to the loop's options. */
export function isComplete(draft: AnswerDraft | null | undefined): boolean {
  const choice = effectiveChoice(draft)
  if (!choice) return false
  return choice !== 'other' || Boolean(draft?.note.trim())
}

/** Words with no option, on an item that offers no "Something else": exported as a note with no option chosen where
 * the channel carries that, else named under "Not in the copy". */
export function isNoteOnly(draft: AnswerDraft | null | undefined): boolean {
  return Boolean(draft && !draft.choice && draft.note.trim() && draft.offersOther === false)
}

// ------------------------------------------------------------------------------------------- markdown

/**
 * Zach's note as a fenced block inside the `- **Note:**` list item: every character kept (newlines, code fences,
 * leading and trailing whitespace), and nothing in it can close the fence or restyle the surrounding markdown.
 *
 * WHY a fence longer than any backtick run in the note: a note that itself contains ``` (a pasted snippet) must not
 * end the block early. WHY two spaces before every line: that is the list item's content indent, which CommonMark
 * strips again, so the block's literal is exactly `note + "\n"` (verified with markdown-it in answers.check.mjs). WHY
 * a fence even for one plain line: inline text is rendered as markdown (`*x*` would become italics, a newline a
 * space), so only a code block shows what was typed.
 */
export function noteBlockLines(note: string): string[] {
  const longest = Math.max(0, ...(note.match(/`+/g) ?? []).map((run) => run.length))
  const fence = '`'.repeat(Math.max(3, longest + 1))
  return ['- **Note:**', `  ${fence}text`, ...markdownLines(note).map((line) => `  ${line}`), `  ${fence}`]
}

/**
 * `text` cut at every line ending CommonMark recognises: LF, CR and CRLF (spec §2.1).
 *
 * WHY all three and not just LF (Codex audit 2026-10-05, round 2 finding 3): a parser ends a line at a lone CR too, so
 * a note "a\rb" split on LF alone put `b` at column 0, outside the list item, and it escaped the fenced block. Every
 * physical line must get the indent, whatever ended it.
 */
export function markdownLines(text: string): string[] {
  return text.split(/\r\n|\r|\n/)
}

/** A lone UTF-16 surrogate: not encodable as UTF-8, so it cannot survive a clipboard or a UTF-8 file as typed. */
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/

/**
 * True when Markdown cannot give `text` back character for character: CommonMark turns every CR and CRLF into LF and
 * NUL into U+FFFD, and a lone surrogate cannot be written as UTF-8. Everything else survives a fenced block exactly
 * (answers.check.mjs measures it with markdown-it).
 */
export function markdownIsLossy(text: string): boolean {
  return /[\r\0]/.test(text) || LONE_SURROGATE.test(text)
}

/** `content` as an inline code span: the one Markdown construct that shows its characters without interpreting
 * backslashes or markup. The delimiter is one backtick longer than any run inside. */
export function codeSpan(content: string): string {
  const longest = Math.max(0, ...(content.match(/`+/g) ?? []).map((run) => run.length))
  const tick = '`'.repeat(longest + 1)
  // CommonMark strips one space from each end when both ends have one, and a backtick at an end would merge with the
  // delimiter; pad only then, so the parsed span is exactly `content`.
  const pad = /^`|`$/.test(content) || (/^ /.test(content) && / $/.test(content) && content.trim() !== '') ? ' ' : ''
  return `${tick}${pad}${content}${pad}${tick}`
}

/**
 * The compact, byte-exact twin of a text Markdown would change: `exact: "<JSON string>"`, the JSON in a code span so no
 * Markdown reader unescapes it. JSON.parse of the span gives the text back exactly (CR, CRLF, NUL, edge spaces).
 *
 * WHY a JSON line and not a second encoding of the block (Codex round 2 finding 3): a chat or note paste has no JSONL
 * row to carry the raw string, and a reader must still be able to recover exactly what Zach typed; one line under the
 * answer does that without making every ordinary answer noisier (it appears only when Markdown would lose something).
 */
export function exactLine(text: string, label = 'exact'): string {
  return `  ${label}: ${codeSpan(JSON.stringify(text))}`
}

/**
 * Loop text that must sit on ONE Markdown line (a heading's title, an answer label): returned as typed, or, when it
 * holds a line ending or a character Markdown cannot carry, as a JSON string in a code span, so it can neither break
 * the line (and restyle what follows) nor lose a character. Never trimmed.
 */
export function inlineExact(text: string): string {
  return /[\r\n]/.test(text) || markdownIsLossy(text) ? codeSpan(JSON.stringify(text)) : text
}

/**
 * True when loop text set on one Markdown line (a heading, the answer line) may not parse back as the same characters:
 * edge whitespace (a heading drops it, and a line's ends are trimmed), a character Markdown may read as markup
 * (emphasis, code, links, raw HTML, entities, escapes, strikethrough), or a heading's closing `#` run.
 * WHY conservative: a twin too many costs one extra line; a twin too few loses what Zach reviewed. The source line
 * itself always keeps every character (never trimmed, never escaped).
 */
export function inlineIsLossy(text: string): boolean {
  return text !== text.trim() || /[\\`*_[\]<>&~]/.test(text) || /(^|\s)#+$/.test(text)
}

/**
 * The `exact <label>: "<JSON>"` twin for loop text on a Markdown line, or [] when the line already carries it exactly.
 * WHY the same rule as notes and option words (verifier, 2026-10-05): an item title with edge spaces lost them in the
 * parsed heading, exactly the loss the `exact:` twin already repairs for a note and an option's words. inlineExact()
 * already shows a line ending or a CR/NUL as JSON on the line itself, so those need no twin.
 */
export function inlineTwinLines(text: string, label: string): string[] {
  if (/[\r\n]/.test(text) || markdownIsLossy(text)) return []
  return inlineIsLossy(text) ? [exactLine(text, label)] : []
}

// ------------------------------------------------------------------------------------------- stored form

/** A stored entry as a draft, or null. The store's reader; pure so answers.check.mjs runs it. */
export function parseStoredDraft(raw: string | null): AnswerDraft | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<AnswerDraft>
    // WHY CHOICES and not a hand list: grasping's `approve` was dropped on every reload by a list that predated it.
    const choice = (CHOICES as unknown[]).includes(value.choice) ? (value.choice as Choice) : null
    return {
      choice,
      note: typeof value.note === 'string' ? value.note : '',
      updated: typeof value.updated === 'string' ? value.updated : '',
      fingerprint: typeof value.fingerprint === 'string' ? value.fingerprint : null,
      status: typeof value.status === 'string' ? value.status : null,
    }
  } catch {
    return null
  }
}

/** A new draft for `item`, bound to the item as it reads now. The store's set() and reconfirm() write exactly this. */
export function boundDraft(item: NeedsItem, choice: Choice | null, note: string, now: Date = new Date()): AnswerDraft {
  return { choice, note, updated: now.toISOString(), fingerprint: reviewedFingerprint(item), status: item.status }
}

