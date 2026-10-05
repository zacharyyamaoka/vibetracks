// Proposal N6 · "Lane + context": the judges' splice of N1 (Zen mode) and N2 (Inbox + reading pane).
//
// N1's lane is the shell: the page opens ON the first question, focus is taken on mount, and the keyboard answers it
// (↵ takes the recommendation, 1-3 pick an option, N writes a note, S marks later, J/K move, C jumps to the end and
// copies, Esc leaves), auto-advancing after a visible confirm, ending on a screen that lists every card and holds the
// one Copy action. N2's context is grafted onto every card: one compact fact line above the options, and the loop's
// full verbatim context directly under them, open, no keypress.
//
// WHY the card reads eyebrow → question → why → (latest update) → one fact line → options → full context: Zach,
// 2026-10-04: "within 1 click … start addressing these … I need enough context though to actually like provide
// feedback". The judges measured the earlier N6 pushing its options below the fold at 1280x800 with a 4-row fact grid
// and a nine-button key rail; the question and every option must now sit on the first screen, and the context that
// is too long for it is the scroll right below, never behind a key.
// WHY only the newest UPDATE above the options, and AFTER the why: rig items grow by appended UPDATE paragraphs (rig T2
// has five). The newest says what changed and must be on the first screen, but leading with it (round 2) pushed the
// thing being decided into second place under "Originally"; the round-2 judge asked for decision first, then
// "Latest update · <header>:". The earlier updates sit in the context below, once.
// WHY the header counts come from needs.py's counts (blocking_now, wants_you) and read "N blocking · M open": the number
// Zach clicked on the home cell must be the number he lands on, in the same words; a second arithmetic here is how
// grasping once read "7 open" on the cell and opened onto an empty page.
// WHY the lane position lives in component state, not the route: every earlier proposal's private key (zen=, ask=,
// n4card=, n5=) leaked into the dashboard's route after leaving the page. Moving between cards is sideways, so
// nothing here belongs in Back's history anyway; drafts persist through the answer store.
// WHY drafts and one Copy, never a Send: the backend is read-only and the loops read answers from their own channels
// (kinsim's jsonl, rig's chat). There is deliberately no control that pretends to submit.

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import {
  CopyOut,
  EvidenceLink,
  GROUP_LABEL,
  WHEN_NOT_STATED,
  appliesAfter,
  choiceLabel,
  effectiveChoice,
  isComplete,
  type AnswerStore,
  type Choice,
  type NeedsDoc,
  type NeedsGroup,
  type NeedsItem,
  type NeedsProposalProps,
  headerCounts,
  headerSummary,
} from '../kit'
import { formatLocal } from '../../shared/time'
import { Inline, Md } from './md'
// WHY a style/ subfolder (as N4 has): the running Vite caches n6/'s directory listing from before the CSS existed and
// would not resolve a sibling file added later; a new folder is read fresh. Harmless after a restart.
import './style/n6.css'

export const NAME = 'Lane + context'

interface Entry {
  doc: NeedsDoc
  item: NeedsItem
}

/** The groups that want something from Zach: exactly the frozen contract's `wants_you`. */
const WANT_GROUPS: NeedsGroup[] = ['blocking', 'no_default', 'waiting']
/** WHY "defaulting" is outside the lane until asked for: its default is already in effect, so it needs nothing from
 *  Zach; putting kinsim's eight in the lane would bury the three that do. One press on the end screen adds them. */
const ALL_GROUPS: NeedsGroup[] = [...WANT_GROUPS, 'defaulting']
/** How long the picked option stays visibly pressed before the next card slides in. */
const CONFIRM_MS = 380
/** WHY at most three blocked ids on the fact line: grasping's model items block 11 cells each, and a wall of ids pushed
 *  the options off the first screen; "+8 more" expands in place, and the context below lists every one with its label. */
const BLOCKS_SHOWN = 3

function buildQueue(docs: NeedsDoc[], includeDefaulting: boolean): Entry[] {
  const groups = includeDefaulting ? ALL_GROUPS : WANT_GROUPS
  const entries: Entry[] = []
  // One track: needs.py's own order. Several: by what an item holds (group) before which track it is in.
  for (const group of groups) for (const doc of docs) for (const item of doc.items) if (item.group === group) entries.push({ doc, item })
  return entries
}

// ---- answers that can only name options that exist ---------------------------------------------------------------

/**
 * The answer store as this lane reads it: a draft whose choice names an option the item does not offer (a stale
 * "accept_recommendation" on a grasping item that has no recommendation, written by another proposal or an older
 * build) loses that choice. WHY a read-side wrapper and not a cleanup write: the store is shared with N1-N5, and
 * nothing here should rewrite what another view saved; but nothing this lane shows or copies may name an option the
 * loop never offered. A note left behind follows the kit's own rule (a note alone is "something else").
 */
function useOfferedAnswers(answers: AnswerStore, docs: NeedsDoc[]): AnswerStore {
  const offered = useMemo(() => {
    const map = new Map<string, Set<Choice>>()
    for (const doc of docs) for (const item of doc.items) map.set(`${doc.track}\u0000${item.local_id}`, new Set(item.options.map((option) => option.key)))
    return map
  }, [docs])
  return useMemo<AnswerStore>(
    () => ({
      ...answers,
      get(track: string, localId: string) {
        const draft = answers.get(track, localId)
        const keys = offered.get(`${track}\u0000${localId}`)
        if (!draft || !keys || !draft.choice || keys.has(draft.choice)) return draft
        // Only the note survives, and only where "something else" is an option it can stand for.
        return draft.note.trim() && keys.has('other') ? { ...draft, choice: null } : null
      },
    }),
    [answers, offered],
  )
}

// ---- the counts contract ----------------------------------------------------------------------------------------

/** A track with no structured needs source reports no counts: "not reported", never 0 (the kit's headerCounts). */
function isReported(doc: NeedsDoc): boolean {
  return headerCounts(doc) !== null
}

function groupCount(doc: NeedsDoc, group: NeedsGroup): number {
  return doc.items.filter((item) => item.group === group).length
}

