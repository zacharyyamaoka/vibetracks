// Proposal N5 · "Agent conversation" for the Needs-you page.
//
// Each question is the agent asking in a quiet chat thread: the ask, its why, the recommendation and the default are
// the agent's message, evidence rides along as attachments, and the loop's appended UPDATE paragraphs arrive as
// follow-up messages. Zach replies inline with one action (a quick reply or a typed sentence), and every reply
// collects into one outgoing "Answers to agents" message on the right, which leaves through the kit's <CopyOut>.
//
// WHY a chat thread and not a form: the loops already talk to Zach in prose ("Filed at wave-3 close from …"), so a
// thread keeps their words verbatim in the shape they were written, and a reply reads as a reply, not as a field.
// WHY quick replies first and the text box second (Smart Reply): most asks are "yes, go with your recommendation",
// which must cost one click; free text is always there for "no, do this instead".
// WHY nothing is "sent": the backend is read-only and the loops read answers from their own channels, so a reply is a
// local draft until Copy answers; the panel says so instead of pretending to deliver (no fake controls).

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import {
  CopyOut,
  EvidenceLink,
  GROUP_LABEL,
  choiceLabel,
  effectiveChoice,
  isComplete,
  type AnswerDraft,
  type Choice,
  type NeedsDoc,
  type NeedsGroup,
  type NeedsItem,
  type NeedsProposalProps,
} from '../kit'
import { formatLocal } from '../../shared/time'
import './n5.css'

export const NAME = 'Agent conversation'

/** Groups that still want Zach, in page order (blocking first). `defaulting` is open but already going ahead. */
const ASKING: NeedsGroup[] = ['blocking', 'no_default', 'waiting']
const RAIL_OPEN: NeedsGroup[] = ['blocking', 'no_default', 'waiting', 'defaulting']
const RAIL_CLOSED: NeedsGroup[] = ['answered', 'done']

const SKIP_KEY = 'vibetracks.needs.n5.skipped'

interface Thread {
  doc: NeedsDoc
  item: NeedsItem
}

function readSkipped(): Set<string> {
  try {
    const raw = window.sessionStorage.getItem(SKIP_KEY)
    const list = raw ? (JSON.parse(raw) as unknown) : []
    return new Set(Array.isArray(list) ? list.filter((value): value is string => typeof value === 'string') : [])
  } catch {
    return new Set()
  }
}

function writeSkipped(set: Set<string>): void {
  try {
    window.sessionStorage.setItem(SKIP_KEY, JSON.stringify([...set]))
  } catch {
    // Blocked storage: skips hold for this page only.
  }
}

