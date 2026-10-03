// The curriculum as a swimlane graph (Zach, Oct 3: "the swim lane view is the backbone"; Ladder, Depth,
// Now·Next·Later and Waves are lenses over the same lanes). Pure functions only: the view renders what these return.
//
// Edges come only from the bam-roadmap/1 document (docModel.ts): a rung's `depends_on` and its `alias_of`. Layering
// first drops feedback edges (Sugiyama step 1) so a cycle someone writes into the data is drawn and flagged, never hidden.
// Ported from the kinsim dashboard (clank-kinsim, src/roadmap/graph.ts @ 69e91af); only the input types changed.

import { blankRung, type RoadmapRung, type RungStatus } from './doc'

export type Lens = 'ladder' | 'depth' | 'board' | 'waves'
export type Orient = 'lr' | 'td'
export type Bucket = 'banked' | 'ready' | 'next' | 'later'

export interface RoadAxis {
  id: string
  title: string
}

export interface RoadRung {
  id: string
  axis: string
  title: string
  status: RungStatus | 'unknown'
  frontier: boolean
  /** The ids of the triage questions blocking this rung (the document's `blockers`). */
  triage: string[]
  wave: number | null
  est: number
  sameAs: string | null
  index: number
  /** The document's own rung: criteria, evidence, history and the rest the focus card reads. */
  rung: RoadmapRung
}

export interface RoadEdge {
  from: string
  to: string
  kind: 'pre' | 'same'
}

export interface RoadModel {
  axes: RoadAxis[]
  rungs: RoadRung[]
  edges: RoadEdge[]
  byId: Map<string, RoadRung>
  parents: Map<string, string[]>
  children: Map<string, string[]>
  up: Map<string, Set<string>>
  down: Map<string, Set<string>>
  feedback: Set<string>
  axisIndex: Map<string, number>
  hasWaves: boolean
}

const BANKED = new Set(['green', 'done'])
export const edgeKey = (edge: { from: string; to: string }) => `${edge.from}>${edge.to}`

/** The model from its parts: indexes, closures and the feedback edges. docModel.ts builds the parts from a document. */
export function finish(axes: RoadAxis[], rungs: RoadRung[], edges: RoadEdge[]): RoadModel {
  const byId = new Map(rungs.map((rung) => [rung.id, rung]))
  const axisIndex = new Map(axes.map((axis, i) => [axis.id, i]))
  const parents = new Map(rungs.map((rung) => [rung.id, [] as string[]]))
  const children = new Map(rungs.map((rung) => [rung.id, [] as string[]]))
  for (const edge of edges) {
    parents.get(edge.to)!.push(edge.from)
    children.get(edge.from)!.push(edge.to)
  }
  const closure = (start: string, next: Map<string, string[]>) => {
    const seen = new Set<string>()
    const stack = [...(next.get(start) ?? [])]
    while (stack.length) {
      const id = stack.pop()!
      if (seen.has(id) || id === start) continue
      seen.add(id)
      stack.push(...(next.get(id) ?? []))
    }
    return seen
  }
  return {
    axes,
    rungs,
    edges,
    byId,
    parents,
    children,
    up: new Map(rungs.map((rung) => [rung.id, closure(rung.id, parents)])),
    down: new Map(rungs.map((rung) => [rung.id, closure(rung.id, children)])),
    feedback: feedbackEdges(axes, rungs, edges, axisIndex),
    axisIndex,
    hasWaves: rungs.some((rung) => rung.wave != null),
  }
}

/** Test seam: a model from plain parts (axes, rungs with prerequisites, statuses), no roadmap document needed. */
export function modelFromParts(axes: RoadAxis[], parts: Array<{ id: string; axis: string; pre?: string[]; status?: RoadRung['status']; wave?: number | null; est?: number; sameAs?: string | null }>): RoadModel {
  const rungs: RoadRung[] = parts.map((part, index) => ({
    id: part.id, axis: part.axis, title: part.id, status: part.status ?? 'missing', frontier: false, triage: [],
    wave: part.wave ?? null, est: part.est ?? 0, sameAs: part.sameAs ?? null, index,
    rung: blankRung(part.id, part.axis, part.pre ?? []),
  }))
  const edges: RoadEdge[] = []
  for (const part of parts) {
    for (const parent of part.pre ?? []) edges.push({ from: parent, to: part.id, kind: 'pre' })
    if (part.sameAs) edges.push({ from: part.sameAs, to: part.id, kind: 'same' })
  }
  return finish(axes, rungs, edges)
}