function Header({ docs, track, loading }: { docs: NeedsDoc[]; track: string | null; loading: boolean }) {
  const title = track ? (docs[0]?.track_title ?? track) : 'Every track'
  // needs.py's two numbers (blocking_now, wants_you) through the kit's one reader, so this header, the home cell and
  // the track page can never disagree.
  const summary = headerSummary(docs)
  const sum = summary.counts
  let line: ReactNode
  let blockingAttr = 'null'
  let openAttr = 'null'
  if (loading && !docs.length) line = <span className="vt-faint">Reading the loops…</span>
  else if (!sum) line = <span className="vt-muted">not reported: {docs.length === 1 ? 'this loop has' : 'these loops have'} no structured questions yet</span>
  else {
    blockingAttr = String(sum.blocking)
    openAttr = String(sum.open)
    // The home cell's words exactly ("N blocking · M open"); colour only when something is blocking.
    line = (
      <>
        <span className={sum.blocking ? 'vt-tone-warn' : undefined}>
          <span className="vt-num">{sum.blocking}</span> blocking
        </span>
        <span> · </span>
        <span className="vt-num">{sum.open}</span> open
        {sum.defaulting ? <span className="vt-faint"> · {sum.defaulting} more defaulting without you</span> : null}
        {summary.notReported.length ? <span className="vt-faint"> · not reported: {summary.notReported.map((doc) => doc.track_title).join(', ')}</span> : null}
      </>
    )
  }
  return (
    <header className="n6-head" data-testid="vt-n6-head" data-blocking={blockingAttr} data-open={openAttr}>
      <h1 className="n6-head-title">{title}</h1>
      <p className="n6-head-counts vt-small" data-testid="vt-n6-head-counts">
        {line}
      </p>
    </header>
  )
}

// ---- small text helpers -----------------------------------------------------------------------------------------

/** When the default fires, in full, for the context's fact rows. Computed against the loop's progress, so it says so. */
function whenText(doc: NeedsDoc, item: NeedsItem): string {
  const { applies, state } = item.default
  const due = appliesAfter(item)
  const at = doc.iteration ? `the loop has finished ${doc.iteration.unit} ${doc.iteration.finished ?? '(not reported)'}` : null
  if (applies.unit === 'never') return 'Never. This waits for you.'
  // WHY "Not stated by the loop" and never the raw word: detection's plan note gives a default but no time, and the old
  // line read "After unstated null". WHY not the kit's "when: not stated" here: this sits in a row already labelled
  // When, and the judges read "When / when: not stated" (the fact line above the options keeps the kit's words).
  if (!due) return 'Not stated by the loop.'
  if (state === 'in_effect') return `In effect now: due ${due}, and ${at ?? 'that has passed'} (computed by the dashboard).`
  return `Due ${due}${at ? `; ${at}` : ''}.`
}

function defaultOptionIndex(item: NeedsItem): number {
  return item.options.findIndex((option) => option.is_default)
}

/** True when the default's own text is the default option's detail, so it is already printed in the option. */
function defaultIsOption(item: NeedsItem): boolean {
  const index = defaultOptionIndex(item)
  if (index < 0) return false
  return (item.options[index].detail_md ?? '').trim() === (item.default.text_md ?? '').trim()
}

/** The fact line's "If silent" clause: names the option by its number instead of repeating its words. */
function silentText(item: NeedsItem): ReactNode {
  const index = defaultOptionIndex(item)
  const option = index >= 0 ? `option ${index + 1}` : null
  if (item.default.applies.unit === 'never') return 'it waits for you'
  if (!option && !item.default.text_md) return <span className="vt-faint">no default stated</span>
  const what: ReactNode = option && defaultIsOption(item) ? option : <Inline text={item.default.text_md} />
  const due = appliesAfter(item)
  if (item.default.state === 'in_effect') return <>{what} is in effect{due ? ` (due ${due})` : ''}</>
  return due ? (
    <>
      {what} {due}
    </>
  ) : (
    <>
      {what} · <span className="vt-faint">{WHEN_NOT_STATED}</span>
    </>
  )
}

function openedText(doc: NeedsDoc, item: NeedsItem): string {
  const parts: string[] = []
  if (item.created.iteration !== null) parts.push(`${doc.iteration?.unit ?? 'iteration'} ${item.created.iteration}`)
  if (item.created.ts) parts.push(formatLocal(item.created.ts))
  if (!parts.length) parts.push('not recorded by the loop')
  if (item.updated.ts && item.updated.ts !== item.created.ts) parts.push(`updated ${formatLocal(item.updated.ts)}`)
  if (item.asked_by.agent) parts.push(`asked by ${item.asked_by.agent}`)
  return parts.join(' · ')
}

/** The fact line's short form: "wave 3 · 10-02", the full stamp one hover away. */
function OpenedShort({ doc, item }: { doc: NeedsDoc; item: NeedsItem }) {
  const parts: ReactNode[] = []
  if (item.created.iteration !== null) parts.push(`${doc.iteration?.unit ?? 'iteration'} ${item.created.iteration}`)
  if (item.created.ts)
    parts.push(
      <span key="ts" title={formatLocal(item.created.ts, { year: true })}>
        {formatLocal(item.created.ts, { dateOnly: true })}
      </span>,
    )
  const updated = item.updated.ts && item.updated.ts !== item.created.ts ? item.updated.ts : null
  return (
    <>
      {parts.length ? (
        <>
          Opened{' '}
          {parts.map((part, position) => (
            <span key={position}>
              {position ? ' · ' : ''}
              {part}
            </span>
          ))}
        </>
      ) : (
        <span className="vt-faint">Opened: not recorded</span>
      )}
      {updated ? (
        <span title={formatLocal(updated, { year: true })}>
          {' · updated '}
          {formatLocal(updated, { dateOnly: true })}
        </span>
      ) : null}
    </>
  )
}

/**
 * The context body below the options, without what the card already printed above them: the provenance sentence (its
 * own quiet line), the question when the body opens with it (detection's asks are the body's first sentence), and the
 * why lead. WHY strip only where the body STARTS with these: there they are the same words twice; where the lead is a
 * sentence from the middle (grasping's "- Notes: Needs a download"), cutting it would break the verbatim body, so the
 * body stays whole. `trimmed` says whether anything was taken, so an empty rest is never mistaken for "no context".
 */