/** Verbatim text with `code` and **bold** spans rendered; every other character is kept as written. */
function Inline({ text }: { text: string }) {
  const parts: ReactNode[] = []
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*/g
  let last = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = pattern.exec(text))) {
    if (match.index > last) parts.push(text.slice(last, match.index))
    if (match[1] !== undefined) parts.push(<code key={key++}>{match[1]}</code>)
    else parts.push(<strong key={key++}>{match[2]}</strong>)
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

// WHY formatLocal (time-format wave): every stamp on every page reads one way, local time with its zone; a proposal
// formatting its own stamps drifted (no zone, or the source's zone).
function when(ts: string | null): string | null {
  if (!ts) return null
  return formatLocal(ts)
}

function initials(agent: string | null): string {
  const name = (agent ?? 'agent').trim()
  return name.slice(0, 2).replace(/^./, (c) => c.toUpperCase())
}

function unitWord(doc: NeedsDoc): string {
  return doc.iteration?.unit ?? 'wave'
}

/** The default line's computed half: when it fires, measured against where the loop is. Labelled as computed. */
function defaultTiming(doc: NeedsDoc, item: NeedsItem): { text: string; tone: 'warn' | 'muted' } {
  const { applies, state } = item.default
  const finished = doc.iteration?.finished
  const at = finished !== null && finished !== undefined ? `the loop has finished ${unitWord(doc)} ${finished}` : null
  if (applies.unit === 'never') return { text: 'No default: this waits for you.', tone: 'warn' }
  if (state === 'in_effect') return { text: `Already in effect (after ${applies.unit} ${applies.after}${at ? `; ${at}` : ''}).`, tone: 'muted' }
  return { text: `Applies after ${applies.unit} ${applies.after}${at ? `; ${at}` : ''}.`, tone: 'muted' }
}

function draftSummary(item: NeedsItem, draft: AnswerDraft | null): string | null {
  const choice = effectiveChoice(draft)
  if (!choice) return null
  return choiceLabel(item, choice)
}

export default function NeedsN5(props: NeedsProposalProps) {
  const { docs, loading, error, answers, route, navigate, track, reload } = props
  const rootRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const [height, setHeight] = useState<number | null>(null)
  const [skipped, setSkipped] = useState<Set<string>>(readSkipped)
  const [showClosed, setShowClosed] = useState<Record<string, boolean>>({})

  // Every thread, in page order per track: blocking, no default, pending, defaulting, then the closed ones.
  const threads = useMemo<Thread[]>(() => docs.flatMap((doc) => doc.items.map((item) => ({ doc, item }))), [docs])
  const answerable = useMemo(() => threads.filter((t) => RAIL_OPEN.includes(t.item.group)), [threads])
  const draftOf = useCallback((t: Thread) => answers.get(t.doc.track, t.item.local_id), [answers])
  const replied = useCallback((t: Thread) => isComplete(draftOf(t)), [draftOf])

  // The first thread that still wants him: the one-click landing (blocking first, never by time).
  const firstWaiting = useMemo(() => {
    const pending = (t: Thread) => !replied(t) && !skipped.has(t.item.id)
    return answerable.find((t) => ASKING.includes(t.item.group) && pending(t)) ?? answerable.find(pending) ?? null
  }, [answerable, replied, skipped])

  const routed = route.n5 ? threads.find((t) => t.item.id === route.n5) ?? null : null
  const [doneView, setDoneView] = useState(false)
  const current = routed ?? (doneView ? null : firstWaiting)

  const select = useCallback(
    (id: string | null) => {
      const next = { ...route }
      if (id) next.n5 = id
      else delete next.n5
      setDoneView(id === null)
      navigate(next, 'replace')
    },
    [navigate, route],
  )

  // Pin the landing thread into the route, so a reply does not swap the thread out from under its own reply bubble.
  useEffect(() => {
    if (!route.n5 && !doneView && firstWaiting) select(firstWaiting.item.id)
  }, [route.n5, doneView, firstWaiting, select])

  // Auto-advance after a reply or a skip, to the next thread that still wants him (Superhuman / Fire & Forget).
  const advanceTimer = useRef<number | null>(null)
  const advanceFrom = useCallback(
    (from: Thread, extraSkipped?: Set<string>) => {
      const skippedNow = extraSkipped ?? skipped
      const order = answerable
      const start = order.findIndex((t) => t.item.id === from.item.id)
      const rest = [...order.slice(start + 1), ...order.slice(0, Math.max(0, start))]
      const next = rest.find((t) => !isComplete(answers.get(t.doc.track, t.item.local_id)) && !skippedNow.has(t.item.id) && ASKING.includes(t.item.group))
      if (advanceTimer.current) window.clearTimeout(advanceTimer.current)
      // WHY a short pause before moving on: the reply bubble lands in the thread first, so he sees what he said.
      advanceTimer.current = window.setTimeout(() => select(next ? next.item.id : null), 650)
    },
    [answerable, answers, select, skipped],
  )
  useEffect(() => () => {
    if (advanceTimer.current) window.clearTimeout(advanceTimer.current)
  }, [])

  const reply = useCallback(
    (t: Thread, choice: Choice | null, note: string) => {
      const text = note.trim()
      if (choice === 'other' && !text) {
        composerRef.current?.focus()
        return
      }
      answers.set(t.doc.track, t.item.local_id, { choice: choice ?? (text ? 'other' : null), note: text })
      if (skipped.has(t.item.id)) {
        const next = new Set(skipped)
        next.delete(t.item.id)
        setSkipped(next)
        writeSkipped(next)
      }
      advanceFrom(t)
    },
    [advanceFrom, answers, skipped],
  )

  const skip = useCallback(
    (t: Thread) => {
      const next = new Set(skipped)
      next.add(t.item.id)
      setSkipped(next)
      writeSkipped(next)
      advanceFrom(t, next)
    },
    [advanceFrom, skipped],
  )

  // Fit the three columns to the dashboard's scroll area so the rail, the thread and the outbox scroll on their own
  // and the composer stays pinned at the bottom of the thread, as in any chat client.
  useLayoutEffect(() => {
    const root = rootRef.current
    const scroller = root?.closest('.vt-scroll') as HTMLElement | null
    if (!root || !scroller) return
    const measure = () => {
      const offset = root.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
      // WHY minus 96: the N-chooser and the A · B · C switcher float over the bottom-right ~90px; the composer and
      // Copy answers must never sit under them.
      setHeight(Math.max(420, scroller.clientHeight - offset - 96))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(scroller)
    return () => observer.disconnect()
  }, [])

  // Keys: J/K next/previous thread (Gmail, Superhuman), A = go with the recommendation, D = let the default apply,
  // R = reply in your own words, S = skip. WHY letters and not 1/2/3: the dashboard owns 1/2/3 for the A · B · C switch.
  // WHY a listener on this page's own root (which keeps focus) and not on window: Clank's workbench consumes bare
  // letter keys while focus sits on <body> (measured: the keydown arrives at window already defaultPrevented), so a
  // window listener would show shortcuts that silently do nothing.
  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
      const target = event.target as HTMLElement | null
      if (target && (target.closest('input, textarea, select, [contenteditable="true"]') || target.isContentEditable)) return
      const key = event.key.toLowerCase()
      const list = answerable
      const index = current ? list.findIndex((t) => t.item.id === current.item.id) : -1
      if (key === 'j' || key === 'k') {
        const next = list[key === 'j' ? Math.min(list.length - 1, index + 1) : Math.max(0, index - 1)]
        if (next) select(next.item.id)
      } else if (current && key === 'a') reply(current, 'accept_recommendation', composerRef.current?.value ?? '')
      else if (current && key === 'd') reply(current, 'use_default', composerRef.current?.value ?? '')
      else if (current && key === 's') skip(current)
      else if (current && key === 'r') composerRef.current?.focus()
      else return
      event.preventDefault()
      event.stopPropagation()
    }
    root.addEventListener('keydown', onKey)
    return () => root.removeEventListener('keydown', onKey)
  }, [answerable, current, reply, select, skip])

  // Keep keyboard focus on this page when the thread changes and focus fell to <body> (the focused control was in the
  // thread that just unmounted). Never pulls focus from another Clank panel or a field.
  const currentId = current?.item.id ?? null
  useEffect(() => {
    const active = document.activeElement
    if (!active || active === document.body || active === document.documentElement) rootRef.current?.focus({ preventScroll: true })
  }, [currentId])

  const totalAsking = threads.filter((t) => ASKING.includes(t.item.group)).length
  const repliedCount = threads.filter(replied).length
  const stillNeed = threads.filter((t) => ASKING.includes(t.item.group) && !replied(t)).length

  return (
    <div className="vt-needs-n5" ref={rootRef} tabIndex={-1} style={{ height: height ?? undefined }} data-testid="vt-needs-n5">
      <aside className="n5-rail" aria-label="Threads" data-testid="n5-rail">
        <div className="n5-rail-head">
          <h1 className="vt-h3">Needs you</h1>
          <p className="vt-small vt-faint">
            {totalAsking} asking · {stillNeed} still need you
          </p>
        </div>
        {loading && !docs.length ? <p className="vt-small vt-muted n5-pad">Reading the loops…</p> : null}
        {error ? (
          <p className="vt-small vt-tone-risk n5-pad">
            /needs did not answer: {error}{' '}
            <button type="button" className="vt-btn n5-link" onClick={reload}>
              Retry
            </button>
          </p>
        ) : null}
        {docs.map((doc) => {
          const open = RAIL_OPEN.flatMap((group) => doc.items.filter((item) => item.group === group))
          const closed = doc.items.filter((item) => RAIL_CLOSED.includes(item.group))
          return (
            <section key={doc.track} className="n5-rail-track" data-testid={`n5-rail-${doc.track}`}>
              <h2 className="n5-rail-title">
                {doc.track_title}
                {doc.counts.blocking_now ? <span className="vt-tone-warn n5-rail-count">{doc.counts.blocking_now} blocking</span> : null}
              </h2>
              {!doc.items.length ? <p className="vt-small vt-faint n5-rail-empty" title={doc.source.note ?? undefined}>No questions from this loop.</p> : null}
              {RAIL_OPEN.map((group) => {
                const items = open.filter((item) => item.group === group)
                if (!items.length) return null
                return (
                  <div key={group} className="n5-rail-group">
                    <p className="n5-rail-group-label">{GROUP_LABEL[group]}</p>
                    {items.map((item) => (
                      <RailRow key={item.id} doc={doc} item={item} current={current?.item.id === item.id} draft={answers.get(doc.track, item.local_id)} skipped={skipped.has(item.id)} onSelect={() => select(item.id)} />
                    ))}
                  </div>
                )
              })}
              {closed.length ? (
                <div className="n5-rail-group">
                  <button type="button" className="vt-btn n5-rail-group-label n5-rail-fold" aria-expanded={Boolean(showClosed[doc.track])} onClick={() => setShowClosed((s) => ({ ...s, [doc.track]: !s[doc.track] }))}>
                    {showClosed[doc.track] ? '▾' : '▸'} Closed by the loop · {closed.length}
                  </button>
                  {showClosed[doc.track]
                    ? closed.map((item) => <RailRow key={item.id} doc={doc} item={item} current={current?.item.id === item.id} draft={null} skipped={false} onSelect={() => select(item.id)} />)
                    : null}
                </div>
              ) : null}
            </section>
          )
        })}
      </aside>

      <main className="n5-main" data-testid="n5-main">
        {current ? (
          <ThreadView key={current.item.id} {...props} thread={current} composerRef={composerRef} draft={draftOf(current)} skipped={skipped.has(current.item.id)} onReply={reply} onSkip={skip} onClear={(t) => answers.clear(t.doc.track, t.item.local_id)} />
        ) : docs.length && !threads.length ? (
          <EmptyState docs={docs} track={track} />
        ) : docs.length ? (
          <div className="n5-done" data-testid="n5-done">
            <p className="vt-h2">You're caught up.</p>
            <p className="vt-muted">
              {repliedCount
                ? `${repliedCount} ${repliedCount === 1 ? 'reply is' : 'replies are'} drafted. Copy them out for the agents.`
                : 'Nothing is drafted yet. Pick a thread on the left to reply.'}
              {skipped.size ? ` ${skipped.size} skipped for now (still open, not in the answers).` : ''}
            </p>
            <CopyOut docs={docs} answers={answers} label="Copy all answers" />
          </div>
        ) : null}
      </main>

      <Outbox {...props} skipped={skipped} repliedCount={repliedCount} stillNeed={stillNeed} onSelect={select} />
    </div>
  )
}