// Kahn's algorithm; while a cycle remains, drop the edge (whose target reaches its source) with the latest source in
// authored order, so the break is deterministic and explainable.
function feedbackEdges(axes: RoadAxis[], rungs: RoadRung[], edges: RoadEdge[], axisIndex: Map<string, number>): Set<string> {
  const byId = new Map(rungs.map((rung) => [rung.id, rung]))
  const authored = (id: string) => (axisIndex.get(byId.get(id)!.axis) ?? 0) * 10000 + byId.get(id)!.index
  const feedback = new Set<string>()
  for (;;) {
    const live = edges.filter((edge) => !feedback.has(edgeKey(edge)))
    const indegree = new Map(rungs.map((rung) => [rung.id, 0]))
    for (const edge of live) indegree.set(edge.to, indegree.get(edge.to)! + 1)
    const queue = [...indegree].filter(([, d]) => d === 0).map(([id]) => id)
    const seen = new Set<string>()
    while (queue.length) {
      const id = queue.shift()!
      seen.add(id)
      for (const edge of live) {
        if (edge.from !== id) continue
        const d = indegree.get(edge.to)! - 1
        indegree.set(edge.to, d)
        if (d === 0) queue.push(edge.to)
      }
    }
    if (seen.size === rungs.length) return feedback
    const reaches = (from: string, goal: string) => {
      const stack = [from]
      const visited = new Set<string>()
      while (stack.length) {
        const id = stack.pop()!
        if (id === goal) return true
        if (visited.has(id)) continue
        visited.add(id)
        for (const edge of live) if (edge.from === id) stack.push(edge.to)
      }
      return false
    }
    const cyclic = live.filter((edge) => !seen.has(edge.from) && !seen.has(edge.to) && reaches(edge.to, edge.from))
    cyclic.sort((a, b) => authored(b.from) - authored(a.from) || authored(a.to) - authored(b.to))
    feedback.add(edgeKey(cyclic[0]))
  }
}

export const isBanked = (model: RoadModel, id: string) => BANKED.has(model.byId.get(id)?.status ?? '')

/**
 * Distance from climbable. Ready = every prerequisite banked AND no blocking triage; Next = one step away (one
 * promotion of a ready rung, or one triage answer); Later = further. An alias follows its target.
 * WHY no recursion (Codex A01): an unbanked prerequisite cycle made the recursive version overflow the stack and take
 * the whole board down; computed in two flat passes, a rung on a cycle simply lands in Later.
 * WHY triage counts (Codex A13): "Ready now" beside a panel that says "Blocked by triage T48" contradicted itself.
 */
export function buckets(model: RoadModel): Map<string, Bucket> {
  // Follow the alias chain to its target, noting whether any rung on the way (the alias itself included) is blocked.
  const target = (id: string) => {
    const seen = new Set<string>()
    let current = id
    let blocked = false
    while (model.byId.get(current)!.sameAs && !seen.has(current)) {
      seen.add(current)
      blocked ||= model.byId.get(current)!.triage.length > 0
      current = model.byId.get(current)!.sameAs!
    }
    return { end: current, blocked }
  }
  const unmet = (id: string) => (model.parents.get(id) ?? []).filter((p) => !isBanked(model, p))
  const own = new Map<string, Bucket>()
  for (const rung of model.rungs) {
    if (isBanked(model, rung.id)) own.set(rung.id, 'banked')
    else if (!unmet(rung.id).length && !rung.triage.length) own.set(rung.id, 'ready')
  }
  for (const rung of model.rungs) {
    if (own.has(rung.id)) continue
    const waiting = unmet(rung.id)
    const oneStep = waiting.length ? waiting.every((p) => own.get(p) === 'ready') && !rung.triage.length : true
    own.set(rung.id, oneStep ? 'next' : 'later')
  }
  // WHY (Codex B10): an alias inherits its target's bucket, but not a block the alias carries itself: a blocked alias
  // beside a ready target is one triage answer away (Next), the same as any other blocked rung.
  return new Map(model.rungs.map((rung) => {
    const { end, blocked } = target(rung.id)
    const placed = own.get(end)!
    return [rung.id, blocked && placed === 'ready' ? 'next' : placed]
  }))
}

