// Proposal N6 · "Lane + context": the judges' splice of N1 (Zen mode) and N2 (Inbox + reading pane).
//
// N1's lane is the shell: the page opens ON the first question, focus is taken on mount, and the keyboard answers it
// (↵ takes the recommendation, 1-3 pick an option, N writes a note, S marks later, J/K move, C jumps to the end and
// copies, Esc leaves), auto-advancing after a visible confirm, ending on a screen that lists every card and holds the
// one Copy action. N2's context is grafted onto every card: the "Blocks · If you stay silent · When · Opened" fact
// rows above the options, and the loop's full verbatim context directly under them.
//
// WHY the context is OPEN by default and A folds it (N1 hid it behind A): Zach, 2026-10-04: "I need enough context
// though to actually like provide feedback". Both judges found N1's one-key reveal was the one keypress too many; the
// options stay on the first screen, and the context needed to answer them is the scroll right below.
// WHY newest UPDATE first (as N3 does it): rig items grow by appended UPDATE paragraphs (rig T2 has five); the newest
// one supersedes the original question, so reading oldest-first answers a question the loop no longer asks.
// WHY the header counts are de-overlapped (N4) and come from needs.py's counts (blocking_now, wants_you): the number
// Zach clicked on the home cell ("B blocking · M open") must be the number he lands on; a second arithmetic here is
// how grasping once read "7 open" on the cell and opened onto an empty page.
// WHY the lane position lives in component state, not the route: every earlier proposal's private key (zen=, ask=,
// n4card=, n5=) leaked into the dashboard's route after leaving the page. Moving between cards is sideways, so
// nothing here belongs in Back's history anyway; drafts persist through the answer store.
// WHY drafts and one Copy, never a Send: the backend is read-only and the loops read answers from their own channels
// (kinsim's jsonl, rig's chat). There is deliberately no control that pretends to submit.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import {
  CopyOut,
  EvidenceLink,
  GROUP_LABEL,
  choiceLabel,
  effectiveChoice,
  isComplete,
  type Choice,
  type NeedsCounts,
  type NeedsDoc,
  type NeedsGroup,
  type NeedsItem,
  type NeedsProposalProps,
  wantsYouCount,
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

function buildQueue(docs: NeedsDoc[], includeDefaulting: boolean): Entry[] {
  const groups = includeDefaulting ? ALL_GROUPS : WANT_GROUPS
  const entries: Entry[] = []
  // One track: needs.py's own order. Several: by what an item holds (group) before which track it is in.
  for (const group of groups) for (const doc of docs) for (const item of doc.items) if (item.group === group) entries.push({ doc, item })
  return entries
}

// ---- the counts contract ----------------------------------------------------------------------------------------

type ContractCounts = Omit<NeedsCounts, 'wants_you' | 'blocking_now'> & { wants_you?: number | null; blocking_now: number | null }

/** A track with no structured needs source reports no counts: "not reported", never 0 (frozen contract). */
function isReported(doc: NeedsDoc): boolean {
  const counts = doc.counts as unknown as ContractCounts
  if (counts.wants_you === null || counts.blocking_now === null) return false
  return !/^none\b/.test(doc.source.adapter)
}

function groupCount(doc: NeedsDoc, group: NeedsGroup): number {
  return doc.items.filter((item) => item.group === group).length
}

/** needs.py's numbers: `blocking_now` and `wants_you`; the de-overlapped parts are counted from the same groups. */
function trackCounts(doc: NeedsDoc) {
  const counts = doc.counts as unknown as ContractCounts
  const noDefault = groupCount(doc, 'no_default')
  const waiting = groupCount(doc, 'waiting')
  const blocking = counts.blocking_now ?? groupCount(doc, 'blocking')
  // `wants_you` is the contract field; the kit's reader falls back to the same three groups until needs.py sends it.
  const open = wantsYouCount(doc)
  return { blocking, open, noDefault, waiting, defaulting: groupCount(doc, 'defaulting') }
}

