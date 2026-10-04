// The scorecard's x-axis: one column per iteration (wave, tick, session) or per calendar day, read from the settings
// page (props.settings.dashboard.xAxis). Plus the small pure helpers the three pages share.
//
// WHY a local helper and not shared/: variants own only their folder (VARIANT-KIT.md). This is listed as a shared
// request, so B and C can group days the same way once it moves to shared/model.ts.
// WHY these day rules (and not "average the day"): a value is only ever a number the projection holds.
//   - A deployment KPI whose `aggregate.period` is that day shows the aggregate (the honest day headline, e.g. "day
//     07-29 median" 3.49°, n 57), never a mean the dashboard computed itself.
//   - A count KPI sums its sessions (57 real runs on 07-29 = the adapter's own "all days" total).
//   - Anything else shows the day's LAST measured value and says "last of N", so a cumulative burn-up stays right and a
//     per-tick value is never silently presented as the day's total.
//   - An iteration with `date: null` (rig tick 2) keeps its own "undated" column in order, never dropped.

import type { Iteration, Kpi, KpiValue, Projection, Track } from '../../shared'
import { shortDay, valueAt, valueDomain as valueDomainOf } from '../../shared'

export interface Column {
  /** Iteration id, or `day:YYYY-MM-DD`. */
  key: string
  /** Main header line: "W3", "T2", "07-29 gravity amplitude ladder", or the day "07-29". */
  label: string
  /** Second header line: the date (iteration mode) or weekday (day mode); "undated" when there is none. */
  sub: string
  /** The change marker(s) at this column: what happened. */
  marker: string
  iterations: Iteration[]
  /** The iteration a click on this column opens (the last one of a day). */
  opens: string
}

export interface Cell {
  value: number | null
  of: number | null
  n: number | null
  spread: number | null
  measured: boolean
  note: string | null
  /** How a multi-iteration day cell was formed ("day 07-29 median", "sum of 15 sessions", "last of 2 ticks"). */
  how: string | null
  evidence: string[]
}

const PLURAL: Record<string, string> = { wave: 'waves', tick: 'ticks', session: 'sessions', day: 'days' }

export function unitWord(track: Track, count: number): string {
  const unit = track.iteration.unit
  return count === 1 ? unit : PLURAL[unit] ?? `${unit}s`
}

function weekday(iso: string): string {
  const date = new Date(`${iso}T12:00:00`)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString('en-GB', { weekday: 'short' })
}

export function buildColumns(track: Track, xAxis: 'iteration' | 'day'): Column[] {
  if (xAxis === 'iteration') {
    return track.iterations.map((it) => {
      // "07-29 hardware gate" → label "hardware gate" over the date line "07-29": the same characters, one line each.
      const day = it.date ? shortDay(it.date) : null
      const split = day !== null && it.label.startsWith(`${day} `)
      return {
      key: it.id,
      label: split ? it.label.slice(day.length + 1) : it.label,
      sub: day ?? 'undated',
      marker: it.marker,
      iterations: [it],
      opens: it.id,
      }
    })
  }
  const columns: Column[] = []
  for (const it of track.iterations) {
    const last = columns[columns.length - 1]
    if (it.date && last && last.key === `day:${it.date}`) {
      last.iterations.push(it)
      last.opens = it.id
      continue
    }
    columns.push({
      key: it.date ? `day:${it.date}` : it.id,
      label: it.date ? shortDay(it.date) : it.label,
      sub: it.date ? weekday(it.date) : 'undated',
      marker: it.marker,
      iterations: [it],
      opens: it.id,
    })
  }
  for (const column of columns) {
    if (column.iterations.length > 1) {
      column.marker = `${column.iterations.length} ${unitWord(track, column.iterations.length)}: ${column.iterations.map((it) => it.label).join(' · ')}`
    }
  }
  return columns
}

function fromValue(value: KpiValue | null, how: string | null = null): Cell {
  return {
    value: value?.value ?? null,
    of: value?.of ?? null,
    n: value?.n ?? null,
    spread: value?.spread ?? null,
    measured: Boolean(value?.measured && value.value !== null),
    note: value?.note ?? null,
    how,
    evidence: value?.evidence ?? [],
  }
}