export const bucket = (model: RoadModel, id: string): Bucket => buckets(model).get(id)!

export const BUCKETS: Array<{ id: Bucket; title: string; perRow: number }> = [
  { id: 'banked', title: 'Banked', perRow: 3 },
  { id: 'ready', title: 'Ready now', perRow: 2 },
  { id: 'next', title: 'Next', perRow: 2 },
  { id: 'later', title: 'Later', perRow: 3 },
]

/** x = longest prerequisite chain from a root (as soon as possible); an alias shares its target's column. */
export function depthColumns(model: RoadModel): Map<string, number> {
  const memo = new Map<string, number>()
  const col = (id: string): number => {
    const cached = memo.get(id)
    if (cached != null) return cached
    memo.set(id, 0)
    const rung = model.byId.get(id)!
    let c = 0
    if (rung.sameAs) c = col(rung.sameAs)
    else for (const edge of model.edges) if (edge.to === id && edge.kind === 'pre' && !model.feedback.has(edgeKey(edge))) c = Math.max(c, col(edge.from) + 1)
    memo.set(id, c)
    return c
  }
  model.rungs.forEach((rung) => col(rung.id))
  return memo
}

export interface Slot {
  gc: number
  gr: number
}
export interface Head {
  at: number
  span: number
  label: string
  bucket?: Bucket
}
export interface Layout {
  lens: Lens
  pos: Map<string, Slot>
  rows: Map<string, number>
  slots: number
  heads: Head[]
}

// A rung continues its same-axis parent's sub-row when that row is free, so a chain reads as one line and a fork
// opens a new row (the robots axis really is two ladders: UR5e and BAM FB).
function packRows(model: RoadModel, at: (id: string) => number) {
  const row = new Map<string, number>()
  const rows = new Map<string, number>()
  for (const axis of model.axes) {
    const members = model.rungs.filter((r) => r.axis === axis.id).map((r) => r.id).sort((a, b) => at(a) - at(b) || model.byId.get(a)!.index - model.byId.get(b)!.index)
    const lastEnd: number[] = []
    for (const id of members) {
      const start = at(id)
      let chosen = -1
      for (const parent of model.parents.get(id) ?? []) {
        if (!row.has(parent) || model.byId.get(parent)!.axis !== axis.id) continue
        if (lastEnd[row.get(parent)!] < start) {
          chosen = row.get(parent)!
          break
        }
      }
      if (chosen < 0) chosen = lastEnd.findIndex((end) => end < start)
      if (chosen < 0) {
        chosen = lastEnd.length
        lastEnd.push(-Infinity)
      }
      lastEnd[chosen] = start
      row.set(id, chosen)
    }
    rows.set(axis.id, Math.max(1, lastEnd.length))
  }
  return { row, rows }
}