function Header({ docs, track, loading }: { docs: NeedsDoc[]; track: string | null; loading: boolean }) {
  const title = track ? (docs[0]?.track_title ?? track) : 'Every track'
  const reported = docs.filter(isReported)
  const unreported = docs.filter((doc) => !isReported(doc))
  let line: ReactNode
  let blockingAttr = 'null'
  let openAttr = 'null'
  if (loading && !docs.length) line = <span className="vt-faint">Reading the loops…</span>
  else if (!reported.length) line = <span className="vt-muted">Not reported: {docs.length === 1 ? 'this loop has' : 'these loops have'} no structured questions yet.</span>
  else {
    const sum = reported.map(trackCounts).reduce(
      (total, counts) => ({
        blocking: total.blocking + counts.blocking,
        open: total.open + counts.open,
        noDefault: total.noDefault + counts.noDefault,
        waiting: total.waiting + counts.waiting,
        defaulting: total.defaulting + counts.defaulting,
      }),
      { blocking: 0, open: 0, noDefault: 0, waiting: 0, defaulting: 0 },
    )
    blockingAttr = String(sum.blocking)
    openAttr = String(sum.open)
    line = (
      <>
        <span className="vt-strong vt-num">{sum.open} open</span>
        <span>: </span>
        <span className={sum.blocking ? 'vt-tone-warn' : undefined}>
          <span className="vt-num">{sum.blocking}</span> blocking now
        </span>
        {sum.noDefault ? <span> · <span className="vt-num">{sum.noDefault}</span> waiting with no default</span> : null}
        {sum.waiting ? <span> · <span className="vt-num">{sum.waiting}</span> with a default pending</span> : null}
        {sum.defaulting ? <span className="vt-faint"> · {sum.defaulting} more defaulting without you</span> : null}
        {unreported.length ? <span className="vt-faint"> · not reported: {unreported.map((doc) => doc.track_title).join(', ')}</span> : null}
      </>
    )
  }
  return (
    <header className="n6-head" data-testid="vt-n6-head" data-blocking={blockingAttr} data-open={openAttr}>
      <h1 className="n6-head-title">{title}</h1>
      <p className="n6-head-counts vt-small">{line}</p>
    </header>
  )
}

// ---- small text helpers -----------------------------------------------------------------------------------------

/** When the default fires, in the loop's own unit, against where the loop is. Computed, so it says so. */
function whenText(doc: NeedsDoc, item: NeedsItem): string {
  const { applies, state } = item.default
  const at = doc.iteration ? `the loop has finished ${doc.iteration.unit} ${doc.iteration.finished ?? '(not reported)'}` : null
  if (applies.unit === 'never') return 'Never. This waits for you.'
  if (state === 'in_effect') return `In effect now: due after ${applies.unit} ${applies.after}, and ${at ?? 'that has passed'} (computed by the dashboard).`
  return `After ${applies.unit} ${applies.after}${at ? `; ${at}` : ''}.`
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

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || Boolean(target.closest('.cm-editor'))
}

// ---- the lane ---------------------------------------------------------------------------------------------------

