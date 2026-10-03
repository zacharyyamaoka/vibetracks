// The projection's types (docs/dashboard/PROJECTION.md, schema "vibetracks-dashboard/1") and the small pure helpers
// every variant shares: latest value, delta vs baseline (direction-aware), formatting with units, status tone.
// WHY one shared model: "solve the display once" (BRIEF, research principle 1). Every track renders through the same
// grammar, so the three variants differ in layout and navigation, never in how a number is read or worded.

export const PROJECTION_SCHEMA = 'vibetracks-dashboard/1'

export type Tone = 'ok' | 'warn' | 'risk' | 'stale' | 'muted'
export type Direction = 'higher' | 'lower' | 'info' | 'count'
export type IterationUnit = 'wave' | 'tick' | 'session' | 'day'
export type Slot = 'S1' | 'S2' | 'S3' | 'S4' | 'S5' | 'S6' | 'S7'
export type EvidenceKind = 'run' | 'lane' | 'audit' | 'gate' | 'report' | 'video' | 'note'
export type MediaKind = 'video' | 'html' | 'image' | 'text'

/** The research's seven KPI slots (a proposed schema, not a standard). */
export const SLOT_NAMES: Record<Slot, string> = {
  S1: 'North star',
  S2: 'Frontier gate',
  S3: 'Guardrails',
  S4: 'Delivery rate',
  S5: 'Evidence trust',
  S6: 'Cost',
  S7: 'Needs you & health',
}

/** The exact words the truth rules require (facts.md). */
export const N1_WORD = 'unconfirmed · repeat needed'

export interface Provenance {
  /** The data-home copy of the snapshot the number was read from. */
  snapshot: string
  /** JSON pointer into the snapshot (`*` = every element). */
  pointer: string
  /** The original live file the snapshot block names, aliases expanded. */
  source: string | null
  /** How the number was derived when it is not a plain read. */
  derived: string | null
  [extra: string]: unknown
}

export interface Status {
  word: string
  tone: Tone
}

export interface TrackState extends Status {
  detail: string
  /** ISO timestamp or date the state holds since. */
  since: string | null
}

export interface Iteration {
  id: string
  label: string
  /** YYYY-MM-DD, or null when no event dates it (rig tick 2). */
  date: string | null
  /** What changed at this iteration: the change marker drawn through every chart and column. */
  marker: string
  provenance: Provenance
}

export interface Target {
  /** A point target, scope or limit. */
  value?: number
  /** A band [low, high]; `kind: 'descriptive'` bands describe, they never judge. */
  band?: [number, number]
  /** A pass/fail gate value (alias of `value` for gates; adapters write `value`). */
  gate?: number
  kind: 'scope' | 'gate' | 'limit' | 'reference' | 'descriptive' | string
  label: string
}

export interface Baseline {
  iteration: string
  label: string
  value: number | null
}

export interface KpiValue {
  iteration: string
  value: number | null
  /** Denominator for "x of y" values (packages 7 of 9, gate runs 6 of 7, rungs 16 of 62). */
  of: number | null
  /** Sample size behind the value (runs, readings). null = not a sampled quantity. */
  n: number | null
  spread: number | null
  /** false = no reading at this iteration: draw a gap, never a zero. */
  measured: boolean
  note: string | null
  /** Evidence item ids of this KPI at this iteration (the provenance click target). */
  evidence: string[]
}

/** A period-level summary beside the per-iteration series (a deployment's day median pools its sessions). */
export interface KpiAggregate {
  label: string
  value: number | null
  n: number | null
  period: string | null
}

export interface Kpi {
  id: string
  label: string
  slot: Slot
  unit: string
  direction: Direction
  target: Target | null
  baseline: Baseline | null
  values: KpiValue[]
  status: Status
  note: string | null
  /** Optional period summary (deployments: the latest day's pooled value, e.g. "day 07-29 median 3.49°"). */
  aggregate?: KpiAggregate | null
  provenance: Provenance
}

export interface NeedsYou {
  id: string
  q: string
  /** Rung ids this question holds; empty = blocks nothing. */
  blocks: string[]
  default: string | null
  applies: string | null
}

export interface MediaRef {
  id: string
  kind: MediaKind
  label: string
}

