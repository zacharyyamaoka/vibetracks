// Proposal N1 "Zen mode" for the "Needs you" page: one question fills the screen, you answer it with one key, and the
// next one slides in. Inspired by Sauna AI's Zen Mode (its Review queue turned into a keyboard-driven triage lane;
// https://www.sauna.ai/learn/web-app/dashboard, read 2026-10-04) and Zach's own "Zen Mode UI, no switching screens"
// note in PROJECT - Sidartha AI ("you just go through a prioritized list", "locked into a single window").
//
// WHY the page opens ON item 1 instead of on a list: Zach, 2026-10-04: "as soon as I click into the worktrack ... it
// should be now within 1 click for me to start addressing these". The Needs-you count is the doorway; a list in
// between is the click we remove.
// WHY answers collect as drafts and leave through one Copy (unlike Sauna, which sends each reply on the keystroke):
// the backend is read-only, the loops read answers from their own channels (kinsim's jsonl, rig's chat), and Zach
// asked for "the option to copy paste my answers". There is deliberately no "Send".
// WHY J = next and K = previous (Sauna has them the other way round): Gmail and Superhuman use J = next, and a key he
// already knows beats a copy of Sauna's one odd choice (the prior-art principles' "the one thing not to copy").
// WHY the bottom dock of live keys is the only chrome: Sauna's cheat-sheet dock; calm is the container and the
// question is the content, so no toolbar and no view toggles (view settings live on the settings page).

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import {
  CopyOut,
  EvidenceLink,
  IncludeDefaultingPointer,
  StaleDraftNotice,
  GROUP_LABEL,
  NO_DEFAULT_RECORDED,
  WHEN_NOT_STATED,
  appliesAfter,
  choiceLabel,
  effectiveChoice,
  hasDefault,
  headerCounts,
  headerSummary,
  isComplete,
  isNoteOnly,
  notReportedText,
  type Choice,
  type NeedsDoc,
  type NeedsGroup,
  type NeedsItem,
  type NeedsProposalProps,
  hoverTime,
  questionText,
  questionMd,
} from '../kit'
import { formatLocal } from '../../shared/time'
import './zen.css'

export const NAME = 'Zen mode'

interface Entry {
  doc: NeedsDoc
  item: NeedsItem
}

// WHY the queue is "wants you" groups first and the defaulting ones only when the settings page says so: an item whose
// default is already in effect needs nothing from Zach; putting all eight of kinsim's in his lane would bury the three
// that do. The end screen counts them and points at the setting ("Include questions whose default is already in
// effect"); a page button or a `zq=all` route flag was a view option outside the settings page (audit finding 13).
const ASK_GROUPS: NeedsGroup[] = ['blocking', 'no_default', 'waiting']
const ALL_GROUPS: NeedsGroup[] = [...ASK_GROUPS, 'defaulting']

function buildQueue(docs: NeedsDoc[], includeDefaulting: boolean): Entry[] {
  const groups = includeDefaulting ? ALL_GROUPS : ASK_GROUPS
  const entries: Entry[] = []
  // Across tracks, order by what an item blocks (group rank) before which track it is in; within a track the backend
  // order (blocking, no default, by when the default fires) is kept.
  for (const group of groups) for (const doc of docs) for (const item of doc.items) if (item.group === group) entries.push({ doc, item })
  return entries
}