export default function NeedsLaneContext(props: NeedsProposalProps) {
  const { docs, track, loading, error, answers, onBack } = props
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
  const [folded, setFolded] = useState(false)
  const [noteFocused, setNoteFocused] = useState(false)
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

  const choose = useCallback(
    (choice: Choice) => {
      if (!current) return
      const { doc, item } = current
      const draft = answers.get(doc.track, item.local_id)
      answers.set(doc.track, item.local_id, { choice })
      if (choice === 'other' && !draft?.note.trim()) {
        setHint('Write your answer, then press ↵ to save it and go on.')
        note.current?.focus()
        return
      }
      unmarkLater(item.id)
      // A visible beat: the picked option stays pressed and the status line says so before the card peels off.
      setFlash(choice)
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => {
        timer.current = null
        goTo(index + 1)
      }, CONFIRM_MS)
    },
    [answers, current, goTo, index, unmarkLater],
  )

  /** ↵: on an untouched card it takes the recommendation; otherwise it saves what is there and goes on. */
  const enter = useCallback(() => {
    if (!current) return
    const { doc, item } = current
    const draft = answers.get(doc.track, item.local_id)
    if (!effectiveChoice(draft)) return choose('accept_recommendation')
    if (!isComplete(draft)) {
      setHint('"Something else" needs a few words; write them, or pick 1 or 2.')
      note.current?.focus()
      return
    }
    unmarkLater(item.id)
    setFlash(effectiveChoice(draft))
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      timer.current = null
      goTo(index + 1)
    }, CONFIRM_MS)
  }, [answers, choose, current, goTo, index, unmarkLater])

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
    const inside = target instanceof Node && Boolean(lane.closest('.vt-dash')?.contains(target))
    const onBody = target === document.body || target === document.documentElement
    if (!inside && !onBody) return
    const key = event.key
    if (target === note.current) {
      if (key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        enter()
      } else if (key === 'Escape') {
        event.preventDefault()
        note.current?.blur()
        lane.focus({ preventScroll: true })
      }
      return
    }
    if (isEditable(target) || event.ctrlKey) return
    // A focused link or button keeps its own Enter/Space (an evidence link, the copy button, the switcher).
    if ((key === 'Enter' || key === ' ') && target instanceof HTMLElement && target.closest('a, button')) return
    const handled = (fn: () => void) => {
      event.preventDefault()
      event.stopPropagation()
      fn()
    }
    if (key === 'Escape') return handled(onBack)
    if (key === 'j' || key === 'ArrowRight') return handled(() => goTo(index + 1))
    if (key === 'k' || key === 'ArrowLeft') return handled(() => goTo(index - 1))
    if (key === 'c' && !event.shiftKey) return handled(copyAll)
    if (!current) return
    if (key === 'Enter') return handled(enter)
    if (key === 'a') return handled(() => setFolded((value) => !value))
    if (key === 's') return handled(skip)
    if (key === 'n') return handled(() => note.current?.focus())
    const number = ['1', '2', '3'].indexOf(key)
    // WHY capture + preventDefault on 1-3: the dashboard's own 1/2/3 switch the A · B · C layout; in the lane they pick
    // an option, and the dashboard's listener skips a defaultPrevented key.
    if (number >= 0 && current.item.options[number]) return handled(() => choose(current.item.options[number].key))
  }
  useEffect(() => {
    const listener = (event: KeyboardEvent) => keyHandler.current(event)
    window.addEventListener('keydown', listener, true)
    return () => window.removeEventListener('keydown', listener, true)
  }, [])

  let body: ReactNode
  if (loading && !docs.length) body = <p className="vt-muted n6-quiet">Reading the loops…</p>
  else if (error && !docs.length) body = <p className="vt-tone-risk n6-quiet">/needs did not answer: {error}</p>
  else if (!queue.length) body = <EmptyLane docs={docs} defaultingCount={defaultingCount} includeDefaulting={includeDefaulting} onIncludeDefaulting={() => setIncludeDefaulting(true)} />
  else if (atEnd || !current)
    body = (
      <EndScreen
        {...props}
        queue={queue}
        later={later}
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
        entry={current}
        folded={folded}
        onToggleFold={() => setFolded((value) => !value)}
        onChoose={choose}
        flash={flash}
        hint={hint}
        noteRef={note}
        onNoteFocus={setNoteFocused}
        onClear={() => {
          answers.clear(current.doc.track, current.item.local_id)
          setHint(null)
        }}
      />
    )

  return (
    <div ref={root} className="vt-needs-n6" tabIndex={-1} data-testid="vt-needs-n6" data-n6-item={current?.item.id ?? (atEnd ? 'end' : '')}>
      <div className="n6-layout">
        <div className="n6-main">
          <Header docs={docs} track={track} loading={loading} />
          {queue.length ? <Progress queue={queue} index={index} atEnd={atEnd || !current} later={later} answers={answers} onJump={goTo} /> : null}
          <div className="n6-stage">{body}</div>
        </div>
        {queue.length ? (
          // WHY a rail beside the card and not a bottom bar: the bottom-right corner belongs to the proposal and
          // A · B · C choosers, which would cover a bottom dock; the keys stay in view while the context scrolls.
          <aside className="n6-rail">
            <Dock
              mode={atEnd || !current ? 'end' : noteFocused ? 'note' : 'card'}
              current={current}
              folded={folded}
              hasDraft={Boolean(current && effectiveChoice(answers.get(current.doc.track, current.item.local_id)))}
              onNext={() => goTo(index + 1)}
              onPrev={() => goTo(index - 1)}
              onEnter={enter}
              onSkip={skip}
              onFold={() => setFolded((value) => !value)}
              onNote={() => note.current?.focus()}
              onCopy={copyAll}
              onLeave={onBack}
            />
          </aside>
        ) : null}
      </div>
    </div>
  )
}

