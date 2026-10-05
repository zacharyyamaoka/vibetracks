// vibetracks-needs/1: what the backend's /needs route serves (vibetracks/dashboard/needs.py is the writer and the
// reference; docs/dashboard/NEEDS-KIT.md documents every field). Loops keep their own formats; this is a projection.

export const NEEDS_SCHEMA = 'vibetracks-needs/1'
export const NEEDS_ALL_SCHEMA = 'vibetracks-needs-all/1'

export type Choice = 'accept_recommendation' | 'use_default' | 'other'
export const CHOICES: Choice[] = ['accept_recommendation', 'use_default', 'other']

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
  label: string
  detail_md: string | null
  recommended: boolean
  is_default: boolean
  needs_note?: boolean
}

export interface NeedsDefault {
  text_md: string
  /** `never` = the loop waits for Zach (a "No default" item). */
  applies: { unit: 'wave' | 'tick' | 'date' | 'never'; after: number | null }
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

export interface NeedsCounts {
  open: number
  blocking_now: number
  no_default: number
  waiting: number
  defaulting: number
  answered: number
  defaulted: number
  closed: number
  total: number
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

export function itemsInGroup(doc: NeedsDoc, group: NeedsGroup): NeedsItem[] {
  return doc.items.filter((item) => item.group === group)
}

/** "after wave 5", "never (waits for you)", "in effect since wave 4". */
export function describeDefault(item: NeedsItem): string {
  const { applies, state } = item.default
  if (applies.unit === 'never') return 'no default: waits for you'
  if (state === 'in_effect') return `in effect (after ${applies.unit} ${applies.after})`
  return `applies after ${applies.unit} ${applies.after}`
}
