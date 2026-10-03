import { describe, expect, it } from 'vitest'
import { bucket, buckets, criticalPath, depthColumns, edgeKey, layout, modelFromParts, place } from './graph'

// The graph half of the kinsim dashboard's roadmap.test.ts (@ 69e91af). Its proof, citation and status-fold halves
// retired with proof.ts: the bam-roadmap/1 document carries proof as typed fields (docModel.test.ts).

const AXES = [{ id: 'r', title: 'Robots' }, { id: 'e', title: 'Eval' }]

describe('graph', () => {
  // E0 → E1 → R0; R0 forks into R1 and R3 (the robots axis is really two ladders); R2 continues R1.
  const model = () => modelFromParts(AXES, [
    { id: 'R0', axis: 'r', pre: ['E1'], status: 'green' },
    { id: 'R1', axis: 'r', pre: ['R0'], status: 'partial', est: 1 },
    { id: 'R2', axis: 'r', pre: ['R1'], est: 2 },
    { id: 'R3', axis: 'r', pre: ['R0'], est: 2 },
    { id: 'E0', axis: 'e', status: 'done' },
    { id: 'E1', axis: 'e', pre: ['E0'], status: 'green' },
  ])

  it('puts each rung at its longest prerequisite chain and forks onto a second sub-row', () => {
    const m = model()
    const col = depthColumns(m)
    expect(Object.fromEntries(col)).toEqual({ R0: 2, R1: 3, R2: 4, R3: 3, E0: 0, E1: 1 })
    const lay = layout(m, 'depth')
    expect(lay.pos.get('R1')).toEqual({ gc: 3, gr: 0 })
    expect(lay.pos.get('R3')).toEqual({ gc: 3, gr: 1 }) // RB3 beside RB1, not after RB2
    expect(lay.pos.get('R2')).toEqual({ gc: 4, gr: 0 }) // continues R1's row
    expect(lay.rows.get('r')).toBe(2)
  })

  it('keeps the authored order in the ladder lens', () => {
    const lay = layout(model(), 'ladder')
    expect(['R0', 'R1', 'R2', 'R3'].map((id) => lay.pos.get(id)!.gc)).toEqual([0, 1, 2, 3])
  })

  it('buckets by distance from climbable', () => {
    const m = model()
    expect(['R0', 'R1', 'R2', 'R3', 'E0'].map((id) => bucket(m, id))).toEqual(['banked', 'ready', 'next', 'ready', 'banked'])
    const board = layout(m, 'board')
    expect(board.heads.map((h) => h.label)).toEqual(['Banked · 3', 'Ready now · 2', 'Next · 1', 'Later · 0'])
  })

  it('puts an alias in its target column and follows its target into the board', () => {
    const m = modelFromParts(AXES, [{ id: 'R0', axis: 'r', status: 'green' }, { id: 'E0', axis: 'e', sameAs: 'R0', status: 'green' }])
    expect(depthColumns(m).get('E0')).toBe(depthColumns(m).get('R0'))
    expect(m.edges).toContainEqual({ from: 'R0', to: 'E0', kind: 'same' })
  })

  it('breaks a cycle at one edge, deterministically, and leaves rungs merely downstream of it alone', () => {
    const m = modelFromParts(AXES, [
      { id: 'R0', axis: 'r', pre: ['E1'] },
      { id: 'R1', axis: 'r', pre: ['R0'] },
      { id: 'E1', axis: 'e', pre: ['R0'] }, // R0 → E1 → R0: a cycle
    ])
    expect([...m.feedback]).toEqual([edgeKey({ from: 'E1', to: 'R0' })]) // the source latest in authored order
    expect(depthColumns(m).get('R1')).toBe(1)
  })

  it('falls back to depth when the curriculum has no waves', () => {
    expect(layout(model(), 'waves').lens).toBe('depth')
  })

  it('sums est waves of unbanked rungs along the longest chain', () => {
    expect(criticalPath(model(), 'R2')).toEqual({ total: 3, path: ['R1', 'R2'] })
    expect(criticalPath(model(), 'R0')).toEqual({ total: 0, path: ['R0'] })
  })

  it('swaps the axes between left-to-right and top-down', () => {
    const m = model()
    const lay = layout(m, 'depth')
    const options = { cellW: 50, cellH: 20, gapAcross: 10, gapWithin: 4, laneGap: 2, label: 100, head: 20, pad: 5 }
    const lr = place(m, lay, { orient: 'lr', ...options })
    const td = place(m, lay, { orient: 'td', ...options })
    expect(lr.nodes.get('R1')!.x).toBeGreaterThan(lr.nodes.get('R0')!.x)
    expect(td.nodes.get('R1')!.y).toBeGreaterThan(td.nodes.get('R0')!.y)
    expect(td.nodes.get('R1')!.x).toBe(td.nodes.get('R0')!.x)
  })

  // Codex A01: an unbanked prerequisite cycle used to overflow the stack and take the whole board down.
  it('buckets a cycle without recursing forever, and lays it out flagged', () => {
    const m = modelFromParts(AXES, [{ id: 'R0', axis: 'r', pre: ['E1'] }, { id: 'E1', axis: 'e', pre: ['R0'] }])
    expect(Object.fromEntries(buckets(m))).toEqual({ R0: 'later', E1: 'later' })
    expect(() => layout(m, 'board')).not.toThrow()
    expect(m.feedback.size).toBe(1)
  })

  // Codex A14: the board must honour each bucket's columns, not stack every card in one.
  it('spreads a full bucket over its columns', () => {
    const m = modelFromParts(AXES, [{ id: 'B0', axis: 'r', status: 'green' }, { id: 'B1', axis: 'r', status: 'green' }, { id: 'B2', axis: 'r', status: 'green' }, { id: 'B3', axis: 'r', status: 'green' }])
    const lay = layout(m, 'board')
    expect(['B0', 'B1', 'B2', 'B3'].map((id) => lay.pos.get(id))).toEqual([{ gc: 0, gr: 0 }, { gc: 1, gr: 0 }, { gc: 2, gr: 0 }, { gc: 0, gr: 1 }])
  })
})
