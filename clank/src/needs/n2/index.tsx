// Proposal N2 · "Inbox + reading pane": the Superhuman / Mail split for the "Needs you" page.
//
// A quiet list of questions on the left (blocking first, each with what it blocks and when its default fires) and a
// reading pane on the right with the whole decision card: why it is asked, what it blocks, what happens if Zach is
// silent and when, the options in the loop's own words with the recommendation first, the evidence, and the answer
// box. The list ends in a real end state, "Copy answers", whose pane reviews every draft and holds the one copy action.
//
// WHY a split and not a stack of cards: Zach (2026-10-04) wants to be "within 1 click" of addressing the questions
// but needs "enough context to actually provide feedback". A split keeps the whole queue visible (what is left, what
// is answered) while the reading pane shows one item's full context at once - the thin one-line row is never the
// only thing on screen.
// WHY the first item is already open on entry: the count is the doorway, not a label; landing on the top blocking
// question with its card expanded is the one-click promise.
// WHY drafts and no "Send": the backend is read-only and the loops read answers from their own channels; Copy answers
// is the only way out, so no control pretends to submit anything (G2, no fake controls).

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
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
import { Md } from './Md'
import './n2.css'

export const NAME = 'Inbox + reading pane'

/** Groups listed in the inbox, in page order. `done` is folded behind its own row (46 closed items on kinsim). */
const OPEN_GROUPS: NeedsGroup[] = ['blocking', 'no_default', 'waiting', 'defaulting']
const LIST_GROUPS: NeedsGroup[] = [...OPEN_GROUPS, 'answered']

const COPY_KEY = 'copy'
const ROUTE_KEY = 'ask'
const LATER_STORAGE = 'vibetracks.needs.n2.later'

type Entry = { kind: 'item'; key: string; doc: NeedsDoc; item: NeedsItem } | { kind: 'copy'; key: string }

function itemKey(doc: NeedsDoc, item: NeedsItem): string {
  return `${doc.track}:${item.local_id}`
}

// "Later" is a per-viewer convenience (which items Zach chose to come back to), so localStorage is fine; every
// access is wrapped because storage is often blocked on Clank origins.
function readLater(): Set<string> {
  try {
    const raw = window.localStorage.getItem(LATER_STORAGE)
    const value = raw ? (JSON.parse(raw) as unknown) : []
    return new Set(Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : [])
  } catch {
    return new Set()
  }
}
function writeLater(later: Set<string>): void {
  try {
    window.localStorage.setItem(LATER_STORAGE, JSON.stringify([...later]))
  } catch {
    // Blocked storage: "later" holds for this page.
  }
}

function shortDate(ts: string | null | undefined): string | null {
  if (!ts) return null
  // WHY: a bare "2026-10-02" parses as UTC midnight, which reads as Oct 1 in Vancouver; a date-only value is a day.
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ts)
  const date = day ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3])) : new Date(ts)
  if (Number.isNaN(date.getTime())) return ts.slice(0, 10)
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function blocksText(item: NeedsItem): string {
  return item.blocks.map((block) => block.id).join(', ')
}

/** The list row's second line: what it holds and when its default fires, in the shared state vocabulary. */
function rowMeta(item: NeedsItem): string {
  const parts: string[] = []
  if (item.blocks.length) parts.push(`blocks ${blocksText(item)}`)
  const { applies, state } = item.default
  if (item.group === 'answered') parts.push(`answered${item.answer?.ts ? ` ${shortDate(item.answer.ts)}` : ''}`)
  else if (item.group === 'done') parts.push(item.status)
  else if (applies.unit === 'never') parts.push('no default · waits for you')
  else if (state === 'in_effect') parts.push(`default in effect since ${applies.unit} ${applies.after}`)
  else parts.push(`default after ${applies.unit} ${applies.after}`)
  return parts.join(' · ')
}

function whenText(doc: NeedsDoc, item: NeedsItem): string {
  const { applies, state } = item.default
  const at = doc.iteration ? `the loop has finished ${doc.iteration.unit} ${doc.iteration.finished ?? '–'}` : null
  if (applies.unit === 'never') return 'Never. This waits for you.'
  if (state === 'in_effect') return `In effect now: due after ${applies.unit} ${applies.after}, and ${at ?? 'that has passed'} (computed by the dashboard).`
  return `After ${applies.unit} ${applies.after}${at ? `; ${at}` : ''}.`
}

function draftWord(item: NeedsItem, draft: AnswerDraft | null): { text: string; tone: 'done' | 'warn' } | null {
  const choice = effectiveChoice(draft)
  if (!choice) return null
  if (!isComplete(draft)) return { text: 'note needed', tone: 'warn' }
  if (choice === 'accept_recommendation') return { text: 'recommendation', tone: 'done' }
  if (choice === 'use_default') return { text: item.default.applies.unit === 'never' ? 'keep waiting' : 'default', tone: 'done' }
  return { text: 'your words', tone: 'done' }
}

