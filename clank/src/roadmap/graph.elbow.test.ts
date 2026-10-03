import { describe, expect, it } from 'vitest'
import { type Box, type Lens, type PlaceOptions, edgePath, layout, modelFromParts, place } from './graph'
import { ROADMAP_SETTINGS_SECTION, defaultRoadmapSettings, edgeStyle } from './settings'

// The "elbow lines" setting (Zach, Oct 3: "the feature to switch to elbow lines (it's a setting)"): orthogonal edges
// that run in the gutters and between card rows, so a line never crosses a card.
const AXES = [{ id: 'a', title: 'A' }, { id: 'b', title: 'B' }, { id: 'c', title: 'C' }]
const MODEL = modelFromParts(AXES, [
  // A0 needs C3 at the far end: a feedback edge that runs backwards along every lens.
  { id: 'A0', axis: 'a', pre: ['C3'] }, { id: 'A1', axis: 'a', pre: ['A0'] }, { id: 'A1b', axis: 'a', pre: ['A0'] },
  { id: 'A2', axis: 'a', pre: ['A1'] }, { id: 'A3', axis: 'a', pre: ['A2', 'A1b'] }, { id: 'A4', axis: 'a', pre: ['A3'] },
  { id: 'B0', axis: 'b' }, { id: 'B1', axis: 'b', pre: ['B0', 'A1'] }, { id: 'B1b', axis: 'b', pre: ['B0'] },
  { id: 'B2', axis: 'b', pre: ['B1'] }, { id: 'B3', axis: 'b', pre: ['A0', 'B2', 'B1b'] },
  { id: 'C0', axis: 'c', pre: ['A3'] }, { id: 'C1', axis: 'c', pre: ['B0'] }, { id: 'C2', axis: 'c', pre: ['C1', 'A0'] },
  { id: 'C3', axis: 'c', pre: ['C2', 'B3'] }, { id: 'C3b', axis: 'c', pre: ['C0', 'A1b'] },
])
const SIZES = {
  compact: { cellW: 56, cellH: 22, gapAcross: 12, gapWithin: 5, laneGap: 4, pad: 6 },
  rich: { cellW: 120, cellH: 88, gapAcross: 30, gapWithin: 8, laneGap: 4, pad: 6 },
}
const optionsFor = (orient: 'lr' | 'td', size: keyof typeof SIZES): PlaceOptions =>
  orient === 'lr' ? { orient, ...SIZES[size], label: 168, head: 24 } : { orient, ...SIZES[size], gapAcross: size === 'rich' ? 26 : 14, gapWithin: size === 'rich' ? 10 : 6, laneGap: 6, label: 58, head: 44 }

type Point = [number, number]
interface Piece { cmd: 'H' | 'V' | 'Q'; from: Point; to: Point; control?: Point }

/** Walks an absolute M/H/V/Q path into pieces; any other command (a diagonal L, a cubic C) throws. */
function pieces(path: string): { start: Point; pieces: Piece[] } {
  const commands = [...path.matchAll(/([A-Za-z])([^A-Za-z]*)/g)].map(([, cmd, args]) => ({ cmd, nums: args.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [] }))
  expect(commands[0].cmd).toBe('M')
  const start: Point = [commands[0].nums[0], commands[0].nums[1]]
  let at = start
  const out: Piece[] = []
  for (const { cmd, nums } of commands.slice(1)) {
    if (cmd === 'H') out.push({ cmd, from: at, to: (at = [nums[0], at[1]]) })
    else if (cmd === 'V') out.push({ cmd, from: at, to: (at = [at[0], nums[0]]) })
    else if (cmd === 'Q') out.push({ cmd, from: at, control: [nums[0], nums[1]], to: (at = [nums[2], nums[3]]) })
    else throw new Error(`non-orthogonal command ${cmd} in ${path}`)
  }
  return { start, pieces: out }
}

/** Every point of the path at half-pixel steps (corners sampled along their quadratic). */
function samples(path: string): Point[] {
  const walked = pieces(path)
  const points: Point[] = [walked.start]
  for (const piece of walked.pieces) {
    const steps = Math.max(2, Math.ceil(Math.hypot(piece.to[0] - piece.from[0], piece.to[1] - piece.from[1]) * 2))
    for (let i = 1; i <= steps; i += 1) {
      const t = i / steps
      if (piece.control) {
        const u = 1 - t
        points.push([u * u * piece.from[0] + 2 * u * t * piece.control[0] + t * t * piece.to[0], u * u * piece.from[1] + 2 * u * t * piece.control[1] + t * t * piece.to[1]])
      } else points.push([piece.from[0] + (piece.to[0] - piece.from[0]) * t, piece.from[1] + (piece.to[1] - piece.from[1]) * t])
    }
  }
  return points
}

const EPS = 1e-6
const strictlyInside = ([x, y]: Point, box: Box) => x > box.x + EPS && x < box.x + box.w - EPS && y > box.y + EPS && y < box.y + box.h - EPS