function RailRow({ doc, item, current, draft, skipped, onSelect }: { doc: NeedsDoc; item: NeedsItem; current: boolean; draft: AnswerDraft | null; skipped: boolean; onSelect(): void }) {
  const done = isComplete(draft)
  const tone = item.group === 'blocking' ? 'warn' : item.group === 'no_default' ? 'stale' : 'ok'
  return (
    <button
      type="button"
      className={`vt-btn n5-rail-row${current ? ' is-current' : ''}${done ? ' is-replied' : ''}`}
      aria-current={current ? 'true' : undefined}
      onClick={onSelect}
      title={`${item.local_id} · ${item.title}`}
      data-testid="n5-thread"
      data-item={item.id}
      data-track={doc.track}
    >
      <span className={`n5-dot n5-dot-${tone}`} aria-hidden />
      <span className="n5-rail-id">{item.local_id}</span>
      <span className="n5-rail-text">{item.title}</span>
      {done ? <span className="n5-rail-state">replied</span> : skipped ? <span className="n5-rail-state">skipped</span> : null}
    </button>
  )
}

function EmptyState({ docs, track }: { docs: NeedsDoc[]; track: string | null }) {
  return (
    <div className="n5-empty" data-testid="n5-empty">
      <p className="vt-h2">No agent is asking you anything here.</p>
      {docs.map((doc) => (
        <div key={doc.track} className="n5-empty-track">
          {track ? null : <p className="vt-strong">{doc.track_title}</p>}
          <p className="vt-muted">
            This loop has no structured questions file, so there are no threads to show.
            {doc.source.note ? ' Where its questions actually live:' : ''}
          </p>
          {doc.source.note ? <p className="n5-empty-note">{doc.source.note}</p> : null}
          <p className="vt-small vt-faint">
            An answer would reach it by {doc.answer_channel.kind.replace(/_/g, ' ')}
            {doc.answer_channel.target ? ` → ${doc.answer_channel.target}` : ''}.
          </p>
        </div>
      ))}
    </div>
  )
}

