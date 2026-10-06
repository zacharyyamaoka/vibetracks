// The calm answer: what the roadmap says at a glance, nearly alone (Zach's rule, feedback_calm_ui_progressive_
// disclosure: "the glance answers 'is everything OK, and what needs me?'"). Pure, so its numbers are tested.
// It leads with where the loop IS (the rungs it climbs now), then what those unlock, then how much is banked: Zach, on
// the track page, "I want to see ... the roadmap for what is next and what is the current rung".
//
// WHY "proven" is green + done and claimed is counted apart: both green and done rest on recorded evidence; claimed is
// the loop's green that its evidence does not prove, which is exactly what this format exists to show.
// WHY "current" is the summary's frontier in its own order: it is the loop's word for what it climbs; the rungs'
// frontier flags and then the `where` rows are only the fallbacks. WHY "next" is derived (unbanked dependents of the
// current rungs) and not read: the document states no "next up" list, and the dependency edges are what it does state.
// WHY "needs you" counts only blockers on the current rungs: a triage question that holds up a later rung is not what
// needs Zach today, and the full board shows every one of them a click deeper.

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
  /** The loop's wave and phase, when it reports them. */
  wave: number | null
  phase: string | null
  /** The rungs the loop is climbing now, in its order. */
  current: string[]
  /** What the current rungs unlock: unbanked dependents that are not current themselves, in rung order. */
  next: string[]
  needs: CalmNeed[]
  lanes: CalmLane[]
}

const PROVEN = new Set(['green', 'done'])

/** One row of the document's `where` list (the loop's own place per lane); the widget's RoadmapDoc type does not carry it. */
interface WhereRow {
  here_claimed?: string | null
  next?: string | null
}

const whereRows = (doc: RoadmapDoc): WhereRow[] => {
  const rows = (doc as { where?: unknown }).where
  return Array.isArray(rows) ? rows.filter((row): row is WhereRow => Boolean(row) && typeof row === 'object') : []
}

export function calmSummary(doc: RoadmapDoc): CalmSummary {
  const rungs = doc.rungs
  const byId = new Map(rungs.map((rung) => [rung.id, rung]))
  const stated = (doc.summary?.frontier ?? []).filter((id) => byId.has(id))
  const flagged = rungs.filter((rung) => rung.frontier).map((rung) => rung.id)
  // WHY the `where` rows are the last resort: they name each lane's place, not what the loop climbs, so a lane with
  // nothing left to climb (every rung proven) must not show up as current.
  const placed = [...new Set(whereRows(doc).map((row) => row.next ?? row.here_claimed).filter((id): id is string => Boolean(id) && byId.has(id!) && !PROVEN.has(byId.get(id!)!.status)))]
  const current = stated.length ? stated : flagged.length ? flagged : placed
  const climbing = new Set(current)
  // WHY every prerequisite must be climbing or proven, not just one: "next" is what opens when today's climb finishes.
  // A rung that also waits on something nobody is climbing (RB4 on MR1) is not next, it is later.
  const ready = (parent: string) => climbing.has(parent) || PROVEN.has(byId.get(parent)?.status ?? '')
  const next = rungs
    .filter((rung) => !PROVEN.has(rung.status) && !climbing.has(rung.id) && (rung.depends_on ?? []).some((parent) => climbing.has(parent))
      && (rung.depends_on ?? []).every(ready))
    .map((rung) => rung.id)
  const needs: CalmNeed[] = []
  for (const id of current) {
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
    wave: typeof doc.summary?.wave === 'number' ? doc.summary.wave : null,
    phase: doc.summary?.phase || null,
    current,
    next,
    needs,
    lanes,
  }
}

/** How many of a list the sentence names before it says "+N". */
export const SHOWN = { current: 2, next: 2, needs: 1 }

export const more = (n: number) => (n > 0 ? ` +${n}` : '')

/** The loop's raw phase token when the calm head names one ("between_waves"); null for no phase or the default "running". */
export function phaseToken(summary: Pick<CalmSummary, 'phase'>): string | null {
  return summary.phase && summary.phase !== 'running' ? summary.phase : null
}

/** "Wave 4", "Wave 4, paused", "Wave 4, between waves", "Paused", or null. WHY "running" is not said: it is the default,
 * and calm says only exceptions. WHY the phase is words (the dashboard's own header says "Between waves" for the same
 * state): the token is the loop's file spelling. The head's title keeps the raw token (phaseToken), so no characters
 * are hidden without a way to see them. */
export function stageLabel(summary: Pick<CalmSummary, 'wave' | 'phase'>): string | null {
  const token = phaseToken(summary)
  const phase = token === null ? null : token.replace(/_/g, ' ')
  if (summary.wave !== null) return phase ? `Wave ${summary.wave}, ${phase}` : `Wave ${summary.wave}`
  return phase ? phase.charAt(0).toUpperCase() + phase.slice(1) : null
}

/** The answer as one line: "Wave 4 · climbing SN1, BT1 +6 · next RB2, OB2 +5 · 4 of 62 proven · 12 claimed · needs you: T48 (blocks SN1) +1". */
export function calmSentence(summary: CalmSummary): string {
  const parts: string[] = []
  const stage = stageLabel(summary)
  if (stage) parts.push(stage)
  if (summary.current.length) parts.push(`climbing ${summary.current.slice(0, SHOWN.current).join(', ')}${more(summary.current.length - SHOWN.current)}`)
  if (summary.next.length) parts.push(`next ${summary.next.slice(0, SHOWN.next).join(', ')}${more(summary.next.length - SHOWN.next)}`)
  parts.push(`${summary.proven} of ${summary.total} proven`)
  if (summary.claimed) parts.push(`${summary.claimed} claimed`)
  if (summary.stale) parts.push(`${summary.stale} stale`)
  if (summary.needs.length) {
    const shown = summary.needs.slice(0, SHOWN.needs).map((need) => `${need.id} (blocks ${need.blocks.join(', ')})`)
    parts.push(`needs you: ${shown.join(', ')}${more(summary.needs.length - SHOWN.needs)}`)
  }
  return parts.join(' · ')
}
