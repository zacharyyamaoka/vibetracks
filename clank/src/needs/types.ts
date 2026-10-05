// vibetracks-needs/1: what the backend's /needs route serves (vibetracks/dashboard/needs.py is the writer and the
// reference; docs/dashboard/NEEDS-KIT.md documents every field). Loops keep their own formats; this is a projection.

export const NEEDS_SCHEMA = 'vibetracks-needs/1'
export const NEEDS_ALL_SCHEMA = 'vibetracks-needs-all/1'

/** `approve` is grasping's leading "Approve the download" (needs.py `leading_options`); the rest are the loops'
 * implicit choices (bam-triage-answer/1). An item offers only some of them: read `item.options`, never assume one. */
export type Choice = 'accept_recommendation' | 'approve' | 'use_default' | 'other'
export const CHOICES: Choice[] = ['accept_recommendation', 'approve', 'use_default', 'other']

export type NeedsGroup = 'blocking' | 'no_default' | 'waiting' | 'defaulting' | 'answered' | 'done'
/** Page order of the groups; the backend already sorts items this way. */
export const GROUP_ORDER: NeedsGroup[] = ['blocking', 'no_default', 'waiting', 'defaulting', 'answered', 'done']
/** Plain words for each group, for headings. */
export const GROUP_LABEL: Record<NeedsGroup, string> = {
  blocking: 'Blocking now',
  no_default: 'Waiting for you (no default)',
  waiting: 'Default pending',
  defaulting: 'Defaulting without you',
  answered: 'Answered',
  done: 'Done',
}

export type AnswerChannelKind = 'jsonl_append' | 'http_post' | 'chat_paste' | 'note_paste' | 'none'

export interface AnswerChannel {
  kind: AnswerChannelKind
  /** A file path, URL, session or note: where an answer goes. */
  target: string | null
  /** `bam-triage-answer/1` when the loop reads machine rows (kinsim), else null. */
  row_schema: string | null
  read_back: string | null
  alternatives?: string[]
}

export interface NeedsOption {
  key: Choice
  /** The dashboard's words for the affordance (`source: "dashboard"`), never the loop's. */
  label: string
  /** `detail_md` is the only loop text in an option (the recommendation or the default, verbatim), or null. */
  source?: 'dashboard'
  detail_md: string | null
  recommended: boolean
  is_default: boolean
  needs_note?: boolean
}

export interface NeedsDefault {
  text_md: string
  /** `never` = no default recorded (`text_md` is ""). `unstated` = there is a default, but the source never says when
   * it fires (`after` is null): show "when: not stated", never "after unstated null". Read it through appliesAfter(). */
  applies: { unit: 'wave' | 'tick' | 'date' | 'never' | 'unstated'; after: number | null }
  /** Computed by the backend against the loop's finished iteration; never trust `status` alone. */
  state: 'pending' | 'in_effect' | 'none'
}

export interface NeedsBlock {
  id: string
  kind: 'rung' | 'cell' | 'lane' | 'package' | 'milestone' | 'hardware'
  label: string | null
}

export interface NeedsEvidence {
  label: string
  kind: 'path' | 'file_line' | 'url' | 'report' | 'command' | 'run'
  /** Absolute path (with `#L<n>` for file_line) or URL. */
  value: string
  path?: string
  line?: number | null
  is_dir?: boolean
}

export interface NeedsAnswer {
  choice: Choice | null
  note: string
  ts: string | null
  /** null when the loop marked the item answered without recording Zach's words. */
  by: 'zach' | null
  channel: AnswerChannelKind
  /** true once the integrator folded it into the loop's own file. */
  folded: boolean
  action_md: string | null
  /** false when the note is the integrator's paraphrase rather than Zach's quoted words. */
  quoted: boolean
}

export interface NeedsUpdate {
  header: string
  text_md: string
}