/** Inline `code` and `**bold**` spans only; every other character is shown as the loop wrote it. */
function Verbatim({ text }: { text: string }) {
  // `**bold**` too: detection's asks open with a bold lead ("**Data.** The Seagate ..."), and the raw asterisks read
  // as noise, not as the loop's emphasis.
  const parts = text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g)
  return (
    <>
      {parts.map((part, index) =>
        part.length > 2 && part.startsWith('`') && part.endsWith('`') ? (
          <code key={index}>{part.slice(1, -1)}</code>
        ) : part.length > 4 && part.startsWith('**') && part.endsWith('**') ? (
          <strong key={index}>{part.slice(2, -2)}</strong>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  )
}

// WHY formatLocal (time-format wave): every stamp on every page reads one way, local time with its zone; a proposal
// formatting its own stamps drifted (no zone, or the source's zone).
function shortDate(ts: string | null): string | null {
  if (!ts) return null
  return formatLocal(ts, { dateOnly: true })
}

function blocksText(item: NeedsItem): string {
  return item.blocks.map((block) => (block.label ? `${block.id} (${block.label})` : block.id)).join(', ')
}

/** When the default fires, in the loop's own unit, with where the loop is now. Computed, so it says so. */
function defaultTiming(doc: NeedsDoc, item: NeedsItem): string {
  if (!hasDefault(item)) return NO_DEFAULT_RECORDED
  const after = appliesAfter(item)
  // WHY no "fires …" sentence without a number: the detection plan note never says when its defaults fire; the raw
  // unit read "fires after unstated null".
  if (!after) return WHEN_NOT_STATED
  const at = doc.iteration ? `${doc.iteration.unit} ${doc.iteration.finished ?? doc.iteration.n ?? '–'} finished` : null
  if (item.default.state === 'in_effect') return `already in effect, ${after}${at ? ` (loop: ${at})` : ''} · computed`
  return `fires ${after}${at ? ` (loop: ${at})` : ''}`
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || Boolean(target.closest('.cm-editor'))
}

export default function NeedsZen(props: NeedsProposalProps) {
  const { docs, loading, error, answers, route, navigate, onBack, includeDefaulting } = props
  const queue = useMemo(() => buildQueue(docs, includeDefaulting), [docs, includeDefaulting])
  const defaultingCount = useMemo(() => docs.reduce((sum, doc) => sum + doc.items.filter((item) => item.group === 'defaulting').length, 0), [docs])
  const atEnd = route.zen === 'end'
  const found = queue.findIndex((entry) => entry.item.id === route.zen)
  const index = atEnd ? queue.length : found >= 0 ? found : 0
  const current = !atEnd && queue.length ? queue[index] : null

  // "Later" is a session-only mark: explicit, visible on the progress ticks and the end screen, never exported.
  const [later, setLater] = useState<Set<string>>(() => new Set())
  const [contextOpen, setContextOpen] = useState(false)
  const [noteFocused, setNoteFocused] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const [flash, setFlash] = useState<Choice | null>(null)
  const [copyRequest, setCopyRequest] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const note = useRef<HTMLTextAreaElement>(null)
  const timer = useRef<number | null>(null)

  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current)
  }, [])
  // Focus moves into the lane once the queue arrives, so the keys work from the first frame. WHY only when focus is
  // on <body> or already in this dashboard: Clank swallows single-letter keys aimed at <body>, but focus sitting in
  // another panel (an editor Zach is typing in) is his and is left alone. In-page focus only; no window is fronted.
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
      const target = next >= queue.length ? 'end' : queue[Math.max(0, next)]?.item.id
      if (!target) return
      // WHY replace: moving between cards is sideways; Back should leave the lane, not replay every card.
      navigate({ ...route, zen: target }, 'replace')
      root.current?.focus({ preventScroll: true })
    },
    [navigate, queue, route],
  )

  const advance = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
    goTo(index + 1)
  }, [goTo, index])

  const choose = useCallback(
    (choice: Choice) => {
      if (!current) return
      const { doc, item } = current
      const draft = answers.get(doc.track, item.local_id)
      if (choice === 'other' && !draft?.note.trim()) {
        answers.set(doc.track, item.local_id, { choice })
        setHint('Write your answer, then press ↵ to save it and go on.')
        note.current?.focus()
        return
      }
      answers.set(doc.track, item.local_id, { choice })
      setLater((previous) => {
        if (!previous.has(item.id)) return previous
        const next = new Set(previous)
        next.delete(item.id)
        return next
      })
      // A short beat so the pick is visibly confirmed before the card peels off.
      setFlash(choice)
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => {
        timer.current = null
        goTo(index + 1)
      }, 220)
    },
    [answers, current, goTo, index],
  )

  /** ↵: save what is there and go on; on an untouched card it takes the recommendation (one key). */
  const enter = useCallback(() => {
    if (!current) return
    const { doc, item } = current
    const draft = answers.get(doc.track, item.local_id)
    // WHY only when the loop offers one: grasping and detection record no recommendation, and ↵ must never file an
    // answer to an option the loop did not give ("Go with the recommendation" of nothing).
    if (!draft) {
      if (item.options.some((option) => option.key === 'accept_recommendation')) return choose('accept_recommendation')
      setHint('This loop recorded no recommendation; pick a numbered option or write your own.')
      return
    }
    if (!isComplete(draft)) {
      setHint('"Something else" needs a few words; write them, or pick 1 or 2.')
      note.current?.focus()
      return
    }
    setLater((previous) => {
      if (!previous.has(item.id)) return previous
      const next = new Set(previous)
      next.delete(item.id)
      return next
    })
    advance()
  }, [advance, answers, choose, current])

  const skip = useCallback(() => {
    if (!current) return
    const id = current.item.id
    setLater((previous) => new Set(previous).add(id))
    advance()
  }, [advance, current])

  const copyAll = useCallback(() => {
    if (!atEnd) navigate({ ...route, zen: 'end' }, 'replace')
    setCopyRequest((n) => n + 1)
  }, [atEnd, navigate, route])

  // The end screen's Copy is the kit's own CopyOut (clipboard, then a pre-selected textarea fallback); C presses it.
  useEffect(() => {
    if (!copyRequest || !atEnd) return
    const button = root.current?.querySelector<HTMLButtonElement>('[data-testid="vt-needs-copy"]')
    if (button && !button.disabled) button.click()
    // Bring the copied text into view: on a long lane (rig's six) it lands below the fold.
    const shown = window.setTimeout(() => root.current?.querySelector('.vt-needs-copy-result')?.scrollIntoView({ block: 'center' }), 120)
    return () => window.clearTimeout(shown)
  }, [copyRequest, atEnd])

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
    // A focused link or button keeps its own Enter/Space (the copy textarea, an evidence link, the switcher).
    if ((key === 'Enter' || key === ' ') && target instanceof HTMLElement && target.closest('a, button')) return
    const handled = (fn: () => void) => {
      event.preventDefault()
      event.stopPropagation()
      fn()
    }
    if (key === 'Escape') return handled(() => (contextOpen ? setContextOpen(false) : onBack()))
    if (key === 'j' || key === 'ArrowRight') return handled(() => goTo(index + 1))
    if (key === 'k' || key === 'ArrowLeft') return handled(() => goTo(index - 1))
    if (key === 'c' && !event.shiftKey) return handled(copyAll)
    if (!current) return
    if (key === 'Enter') return handled(enter)
    if (key === 'a') return handled(() => setContextOpen((open) => !open))
    if (key === 's') return handled(skip)
    if (key === 'n') return handled(() => note.current?.focus())
    const number = ['1', '2', '3'].indexOf(key)
    // WHY capture + preventDefault on 1-3: the dashboard's own 1/2/3 switch the A · B · C layout; in the lane they
    // pick an option, and the dashboard's listener skips a defaultPrevented key.
    if (number >= 0 && current.item.options[number]) return handled(() => choose(current.item.options[number].key))
  }
  useEffect(() => {
    const listener = (event: KeyboardEvent) => keyHandler.current(event)
    window.addEventListener('keydown', listener, true)
    return () => window.removeEventListener('keydown', listener, true)
  }, [])

  let body: ReactNode
  if (loading && !docs.length) body = <p className="vt-muted zen-quiet">Reading the loops…</p>
  else if (error && !docs.length) body = <p className="vt-tone-risk zen-quiet">/needs did not answer: {error}</p>
  else if (!queue.length) body = <EmptyLane {...props} defaultingCount={defaultingCount} includeDefaulting={includeDefaulting} />
  else if (atEnd || !current) body = <EndScreen {...props} queue={queue} later={later} defaultingCount={defaultingCount} includeDefaulting={includeDefaulting} onJump={goTo} />
  else
    body = (
      <Card
        {...props}
        entry={current}
        contextOpen={contextOpen}
        onToggleContext={() => setContextOpen((open) => !open)}
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
    <div ref={root} className="vt-needs-n1" tabIndex={-1} data-testid="vt-needs-zen" data-zen-item={current?.item.id ?? (atEnd ? 'end' : '')}>
      <div className="zen-layout">
        <div className="zen-main">
          {queue.length ? <Progress docs={docs} queue={queue} index={index} atEnd={atEnd || !current} later={later} answers={answers} onJump={goTo} /> : null}
          <div className="zen-stage">{body}</div>
        </div>
        {queue.length ? (
          // WHY a rail beside the card and not Sauna's bottom bar: the bottom-right corner belongs to the N1…N5 and
          // A · B · C choosers, which would cover a bottom dock; the keys stay in view while the context scrolls.
          <aside className="zen-rail">
            <Dock
              mode={atEnd || !current ? 'end' : noteFocused ? 'note' : 'card'}
              current={current}
              contextOpen={contextOpen}
              onNext={() => goTo(index + 1)}
              onPrev={() => goTo(index - 1)}
              onEnter={enter}
              onSkip={skip}
              onContext={() => setContextOpen((open) => !open)}
              onCopy={copyAll}
              onLeave={onBack}
              hasDraft={Boolean(current && answers.get(current.doc.track, current.item.local_id))}
            />
          </aside>
        ) : null}
      </div>
    </div>
  )
}