const LENSES: Lens[] = ['ladder', 'depth', 'board']
const CASES = LENSES.flatMap((lens) => (['lr', 'td'] as const).flatMap((orient) => (['compact', 'rich'] as const).map((size) => ({ lens, orient, size }))))

describe('elbow edges', () => {
  for (const { lens, orient, size } of CASES) {
    const name = `${lens} ${orient} ${size}`
    const geo = place(MODEL, layout(MODEL, lens), optionsFor(orient, size))
    const edges = MODEL.edges.filter((edge) => edge.kind !== 'same')

    it(`never passes through a card (${name})`, () => {
      expect(edges.length).toBeGreaterThan(15)
      for (const edge of edges) {
        const path = edgePath(geo, edge, 'elbow')
        for (const point of samples(path)) {
          for (const [id, box] of geo.nodes) expect(strictlyInside(point, box), `${edge.from}->${edge.to} enters ${id} at ${point}: ${path}`).toBe(false)
        }
      }
    })

    it(`is orthogonal, with only small rounded corners (${name})`, () => {
      for (const edge of edges) {
        const path = edgePath(geo, edge, 'elbow')
        for (const piece of pieces(path).pieces) {
          if (piece.cmd === 'H') expect(piece.to[1]).toBe(piece.from[1])
          if (piece.cmd === 'V') expect(piece.to[0]).toBe(piece.from[0])
          if (piece.cmd === 'Q') {
            // A corner turns exactly once: its control point is the corner of the box its two ends span, and it is small.
            const [cx, cy] = piece.control!
            const horizontalFirst = cy === piece.from[1] && cx === piece.to[0]
            const verticalFirst = cx === piece.from[0] && cy === piece.to[1]
            expect(horizontalFirst || verticalFirst, `${path}`).toBe(true)
            expect(Math.max(Math.abs(piece.to[0] - piece.from[0]), Math.abs(piece.to[1] - piece.from[1])), path).toBeLessThanOrEqual(6 + EPS)
          }
        }
      }
    })

    it(`leaves the source on its later edge and enters the target on its earlier edge, at their centres (${name})`, () => {
      for (const edge of edges) {
        const a = geo.nodes.get(edge.from)!, b = geo.nodes.get(edge.to)!
        const walked = pieces(edgePath(geo, edge, 'elbow'))
        const end = walked.pieces.at(-1)!.to
        if (orient === 'lr') {
          expect(walked.start, edge.from).toEqual([a.x + a.w, a.y + a.h / 2])
          expect(end, edge.to).toEqual([b.x, b.y + b.h / 2])
        } else {
          expect(walked.start, edge.from).toEqual([a.x + a.w / 2, a.y + a.h])
          expect(end, edge.to).toEqual([b.x + b.w / 2, b.y])
        }
      }
    })
  }

  it('routes a next-column edge through its one gutter in three segments', () => {
    const geo = place(MODEL, layout(MODEL, 'depth'), optionsFor('lr', 'compact'))
    const edge = MODEL.edges.find((e) => e.from === 'A0' && e.to === 'A1b')!
    const a = geo.nodes.get('A0')!, b = geo.nodes.get('A1b')!
    const gutter = a.x + a.w + 6
    expect(b.x - gutter).toBe(6)
    expect(edgePath(geo, edge, 'elbow')).toMatch(new RegExp(`^M${a.x + a.w} ${a.y + a.h / 2} H${a.x + a.w + 3}`))
    expect(pieces(edgePath(geo, edge, 'elbow')).pieces.filter((p) => p.cmd !== 'Q').map((p) => p.cmd)).toEqual(['H', 'V', 'H'])
  })

  it('keeps an alias on its short tie in both styles', () => {
    const m = modelFromParts(AXES.slice(0, 2), [{ id: 'R0', axis: 'a' }, { id: 'E0', axis: 'b', sameAs: 'R0' }])
    const geo = place(m, layout(m, 'ladder'), optionsFor('lr', 'compact'))
    expect(edgePath(geo, m.edges[0], 'elbow')).toBe(edgePath(geo, m.edges[0]))
  })

  it('keeps the curve exactly as it was', () => {
    const geo = place(MODEL, layout(MODEL, 'depth'), optionsFor('lr', 'compact'))
    const edge = MODEL.edges.find((e) => e.from === 'A0' && e.to === 'A1')!
    const a = geo.nodes.get('A0')!, b = geo.nodes.get('A1')!
    const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2
    expect(edgePath(geo, edge)).toBe(`M${x1} ${y1} C${x1 + 12} ${y1}, ${x2 - 12} ${y2}, ${x2} ${y2}`)
    expect(edgePath(geo, edge, 'curve')).toBe(edgePath(geo, edge))
  })

  it('defaults the setting to curved edges', () => {
    expect(defaultRoadmapSettings.edges).toBe('curve')
    expect(ROADMAP_SETTINGS_SECTION.items.find((item) => item.key === 'edges')?.default).toBe('curve')
    expect(edgeStyle({})).toBe('curve')
    expect(edgeStyle({ edges: 'elbow' })).toBe('elbow')
    expect(edgeStyle({ edges: 'diagonal' })).toBe('curve')
  })
})