function contextRemainder(item: NeedsItem): { body: string; trimmed: boolean; leadTaken: boolean; lifted: string | null } {
  const base = item.context_base_md || item.context_md
  let body = (item.provenance_md && base.startsWith(item.provenance_md) ? base.slice(item.provenance_md.length) : base).trim()
  let trimmed = false
  const take = (prefix: string | null | undefined) => {
    const text = prefix?.trim()
    if (text && body.startsWith(text)) {
      body = body.slice(text.length).trim()
      trimmed = true
      return true
    }
    return false
  }
  if (!take(item.ask)) {
    // An older shape: the body opens with the question as a bold title ("**Data.** …") and the ask is its plain words.
    const title = body.match(/^\*\*([^*\n]+)\*\*\s*/)
    const lead = item.context_lead_md?.trim()
    if (title && lead && [item.ask, item.title].some((text) => text.trim() === title[1].trim()) && body.slice(title[0].length).startsWith(lead)) {
      body = body.slice(title[0].length)
      trimmed = true
    }
  }
  const leadTaken = take(item.context_lead_md)
  const lead = item.context_lead_md?.trim()
  if (!leadTaken && lead) {
    // WHY lift the body's opening block when the lead sits inside it (grasping: "**GG-CNN (planar, Cornell)**" then
    // "- Licence: BSD-3" / "- Notes: Needs a download …"): those lines are what an approval rests on, and the judges
    // found them only in Full context, under the note box, while the card above the options said nothing. The block is
    // cut from the START of the body, so what stays below is still the verbatim rest and nothing prints twice.
    const at = body.indexOf(lead)
    const blockEnd = at >= 0 ? body.indexOf('\n\n', at + lead.length) : -1
    const block = at >= 0 ? (blockEnd >= 0 ? body.slice(0, blockEnd) : body).trim() : ''
    if (block && block.length <= LIFT_MAX_CHARS) {
      body = body.slice(block.length).trim()
      return { body, trimmed: true, leadTaken: true, lifted: block }
    }
  }
  return { body, trimmed, leadTaken, lifted: null }
}

/** WHY a cap on the lifted block: it lives above the options, so a lead buried deep in a long body stays where it is
 *  (the body below is verbatim and whole) rather than dragging half the context above the fold. */
const LIFT_MAX_CHARS = 480

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || Boolean(target.closest('.cm-editor'))
}

/**
 * Text clamped to a few lines with an explicit "…more" that opens it in place (and "less" to close).
 * WHY not CSS line-clamp alone: the browser's ellipsis is easy to miss and is not a control; a clamp must say that it
 * hides something and give the whole text back in one click (truthful rendering).
 */
function Clamp({ lines, children, testId }: { lines: number; children: ReactNode; testId?: string }) {
  const [open, setOpen] = useState(false)
  const [over, setOver] = useState(false)
  const body = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const element = body.current
    if (!element || open) return
    const check = () => setOver(element.scrollHeight > element.clientHeight + 2)
    check()
    const observer = new ResizeObserver(check)
    observer.observe(element)
    return () => observer.disconnect()
  }, [open, children])
  return (
    <div className="n6-clamp" data-open={open} data-over={over} data-testid={testId} style={{ ['--n6-lines' as string]: lines }}>
      <div ref={body} className="n6-clamp-body">
        {children}
      </div>
      {over && !open ? (
        <button type="button" className="vt-btn n6-clamp-more" onClick={() => setOpen(true)} data-testid={testId ? `${testId}-more` : undefined}>
          …more
        </button>
      ) : null}
      {open ? (
        <button type="button" className="vt-btn n6-clamp-less vt-small" onClick={() => setOpen(false)}>
          less
        </button>
      ) : null}
    </div>
  )
}

// ---- the lane ---------------------------------------------------------------------------------------------------