export interface MediaEntry extends MediaRef {
  path: string
  mime: string
  bytes: number | null
}

export interface EvidenceItem {
  id: string
  iteration: string
  kind: EvidenceKind
  title: string
  when: string | null
  metrics: Record<string, string | number | boolean | null | Record<string, number>>
  status: string | null
  media: MediaRef[]
  links: Link[]
  note: string | null
}

export interface Link {
  label: string
  kind: 'media' | 'path' | 'command'
  media?: string
  value?: string
}

export interface Track {
  id: string
  title: string
  kind: 'loop' | 'deployment'
  parent: string | null
  summary: string
  state: TrackState
  iteration: { unit: IterationUnit; label: string }
  iterations: Iteration[]
  north_star: string
  kpis: Kpi[]
  needs_you: NeedsYou[]
  evidence: {
    by_iteration: Record<string, EvidenceItem[]>
    by_kpi?: Record<string, string[]>
  }
  links: Link[]
  provenance: Provenance
}

export interface Projection {
  schema: typeof PROJECTION_SCHEMA | string
  generated_at: string
  as_of: string
  source: {
    adapter: string
    kind: 'snapshot' | 'live' | string
    live: boolean
    snapshot: string
    snapshot_generated_at: string | null
    curriculum: string | null
    todo: string
    units_note: string | null
  }
  tracks: Track[]
  media: Record<string, MediaEntry>
}

// ------------------------------------------------------------------------------------------------ lookups

export function trackById(projection: Projection, id: string | null | undefined): Track | null {
  return projection.tracks.find((track) => track.id === id) ?? null
}

/** Tracks with no parent (the loops), in projection order. */
export function topLevelTracks(projection: Projection): Track[] {
  return projection.tracks.filter((track) => track.parent === null)
}

/** Tracks whose parent is `id` (a loop's deployments). */
export function childrenOf(projection: Projection, id: string): Track[] {
  return projection.tracks.filter((track) => track.parent === id)
}

export function kpiById(track: Track, id: string | null | undefined): Kpi | null {
  return track.kpis.find((kpi) => kpi.id === id) ?? null
}

export function northStar(track: Track): Kpi | null {
  return kpiById(track, track.north_star)
}

export function iterationById(track: Track, id: string | null | undefined): Iteration | null {
  return track.iterations.find((it) => it.id === id) ?? null
}

export function latestIteration(track: Track): Iteration | null {
  return track.iterations[track.iterations.length - 1] ?? null
}

export function valueAt(kpi: Kpi, iterationId: string): KpiValue | null {
  return kpi.values.find((value) => value.iteration === iterationId) ?? null
}

/** KPIs grouped by slot, S1 first, in projection order inside a slot. */
export function kpisBySlot(track: Track): Array<{ slot: Slot; name: string; kpis: Kpi[] }> {
  const slots = Object.keys(SLOT_NAMES) as Slot[]
  return slots
    .map((slot) => ({ slot, name: SLOT_NAMES[slot], kpis: track.kpis.filter((kpi) => kpi.slot === slot) }))
    .filter((group) => group.kpis.length > 0)
}

export function allEvidence(track: Track): EvidenceItem[] {
  return track.iterations.flatMap((it) => track.evidence.by_iteration[it.id] ?? [])
}

export function evidenceAt(track: Track, iterationId: string): EvidenceItem[] {
  return track.evidence.by_iteration[iterationId] ?? []
}

export function evidenceById(track: Track, ids: string[]): EvidenceItem[] {
  const index = new Map(allEvidence(track).map((item) => [item.id, item]))
  return ids.map((id) => index.get(id)).filter((item): item is EvidenceItem => Boolean(item))
}

/** The evidence behind one cell (KPI × iteration): what a click on that point opens. */
export function evidenceForValue(track: Track, kpi: Kpi, iterationId: string): EvidenceItem[] {
  return evidenceById(track, valueAt(kpi, iterationId)?.evidence ?? [])
}

/** Every evidence item of one KPI, in iteration order. */
export function evidenceForKpi(track: Track, kpi: Kpi): EvidenceItem[] {
  return evidenceById(track, kpi.values.flatMap((value) => value.evidence))
}

