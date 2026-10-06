import { describe, expect, it } from 'vitest'
import { firstRung, layout, modelFromParts, neighbour, place, type Direction, type Lens, type Orient, type RoadModel } from './graph'

const OPTIONS = { cellW: 100, cellH: 40, gapAcross: 20, gapWithin: 10, laneGap: 16, label: 30, head: 20, pad: 4 }
const AXES = [{ id: 'r', title: 'Robots' }, { id: 'e', title: 'Eval' }]
type Parts = Parameters<typeof modelFromParts>[1]

const build = (parts: Parts, orient: Orient, lens: Lens = 'depth', axes = AXES) => {
  const model = modelFromParts(axes, parts)
  return { model, geo: place(model, layout(model, lens), { ...OPTIONS, orient }) }
}
const step = ({ model, geo }: { model: RoadModel; geo: ReturnType<typeof place> }, from: string, dir: Direction) => neighbour(model, geo, from, dir)

// R1 sits three columns after R0; E1 is nearer to R0 along x but in the other lane.
const DIAGONAL: Parts = [
  { id: 'R0', axis: 'r' }, { id: 'E0', axis: 'e' }, { id: 'E1', axis: 'e', pre: ['E0'] }, { id: 'E2', axis: 'e', pre: ['E1'] },
  { id: 'R1', axis: 'r', pre: ['R0', 'E2'] },
]

// Codex I03 (round 8): lane r ends at column 2 while lane e has a card at column 3, so the old all-lane fallback
// stepped from the end of r onto e. The arrow along a lane has to stop at the lane's end.
const LANE_ENDS_EARLY: Parts = [
  { id: 'R0', axis: 'r' }, { id: 'R1', axis: 'r', pre: ['R0'] }, { id: 'R2', axis: 'r', pre: ['R1'] },
  { id: 'E0', axis: 'e' }, { id: 'E1', axis: 'e', pre: ['E0'] }, { id: 'E2', axis: 'e', pre: ['E1'] }, { id: 'E3', axis: 'e', pre: ['E2'] },
]

describe('arrow-key neighbour (lr: lanes are rows)', () => {
  it('goes right to the next rung in the same lane even when another lane has a nearer card diagonally', () => {
    const fixture = build(DIAGONAL, 'lr')
    const { geo } = fixture
    const along = (id: string) => geo.nodes.get(id)!.x - geo.nodes.get('R0')!.x
    expect(along('E1')).toBeLessThan(along('R1'))
    expect(step(fixture, 'R0', 'right')).toBe('R1')
  })

  it('goes left in the same lane too', () => {
    expect(step(build(DIAGONAL, 'lr'), 'R1', 'left')).toBe('R0')
  })

  it('stays in its lane at the lane end: null, never a card in another lane', () => {
    const fixture = build([{ id: 'R0', axis: 'r' }, { id: 'E0', axis: 'e' }, { id: 'E1', axis: 'e', pre: ['E0'] }], 'lr')
    expect(step(fixture, 'R0', 'right')).toBeNull()
    expect(step(fixture, 'E1', 'right')).toBeNull()
  })

  it('goes down to the nearest card in the lane below, aligned by x', () => {
    const fixture = build([{ id: 'R0', axis: 'r' }, { id: 'R1', axis: 'r' }, { id: 'E0', axis: 'e' }, { id: 'E1', axis: 'e' }], 'lr', 'ladder')
    expect(step(fixture, 'R1', 'down')).toBe('E1')
    expect(step(fixture, 'R0', 'down')).toBe('E0')
  })

  it('goes up to null at the top lane and back up from the lane below', () => {
    const fixture = build([{ id: 'R0', axis: 'r' }, { id: 'E0', axis: 'e' }], 'lr', 'ladder')
    expect(step(fixture, 'R0', 'up')).toBeNull()
    expect(step(fixture, 'E0', 'up')).toBe('R0')
  })

  it('goes down through a forked lane sub-row before the next lane', () => {
    const fixture = build([
      { id: 'R0', axis: 'r' }, { id: 'RA', axis: 'r', pre: ['R0'] }, { id: 'RB', axis: 'r', pre: ['R0'] },
      { id: 'E0', axis: 'e' }, { id: 'E1', axis: 'e', pre: ['E0'] },
    ], 'lr')
    const { geo } = fixture
    expect(geo.nodes.get('RB')!.y).toBeGreaterThan(geo.nodes.get('RA')!.y)
    expect(geo.nodes.get('RB')!.x).toBe(geo.nodes.get('RA')!.x)
    expect(step(fixture, 'RA', 'down')).toBe('RB')
    expect(step(fixture, 'RB', 'down')).toBe('E1')
    expect(step(fixture, 'RB', 'up')).toBe('RA')
  })
})