export default function NeedsLaneContext(props: NeedsProposalProps) {
  const { docs, track, loading, error, onBack } = props
  const answers = useOfferedAnswers(props.answers, docs)
  const [includeDefaulting, setIncludeDefaulting] = useState(false)
  const queue = useMemo(() => buildQueue(docs, includeDefaulting), [docs, includeDefaulting])
  const defaultingCount = useMemo(() => docs.reduce((sum, doc) => sum + groupCount(doc, 'defaulting'), 0), [docs])
  // Position: an item id, 'end', or null for "the first card".
  const [position, setPosition] = useState<string | null>(null)
  const atEnd = position === 'end'
  const found = queue.findIndex((entry) => entry.item.id === position)
  const index = atEnd ? queue.length : found >= 0 ? found : 0
  const current = !atEnd && queue.length ? queue[index] : null

  // "Later" is a session-only mark: visible on the ticks and the end screen, never exported.
  const [later, setLater] = useState<Set<string>>(() => new Set())
  // WHY a set of cards actually shown, not the position: c jumps to the end from card 3 of 7, and the progress line
  // read "All 7 seen" while the end screen listed five unanswered. "Seen" means the card was on screen.
  const [seen, setSeen] = useState<Set<string>>(() => new Set())
  const [legend, setLegend] = useState(false)
  // WHY the lane resets when the route's track changes: the shell keeps this component mounted across tracks, and a
  // lane left at 'end' on grasping opened detection on its end screen, past three unanswered questions.
  const [laneTrack, setLaneTrack] = useState(track)
  if (laneTrack !== track) {
    setLaneTrack(track)
    setPosition(null)
    setLater(new Set())
    setSeen(new Set())
    setIncludeDefaulting(false)
  }
  const [hint, setHint] = useState<string | null>(null)
  const [flash, setFlash] = useState<Choice | null>(null)
  const [copyRequest, setCopyRequest] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const note = useRef<HTMLTextAreaElement>(null)
  const timer = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    },
    [],
  )

  // Focus moves into the lane once the queue arrives, so the keys work from the first frame. WHY only from <body> or
  // from inside this dashboard: Clank swallows single-letter keys aimed at <body>, but focus sitting in another panel
  // (an editor Zach is typing in) is his and is left alone. In-page focus only; no window is fronted.
  const hasQueue = queue.length > 0
  useEffect(() => {
    const lane = root.current
    if (!lane) return
    const active = document.activeElement
    const ours = !active || active === document.body || (lane.closest('.vt-dash')?.contains(active) && !isEditable(active))
    if (ours) lane.focus({ preventScroll: true })
    // A cold app load can drop focus back to <body> after this mount (workspace restore); re-check twice, taking
    // focus only from <body>, never from another element.
    const retries = [300, 1200].map((delay) =>
      window.setTimeout(() => {
        if (document.activeElement === document.body && root.current?.isConnected) root.current.focus({ preventScroll: true })
      }, delay),
    )
    return () => retries.forEach((id) => window.clearTimeout(id))
  }, [hasQueue])

  const currentId = current?.item.id ?? null
  useEffect(() => {
    if (!currentId) return
    setSeen((previous) => (previous.has(currentId) ? previous : new Set(previous).add(currentId)))
  }, [currentId])

  useEffect(() => {
    setHint(null)
    setFlash(null)
    root.current?.closest('.vt-scroll')?.scrollTo({ top: 0 })
  }, [current?.item.id, atEnd])

  const goTo = useCallback(
    (next: number) => {
      if (!queue.length) return
      setPosition(next >= queue.length ? 'end' : queue[Math.max(0, next)].item.id)
      root.current?.focus({ preventScroll: true })
    },
    [queue],
  )

  const unmarkLater = useCallback((id: string) => {
    setLater((previous) => {
      if (!previous.has(id)) return previous
      const next = new Set(previous)
      next.delete(id)
      return next
    })
  }, [])

  const advance = useCallback(
    (choice: Choice, id: string) => {
      unmarkLater(id)
      // A visible beat: the picked option stays pressed and the status line says so before the card peels off.
      setFlash(choice)
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => {
        timer.current = null
        goTo(index + 1)
      }, CONFIRM_MS)
    },
    [goTo, index, unmarkLater],
  )

  const choose = useCallback(
    (choice: Choice) => {
      if (!current) return
      const { doc, item } = current
      // Never record an option the loop did not offer.
      if (!item.options.some((option) => option.key === choice)) return
      const draft = answers.get(doc.track, item.local_id)
      answers.set(doc.track, item.local_id, { choice })
      if (choice === 'other' && !draft?.note.trim()) {
        setHint('Write your answer, then press ↵ to save it and go on.')
        note.current?.focus()
        return
      }
      advance(choice, item.id)
    },
    [advance, answers, current],
  )

  /**
   * ↵: on an untouched card it takes the loop's recommended option; otherwise it saves what is there and goes on.
   * WHY ↵ opens the note where nothing is recommended (grasping, detection): the old ↵ recorded
   * "accept_recommendation" on items that offer no recommendation, and Copy then exported an option that did not exist.
   */
  const enter = useCallback(() => {
    if (!current) return
    const { doc, item } = current
    const draft = answers.get(doc.track, item.local_id)
    if (!effectiveChoice(draft)) {
      const recommended = item.options.find((option) => option.recommended)
      if (recommended) return choose(recommended.key)
      setHint(`Nothing is recommended here: pick ${item.options.length > 1 ? `1–${item.options.length}` : '1'}, or write your answer.`)
      note.current?.focus()
      return
    }
    if (!isComplete(draft)) {
      setHint('"Something else" needs a few words; write them, or pick another option.')
      note.current?.focus()
      return
    }
    advance(effectiveChoice(draft) as Choice, item.id)
  }, [advance, answers, choose, current])

  const skip = useCallback(() => {
    if (!current) return
    const id = current.item.id
    setLater((previous) => new Set(previous).add(id))
    goTo(index + 1)
  }, [current, goTo, index])

  const copyAll = useCallback(() => {
    if (queue.length) setPosition('end')
    setCopyRequest((n) => n + 1)
  }, [queue.length])

  // The end screen's Copy is the kit's own CopyOut (clipboard, then a pre-selected textarea); C presses it.
  useEffect(() => {
    if (!copyRequest || (!atEnd && queue.length)) return
    const button = root.current?.querySelector<HTMLButtonElement>('[data-testid="vt-needs-copy"]')
    if (button && !button.disabled) button.click()
    const shown = window.setTimeout(() => root.current?.querySelector('.vt-needs-copy-result')?.scrollIntoView({ block: 'center' }), 120)
    return () => window.clearTimeout(shown)
  }, [copyRequest, atEnd, queue.length])

  const keyHandler = useRef<(event: KeyboardEvent) => void>(() => undefined)
  keyHandler.current = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.altKey || event.metaKey) return
    const lane = root.current
    if (!lane) return
    const target = event.target
    const inside = target instanceof Node && Boolean(lane.contains(target))
    const inDash = target instanceof Node && Boolean(lane.closest('.vt-dash')?.contains(target))
    const onBody = target === document.body || target === document.documentElement
    if (!inDash && !onBody) return
    const key = event.key
    const handled = (fn: () => void) => {
      event.preventDefault()
      event.stopPropagation()
      fn()
    }
    if (target === note.current) {
      if (key === 'Enter' && !event.shiftKey) handled(enter)
      else if (key === 'Escape') handled(() => lane.focus({ preventScroll: true }))
      return
    }
    // WHY Esc leaves straight from the copied-answers box: it is read-only, so there is nothing to lose, and "Esc
    // leaves" stays true everywhere except the one box Zach writes in (where Esc returns to the keys).
    const readOnlyBox = inside && target instanceof HTMLTextAreaElement && target.readOnly
    if (key === 'Escape' && (readOnlyBox || !isEditable(target))) return handled(onBack)
    if (isEditable(target) || event.ctrlKey) return
    // A focused link or button keeps its own Enter/Space (an evidence link, "…more", the copy button, the switcher).
    if ((key === 'Enter' || key === ' ') && target instanceof HTMLElement && target.closest('a, button')) return
    if (key === '?') return handled(() => setLegend((value) => !value))
    if (key === 'j' || key === 'ArrowRight') return handled(() => goTo(index + 1))
    if (key === 'k' || key === 'ArrowLeft') return handled(() => goTo(index - 1))
    if (key === 'c' && !event.shiftKey) return handled(copyAll)
    if (!current) return
    if (key === 'Enter') return handled(enter)
    if (key === 's') return handled(skip)
    if (key === 'n') return handled(() => note.current?.focus())
    const number = ['1', '2', '3', '4', '5', '6', '7', '8', '9'].indexOf(key)
    // WHY capture + preventDefault on the digits: the dashboard's own 1/2/3 switch the A · B · C layout; in the lane
    // they pick an option, and the dashboard's listener skips a defaultPrevented key.
    if (number >= 0 && current.item.options[number]) return handled(() => choose(current.item.options[number].key))
  }
  useEffect(() => {
    const listener = (event: KeyboardEvent) => keyHandler.current(event)
    window.addEventListener('keydown', listener, true)
    return () => window.removeEventListener('keydown', listener, true)
  }, [])

  const draftOfCurrent = current ? answers.get(current.doc.track, current.item.local_id) : null
  const keys = queue.length ? (
    <KeyLine
      mode={atEnd || !current ? 'end' : 'card'}
      item={current?.item ?? null}
      hasDraft={Boolean(effectiveChoice(draftOfCurrent))}
      legend={legend}
      onToggleLegend={() => setLegend((value) => !value)}
    />
  ) : null

  let body: ReactNode
  if (loading && !docs.length) body = <p className="vt-muted n6-quiet">Reading the loops…</p>
  else if (error && !docs.length) body = <p className="vt-tone-risk n6-quiet">/needs did not answer: {error}</p>
  else if (!queue.length) body = <EmptyLane docs={docs} defaultingCount={defaultingCount} includeDefaulting={includeDefaulting} onIncludeDefaulting={() => setIncludeDefaulting(true)} />
  else if (atEnd || !current)
    body = (
      <EndScreen
        {...props}
        answers={answers}
        queue={queue}
        later={later}
        keys={keys}
        defaultingCount={defaultingCount}
        includeDefaulting={includeDefaulting}
        onJump={goTo}
        onIncludeDefaulting={() => {
          const first = buildQueue(docs, true).find((entry) => entry.item.group === 'defaulting')
          setIncludeDefaulting(true)
          setPosition(first?.item.id ?? 'end')
        }}
      />
    )
  else
    body = (
      <Card
        {...props}
        answers={answers}
        key={current.item.id}
        entry={current}
        keys={keys}
        onChoose={choose}
        flash={flash}
        hint={hint}
        noteRef={note}
        onClear={() => {
          props.answers.clear(current.doc.track, current.item.local_id)
          setHint(null)
        }}
      />
    )

  return (
    <div ref={root} className="vt-needs-n6" tabIndex={-1} data-testid="vt-needs-n6" data-n6-item={current?.item.id ?? (atEnd ? 'end' : '')}>
      <div className="n6-main">
        <Header docs={docs} track={track} loading={loading} />
        {queue.length ? <Progress queue={queue} index={index} atEnd={atEnd || !current} later={later} seen={seen} answers={answers} onJump={goTo} /> : null}
        <div className="n6-stage">{body}</div>
      </div>
    </div>
  )
}