interface ThreadProps extends NeedsProposalProps {
  thread: Thread
  draft: AnswerDraft | null
  skipped: boolean
  composerRef: RefObject<HTMLTextAreaElement | null>
  onReply(t: Thread, choice: Choice | null, note: string): void
  onSkip(t: Thread): void
  onClear(t: Thread): void
}

function ThreadView(props: ThreadProps) {
  const { thread, draft, skipped, composerRef, onReply, onSkip, onClear, backend, projection } = props
  const { doc, item } = thread
  const [fullContext, setFullContext] = useState(false)
  const [showEarlier, setShowEarlier] = useState(false)
  const [text, setText] = useState('')
  const streamRef = useRef<HTMLDivElement>(null)
  const timing = defaultTiming(doc, item)
  const base = item.context_base_md || item.context_md
  const lead = item.context_lead_md
  const foldable = Boolean(lead && lead.length < base.length - 20)
  const earlier = item.updates.length > 2 ? item.updates.slice(0, -2) : []
  const recent = item.updates.length > 2 ? item.updates.slice(-2) : item.updates
  const agent = item.asked_by.agent ?? 'agent'
  const closed = item.group === 'answered' || item.group === 'done'
  const draftLabel = draftSummary(item, draft)
  const complete = isComplete(draft)

  useEffect(() => {
    streamRef.current?.scrollTo({ top: 0 })
  }, [item.id])
  // A new or edited reply scrolls into view, so the bubble he just made is what he sees before the thread moves on.
  const replyKey = `${draft?.choice ?? ''}|${draft?.note ?? ''}|${skipped}`
  const lastReplyKey = useRef(replyKey)
  useEffect(() => {
    if (lastReplyKey.current === replyKey) return
    lastReplyKey.current = replyKey
    const stream = streamRef.current
    if (stream) stream.scrollTo({ top: stream.scrollHeight, behavior: 'smooth' })
  }, [replyKey])

  const send = (choice: Choice | null) => {
    onReply(thread, choice, text)
    setText('')
  }

  const asked = [item.created.iteration !== null ? `${unitWord(doc)} ${item.created.iteration}` : null, when(item.created.ts)].filter(Boolean).join(' · ')

  return (
    <div className="n5-thread" data-testid="n5-threadview" data-item={item.id}>
      <header className="n5-thread-head">
        <p className="vt-small vt-faint">
          {doc.track_title} · {GROUP_LABEL[item.group]}
        </p>
        <h2 className="n5-thread-title">
          <span className="n5-thread-id">{item.local_id}</span> {item.title}
        </h2>
      </header>

      <div className="n5-stream" ref={streamRef}>
        <Message agent={agent} meta={`asked ${asked || 'at an unrecorded time'}`}>
          {item.ask && item.ask !== item.title ? <p className="n5-ask"><Inline text={item.ask} /></p> : null}
          <div className="n5-body" data-testid="n5-context">
            {foldable && !fullContext ? <p><Inline text={lead as string} /></p> : <p className="n5-pre"><Inline text={base} /></p>}
            {foldable ? (
              <button type="button" className="vt-btn n5-link vt-small" onClick={() => setFullContext((v) => !v)} aria-expanded={fullContext} data-testid="n5-more">
                {fullContext ? 'Show less' : `Read the full message (${base.length.toLocaleString()} characters)`}
              </button>
            ) : null}
          </div>

          {item.blocks.length ? (
            <p className="n5-line">
              <span className={item.blocking_now ? 'n5-key vt-tone-warn' : 'n5-key'}>{item.blocking_now ? 'Blocking now' : 'Holds'}</span>
              <span>
                {item.blocks.map((block, index) => (
                  <span key={block.id}>
                    {index ? ', ' : ''}
                    <span className="vt-strong">{block.id}</span>
                    {block.label ? ` ${block.label}` : ''}
                  </span>
                ))}
              </span>
            </p>
          ) : null}

          <div className="n5-rec" data-testid="n5-rec">
            <p className="n5-key">I recommend</p>
            <p className="n5-pre"><Inline text={item.recommendation_md || 'No recommendation recorded.'} /></p>
          </div>

          <div className="n5-default" data-testid="n5-default">
            <p className="n5-key">If you don't answer</p>
            <p className="n5-pre"><Inline text={item.default.text_md || 'No default recorded.'} /></p>
            {/* WHY skip the computed line when the loop's own words already open with "No default": say it once. */}
            {item.default.applies.unit === 'never' && /^no default/i.test(item.default.text_md) ? null : (
            <p className={`vt-small ${timing.tone === 'warn' ? 'vt-tone-warn' : 'vt-faint'}`}>
              {timing.text}
              {item.default.state === 'in_effect' ? ' Computed from the loop’s finished iteration; its own status still reads open.' : ''}
            </p>
            )}
          </div>

          {item.evidence.length ? (
            <div className="n5-attachments" data-testid="n5-attachments">
              {item.evidence.map((entry, index) => (
                <span key={index} className="n5-attachment">
                  <span className="n5-attachment-kind">{entry.kind === 'url' ? 'link' : entry.is_dir ? 'folder' : 'file'}</span>
                  <EvidenceLink backend={backend} doc={doc} item={item} index={index} projection={projection} />
                </span>
              ))}
            </div>
          ) : null}
          {item.provenance_md ? <p className="vt-small vt-faint n5-prov"><Inline text={item.provenance_md} /></p> : null}
        </Message>

        {earlier.length ? (
          showEarlier ? (
            earlier.map((update, index) => (
              <Message key={`e${index}`} agent={agent} meta={`update · ${update.header}`} follow>
                <p className="n5-pre"><Inline text={update.text_md} /></p>
              </Message>
            ))
          ) : (
            <button type="button" className="vt-btn n5-link vt-small n5-earlier" onClick={() => setShowEarlier(true)} data-testid="n5-earlier">
              Show {earlier.length} earlier update{earlier.length === 1 ? '' : 's'}
            </button>
          )
        ) : null}
        {recent.map((update, index) => (
          <Message key={`r${index}`} agent={agent} meta={`update · ${update.header}`} follow>
            <p className="n5-pre"><Inline text={update.text_md} /></p>
          </Message>
        ))}

        {item.answer ? (
          <>
            <Reply meta={`${item.answer.by ? 'you' : 'closed by the loop without your words'}${item.answer.ts ? ` · ${when(item.answer.ts)}` : ''} · recorded by the loop${item.answer.folded ? '' : ' (not folded yet)'}`}>
              {item.answer.choice ? <p className="vt-strong">{choiceLabel(item, item.answer.choice)}</p> : null}
              {item.answer.note ? <p className="n5-pre">{item.answer.quoted ? `“${item.answer.note}”` : item.answer.note}</p> : <p className="vt-faint">No words recorded.</p>}
              {item.answer.note && !item.answer.quoted ? <p className="vt-small vt-faint">The integrator's paraphrase, not your quoted words.</p> : null}
            </Reply>
            {item.answer.action_md ? (
              <Message agent={agent} meta="what the loop did" follow>
                <p className="n5-pre"><Inline text={item.answer.action_md} /></p>
              </Message>
            ) : null}
          </>
        ) : null}

        {draftLabel ? (
          <Reply meta="you · draft, leaves with Copy answers" draft testid="n5-draft">
            <p className="vt-strong">{draftLabel}</p>
            {draft?.note.trim() ? <p className="n5-pre">{draft.note.trim()}</p> : null}
            {!complete ? <p className="vt-small vt-tone-warn">“Something else” needs words; add them below.</p> : null}
            <p className="n5-reply-actions">
              <button
                type="button"
                className="vt-btn n5-link vt-small"
                onClick={() => {
                  setText(draft?.note ?? '')
                  composerRef.current?.focus()
                }}
              >
                Edit
              </button>
              <button type="button" className="vt-btn n5-link vt-small" onClick={() => onClear(thread)} data-testid="n5-withdraw">
                Withdraw
              </button>
            </p>
          </Reply>
        ) : skipped ? (
          <p className="vt-small vt-faint n5-skipped-note" data-testid="n5-skipped">You skipped this for now. It stays open and is left out of the answers.</p>
        ) : null}
      </div>

      {closed ? (
        <p className="n5-composer n5-composer-closed vt-small vt-faint">This thread is closed by the loop. Reopen it in the loop's own channel if it needs you again.</p>
      ) : (
        <div className="n5-composer" data-testid="n5-composer">
          <div className="n5-quick" role="group" aria-label="Quick replies">
            {item.options
              .filter((option) => option.key !== 'other')
              .map((option) => (
                <button
                  key={option.key}
                  type="button"
                  className="vt-btn vt-chip-btn n5-chip"
                  aria-pressed={draft?.choice === option.key}
                  title={option.detail_md ?? option.label}
                  onClick={() => send(option.key)}
                  data-testid={`n5-quick-${option.key}`}
                >
                  {option.label}
                  {option.recommended ? <span className="n5-chip-tag">recommended</span> : null}
                  <kbd>{option.key === 'accept_recommendation' ? 'A' : 'D'}</kbd>
                </button>
              ))}
          </div>
          <div className="n5-input-row">
            <textarea
              ref={composerRef}
              className="n5-input"
              rows={1}
              value={text}
              placeholder={`Reply to ${agent} in your own words (Enter sends)`}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  if (text.trim()) send('other')
                } else if (event.key === 'Escape') {
                  event.currentTarget.blur()
                }
              }}
              data-testid="n5-input"
            />
            <button type="button" className="vt-btn n5-send" disabled={!text.trim()} onClick={() => send('other')} data-testid="n5-send">
              Reply
            </button>
            <button type="button" className="vt-btn n5-link vt-small n5-skip" onClick={() => onSkip(thread)} data-testid="n5-skip" title="Leave it open and move on; it is left out of the answers">
              Skip <kbd>S</kbd>
            </button>
          </div>
          <p className="vt-small vt-faint n5-hint">
            Typed words ride along with a quick reply · J / K moves between threads
          </p>
        </div>
      )}
    </div>
  )
}

