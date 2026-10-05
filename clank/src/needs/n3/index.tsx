// Proposal N3 · "Review document": the GitHub pull-request review applied to the Needs-you page. Every question is
// one "file" in a single readable document: its why, the loop's options (recommendation and default, verbatim), what
// it holds, its evidence, and an inline answer. Answers save as drafts on every click or keystroke; a pinned
// "pending review" meter (above the document's own scroll, never over it) counts them; one "Finish review → copy" at the end emits the agreed markdown.
//
// WHY a document and not a one-at-a-time focus mode (N1/Sauna): Zach answers better when he can see the neighbouring
// questions (T12 "land on main" and T33 "disk" interact), and a PR review is the reading mode he already uses daily.
// WHY nothing is sent: the backend is read-only and each loop reads answers from its own channel; the pending review
// leaves only through Copy (no fake "Submit").

import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react'
import {
  CopyOut,
  EvidenceLink,
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
  notReportedText,
  useFitToScroller,
  type AnswerDraft,
  type Choice,
  type NeedsDoc,
  type NeedsItem,
  type NeedsOption,
  type NeedsProposalProps,
} from '../kit'
import { Inline, Md } from './md'
import { formatLocal } from '../../shared/time'
import './n3.css'

export const NAME = 'Review document'

const ASK_GROUPS = new Set(['blocking', 'no_default', 'waiting'])
/** Context longer than this is folded behind its lead sentence (never cut: the toggle shows every character). */
const FOLD_CHARS = 700

interface Entry {
  doc: NeedsDoc
  item: NeedsItem
}

// ---- "Skip for now": the one piece of state the shared AnswerStore has no word for. WHY its own key: a skip must be
// explicit and visible (never a silent omission), survive a reload like the drafts do, and never reach the export.
const SKIP_KEY = 'vibetracks.needs.n3.skipped'

function readSkips(): Record<string, true> {
  try {
    const raw = window.localStorage.getItem(SKIP_KEY)
    const value = raw ? (JSON.parse(raw) as unknown) : null
    if (!Array.isArray(value)) return {}
    return Object.fromEntries(value.filter((id): id is string => typeof id === 'string').map((id) => [id, true as const]))
  } catch {
    return {}
  }
}

function useSkips() {
  const [skips, setSkips] = useState<Record<string, true>>(readSkips)
  const set = useCallback((id: string, skipped: boolean) => {
    setSkips((previous) => {
      if (Boolean(previous[id]) === skipped) return previous
      const next = { ...previous }
      if (skipped) next[id] = true
      else delete next[id]
      try {
        window.localStorage.setItem(SKIP_KEY, JSON.stringify(Object.keys(next)))
      } catch {
        // Blocked storage: the skip holds for this page.
      }
      return next
    })
  }, [])
  return { skips, set }
}

// WHY formatLocal (time-format wave): every stamp on every page reads one way, local time with its zone; a proposal
// formatting its own stamps drifted (no zone, or the source's zone).
// A bare clock ("17:55") had no zone, so it was dropped for the one full local stamp.
function clock(iso: string | null | undefined): string {
  return formatLocal(iso)
}

function day(iso: string | null | undefined): string {
  return formatLocal(iso)
}

/** The default's tag on its option row: when it fires, or that it never does. `in_effect` is labelled computed. */
function defaultTag(doc: NeedsDoc, item: NeedsItem): string {
  if (!hasDefault(item) || item.default.state === 'none') return `Default · ${NO_DEFAULT_RECORDED}`
  const after = appliesAfter(item)
  // WHY: the detection plan note never says when its defaults fire; the raw unit read "applies after unstated null".
  if (!after) return `Default · ${WHEN_NOT_STATED}`
  const now = doc.iteration?.finished != null ? `${doc.iteration.unit} ${doc.iteration.finished} finished` : null
  if (item.default.state === 'in_effect') return `Default · already in effect (computed: due ${after}${now ? `; ${now}` : ''})`
  return `Default · applies ${after} if you stay silent${now ? ` (now: ${now})` : ''}`
}