/**
 * One quiet line of keys under the options, the full legend one "?" away.
 * WHY not the nine-button rail it replaces: the rail stacked above the header below 1180 px and pushed the options off
 * the first screen, and two of its entries were labels dressed as buttons. The line is plain text; the only control in
 * it is "? keys", which really toggles the legend. Every recommendation word disappears where nothing is recommended.
 */
function KeyLine({ mode, item, hasDraft, legend, onToggleLegend }: { mode: 'card' | 'end'; item: NeedsItem | null; hasDraft: boolean; legend: boolean; onToggleLegend(): void }) {
  const count = item?.options.length ?? 0
  const pick = count > 1 ? `1–${count} pick` : count === 1 ? '1 pick' : null
  const recommended = Boolean(item?.options.some((option) => option.recommended))
  const enterWord = hasDraft ? 'save and next' : recommended ? 'take recommendation' : 'write a note'
  const parts: string[] =
    mode === 'end' ? ['k back to the last card', 'c copy all', 'Esc leave'] : [`↵ ${enterWord}`, ...(pick ? [pick] : []), 'n note', 's later', 'c copy']
  return (
    <div className="n6-keys vt-small" data-testid="vt-n6-keys" data-recommended={recommended}>
      <p className="n6-keys-line">
        <span className="vt-faint">{parts.join(' · ')} · </span>
        <button type="button" className="vt-btn n6-keys-toggle" aria-expanded={legend} onMouseDown={(event) => event.preventDefault()} onClick={onToggleLegend} data-testid="vt-n6-keys-toggle">
          ? keys
        </button>
      </p>
      {legend ? (
        <dl className="n6-legend" data-testid="vt-n6-legend">
          {mode === 'card' ? (
            <>
              {recommended ? (
                <>
                  <dt>↵</dt>
                  <dd>take the recommended option and go on; with a draft, save it and go on</dd>
                </>
              ) : (
                <>
                  <dt>↵</dt>
                  <dd>nothing is recommended here, so ↵ opens the note; with a draft, save it and go on</dd>
                </>
              )}
              {pick ? (
                <>
                  <dt>{count > 1 ? `1–${count}` : '1'}</dt>
                  <dd>pick that option and go on</dd>
                </>
              ) : null}
              <dt>n</dt>
              <dd>write a note or your own answer: ↵ saves it and goes on, Shift+↵ is a new line, Esc returns to the keys</dd>
              <dt>s</dt>
              <dd>later: skip it for now (left out of the copy)</dd>
            </>
          ) : null}
          <dt>j · k</dt>
          <dd>next · previous (→ · ← too)</dd>
          <dt>c</dt>
          <dd>go to the end and copy every answer</dd>
          <dt>Esc</dt>
          <dd>leave the page, from anywhere including the copied-answers box; only in the note box does Esc first return to the keys</dd>
          <dt>?</dt>
          <dd>show or hide this list</dd>
        </dl>
      ) : null}
    </div>
  )
}

function Progress({
  queue,
  index,
  atEnd,
  later,
  seen,
  answers,
  onJump,
}: {
  queue: Entry[]
  index: number
  atEnd: boolean
  later: Set<string>
  seen: Set<string>
  answers: AnswerStore
  onJump(index: number): void
}) {
  const current = atEnd ? null : queue[index]
  const answered = queue.filter((entry) => isComplete(answers.get(entry.doc.track, entry.item.local_id))).length
  const multiTrack = new Set(queue.map((entry) => entry.doc.track)).size > 1
  const seenCount = queue.filter((entry) => seen.has(entry.item.id)).length
  return (
    <div className="n6-progress vt-small" data-testid="vt-n6-progress">
      <span className="n6-progress-where">
        {current ? (
          <>
            <span className="vt-strong vt-num">
              {index + 1} of {queue.length}
            </span>
            <span className={current.item.group === 'blocking' ? 'vt-tone-warn' : 'vt-muted'}> · {GROUP_LABEL[current.item.group]}</span>
            {multiTrack ? <span className="vt-faint"> · {current.doc.track_title}</span> : null}
          </>
        ) : (
          <span className="vt-strong vt-num" data-testid="vt-n6-seen">
            {seenCount === queue.length ? `All ${queue.length} seen` : `${seenCount} of ${queue.length} seen`}
          </span>
        )}
      </span>
      <span className="n6-ticks" role="list">
        {queue.map((entry, position) => {
          const draft = answers.get(entry.doc.track, entry.item.local_id)
          // WHY "unanswered" and not "open": "open" on this page is the header's count of what wants Zach.
          const state = isComplete(draft) ? 'answered' : later.has(entry.item.id) ? 'later' : 'unanswered'
          return (
            <button
              key={entry.item.id}
              type="button"
              role="listitem"
              className="vt-btn n6-tick"
              data-state={state}
              aria-current={!atEnd && position === index ? 'step' : undefined}
              aria-label={`${entry.item.local_id} (${state})`}
              title={`${entry.item.local_id} · ${entry.item.title} (${state})`}
              onClick={() => onJump(position)}
            />
          )
        })}
      </span>
      <span className="n6-progress-meter vt-faint vt-num">
        {answered} answered{later.size ? ` · ${later.size} later` : ''}
      </span>
    </div>
  )
}

/**
 * How many of `total` entries a collapsed list shows. WHY never "+1 more": the judges read "Blocks H1, H2, H4 +1 more"
 * on detection, a control that hides exactly as much as it costs; a list hides entries only when it hides two or more.
 */
function collapsedCount(total: number, cap: number): number {
  return total <= cap + 1 ? total : cap
}

/** WHY at most two evidence entries in the eyebrow: kinsim T33 carries four long paths, which took three lines above
 *  the question; "+2 more" opens the rest in place, the same pattern as the blocks. */
