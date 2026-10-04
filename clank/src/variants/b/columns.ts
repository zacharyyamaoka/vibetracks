// Variant B's x-axis: the shared, aligned columns every KPI row of the wall is drawn on, and the value of one KPI in
// one column. A column is one iteration (wave · tick · session), or one calendar day when the settings page says
// xAxis = day.
//
// WHY one column model for every row: the research's "small multiples on one shared, aligned x-axis" only works when
// every row maps an iteration to the same x. Building the columns once per track (not per chart) is what lets one
// cursor run through all rows and lets the eye line up what moved together in one wave.
// WHY the day rules below are spelled out in every readout ("day 07-29 median", "sum of 2 ticks", "last of 15:
// 07-29 limits full torque"): pooling several iterations into one day is a derivation, and a derived number that does
// not say how it was derived reads as a measurement (truth rule 1, "every number comes from a named source").

import type { Iteration, Kpi, KpiValue, Track } from '../../shared'
import { formatDay, measuredValues, shortDay, valueAt, valueDomain } from '../../shared'

export interface Column {
  /** Stable key: the iteration id, or `day:<date>` / `undated:<iteration id>` on the day axis. */
  id: string
  /** The axis label ("W3", "07-29 flat", "10-02"). */
  label: string
  /** The long name for readouts ("W3 · Sat 3 Oct", "07-29 · 15 sessions"). */
  title: string
  date: string | null
  iterations: Iteration[]
  /** What changed in this column: the iteration's marker, or each pooled iteration's marker. */
  marker: string
}

export type XAxis = 'iteration' | 'day'

const UNIT_PLURAL: Record<string, string> = { wave: 'waves', tick: 'ticks', session: 'sessions', day: 'days' }

export function unitPlural(track: Track, count: number): string {
  const unit = track.iteration.unit
  return count === 1 ? unit : (UNIT_PLURAL[unit] ?? `${unit}s`)
}

export function buildColumns(track: Track, xAxis: XAxis): Column[] {
  if (xAxis === 'iteration') {
    return track.iterations.map((it) => ({
      id: it.id,
      label: it.label,
      title: `${it.label} · ${it.date ? formatDay(it.date) : 'no date recorded'}`,
      date: it.date,
      iterations: [it],
      marker: it.marker,
    }))
  }
  // WHY an undated iteration keeps its own column on the day axis (rig tick 2): VARIANT-KIT says it is "shown as
  // undated, never dropped"; folding it into a neighbouring day would invent a date.
  const columns: Column[] = []
  for (const it of track.iterations) {
    const last = columns[columns.length - 1]
    if (it.date && last && last.date === it.date) {
      last.iterations.push(it)
      continue
    }
    columns.push({
      id: it.date ? `day:${it.date}` : `undated:${it.id}`,
      label: it.date ? shortDay(it.date) : `${it.label} · undated`,
      title: '',
      date: it.date,
      iterations: [it],
      marker: '',
    })
  }
  for (const column of columns) {
    const count = column.iterations.length
    column.title = column.date
      ? `${formatDay(column.date)} · ${count} ${unitPlural(track, count)}${count > 1 ? ` (${column.iterations.map((it) => it.label).join(', ')})` : ` (${column.iterations[0].label})`}`
      : `${column.iterations[0].label} · no date recorded`
    column.marker = count === 1 ? column.iterations[0].marker : column.iterations.map((it) => `${it.label}: ${it.marker}`).join(' · ')
  }
  return columns
}

export function columnIndexOfIteration(columns: Column[], iterationId: string | null | undefined): number {
  if (!iterationId) return -1
  return columns.findIndex((column) => column.iterations.some((it) => it.id === iterationId))
}

/** One KPI in one column. On the iteration axis it is the KpiValue itself; on the day axis it says how it pooled. */
export interface Cell {
  value: number | null
  of: number | null
  n: number | null
  spread: number | null
  measured: boolean
  note: string | null
  evidence: string[]
  /** The iteration a click on this cell opens (the column's last iteration that carries the reading). */
  iteration: string
  /** The raw KpiValue when the column is one iteration (deltas need it); null when pooled. */
  raw: KpiValue | null
  /** How a pooled value was derived ("day 07-29 median", "sum of 2 ticks", "last of 15: …"); null when not pooled. */
  rule: string | null
}