// ------------------------------------------------------------------------------------------------ values

export function measuredValues(kpi: Kpi): KpiValue[] {
  return kpi.values.filter((value) => value.measured && value.value !== null)
}

/** The newest measured value, or null when the KPI was never measured. */
export function latestValue(kpi: Kpi): KpiValue | null {
  const measured = measuredValues(kpi)
  return measured[measured.length - 1] ?? null
}

/** The measured value before `iterationId` (default: before the latest). */
export function previousValue(kpi: Kpi, iterationId?: string): KpiValue | null {
  const measured = measuredValues(kpi)
  const at = iterationId === undefined ? measured.length - 1 : measured.findIndex((value) => value.iteration === iterationId)
  return at > 0 ? measured[at - 1] : null
}

export interface Delta {
  from: number
  to: number
  delta: number
  /** true = moved the good way, false = the bad way, null = no direction (info/count) or unchanged. */
  better: boolean | null
  /** What the delta is measured against ("start 09-30", "previous", "V0 untuned twin"). */
  against: string
  /** True when either side rests on n ≤ 1: the change must read "unconfirmed · repeat needed". */
  unconfirmed: boolean
}

function makeDelta(kpi: Kpi, from: number, to: number, against: string, nFrom: number | null, nTo: number | null): Delta {
  const delta = to - from
  let better: boolean | null = null
  if (delta !== 0 && (kpi.direction === 'higher' || kpi.direction === 'lower')) better = (delta > 0) === (kpi.direction === 'higher')
  const unconfirmed = (nFrom !== null && nFrom <= 1) || (nTo !== null && nTo <= 1)
  return { from, to, delta, better, against, unconfirmed }
}

/** Latest vs the KPI's named, pinned baseline. null when either side is missing. */
export function deltaVsBaseline(kpi: Kpi, at?: KpiValue | null): Delta | null {
  const latest = at === undefined ? latestValue(kpi) : at
  if (!latest || latest.value === null || !kpi.baseline || kpi.baseline.value === null) return null
  const base = valueAt(kpi, kpi.baseline.iteration)
  return makeDelta(kpi, kpi.baseline.value, latest.value, kpi.baseline.label, base?.n ?? null, latest.n)
}

/** Latest (or `at`) vs the measured value before it. */
export function deltaVsPrevious(kpi: Kpi, at?: KpiValue | null): Delta | null {
  const latest = at === undefined ? latestValue(kpi) : at
  if (!latest || latest.value === null) return null
  const previous = previousValue(kpi, latest.iteration)
  if (!previous || previous.value === null) return null
  return makeDelta(kpi, previous.value, latest.value, 'previous', previous.n, latest.n)
}

/** Where the latest value sits against its target: met / not met / inside or outside a band. null without a target. */
export function targetState(kpi: Kpi, at?: KpiValue | null): 'met' | 'not met' | 'inside band' | 'outside band' | null {
  const latest = at === undefined ? latestValue(kpi) : at
  const target = kpi.target
  if (!latest || latest.value === null || !target) return null
  if (target.band) return latest.value >= target.band[0] && latest.value <= target.band[1] ? 'inside band' : 'outside band'
  const goal = target.value ?? target.gate
  if (goal === undefined || target.kind === 'scope' || target.kind === 'reference') return null
  if (target.kind === 'limit') return latest.value < goal ? 'met' : 'not met'
  if (kpi.direction === 'lower') return latest.value <= goal ? 'met' : 'not met'
  return latest.value >= goal ? 'met' : 'not met'
}

/** The y-domain that holds every measured value and the target, for charts that share one scale per KPI. */
export function valueDomain(kpi: Kpi): [number, number] {
  const numbers = measuredValues(kpi).map((value) => value.value as number)
  const target = kpi.target
  if (target?.band) numbers.push(...target.band)
  const goal = target?.value ?? target?.gate
  if (goal !== undefined) numbers.push(goal)
  if (kpi.baseline?.value !== undefined && kpi.baseline?.value !== null) numbers.push(kpi.baseline.value)
  if (numbers.length === 0) return [0, 1]
  let low = Math.min(...numbers)
  let high = Math.max(...numbers)
  if (kpi.unit === '%' || kpi.direction === 'count' || target?.kind === 'scope') low = Math.min(0, low)
  if (low === high) {
    low -= Math.abs(low) * 0.1 || 1
    high += Math.abs(high) * 0.1 || 1
  }
  return [low, high]
}