const EVIDENCE_SHOWN = 2

function EvidenceInline({ backend, doc, item, projection }: Pick<NeedsProposalProps, 'backend' | 'projection'> & { doc: NeedsDoc; item: NeedsItem }) {
  const [all, setAll] = useState(false)
  const count = all ? item.evidence.length : collapsedCount(item.evidence.length, EVIDENCE_SHOWN)
  const hidden = item.evidence.length - count
  return (
    <span className="n6-evidence" data-testid="vt-n6-evidence">
      {' · evidence '}
      {item.evidence.slice(0, count).map((_, position) => (
        <EvidenceLink key={position} backend={backend} doc={doc} item={item} index={position} projection={projection} />
      ))}
      {hidden > 0 ? (
        <>
          {' '}
          <button type="button" className="vt-btn n6-inline-btn" onClick={() => setAll(true)} data-testid="vt-n6-evidence-more">
            +{hidden} more
          </button>
        </>
      ) : null}
    </span>
  )
}

function BlocksInline({ item }: { item: NeedsItem }) {
  const [all, setAll] = useState(false)
  if (!item.blocks.length) return <span className="vt-faint">Blocks: none named</span>
  const shown = all ? item.blocks : item.blocks.slice(0, collapsedCount(item.blocks.length, BLOCKS_SHOWN))
  const hidden = item.blocks.length - shown.length
  return (
    <span data-testid="vt-n6-blocks">
      Blocks{' '}
      {shown.map((block, position) => (
        <span key={block.id} title={block.label ?? undefined}>
          {position ? ', ' : ''}
          <span className="vt-strong">{block.id}</span>
        </span>
      ))}
      {hidden > 0 ? (
        <>
          {' '}
          <button type="button" className="vt-btn n6-inline-btn" onClick={() => setAll(true)} data-testid="vt-n6-blocks-more">
            +{hidden} more
          </button>
        </>
      ) : all && item.blocks.length > collapsedCount(item.blocks.length, BLOCKS_SHOWN) ? (
        <>
          {' '}
          <button type="button" className="vt-btn n6-inline-btn" onClick={() => setAll(false)}>
            fewer
          </button>
        </>
      ) : null}
    </span>
  )
}