export function layout(model: RoadModel, lens: Lens): Layout {
  const pos = new Map<string, Slot>()
  if (lens === 'ladder') {
    for (const axis of model.axes) model.rungs.filter((r) => r.axis === axis.id).forEach((r, i) => pos.set(r.id, { gc: i, gr: 0 }))
    const slots = Math.max(1, ...[...pos.values()].map((p) => p.gc + 1))
    return { lens, pos, rows: new Map(model.axes.map((a) => [a.id, 1])), slots, heads: Array.from({ length: slots }, (_, i) => ({ at: i, span: 1, label: i === 0 ? 'rung 0' : String(i) })) }
  }
  if (lens === 'board') {
    const rows = new Map<string, number>()
    const heads: Head[] = []
    let start = 0
    const placed = buckets(model)
    for (const b of BUCKETS) {
      const members = (axis: string) => model.rungs.filter((r) => r.axis === axis && placed.get(r.id) === b.id)
      const width = Math.max(1, Math.min(b.perRow, Math.max(...model.axes.map((a) => members(a.id).length))))
      for (const axis of model.axes) {
        const list = members(axis.id)
        list.forEach((r, i) => pos.set(r.id, { gc: start + (i % width), gr: Math.floor(i / width) }))
        rows.set(axis.id, Math.max(rows.get(axis.id) ?? 1, Math.ceil(list.length / width)))
      }
      heads.push({ at: start, span: width, label: `${b.title} · ${[...placed.values()].filter((v) => v === b.id).length}`, bucket: b.id })
      start += width
    }
    return { lens, pos, rows, slots: start, heads }
  }
  if (lens === 'waves' && model.hasWaves) {
    const maxWave = Math.max(...model.rungs.map((r) => r.wave ?? 0))
    const wave = (id: string) => model.byId.get(id)!.wave ?? maxWave + 1
    // WHY sub-columns inside a wave (Zach, Oct 3: "items that have sequential dependencies are on the same layer...
    // shouldn't each one be on its own layer?"): the plan often puts a rung and its prerequisite in one wave (EV1 and
    // EV2 in w3), and one column per wave drew them side by side as if parallel. Like an era band in a Civ tech tree,
    // a wave keeps its band but orders its rungs by dependency inside it, so every arrow points forward.
    const memo = new Map<string, number>()
    const sub = (id: string): number => {
      const cached = memo.get(id)
      if (cached != null) return cached
      memo.set(id, 0)
      const rung = model.byId.get(id)!
      let c = 0
      if (rung.sameAs && wave(rung.sameAs) === wave(id)) c = sub(rung.sameAs)
      else for (const edge of model.edges) {
        if (edge.to === id && edge.kind === 'pre' && !model.feedback.has(edgeKey(edge)) && wave(edge.from) === wave(id)) c = Math.max(c, sub(edge.from) + 1)
      }
      memo.set(id, c)
      return c
    }
    const widths = Array.from({ length: maxWave + 2 }, (_, w) => Math.max(1, ...model.rungs.filter((r) => wave(r.id) === w).map((r) => sub(r.id) + 1)))
    const starts = widths.map((_, w) => widths.slice(0, w).reduce((sum, width) => sum + width, 0))
    const at = (id: string) => starts[wave(id)] + sub(id)
    const { row, rows } = packRows(model, at)
    model.rungs.forEach((r) => pos.set(r.id, { gc: at(r.id), gr: row.get(r.id)! }))
    const heads = widths.map((span, w) => ({ at: starts[w], span, label: w === maxWave + 1 ? 'no wave' : `w${w}` }))
    return { lens, pos, rows, slots: starts[maxWave + 1] + widths[maxWave + 1], heads }
  }
  const col = depthColumns(model)
  const { row, rows } = packRows(model, (id) => col.get(id)!)
  model.rungs.forEach((r) => pos.set(r.id, { gc: col.get(r.id)!, gr: row.get(r.id)! }))
  const slots = Math.max(1, ...[...col.values()].map((c) => c + 1))
  return { lens: 'depth', pos, rows, slots, heads: Array.from({ length: slots }, (_, i) => ({ at: i, span: 1, label: i === 0 ? 'depth 0' : String(i) })) }
}

export interface Box {
  x: number
  y: number
  w: number
  h: number
}
export interface LaneBox {
  axis: RoadAxis
  start: number
  size: number
}
export interface Geometry {
  orient: Orient
  nodes: Map<string, Box>
  lanes: LaneBox[]
  /** The spacing `place` used, so an edge can route through the gutters and row gaps (elbow lines). */
  gaps: { across: number; within: number }
  heads: Array<Head & { a: number; len: number }>
  width: number
  height: number
}
export interface PlaceOptions {
  orient: Orient
  cellW: number
  cellH: number
  gapAcross: number
  gapWithin: number
  laneGap: number
  label: number
  head: number
  pad: number
}

