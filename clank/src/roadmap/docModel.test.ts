import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { RoadmapDoc } from './doc'
import { RoadmapDocError, modelFromDoc, parseRoadmapDoc } from './docModel'
import { layout, type Lens } from './graph'

// The REAL projections (bam_ws reports, 2026-10-03): kinsim (62 rungs, 5 aliases, waves, triage blockers) and rig
// (22 rungs, no waves, no depends_on). WHY real documents and not a fixture: the adapter's job is to take exactly what
// the projector writes, so a fixture shaped by this test's own idea of the format would prove nothing.
const DOCS = '/home/bam/bam_ws/reports/media/bam-roadmap-format-2026-10-03'
const read = (name: string): unknown => JSON.parse(readFileSync(`${DOCS}/${name}.json`, 'utf8'))
const REAL = ['kinsim', 'rig'] as const

for (const name of REAL) {
  describe(`modelFromDoc on the real ${name}.json`, () => {
    const doc = parseRoadmapDoc(read(name))
    const model = modelFromDoc(doc)

    it('maps every rung, once, carrying the document rung itself', () => {
      expect(model.rungs.length).toBe(doc.rungs.length)
      expect([...model.rungs.map((rung) => rung.id)].sort()).toEqual([...doc.rungs.map((rung) => rung.id)].sort())
      for (const rung of doc.rungs) {
        const mapped = model.byId.get(rung.id)!
        expect(mapped.rung === rung, rung.id).toBe(true)
        expect(mapped.axis).toBe(rung.axis)
        expect(mapped.title).toBe(rung.title)
        expect(mapped.wave).toBe(rung.wave)
        expect(mapped.frontier).toBe(rung.frontier)
        expect(mapped.triage).toEqual(rung.blockers.map((blocker) => blocker.id))
      }
    })

    it('draws exactly the depends_on edges as prerequisites', () => {
      const expected = doc.rungs.flatMap((rung) => rung.depends_on.map((parent) => `${parent}>${rung.id}`)).sort()
      const drawn = model.edges.filter((edge) => edge.kind === 'pre').map((edge) => `${edge.from}>${edge.to}`).sort()
      expect(drawn).toEqual(expected)
      // The projector's own edge list agrees (an independent spelling of the same relation).
      expect(drawn).toEqual(doc.edges.filter((edge) => edge.kind === 'prerequisite').map((edge) => `${edge.from}>${edge.to}`).sort())
    })

    it('maps every alias_of to sameAs and a same edge from its target', () => {
      for (const rung of doc.rungs) {
        expect(model.byId.get(rung.id)!.sameAs, rung.id).toBe(rung.alias_of)
        if (rung.alias_of) expect(model.edges).toContainEqual({ from: rung.alias_of, to: rung.id, kind: 'same' })
      }
      expect(model.edges.filter((edge) => edge.kind === 'same').length).toBe(doc.rungs.filter((rung) => rung.alias_of).length)
    })

    it('keeps every derived status as stored, claimed included', () => {
      for (const rung of doc.rungs) expect(model.byId.get(rung.id)!.status, rung.id).toBe(rung.status)
      const claimed = model.rungs.filter((rung) => rung.status === 'claimed')
      expect(claimed.length).toBe(doc.counts.by_status.claimed)
      expect(claimed.map((rung) => rung.id).sort()).toEqual([...doc.counts.claimed_green_not_proven].sort())
      for (const rung of claimed) expect(rung.rung.claimed_status).toBe('green')
    })

    it('orders the lanes by the axes order and the rungs by their authored order inside a lane', () => {
      expect(model.axes.map((axis) => axis.id)).toEqual([...doc.axes].sort((a, b) => a.order - b.order).map((axis) => axis.id))
      for (const axis of model.axes) {
        const orders = model.rungs.filter((rung) => rung.axis === axis.id).map((rung) => rung.rung.order)
        expect(orders).toEqual([...orders].sort((a, b) => a - b))
      }
    })

    it('lays out under every lens', () => {
      for (const lens of ['ladder', 'depth', 'board', 'waves'] as Lens[]) {
        const lay = layout(model, lens)
        expect(lay.pos.size, lens).toBe(doc.rungs.length)
      }
    })
  })
}

describe('modelFromDoc on the real documents: what differs between them', () => {
  it('kinsim has waves, aliases and est_waves; rig has none of them', () => {
    const kinsim = modelFromDoc(parseRoadmapDoc(read('kinsim')))
    const rig = modelFromDoc(parseRoadmapDoc(read('rig')))
    expect(kinsim.hasWaves).toBe(true)
    expect(kinsim.rungs.filter((rung) => rung.sameAs).length).toBe(5)
    expect(kinsim.rungs.some((rung) => rung.est > 0)).toBe(true)
    expect(rig.hasWaves).toBe(false)
    // rig's ordering lives only in its `package` edges (work packages), which the board does not draw: the spec draws
    // depends_on and alias_of. Pinned so a change to that rule is a deliberate one.
    expect(rig.edges).toEqual([])
  })
})

describe('parseRoadmapDoc refuses what is not a bam-roadmap/1 document', () => {
  const kinsim = read('kinsim') as RoadmapDoc

  it('refuses a foreign schema, naming it', () => {
    expect(() => parseRoadmapDoc({ ...kinsim, schema: 'bam-roadmap/2' })).toThrow(/bam-roadmap\/2/)
    expect(() => parseRoadmapDoc({ ...kinsim, schema: 'loop-status/1' })).toThrow(/not a bam-roadmap\/1 document/)
    expect(() => parseRoadmapDoc({ rungs: [] })).toThrow(/not a bam-roadmap\/1 document/)
  })

  it('refuses a non-object and a document without rungs or axes', () => {
    expect(() => parseRoadmapDoc(null)).toThrow(/not a bam-roadmap\/1 document/)
    expect(() => parseRoadmapDoc('bam-roadmap/1')).toThrow(/not a bam-roadmap\/1 document/)
    expect(() => parseRoadmapDoc({ ...kinsim, rungs: undefined })).toThrow(/rungs/)
    expect(() => parseRoadmapDoc({ ...kinsim, axes: {} })).toThrow(/axes/)
  })

  it('throws a RoadmapDocError, so the widget can say what is wrong without a crash', () => {
    let caught: unknown = null
    try {
      parseRoadmapDoc({ schema: 'x' })
    } catch (error) {
      caught = error
    }
    expect(caught instanceof RoadmapDocError).toBe(true)
  })

  it('refuses a rung on an axis the document does not declare', () => {
    const broken = { ...kinsim, rungs: [{ ...kinsim.rungs[0], axis: 'nowhere' }, ...kinsim.rungs.slice(1)] }
    expect(() => modelFromDoc(parseRoadmapDoc(broken))).toThrow(/nowhere/)
  })

  it('accepts the real documents as they are', () => {
    expect(parseRoadmapDoc(kinsim).loop).toBe('kinsim')
    expect(parseRoadmapDoc(read('rig')).loop).toBe('rig')
  })
})
