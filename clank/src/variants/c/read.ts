// How Variant C reads one KPI into words: the headline number, its change, and the route helpers the panes share.
// Every number goes through the shared model (formatValue, deltaVsBaseline, describeDelta), so wording matches A and B.

import type { Delta, EvidenceItem, Kpi, KpiValue, Projection, Route, Track } from '../../shared'
import {
  allEvidence,
  childrenOf,
  deltaVsBaseline,
  deltaVsPrevious,
  formatKpiValue,
  formatValue,
  iterationById,
  latestValue,
  topLevelTracks,
} from '../../shared'

export interface Headline {
  /** The value the headline reads (a synthetic one carrying the aggregate's n for a deployment). */
  value: KpiValue | null
  text: string
  /** What the number is: "W3", "day 07-29 median · n 57", "all days". */
  label: string
  aggregate: boolean
}

/** The KPI's honest headline. WHY the aggregate first: for a deployment the latest single session mixes trajectories,
 * while the adapter's day summary pools every run of that day (task brief: "use kpi.aggregate where the day summary
 * is the honest headline"). Loops have no aggregate and read their latest measured iteration. */
export function headline(track: Track, kpi: Kpi): Headline {
  const latest = latestValue(kpi)
  const aggregate = kpi.aggregate
  if (aggregate && aggregate.value !== null) {
    const value: KpiValue = {
      iteration: latest?.iteration ?? track.iterations[track.iterations.length - 1]?.id ?? '',
      value: aggregate.value,
      of: null,
      n: aggregate.n,
      spread: null,
      measured: true,
      note: aggregate.label,
      evidence: [],
    }
    return {
      value,
      text: formatValue(aggregate.value, kpi.unit),
      label: aggregate.n !== null ? `${aggregate.label} · n ${aggregate.n}` : aggregate.label,
      aggregate: true,
    }
  }
  if (!latest) return { value: null, text: '—', label: 'never measured', aggregate: false }
  return {
    value: latest,
    text: formatKpiValue(kpi, latest),
    label: iterationById(track, latest.iteration)?.label ?? latest.iteration,
    aggregate: false,
  }
}

/** The headline's change: vs the named pinned baseline when the KPI has one, else vs the previous iteration (a loop's
 * KPIs mostly have no baseline). An aggregate total ("all days") has no meaningful previous, so no change. */
export function headlineDelta(kpi: Kpi, head: Headline): Delta | null {
  if (!head.value) return null
  if (kpi.baseline && kpi.baseline.value !== null) return deltaVsBaseline(kpi, head.value)
  if (head.aggregate) return null
  return deltaVsPrevious(kpi, head.value)
}

/** Loops in projection order, each followed by its deployments (indented in pane 1). */
export function orderedTracks(projection: Projection): Array<{ track: Track; depth: 0 | 1 }> {
  const rows: Array<{ track: Track; depth: 0 | 1 }> = []
  for (const loop of topLevelTracks(projection)) {
    rows.push({ track: loop, depth: 0 })
    for (const child of childrenOf(projection, loop.id)) rows.push({ track: child, depth: 1 })
  }
  return rows
}

/** The route one level up (Esc): file → item → iteration → track (L2) → glance (L1). */
export function upRoute(route: Route): Route {
  const next: Route = { ...route }
  if (next.file) {
    delete next.file
    delete next.line
    return next
  }
  if (next.item) {
    delete next.item
    return next
  }
  if (next.iteration) {
    delete next.iteration
    return next
  }
  return {}
}

/** The latest evidence item that names a roadmap rung: a judged run titled "BT1 · …" or a lane whose metrics carry
 * `rung`, else a rung-status note listing it (VARIANTS.md "onOpenRung"). */
export function evidenceForRung(track: Track, rungId: string): EvidenceItem | null {
  const items = allEvidence(track)
  const runs = items.filter(
    (item) => (item.kind === 'run' && item.title.startsWith(`${rungId} `)) || item.metrics.rung === rungId,
  )
  if (runs.length) return runs[runs.length - 1]
  const notes = items.filter((item) => item.kind === 'note' && Object.prototype.hasOwnProperty.call(item.metrics, rungId))
  return notes[notes.length - 1] ?? null
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`
}