export interface NeedsItem {
  /** `<track>:<local_id>`, globally unique. */
  id: string
  /** What the loop calls it (T47); used verbatim in exports. */
  local_id: string
  kind: 'decision' | 'approval' | 'physical_action' | 'ruling' | 'fyi'
  title: string
  /** One-line ask; falls back to the title. */
  ask: string
  /** The loop's full question text, verbatim. Fold it by default. */
  context_md: string
  /** ≤200 chars, only when the loop emits one; the dashboard never invents it. */
  context_summary: string | null
  /** context_md minus its appended `UPDATE …:` paragraphs. */
  context_base_md: string
  /** The first sentence of the base that says why (a verbatim slice, not a summary). */
  context_lead_md: string | null
  /** A leading "Filed at wave-N close from …" sentence, split off verbatim. */
  provenance_md: string | null
  /** Appended `UPDATE <header>: …` paragraphs, oldest first (rig items grow this way). */
  updates: NeedsUpdate[]
  options: NeedsOption[]
  recommendation_md: string
  default: NeedsDefault
  blocks: NeedsBlock[]
  blocking_now: boolean
  group: NeedsGroup
  evidence: NeedsEvidence[]
  asked_by: { agent: string | null; session: string | null; account: string | null }
  created: { iteration: number | null; ts: string | null }
  updated: { ts: string | null; note: string | null }
  /** Effective status: an answer row the integrator has not folded yet already reads `answered`. */
  status: 'open' | 'answered' | 'defaulted' | 'closed' | 'superseded'
  /** The loop file's own status word. */
  raw_status: string
  answer: NeedsAnswer | null
  effort: string | null
}

/** Every value is null on a doc with no structured source ("not reported", never 0). Headers read them through
 * headerCounts() (kit.ts), never by summing fields: `no_default` also counts blocking items that have no default. */
export interface NeedsCounts {
  open: number | null
  blocking_now: number | null
  /** Items that still want Zach: groups blocking + no_default + waiting (open items whose default is NOT already in
   * effect). The ONE number every "M open" in the dashboard shows (home cell, track page, needs page header). Optional
   * only until every backend sends it; read it through headerCounts(). */
  wants_you?: number | null
  no_default: number | null
  waiting: number | null
  defaulting: number | null
  answered: number | null
  defaulted: number | null
  closed: number | null
  total: number | null
}

export interface NeedsDoc {
  schema: typeof NEEDS_SCHEMA
  track: string
  track_title: string
  generated_at: string
  iteration: { unit: string; n: number | null; phase: string | null; finished: number | null } | null
  source: { adapter: string; paths: string[]; commit: string | null; live: boolean; note: string | null }
  answer_channel: AnswerChannel
  counts: NeedsCounts
  items: NeedsItem[]
}

export interface NeedsAll {
  schema: typeof NEEDS_ALL_SCHEMA
  generated_at: string
  tracks: NeedsDoc[]
}

/** Items that still want something from Zach (blocking, no default, default pending), in page order. */
export function openAsks(doc: NeedsDoc): NeedsItem[] {
  return doc.items.filter((item) => item.group === 'blocking' || item.group === 'no_default' || item.group === 'waiting')
}

/** The "M open" of "B blocking · M open": counts.wants_you, else the same groups counted from the items. */
export function wantsYouCount(doc: NeedsDoc): number {
  return typeof doc.counts.wants_you === 'number' ? doc.counts.wants_you : openAsks(doc).length
}

export function itemsInGroup(doc: NeedsDoc, group: NeedsGroup): NeedsItem[] {
  return doc.items.filter((item) => item.group === group)
}

/** The words for a default the source does not have ("no default recorded") and for one whose timing it never states
 * ("when: not stated"). WHY shared: every proposal used to print the raw unit ("after unstated null"). */
export const NO_DEFAULT_RECORDED = 'no default recorded'
export const WHEN_NOT_STATED = 'when: not stated'

/** True when the item has a default text (unit is not `never`). */
export function hasDefault(item: NeedsItem): boolean {
  return item.default.applies.unit !== 'never'
}

/** "after wave 5" in the loop's own unit, or null when the source does not say when (unit `never` or `unstated`, or
 * no number recorded). Callers show WHEN_NOT_STATED (or NO_DEFAULT_RECORDED) for null; never the raw unit. */
export function appliesAfter(item: NeedsItem): string | null {
  const { unit, after } = item.default.applies
  if (unit === 'never' || unit === 'unstated' || after === null || after === undefined) return null
  return `after ${unit} ${after}`
}

/** "applies after wave 5", "in effect (after wave 4)", "no default recorded", "when: not stated". */
export function describeDefault(item: NeedsItem): string {
  if (!hasDefault(item)) return NO_DEFAULT_RECORDED
  const after = appliesAfter(item)
  if (item.default.state === 'in_effect') return `in effect (${after ?? WHEN_NOT_STATED})`
  return after ? `applies ${after}` : WHEN_NOT_STATED
}