function Progress({
  queue,
  index,
  atEnd,
  later,
  answers,
  onJump,
}: {
  queue: Entry[]
  index: number
  atEnd: boolean
  later: Set<string>
  answers: NeedsProposalProps['answers']
  onJump(index: number): void
}) {
  const current = atEnd ? null : queue[index]
  const answered = queue.filter((entry) => isComplete(answers.get(entry.doc.track, entry.item.local_id))).length
  const multiTrack = new Set(queue.map((entry) => entry.doc.track)).size > 1
  return (
    <div className="n6-progress" data-testid="vt-n6-progress">
      <p className="n6-progress-line vt-small">
        {current ? (
          <>
            <span className="vt-strong vt-num">
              {index + 1} of {queue.length}
            </span>
            <span className={current.item.group === 'blocking' ? 'vt-tone-warn' : 'vt-muted'}> · {GROUP_LABEL[current.item.group]}</span>
            {multiTrack ? <span className="vt-faint"> · {current.doc.track_title}</span> : null}
          </>
        ) : (
          <span className="vt-strong">All {queue.length} seen</span>
        )}
        <span className="n6-progress-meter vt-faint vt-num">
          {answered} answered{later.size ? ` · ${later.size} later` : ''}
        </span>
      </p>
      <div className="n6-ticks" role="list">
        {queue.map((entry, position) => {
          const draft = answers.get(entry.doc.track, entry.item.local_id)
          const state = isComplete(draft) ? 'answered' : later.has(entry.item.id) ? 'later' : 'open'
          return (
            <button
              key={entry.item.id}
              type="button"
              role="listitem"
              className="vt-btn n6-tick"
              data-state={state}
              aria-current={!atEnd && position === index ? 'step' : undefined}
              title={`${entry.item.local_id} · ${entry.item.title} (${state})`}
              onClick={() => onJump(position)}
            />
          )
        })}
      </div>
    </div>
  )
}

