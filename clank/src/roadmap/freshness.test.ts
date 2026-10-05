import { describe, expect, it } from 'vitest'
import { freshness } from './freshness'

// The API's contract (vibetracks/roadmap/api.py): when a projection fails and an older good document is served, its
// `warnings` carry an entry starting "stale: " and `generated_at` is the time of the good projection.
const NOW = new Date('2026-10-04T18:00:00Z')
const at = (generated_at: string, warnings: string[] = []) => ({ generated_at, warnings })
const opts = { now: NOW, timeZone: 'UTC' }

describe('freshness (the quiet "as of" and the one calm "not current" line)', () => {
  it('a fresh document shows only the as-of time, and no not-current line', () => {
    expect(freshness(at('2026-10-04T14:05:09Z'), opts)).toEqual({ asOf: 'as of 14:05', notCurrent: null, notCurrentFull: null })
  })

  it('a document projected on an earlier day names that day, so an old good projection cannot read as today', () => {
    expect(freshness(at('2026-10-03T23:59:00Z'), opts).asOf).toBe('as of 3 Oct 23:59')
    expect(freshness(at('2026-10-04T00:00:00Z'), opts).asOf).toBe('as of 00:00')
  })

  it('a "stale: " warning becomes the not-current line, with the reason trimmed and the prefix dropped', () => {
    const result = freshness(at('2026-10-04T14:05:00Z', ['no rung on axis x', 'stale:  projecting kinsim failed: boom \n']), opts)
    expect(result.notCurrent).toBe('Not current: projecting kinsim failed: boom')
    expect(result.notCurrentFull).toBe('projecting kinsim failed: boom')
    expect(result.asOf).toBe('as of 14:05')
  })

  it('ordinary warnings, and look-alikes without the exact "stale: " prefix, are not staleness', () => {
    expect(freshness(at('2026-10-04T14:05:00Z', ['3 links unresolved', 'stale:no space', 'a stale: mid-line', 'Stale: capital']), opts).notCurrent).toBeNull()
  })

  it('an empty reason still says the document is not current', () => {
    expect(freshness(at('2026-10-04T14:05:00Z', ['stale: ']), opts).notCurrent).toBe('Not current')
  })

  it('a long reason is cut with an explicit ellipsis, and the whole of it stays in notCurrentFull', () => {
    const reason = `projecting kinsim failed: ${'x'.repeat(400)}`
    const result = freshness(at('2026-10-04T14:05:00Z', [`stale: ${reason}`]), opts)
    expect(result.notCurrent!.endsWith('…')).toBe(true)
    expect(result.notCurrent!.length).toBeLessThan(200)
    expect(result.notCurrentFull).toBe(reason)
  })

  it('an unreadable generated_at shows no as-of rather than a made-up time', () => {
    expect(freshness(at(''), opts).asOf).toBeNull()
    expect(freshness(at('not a time'), opts).asOf).toBeNull()
    expect(freshness({ generated_at: undefined as never, warnings: undefined as never }, opts)).toEqual({ asOf: null, notCurrent: null, notCurrentFull: null })
  })
})