export function cellFor(track: Track, kpi: Kpi, column: Column): Cell {
  if (column.iterations.length === 1) return fromValue(valueAt(kpi, column.iterations[0].id))
  const values = column.iterations.map((it) => valueAt(kpi, it.id)).filter((v): v is KpiValue => v !== null)
  const measured = values.filter((v) => v.measured && v.value !== null)
  const evidence = values.flatMap((v) => v.evidence)
  const day = column.iterations[0].date
  const words = `${measured.length} ${unitWord(track, measured.length)}`
  if (kpi.aggregate && kpi.aggregate.period && kpi.aggregate.period === day && kpi.aggregate.value !== null) {
    return { value: kpi.aggregate.value, of: null, n: kpi.aggregate.n, spread: null, measured: true, note: null, how: kpi.aggregate.label, evidence }
  }
  if (measured.length === 0) {
    return { value: null, of: null, n: null, spread: null, measured: false, note: values.find((v) => v.note)?.note ?? 'not measured on this day', how: null, evidence }
  }
  if (measured.length === 1) return { ...fromValue(measured[0], `only reading of ${column.iterations.length} ${unitWord(track, column.iterations.length)}`), evidence }
  if (kpi.direction === 'count') {
    const sum = measured.reduce((total, v) => total + (v.value as number), 0)
    return { value: sum, of: null, n: null, spread: null, measured: true, note: null, how: `sum of ${words}`, evidence }
  }
  const last = measured[measured.length - 1]
  return { ...fromValue(last, `last of ${words}`), evidence }
}

// ------------------------------------------------------------------------------------------------ small helpers

/** Whole days from `from` to `to` (both YYYY-MM-DD or ISO). */
export function daysBetween(from: string, to: string): number {
  const a = Date.parse(from.length === 10 ? `${from}T12:00:00` : from)
  const b = Date.parse(to.length === 10 ? `${to}T12:00:00` : to)
  return Math.round((b - a) / 86_400_000)
}

export function relativeDay(date: string | null, asOf: string): string {
  if (!date) return 'undated'
  const days = daysBetween(date.slice(0, 10), asOf)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 0) return shortDay(date)
  return `${days} days ago`
}

/** The newest iteration that carries a date. */
export function latestDated(track: Track): Iteration | null {
  for (let i = track.iterations.length - 1; i >= 0; i -= 1) if (track.iterations[i].date) return track.iterations[i]
  return null
}

/** The y-domain of a trend glyph: a scope KPI (a burn-up, 16 of 62) fits its own values so the climb is visible (the
 * level against scope is already printed as "16 / 62"); every other KPI shares valueDomain, target included. */
export function trendDomain(kpi: Kpi): [number, number] {
  if (kpi.target?.kind !== 'scope') return valueDomainOf(kpi)
  const numbers = kpi.values.filter((v) => v.measured && v.value !== null).map((v) => v.value as number)
  if (numbers.length === 0) return [0, 1]
  const low = Math.min(...numbers)
  const high = Math.max(...numbers)
  return low === high ? [low - 1, high + 1] : [low, high]
}

/** "2026-10-03T05:53:39+00:00" → "10-03 05:53 UTC": the clock the source wrote, never re-zoned to this machine. */
export function formatSince(since: string | null): string {
  if (!since) return ''
  if (since.length <= 10) return shortDay(since)
  const offset = since.slice(19).replace(/^\.\d+/, '')
  const zone = offset === '+00:00' || offset === 'Z' ? 'UTC' : offset.replace('-', '−')
  return `${since.slice(5, 10)} ${since.slice(11, 16)}${zone ? ` ${zone}` : ''}`
}

/** A KPI is a loop-progress burn-up when its target is a scope ("of 62 rungs"): draw it as steps from 0. */
export function scopeDomain(kpi: Kpi): [number, number] | undefined {
  return kpi.target?.kind === 'scope' && kpi.target.value !== undefined ? [0, kpi.target.value] : undefined
}

/** Colour a cell only when it misses a gate or a limit (descriptive bands and references never judge). */
export function missesTarget(kpi: Kpi, value: number | null): boolean {
  const target = kpi.target
  if (value === null || !target) return false
  const goal = target.value ?? target.gate
  if (goal === undefined) return false
  if (target.kind === 'limit') return value >= goal
  if (target.kind === 'gate') return kpi.direction === 'lower' ? value > goal : value < goal
  return false
}

/** The media's owning evidence item, so a track link ("Wave 3 report") opens in place on its iteration page. */
export function evidenceOwningMedia(track: Track, mediaId: string): { iteration: string; item: string } | null {
  for (const it of track.iterations) {
    for (const item of track.evidence.by_iteration[it.id] ?? []) {
      if (item.media.some((media) => media.id === mediaId)) return { iteration: it.id, item: item.id }
    }
  }
  return null
}

/** A loop's open questions, totalled across the projection (the L1 subtitle). */
export function totalBlocking(projection: Projection): number {
  return projection.tracks.reduce((sum, track) => sum + track.needs_you.filter((q) => q.blocks.length > 0).length, 0)
}

/** "wave closed: 7/7 landed · ruler pinned a2-v2 · …" → true: a ruler (measuring tool) change gets its own mark, so a
 * KPI jump caused by changing the metric is never read as progress (research: change markers, METR / W&B Weave). */
export function isRulerChange(marker: string): boolean {
  return /\bruler\b/i.test(marker)
}