function Card({
  entry,
  answers,
  backend,
  projection,
  docs,
  keys,
  onChoose,
  flash,
  hint,
  noteRef,
  onClear,
}: NeedsProposalProps & {
  entry: Entry
  keys: ReactNode
  onChoose(choice: Choice): void
  flash: Choice | null
  hint: string | null
  noteRef: RefObject<HTMLTextAreaElement | null>
  onClear(): void
}) {
  const { doc, item } = entry
  const draft = answers.get(doc.track, item.local_id)
  const picked = flash ?? effectiveChoice(draft)
  const { body, trimmed, leadTaken, lifted } = contextRemainder(item)
  // WHY the lead is left out above the options when it is a sentence deep in the body that could not be lifted: the
  // body below must stay verbatim and whole, so printing the lead on top too would be the same words twice. A lead in
  // the body's short opening block lifts that whole block instead (contextRemainder).
  const rawLead = item.context_lead_md?.trim() || null
  const lead = lifted ? null : rawLead && (leadTaken || !body.includes(rawLead)) ? rawLead : null
  const newest = item.updates.length ? item.updates[item.updates.length - 1] : null
  const earlier = item.updates.slice(0, -1).reverse()
  const recommended = item.options.some((option) => option.recommended)
  return (
    <article className="n6-card" data-testid="vt-n6-card" data-item={item.id}>
      {/* WHY evidence sits in the eyebrow (N3, GitHub's file path in the header): every entry is one click away
          without pushing the options off the first screen. */}
      <p className="n6-eyebrow vt-small vt-muted">
        <span className="vt-num vt-strong">{item.local_id}</span>
        {docs.length > 1 ? <span> · {doc.track_title}</span> : null}
        {item.kind !== 'decision' ? <span> · {item.kind.replace(/_/g, ' ')}</span> : null}
        {item.evidence.length ? <EvidenceInline backend={backend} doc={doc} item={item} projection={projection} /> : null}
      </p>
      <h1 className="n6-question">
        <Inline text={item.ask || item.title} />
      </h1>

      {/* WHY the decision content first and the newest update second: the judges read rig T2 leading with its fifth
          UPDATE ("the board's velocity limit acts on …") while the thing being approved ("Ratio, PID … applied in one
          write") sat second under "Originally"; an approval is read for WHAT it approves, then for what changed since.
          Both stay above the options, each clamped with an explicit "…more". */}
      {lifted ? (
        <div className="n6-lead" data-testid="vt-n6-why" data-lifted="true">
          <Clamp lines={5} testId="vt-n6-why-clamp">
            <Md text={lifted} className="n6-prose" />
          </Clamp>
        </div>
      ) : lead ? (
        <div className="n6-lead" data-testid="vt-n6-why">
          <Clamp lines={2} testId="vt-n6-why-clamp">
            <p className="n6-prose">
              <Inline text={lead} />
            </p>
          </Clamp>
        </div>
      ) : null}
      {newest ? (
        <div className="n6-lead n6-update-top" data-testid="vt-n6-update">
          <Clamp lines={3} testId="vt-n6-update-clamp">
            <p className="n6-prose">
              <span className="n6-inline-label">
                Latest update · {newest.header}
                {item.updates.length > 1 ? ` · newest of ${item.updates.length}` : ''}:{' '}
              </span>
              <Inline text={newest.text_md} />
            </p>
          </Clamp>
        </div>
      ) : null}

      <p className="n6-factline vt-small vt-muted" data-testid="vt-n6-facts">
        <BlocksInline item={item} />
        <span className="n6-sep"> · </span>
        <span data-testid="vt-n6-silent">If silent: {silentText(item)}</span>
        <span className="n6-sep"> · </span>
        <OpenedShort doc={doc} item={item} />
      </p>

      <section className="n6-options" aria-label="Options">
        {item.options.map((option, position) => {
          const isPicked = picked === option.key
          return (
            <button
              key={option.key}
              type="button"
              className="vt-btn n6-option"
              aria-pressed={isPicked}
              data-testid={`vt-n6-option-${option.key}`}
              onClick={() => onChoose(option.key)}
            >
              <kbd className="n6-key">{position + 1}</kbd>
              <span className="n6-option-text">
                <span className="n6-option-label">
                  {option.label}
                  {option.recommended ? <span className="n6-tag">recommended</span> : null}
                  {option.is_default ? <span className="n6-tag">{item.default.applies.unit === 'never' ? 'what happens now' : 'default'}</span> : null}
                </span>
                {option.detail_md ? (
                  <span className="n6-option-detail vt-small">
                    <Inline text={option.detail_md} />
                  </span>
                ) : null}
              </span>
            </button>
          )
        })}
        {keys}
        <textarea
          ref={noteRef}
          className="n6-note"
          data-testid="vt-n6-note"
          rows={2}
          placeholder="Add a note, or write your own answer (n). ↵ saves and goes on · Shift+↵ new line"
          value={draft?.note ?? ''}
          onChange={(event) => answers.set(doc.track, item.local_id, { note: event.target.value })}
        />
        <p className="n6-draft-line vt-small" role="status" data-testid="vt-n6-status">
          {hint ? (
            <span className="vt-tone-warn">{hint}</span>
          ) : flash ? (
            <span className="vt-strong">
              Saved: {choiceLabel(item, flash)}
              {draft?.note.trim() ? ' + note' : ''}. Next…
            </span>
          ) : draft && effectiveChoice(draft) ? (
            <>
              <span className="vt-muted">
                Draft: {choiceLabel(item, effectiveChoice(draft) as Choice)}
                {draft.note.trim() ? ' + note' : ''}
                {!isComplete(draft) ? ' (needs a note)' : ''}
              </span>{' '}
              <button type="button" className="vt-btn vt-faint n6-clear" onClick={onClear}>
                clear
              </button>
            </>
          ) : (
            <span className="vt-faint">{recommended ? 'Nothing picked yet.' : 'Nothing picked yet; no option is recommended here.'}</span>
          )}
        </p>
      </section>

      <section className="n6-context" data-testid="vt-n6-context">
        <p className="n6-label">Full context · verbatim</p>
        {earlier.length ? (
          <div className="n6-updates" data-testid="vt-n6-earlier-updates">
            {earlier.map((update, position) => (
              <div key={position} className="n6-update">
                <p className="n6-label">Earlier update · {update.header}</p>
                <Md text={update.text_md} className="n6-prose" />
              </div>
            ))}
          </div>
        ) : null}
        {item.provenance_md ? (
          <p className="vt-small vt-faint n6-provenance">
            <Inline text={item.provenance_md} />
          </p>
        ) : null}
        {body ? (
          <Md text={body} className="n6-prose" />
        ) : (
          <p className="vt-faint vt-small">{trimmed ? 'Nothing beyond the lines above the options.' : 'The loop gives no further context.'}</p>
        )}
        <dl className="n6-facts vt-small" data-testid="vt-n6-facts-full">
          <dt>Blocks</dt>
          <dd>
            {item.blocks.length ? (
              item.blocks.map((block) => (
                <span key={block.id} className="n6-block-row">
                  <span className="vt-strong">{block.id}</span>
                  {block.label ? <span className="vt-muted"> {block.label}</span> : null}
                </span>
              ))
            ) : (
              <span className="vt-faint">nothing named</span>
            )}
          </dd>
          {item.default.text_md && !defaultIsOption(item) ? (
            <>
              <dt>If you stay silent</dt>
              <dd>
                <Inline text={item.default.text_md} />
              </dd>
            </>
          ) : null}
          <dt>When</dt>
          <dd className={item.default.state === 'in_effect' ? 'vt-muted' : undefined}>{whenText(doc, item)}</dd>
          <dt>Opened</dt>
          <dd className="vt-muted">{openedText(doc, item)}</dd>
          {/* WHY the computed group leads and the loop's status word is quoted: "open" on this page means one thing,
              the header's "M open" (wants you); the loop file's own "open" is its word, so it is shown as a quote. */}
          <dt>Status</dt>
          <dd>
            {GROUP_LABEL[item.group]} <span className="vt-muted">(computed)</span>
            <span className="vt-muted"> · the loop file's status: “{item.raw_status}”</span>
          </dd>
          {item.updated.note ? (
            <>
              <dt>Last loop event</dt>
              <dd className="vt-muted">
                <Inline text={item.updated.note} />
              </dd>
            </>
          ) : null}
          <dt>Answer goes</dt>
          <dd className="vt-muted">
            {doc.answer_channel.kind.replace(/_/g, ' ')}
            {doc.answer_channel.target ? `: ${doc.answer_channel.target}` : ''}
          </dd>
          {/* WHY its own row: run on after the target it read "read back no loop reads answers yet". */}
          {doc.answer_channel.read_back ? (
            <>
              <dt>Read back</dt>
              <dd className="vt-muted">{doc.answer_channel.read_back}</dd>
            </>
          ) : null}
        </dl>
      </section>
    </article>
  )
}