function Card({
  entry,
  answers,
  backend,
  projection,
  docs,
  folded,
  onToggleFold,
  onChoose,
  flash,
  hint,
  noteRef,
  onNoteFocus,
  onClear,
}: NeedsProposalProps & {
  entry: Entry
  folded: boolean
  onToggleFold(): void
  onChoose(choice: Choice): void
  flash: Choice | null
  hint: string | null
  noteRef: RefObject<HTMLTextAreaElement | null>
  onNoteFocus(focused: boolean): void
  onClear(): void
}) {
  const { doc, item } = entry
  const draft = answers.get(doc.track, item.local_id)
  const picked = flash ?? effectiveChoice(draft)
  const lead = item.context_lead_md
  const base = item.context_base_md || item.context_md
  // The provenance sentence gets its own quiet line, so the body starts where the loop's argument does.
  const body = (item.provenance_md && base.startsWith(item.provenance_md) ? base.slice(item.provenance_md.length) : base).trim()
  const updates = [...item.updates].reverse()
  return (
    <article className="n6-card" key={item.id} data-testid="vt-n6-card" data-item={item.id}>
      {/* WHY evidence sits in the eyebrow (N3, GitHub's file path in the header): every entry is one click away
          without pushing the options off the first screen. */}
      <p className="n6-eyebrow vt-small vt-muted">
        <span className="vt-num vt-strong">{item.local_id}</span>
        {docs.length > 1 ? <span> · {doc.track_title}</span> : null}
        {item.kind !== 'decision' ? <span> · {item.kind.replace(/_/g, ' ')}</span> : null}
        {item.evidence.length ? (
          <span className="n6-evidence">
            {' · evidence '}
            {item.evidence.map((_, position) => (
              <EvidenceLink key={position} backend={backend} doc={doc} item={item} index={position} projection={projection} />
            ))}
          </span>
        ) : null}
      </p>
      <h1 className="n6-question">
        <Inline text={item.ask || item.title} />
      </h1>

      <dl className="n6-facts vt-small" data-testid="vt-n6-facts">
        <dt>Blocks</dt>
        <dd>
          {item.blocks.length ? (
            item.blocks.map((block, position) => (
              <span key={block.id}>
                {position ? ' · ' : ''}
                <span className="vt-strong">{block.id}</span>
                {block.label ? <span className="vt-muted"> {block.label}</span> : null}
              </span>
            ))
          ) : (
            <span className="vt-faint">nothing named</span>
          )}
        </dd>
        <dt>If you stay silent</dt>
        <dd>{item.default.text_md ? <Inline text={item.default.text_md} /> : <span className="vt-faint">the loop states no default</span>}</dd>
        <dt>When</dt>
        <dd className={item.default.state === 'in_effect' ? 'vt-muted' : undefined}>{whenText(doc, item)}</dd>
        <dt>Opened</dt>
        <dd className="vt-muted">{openedText(doc, item)}</dd>
      </dl>

      {lead ? (
        <section className="n6-why">
          <p className="n6-label">Why it's asked</p>
          <Md text={lead} className="n6-prose" />
        </section>
      ) : null}

      <section className="n6-options" aria-label="Options">
        <p className="n6-label">Your answer</p>
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
                ) : option.needs_note || option.key === 'other' ? (
                  <span className="n6-option-detail vt-small">Your own answer, in the box below.</span>
                ) : null}
              </span>
            </button>
          )
        })}
        <textarea
          ref={noteRef}
          className="n6-note"
          data-testid="vt-n6-note"
          rows={2}
          placeholder="Add a note, or write your own answer (n). ↵ saves and goes on · Shift+↵ new line"
          value={draft?.note ?? ''}
          onChange={(event) => answers.set(doc.track, item.local_id, { note: event.target.value })}
          onFocus={() => onNoteFocus(true)}
          onBlur={() => onNoteFocus(false)}
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
            <span className="vt-faint">Nothing picked yet; ↵ takes the recommendation.</span>
          )}
        </p>
      </section>

      <section className="n6-context" data-testid="vt-n6-context-section">
        <button type="button" className="vt-btn n6-fold vt-small" aria-expanded={!folded} onClick={onToggleFold} data-testid="vt-n6-fold">
          <kbd className="n6-key">A</kbd> {folded ? 'Show the full context' : 'Full context · verbatim'}
          {folded ? null : <span className="vt-faint"> · A folds it</span>}
        </button>
        {folded ? null : (
          <div className="n6-context-body" data-testid="vt-n6-context">
            {updates.length ? (
              <div className="n6-updates">
                {updates.map((update, position) => (
                  <div key={position} className="n6-update">
                    <p className="n6-label">
                      UPDATE {update.header}
                      {position === 0 && updates.length > 1 ? ` · newest of ${updates.length}` : ''}
                    </p>
                    <Md text={update.text_md} className="n6-prose" />
                  </div>
                ))}
                <p className="n6-label n6-original">The original question</p>
              </div>
            ) : null}
            {item.provenance_md ? (
              <p className="vt-small vt-faint n6-provenance">
                <Inline text={item.provenance_md} />
              </p>
            ) : null}
            {body ? <Md text={body} className="n6-prose" /> : <p className="vt-faint vt-small">The loop gives no further context.</p>}
            <dl className="n6-facts n6-facts-tail vt-small">
              <dt>Status</dt>
              <dd>
                {item.status}
                {item.raw_status !== item.status ? ` (the loop file says ${item.raw_status})` : ''} · {GROUP_LABEL[item.group].toLowerCase()} (computed)
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
                {doc.answer_channel.read_back ? `; read back ${doc.answer_channel.read_back}` : ''}
              </dd>
            </dl>
          </div>
        )}
      </section>
    </article>
  )
}