/** Grid units to pixels. LR: lanes are rows and slots run left to right. TD: lanes are columns, slots run down. */
export function place(model: RoadModel, lay: Layout, o: PlaceOptions): Geometry {
  const lr = o.orient === 'lr'
  const across = (lr ? o.cellW : o.cellH) + o.gapAcross
  const within = (lr ? o.cellH : o.cellW) + o.gapWithin
  const lanes: LaneBox[] = []
  let cursor = lr ? o.head : o.label
  for (const axis of model.axes) {
    const n = lay.rows.get(axis.id) ?? 1
    const size = n * within - o.gapWithin + o.pad * 2
    lanes.push({ axis, start: cursor, size })
    cursor += size + o.laneGap
  }
  const laneOf = new Map(lanes.map((lane) => [lane.axis.id, lane]))
  const origin = lr ? o.label : o.head
  const nodes = new Map<string, Box>()
  for (const [id, slot] of lay.pos) {
    const lane = laneOf.get(model.byId.get(id)!.axis)!
    const a = origin + slot.gc * across
    const w = lane.start + o.pad + slot.gr * within
    nodes.set(id, lr ? { x: a, y: w, w: o.cellW, h: o.cellH } : { x: w, y: a, w: o.cellW, h: o.cellH })
  }
  const extentA = origin + lay.slots * across
  const extentW = cursor - o.laneGap
  return {
    orient: o.orient,
    nodes,
    lanes,
    gaps: { across: o.gapAcross, within: o.gapWithin },
    heads: lay.heads.map((h) => ({ ...h, a: origin + h.at * across, len: h.span * across - o.gapAcross })),
    width: (lr ? extentA : extentW) + 6,
    height: (lr ? extentW : extentA) + 6,
  }
}

export type Direction = 'left' | 'right' | 'up' | 'down'

// WHY lane preference (Zach, Oct 3: "arrow keys between rungs: the selection moves and the view follows"): a lane is
// a track of work, so the arrow that runs ALONG lanes (← → in the ↔ orientation, ↑ ↓ in ↓) stays in the lane and
// walks its rungs in order, even when another lane has a card diagonally nearer, and at the lane's end it stops (null)
// rather than hopping into another lane (Codex I03: Right from OB5 landed on RB6). The arrow that runs ACROSS lanes is
// pure spatial scoring, which steps through a forked lane's sub-rows before reaching the next lane.
/** The card an arrow key moves to from `from`, or null at an edge. Distance ahead plus twice the sideways offset. */
export function neighbour(model: RoadModel, geo: Geometry, from: string, dir: Direction): string | null {
  const origin = geo.nodes.get(from)
  const source = model.byId.get(from)
  if (!origin || !source) return null
  const centre = (box: Box) => ({ x: box.x + box.w / 2, y: box.y + box.h / 2 })
  const here = centre(origin)
  const candidates: Array<{ id: string; score: number; across: number }> = []
  for (const [id, box] of geo.nodes) {
    if (id === from) continue
    const there = centre(box)
    const dx = there.x - here.x
    const dy = there.y - here.y
    const along = dir === 'right' ? dx : dir === 'left' ? -dx : dir === 'down' ? dy : -dy
    if (along <= 0.5) continue
    const across = Math.abs(dir === 'left' || dir === 'right' ? dy : dx)
    candidates.push({ id, score: along + 2 * across, across })
  }
  const best = (list: typeof candidates) => list.sort((a, b) => a.score - b.score || a.across - b.across || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))[0]?.id ?? null
  const alongLane = geo.orient === 'lr' ? dir === 'left' || dir === 'right' : dir === 'up' || dir === 'down'
  if (alongLane) {
    return best(candidates.filter((c) => model.byId.get(c.id)?.axis === source.axis))
  }
  return best(candidates)
}