describe('arrow-key neighbour (td: lanes are columns, roles swap)', () => {
  it('goes down in the same lane even when another lane has a nearer card diagonally', () => {
    const fixture = build(DIAGONAL, 'td')
    const { geo } = fixture
    const along = (id: string) => geo.nodes.get(id)!.y - geo.nodes.get('R0')!.y
    expect(along('E1')).toBeLessThan(along('R1'))
    expect(step(fixture, 'R0', 'down')).toBe('R1')
    expect(step(fixture, 'R1', 'up')).toBe('R0')
  })

  it('goes right across lanes by pure spatial scoring', () => {
    const fixture = build([{ id: 'R0', axis: 'r' }, { id: 'R1', axis: 'r' }, { id: 'E0', axis: 'e' }, { id: 'E1', axis: 'e' }], 'td', 'ladder')
    expect(step(fixture, 'R1', 'right')).toBe('E1')
    expect(step(fixture, 'E0', 'right')).toBeNull()
    expect(step(fixture, 'E0', 'left')).toBe('R0')
  })
})

describe('along-lane arrow at the lane end (Codex I03)', () => {
  it('lr: Right from the last card of a lane is null even though another lane has a card further right', () => {
    const fixture = build(LANE_ENDS_EARLY, 'lr')
    const { geo } = fixture
    expect(geo.nodes.get('E3')!.x).toBeGreaterThan(geo.nodes.get('R2')!.x)
    expect(step(fixture, 'R2', 'right')).toBeNull()
    expect(step(fixture, 'R1', 'right')).toBe('R2')
  })

  it('td: Down from the last card of a lane is null even though another lane has a card further down', () => {
    const fixture = build(LANE_ENDS_EARLY, 'td')
    const { geo } = fixture
    expect(geo.nodes.get('E3')!.y).toBeGreaterThan(geo.nodes.get('R2')!.y)
    expect(step(fixture, 'R2', 'down')).toBeNull()
    expect(step(fixture, 'R1', 'down')).toBe('R2')
  })

  it('the arrow across lanes still reaches the other lane', () => {
    expect(step(build(LANE_ENDS_EARLY, 'lr', 'depth'), 'R2', 'down')).toBe('E2')
    expect(step(build(LANE_ENDS_EARLY, 'td', 'depth'), 'R2', 'right')).toBe('E2')
  })
})

describe('firstRung', () => {
  const parts: Parts = [{ id: 'R0', axis: 'r' }, { id: 'R1', axis: 'r', pre: ['R0'] }, { id: 'E0', axis: 'e' }, { id: 'E1', axis: 'e', pre: ['E0'] }]

  it('prefers a frontier rung, in reading order', () => {
    const { model, geo } = build(parts, 'lr')
    model.byId.get('E1')!.frontier = true
    expect(firstRung(model, geo)).toBe('E1')
    model.byId.get('R1')!.frontier = true
    expect(firstRung(model, geo)).toBe('R1')
  })

  it('falls back to the top-left card when nothing is frontier', () => {
    const { model, geo } = build(parts, 'lr')
    expect(firstRung(model, geo)).toBe('R0')
  })
})