export default function NeedsN2(props: NeedsProposalProps) {
  const { docs, loading, error, answers, route, navigate } = props
  const [later, setLater] = useState<Set<string>>(readLater)
  const [showDone, setShowDone] = useState<Set<string>>(() => new Set())
  const rootRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const paneRef = useRef<HTMLDivElement>(null)
  const noteRef = useRef<HTMLTextAreaElement>(null)
  const [height, setHeight] = useState<number | null>(null)

  // The inbox order: per track, open groups first (the backend already sorts items), answered next, done folded.
  const entries = useMemo<Entry[]>(() => {
    const list: Entry[] = []
    for (const doc of docs) {
      for (const group of [...LIST_GROUPS, 'done' as NeedsGroup]) {
        if (group === 'done' && !showDone.has(doc.track)) continue
        for (const item of doc.items) if (item.group === group) list.push({ kind: 'item', key: itemKey(doc, item), doc, item })
      }
    }
    list.push({ kind: 'copy', key: COPY_KEY })
    return list
  }, [docs, showDone])

  const isOpenAsk = (entry: Entry) => entry.kind === 'item' && OPEN_GROUPS.includes(entry.item.group)

  // Selection lives in the route (`ask=kinsim:T47`), so a reload or a pasted link reopens the same question.
  const requested = route[ROUTE_KEY]
  const firstOpen = entries.find((entry) => isOpenAsk(entry)) ?? entries.find((entry) => entry.kind === 'item') ?? entries[entries.length - 1]
  const selected = entries.find((entry) => entry.key === requested) ?? firstOpen
  const selectedIndex = entries.indexOf(selected)

  const select = useCallback(
    (key: string) => {
      // WHY replace: moving along the inbox is a sideways move; Back should leave the page, not replay every row.
      navigate({ ...route, [ROUTE_KEY]: key }, 'replace')
    },
    [navigate, route],
  )

  /** The next question still wanting an answer after `from` (wrapping), else the Copy answers end state. */
  const nextUnsettled = useCallback(
    (from: number, skip: Set<string> = later): string => {
      const open = entries.filter((entry) => isOpenAsk(entry))
      const after = [...entries.slice(from + 1), ...entries.slice(0, from + 1)]
      const target = after.find(
        (entry) => open.includes(entry) && entry.key !== selected.key && !skip.has(entry.key) && !isComplete(answers.get((entry as { doc: NeedsDoc }).doc.track, (entry as { item: NeedsItem }).item.local_id)),
      )
      return target?.key ?? COPY_KEY
    },
    [entries, later, answers, selected.key],
  )

  const markLater = useCallback(
    (key: string, on: boolean) => {
      const next = new Set(later)
      if (on) next.add(key)
      else next.delete(key)
      setLater(next)
      writeLater(next)
      return next
    },
    [later],
  )

  const choose = useCallback(
    (entry: Entry, choice: Choice, mode: 'toggle' | 'set') => {
      if (entry.kind !== 'item') return
      const draft = answers.get(entry.doc.track, entry.item.local_id)
      const value = mode === 'toggle' && draft?.choice === choice ? null : choice
      answers.set(entry.doc.track, entry.item.local_id, { choice: value })
      if (later.has(entry.key)) markLater(entry.key, false)
    },
    [answers, later, markLater],
  )

  // Fit the split to the scroll container so the list and the reading pane scroll on their own, like a mail client.
  useLayoutEffect(() => {
    const root = rootRef.current
    const scroll = root?.closest('.vt-scroll') as HTMLElement | null
    if (!root || !scroll) return
    const fit = () => {
      const top = root.getBoundingClientRect().top - scroll.getBoundingClientRect().top + scroll.scrollTop
      setHeight(Math.max(480, Math.floor(scroll.clientHeight - top)))
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(scroll)
    return () => observer.disconnect()
  }, [])

  // Keys work as soon as the page opens: J/K or arrows move, 1/2/3 answer.
  useEffect(() => {
    rootRef.current?.focus({ preventScroll: true })
  }, [])

  // A new selection starts at the top of its card, and its row is kept in view.
  useEffect(() => {
    paneRef.current?.scrollTo({ top: 0 })
    listRef.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(selected.key)}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [selected.key])

  const onKeyDown = (event: KeyboardEvent) => {
    const target = event.target as HTMLElement
    // WHY a window listener scoped to "inside this page, or nothing focused": Clank often leaves focus on <body>
    // after the viewer mounts, and the keys must work the moment the page opens; a key typed into another Clank
    // pane's own element is never taken.
    // "Inside" is the whole dashboard viewer: focus often sits on the shell's own ← Back or the N-chooser.
    const inside = target instanceof Node && Boolean((rootRef.current?.closest('.vt-dash') ?? rootRef.current)?.contains(target))
    const onBody = target === document.body || target === document.documentElement
    // A hidden Clank tab keeps this page mounted; it has no client rects then, and must not take keys.
    if (event.defaultPrevented || !rootRef.current || !rootRef.current.getClientRects().length || !(inside || onBody)) return
    if (event.altKey || event.metaKey || (event.ctrlKey && event.key !== 'Enter')) return
    if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT' || target.tagName === 'SELECT') {
      if (event.key === 'Escape') {
        event.preventDefault()
        rootRef.current?.focus({ preventScroll: true })
      } else if (event.key === 'Enter' && event.ctrlKey) {
        event.preventDefault()
        rootRef.current?.focus({ preventScroll: true })
        select(nextUnsettled(selectedIndex))
      }
      return
    }
    const onControl = target.tagName === 'BUTTON' || target.tagName === 'A' || target.tagName === 'SUMMARY'
    const key = event.key
    if (key === 'j' || key === 'ArrowDown') {
      event.preventDefault()
      select(entries[Math.min(entries.length - 1, selectedIndex + 1)].key)
    } else if (key === 'k' || key === 'ArrowUp') {
      event.preventDefault()
      select(entries[Math.max(0, selectedIndex - 1)].key)
    } else if (key === 'c') {
      event.preventDefault()
      select(COPY_KEY)
    } else if (selected.kind === 'item') {
      if ((key === '1' || (key === 'Enter' && !onControl)) && selected.item.options[0]) {
        event.preventDefault()
        choose(selected, selected.item.options[0].key, 'set')
        select(nextUnsettled(selectedIndex))
      } else if (key === '2' && selected.item.options[1]) {
        event.preventDefault()
        choose(selected, selected.item.options[1].key, 'set')
        select(nextUnsettled(selectedIndex))
      } else if (key === '3' || key === 'n') {
        event.preventDefault()
        if (key === '3') choose(selected, 'other', 'set')
        noteRef.current?.focus()
      } else if (key === 'l') {
        event.preventDefault()
        const next = markLater(selected.key, !later.has(selected.key))
        if (next.has(selected.key)) select(nextUnsettled(selectedIndex, next))
      }
    }
  }

  // WHY capture phase + preventDefault: the dashboard's own window listener turns 1/2/3 into the A · B · C layout
  // switch; here they answer, and the dashboard skips a key that was already handled.
  const keyHandler = useRef(onKeyDown)
  keyHandler.current = onKeyDown
  useEffect(() => {
    const listener = (event: KeyboardEvent) => keyHandler.current(event)
    window.addEventListener('keydown', listener, true)
    return () => window.removeEventListener('keydown', listener, true)
  }, [])

  // The meter counts open asks only: items whose default already applied still count, because answering them is
  // still Zach's to do; the loop-answered and closed ones do not.
  const openEntries = entries.filter(isOpenAsk) as Extract<Entry, { kind: 'item' }>[]
  const answeredCount = openEntries.filter((entry) => isComplete(answers.get(entry.doc.track, entry.item.local_id))).length
  const laterCount = openEntries.filter((entry) => later.has(entry.key) && !isComplete(answers.get(entry.doc.track, entry.item.local_id))).length
  const draftsTotal = docs.reduce((sum, doc) => sum + doc.items.filter((item) => isComplete(answers.get(doc.track, item.local_id))).length, 0)
  const single = docs.length === 1 ? docs[0] : null
  const hasItems = entries.some((entry) => entry.kind === 'item')

  return (
    <div
      ref={rootRef}
      className="vt-needs-n2"
      data-testid="vt-needs-n2"
      tabIndex={-1}
      style={height ? { height } : undefined}
    >
      <header className="n2-head">
        <div className="n2-head-text">
          <h1 className="vt-h2">Needs you{single ? <span className="vt-muted"> · {single.track_title}</span> : null}</h1>
          <p className="vt-small vt-muted n2-counts" data-testid="n2-counts">
            {docs.length ? <Counts docs={docs} /> : loading ? 'Reading the loops…' : null}
          </p>
        </div>
        {openEntries.length ? (
          <div className="n2-meter" data-testid="n2-meter" title="Answered drafts out of the open questions">
            <span className="vt-small vt-num">
              <span className="vt-strong">{answeredCount}</span> of {openEntries.length} answered
              {laterCount ? <span className="vt-faint"> · {laterCount} later</span> : null}
            </span>
            <span className="n2-meter-bar" aria-hidden>
              <span style={{ width: `${(100 * answeredCount) / openEntries.length}%` }} />
            </span>
          </div>
        ) : null}
      </header>
      {error ? <p className="vt-small vt-tone-risk n2-error">/needs did not answer: {error}</p> : null}

      <div className="n2-split">
        <nav className="n2-list" ref={listRef} aria-label="Questions" data-testid="n2-list">
          {docs.map((doc) => (
            <TrackList
              key={doc.track}
              doc={doc}
              multi={docs.length > 1}
              entries={entries}
              selectedKey={selected.key}
              onSelect={select}
              answers={props.answers}
              later={later}
              doneShown={showDone.has(doc.track)}
              onToggleDone={() => {
                const next = new Set(showDone)
                if (next.has(doc.track)) next.delete(doc.track)
                else next.add(doc.track)
                setShowDone(next)
              }}
            />
          ))}
          {hasItems ? (
          <>
          <button
            type="button"
            className="vt-btn n2-row n2-row-copy"
            data-key={COPY_KEY}
            aria-current={selected.key === COPY_KEY}
            onClick={() => select(COPY_KEY)}
            data-testid="n2-copy-row"
          >
            <span className="n2-row-title">Copy answers</span>
            <span className="n2-row-meta vt-small vt-faint">
              {draftsTotal ? `${draftsTotal} ready to copy` : 'nothing answered yet'}
            </span>
          </button>
          <p className="n2-keys vt-small vt-faint" data-testid="n2-keys">
            <kbd>J</kbd>/<kbd>K</kbd> move · <kbd>1</kbd> or <kbd>↵</kbd> recommendation · <kbd>2</kbd> default · <kbd>3</kbd> write · <kbd>L</kbd> later · <kbd>C</kbd> copy
          </p>
          </>
          ) : null}
        </nav>

        <article className="n2-pane" ref={paneRef} data-testid="n2-pane">
          {!hasItems && docs.length ? (
            <EmptyPane docs={docs} />
          ) : selected.kind === 'copy' ? (
            <CopyPane {...props} entries={entries} later={later} onSelect={select} />
          ) : (
            <ItemPane
              {...props}
              key={selected.key}
              entry={selected}
              noteRef={noteRef}
              later={later.has(selected.key)}
              onChoose={(choice, mode) => choose(selected, choice, mode)}
              onLater={() => {
                const next = markLater(selected.key, !later.has(selected.key))
                if (next.has(selected.key)) select(nextUnsettled(selectedIndex, next))
              }}
              onNext={() => select(nextUnsettled(selectedIndex))}
            />
          )}
          {!docs.length && !loading && !error ? <p className="vt-muted">No tracks answered /needs.</p> : null}
        </article>
      </div>
    </div>
  )
}