/** Where the first arrow key lands with nothing selected: the first frontier rung in reading order, else the top-left card. */
export function firstRung(model: RoadModel, geo: Geometry): string | null {
  const reading = [...geo.nodes].sort(([a, p], [b, q]) => p.y - q.y || p.x - q.x || (a < b ? -1 : a > b ? 1 : 0))
  return (reading.find(([id]) => model.byId.get(id)?.frontier) ?? reading[0])?.[0] ?? null
}

const ELBOW_RADIUS = 6

/**
 * An orthogonal route that never crosses a card. It leaves the source's later edge, runs in the gutter between
 * columns, and (unless the target is in the next column) crosses over in the gap between card rows beside the target,
 * then enters the target's earlier edge. WHY the channel is beside the target and not the source: the last stretch is
 * what the eye follows into the card, so it reads as arriving from the row it belongs to. A backward or feedback edge
 * takes the same five segments, just with the channel run leftwards. Written in (u, v): u along the flow, v across it,
 * so top-down is the same route with the axes swapped.
 */
function elbowPath(geo: Geometry, a: Box, b: Box): string {
  const lr = geo.orient === 'lr'
  const along = (box: Box) => (lr ? { lo: box.x, len: box.w } : { lo: box.y, len: box.h })
  const across = (box: Box) => (lr ? { lo: box.y, len: box.h } : { lo: box.x, len: box.w })
  const u1 = along(a).lo + along(a).len, v1 = across(a).lo + across(a).len / 2
  const u2 = along(b).lo, v2 = across(b).lo + across(b).len / 2
  const g1 = u1 + geo.gaps.across / 2, g2 = u2 - geo.gaps.across / 2
  let route: Array<[number, number]>
  if (Math.abs(g1 - g2) < 1e-6) route = [[u1, v1], [g1, v1], [g1, v2], [u2, v2]]
  else {
    // The row gaps are uniform, so a line half a gap above or below the target's row clears every card in the lane.
    const above = across(b).lo - geo.gaps.within / 2, below = across(b).lo + across(b).len + geo.gaps.within / 2
    const vc = Math.abs(above - v1) <= Math.abs(below - v1) ? above : below
    route = [[u1, v1], [g1, v1], [g1, vc], [g2, vc], [g2, v2], [u2, v2]]
  }
  // Drop repeated and collinear points (a target on the source's row has no jog), then round each corner.
  const points = route.filter((p, i) => {
    if (i === 0 || i === route.length - 1) return i === 0 || p[0] !== route[i - 1][0] || p[1] !== route[i - 1][1]
    const q = route[i - 1], n = route[i + 1]
    return !((p[0] === q[0] && p[0] === n[0]) || (p[1] === q[1] && p[1] === n[1]))
  })
  const xy = ([u, v]: [number, number]): [number, number] => (lr ? [u, v] : [v, u])
  const line = (from: [number, number], to: [number, number]) => (from[1] === to[1] ? `H${to[0]}` : `V${to[1]}`)
  let at = xy(points[0])
  let d = `M${at[0]} ${at[1]}`
  for (let i = 1; i < points.length - 1; i += 1) {
    const prev = points[i - 1], corner = points[i], next = points[i + 1]
    const inLen = Math.abs(corner[0] - prev[0]) + Math.abs(corner[1] - prev[1]), outLen = Math.abs(next[0] - corner[0]) + Math.abs(next[1] - corner[1])
    // Clamped to half of each neighbouring segment, so two corners never overshoot into each other.
    const r = Math.min(ELBOW_RADIUS, inLen / 2, outLen / 2)
    const before = xy([corner[0] - Math.sign(corner[0] - prev[0]) * r, corner[1] - Math.sign(corner[1] - prev[1]) * r])
    const after = xy([corner[0] + Math.sign(next[0] - corner[0]) * r, corner[1] + Math.sign(next[1] - corner[1]) * r])
    const c = xy(corner)
    if (before[0] !== at[0] || before[1] !== at[1]) d += ` ${line(at, before)}`
    d += ` Q${c[0]} ${c[1]} ${after[0]} ${after[1]}`
    at = after
  }
  const last = xy(points[points.length - 1])
  return `${d} ${line(at, last)}`
}