export function cellAt(track: Track, kpi: Kpi, column: Column): Cell {
  const lastIteration = column.iterations[column.iterations.length - 1]
  if (column.iterations.length === 1) {
    const raw = valueAt(kpi, lastIteration.id)
    return {
      value: raw?.value ?? null,
      of: raw?.of ?? null,
      n: raw?.n ?? null,
      spread: raw?.spread ?? null,
      measured: Boolean(raw?.measured && raw.value !== null),
      note: raw?.note ?? null,
      evidence: raw?.evidence ?? [],
      iteration: lastIteration.id,
      raw,
      rule: null,
    }
  }
  const values = column.iterations.map((it) => valueAt(kpi, it.id)).filter((value): value is KpiValue => Boolean(value))
  const measured = values.filter((value) => value.measured && value.value !== null)
  const evidence = Array.from(new Set(values.flatMap((value) => value.evidence)))
  const count = column.iterations.length
  const carrier = measured[measured.length - 1]?.iteration ?? lastIteration.id
  const base = { spread: null, evidence, iteration: carrier, raw: null, note: null }
  // WHY the adapter's aggregate wins on its own day: a deployment's day summary (the median over every run that day)
  // is the honest headline; the last session of the day would be one trajectory standing in for 57 runs.
  const aggregate = kpi.aggregate
  if (aggregate && aggregate.value !== null && aggregate.period && aggregate.period === column.date) {
    return { ...base, value: aggregate.value, of: null, n: aggregate.n, measured: true, rule: aggregate.label }
  }
  if (measured.length === 0) {
    return { ...base, value: null, of: null, n: null, measured: false, rule: null, note: `not measured in any of the ${count} ${unitPlural(track, count)}` }
  }
  if (kpi.direction === 'count') {
    const sum = measured.reduce((total, value) => total + (value.value as number), 0)
    const allOf = measured.every((value) => value.of !== null)
    const allN = measured.every((value) => value.n !== null)
    return {
      ...base,
      value: sum,
      of: allOf ? measured.reduce((total, value) => total + (value.of as number), 0) : null,
      n: allN ? measured.reduce((total, value) => total + (value.n as number), 0) : null,
      measured: true,
      rule: `sum of ${measured.length} ${unitPlural(track, measured.length)}`,
    }
  }
  const last = measured[measured.length - 1]
  const lastLabel = column.iterations.find((it) => it.id === last.iteration)?.label ?? last.iteration
  return {
    ...base,
    value: last.value,
    of: last.of,
    n: last.n,
    spread: last.spread,
    measured: true,
    rule: `last of ${count} ${unitPlural(track, count)}: ${lastLabel}`,
  }
}

/** The y-domain of one row: every value the row draws (pooled day values included), the target and the baseline. */
export function rowDomain(kpi: Kpi, cells: Cell[]): [number, number] {
  const [low, high] = valueDomain(kpi)
  const values = cells.filter((cell) => cell.measured && cell.value !== null).map((cell) => cell.value as number)
  if (measuredValues(kpi).length === 0 && values.length === 0) return [low, high]
  let lo = Math.min(low, ...values)
  let hi = Math.max(high, ...values)
  if (lo === hi) {
    lo -= Math.abs(lo) * 0.1 || 1
    hi += Math.abs(hi) * 0.1 || 1
  }
  return [lo, hi]
}

/** A marker shortened to fit `max` characters, cut at its own " · " seams, with an explicit ellipsis when cut. */
export function shortMarker(marker: string, max: number): string {
  const text = marker.replace(/^wave closed: /, '')
  if (text.length <= max) return text
  const parts = text.split(' · ')
  let out = ''
  for (const part of parts) {
    const next = out ? `${out} · ${part}` : part
    if (next.length + 2 > max) break
    out = next
  }
  if (!out) out = text.slice(0, Math.max(1, max - 1))
  return `${out} …`
}

/** True when the marker records a change of the measuring tool (a pinned ruler, a freeze): such a step is not progress. */
export function isRulerChange(marker: string): boolean {
  return /ruler|freeze/i.test(marker)
}
