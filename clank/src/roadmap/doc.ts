// The bam-roadmap/1 document as the widget reads it: the subset of the schema the board and the focus card use.
// Schema: bam_ws src/dev/bam_roadmap/schemas/bam-roadmap-1.schema.json. Types only, plus the schema id and a blank rung
// for graph.ts's test seam; the adapter to the board's model is docModel.ts.
//
// WHY typed fields and no text scraping: the kinsim dashboard read proof out of free text (proof.ts, retired). The
// format now carries the derived status, the loop's own word, typed criteria and evidence links that open, so the
// widget renders them as stored.

export const ROADMAP_SCHEMA = 'bam-roadmap/1'

/** Derived from evidence. `claimed`: the loop says green but its evidence does not prove it. */
export const RUNG_STATUSES = ['green', 'done', 'stale', 'claimed', 'partial', 'missing'] as const
export type RungStatus = (typeof RUNG_STATUSES)[number]
/** The loop's own word (status.json / ladder.json). */
export type ClaimedStatus = 'green' | 'done' | 'partial' | 'missing'
export type Verdict = 'met' | 'stale' | 'unknown' | 'unmet'
export type Strength = 'record' | 'log' | 'claim'

/** A path that opens: `abs` is set only when it exists now; otherwise `why_unresolved` says why. Lines are 1-based. */
export interface RoadmapLink {
  kind: string
  label: string | null
  path: string | null
  base: 'repo' | 'data_home' | 'abs' | null
  abs: string | null
  line: number | null
  end_line: number | null
  exists: boolean
  why_unresolved: string | null
}

export interface RoadmapSource extends RoadmapLink {
  pointer: string
}

/** One row of the loop's loop_events.jsonl, named by its physical line. */
export interface EventRef {
  path: string | null
  base: string | null
  abs: string | null
  line: number
  kind: string | null
  subject: string | null
  status: string | null
  ts: string | null
  commit: string | null
}

export interface RoadmapTarget extends RoadmapLink {
  verdict: Verdict
  strength: Strength | null
  evidence: string[]
  commit: string | null
  note: string
  changed_since: string[]
}

export interface RoadmapCriterion {
  id: string
  kind: string
  method: 'test' | 'analysis' | 'demonstration' | 'inspection' | null
  title: string
  text: string
  source: RoadmapSource | null
  targets: RoadmapTarget[]
  verdict: Verdict
  strength: Strength | null
  reason: string
  evidence: string[]
}

export interface RoadmapEvidence extends RoadmapLink {
  id: string
  result: 'passed' | 'warned' | 'failed' | 'error' | 'skipped' | null
  strength: Strength
  commit: string | null
  ts: string | null
  origin: string
  run_id?: string
  role: 'supports' | 'superseded' | 'context'
  superseded_by: string | null
  event: EventRef | null
}

export interface RoadmapHistoryRow {
  ts: string | null
  wave: number | null
  kind: string | null
  status: string | null
  commit: string | null
  detail: string
  evidence_text: string | null
  evidence: string[]
  event: EventRef
  /** The line of the later status event that replaced this one; null for the current one. */
  superseded_by: number | null
}

export interface RoadmapBlocker {
  id: string
  title: string
  default: string | null
  default_applies_after_wave: number | null
  source: RoadmapLink | null
}

export interface RoadmapKpi {
  name: string
  value: number | null
  unit: string | null
  run: string | null
  ts: string | null
}

export interface RoadmapRung {
  id: string
  axis: string
  title: string
  adds: string | null
  order: number
  wave: number | null
  depends_on: string[]
  alias_of: string | null
  status: RungStatus
  claimed_status: ClaimedStatus
  status_reason: string
  claimed_by: { source: RoadmapSource | null; event: EventRef | null }
  frontier: boolean
  done_when: { rule: 'all' | 'alias' | 'none'; text: string; source: RoadmapSource | null }
  criteria: RoadmapCriterion[]
  support: { evidence: string[]; runs: string[]; events: EventRef[]; commits: string[]; rungs: string[] }
  evidence: RoadmapEvidence[]
  history: RoadmapHistoryRow[]
  blockers: RoadmapBlocker[]
  kpis: RoadmapKpi[]
  notes: string[]
  /** Loop-specific extension (kinsim: cell, est_waves, gate, ...); never read by the status rule. */
  x: Record<string, unknown>
}

export interface RoadmapAxis {
  id: string
  title: string
  order: number
}

export interface RoadmapDoc {
  schema: typeof ROADMAP_SCHEMA
  loop: string
  title: string
  generated_at: string
  summary: { wave: number | null; phase: string | null; frontier: string[]; milestone: unknown; links: Record<string, unknown> }
  counts: { by_status: Record<RungStatus, number>; claimed_green_not_proven: string[]; evidence_items: number; unresolved_links: number }
  warnings: string[]
  axes: RoadmapAxis[]
  rungs: RoadmapRung[]
  edges: Array<{ from: string; to: string; kind: 'prerequisite' | 'same_as' | 'package'; via: string | null }>
}

/** A rung with every list empty: graph.ts's test seam (modelFromParts) builds its rungs from this. */
export function blankRung(id: string, axis: string, dependsOn: string[] = []): RoadmapRung {
  return {
    id, axis, title: id, adds: null, order: 0, wave: null, depends_on: dependsOn, alias_of: null, status: 'missing',
    claimed_status: 'missing', status_reason: '', claimed_by: { source: null, event: null }, frontier: false,
    done_when: { rule: 'none', text: '', source: null }, criteria: [], support: { evidence: [], runs: [], events: [], commits: [], rungs: [] },
    evidence: [], history: [], blockers: [], kpis: [], notes: [], x: {},
  }
}
