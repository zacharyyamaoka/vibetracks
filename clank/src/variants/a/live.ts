// The live build's per-track fields (docs/dashboard/PROJECTION.md, "Track": reporting, needs_you_count, freshness,
// registry, purpose), read with guards because shared/model.ts's Track type does not declare them yet (a shared
// request: add them there; until then this file is variant A's only reader).
// WHY guards and not a cast at each use: a snapshot projection has none of these fields, and a missing field must read
// as "unknown", never as zero or as fine (truth rule 2).

import type { Projection, Track } from '../../shared'
import { blockingQuestions } from '../../shared'
import { latestDated, relativeDay } from './columns'

export interface Freshness {
  newest: string | null
  newest_source: string | null
  /** Wall-clock hours since the newest heartbeat file moved (never agent-hours). */
  age_h: number | null
  stall_hours: number | null
  /** null when no heartbeat file exists: unknown, never fine. */
  stale: boolean | null
  note: string | null
}

export interface RegistryInfo {
  status: string | null
  priority: number | null
  owner: string | null
  /** The note's revision; it fences a rename. */
  revision: string | null
  /** `{projector, sources}` or null ("No roadmap reported yet"). */
  roadmap: unknown
  note_path: string | null
}

const isObject = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value)
const str = (value: unknown): string | null => (typeof value === 'string' && value ? value : null)
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)

function field(track: Track, key: string): unknown {
  return (track as unknown as Record<string, unknown>)[key]
}

/** false only when the build says the adapter could not report; a snapshot track (no field) counts as reporting. */
export function isReporting(track: Track): boolean {
  return field(track, 'reporting') !== false
}

/** This track's own source kind ("live", "snapshot", "none"), when the build says. */
export function sourceKind(track: Track): string | null {
  const raw = field(track, 'source')
  return isObject(raw) ? str(raw.kind) : null
}

export function purposeOf(track: Track): string | null {
  return str(field(track, 'purpose'))
}

export function registryOf(track: Track): RegistryInfo | null {
  const raw = field(track, 'registry')
  if (!isObject(raw)) return null
  return {
    status: str(raw.status),
    priority: num(raw.priority),
    owner: str(raw.owner),
    revision: str(raw.revision),
    roadmap: raw.roadmap ?? null,
    note_path: str(raw.note_path),
  }
}

export function freshnessOf(track: Track): Freshness | null {
  const raw = field(track, 'freshness')
  if (!isObject(raw)) return null
  return {
    newest: str(raw.newest),
    newest_source: str(raw.newest_source),
    age_h: num(raw.age_h),
    stall_hours: num(raw.stall_hours),
    stale: typeof raw.stale === 'boolean' ? raw.stale : null,
    note: str(raw.note),
  }
}

/** `{open, blocking}`; each null when unknown (a track that has not reported has not said it needs nothing). */
export function needsCount(track: Track): { open: number | null; blocking: number | null } {
  const raw = field(track, 'needs_you_count')
  if (isObject(raw)) return { open: num(raw.open), blocking: num(raw.blocking) }
  // A snapshot track carries the questions themselves.
  return { open: track.needs_you.length, blocking: blockingQuestions(track).length }
}

/** "12 min ago", "5 h ago", "3 days ago": wall-clock age, as the build measured it on this request. */
export function formatAge(hours: number): string {
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min ago`
  if (hours < 48) return `${Math.round(hours)} h ago`
  return `${Math.round(hours / 24)} days ago`
}

export interface Moved {
  /** "12 min ago", "Yesterday", "unknown". */
  text: string
  /** What moved: the heartbeat source, or the iteration it was read from. */
  detail: string | null
  stale: boolean
  unknown: boolean
}

/** When the loop last moved: the live heartbeat when the build measured one, else the newest dated iteration. */
export function lastMoved(projection: Projection, track: Track): Moved {
  // WHY a deployment skips the heartbeat: the build hands a child its parent loop's freshness (the rig loop's
  // loop-status.json, minutes old), so CAN 16 read "last moved 6 min ago" while its newest real session is 07-28 —
  // a stale bench dressed as live. A deployment moves when it gains a session, so its own newest dated session is
  // the honest answer (integration check 2026-10-04).
  if (track.parent !== null) {
    const session = latestDated(track)
    if (!session) return { text: 'unknown', detail: 'no dated session', stale: false, unknown: true }
    return { text: relativeDay(session.date, projection.as_of), detail: `newest ${track.iteration.unit} · ${session.label}`, stale: false, unknown: false }
  }
  const fresh = freshnessOf(track)
  if (fresh) {
    if (fresh.age_h === null || fresh.stale === null) {
      return { text: 'unknown', detail: fresh.note ?? 'no heartbeat file found', stale: false, unknown: true }
    }
    const rule = fresh.stall_hours !== null ? `quiet past the ${fresh.stall_hours} h stall rule` : 'quiet past its stall rule'
    return {
      text: formatAge(fresh.age_h),
      detail: fresh.stale ? (fresh.note ? `${rule} · ${fresh.note}` : rule) : fresh.newest_source,
      stale: fresh.stale,
      unknown: false,
    }
  }
  const moved = latestDated(track)
  if (!moved) return { text: 'unknown', detail: 'no dated iteration', stale: false, unknown: true }
  return { text: relativeDay(moved.date, projection.as_of), detail: track.iteration.label, stale: false, unknown: false }
}
