// The x-axis of one track, as the reader set it on the settings page (settings.dashboard.xAxis): one column per
// iteration (the track's own wave, tick or session), or one per calendar day.
//
// WHY a local helper and not a shared one: variants may not edit shared/ (VARIANT-KIT.md); reported as a shared
// request so all three proposals collapse days identically.
// WHY these day rules, and not "average the day": a day column must say exactly what its number is.
//   1. The KPI's own `aggregate` when its period is that day (deployments: "day 07-29 median", n 57) — the adapter's
//      pooled figure is the honest headline (PROJECTION.md).
//   2. A `count` KPI sums its sessions (runs, audits, questions opened): a count over a day is a sum.
//   3. Anything else is the day's LAST reading, and the note says so ("last reading of the day …").
//   4. Nothing measured that day stays a gap with a note, never a zero.
// An iteration with `date: null` (rig tick 2) gets its own "undated" column instead of being dropped.

import type { Iteration, Kpi, KpiValue, Track } from '../../shared'
import { shortDay, valueAt } from '../../shared'

export interface TrackView {
  /** The columns to draw: the track's iterations, or synthetic day columns. */
  columns: Iteration[]
  /** Column id -> the iterations it covers (one in iteration mode). */
  members: Record<string, Iteration[]>
  /** The KPI with its values re-aligned to `columns` (the KPI itself in iteration mode). */
  kpi: (kpi: Kpi) => Kpi
  /** Map any routed iteration id (an iteration or a day column) to a column id of this view, or null. */
  resolve: (id: string | null | undefined) => string | null
  mode: 'iteration' | 'day'
}

const DAY_PREFIX = 'day:'

function plural(unit: string, count: number): string {
  return count === 1 ? unit : `${unit}s`
}

function dayValue(kpi: Kpi, columnId: string, members: Iteration[], unit: string): KpiValue {
  const values = members.map((member) => valueAt(kpi, member.id)).filter((value): value is KpiValue => Boolean(value))
  const measured = values.filter((value) => value.measured && value.value !== null)
  const evidence = values.flatMap((value) => value.evidence)
  const date = members[0]?.date ?? null
  const aggregate = kpi.aggregate
  if (aggregate && date && aggregate.period === date && aggregate.value !== null) {
    return {
      iteration: columnId,
      value: aggregate.value,
      of: null,
      n: aggregate.n,
      spread: null,
      measured: true,
      note: members.length > 1 ? `${aggregate.label}, pooled over ${members.length} ${plural(unit, members.length)}` : aggregate.label,
      evidence,
    }
  }
  if (measured.length === 0) {
    return {
      iteration: columnId,
      value: null,
      of: null,
      n: null,
      spread: null,
      measured: false,
      note: members.length > 1 ? `not measured in any of this day's ${members.length} ${plural(unit, members.length)}` : values[0]?.note ?? 'not measured',
      evidence,
    }
  }
  if (members.length === 1) return { ...measured[0], iteration: columnId }
  if (kpi.direction === 'count') {
    return {
      iteration: columnId,
      value: measured.reduce((sum, value) => sum + (value.value as number), 0),
      of: null,
      n: null,
      spread: null,
      measured: true,
      note: `sum of ${measured.length} ${plural(unit, measured.length)}`,
      evidence,
    }
  }
  const last = measured[measured.length - 1]
  const lastLabel = members.find((member) => member.id === last.iteration)?.label ?? last.iteration
  return {
    ...last,
    iteration: columnId,
    note: `last reading of the day (${lastLabel}); ${measured.length} of ${members.length} ${plural(unit, members.length)} measured`,
    evidence,
  }
}

export function trackView(track: Track, mode: 'iteration' | 'day'): TrackView {
  if (mode === 'iteration') {
    const members: Record<string, Iteration[]> = {}
    for (const it of track.iterations) members[it.id] = [it]
    return {
      columns: track.iterations,
      members,
      kpi: (kpi) => kpi,
      mode,
      resolve: (id) => {
        if (!id) return null
        if (track.iterations.some((it) => it.id === id)) return id
        if (id.startsWith(DAY_PREFIX)) {
          // A day column routed while the axis was "day": land on the last iteration of that day.
          const key = id.slice(DAY_PREFIX.length)
          const inDay = track.iterations.filter((it) => (it.date ?? 'undated') === key)
          return inDay[inDay.length - 1]?.id ?? null
        }
        return null
      },
    }
  }
  const unit = track.iteration.unit
  const order: string[] = []
  const groups: Record<string, Iteration[]> = {}
  for (const it of track.iterations) {
    const key = it.date ?? 'undated'
    if (!groups[key]) {
      groups[key] = []
      order.push(key)
    }
    groups[key].push(it)
  }
  const columns: Iteration[] = order.map((key) => {
    const group = groups[key]
    const marker =
      group.length === 1
        ? `${group[0].label}: ${group[0].marker}`
        : `${group.length} ${plural(unit, group.length)}: ${group
            .slice(0, 3)
            .map((it) => it.label)
            .join(' · ')}${group.length > 3 ? ` · +${group.length - 3} more` : ''}`
    return {
      id: `${DAY_PREFIX}${key}`,
      label: key === 'undated' ? 'undated' : shortDay(key),
      date: key === 'undated' ? null : key,
      marker,
      provenance: group[group.length - 1].provenance,
    }
  })
  const members: Record<string, Iteration[]> = {}
  for (const column of columns) members[column.id] = groups[column.id.slice(DAY_PREFIX.length)]
  const cache = new Map<string, Kpi>()
  return {
    columns,
    members,
    mode,
    kpi: (kpi) => {
      const hit = cache.get(kpi.id)
      if (hit) return hit
      const next: Kpi = { ...kpi, values: columns.map((column) => dayValue(kpi, column.id, members[column.id], unit)) }
      cache.set(kpi.id, next)
      return next
    },
    resolve: (id) => {
      if (!id) return null
      if (id.startsWith(DAY_PREFIX)) return columns.some((column) => column.id === id) ? id : null
      const it = track.iterations.find((candidate) => candidate.id === id)
      return it ? `${DAY_PREFIX}${it.date ?? 'undated'}` : null
    },
  }
}
