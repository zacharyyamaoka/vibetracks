// How current a roadmap document is, from the two fields the API gives it (vibetracks/roadmap/api.py): `generated_at`
// is the time of the projection the document came from, and when a projection fails and an older good document is
// served instead, `warnings` carries an entry starting "stale: " (its reason after the prefix). Pure, so it is tested.
//
// WHY the widget says this at all (Codex V05): a served fallback is otherwise identical to a fresh document, and a
// green "1 of 1 proven" from a failed projection reads as current proof.

import type { RoadmapDoc } from './doc'

export interface Freshness {
  /** "as of 14:05" (with the day, when it is not today); null when generated_at is unreadable. */
  asOf: string | null
  /** The calm line, "Not current: <reason>", the reason cut at NOT_CURRENT_MAX with an explicit ellipsis; null when fresh. */
  notCurrent: string | null
  /** The reason as the API wrote it, trimmed and whole: for the line's tooltip. Null when fresh. */
  notCurrentFull: string | null
}

const STALE_PREFIX = 'stale: '
/** WHY a cap: the reason is a projector error message and can run to a traceback; the full text stays in the tooltip. */
export const NOT_CURRENT_MAX = 140

interface FreshnessOptions {
  now?: Date
  /** IANA zone for the as-of time; the viewer's own zone when omitted. */
  timeZone?: string
}

const dayOf = (at: Date, timeZone: string | undefined) =>
  new Intl.DateTimeFormat('en-GB', { timeZone, year: 'numeric', month: 'numeric', day: 'numeric' }).format(at)

/** "as of 14:05", or "as of 3 Oct 14:05" when the projection is from another day than `now`. */
export function formatAsOf(generatedAt: string, { now = new Date(), timeZone }: FreshnessOptions = {}): string | null {
  const at = new Date(generatedAt)
  if (typeof generatedAt !== 'string' || !generatedAt || Number.isNaN(at.getTime())) return null
  const time = new Intl.DateTimeFormat('en-GB', { timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(at)
  if (dayOf(at, timeZone) === dayOf(now, timeZone)) return `as of ${time}`
  const day = new Intl.DateTimeFormat('en-GB', { timeZone, day: 'numeric', month: 'short' }).format(at)
  return `as of ${day} ${time}`
}

export function freshness(doc: Pick<RoadmapDoc, 'generated_at' | 'warnings'>, options: FreshnessOptions = {}): Freshness {
  const warning = (Array.isArray(doc.warnings) ? doc.warnings : []).find((entry): entry is string => typeof entry === 'string' && entry.startsWith(STALE_PREFIX))
  const asOf = formatAsOf(doc.generated_at, options)
  if (warning === undefined) return { asOf, notCurrent: null, notCurrentFull: null }
  const reason = warning.slice(STALE_PREFIX.length).trim()
  const shown = reason.length > NOT_CURRENT_MAX ? `${reason.slice(0, NOT_CURRENT_MAX).trimEnd()}…` : reason
  return { asOf, notCurrent: shown ? `Not current: ${shown}` : 'Not current', notCurrentFull: reason }
}