/** An edge as a smooth curve (or, as `elbow`, orthogonal lines) from the later side of its source to the earlier side of its target. */
export function edgePath(geo: Geometry, edge: RoadEdge, style: 'curve' | 'elbow' = 'curve'): string {
  const a = geo.nodes.get(edge.from)!
  const b = geo.nodes.get(edge.to)!
  if (edge.kind === 'same') {
    const lr = geo.orient === 'lr'
    // An alias in its target's slot: a short dashed tie in the gutter, never across other cards. Only when the slots
    // really match (Ladder and Now·Next·Later place an alias in any column); else a curve between both boxes (Codex B11).
    if (lr ? a.x === b.x : a.y === b.y) return lr ? `M${a.x - 4} ${a.y + a.h / 2} V${b.y + b.h / 2}` : `M${a.x + a.w / 2} ${a.y - 4} H${b.x + b.w / 2}`
    if (lr) {
      const right = b.x > a.x
      const x1 = right ? a.x + a.w : a.x, x2 = right ? b.x : b.x + b.w, y1 = a.y + a.h / 2, y2 = b.y + b.h / 2
      const d = Math.max(12, Math.min(48, Math.abs(x2 - x1) / 2)) * (right ? 1 : -1)
      return `M${x1} ${y1} C${x1 + d} ${y1}, ${x2 - d} ${y2}, ${x2} ${y2}`
    }
    const down = b.y > a.y
    const x1 = a.x + a.w / 2, x2 = b.x + b.w / 2, y1 = down ? a.y + a.h : a.y, y2 = down ? b.y : b.y + b.h
    const d = Math.max(12, Math.min(48, Math.abs(y2 - y1) / 2)) * (down ? 1 : -1)
    return `M${x1} ${y1} C${x1} ${y1 + d}, ${x2} ${y2 - d}, ${x2} ${y2}`
  }
  if (style === 'elbow') return elbowPath(geo, a, b)
  if (geo.orient === 'lr') {
    const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2
    const d = Math.max(12, Math.min(48, Math.abs(x2 - x1) / 2))
    return `M${x1} ${y1} C${x1 + d} ${y1}, ${x2 - d} ${y2}, ${x2} ${y2}`
  }
  const x1 = a.x + a.w / 2, y1 = a.y + a.h, x2 = b.x + b.w / 2, y2 = b.y
  const d = Math.max(12, Math.min(48, Math.abs(y2 - y1) / 2))
  return `M${x1} ${y1} C${x1} ${y1 + d}, ${x2} ${y2 - d}, ${x2} ${y2}`
}

/** Longest chain of est_waves over rungs not yet banked (a partial rung counts in full; an alias weighs 0). */
export function criticalPath(model: RoadModel, goal: string): { total: number; path: string[] } {
  const memo = new Map<string, { d: number; via: string | null }>()
  const weight = (id: string) => {
    const rung = model.byId.get(id)!
    return isBanked(model, id) || rung.sameAs ? 0 : rung.est
  }
  const dist = (id: string): { d: number; via: string | null } => {
    const cached = memo.get(id)
    if (cached) return cached
    memo.set(id, { d: 0, via: null })
    let best = 0
    let via: string | null = null
    for (const edge of model.edges) {
      if (edge.to !== id || model.feedback.has(edgeKey(edge))) continue
      const d = dist(edge.from).d
      if (d > best) {
        best = d
        via = edge.from
      }
    }
    const value = { d: best + weight(id), via }
    memo.set(id, value)
    return value
  }
  const path: string[] = []
  for (let id: string | null = goal; id; id = dist(id).via) path.unshift(id)
  return { total: dist(goal).d, path: path.filter((id) => weight(id) > 0 || id === goal) }
}