function Counts({ docs }: { docs: NeedsDoc[] }) {
  const sum = (key: keyof NeedsDoc['counts']) => docs.reduce((total, doc) => total + doc.counts[key], 0)
  const blocking = sum('blocking_now')
  const parts = [
    <span key="b" className={blocking ? 'vt-tone-warn' : undefined}>
      {blocking} blocking now
    </span>,
    <span key="n">{sum('no_default')} no default</span>,
    <span key="w">{sum('waiting')} default pending</span>,
    <span key="d">{sum('defaulting')} defaulting without you</span>,
  ]
  const single = docs.length === 1 ? docs[0] : null
  return (
    <>
      {parts.map((part, index) => (
        <span key={index}>
          {index ? ' · ' : ''}
          {part}
        </span>
      ))}
      {single?.iteration ? (
        <span className="vt-faint">
          {' '}
          · loop at {single.iteration.unit} {single.iteration.n ?? '–'}
          {single.iteration.phase ? ` (${single.iteration.phase.replace(/_/g, ' ')})` : ''}
        </span>
      ) : null}
      {docs.length > 1 ? <span className="vt-faint"> · {docs.length} tracks</span> : null}
    </>
  )
}

interface TrackListProps {
  doc: NeedsDoc
  multi: boolean
  entries: Entry[]
  selectedKey: string
  onSelect(key: string): void
  answers: NeedsProposalProps['answers']
  later: Set<string>
  doneShown: boolean
  onToggleDone(): void
}

