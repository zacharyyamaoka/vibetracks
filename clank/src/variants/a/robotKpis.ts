// The robot-KPI blocks a track may carry (docs/dashboard/PROJECTION.md: `kpi_groups`, `Kpi.group`, `kpi_table`,
// `playbacks`; the rig adapter writes them, 2026-10-06 KPI-VIEW brief, src/dev/bam_rig_loop/briefs/KPI-VIEW.md), read with guards because shared/model.ts does
// not declare them (variant A is their only reader; moving the types there is a shared request, like live.ts's).
// WHY guards and not casts: a snapshot projection, or any other track, has none of these fields, and a missing field
// must render as "not there", never as an empty table that reads like "no rows".

import type { Kpi, Track } from '../../shared'
import { formatValue } from '../../shared'
import { formatLocal } from '../../shared/time'

export interface KpiGroup {
  id: string
  label: string
  /** Collapsed by default (the loop's own numbers): one click opens it, and the route remembers it (`kg`). */
  collapsed: boolean
  note: string | null
}

export interface KpiDef {
  key: string
  label: string
  unit: string
  lower_is_better: boolean | null
  /** Display scale: the export stores rad and N·m; deg = value × scale. */
  scale: number
}

export interface KpiTableRow {
  deployment_id: string
  period: string
  start: string | null
  end: string | null
  counts: { real?: number; sim?: number; aborted?: number } | null
  kpis: Record<string, number | null>
  backend: string | null
  twin_version: string | null
  control_mode: string | null
  settings: Record<string, unknown> | null
  na_reason: string | null
  [extra: string]: unknown
}

export interface KpiTable {
  state: 'ok' | 'missing' | 'unreadable' | string
  dir: string | null
  json: string | null
  csv: string | null
  message: string | null
  command: string | null
  contract: string | null
  generated_at: string | null
  generated_label: string | null
  cache: { sha256?: string; runs?: number; scanned_at?: string; cache_version?: number; dir?: string } | null
  kpi_defs: KpiDef[]
  settings_keys: string[]
  rows: KpiTableRow[]
  /** deployment id -> the child track id it belongs to ("can12-pendulum-10to1" -> "can12"). */
  deployments: Record<string, string>
  headline: { deployment: string; label: string; real_row: number | null; twin_row: number | null; twin_baseline_row: number | null; rule: string | null } | null
  /** The KPI doc (bam_deployments KPIS.md): its path, and its media id when the file exists. */
  doc: { path: string | null; media: string | null } | null
}

export interface PlaybackEntry {
  run_id: string
  trajectory: string | null
  session: string | null
  started_at: string | null
  started_label: string | null
  control_mode: string | null
  twin_versions: string[]
  twin_vs_real_rms_rad: Record<string, number>
  file: string | null
  rrd: string | null
  rrd_exists: boolean
  size_bytes: number | null
  /** One physical line: the absolute viewer path, a space, the absolute .rrd path. */
  command: string | null
  video_path: string | null
  /** A media id in the projection's allowlist when the mp4 exists. */
  video: string | null
}

export interface PlaybackGroup {
  id: string
  label: string
  count: number
  twin_runs: number
  runs: PlaybackEntry[]
}

export interface Playbacks {
  state: 'ok' | 'missing' | 'unreadable' | string
  dir: string | null
  index: string | null
  viewer: string | null
  viewer_exists: boolean
  message: string | null
  command: string | null
  count: number
  group_by: string
  groups: PlaybackGroup[]
}

const isObject = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value)

function field(track: Track, key: string): unknown {
  return (track as unknown as Record<string, unknown>)[key]
}

/** The track's KPI groups, in render order, or null when it declares none (then the scorecard groups by slot). */
export function kpiGroupsOf(track: Track): KpiGroup[] | null {
  const raw = field(track, 'kpi_groups')
  if (!Array.isArray(raw)) return null
  const groups = raw
    .filter(isObject)
    .filter((group) => typeof group.id === 'string' && group.id)
    .map((group) => ({
      id: String(group.id),
      label: typeof group.label === 'string' && group.label ? group.label : String(group.id),
      collapsed: group.collapsed === true,
      note: typeof group.note === 'string' ? group.note : null,
    }))
  return groups.length ? groups : null
}

export function groupOf(kpi: Kpi): string | null {
  const value = (kpi as unknown as Record<string, unknown>).group
  return typeof value === 'string' && value ? value : null
}

export function kpiTableOf(track: Track): KpiTable | null {
  const raw = field(track, 'kpi_table')
  if (!isObject(raw) || typeof raw.state !== 'string') return null
  return {
    ...(raw as unknown as KpiTable),
    kpi_defs: Array.isArray(raw.kpi_defs) ? (raw.kpi_defs.filter((d) => isObject(d) && typeof d.key === 'string') as unknown as KpiDef[]) : [],
    rows: Array.isArray(raw.rows) ? (raw.rows.filter(isObject) as unknown as KpiTableRow[]) : [],
    settings_keys: Array.isArray(raw.settings_keys) ? raw.settings_keys.filter((key): key is string => typeof key === 'string') : [],
    deployments: isObject(raw.deployments) ? (raw.deployments as Record<string, string>) : {},
  }
}