function EndScreen({
  docs,
  answers,
  queue,
  later,
  keys,
  defaultingCount,
  includeDefaulting,
  onJump,
  onIncludeDefaulting,
}: NeedsProposalProps & {
  queue: Entry[]
  later: Set<string>
  keys: ReactNode
  defaultingCount: number
  includeDefaulting: boolean
  onJump(index: number): void
  onIncludeDefaulting(): void
}) {
  const draftOf = (entry: Entry) => answers.get(entry.doc.track, entry.item.local_id)
  const answered = queue.filter((entry) => isComplete(draftOf(entry)))
  const laterEntries = queue.filter((entry) => later.has(entry.item.id) && !isComplete(draftOf(entry)))
  const unanswered = queue.filter((entry) => !isComplete(draftOf(entry)) && !later.has(entry.item.id))
  // WHY name drafts outside the lane: Copy exports every complete draft in these docs, including one written on an
  // earlier visit to an item that has since started defaulting. Each answer that leaves must be visible here first.
  const inLane = new Set(queue.map((entry) => entry.item.id))
  const elsewhere = docs.flatMap((doc) => doc.items.filter((item) => !inLane.has(item.id) && isComplete(answers.get(doc.track, item.local_id))).map((item) => ({ doc, item })))
  const unreported = docs.filter((doc) => !isReported(doc))
  const position = (entry: Entry) => queue.findIndex((candidate) => candidate.item.id === entry.item.id)
  const links = (entries: Entry[]) =>
    entries.map((entry, i) => (
      <span key={entry.item.id}>
        {i ? ', ' : ''}
        <button type="button" className="vt-btn n6-link" onClick={() => onJump(position(entry))}>
          {entry.item.local_id}
        </button>
      </span>
    ))
  return (
    <article className="n6-card n6-end" data-testid="vt-n6-end">
      <p className="n6-eyebrow vt-small vt-muted">End of the lane</p>
      <h1 className="n6-question">
        {answered.length} of {queue.length} answered
      </h1>
      <p className="vt-muted vt-small">Nothing has been sent. Copy the answers and paste them where the loop reads them.</p>
      <ol className="n6-summary" data-testid="vt-n6-summary">
        {queue.map((entry, i) => {
          const draft = draftOf(entry)
          const choice = effectiveChoice(draft)
          const complete = isComplete(draft)
          return (
            <li key={entry.item.id}>
              <button type="button" className="vt-btn n6-summary-row" onClick={() => onJump(i)}>
                <span className="vt-faint vt-num n6-summary-id">{entry.item.local_id}</span>
                <span className="n6-summary-text">
                  <span className="n6-summary-title">
                    <Inline text={entry.item.title} />
                  </span>
                  <span className="vt-small">
                    {complete && choice ? (
                      <span>
                        {choiceLabel(entry.item, choice)}
                        {draft?.note.trim() ? <span className="vt-muted"> · “{draft.note.trim()}”</span> : null}
                      </span>
                    ) : later.has(entry.item.id) ? (
                      <span className="vt-faint">later</span>
                    ) : choice ? (
                      <span className="vt-tone-warn">“Something else” needs a note</span>
                    ) : (
                      <span className="vt-faint">not answered</span>
                    )}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>
      {laterEntries.length || unanswered.length ? (
        <p className="vt-small vt-muted n6-notcopy" data-testid="vt-n6-not-in-copy">
          <span className="n6-label-inline">Not in the copy</span>
          {laterEntries.length ? <> · Later: {links(laterEntries)}</> : null}
          {unanswered.length ? <> · Unanswered: {links(unanswered)}</> : null}
        </p>
      ) : null}
      {elsewhere.length ? (
        <p className="vt-small vt-muted n6-notcopy" data-testid="vt-n6-elsewhere">
          <span className="n6-label-inline">Also in the copy</span> · drafted on an earlier visit, outside this lane:{' '}
          {elsewhere.map(({ doc, item }) => `${item.local_id} (${GROUP_LABEL[item.group].toLowerCase()}${docs.length > 1 ? `, ${doc.track_title}` : ''})`).join(', ')}
        </p>
      ) : null}
      <CopyOut docs={docs} answers={answers} label="Copy all answers" className="n6-copy" />
      {keys}
      {docs.filter(isReported).map((doc) => (
        <p key={doc.track} className="vt-small vt-faint n6-channel">
          {doc.track_title}: {doc.answer_channel.kind === 'jsonl_append' ? 'append the jsonl rows to' : 'paste into'} {doc.answer_channel.target ?? 'the loop'}
          <ReadBack doc={doc} />
        </p>
      ))}
      {!includeDefaulting && defaultingCount ? (
        <p className="n6-more vt-small">
          <span className="vt-muted">
            {/* WHY not "open": the header's "M open" counts what wants Zach; these are the header's "more defaulting
                without you", in the same words, so one word never means two things on this page. */}
            {defaultingCount} more {defaultingCount === 1 ? 'is' : 'are'} defaulting without you: {defaultingCount === 1 ? 'its' : 'their'} default is already in effect (computed from the loop's progress).{' '}
          </span>
          <button type="button" className="vt-btn n6-link" data-testid="vt-n6-more" onClick={onIncludeDefaulting}>
            Review them too →
          </button>
        </p>
      ) : null}
      {unreported.length ? <NotReported docs={unreported} /> : null}
    </article>
  )
}

/**
 * The end of a channel sentence: ". Read back: <the loop's words>." WHY a labelled sentence of its own: run on after
 * the target with "; read back" it read "read back no loop reads answers yet", and the loops' read_back texts start
 * every which way ("at the next wave start", "by hand: …", "no loop reads …").
 */
function ReadBack({ doc }: { doc: NeedsDoc }) {
  if (!doc.answer_channel.read_back) return <>.</>
  return (
    <>
      . <span className="n6-label-inline">Read back:</span> {doc.answer_channel.read_back.replace(/\.$/, '')}.
    </>
  )
}

/** N2's empty-state wording: say where each loop's questions actually live, never "all clear". */
function NotReported({ docs }: { docs: NeedsDoc[] }) {
  return (
    <section className="n6-unreported" data-testid="vt-n6-unreported">
      {docs.map((doc) => (
        <div key={doc.track} className="n6-unreported-track">
          <p className="n6-label">{doc.track_title} · not reported</p>
          <p className="vt-muted">No structured questions from this loop yet.</p>
          <p className="vt-small vt-faint">{doc.source.note ?? 'This loop publishes no needs-you file.'}</p>
          {doc.answer_channel.target ? (
            <p className="vt-small vt-faint">
              To answer it anyway: {doc.answer_channel.kind.replace(/_/g, ' ')} to {doc.answer_channel.target}
              <ReadBack doc={doc} />
            </p>
          ) : null}
        </div>
      ))}
    </section>
  )
}

function EmptyLane({
  docs,
  defaultingCount,
  includeDefaulting,
  onIncludeDefaulting,
}: {
  docs: NeedsDoc[]
  defaultingCount: number
  includeDefaulting: boolean
  onIncludeDefaulting(): void
}) {
  const reported = docs.filter(isReported)
  const unreported = docs.filter((doc) => !isReported(doc))
  return (
    <article className="n6-card n6-empty" data-testid="vt-n6-empty">
      {reported.length ? (
        <h1 className="n6-question">Nothing is waiting on you{reported.length === 1 ? ` in ${reported[0].track_title}` : ''}.</h1>
      ) : (
        <h1 className="n6-question">No structured questions from this loop yet</h1>
      )}
      {reported.map((doc) => (
        <p key={doc.track} className="vt-muted n6-empty-track">
          {docs.length > 1 ? `${doc.track_title}: ` : ''}
          {doc.counts.total} items on file, none asking for you now.
        </p>
      ))}
      {!includeDefaulting && defaultingCount ? (
        <p className="n6-more vt-small">
          <span className="vt-muted">
            {defaultingCount} {defaultingCount === 1 ? 'is' : 'are'} defaulting without you: the default is already in effect (computed from the loop's progress).{' '}
          </span>
          <button type="button" className="vt-btn n6-link" onClick={onIncludeDefaulting}>
            Review them →
          </button>
        </p>
      ) : null}
      {unreported.length === 1 && !reported.length ? (
        <div className="n6-unreported" data-testid="vt-n6-unreported">
          <p className="vt-muted">{unreported[0].source.note ?? 'This loop publishes no needs-you file.'}</p>
          {unreported[0].answer_channel.target ? (
            <p className="vt-small vt-faint">
              To answer it anyway: {unreported[0].answer_channel.kind.replace(/_/g, ' ')} to {unreported[0].answer_channel.target}
              <ReadBack doc={unreported[0]} />
            </p>
          ) : null}
        </div>
      ) : unreported.length ? (
        <NotReported docs={unreported} />
      ) : null}
    </article>
  )
}