function EndScreen({
  docs,
  answers,
  queue,
  later,
  defaultingCount,
  includeDefaulting,
  onJump,
  onIncludeDefaulting,
}: NeedsProposalProps & {
  queue: Entry[]
  later: Set<string>
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
      {docs.filter(isReported).map((doc) => (
        <p key={doc.track} className="vt-small vt-faint n6-channel">
          {doc.track_title}: {doc.answer_channel.kind === 'jsonl_append' ? 'append the jsonl rows to' : 'paste into'} {doc.answer_channel.target ?? 'the loop'}
          {doc.answer_channel.read_back ? `; read back ${doc.answer_channel.read_back}` : ''}.
        </p>
      ))}
      {!includeDefaulting && defaultingCount ? (
        <p className="n6-more vt-small">
          <span className="vt-muted">
            {defaultingCount} more {defaultingCount === 1 ? 'is' : 'are'} open, but {defaultingCount === 1 ? 'its' : 'their'} default is already in effect (computed from the loop's progress).{' '}
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
              {doc.answer_channel.read_back ? `; ${doc.answer_channel.read_back}` : ''}.
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
          <span className="vt-muted">{defaultingCount} open with the default already in effect. </span>
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
              {unreported[0].answer_channel.read_back ? `; ${unreported[0].answer_channel.read_back}` : ''}.
            </p>
          ) : null}
        </div>
      ) : unreported.length ? (
        <NotReported docs={unreported} />
      ) : null}
    </article>
  )
}

function Dock({
  mode,
  current,
  folded,
  hasDraft,
  onNext,
  onPrev,
  onEnter,
  onSkip,
  onFold,
  onNote,
  onCopy,
  onLeave,
}: {
  mode: 'card' | 'note' | 'end'
  current: Entry | null
  folded: boolean
  hasDraft: boolean
  onNext(): void
  onPrev(): void
  onEnter(): void
  onSkip(): void
  onFold(): void
  onNote(): void
  onCopy(): void
  onLeave(): void
}) {
  // Every button does exactly what its key does; the two key legends ("1-3", "Shift ↵") are plain text, not buttons,
  // so nothing in the dock is a fake control.
  type Key = { k: string; label: string; run?: () => void }
  const keys: Key[] =
    mode === 'end'
      ? [
          { k: 'K', label: 'back to the last card', run: onPrev },
          { k: 'C', label: 'copy all answers', run: onCopy },
          { k: 'Esc', label: 'leave', run: onLeave },
        ]
      : mode === 'note'
        ? [
            { k: '↵', label: 'save and next', run: onEnter },
            { k: 'Shift ↵', label: 'new line' },
            { k: 'Esc', label: 'back to keys', run: () => (document.activeElement as HTMLElement | null)?.blur() },
          ]
        : [
            { k: `1–${current?.item.options.length ?? 3}`, label: 'answer' },
            { k: '↵', label: hasDraft ? 'save and next' : 'take recommendation', run: onEnter },
            { k: 'N', label: 'note', run: onNote },
            { k: 'S', label: 'later', run: onSkip },
            { k: 'A', label: folded ? 'show context' : 'fold context', run: onFold },
            { k: 'J', label: 'next', run: onNext },
            { k: 'K', label: 'previous', run: onPrev },
            { k: 'C', label: 'copy all', run: onCopy },
            { k: 'Esc', label: 'leave', run: onLeave },
          ]
  return (
    <div className="n6-dock vt-small" data-testid="vt-n6-dock" data-mode={mode}>
      <p className="n6-label n6-dock-title">{mode === 'end' ? 'Keys · end' : mode === 'note' ? 'Keys · writing' : 'Keys'}</p>
      {keys.map((entry) =>
        entry.run ? (
          <button key={entry.k} type="button" className="vt-btn n6-dock-item" onMouseDown={(event) => event.preventDefault()} onClick={entry.run}>
            <kbd className="n6-key">{entry.k}</kbd> {entry.label}
          </button>
        ) : (
          <span key={entry.k} className="n6-dock-item n6-dock-static">
            <kbd className="n6-key">{entry.k}</kbd> {entry.label}
          </span>
        ),
      )}
    </div>
  )
}