export function playbacksOf(track: Track): Playbacks | null {
  const raw = field(track, 'playbacks')
  if (!isObject(raw) || typeof raw.state !== 'string') return null
  const groups = Array.isArray(raw.groups)
    ? raw.groups.filter(isObject).map((group) => ({
        ...(group as unknown as PlaybackGroup),
        runs: Array.isArray(group.runs) ? (group.runs.filter((run) => isObject(run) && typeof run.run_id === 'string') as unknown as PlaybackEntry[]) : [],
      }))
    : []
  return { ...(raw as unknown as Playbacks), groups }
}

// ------------------------------------------------------------------------------------------------ cells

export const RAD_TO_DEG = 180 / Math.PI
export const NOT_MEASURED = 'not measured'
export const NOT_APPLICABLE = 'n/a'

/** One KPI cell of the table: the export's value × its display scale, formatted with its unit; a null is "not
 * measured", or "n/a" on a row that carries an `na_reason` (the kinematic backend follows its target by construction). */
export function tableCell(row: KpiTableRow, def: KpiDef): { text: string; measured: boolean; title: string | null } {
  const raw = isObject(row.kpis) ? row.kpis[def.key] : null
  if (typeof raw !== 'number' || !Number.isFinite(raw)) {
    return row.na_reason ? { text: NOT_APPLICABLE, measured: false, title: row.na_reason } : { text: NOT_MEASURED, measured: false, title: null }
  }
  const scale = typeof def.scale === 'number' && Number.isFinite(def.scale) ? def.scale : 1
  const unit = def.unit === 'deg' ? 'deg' : def.unit
  return { text: formatValue(raw * scale, unit), measured: true, title: `${raw} (stored) × ${scale} = ${raw * scale}` }
}

/** The settings as short words in the export's key order. Values are shown as stored (no rounding, no trimming). */
export function settingWords(row: KpiTableRow, keys: string[]): Array<{ key: string; text: string }> {
  const settings = isObject(row.settings) ? row.settings : {}
  const words: Array<{ key: string; text: string }> = []
  for (const key of keys) {
    const value = settings[key]
    if (value === null || value === undefined || key === 'plant') continue
    if (key === 'torque_cap_nm') words.push({ key, text: `cap ${String(value)} N·m` })
    else if (key === 'coulomb_friction_nm') words.push({ key, text: `Coulomb ${String(value)} N·m` })
    else if (key === 'friction_ff') words.push({ key, text: `friction FF ${value === true ? 'on' : value === false ? 'off' : String(value)}` })
    else if (key === 'mounting') words.push({ key, text: String(value) })
    else words.push({ key, text: `${key} ${typeof value === 'object' ? JSON.stringify(value) : String(value)}` })
  }
  return words
}

/** "07-29 15:10 – 16:13 PDT" (one day), "07-28 17:01 PDT – 07-29 09:00 PDT", or "no runs". */
export function rangeLabel(start: string | null, end: string | null): string {
  if (!start && !end) return 'no runs'
  const from = formatLocal(start)
  const to = formatLocal(end)
  if (!from || !to || from === to) return from || to
  const zone = / (\S+)$/.exec(to)?.[1] ?? ''
  if (from.slice(0, 5) === to.slice(0, 5) && from.endsWith(` ${zone}`)) return `${from.slice(0, -zone.length - 1)} – ${to.slice(6)}`
  return `${from} – ${to}`
}

/** "26 real", "111 sim", "11 real · 2 aborted": the row's own counts, never derived. */
export function runsLabel(row: KpiTableRow): string {
  const counts = isObject(row.counts) ? row.counts : {}
  const parts: string[] = []
  if (typeof counts.real === 'number' && counts.real > 0) parts.push(`${counts.real} real`)
  if (typeof counts.sim === 'number' && counts.sim > 0) parts.push(`${counts.sim} sim`)
  if (typeof counts.aborted === 'number' && counts.aborted > 0) parts.push(`${counts.aborted} aborted`)
  return parts.length ? parts.join(' · ') : '0 runs'
}

/** "V0 2.65° · V1 0.529°": each twin version's re-run against the real run, in degrees (stored in rad). */
export function twinWords(entry: PlaybackEntry): string {
  if (!entry.twin_versions.length) return 'no twin re-run'
  return entry.twin_versions
    .map((version) => {
      const rad = entry.twin_vs_real_rms_rad[version]
      return `${version} ${typeof rad === 'number' ? formatValue(rad * RAD_TO_DEG, 'deg') : '—'}`
    })
    .join(' · ')
}