// ------------------------------------------------------------------------------------------------ formatting

const UNIT_SUFFIX: Record<string, string> = {
  deg: '°',
  '%': '\u00a0%',
  'h elapsed': '\u00a0h',
  h: '\u00a0h',
  '×': '×',
  'N·m': '\u00a0N·m',
}

/** Significant digits that keep small numbers readable (0.02181 N·m) without padding big ones (1000). */
export function formatNumber(value: number, unit?: string): string {
  if (!Number.isFinite(value)) return '—'
  if (Number.isInteger(value)) return value.toLocaleString('en-US')
  const abs = Math.abs(value)
  if (unit === '%') return value.toFixed(1)
  if (abs >= 100) return value.toFixed(0)
  if (abs >= 10) return value.toFixed(1)
  if (abs >= 1) return value.toFixed(2)
  if (abs >= 0.1) return value.toFixed(3)
  return value.toPrecision(3)
}

/** "3.49°", "73.4 %", "9.3 h", "16 / 62", "—" for no value. Units that are nouns (rungs, runs) are left to the label. */
export function formatValue(value: number | null | undefined, unit: string, of?: number | null): string {
  if (value === null || value === undefined) return '—'
  const number = formatNumber(value, unit)
  if (of !== null && of !== undefined) return `${number}\u00a0/\u00a0${formatNumber(of)}`
  return number + (UNIT_SUFFIX[unit] ?? '')
}

export function formatKpiValue(kpi: Kpi, value: KpiValue | null | undefined): string {
  if (!value || !value.measured) return '—'
  return formatValue(value.value, kpi.unit, value.of)
}

/** "+9", "−2.89°", "±0" with a real minus sign. */
export function formatDelta(delta: number, unit: string): string {
  if (delta === 0) return '±0'
  const sign = delta > 0 ? '+' : '−'
  return sign + formatNumber(Math.abs(delta), unit) + (UNIT_SUFFIX[unit] ?? '')
}

/** "n = 15", or "" when n is not meaningful. */
export function formatN(value: KpiValue | null | undefined): string {
  return value && value.n !== null && value.n !== undefined ? `n = ${value.n}` : ''
}

export function formatTargetLabel(kpi: Kpi): string {
  return kpi.target?.label ?? 'no target set'
}

/** "Sat 3 Oct" from an ISO date or timestamp. */
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

/** "MM-DD" from an ISO date. */
export function shortDay(iso: string | null | undefined): string {
  return iso ? iso.slice(5, 10) : '—'
}

/** The calm reading of a delta: "+9 since start 09-30", or the n = 1 rule's words. */
export function describeDelta(kpi: Kpi, delta: Delta | null): string {
  if (!delta) return ''
  if (delta.unconfirmed && delta.delta !== 0) return `${formatDelta(delta.delta, kpi.unit)} vs ${delta.against} · ${N1_WORD}`
  return `${formatDelta(delta.delta, kpi.unit)} vs ${delta.against}`
}

// ------------------------------------------------------------------------------------------------ tone

/** Colour only for exceptions (BRIEF): ok and muted render grey; warn, risk and stale get colour. */
export function isException(tone: Tone): boolean {
  return tone === 'warn' || tone === 'risk' || tone === 'stale'
}

export function toneOf(status: Status | null | undefined): Tone {
  return status?.tone ?? 'muted'
}

/** The CSS class for a tone (calm.css): `vt-tone-warn` etc. */
export function toneClass(tone: Tone): string {
  return `vt-tone-${tone}`
}

/** The tone a delta deserves: grey unless it moved the bad way on confirmed data. */
export function deltaTone(delta: Delta | null): Tone {
  if (!delta) return 'muted'
  if (delta.unconfirmed && delta.delta !== 0) return 'warn'
  return delta.better === false ? 'warn' : 'muted'
}

/** Open questions that hold a rung, then the rest. */
export function blockingQuestions(track: Track): NeedsYou[] {
  return track.needs_you.filter((question) => question.blocks.length > 0)
}
