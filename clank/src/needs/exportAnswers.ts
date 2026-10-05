// What "Copy answers" puts on the clipboard: one block per track, readable by Zach, quotable by the integrator, and
// machine-appendable where the loop reads rows. Format agreed with the data mapper (docs/dashboard/NEEDS-KIT.md):
//
//   # Answers · Kinematic Sim · 2026-10-04 19:20 PDT
//   <!-- vibetracks-needs/1 · track=kinsim · source=triage.json@eff3ea86 · channel=jsonl_append -> /…/triage_answers.jsonl -->
//
//   ## T47 · Should this robot be expected to pick at 1.0 m/s and above?
//   - **Answer:** Go with the recommendation (accept_recommendation)
//   - **Note:** Keep the motor limits; also log the skip reason per object.
//
//   ```jsonl
//   {"ts":"2026-10-04T19:20:11-07:00","triage_id":"T47","choice":"accept_recommendation","note":"…"}
//   ```
//
// A track without machine rows (rig's chat paste, detection's note paste, ...) also gets the chosen option's own
// words, quoted under the answer line:
//
//   ## T2 · Approve the W1 bench run?
//   - **Answer:** Go with the recommendation (accept_recommendation)
//     > Run W1 on the bench at 37 V with the soft stops …   (the loop's recommendation, verbatim, every line)
//
// WHY: the label alone ("Go with the recommendation") does not say WHAT was approved, and a chat-paste integrator has
// nothing else to read; the recommendation it refers to may have been rewritten by an UPDATE since. Rows for
// bam-triage-answer/1 stay exactly {ts, triage_id, choice, note}: that loop resolves the choice against its own file.
// When the loop recorded no words for the option, the quote says so instead of staying silent.
//
// WHY every heading carries local_id AND the full title: the integrator must never have to ask which item an answer
// is for (the pyblocks precedent). WHY the jsonl fence only for bam-triage-answer/1 tracks: those rows are appended
// verbatim to triage_answers.jsonl and must validate (exactly {ts, triage_id, choice, note}); a chat-paste loop
// (rig) quotes the markdown instead. Unanswered items are omitted, never exported as blanks.

import { effectiveChoice, isComplete, type AnswerDraft } from './answers'
import type { Choice, NeedsDoc, NeedsItem } from './types'

export const ANSWER_ROW_SCHEMA = 'bam-triage-answer/1'

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
  /** Drafts left out, with why (`other` with a blank note). */
  skipped: { id: string; reason: string }[]
}

type DraftLookup = (track: string, localId: string) => AnswerDraft | null

/** The chosen option's own words as markdown quote lines under the answer bullet, or [] for "Something else" (the note
 * is the answer). Every line of the loop's text is kept; blank lines stay as a bare `>` so paragraphs survive. */
export function optionQuoteLines(item: NeedsItem, choice: Choice): string[] {
  if (choice === 'other') return []
  const option = item.options.find((candidate) => candidate.key === choice)
  const text = option?.detail_md?.trim() ?? ''
  if (!text) return ['  > (the loop recorded no words for this option)']
  return text.split(/\r?\n/).map((line) => (line.trim() ? `  > ${line}` : '  >'))
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
    const draft = draftOf(doc.track, item.local_id)
    const choice = effectiveChoice(draft)
    if (!draft || !choice) continue
    if (!isComplete(draft)) {
      skipped.push({ id: item.id, reason: '"Something else" needs a note' })
      continue
    }
    const note = draft.note.trim()
    const lines = [`## ${item.local_id} · ${item.title}`, `- **Answer:** ${choiceLabel(item, choice)} (${choice})`]
    if (!rowsCarryChoice) lines.push(...optionQuoteLines(item, choice))
    if (note) lines.push(`- **Note:** ${note.replace(/\n+/g, ' ')}`)
    sections.push(lines.join('\n'))
    exported.push(item.id)
    // Key order matters for a reader comparing rows by eye; JSON.stringify keeps insertion order.
    rows.push(JSON.stringify({ ts, triage_id: item.local_id, choice, note }))
  }
  if (!sections.length) return skipped.length ? { markdown: '', exported, skipped } : null
  const channel = doc.answer_channel
  const source = doc.source.paths[0] ? `${doc.source.paths[0].split('/').pop()}${doc.source.commit ? `@${doc.source.commit}` : ''}` : doc.source.adapter
  const header = [
    `# Answers · ${doc.track_title} · ${headingTime(now)}`,
    `<!-- vibetracks-needs/1 · track=${doc.track} · source=${source} · channel=${channel.kind}${channel.target ? ` -> ${channel.target}` : ''} -->`,
  ].join('\n')
  let markdown = `${header}\n\n${sections.join('\n\n')}`
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
