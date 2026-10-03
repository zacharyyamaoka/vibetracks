// The calm answer: what the collapsed Roadmap section says, nearly alone (Zach's rule, feedback_calm_ui_progressive_
// disclosure: "the glance answers 'is everything OK, and what needs me?'"). Pure, so its numbers are tested.
//
// WHY "proven" is green + done and claimed is counted apart: both green and done rest on recorded evidence; claimed is
// the loop's green that its evidence does not prove, which is exactly what this format exists to show.
// WHY "next" is the summary's frontier in its own order: it is the loop's word for what it climbs next; the rungs'
// frontier flags are only the fallback. WHY "needs you" counts only blockers on the frontier: a triage question that
// holds up a later rung is not what needs Zach today, and the full board shows every one of them a click deeper.

import type { RoadmapDoc } from './doc'

export interface CalmLane {
  axis: string
  title: string
  total: number
  proven: number
  claimed: number
}

export interface CalmNeed {
  /** The triage question's id (T48). */
  id: string
  title: string
  /** The frontier rungs it blocks, in frontier order. */
  blocks: string[]
}

export interface CalmSummary {
  total: number
  proven: number
  claimed: number
  stale: number
  next: string[]
  needs: CalmNeed[]
  lanes: CalmLane[]
}

const PROVEN = new Set(['green', 'done'])

export function calmSummary(doc: RoadmapDoc): CalmSummary {
  const rungs = doc.rungs
  const byId = new Map(rungs.map((rung) => [rung.id, rung]))
  const stated = (doc.summary?.frontier ?? []).filter((id) => byId.has(id))
  const next = stated.length ? stated : rungs.filter((rung) => rung.frontier).map((rung) => rung.id)
  const needs: CalmNeed[] = []
  for (const id of next) {
    for (const blocker of byId.get(id)!.blockers ?? []) {
      const known = needs.find((need) => need.id === blocker.id)
      if (known) {
        if (!known.blocks.includes(id)) known.blocks.push(id)
      } else needs.push({ id: blocker.id, title: blocker.title, blocks: [id] })
    }
  }
  const lanes = [...doc.axes].sort((a, b) => a.order - b.order).map((axis) => {
    const members = rungs.filter((rung) => rung.axis === axis.id)
    return {
      axis: axis.id,
      title: axis.title,
      total: members.length,
      proven: members.filter((rung) => PROVEN.has(rung.status)).length,
      claimed: members.filter((rung) => rung.status === 'claimed').length,
    }
  })
  return {
    total: rungs.length,
    proven: rungs.filter((rung) => PROVEN.has(rung.status)).length,
    claimed: rungs.filter((rung) => rung.status === 'claimed').length,
    stale: rungs.filter((rung) => rung.status === 'stale').length,
    next,
    needs,
    lanes,
  }
}

/** How many of a list the sentence names before it says "+N". */
export const SHOWN = { next: 2, needs: 1 }

const more = (n: number) => (n > 0 ? ` +${n}` : '')

/** The answer as one line: "4 of 62 proven · 12 claimed · next: SN1, BT1 +6 · needs you: T48 (blocks SN1) +1". */
export function calmSentence(summary: CalmSummary): string {
  const parts = [`${summary.proven} of ${summary.total} proven`, `${summary.claimed} claimed`]
  if (summary.stale) parts.push(`${summary.stale} stale`)
  if (summary.next.length) parts.push(`next: ${summary.next.slice(0, SHOWN.next).join(', ')}${more(summary.next.length - SHOWN.next)}`)
  if (summary.needs.length) {
    const shown = summary.needs.slice(0, SHOWN.needs).map((need) => `${need.id} (blocks ${need.blocks.join(', ')})`)
    parts.push(`needs you: ${shown.join(', ')}${more(summary.needs.length - SHOWN.needs)}`)
  }
  return parts.join(' · ')
}