function opened(doc: NeedsDoc, item: NeedsItem): string {
  if (item.created.ts) return `opened ${day(item.created.ts)}`
  if (item.created.iteration !== null) return `opened ${doc.iteration?.unit ?? 'wave'} ${item.created.iteration}`
  return ''
}

function channelWords(doc: NeedsDoc): string {
  const channel = doc.answer_channel
  const target = channel.target ? (channel.target.startsWith('/') ? channel.target.split('/').pop() : channel.target) : null
  if (channel.kind === 'jsonl_append') return `answers reach the loop as rows appended to ${target ?? 'its answers file'} (read ${channel.read_back ?? 'by the loop'})`
  if (channel.kind === 'chat_paste') return `answers reach the loop as a paste into ${target ?? 'its chat'} (read ${channel.read_back ?? 'by hand'})`
  return `answers via ${channel.kind}${target ? ` → ${target}` : ''}`
}

export default function NeedsN3(props: NeedsProposalProps) {
  const { docs, track, loading, error, answers } = props
  const { skips, set: setSkip } = useSkips()
  const multi = track === null

  const asks: Entry[] = useMemo(() => docs.flatMap((doc) => doc.items.filter((item) => ASK_GROUPS.has(item.group)).map((item) => ({ doc, item }))), [docs])
  const defaulting: Entry[] = useMemo(() => docs.flatMap((doc) => doc.items.filter((item) => item.group === 'defaulting').map((item) => ({ doc, item }))), [docs])
  // Card order in the document = j/k order.
  const order: Entry[] = useMemo(
    () => docs.flatMap((doc) => [...asks.filter((entry) => entry.doc === doc), ...defaulting.filter((entry) => entry.doc === doc)]),
    [docs, asks, defaulting],
  )

  const draftOf = useCallback((entry: Entry) => answers.get(entry.doc.track, entry.item.local_id), [answers])
  const answeredAsks = asks.filter((entry) => isComplete(draftOf(entry)))
  const skippedAsks = asks.filter((entry) => !isComplete(draftOf(entry)) && skips[entry.item.id])
  const leftAsks = asks.filter((entry) => !isComplete(draftOf(entry)) && !skips[entry.item.id])
  const overrides = defaulting.filter((entry) => isComplete(draftOf(entry)))

  const rootRef = useRef<HTMLDivElement>(null)
  // WHY a framed page (the review bar above the document's own scroll) and not `position: sticky`: the sticky bar
  // covered whichever card head scrolled under it (kinsim T54 at max scroll, 1440x900). Measured by elementFromPoint.
  const height = useFitToScroller(rootRef)
  const [current, setCurrent] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const cards = useRef(new Map<string, HTMLElement>())
  const isOpen = useCallback((item: NeedsItem) => expanded[item.id] ?? ASK_GROUPS.has(item.group), [expanded])

  useEffect(() => {
    if (current === null && order.length) setCurrent(order[0].item.id)
  }, [current, order])

  const goTo = useCallback((id: string) => {
    setCurrent(id)
    setExpanded((previous) => ({ ...previous, [id]: true }))
    window.requestAnimationFrame(() => cards.current.get(id)?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
  }, [])
  const goToFinish = useCallback(() => {
    document.getElementById('vt-n3-finish')?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [])

  const choose = useCallback(
    (entry: Entry, choice: Choice) => {
      const draft = answers.get(entry.doc.track, entry.item.local_id)
      answers.set(entry.doc.track, entry.item.local_id, { choice: draft?.choice === choice ? null : choice })
      setSkip(entry.item.id, false)
      setCurrent(entry.item.id)
    },
    [answers, setSkip],
  )

  const nextOpen = useCallback(
    (after: string | null): Entry | null => {
      const start = after ? asks.findIndex((entry) => entry.item.id === after) + 1 : 0
      const rest = [...asks.slice(start), ...asks.slice(0, start)]
      return rest.find((entry) => entry.item.id !== after && !isComplete(draftOf(entry)) && !skips[entry.item.id]) ?? null
    },
    [asks, draftOf, skips],
  )

  // Keys: j/k move (Gmail/Superhuman, never reversed), 1/2/3 pick an option of the current item, s skips it.
  // WHY ignored inside a text field: the note is free text, and a "1" typed there must stay a "1".
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      if (target && (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT' || target.tagName === 'SELECT' || target.isContentEditable)) return
      const index = order.findIndex((entry) => entry.item.id === current)
      if (event.key === 'j' || event.key === 'k') {
        const next = order[Math.min(order.length - 1, Math.max(0, index + (event.key === 'j' ? 1 : -1)))]
        if (next) {
          event.preventDefault()
          goTo(next.item.id)
        }
        return
      }
      const entry = order[index]
      if (!entry) return
      if (/^[1-9]$/.test(event.key)) {
        const option = entry.item.options[Number(event.key) - 1]
        if (option) {
          event.preventDefault()
          choose(entry, option.key)
        }
      } else if (event.key === 's') {
        event.preventDefault()
        setSkip(entry.item.id, !skips[entry.item.id])
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [order, current, goTo, choose, setSkip, skips])

  if (loading && !docs.length) return <div ref={rootRef} className="vt-page vt-needs-n3"><p className="vt-muted">Reading the loops…</p></div>
  if (error && !docs.length) return <div ref={rootRef} className="vt-page vt-needs-n3"><p className="vt-tone-risk">/needs did not answer: {error}</p></div>

  const single = !multi ? (props.doc ?? docs[0] ?? null) : null
  const total = asks.length
  const done = answeredAsks.length + skippedAsks.length
  const setOpen = (id: string, value: boolean) => setExpanded((previous) => ({ ...previous, [id]: value }))
  const cardProps = { props, skips, setSkip, choose, isOpen, setOpen, current, setCurrent, cards, nextOpen, goTo, goToFinish }

  return (
    <div ref={rootRef} className="vt-page vt-needs-n3 vt-n3-framed vt-needs-framed" data-testid="vt-needs-n3" style={height ? { height } : undefined}>
      <div className="vt-n3-layout">
        <nav className="vt-n3-toc" aria-label="Questions in this review">
          <p className="vt-label">In this review</p>
          {docs.map((doc) => {
            const docAsks = asks.filter((entry) => entry.doc === doc)
            const docDefaulting = defaulting.filter((entry) => entry.doc === doc)
            return (
              <div key={doc.track} className="vt-n3-toc-track">
                {multi ? <p className="vt-n3-toc-title">{doc.track_title}</p> : null}
                {!doc.items.length ? <p className="vt-small vt-faint">No structured questions</p> : null}
                {doc.items.length && !docAsks.length ? <p className="vt-small vt-faint">Nothing waits for you</p> : null}
                {docAsks.map((entry) => (
                  <TocRow key={entry.item.id} entry={entry} draft={draftOf(entry)} skipped={Boolean(skips[entry.item.id])} current={current === entry.item.id} onGo={goTo} />
                ))}
                {docDefaulting.length ? (
                  <>
                    <p className="vt-n3-toc-group vt-faint">Defaulting without you · {docDefaulting.length}</p>
                    {docDefaulting.map((entry) => (
                      <TocRow key={entry.item.id} entry={entry} draft={draftOf(entry)} skipped={false} current={current === entry.item.id} onGo={goTo} />
                    ))}
                  </>
                ) : null}
              </div>
            )
          })}
        </nav>

        <main className="vt-n3-main">
          {total || overrides.length ? (
            <div className="vt-n3-reviewbar" data-testid="vt-n3-reviewbar">
              <span className="vt-n3-reviewbar-title">Pending review</span>
              <span className="vt-n3-meter" aria-hidden="true">
                <span style={{ width: `${total ? (answeredAsks.length / total) * 100 : 0}%` }} />
                <span className="vt-n3-meter-skip" style={{ width: `${total ? (skippedAsks.length / total) * 100 : 0}%` }} />
              </span>
              <span className="vt-num" data-testid="vt-n3-counter">
                {answeredAsks.length} of {total} answered
                {skippedAsks.length ? ` · ${skippedAsks.length} skipped` : ''}
                {overrides.length ? ` · ${overrides.length} override${overrides.length === 1 ? '' : 's'}` : ''}
              </span>
              <span className="vt-n3-reviewbar-gap" />
              {leftAsks.length ? (
                <button type="button" className="vt-btn vt-n3-link" onClick={() => { const next = nextOpen(current); if (next) goTo(next.item.id) }}>
                  Next unanswered ↓
                </button>
              ) : null}
              <button type="button" className={`vt-btn vt-n3-finish-btn ${total && done === total ? 'is-ready' : ''}`} onClick={goToFinish} data-testid="vt-n3-goto-finish">
                Finish review ↓
              </button>
            </div>
          ) : null}
          <div className="vt-n3-doc" data-testid="vt-n3-doc">
          <header className="vt-n3-header">
            <p className="vt-label">Needs you · review</p>
            <h1 className="vt-h1">{single ? single.track_title : 'Every track'}</h1>
            {single ? <TrackSummary doc={single} /> : <AllSummary docs={docs} />}
          </header>

          {docs.map((doc) => (
            <section key={doc.track} className="vt-n3-track" data-testid={`vt-n3-track-${doc.track}`}>
              {multi ? (
                <div className="vt-n3-track-head">
                  <h2 className="vt-h2">{doc.track_title}</h2>
                  <TrackSummary doc={doc} />
                </div>
              ) : null}
              {!doc.items.length ? <EmptyTrack doc={doc} /> : <TrackBody doc={doc} asks={asks} defaulting={defaulting} {...cardProps} />}
            </section>
          ))}

          {total || overrides.length ? (
            <section id="vt-n3-finish" className="vt-n3-finish" data-testid="vt-n3-finish">
              <h2 className="vt-h2">Finish your review</h2>
              <p className="vt-sub">
                {answeredAsks.length + overrides.length
                  ? `${answeredAsks.length + overrides.length} answer${answeredAsks.length + overrides.length === 1 ? '' : 's'} will be copied as markdown, one heading per question id, in the format the loop reads.`
                  : 'Nothing answered yet. Pick an option or write a note on any question above.'}
              </p>
              {answeredAsks.length || overrides.length ? (
                <ul className="vt-n3-summary">
                  {[...answeredAsks, ...overrides].map((entry) => {
                    const draft = draftOf(entry)
                    const choice = effectiveChoice(draft) as Choice
                    return (
                      <li key={entry.item.id}>
                        <button type="button" className="vt-btn vt-n3-summary-id" onClick={() => goTo(entry.item.id)} title="Back to this question">
                          {multi ? `${entry.doc.track} · ` : ''}
                          {entry.item.local_id}
                        </button>
                        <span className="vt-n3-summary-choice">{choiceLabel(entry.item, choice)}</span>
                        {draft?.note.trim() ? <span className="vt-n3-summary-note">“{draft.note.trim()}”</span> : null}
                        {entry.item.group === 'defaulting' ? <span className="vt-faint vt-small"> · overrides a default in effect</span> : null}
                      </li>
                    )
                  })}
                </ul>
              ) : null}
              {skippedAsks.length || leftAsks.length ? (
                <p className="vt-small vt-muted vt-n3-leftout">
                  Not in the copy:{' '}
                  {skippedAsks.map((entry) => `${entry.item.local_id} (skipped)`).concat(leftAsks.map((entry) => `${entry.item.local_id} (unanswered)`)).join(' · ')}
                </p>
              ) : null}
              <CopyOut docs={docs} answers={answers} label="Finish review → copy" className="vt-n3-copyout" />
              <p className="vt-small vt-faint vt-n3-keys">Keys: j / k move between questions · 1 2 3 pick an option · s skip · drafts save as you go</p>
            </section>
          ) : null}
          </div>
        </main>
      </div>
    </div>
  )
}

/** "B blocking now · M open" from needs.py (headerCounts): the same two numbers as the home cell and the track page,
 * with M split by group after it (disjoint, so the parts sum to M). WHY not counts.no_default: it also counts blocking items
 * with no default, and the old line summed to 8 for rig's 6. Null counts read "Not reported" plus the doc's note. */
function CountsLine({ counts }: { counts: NonNullable<ReturnType<typeof headerCounts>> }) {
  return (
    <span data-testid="vt-n3-counts" data-blocking={counts.blocking} data-open={counts.open}>
      <span className="vt-strong">{counts.open} open</span>
      {': '}
      <span className={counts.blocking ? 'vt-tone-warn' : undefined}>{counts.blocking} blocking now</span>
      {` · ${counts.parts.noDefault} waiting with no default · ${counts.parts.waiting} default pending`}
      {counts.defaulting ? <span className="vt-faint"> · {counts.defaulting} more defaulting without you</span> : null}
    </span>
  )
}

function TrackSummary({ doc }: { doc: NeedsDoc }) {
  const counts = headerCounts(doc)
  return (
    <>
      <p className="vt-sub">{counts ? <CountsLine counts={counts} /> : <span data-testid="vt-n3-not-reported">{notReportedText(doc)}</span>}</p>
      {/* WHY no source line on an empty track: its empty-state box already quotes the note and the channel. */}
      {doc.items.length ? <p className="vt-small vt-faint vt-n3-source">
        {doc.iteration ? `${doc.iteration.unit} ${doc.iteration.n ?? '–'}${doc.iteration.phase ? ` · ${doc.iteration.phase.replace(/_/g, ' ')}` : ''} · ` : ''}
        {doc.source.live ? 'read live' : 'not live'}
        {doc.source.paths[0] ? ` from ${doc.source.paths[0].split('/').pop()}` : ''}
        {doc.source.commit ? ` @${doc.source.commit}` : ''} · {channelWords(doc)}
      </p> : null}
    </>
  )
}

function AllSummary({ docs }: { docs: NeedsDoc[] }) {
  const summary = headerSummary(docs)
  return (
    <p className="vt-sub">
      {summary.counts ? <CountsLine counts={summary.counts} /> : 'Not reported'}
      {summary.counts ? ` across ${summary.reported.length} track${summary.reported.length === 1 ? '' : 's'}` : ''}
      {summary.notReported.length ? <span className="vt-faint"> · not reported: {summary.notReported.map((doc) => doc.track_title).join(', ')}</span> : null}
    </p>
  )
}

function EmptyTrack({ doc }: { doc: NeedsDoc }) {
  return (
    <div className="vt-n3-empty" data-testid="vt-n3-empty">
      <p className="vt-strong">{headerCounts(doc) ? 'Nothing to review here.' : 'Not reported'}</p>
      {/* WHY no note here: the track's summary line right above already reads "Not reported: <note>". */}
      <p className="vt-small vt-muted">This track has no needs-you file, so there are no ids, defaults or statuses to answer against.</p>
      {doc.answer_channel.kind !== 'none' ? (
        <p className="vt-small vt-muted">
          How an answer would reach it: {doc.answer_channel.kind.replace(/_/g, ' ')}
          {doc.answer_channel.target ? ` → ${doc.answer_channel.target}` : ''}
          {doc.answer_channel.read_back ? `; read back ${doc.answer_channel.read_back}` : ''}.
        </p>
      ) : null}
    </div>
  )
}

interface CardContext {
  props: NeedsProposalProps
  skips: Record<string, true>
  setSkip(id: string, skipped: boolean): void
  choose(entry: Entry, choice: Choice): void
  isOpen(item: NeedsItem): boolean
  setOpen(id: string, open: boolean): void
  current: string | null
  setCurrent(id: string): void
  cards: MutableRefObject<Map<string, HTMLElement>>
  nextOpen(after: string | null): Entry | null
  goTo(id: string): void
  goToFinish(): void
}

function TrackBody({ doc, asks, defaulting, ...ctx }: CardContext & { doc: NeedsDoc; asks: Entry[]; defaulting: Entry[] }) {
  const mine = asks.filter((entry) => entry.doc === doc)
  const docDefaulting = defaulting.filter((entry) => entry.doc === doc)
  const recorded = doc.items.filter((item) => item.group === 'answered')
  const closed = doc.items.filter((item) => item.group === 'done').length
  return (
    <>
      {mine.length ? mine.map((entry) => <Card key={entry.item.id} entry={entry} {...ctx} />) : <p className="vt-n3-none vt-muted">Nothing waits for you on this track right now.</p>}
      {docDefaulting.length ? (
        <div className="vt-n3-section">
          <h3 className="vt-h3">
            Defaulting without you <span className="vt-faint">{docDefaulting.length}</span>
          </h3>
          <p className="vt-small vt-muted">Still open in the loop, but their default is already in effect (computed from the finished {doc.iteration?.unit ?? 'iteration'}). Open one only to override it.</p>
          {docDefaulting.map((entry) => (
            <Card key={entry.item.id} entry={entry} {...ctx} />
          ))}
        </div>
      ) : null}
      {recorded.length ? (
        <div className="vt-n3-section">
          <h3 className="vt-h3">
            Answered in the loop <span className="vt-faint">{recorded.length}</span>
          </h3>
          <ul className="vt-n3-recorded">
            {recorded.map((item) => (
              <li key={item.id}>
                <span className="vt-faint vt-num">{item.local_id}</span> <Inline text={item.title} />
                <span className="vt-small vt-muted">
                  {' · '}
                  {item.answer?.choice ? choiceLabel(item, item.answer.choice) : 'answered'}
                  {item.answer?.note ? ` — ${item.answer.note}` : ''}
                  {item.answer && item.answer.by === null ? ' (closed by the loop without your words)' : item.answer && !item.answer.quoted ? " (integrator's paraphrase)" : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {closed ? <p className="vt-small vt-faint vt-n3-closed">{closed} closed item{closed === 1 ? '' : 's'} (defaulted or done) are not part of this review.</p> : null}
    </>
  )
}

function TocRow({ entry, draft, skipped, current, onGo }: { entry: Entry; draft: AnswerDraft | null; skipped: boolean; current: boolean; onGo(id: string): void }) {
  const complete = isComplete(draft)
  const state = complete ? 'answered' : skipped ? 'skipped' : entry.item.blocking_now ? 'blocking' : 'open'
  return (
    <button type="button" className={`vt-btn vt-n3-toc-row ${current ? 'is-current' : ''}`} data-state={state} onClick={() => onGo(entry.item.id)} title={entry.item.title}>
      <span className="vt-n3-glyph" aria-label={state}>{complete ? '●' : skipped ? '–' : '○'}</span>
      <span className="vt-n3-toc-id vt-num">{entry.item.local_id}</span>
      <span className="vt-n3-toc-text">{entry.item.title.replace(/`/g, '')}</span>
    </button>
  )
}

function Card({ entry, ...ctx }: CardContext & { entry: Entry }) {
  const { doc, item } = entry
  const { props, skips, setSkip, choose, isOpen, current, setCurrent, cards, nextOpen, goTo, goToFinish } = ctx
  const [fullContext, setFullContext] = useState(false)
  const [showOlder, setShowOlder] = useState(false)
  const [showChange, setShowChange] = useState(false)
  const draft = props.answers.get(doc.track, item.local_id)
  const choice = effectiveChoice(draft)
  const complete = isComplete(draft)
  const skipped = Boolean(skips[item.id]) && !complete
  const open = isOpen(item)
  // A fold is local view state, not a place: the route is untouched, so Back still leaves the page.
  const toggle = () => {
    setCurrent(item.id)
    ctx.setOpen(item.id, !open)
  }
  const base = item.context_base_md || item.context_md
  const long = base.length > FOLD_CHARS
  const updates = [...item.updates].reverse()
  const next = nextOpen(item.id)
  const isAsk = ASK_GROUPS.has(item.group)

  return (
    <article
      ref={(node) => {
        if (node) cards.current.set(item.id, node)
        else cards.current.delete(item.id)
      }}
      className={`vt-n3-card ${current === item.id ? 'is-current' : ''} ${complete ? 'is-answered' : ''} ${skipped ? 'is-skipped' : ''}`}
      data-testid="vt-n3-card"
      data-item={item.id}
      onMouseDown={() => current !== item.id && setCurrent(item.id)}
    >
      <header className="vt-n3-card-head" onClick={toggle} role="button" tabIndex={0} aria-expanded={open} onKeyDown={(event) => (event.key === 'Enter' || event.key === ' ') && (event.preventDefault(), toggle())}>
        <span className="vt-n3-chevron" aria-hidden="true">{open ? '▾' : '▸'}</span>
        <span className="vt-n3-card-id vt-num">{item.local_id}</span>
        <span className="vt-n3-card-title">
          <Inline text={item.title} />
        </span>
        <span className="vt-n3-card-state">
          {complete ? (
            <span className="vt-n3-pending">Pending · {choiceLabel(item, choice as Choice)}</span>
          ) : skipped ? (
            <span className="vt-faint">Skipped</span>
          ) : (
            <span className={`vt-n3-group vt-n3-group-${item.group}`}>{GROUP_LABEL[item.group]}</span>
          )}
        </span>
      </header>
      {open ? (
        <div className="vt-n3-card-body">
          <p className="vt-n3-meta vt-small vt-muted">
            {item.blocks.length ? (
              <span>
                Holds {item.blocks.map((block) => (block.label ? `${block.id} · ${block.label}` : block.id)).join(', ')}
                {item.blocking_now ? ' (blocking now)' : ''}
              </span>
            ) : (
              <span>Holds no rung</span>
            )}
            <span title={item.created.ts ?? undefined}>{opened(doc, item)}</span>
            {item.updated.ts ? (
              <span title={item.updated.ts}>
                updated {day(item.updated.ts)}
                {item.updated.note ? (
                  <>
                    {' · '}
                    <button type="button" className="vt-btn vt-n3-link" onClick={() => setShowChange(!showChange)} aria-expanded={showChange}>
                      {showChange ? 'hide what changed' : 'what changed'}
                    </button>
                  </>
                ) : null}
              </span>
            ) : null}
            {item.kind !== 'decision' ? <span>{item.kind.replace(/_/g, ' ')}</span> : null}
            {/* WHY evidence sits in the meta row (GitHub's file path in the header): it keeps the answer on the first
                screen when the page opens, and every entry is still one click away. */}
            {item.evidence.length ? (
              <span className="vt-n3-evidence">
                evidence{' '}
                {item.evidence.map((_, index) => (
                  <EvidenceLink key={index} backend={props.backend} doc={doc} item={item} index={index} projection={props.projection} />
                ))}
              </span>
            ) : null}
          </p>
          {/* WHY folded: the loop's change note covers the whole wave (several items), so open it only on request. */}
          {showChange && item.updated.note ? <p className="vt-small vt-muted vt-n3-change"><Inline text={item.updated.note} /></p> : null}

          <div className="vt-n3-block">
            <p className="vt-n3-label">Why it’s asked</p>
            {long && !fullContext ? (
              <>
                {item.context_lead_md ? <Md text={item.context_lead_md} /> : null}
                <button type="button" className="vt-btn vt-n3-link vt-small" onClick={() => setFullContext(true)}>
                  Read the full context · {base.length.toLocaleString()} characters
                </button>
              </>
            ) : (
              <>
                <Md text={base} />
                {long ? (
                  <button type="button" className="vt-btn vt-n3-link vt-small" onClick={() => setFullContext(false)}>
                    Fold the context
                  </button>
                ) : null}
              </>
            )}
          </div>

          {updates.length ? (
            <div className="vt-n3-block">
              <p className="vt-n3-label">Updates · {updates.length}, newest first</p>
              {(showOlder ? updates : updates.slice(0, 1)).map((update, index) => (
                <div key={index} className="vt-n3-update">
                  <p className="vt-small vt-faint">UPDATE {update.header}</p>
                  <Md text={update.text_md} className="vt-small" />
                </div>
              ))}
              {updates.length > 1 ? (
                <button type="button" className="vt-btn vt-n3-link vt-small" onClick={() => setShowOlder(!showOlder)}>
                  {showOlder ? 'Show only the newest update' : `Show ${updates.length - 1} older update${updates.length === 2 ? '' : 's'}`}
                </button>
              ) : null}
            </div>
          ) : null}

          <div className="vt-n3-answer">
            <p className="vt-n3-label">Your answer</p>
            <div role="radiogroup" aria-label={`Answer ${item.local_id}`} className="vt-n3-options">
              {item.options.map((option, index) => (
                <OptionRow key={option.key} doc={doc} item={item} option={option} index={index} picked={choice === option.key && Boolean(draft?.choice || option.key === 'other')} onPick={() => choose(entry, option.key)} />
              ))}
            </div>
            <textarea
              className="vt-needs-note vt-n3-note"
              data-testid="vt-n3-note"
              rows={2}
              value={draft?.note ?? ''}
              placeholder={choice === 'other' && draft?.choice === 'other' ? 'Write what to do instead (needed for “Something else”)' : 'Add a note for the loop (optional; a note on its own answers as “Something else”)'}
              onFocus={() => setCurrent(item.id)}
              onChange={(event) => {
                props.answers.set(doc.track, item.local_id, { note: event.target.value })
                if (event.target.value.trim()) setSkip(item.id, false)
              }}
            />
            <div className="vt-n3-card-foot vt-small">
              {complete ? (
                <span className="vt-muted" title={draft?.updated}>In your pending review · draft saved {clock(draft?.updated)}</span>
              ) : choice === 'other' ? (
                <span className="vt-tone-warn">“Something else” needs a note before it can be copied</span>
              ) : skipped ? (
                <span className="vt-muted">Skipped · left out of the copy</span>
              ) : (
                <span className="vt-faint">Not answered yet</span>
              )}
              <span className="vt-n3-foot-gap" />
              {isAsk && !complete ? (
                <button type="button" className="vt-btn vt-n3-link" onClick={() => setSkip(item.id, !skipped)} data-testid="vt-n3-skip">
                  {skipped ? 'Undo skip' : 'Skip for now'}
                </button>
              ) : null}
              {complete && draft ? (
                <button type="button" className="vt-btn vt-n3-link vt-faint" onClick={() => props.answers.clear(doc.track, item.local_id)}>
                  Discard answer
                </button>
              ) : null}
              {isAsk && (complete || skipped) ? (
                next ? (
                  <button type="button" className="vt-btn vt-n3-link" onClick={() => goTo(next.item.id)}>
                    Next: {next.item.local_id} ↓
                  </button>
                ) : (
                  <button type="button" className="vt-btn vt-n3-link" onClick={goToFinish}>
                    Finish review ↓
                  </button>
                )
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </article>
  )
}

function OptionRow({ doc, item, option, index, picked, onPick }: { doc: NeedsDoc; item: NeedsItem; option: NeedsOption; index: number; picked: boolean; onPick(): void }) {
  return (
    <div
      role="radio"
      aria-checked={picked}
      tabIndex={0}
      className={`vt-n3-option ${picked ? 'is-picked' : ''}`}
      data-testid={`vt-n3-option-${option.key}`}
      onClick={onPick}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onPick()
        }
      }}
    >
      <span className="vt-n3-radio" aria-hidden="true" />
      <span className="vt-n3-option-body">
        <span className="vt-n3-option-label">
          <span className="vt-n3-key vt-faint">{index + 1}</span>
          {option.key === 'other' ? 'Something else' : option.label}
          {option.recommended ? <span className="vt-n3-tag">Recommended</span> : null}
          {option.key === 'use_default' ? <span className="vt-n3-tag vt-n3-tag-quiet">{defaultTag(doc, item)}</span> : null}
        </span>
        {option.detail_md ? <Md text={option.detail_md} className="vt-n3-option-detail" /> : <span className="vt-n3-option-detail vt-faint">Write it in the note below.</span>}
      </span>
    </div>
  )
}
