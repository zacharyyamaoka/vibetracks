import { describe, expect, it } from 'vitest'
import { buckets, edgePath, layout, modelFromParts, place, type Box, type PlaceOptions, type RoadModel } from './graph'

const AXES = [{ id: 'r', title: 'Robots' }, { id: 'e', title: 'Eval' }]
// modelFromParts has no triage field (its signature is shared); blocking triage is set on the built rung instead.
const block = (model: RoadModel, id: string) => { model.byId.get(id)!.triage = ['T48'] }

describe('alias buckets (B10)', () => {
  it('does not call a blocked alias ready just because its target is', () => {
    const m = modelFromParts(AXES, [{ id: 'A', axis: 'r', status: 'partial' }, { id: 'B', axis: 'e', status: 'partial', sameAs: 'A' }])
    block(m, 'B')
    expect(Object.fromEntries(buckets(m))).toEqual({ A: 'ready', B: 'next' })
  })

  it('keeps an unblocked alias with its ready target', () => {
    const m = modelFromParts(AXES, [{ id: 'A', axis: 'r', status: 'partial' }, { id: 'B', axis: 'e', status: 'partial', sameAs: 'A' }])
    expect(Object.fromEntries(buckets(m))).toEqual({ A: 'ready', B: 'ready' })
  })

  it('carries a block anywhere along an alias chain to every alias behind it', () => {
    const m = modelFromParts(AXES, [
      { id: 'A', axis: 'r', status: 'partial' },
      { id: 'B', axis: 'e', status: 'partial', sameAs: 'A' },
      { id: 'C', axis: 'e', status: 'partial', sameAs: 'B' },
    ])
    block(m, 'B')
    expect(Object.fromEntries(buckets(m))).toEqual({ A: 'ready', B: 'next', C: 'next' })
  })

  it('still banks an alias whose target is banked', () => {
    const m = modelFromParts(AXES, [{ id: 'A', axis: 'r', status: 'green' }, { id: 'B', axis: 'e', status: 'green', sameAs: 'A' }])
    expect(Object.fromEntries(buckets(m))).toEqual({ A: 'banked', B: 'banked' })
  })
})

describe('alias connector (B11)', () => {
  const OPTIONS = { cellW: 100, cellH: 40, gapAcross: 20, gapWithin: 10, laneGap: 16, label: 30, head: 20, pad: 4 }
  const lr: PlaceOptions = { ...OPTIONS, orient: 'lr' }
  const td: PlaceOptions = { ...OPTIONS, orient: 'td' }
  // The end point of an absolute M/V/H/C path.
  const endOf = (path: string): [number, number] => {
    const [x0, y0, ...rest] = path.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
    if (/V/.test(path)) return [x0, rest[0]]
    if (/H/.test(path)) return [rest[0], y0]
    return [rest.at(-2)!, rest.at(-1)!]
  }
  const touches = (end: [number, number], box: Box, orient: 'lr' | 'td') => orient === 'lr'
    ? (end[0] === box.x || end[0] === box.x + box.w) && end[1] === box.y + box.h / 2
    : (end[1] === box.y || end[1] === box.y + box.h) && end[0] === box.x + box.w / 2

  for (const orient of ['lr', 'td'] as const) {
    it(`ends a cross-column alias at its target box (${orient})`, () => {
      const m = modelFromParts(AXES, [
        { id: 'R0', axis: 'r' }, { id: 'R1', axis: 'r' }, { id: 'E0', axis: 'e' }, { id: 'E1', axis: 'e', sameAs: 'R0' },
      ])
      const geo = place(m, layout(m, 'ladder'), orient === 'lr' ? lr : td)
      // Ladder lens: gc is the index within the axis, so the alias E1 (column 1) is a column away from R0 (column 0).
      expect(geo.nodes.get('R0')![orient === 'lr' ? 'x' : 'y']).not.toBe(geo.nodes.get('E1')![orient === 'lr' ? 'x' : 'y'])
      const edge = m.edges.find((e) => e.kind === 'same')!
      const path = edgePath(geo, edge)
      expect(touches(endOf(path), geo.nodes.get(edge.to)!, orient), `${orient}: ${path} vs ${JSON.stringify(geo.nodes.get(edge.to))}`).toBe(true)
    })

    it(`ends an alias placed left of its target at the target box (${orient})`, () => {
      const m = modelFromParts(AXES, [
        { id: 'R0', axis: 'r' }, { id: 'R1', axis: 'r' }, { id: 'E0', axis: 'e', sameAs: 'R1' },
      ])
      const geo = place(m, layout(m, 'ladder'), orient === 'lr' ? lr : td)
      const edge = m.edges.find((e) => e.kind === 'same')!
      const path = edgePath(geo, edge)
      expect(touches(endOf(path), geo.nodes.get(edge.to)!, orient), `${orient}: ${path}`).toBe(true)
    })
  }

  it('keeps the gutter shortcut when both endpoints share a column', () => {
    const m = modelFromParts(AXES, [{ id: 'R0', axis: 'r' }, { id: 'E0', axis: 'e', sameAs: 'R0' }])
    const geo = place(m, layout(m, 'ladder'), lr)
    const a = geo.nodes.get('R0')!, b = geo.nodes.get('E0')!
    expect(a.x).toBe(b.x)
    expect(edgePath(geo, m.edges[0])).toBe(`M${a.x - 4} ${a.y + a.h / 2} V${b.y + b.h / 2}`)
  })
})

// Zach, Oct 3: "shouldn't each one be on its own layer?" A wave keeps its band, ordered by dependency inside it.
describe('waves lens', () => {
  it('puts a rung after its prerequisite even when the plan puts both in one wave', () => {
    const m = modelFromParts([{ id: 'e', title: 'Eval' }, { id: 'r', title: 'Robots' }], [
      { id: 'E1', axis: 'e', wave: 3 }, { id: 'E2', axis: 'e', pre: ['E1'], wave: 3 }, { id: 'E3', axis: 'e', pre: ['E2'], wave: 3 },
      { id: 'R0', axis: 'r', pre: ['E1'], wave: 4 }, { id: 'R1', axis: 'r', wave: 3 },
    ])
    const lay = layout(m, 'waves')
    const gc = (id: string) => lay.pos.get(id)!.gc
    expect(gc('E2')).toBe(gc('E1') + 1)
    expect(gc('E3')).toBe(gc('E2') + 1)
    expect(gc('R1')).toBe(gc('E1'))
    expect(gc('R0')).toBeGreaterThan(gc('E3'))
    const w3 = lay.heads.find((head) => head.label === 'w3')!
    expect([w3.at, w3.span]).toEqual([gc('E1'), 3])
    for (const edge of m.edges) expect(gc(edge.to)).toBeGreaterThan(gc(edge.from))
  })
})