function TrackList({ doc, multi, selectedKey, onSelect, answers, later, doneShown, onToggleDone }: TrackListProps) {
  const done = doc.items.filter((item) => item.group === 'done')
  return (
    <section className="n2-track" data-testid={`n2-track-${doc.track}`}>
      {multi ? <h2 className="n2-track-title vt-small vt-strong">{doc.track_title}</h2> : null}
      {!doc.items.length ? (
        // WHY the loop's own note and not "all clear": these tracks have questions, just not in a structured file;
        // saying "nothing needs you" would be untrue.
        <div className="n2-empty vt-small" data-testid="n2-empty">
          <p className="vt-muted">No structured questions from this loop yet.</p>
          {multi && doc.source.note ? <p className="vt-faint n2-empty-note">{doc.source.note}</p> : null}
          {multi && doc.answer_channel.target ? (
            <p className="vt-faint n2-empty-note">
              Answers reach it by {doc.answer_channel.kind.replace(/_/g, ' ')}: {doc.answer_channel.target}
              {doc.answer_channel.read_back ? `; ${doc.answer_channel.read_back}` : ''}.
            </p>
          ) : null}
        </div>
      ) : null}
      {LIST_GROUPS.map((group) => {
        const items = doc.items.filter((item) => item.group === group)
        if (!items.length) return null
        return (
          <div key={group} className="n2-group">
            <h3 className={`n2-group-title vt-small ${group === 'blocking' ? 'vt-tone-warn' : 'vt-faint'}`}>
              {GROUP_LABEL[group]} <span className="vt-num">{items.length}</span>
            </h3>
            {items.map((item) => (
              <Row key={item.id} doc={doc} item={item} selected={selectedKey === itemKey(doc, item)} onSelect={onSelect} draft={answers.get(doc.track, item.local_id)} later={later.has(itemKey(doc, item))} />
            ))}
          </div>
        )
      })}
      {done.length ? (
        <div className="n2-group">
          <button type="button" className="vt-btn n2-group-title n2-fold vt-small vt-faint" onClick={onToggleDone} aria-expanded={doneShown} data-testid={`n2-done-${doc.track}`}>
            {doneShown ? '▾' : '▸'} {GROUP_LABEL.done} <span className="vt-num">{done.length}</span>
          </button>
          {doneShown
            ? done.map((item) => (
                <Row key={item.id} doc={doc} item={item} selected={selectedKey === itemKey(doc, item)} onSelect={onSelect} draft={answers.get(doc.track, item.local_id)} later={later.has(itemKey(doc, item))} />
              ))
            : null}
        </div>
      ) : null}
    </section>
  )
}

