// "· N proven" beside a loop's north star: how many rungs the roadmap projector itself counts as proven
// (counts.by_status.green + counts.by_status.done), read from the roadmap widget's document.
// WHY the projector's counts and never the rung list: the projector owns what "proven" means (green = judged with
// evidence, done = closed); recounting rung statuses here would be a second derivation that can drift from the
// widget's own numbers on the same page (agreed with the roadmap session, 2026-10-04).
// WHY "(not current)" on a "stale…" warning: the backend served its last good projection after a failed refresh; the
// number is real but old, so it is shown and marked, never passed off as now.
// WHY nothing at all when a count is missing: a missing count is not 0 proven (truth rule); the line stays as it was.
// Pure and dependency-free so `node --experimental-strip-types proven.test.mjs` can check it without a bundler.

const isObject = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value)
const count = (value: unknown): number | null => (typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null)

/** The roadmap document inside useRoadmap(...).doc: the real widget wraps it as `{document, artNames, ...}`; a bare
 * document (the shape the contract names) is accepted too. */
function documentOf(doc: unknown): Record<string, unknown> | null {
  if (!isObject(doc)) return null
  return isObject(doc.document) ? doc.document : doc
}

export interface Proven {
  /** green + done, from the projector's own counts. */
  proven: number
  /** The document was served from a fallback after a failed refresh (a warning starting "stale"). */
  stale: boolean
}

/** The proven count, or null when the document is absent or does not carry both counts. */
export function provenOf(doc: unknown): Proven | null {
  const document = documentOf(doc)
  if (!document) return null
  const counts = isObject(document.counts) ? document.counts : null
  const byStatus = counts && isObject(counts.by_status) ? counts.by_status : null
  if (!byStatus) return null
  const green = count(byStatus.green)
  const done = count(byStatus.done)
  if (green === null || done === null) return null
  const warnings = Array.isArray(document.warnings) ? document.warnings : []
  const stale = warnings.some((warning) => typeof warning === 'string' && warning.startsWith('stale'))
  return { proven: green + done, stale }
}

/** "4 proven", "4 proven (not current)", or null (leave the line exactly as it is). */
export function provenText(doc: unknown): string | null {
  const proven = provenOf(doc)
  if (!proven) return null
  return `${proven.proven} proven${proven.stale ? ' (not current)' : ''}`
}
