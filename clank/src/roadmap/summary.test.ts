import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { blankRung, type RoadmapDoc, type RoadmapRung } from './doc'
import { parseRoadmapDoc } from './docModel'
import { calmSentence, calmSummary, phaseToken, stageLabel } from './summary'

const DOCS = '/home/bam/bam_ws/reports/media/bam-roadmap-format-2026-10-03'
const real = (name: string) => parseRoadmapDoc(JSON.parse(readFileSync(`${DOCS}/${name}.json`, 'utf8')))

/** A small document: two lanes, statuses and blockers as given, frontier as given (summary order). */
function tiny(
  rungs: Array<Partial<RoadmapRung> & { id: string; axis: string }>,
  frontier: string[],
  where?: Array<{ axis: string; here: string | null; here_claimed: string | null; next: string | null; status: string }>,
  summary: Partial<RoadmapDoc['summary']> = {},
): RoadmapDoc {
  const full = rungs.map((part, order) => ({ ...blankRung(part.id, part.axis), order, ...part }))
  const byStatus = { green: 0, done: 0, stale: 0, claimed: 0, partial: 0, missing: 0 }
  for (const rung of full) byStatus[rung.status] += 1
  return {
    schema: 'bam-roadmap/1', loop: 't', title: 'T', generated_at: '2026-10-03T00:00:00Z',
    summary: { wave: 1, phase: 'running', frontier, milestone: null, links: {}, ...summary },
    ...(where ? { where } : {}),
    counts: { by_status: byStatus, claimed_green_not_proven: [], evidence_items: 0, unresolved_links: 0 },
    warnings: [], axes: [{ id: 'a', title: 'Alpha', order: 0 }, { id: 'b', title: 'Beta', order: 1 }], rungs: full, edges: [],
  }
}
const blocker = (id: string) => ({ id, title: `question ${id}`, default: null, default_applies_after_wave: null, source: null })

describe('calmSummary on the real documents', () => {
  it('kinsim: proven is green + done, claimed is its own count, both as the projector counted them', () => {
    const doc = real('kinsim')
    const summary = calmSummary(doc)
    expect(summary.total).toBe(62)
    expect(summary.proven).toBe(doc.counts.by_status.green + doc.counts.by_status.done)
    expect(summary.proven).toBe(4)
    expect(summary.claimed).toBe(doc.counts.by_status.claimed)
    expect(summary.claimed).toBe(12)
    expect(summary.stale).toBe(0)
    expect(summary.current).toEqual(doc.summary.frontier)
    // Every prerequisite climbing or proven: RB4 also waits on MR1, which nobody is climbing, so it is later, not next.
    expect(summary.next).toEqual(['RB2', 'OB2', 'SN2', 'GP2', 'BT2', 'RG5', 'VZ5'])
    expect(summary.needs).toEqual([
      { id: 'T48', title: summary.needs[0].title, blocks: ['SN1'] },
      { id: 'T49', title: summary.needs[1].title, blocks: ['SN1'] },
    ])
    expect(calmSentence(summary)).toBe('Wave 4 · climbing SN1, BT1 +6 · next RB2, OB2 +5 · 4 of 62 proven · 12 claimed · needs you: T48 (blocks SN1) +1')
  })

  it('kinsim: one lane per axis, in axis order, adding up to the whole', () => {
    const doc = real('kinsim')
    const lanes = calmSummary(doc).lanes
    expect(lanes.map((lane) => lane.axis)).toEqual([...doc.axes].sort((a, b) => a.order - b.order).map((axis) => axis.id))
    expect(lanes.reduce((sum, lane) => sum + lane.total, 0)).toBe(62)
    expect(lanes.reduce((sum, lane) => sum + lane.proven, 0)).toBe(4)
    expect(lanes.reduce((sum, lane) => sum + lane.claimed, 0)).toBe(12)
  })

  it('rig: nothing proven, its frontier current, no dependency edges so no next, nobody blocked', () => {
    const summary = calmSummary(real('rig'))
    expect([summary.proven, summary.total, summary.claimed]).toEqual([0, 22, 12])
    expect(summary.needs).toEqual([])
    expect(calmSentence(summary)).toBe('Wave 4 · climbing CS1b, CM2 +2 · 0 of 22 proven · 12 claimed')
  })
})