function Row({ doc, item, selected, onSelect, draft, later }: { doc: NeedsDoc; item: NeedsItem; selected: boolean; onSelect(key: string): void; draft: AnswerDraft | null; later: boolean }) {
  const key = itemKey(doc, item)
  const word = draftWord(item, draft)
  const settled = word?.tone === 'done' || item.group === 'answered' || item.group === 'done'
  return (
    <button
      type="button"
      className={`vt-btn n2-row${settled ? ' n2-row-settled' : ''}`}
      data-key={key}
      aria-current={selected}
      onClick={() => onSelect(key)}
      data-testid="n2-row"
      data-item={item.id}
    >
      <span className="n2-row-line">
        <span className="n2-row-id vt-num">{item.local_id}</span>
        {/* WHY a CSS line clamp: it ends in a visible ellipsis, and the full title heads the reading pane. */}
        <span className="n2-row-title" title={item.title}>
          {item.title}
        </span>
        {word ? (
          <span className={`n2-row-state vt-small ${word.tone === 'warn' ? 'vt-tone-warn' : ''}`} data-testid="n2-row-state">
            {word.tone === 'done' ? '✓ ' : ''}
            {word.text}
          </span>
        ) : later ? (
          <span className="n2-row-state vt-small vt-faint" data-testid="n2-row-state">
            later
          </span>
        ) : null}
      </span>
      <span className={`n2-row-meta vt-small ${item.blocking_now ? 'vt-tone-warn' : 'vt-faint'}`}>{rowMeta(item)}</span>
    </button>
  )
}

interface ItemPaneProps extends NeedsProposalProps {
  entry: Extract<Entry, { kind: 'item' }>
  noteRef: RefObject<HTMLTextAreaElement | null>
  later: boolean
  onChoose(choice: Choice, mode: 'toggle' | 'set'): void
  onLater(): void
  onNext(): void
}