function Progress({
  docs,
  queue,
  index,
  atEnd,
  later,
  answers,
  onJump,
}: {
  docs: NeedsDoc[]
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
  // WHY the contract's two numbers here: the home cell and the track page say "B blocking · M open" from needs.py;
  // the lane must repeat them so the doorway and the room agree (the queue length alone hid the blocking count).
  const summary = headerSummary(docs)
  return (
    <div className="zen-progress" data-testid="vt-zen-progress">
      <p className="zen-progress-line vt-small">
        {current ? (
          <>
            <span className="vt-strong vt-num">
              {index + 1} of {queue.length}
            </span>
            <span className="vt-muted"> · {GROUP_LABEL[current.item.group]}</span>
            {current.item.blocks.length ? <span className="vt-muted"> · blocks {blocksText(current.item)}</span> : null}
            {multiTrack ? <span className="vt-faint"> · {current.doc.track_title}</span> : null}
          </>
        ) : (
          <span className="vt-strong">All {queue.length} seen</span>
        )}
        <span className="zen-progress-meter vt-faint vt-num" data-testid="vt-zen-counts">
          {summary.counts ? (
            <>
              <span className={summary.counts.blocking ? 'vt-tone-warn' : undefined}>{summary.counts.blocking} blocking now</span> · {summary.counts.open} open ·{' '}
            </>
          ) : null}
          {answered} answered{later.size ? ` · ${later.size} later` : ''}
          {summary.notReported.length ? ` · not reported: ${summary.notReported.map((doc) => doc.track_title).join(', ')}` : ''}
        </span>
      </p>
      <div className="zen-ticks" role="list">
        {queue.map((entry, position) => {
          const draft = answers.get(entry.doc.track, entry.item.local_id)
          const state = isComplete(draft) ? 'answered' : later.has(entry.item.id) ? 'later' : 'open'
          return (
            <button
              key={entry.item.id}
              type="button"
              role="listitem"
              className="vt-btn zen-tick"
              data-state={state}
              data-group={entry.item.group}
              aria-current={!atEnd && position === index ? 'step' : undefined}
              title={`${entry.item.local_id} · ${questionText(entry.item)} (${state})`}
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
  contextOpen,
  onToggleContext,
  onChoose,
  flash,
  hint,
  noteRef,
  onNoteFocus,
  onClear,
}: NeedsProposalProps & {
  entry: Entry
  contextOpen: boolean
  onToggleContext(): void
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
  const latest = item.updates.length ? item.updates[item.updates.length - 1] : null
  const opened = item.created.iteration !== null ? `opened ${doc.iteration?.unit ?? 'wave'} ${item.created.iteration}` : shortDate(item.created.ts) ? `opened ${shortDate(item.created.ts)}` : null
  const updated = shortDate(item.updated.ts)
  const contextCount = item.evidence.length
  return (
    <article className="zen-card" key={item.id} data-testid="vt-zen-card" data-item={item.id}>
      <p className="vt-label zen-eyebrow">
        <span className="vt-num">{item.local_id}</span> · {doc.track_title}
        {opened ? <span title={item.created.iteration === null ? hoverTime(item.created.ts) : undefined}>{` · ${opened}`}</span> : ''}
        {updated ? <span title={hoverTime(item.updated.ts)}>{` · updated ${updated}`}</span> : ''}
        {item.asked_by.agent ? ` · asked by ${item.asked_by.agent}` : ''}
      </p>
      <h1 className="zen-question">
        <Verbatim text={item.ask || item.title} />
      </h1>

      {item.context_lead_md ? (
        <section className="zen-why">
          <p className="vt-label">Why it's asked</p>
          <p>
            <Verbatim text={item.context_lead_md} />
          </p>
        </section>
      ) : null}
      {latest ? (
        <section className="zen-why">
          <p className="vt-label">
            Latest update · {latest.header}
            {item.updates.length > 1 ? <span className="vt-faint"> ({item.updates.length} updates; all under Context)</span> : null}
          </p>
          <p>
            <Verbatim text={latest.text_md} />
          </p>
        </section>
      ) : null}

      <section className="zen-options" aria-label="Options">
        <p className="vt-label">Your answer</p>
        {item.options.map((option, position) => {
          const isPicked = picked === option.key
          return (
            <button
              key={option.key}
              type="button"
              className="vt-btn zen-option"
              aria-pressed={isPicked}
              data-testid={`vt-zen-option-${option.key}`}
              onClick={() => onChoose(option.key)}
            >
              <kbd className="zen-key">{position + 1}</kbd>
              <span className="zen-option-text">
                <span className="zen-option-label">
                  {option.label}
                  {option.recommended ? <span className="zen-tag">recommended</span> : null}
                  {option.is_default ? <span className="zen-tag">{item.default.applies.unit === 'never' ? 'what happens now' : 'default'}</span> : null}
                </span>
                {option.is_default ? <span className="zen-option-when vt-small">{defaultTiming(doc, item)}</span> : null}
                {option.detail_md ? (
                  <span className="zen-option-detail vt-small">
                    <Verbatim text={option.detail_md} />
                  </span>
                ) : option.needs_note ? (
                  <span className="zen-option-detail vt-small">Your own answer, in the box below.</span>
                ) : null}
              </span>
            </button>
          )
        })}
        <StaleDraftNotice answers={answers} doc={doc} item={item} />
        <textarea
          ref={noteRef}
          className="zen-note"
          data-testid="vt-zen-note"
          rows={2}
          placeholder="Add a note, or write your own answer (n). ↵ saves and goes on · Shift+↵ new line"
          value={draft?.note ?? ''}
          onChange={(event) => answers.set(doc.track, item.local_id, { note: event.target.value })}
          onFocus={() => onNoteFocus(true)}
          onBlur={() => onNoteFocus(false)}
        />
        <p className="zen-draft-line vt-small" role="status">
          {hint ? (
            <span className="vt-tone-warn">{hint}</span>
          ) : isNoteOnly(draft) ? (
            <>
              <span className="vt-muted">Draft: a note, no option (this question offers no "Something else")</span>{' '}
              <button type="button" className="vt-btn vt-faint zen-clear" onClick={onClear}>
                clear
              </button>
            </>
          ) : draft && effectiveChoice(draft) ? (
            <>
              <span className="vt-muted">
                Draft: {choiceLabel(item, effectiveChoice(draft) as Choice)}
                {draft.note.trim() ? ' + note' : ''}
                {!isComplete(draft) ? ' (needs a note)' : ''}
              </span>{' '}
              <button type="button" className="vt-btn vt-faint zen-clear" onClick={onClear}>
                clear
              </button>
            </>
          ) : (
            <span className="vt-faint">
              {item.options.some((option) => option.key === 'accept_recommendation') ? 'Nothing picked yet; ↵ takes the recommendation.' : 'Nothing picked yet; no recommendation recorded.'}
            </span>
          )}
        </p>
      </section>

      <section className="zen-context">
        <button type="button" className="vt-btn zen-context-toggle vt-small" aria-expanded={contextOpen} onClick={onToggleContext} data-testid="vt-zen-context-toggle">
          <kbd className="zen-key">A</kbd> {contextOpen ? 'Hide' : 'Full context'} {contextCount ? `and ${contextCount} evidence` : ''}
          {item.blocks.length ? ' · what it blocks' : ''}
        </button>
        {contextOpen ? (
          <div className="zen-context-body" data-testid="vt-zen-context">
            {item.provenance_md ? (
              <p className="vt-small vt-muted">
                <Verbatim text={item.provenance_md} />
              </p>
            ) : null}
            <p className="zen-pre">
              <Verbatim text={item.context_base_md.replace(item.provenance_md ?? '\u0000', '').trim() || item.context_md} />
            </p>
            {item.updates.length ? (
              <div className="zen-updates">
                {[...item.updates].reverse().map((update, position) => (
                  <div key={position} className="zen-update">
                    <p className="vt-label">
                      Update · {update.header}
                      {position === 0 ? ' (newest)' : ''}
                    </p>
                    <p className="zen-pre vt-small">
                      <Verbatim text={update.text_md} />
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
            <dl className="zen-facts vt-small">
              <dt>Recommendation</dt>
              <dd>
                <Verbatim text={item.recommendation_md} />
              </dd>
              <dt>If you stay silent</dt>
              <dd>
                <Verbatim text={item.default.text_md} /> <span className="vt-faint">({defaultTiming(doc, item)})</span>
              </dd>
              <dt>Blocks</dt>
              <dd>{item.blocks.length ? item.blocks.map((block) => `${block.id}${block.label ? ` ${block.label}` : ''} (${block.kind})`).join(' · ') : <span className="vt-faint">nothing on the roadmap</span>}</dd>
              <dt>Evidence</dt>
              <dd className="zen-evidence">
                {item.evidence.length ? (
                  item.evidence.map((_, position) => <EvidenceLink key={position} backend={backend} doc={doc} item={item} index={position} projection={projection} />)
                ) : (
                  <span className="vt-faint">none named in the item</span>
                )}
              </dd>
              <dt>Status</dt>
              <dd>
                {item.status}
                {item.raw_status !== item.status ? ` (loop file says ${item.raw_status})` : ''} · {GROUP_LABEL[item.group].toLowerCase()} (computed)
              </dd>
              {item.updated.note ? (
                <>
                  <dt>Last loop event</dt>
                  <dd className="vt-muted">
                    <Verbatim text={item.updated.note} />
                  </dd>
                </>
              ) : null}
            </dl>
          </div>
        ) : null}
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
  openSettings,
  onJump,
}: NeedsProposalProps & { queue: Entry[]; later: Set<string>; defaultingCount: number; includeDefaulting: boolean; onJump(index: number): void }) {
  const answered = queue.filter((entry) => isComplete(answers.get(entry.doc.track, entry.item.local_id))).length
  const laterCount = queue.filter((entry) => later.has(entry.item.id) && !isComplete(answers.get(entry.doc.track, entry.item.local_id))).length
  const open = queue.length - answered - laterCount
  return (
    <article className="zen-card zen-end" data-testid="vt-zen-end">
      <p className="vt-label zen-eyebrow">End of the lane</p>
      <h1 className="zen-question">
        {answered} of {queue.length} answered
      </h1>
      <p className="vt-muted">
        {laterCount ? `${laterCount} left for later` : 'none left for later'}
        {open ? ` · ${open} not answered yet` : ''}. Nothing has been sent: copy the answers and paste them where the loop reads them.
      </p>
      <ol className="zen-summary">
        {queue.map((entry, position) => {
          const draft = answers.get(entry.doc.track, entry.item.local_id)
          const choice = effectiveChoice(draft)
          const complete = isComplete(draft)
          return (
            <li key={entry.item.id}>
              <button type="button" className="vt-btn zen-summary-row" onClick={() => onJump(position)}>
                <span className="vt-faint vt-num zen-summary-id">{entry.item.local_id}</span>
                <span className="zen-summary-text">
                  <span className="zen-summary-title">
                    <Verbatim text={questionMd(entry.item)} />
                  </span>
                  <span className="vt-small">
                    {complete && choice ? (
                      <span>
                        {choiceLabel(entry.item, choice)}
                        {draft?.note.trim() ? <span className="vt-muted zen-summary-note"> · “{draft.note}”</span> : null}
                      </span>
                    ) : answers.stale(entry.doc.track, entry.item.local_id) ? (
                      <span className="vt-muted">your draft is stale: reconfirm or discard it on its card</span>
                    ) : later.has(entry.item.id) ? (
                      <span className="vt-faint">left for later</span>
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
      <CopyOut docs={docs} answers={answers} label="Copy all answers" className="zen-copy" />
      {docs.map((doc) => (
        <p key={doc.track} className="vt-small vt-faint zen-channel">
          {doc.track_title}: {doc.answer_channel.kind === 'jsonl_append' ? 'append the jsonl rows to' : 'paste into'} {doc.answer_channel.target ?? 'the loop'}
          {doc.answer_channel.read_back ? `; read back ${doc.answer_channel.read_back}` : ''}.
        </p>
      ))}
      {!includeDefaulting && defaultingCount ? (
        <p className="zen-more vt-small vt-muted" data-testid="vt-zen-more">
          {defaultingCount} more {defaultingCount === 1 ? 'is' : 'are'} open, but {defaultingCount === 1 ? 'its' : 'their'} default is already in effect (computed from the loop's progress), so {defaultingCount === 1 ? 'it is' : 'they are'} not in this lane. <IncludeDefaultingPointer openSettings={openSettings} testId="vt-zen-settings-link" />
        </p>
      ) : null}
    </article>
  )
}

function EmptyLane({ docs, openSettings, defaultingCount, includeDefaulting }: NeedsProposalProps & { defaultingCount: number; includeDefaulting: boolean }) {
  const summary = headerSummary(docs)
  return (
    <article className="zen-card zen-empty" data-testid="vt-zen-empty">
      <p className="vt-label zen-eyebrow">Needs you{docs.length === 1 ? ` · ${docs[0].track_title}` : ''}</p>
      {/* WHY "Not reported" and not "Nothing is waiting": a track with no structured source (pyblocks, a deployment)
          has null counts; claiming an all-clear there would be a 0 nobody measured. */}
      <h1 className="zen-question" data-testid="vt-zen-empty-head">
        {!summary.reported.length
          ? 'Not reported'
          : summary.notReported.length
            ? 'Nothing is waiting on you in the tracks that report.'
            : `Nothing is waiting on you${docs.length === 1 ? ` in ${docs[0].track_title}` : ''}.`}
      </h1>
      {docs.map((doc) => {
        const counts = headerCounts(doc)
        return (
          <div key={doc.track} className="zen-empty-track">
            {docs.length > 1 ? <p className="vt-strong">{doc.track_title}</p> : null}
            <p className="vt-muted">
              {counts ? (
                <>
                  {counts.blocking} blocking now · {counts.open} open{doc.counts.total !== null ? ` · ${doc.counts.total} items on file` : ''}. {doc.source.note}
                </>
              ) : summary.reported.length ? (
                notReportedText(doc)
              ) : (
                // The headline already says "Not reported"; the note says where the questions live.
                (doc.source.note ?? notReportedText(doc))
              )}
            </p>
            {doc.answer_channel.kind !== 'none' ? (
              <p className="vt-small vt-faint">
                Answers would reach it by {doc.answer_channel.kind.replace(/_/g, ' ')}
                {doc.answer_channel.target ? `: ${doc.answer_channel.target}` : ''}.
              </p>
            ) : null}
          </div>
        )
      })}
      {!includeDefaulting && defaultingCount ? (
        <p className="zen-more vt-small vt-muted" data-testid="vt-zen-more">
          {defaultingCount} open with the default already in effect. <IncludeDefaultingPointer openSettings={openSettings} testId="vt-zen-settings-link" />
        </p>
      ) : null}
    </article>
  )
}

function Dock({
  mode,
  current,
  contextOpen,
  hasDraft,
  onNext,
  onPrev,
  onEnter,
  onSkip,
  onContext,
  onCopy,
  onLeave,
}: {
  mode: 'card' | 'note' | 'end'
  current: Entry | null
  contextOpen: boolean
  hasDraft: boolean
  onNext(): void
  onPrev(): void
  onEnter(): void
  onSkip(): void
  onContext(): void
  onCopy(): void
  onLeave(): void
}) {
  // Every entry is a real button doing exactly what its key does; the dock changes with the sub-mode (Sauna).
  const keys: { k: string; label: string; run(): void }[] =
    mode === 'end'
      ? [
          { k: 'K', label: 'back to the last card', run: onPrev },
          { k: 'C', label: 'copy all answers', run: onCopy },
          { k: 'Esc', label: 'leave', run: onLeave },
        ]
      : mode === 'note'
        ? [
            { k: '↵', label: 'save and next', run: onEnter },
            { k: 'Shift ↵', label: 'new line', run: () => undefined },
            { k: 'Esc', label: 'back to keys', run: () => (document.activeElement as HTMLElement | null)?.blur() },
          ]
        : [
            { k: `1–${current?.item.options.length ?? 3}`, label: 'answer', run: () => undefined },
            // No "take recommendation" key on a card whose loop recorded none (grasping, detection).
            ...(hasDraft || current?.item.options.some((option) => option.key === 'accept_recommendation')
              ? [{ k: '↵', label: hasDraft ? 'save and next' : 'take recommendation', run: onEnter }]
              : []),
            { k: 'N', label: 'note', run: () => (document.querySelector('[data-testid="vt-zen-note"]') as HTMLElement | null)?.focus() },
            { k: 'A', label: contextOpen ? 'hide context' : 'context', run: onContext },
            { k: 'S', label: 'later', run: onSkip },
            { k: 'J', label: 'next', run: onNext },
            { k: 'K', label: 'previous', run: onPrev },
            { k: 'C', label: 'copy all', run: onCopy },
            { k: 'Esc', label: 'leave', run: onLeave },
          ]
  return (
    <div className="zen-dock vt-small" data-testid="vt-zen-dock" data-mode={mode}>
      <p className="vt-label zen-dock-title">{mode === 'end' ? 'Keys · end' : mode === 'note' ? 'Keys · writing' : 'Keys'}</p>
      {keys.map((entry) =>
        entry.label === 'answer' || entry.label === 'new line' ? (
          <span key={entry.k} className="zen-dock-item zen-dock-static">
            <kbd className="zen-key">{entry.k}</kbd> {entry.label}
          </span>
        ) : (
          <button key={entry.k} type="button" className="vt-btn zen-dock-item" onMouseDown={(event) => event.preventDefault()} onClick={entry.run}>
            <kbd className="zen-key">{entry.k}</kbd> {entry.label}
          </button>
        ),
      )}
    </div>
  )
}