function Message({ agent, meta, follow, children }: { agent: string; meta: string; follow?: boolean; children: ReactNode }) {
  return (
    <div className={`n5-msg${follow ? ' is-follow' : ''}`} data-testid="n5-msg">
      <span className="n5-avatar" aria-hidden>
        {initials(agent)}
      </span>
      <div className="n5-msg-main">
        <p className="n5-msg-meta">
          <span className="vt-strong">{agent}</span> <span className="vt-faint">{meta}</span>
        </p>
        <div className="n5-msg-body">{children}</div>
      </div>
    </div>
  )
}

function Reply({ meta, draft, testid, children }: { meta: string; draft?: boolean; testid?: string; children: ReactNode }) {
  return (
    <div className={`n5-reply${draft ? ' is-draft' : ''}`} data-testid={testid ?? 'n5-reply'}>
      <p className="n5-msg-meta vt-faint">{meta}</p>
      <div className="n5-reply-bubble">{children}</div>
    </div>
  )
}

function Outbox({ docs, answers, skipped, repliedCount, stillNeed, onSelect }: NeedsProposalProps & { skipped: Set<string>; repliedCount: number; stillNeed: number; onSelect(id: string): void }) {
  const total = repliedCount + stillNeed
  return (
    <aside className="n5-outbox" aria-label="Answers to agents" data-testid="n5-outbox">
      <h2 className="vt-h3">Answers to agents</h2>
      <p className="vt-small vt-faint">Your replies collect here as one message. Nothing is sent until you copy it out.</p>
      <div className="n5-meter" aria-label={`${repliedCount} replied`}>
        <span style={{ width: total ? `${Math.round((100 * Math.min(repliedCount, total)) / total)}%` : '0%' }} />
      </div>
      <p className="vt-small vt-muted">
        {repliedCount} {repliedCount === 1 ? 'reply' : 'replies'} drafted · {stillNeed} still need you
      </p>
      {docs.map((doc) => {
        const lines = doc.items
          .map((item) => ({ item, draft: answers.get(doc.track, item.local_id) }))
          .filter(({ draft }) => effectiveChoice(draft))
        const skips = doc.items.filter((item) => skipped.has(item.id) && !effectiveChoice(answers.get(doc.track, item.local_id)))
        if (!lines.length && !skips.length) return null
        const channel = doc.answer_channel
        return (
          <section key={doc.track} className="n5-out-track" data-testid={`n5-out-${doc.track}`}>
            <p className="n5-out-to">
              To <span className="vt-strong">{doc.track_title}</span>
            </p>
            <p className="vt-small vt-faint" title={channel.target ?? undefined}>
              {channel.kind === 'jsonl_append' ? `appends to ${channel.target?.split('/').pop() ?? 'the answers file'}` : channel.kind === 'chat_paste' ? "paste into the loop's chat" : channel.kind.replace(/_/g, ' ')}
            </p>
            <ul className="n5-out-lines">
              {lines.map(({ item, draft }) => (
                <li key={item.id}>
                  <button type="button" className="vt-btn n5-out-line" onClick={() => onSelect(item.id)} title={`${item.local_id} · ${item.title}`}>
                    <span className="n5-rail-id">{item.local_id}</span>
                    <span>
                      {draftSummary(item, draft)}
                      {draft?.note.trim() ? <span className="vt-faint"> · “{draft.note.trim()}”</span> : null}
                      {!isComplete(draft) ? <span className="vt-tone-warn"> · needs words</span> : null}
                    </span>
                  </button>
                </li>
              ))}
              {skips.map((item) => (
                <li key={item.id}>
                  <button type="button" className="vt-btn n5-out-line is-skipped" onClick={() => onSelect(item.id)} title={`${item.local_id} · ${item.title}`}>
                    <span className="n5-rail-id">{item.local_id}</span>
                    <span className="vt-faint">skipped, not included</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )
      })}
      <CopyOut docs={docs} answers={answers} />
    </aside>
  )
}