function ItemPane({ entry, answers, backend, projection, noteRef, later, onChoose, onLater, onNext, docs }: ItemPaneProps) {
  const { doc, item } = entry
  const titleRef = useRef<HTMLHeadingElement>(null)
  const draft = answers.get(doc.track, item.local_id)
  const choice = effectiveChoice(draft)
  const complete = isComplete(draft)
  const lead = item.context_lead_md
  const base = item.context_base_md || item.context_md
  // The provenance sentence is shown on its own line, so the body below it starts where the loop's argument does.
  const body = item.provenance_md && base.startsWith(item.provenance_md) ? base.slice(item.provenance_md.length).trim() : base
  const updates = [...item.updates].reverse()
  const opened = [item.created.iteration !== null ? `${doc.iteration?.unit ?? 'wave'} ${item.created.iteration}` : null, shortDate(item.created.ts)].filter(Boolean).join(' · ')
  const updated = shortDate(item.updated.ts)

  return (
    <div className="n2-card" data-testid="n2-card" data-item={item.id}>
      <StickyTitle titleRef={titleRef} id={item.local_id} title={item.title} />
      <p className="vt-small vt-faint n2-kicker">
        <span className="vt-num">{item.local_id}</span>
        {' · '}
        <span className={item.blocking_now ? 'vt-tone-warn vt-strong' : undefined}>{GROUP_LABEL[item.group]}</span>
        {docs.length > 1 ? ` · ${doc.track_title}` : ''}
        {item.kind !== 'decision' ? ` · ${item.kind.replace(/_/g, ' ')}` : ''}
      </p>
      <h2 className="vt-h2 n2-title" ref={titleRef}>
        <Md text={item.ask || item.title} />
      </h2>

      <dl className="n2-props vt-small">
        <dt>Blocks</dt>
        <dd data-testid="n2-blocks">
          {item.blocks.length
            ? item.blocks.map((block, index) => (
                <span key={block.id}>
                  {index ? ' · ' : ''}
                  <span className="vt-strong">{block.id}</span>
                  {block.label ? <span className="vt-muted"> {block.label}</span> : null}
                </span>
              ))
            : <span className="vt-faint">nothing named</span>}
        </dd>
        <dt>If you stay silent</dt>
        <dd data-testid="n2-default">
          {item.default.applies.unit === 'never' ? <span>{item.default.text_md ? <Md text={item.default.text_md} /> : 'No default.'}</span> : <Md text={item.default.text_md} />}
        </dd>
        <dt>When</dt>
        <dd className={item.default.state === 'in_effect' ? 'vt-muted' : undefined} data-testid="n2-when">
          {whenText(doc, item)}
        </dd>
        <dt>Opened</dt>
        <dd className="vt-muted">
          {opened || '–'}
          {updated && updated !== shortDate(item.created.ts) ? ` · updated ${updated}` : ''}
          {item.asked_by.agent ? ` · asked by ${item.asked_by.agent}` : ''}
        </dd>
      </dl>

      {lead ? (
        <section className="n2-section">
          <h3 className="n2-label">Why it's asked</h3>
          <p className="n2-prose">
            <Md text={lead} />
          </p>
        </section>
      ) : null}

      {item.answer ? <LoopAnswer item={item} /> : null}

      <section className="n2-section n2-answer" data-testid="n2-answer">
        <h3 className="n2-label">
          Your answer
          {complete ? <span className="n2-saved"> · drafted, goes out with Copy answers</span> : null}
        </h3>
        <div className="n2-options" role="radiogroup" aria-label="Answer">
          {item.options.map((option, index) => {
            const pressed = choice === option.key
            const tags = [option.recommended ? 'recommended' : null, option.is_default && item.default.applies.unit !== 'never' ? `default · ${item.default.state === 'in_effect' ? 'in effect' : `after ${item.default.applies.unit} ${item.default.applies.after}`}` : null].filter(Boolean)
            return (
              <button
                key={option.key}
                type="button"
                role="radio"
                aria-checked={pressed}
                className={`vt-btn n2-option${pressed ? ' n2-option-on' : ''}`}
                onClick={(event) => {
                  // WHY detail 0 sets instead of toggling: Enter or Space on a focused option re-fires its click,
                  // and that must never silently un-answer the item; only a second mouse click unpicks.
                  onChoose(option.key, event.detail === 0 ? 'set' : 'toggle')
                  if (option.key === 'other') window.setTimeout(() => noteRef.current?.focus(), 0)
                }}
                data-testid={`n2-option-${option.key}`}
              >
                <span className="n2-option-key vt-num">{index + 1}</span>
                <span className="n2-option-body">
                  <span className="n2-option-label">
                    {option.label}
                    {tags.length ? <span className="vt-faint vt-small"> · {tags.join(' · ')}</span> : null}
                  </span>
                  {option.detail_md ? (
                    <span className="n2-option-detail vt-small">
                      <Md text={option.detail_md} />
                    </span>
                  ) : option.key === 'other' ? (
                    <span className="n2-option-detail vt-small vt-faint">Say what to do instead in the note below.</span>
                  ) : null}
                </span>
              </button>
            )
          })}
        </div>
        <textarea
          ref={noteRef}
          className="n2-note"
          rows={2}
          placeholder={choice === 'other' ? 'What should the loop do instead? (required)' : 'Note for the loop (optional; a note alone answers as "Something else")'}
          value={draft?.note ?? ''}
          onChange={(event) => answers.set(doc.track, item.local_id, { note: event.target.value })}
          data-testid="n2-note"
        />
        <div className="n2-actions vt-small">
          {choice && !complete ? <span className="vt-tone-warn">"Something else" needs a note before it can be copied.</span> : null}
          <span className="n2-actions-right">
            {draft ? (
              <button type="button" className="vt-btn vt-muted n2-link" onClick={() => answers.clear(doc.track, item.local_id)} data-testid="n2-clear">
                Clear
              </button>
            ) : null}
            {!complete ? (
              <button type="button" className="vt-btn vt-muted n2-link" onClick={onLater} aria-pressed={later} data-testid="n2-later">
                {later ? 'Marked later · undo' : 'Later'}
              </button>
            ) : null}
            <button type="button" className="vt-btn n2-link n2-next" onClick={onNext} data-testid="n2-next">
              Next question ↓
            </button>
          </span>
        </div>
      </section>

      {body && body !== lead ? (
        <section className="n2-section">
          <h3 className="n2-label">Full context · verbatim</h3>
          {item.provenance_md ? (
            <p className="vt-small vt-faint n2-provenance">
              <Md text={item.provenance_md} />
            </p>
          ) : null}
          <p className="n2-prose n2-body" data-testid="n2-context">
            <Md text={body} />
          </p>
        </section>
      ) : item.provenance_md ? (
        <p className="vt-small vt-faint n2-provenance">
          <Md text={item.provenance_md} />
        </p>
      ) : null}

      {updates.length ? (
        <section className="n2-section" data-testid="n2-updates">
          <h3 className="n2-label">Updates · newest first</h3>
          <Update update={updates[0]} />
          {updates.length > 1 ? (
            <details className="n2-earlier">
              <summary className="vt-small vt-muted">
                {updates.length - 1} earlier update{updates.length === 2 ? '' : 's'}
              </summary>
              {updates.slice(1).map((update, index) => (
                <Update key={index} update={update} />
              ))}
            </details>
          ) : null}
        </section>
      ) : null}

      {item.evidence.length ? (
        <section className="n2-section">
          <h3 className="n2-label">Evidence</h3>
          <ul className="n2-evidence vt-small" data-testid="n2-evidence">
            {item.evidence.map((_, index) => (
              <li key={index}>
                <EvidenceLink backend={backend} doc={doc} item={item} index={index} projection={projection} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="vt-small vt-faint n2-channel">
        Answers reach {doc.track_title} by {doc.answer_channel.kind.replace(/_/g, ' ')}
        {doc.answer_channel.target ? `: ${doc.answer_channel.target}` : ''}
        {doc.answer_channel.read_back ? `; read back ${doc.answer_channel.read_back.replace(/^at /, 'at ')}` : ''}.
      </p>
    </div>
  )
}

/** Once the question's title scrolls away, a one-line strip keeps it in sight, as a mail client keeps the subject.
 *  WHY zero height: the strip overlays the pane instead of pushing the card, so showing it never moves the text. */
function StickyTitle({ titleRef, id, title }: { titleRef: RefObject<HTMLHeadingElement | null>; id: string; title: string }) {
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const heading = titleRef.current
    const pane = heading?.closest('.n2-pane')
    if (!heading || !pane || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => setShown(!entry.isIntersecting), { root: pane, threshold: 0 })
    observer.observe(heading)
    return () => observer.disconnect()
  }, [titleRef])
  return (
    <div className="n2-sticky" aria-hidden={!shown}>
      <div className={`n2-sticky-bar${shown ? ' n2-sticky-on' : ''}`} title={title}>
        <span className="vt-faint vt-num">{id}</span> <span className="vt-strong">{title}</span>
      </div>
    </div>
  )
}

function Update({ update }: { update: NeedsItem['updates'][number] }) {
  return (
    <div className="n2-update">
      <p className="vt-small vt-faint">UPDATE {update.header}</p>
      <p className="n2-prose">
        <Md text={update.text_md} />
      </p>
    </div>
  )
}

/** What the loop itself recorded, kept apart from Zach's draft so the two are never confused. */
function LoopAnswer({ item }: { item: NeedsItem }) {
  const answer = item.answer
  if (!answer) return null
  return (
    <section className="n2-section n2-loop-answer" data-testid="n2-loop-answer">
      <h3 className="n2-label">Already recorded by the loop{answer.ts ? ` · ${shortDate(answer.ts)}` : ''}</h3>
      {answer.by === 'zach' && answer.note ? (
        <p className="n2-prose">
          {answer.quoted ? '“' : ''}
          {answer.note}
          {answer.quoted ? '”' : ''}
          <span className="vt-faint vt-small"> {answer.quoted ? 'your words' : "the integrator's paraphrase"}</span>
        </p>
      ) : (
        <p className="vt-small vt-muted">Closed by the loop without your words{answer.choice ? ` (${choiceLabel(item, answer.choice)})` : ''}.</p>
      )}
      {answer.action_md ? (
        <p className="vt-small vt-muted">
          Done: <Md text={answer.action_md} />
        </p>
      ) : null}
    </section>
  )
}

function CopyPane({ docs, answers, entries, later, onSelect }: NeedsProposalProps & { entries: Entry[]; later: Set<string>; onSelect(key: string): void }) {
  const items = entries.filter((entry): entry is Extract<Entry, { kind: 'item' }> => entry.kind === 'item')
  const drafted = items.filter((entry) => effectiveChoice(answers.get(entry.doc.track, entry.item.local_id)))
  const laterItems = items.filter((entry) => later.has(entry.key) && !isComplete(answers.get(entry.doc.track, entry.item.local_id)))
  const unanswered = items.filter((entry) => OPEN_GROUPS.includes(entry.item.group) && !effectiveChoice(answers.get(entry.doc.track, entry.item.local_id)) && !later.has(entry.key))
  return (
    <div className="n2-card n2-copy" data-testid="n2-copy-pane">
      <p className="vt-small vt-faint n2-kicker">End of the inbox</p>
      <h2 className="vt-h2 n2-title">Copy answers</h2>
      <p className="vt-sub vt-small">
        Every drafted answer, in one paste-ready block per track. Nothing has left this page yet: paste the block into the loop's chat
        {docs.some((doc) => doc.answer_channel.row_schema) ? ', or append its jsonl rows to the answers file' : ''}.
      </p>

      <section className="n2-section">
        <h3 className="n2-label">Answered · {drafted.length}</h3>
        {drafted.length ? (
          <ul className="n2-review" data-testid="n2-review">
            {drafted.map((entry) => {
              const draft = answers.get(entry.doc.track, entry.item.local_id)
              const choice = effectiveChoice(draft)
              const complete = isComplete(draft)
              return (
                <li key={entry.key}>
                  <button type="button" className="vt-btn n2-review-row" onClick={() => onSelect(entry.key)}>
                    <span className="n2-row-id vt-num">{entry.item.local_id}</span>
                    <span className="n2-review-text">
                      <span className="n2-review-title">{entry.item.title}</span>
                      <span className={`vt-small ${complete ? 'vt-muted' : 'vt-tone-warn'}`}>
                        {choice ? choiceLabel(entry.item, choice) : ''}
                        {draft?.note.trim() ? ` · “${draft.note.trim()}”` : complete ? '' : ' · needs a note'}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="vt-small vt-faint">Nothing answered yet. Pick an option on any question; it lands here.</p>
        )}
      </section>

      {laterItems.length || unanswered.length ? (
        <section className="n2-section">
          <h3 className="n2-label">Not in the copy</h3>
          <p className="vt-small vt-muted">
            {laterItems.length ? (
              <>
                Later: <ItemLinks entries={laterItems} onSelect={onSelect} />.{' '}
              </>
            ) : null}
            {unanswered.length ? (
              <>
                Unanswered: <ItemLinks entries={unanswered} onSelect={onSelect} />.
              </>
            ) : null}
          </p>
        </section>
      ) : null}

      <CopyOut docs={docs} answers={answers} label="Copy all answers" className="n2-copyout" />
    </div>
  )
}

function ItemLinks({ entries, onSelect }: { entries: Extract<Entry, { kind: 'item' }>[]; onSelect(key: string): void }) {
  return (
    <>
      {entries.map((entry, index) => (
        <span key={entry.key}>
          {index ? ', ' : ''}
          <button type="button" className="vt-btn n2-inline-link" onClick={() => onSelect(entry.key)}>
            {entry.item.local_id}
          </button>
        </span>
      ))}
    </>
  )
}

/** No structured questions on any shown track: say where each loop's questions actually live, never "all clear". */
function EmptyPane({ docs }: { docs: NeedsDoc[] }) {
  return (
    <div className="n2-card" data-testid="n2-empty-pane">
      <h2 className="vt-h2 n2-title">No structured questions yet</h2>
      <p className="vt-sub vt-small">
        {docs.length === 1 ? 'This loop does' : 'These loops do'} not publish a needs-you file, so there is nothing to answer here. Where {docs.length === 1 ? 'its' : 'their'} questions live today:
      </p>
      {docs.map((doc) => (
        <section key={doc.track} className="n2-section">
          <h3 className="n2-label">{doc.track_title}</h3>
          <p className="n2-prose">{doc.source.note ?? 'This loop publishes no needs-you file.'}</p>
          {doc.answer_channel.target ? (
            <p className="vt-small vt-muted">
              To answer it anyway: {doc.answer_channel.kind.replace(/_/g, ' ')} to {doc.answer_channel.target}
              {doc.answer_channel.read_back ? `; ${doc.answer_channel.read_back}` : ''}.
            </p>
          ) : null}
        </section>
      ))}
    </div>
  )
}