describe('calmSummary rules', () => {
  it('says stale only when something is stale, and claimed only when something is claimed', () => {
    const doc = tiny([{ id: 'A0', axis: 'a', status: 'stale' }, { id: 'B0', axis: 'b', status: 'green' }], [])
    expect(calmSentence(calmSummary(doc))).toBe('Wave 1 · 1 of 2 proven · 1 stale')
  })

  it('groups one question blocking two current rungs, and ignores blockers off the frontier', () => {
    const doc = tiny([
      { id: 'A0', axis: 'a', blockers: [blocker('T1')] },
      { id: 'B0', axis: 'b', blockers: [blocker('T1'), blocker('T2')] },
      { id: 'B1', axis: 'b', blockers: [blocker('T9')] },
    ], ['B0', 'A0'])
    const summary = calmSummary(doc)
    expect(summary.needs.map((need) => [need.id, need.blocks])).toEqual([['T1', ['B0', 'A0']], ['T2', ['B0']]])
    expect(calmSentence(summary)).toBe('Wave 1 · climbing B0, A0 · 0 of 3 proven · needs you: T1 (blocks B0, A0) +1')
  })

  it('falls back to the rungs flagged frontier when the summary names none', () => {
    const doc = tiny([{ id: 'A0', axis: 'a' }, { id: 'B0', axis: 'b', frontier: true }], [])
    expect(calmSummary(doc).current).toEqual(['B0'])
  })

  it('names what the current rungs unlock: unbanked dependents, in rung order, not themselves current', () => {
    const doc = tiny([
      { id: 'A0', axis: 'a', status: 'done' },
      { id: 'A1', axis: 'a', status: 'partial', depends_on: ['A0'] },
      { id: 'A2', axis: 'a', depends_on: ['A1'] },
      { id: 'B1', axis: 'b', status: 'partial', depends_on: ['A0'] },
      { id: 'B2', axis: 'b', depends_on: ['B1', 'A1'] },
      { id: 'B3', axis: 'b', status: 'claimed', claimed_status: 'green', depends_on: ['B1'] },
      { id: 'B4', axis: 'b', status: 'green', depends_on: ['B1'] },
      { id: 'B5', axis: 'b', depends_on: ['B3'] },
    ], ['B1', 'A1'])
    const summary = calmSummary(doc)
    // A2 (after A1), B2 (after both), B3 (claimed is not banked); not B4 (proven), not B5 (waits on B3, not on a current rung)
    expect(summary.next).toEqual(['A2', 'B2', 'B3'])
    expect(calmSentence(summary)).toBe('Wave 1 · climbing B1, A1 · next A2, B2 +1 · 2 of 8 proven · 1 claimed')
  })

  it('leaves next out when the current rungs unlock nothing', () => {
    const doc = tiny([{ id: 'A0', axis: 'a', status: 'partial' }, { id: 'B0', axis: 'b', status: 'done' }], ['A0'])
    expect(calmSummary(doc).next).toEqual([])
    expect(calmSentence(calmSummary(doc))).toBe('Wave 1 · climbing A0 · 1 of 2 proven')
  })

  it('with no frontier at all, takes each lane\'s next rung from the where rows, skipping proven and unknown ids', () => {
    const doc = tiny(
      [{ id: 'A0', axis: 'a', status: 'done' }, { id: 'A1', axis: 'a', depends_on: ['A0'] }, { id: 'B0', axis: 'b', status: 'claimed', claimed_status: 'green' }, { id: 'B1', axis: 'b', depends_on: ['B0'] }],
      [],
      [
        { axis: 'a', here: 'A0', here_claimed: 'A0', next: 'A1', status: 'partial' },
        { axis: 'b', here: null, here_claimed: 'B0', next: null, status: 'partial' },
        { axis: 'c', here: null, here_claimed: null, next: 'ZZ9', status: 'partial' },
      ],
    )
    const summary = calmSummary(doc)
    expect(summary.current).toEqual(['A1', 'B0'])
    expect(summary.next).toEqual(['B1'])
    expect(calmSentence(summary)).toBe('Wave 1 · climbing A1, B0 · next B1 · 1 of 4 proven · 1 claimed')
  })

  it('with neither frontier nor where rows, says only the bank', () => {
    const doc = tiny([{ id: 'A0', axis: 'a', status: 'done' }], [], undefined, { wave: null, phase: null })
    expect(calmSentence(calmSummary(doc))).toBe('1 of 1 proven')
  })

  it('names the phase beside the wave only when the loop is not simply running', () => {
    const doc = tiny([{ id: 'A0', axis: 'a' }], ['A0'], undefined, { phase: 'paused' })
    expect(calmSentence(calmSummary(doc))).toBe('Wave 1, paused · climbing A0 · 0 of 1 proven')
    expect(calmSentence(calmSummary(tiny([{ id: 'A0', axis: 'a' }], ['A0'], undefined, { wave: null, phase: 'paused' })))).toBe('Paused · climbing A0 · 0 of 1 proven')
  })

  it('says the phase in words: underscores become spaces (a hyphen is English and stays), lowercase after the wave, capital only first', () => {
    expect(stageLabel({ wave: 4, phase: 'between_waves' })).toBe('Wave 4, between waves')
    expect(stageLabel({ wave: 4, phase: 're-planning' })).toBe('Wave 4, re-planning')
    expect(stageLabel({ wave: null, phase: 'between_waves' })).toBe('Between waves')
    expect(stageLabel({ wave: 4, phase: 'running' })).toBe('Wave 4')
  })

  it('keeps the loop\'s raw phase token for the head\'s title (nothing hidden without a way to see it)', () => {
    expect(phaseToken({ phase: 'between_waves' })).toBe('between_waves')
    expect(phaseToken({ phase: 'running' })).toBeNull()
    expect(phaseToken({ phase: null })).toBeNull()
  })
})
