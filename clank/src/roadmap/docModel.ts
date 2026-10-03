// A bam-roadmap/1 document (doc.ts) to graph.ts's RoadModel: lanes from `axes`, cards from `rungs`, prerequisite edges
// from each rung's `depends_on`, alias ties from `alias_of`. Pure; graph.ts keeps its own types and this file adapts.
//
// WHY depends_on and alias_of only, not the document's whole `edges` list: those two are the rung's own word and the
// same relation the kinsim board drew (`prerequisites`, `gate.kind == same_as`). A `package` edge (rig: "R2 needs R1")
// is derived from work packages and can run both ways between two rungs, so it is not drawn.

import { ROADMAP_SCHEMA, RUNG_STATUSES, type RoadmapDoc, type RoadmapRung } from './doc'
import { type RoadAxis, type RoadEdge, type RoadModel, type RoadRung, finish } from './graph'

/** A document the widget cannot read: a foreign schema, or a shape the board cannot lay out. */
export class RoadmapDocError extends Error {}

const isObject = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value)

/** The document, once it is a bam-roadmap/1 object with rung and axis lists. Throws RoadmapDocError otherwise. The
 * schema's other rules are the projector's (`python -m bam_roadmap validate`), not re-checked here. */
export function parseRoadmapDoc(value: unknown): RoadmapDoc {
  if (!isObject(value) || value.schema !== ROADMAP_SCHEMA) {
    const schema = isObject(value) ? value.schema : undefined
    throw new RoadmapDocError(`not a ${ROADMAP_SCHEMA} document (schema ${JSON.stringify(schema ?? null)})`)
  }
  for (const key of ['axes', 'rungs'] as const) {
    if (!Array.isArray(value[key])) throw new RoadmapDocError(`the ${ROADMAP_SCHEMA} document has no ${key} list`)
  }
  return value as unknown as RoadmapDoc
}

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)
const statusOf = (rung: RoadmapRung): RoadRung['status'] => ((RUNG_STATUSES as readonly string[]).includes(rung.status) ? rung.status : 'unknown')

export function modelFromDoc(doc: RoadmapDoc): RoadModel {
  const axes: RoadAxis[] = [...doc.axes].sort((a, b) => a.order - b.order).map((axis) => ({ id: axis.id, title: axis.title }))
  const lane = new Map(axes.map((axis, i) => [axis.id, i]))
  for (const rung of doc.rungs) {
    if (!lane.has(rung.axis)) throw new RoadmapDocError(`rung ${rung.id} is on axis ${JSON.stringify(rung.axis)}, which the document does not declare`)
  }
  // Lane by lane in authored order (`order`), so the Ladder lens reads as the loop wrote it whatever the list order.
  const ordered = doc.rungs
    .map((rung, at) => ({ rung, at }))
    .sort((a, b) => lane.get(a.rung.axis)! - lane.get(b.rung.axis)! || a.rung.order - b.rung.order || a.at - b.at)
    .map(({ rung }) => rung)
  const known = new Set(ordered.map((rung) => rung.id))
  const rungs: RoadRung[] = ordered.map((rung, index) => ({
    id: rung.id,
    axis: rung.axis,
    title: rung.title,
    status: statusOf(rung),
    frontier: rung.frontier === true,
    triage: (rung.blockers ?? []).map((blocker) => blocker.id),
    wave: num(rung.wave),
    // est_waves is kinsim's plan (x is the loop's own extension); a loop without it weighs every rung 0.
    est: num(rung.x?.est_waves) ?? 0,
    sameAs: rung.alias_of && known.has(rung.alias_of) ? rung.alias_of : null,
    index,
    rung,
  }))
  const edges: RoadEdge[] = []
  for (const rung of rungs) {
    for (const parent of rung.rung.depends_on ?? []) if (known.has(parent)) edges.push({ from: parent, to: rung.id, kind: 'pre' })
    if (rung.sameAs) edges.push({ from: rung.sameAs, to: rung.id, kind: 'same' })
  }
  return finish(axes, rungs, edges)
}

/** The short line under a rich card: the status, and how many of its criteria are met. */
export function cardLine(rung: RoadRung): string {
  const criteria = rung.rung.criteria ?? []
  if (!criteria.length) return rung.status
  return `${rung.status} · ${criteria.filter((criterion) => criterion.verdict === 'met').length}/${criteria.length} met`
}
