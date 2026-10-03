import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { blankRung, type RoadmapDoc, type RoadmapRung } from './doc'
import { parseRoadmapDoc } from './docModel'
import { calmSentence, calmSummary } from './summary'

const DOCS = '/home/bam/bam_ws/reports/media/bam-roadmap-format-2026-10-03'
const real = (name: string) => parseRoadmapDoc(JSON.parse(readFileSync(`${DOCS}/${name}.json`, 'utf8')))

/** A small document: two lanes, statuses and blockers as given, frontier as given (summary order). */
function tiny(rungs: Array<Partial<RoadmapRung> & { id: string; axis: string }>, frontier: string[]): RoadmapDoc {
  const full = rungs.map((part, order) => ({ ...blankRung(part.id, part.axis), order, ...part }))
  const byStatus = { green: 0, done: 0, stale: 0, claimed: 0, partial: 0, missing: 0 }
  for (const rung of full) byStatus[rung.status] += 1
  return {
    schema: 'bam-roadmap/1', loop: 't', title: 'T', generated_at: '2026-10-03T00:00:00Z',
    summary: { wave: 1, phase: 'running', frontier, milestone: null, links: {} },
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
    expect(summary.next).toEqual(doc.summary.frontier)
    expect(summary.needs).toEqual([
      { id: 'T48', title: summary.needs[0].title, blocks: ['SN1'] },
      { id: 'T49', title: summary.needs[1].title, blocks: ['SN1'] },
    ])
    expect(calmSentence(summary)).toBe('4 of 62 proven · 12 claimed · next: SN1, BT1 +6 · needs you: T48 (blocks SN1) +1')
  })

  it('kinsim: one lane per axis, in axis order, adding up to the whole', () => {
    const doc = real('kinsim')
    const lanes = calmSummary(doc).lanes
    expect(lanes.map((lane) => lane.axis)).toEqual([...doc.axes].sort((a, b) => a.order - b.order).map((axis) => axis.id))
    expect(lanes.reduce((sum, lane) => sum + lane.total, 0)).toBe(62)
    expect(lanes.reduce((sum, lane) => sum + lane.proven, 0)).toBe(4)
    expect(lanes.reduce((sum, lane) => sum + lane.claimed, 0)).toBe(12)
  })

  it('rig: nothing proven, its frontier next, nobody on the frontier blocked', () => {
    const summary = calmSummary(real('rig'))
    expect([summary.proven, summary.total, summary.claimed]).toEqual([0, 22, 12])
    expect(summary.needs).toEqual([])
    expect(calmSentence(summary)).toBe('0 of 22 proven · 12 claimed · next: CS1b, CM2 +2')
  })
})

describe('calmSummary rules', () => {
  it('says stale only when something is stale', () => {
    const doc = tiny([{ id: 'A0', axis: 'a', status: 'stale' }, { id: 'B0', axis: 'b', status: 'green' }], [])
    expect(calmSentence(calmSummary(doc))).toBe('1 of 2 proven · 0 claimed · 1 stale')
  })

  it('groups one question blocking two frontier rungs, and ignores blockers off the frontier', () => {
    const doc = tiny([
      { id: 'A0', axis: 'a', blockers: [blocker('T1')] },
      { id: 'B0', axis: 'b', blockers: [blocker('T1'), blocker('T2')] },
      { id: 'B1', axis: 'b', blockers: [blocker('T9')] },
    ], ['B0', 'A0'])
    const summary = calmSummary(doc)
    expect(summary.needs.map((need) => [need.id, need.blocks])).toEqual([['T1', ['B0', 'A0']], ['T2', ['B0']]])
    expect(calmSentence(summary)).toBe('0 of 3 proven · 0 claimed · next: B0, A0 · needs you: T1 (blocks B0, A0) +1')
  })

  it('falls back to the rungs flagged frontier when the summary names none', () => {
    const doc = tiny([{ id: 'A0', axis: 'a' }, { id: 'B0', axis: 'b', frontier: true }], [])
    expect(calmSummary(doc).next).toEqual(['B0'])
  })

  it('leaves next out when there is no frontier at all', () => {
    const doc = tiny([{ id: 'A0', axis: 'a', status: 'done' }], [])
    expect(calmSentence(calmSummary(doc))).toBe('1 of 1 proven · 0 claimed')
  })
})
