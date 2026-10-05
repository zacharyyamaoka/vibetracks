// Proposal N4 · Decision cards. Each open question is one card that LEADS WITH THE DECISION: its options are big
// one-click choices (the recommendation marked, the default named with when it fires), "Something else…" opens a text
// answer, and the loop's full context sits folded one click (or Space) below. A stack of pills above the card shows
// answered vs skipped vs remaining; answering auto-advances to the next unresolved card, and the run ends on a done
// card whose one action is Copy answers.
//
// WHY the decision first and the context folded: Zach's ask (2026-10-04) is "within 1 click … start addressing these",
// and these loops already hand him a recommendation and a default for every item, so most answers are a click on a
// choice he can read in full on the button itself. The why-line stays visible so a click is never blind.
// WHY one card at a time, not a list: a list makes every question compete; a card is a finite queue with a real end
// (Superhuman / Readwise), and the pill stack keeps the whole queue in view so nothing is hidden.
// WHY "Defaulting without you" is a second, optional segment: those items are open in the loop but their default is
// already in effect (computed by the backend), so they never gate "done"; they are there to override, not to answer.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CopyOut, EvidenceLink, GROUP_LABEL, choiceLabel, effectiveChoice, isComplete, type Choice, type NeedsDoc, type NeedsItem, type NeedsOption, type NeedsProposalProps } from '../kit'
import { Md } from './md'
import './style/n4.css'

export const NAME = 'Decision cards'

type Segment = 'needs' | 'optional'
interface Entry {
  key: string
  doc: NeedsDoc
  item: NeedsItem
  segment: Segment
}

const NEEDS_GROUPS = ['blocking', 'no_default', 'waiting'] as const
const DONE = 'done'
const SKIP_KEY = 'vibetracks.needs.n4.skipped'
// WHY a short pause before advancing: the reader sees the choice land on the card before it moves on; any longer and
// a fast reader clicks the next card's button in the old card's place.
const ADVANCE_MS = 420

// ---- skipped items: a per-viewer convenience (which cards I set aside), never an answer, so it is not in the store.
function readSkipped(): Set<string> {
  try {
    const raw = window.localStorage.getItem(SKIP_KEY)
    const list = raw ? (JSON.parse(raw) as unknown) : []
    return new Set(Array.isArray(list) ? list.filter((value): value is string => typeof value === 'string') : [])
  } catch {
    return new Set()
  }
}
function writeSkipped(skipped: Set<string>): void {
  try {
    window.localStorage.setItem(SKIP_KEY, JSON.stringify([...skipped]))
  } catch {
    // Blocked storage: skips hold for this page.
  }
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || Boolean(target.closest('.cm-editor'))
}

function formatTs(ts: string | null): string | null {
  if (!ts) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(ts)) return ts
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return ts
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** When the default fires, in words; a computed state says so. */
function defaultWhen(doc: NeedsDoc, item: NeedsItem): string {
  const { applies, state } = item.default
  if (applies.unit === 'never') return 'No default: the loop waits for you'
  const at = `${applies.unit} ${applies.after}`
  if (state === 'in_effect') return `Already in effect: it applied after ${at} (computed from the loop's progress)`
  const now = doc.iteration?.finished != null ? ` · ${doc.iteration.unit} ${doc.iteration.finished} has finished` : ''
  return `Applies if you stay silent past ${at}${now}`
}

function blocksText(item: NeedsItem): string | null {
  if (!item.blocks.length) return null
  return item.blocks.map((block) => (block.label ? `${block.id} ${block.label}` : block.id)).join(', ')
}

export default function NeedsN4(props: NeedsProposalProps) {
  const { docs, loading, error, answers, route, navigate, reload, track } = props
  const [skipped, setSkipped] = useState<Set<string>>(readSkipped)

  const entries = useMemo<Entry[]>(() => {
    const all: Entry[] = []
    for (const doc of docs) {
      for (const item of doc.items) {
        if ((NEEDS_GROUPS as readonly string[]).includes(item.group)) all.push({ key: item.id, doc, item, segment: 'needs' })
        else if (item.group === 'defaulting') all.push({ key: item.id, doc, item, segment: 'optional' })
      }
    }
    // Across tracks, blocking first, then no default, then pending, then defaulting; the backend's order within.
    const rank = (entry: Entry) => (entry.segment === 'optional' ? 9 : NEEDS_GROUPS.indexOf(entry.item.group as (typeof NEEDS_GROUPS)[number]))
    return all.map((entry, index) => ({ entry, index })).sort((a, b) => rank(a.entry) - rank(b.entry) || a.index - b.index).map(({ entry }) => entry)
  }, [docs])
  const needsEntries = entries.filter((entry) => entry.segment === 'needs')
  const optionalEntries = entries.filter((entry) => entry.segment === 'optional')

  const answered = useCallback((entry: Entry) => isComplete(answers.get(entry.doc.track, entry.item.local_id)), [answers])
  const resolved = useCallback((entry: Entry) => answered(entry) || skipped.has(entry.key), [answered, skipped])

  const firstOpen = (needsEntries.find((entry) => !resolved(entry)) ?? (needsEntries.length ? null : optionalEntries.find((entry) => !resolved(entry))))?.key
  const routed = route.n4card
  const currentKey = routed === DONE ? DONE : routed && entries.some((entry) => entry.key === routed) ? routed : (firstOpen ?? (entries.length ? DONE : null))
  const current = entries.find((entry) => entry.key === currentKey) ?? null

  const go = useCallback(
    (key: string) => {
      // A sideways move inside the queue: replace, so Back still leaves the page in one step.
      navigate({ ...route, n4card: key }, 'replace')
    },
    [navigate, route],
  )

  /** The next unresolved card in the same segment (after `from`, wrapping), else the done card. */
  const nextKey = useCallback(
    (from: Entry, justResolved = true): string => {
      const segment = entries.filter((entry) => entry.segment === from.segment)
      const at = segment.findIndex((entry) => entry.key === from.key)
      const order = [...segment.slice(at + 1), ...segment.slice(0, at)]
      const next = order.find((entry) => !resolved(entry) && !(justResolved && entry.key === from.key))
      return next?.key ?? DONE
    },
    [entries, resolved],
  )

  const pending = useRef<number | null>(null)
  useEffect(() => () => {
    if (pending.current) window.clearTimeout(pending.current)
  }, [])
  const advanceFrom = useCallback(
    (entry: Entry) => {
      if (pending.current) window.clearTimeout(pending.current)
      pending.current = window.setTimeout(() => {
        pending.current = null
        go(nextKey(entry))
      }, ADVANCE_MS)
    },
    [go, nextKey],
  )

  const setSkip = useCallback((entry: Entry, on: boolean) => {
    setSkipped((previous) => {
      const next = new Set(previous)
      if (on) next.add(entry.key)
      else next.delete(entry.key)
      writeSkipped(next)
      return next
    })
  }, [])

  const choose = useCallback(
    (entry: Entry, choice: Choice) => {
      const draft = answers.get(entry.doc.track, entry.item.local_id)
      // Picking an option keeps a note already typed; switching away from "Something else" keeps it as the note.
      answers.set(entry.doc.track, entry.item.local_id, { choice, note: draft?.note ?? '' })
      setSkip(entry, false)
      advanceFrom(entry)
    },
    [answers, advanceFrom, setSkip],
  )

  const skip = useCallback(
    (entry: Entry) => {
      setSkip(entry, true)
      go(nextKey(entry))
    },
    [go, nextKey, setSkip],
  )

  const step = useCallback(
    (delta: 1 | -1) => {
      if (!entries.length) return
      const at = currentKey === DONE ? entries.length : entries.findIndex((entry) => entry.key === currentKey)
      const target = at + delta
      if (target >= entries.length) go(DONE)
      else if (target >= 0) go(entries[target].key)
    },
    [entries, currentKey, go],
  )

  if (loading && !docs.length) {
    return (
      <div className="vt-page vt-needs-n4">
        <p className="vt-muted">Reading the loops…</p>
      </div>
    )
  }

  const doc = props.doc
  const empty = docs.filter((candidate) => !candidate.items.some((item) => (NEEDS_GROUPS as readonly string[]).includes(item.group) || item.group === 'defaulting'))
  const decided = docs.flatMap((candidate) => candidate.items.filter((item) => item.group === 'answered' || item.group === 'done').map((item) => ({ doc: candidate, item })))
  const answeredCount = needsEntries.filter(answered).length
  const skippedCount = needsEntries.filter((entry) => !answered(entry) && skipped.has(entry.key)).length

  return (
    <div className="vt-page vt-needs-n4" data-testid="vt-needs-n4">
      <header className="n4-head">
        <p className="vt-label">Needs you{doc?.iteration ? ` · ${doc.iteration.unit} ${doc.iteration.n ?? '–'}${doc.iteration.phase ? `, ${doc.iteration.phase.replace(/_/g, ' ')}` : ''}` : ''}</p>
        <h1 className="vt-h1">{doc ? doc.track_title : 'Every track'}</h1>
        <p className="vt-sub">{summaryLine(docs)}</p>
        {error ? (
          <p className="vt-small vt-tone-risk">
            /needs did not answer: {error}{' '}
            <button type="button" className="vt-btn n4-link" onClick={reload}>
              Read again
            </button>
          </p>
        ) : null}
      </header>

      {entries.length ? (
        <Stack
          needs={needsEntries}
          optional={optionalEntries}
          currentKey={currentKey}
          answered={answered}
          skipped={skipped}
          onPick={go}
          multiTrack={!track}
          answeredCount={answeredCount}
        />
      ) : null}

      {current ? (
        <Card key={current.key} {...props} entry={current} multiTrack={!track} skipped={skipped.has(current.key)} onChoose={choose} onSkip={skip} onStep={step} onAdvance={() => go(nextKey(current))} onUnskip={() => setSkip(current, false)} />
      ) : currentKey === DONE ? (
        <DoneCard
          {...props}
          needs={needsEntries}
          optional={optionalEntries}
          answeredCount={answeredCount}
          skippedCount={skippedCount}
          answered={answered}
          skipped={skipped}
          onPick={go}
        />
      ) : null}

      {entries.length && currentKey !== DONE ? (
        <section className="n4-tray" aria-label="Your answers">
          <AnswerTray entries={entries} answers={answers} onPick={go} currentKey={currentKey} />
          <CopyOut docs={docs} answers={answers} />
        </section>
      ) : null}

      {empty.length ? <EmptyTracks docs={empty} lone={entries.length === 0} /> : null}
      {decided.length ? <Decided decided={decided} /> : null}
    </div>
  )
}

function summaryLine(docs: NeedsDoc[]): string {
  if (docs.length && docs.every((doc) => !doc.items.length)) return 'No structured questions in this loop yet'
  const total = docs.reduce(
    (sum, doc) => ({
      blocking: sum.blocking + doc.counts.blocking_now,
      noDefault: sum.noDefault + doc.items.filter((item) => item.group === 'no_default').length,
      waiting: sum.waiting + doc.counts.waiting,
      defaulting: sum.defaulting + doc.counts.defaulting,
    }),
    { blocking: 0, noDefault: 0, waiting: 0, defaulting: 0 },
  )
  const parts = [
    `${total.blocking} blocking now`,
    total.noDefault ? `${total.noDefault} waiting for you with no default` : null,
    total.waiting ? `${total.waiting} with a default pending` : null,
    total.defaulting ? `${total.defaulting} defaulting without you` : null,
  ].filter(Boolean)
  return parts.join(' · ')
}

// ---- the stack: one pill per card, in queue order; it is both the progress meter and the way to jump.
function Stack({
  needs,
  optional,
  currentKey,
  answered,
  skipped,
  onPick,
  multiTrack,
  answeredCount,
}: {
  needs: Entry[]
  optional: Entry[]
  currentKey: string | null
  answered(entry: Entry): boolean
  skipped: Set<string>
  onPick(key: string): void
  multiTrack: boolean
  answeredCount: number
}) {
  const pill = (entry: Entry) => {
    const isAnswered = answered(entry)
    const state = isAnswered ? 'answered' : skipped.has(entry.key) ? 'skipped' : 'open'
    const label = multiTrack ? `${entry.doc.track} ${entry.item.local_id}` : entry.item.local_id
    return (
      <button
        key={entry.key}
        type="button"
        className={`vt-btn n4-pill n4-pill-${state}${entry.item.blocking_now ? ' n4-pill-blocking' : ''}`}
        aria-current={entry.key === currentKey ? 'step' : undefined}
        title={`${entry.item.local_id} · ${entry.item.title} (${state === 'open' ? GROUP_LABEL[entry.item.group].toLowerCase() : state})`}
        onClick={() => onPick(entry.key)}
        data-testid="n4-pill"
        data-state={state}
      >
        {state === 'answered' ? <span className="n4-pill-mark">✓</span> : state === 'skipped' ? <span className="n4-pill-mark">–</span> : entry.item.blocking_now ? <span className="n4-dot" /> : null}
        {label}
      </button>
    )
  }
  return (
    <nav className="n4-stack" aria-label="Questions" data-testid="n4-stack">
      {needs.length ? (
        <div className="n4-stack-seg">
          <span className="n4-stack-label">
            Needs you <span className="vt-num">{answeredCount}/{needs.length}</span> answered
          </span>
          <span className="n4-pills">{needs.map(pill)}</span>
        </div>
      ) : null}
      {optional.length ? (
        <div className="n4-stack-seg n4-stack-optional">
          <span className="n4-stack-label">
            Defaulting without you <span className="vt-num">{optional.length}</span> · optional
          </span>
          <span className="n4-pills">{optional.map(pill)}</span>
        </div>
      ) : null}
      <button type="button" className={`vt-btn n4-pill n4-pill-done`} aria-current={currentKey === DONE ? 'step' : undefined} onClick={() => onPick(DONE)} title="The end of the queue: copy your answers">
        Done
      </button>
    </nav>
  )
}

// ---- one decision card
function Card({
  entry,
  answers,
  backend,
  projection,
  multiTrack,
  skipped,
  onChoose,
  onSkip,
  onStep,
  onAdvance,
  onUnskip,
}: NeedsProposalProps & {
  entry: Entry
  multiTrack: boolean
  skipped: boolean
  onChoose(entry: Entry, choice: Choice): void
  onSkip(entry: Entry): void
  onStep(delta: 1 | -1): void
  onAdvance(): void
  onUnskip(): void
}) {
  const { doc, item } = entry
  const draft = answers.get(doc.track, item.local_id)
  const choice = effectiveChoice(draft)
  const [otherOpen, setOtherOpen] = useState(choice === 'other')
  const [noteOpen, setNoteOpen] = useState(Boolean(draft?.note && choice !== 'other'))
  const [contextOpen, setContextOpen] = useState(false)
  const cardRef = useRef<HTMLElement>(null)
  const otherRef = useRef<HTMLTextAreaElement>(null)
  const noteRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    // Land focus on the card (not a button) so Space and the number keys act on it, and bring its top into view.
    cardRef.current?.focus({ preventScroll: true })
    const card = cardRef.current
    if (card) {
      const box = card.getBoundingClientRect()
      if (box.top < 0 || box.top > window.innerHeight * 0.6) card.scrollIntoView({ block: 'start', behavior: 'smooth' })
    }
  }, [])

  const openOther = useCallback(() => {
    setOtherOpen(true)
    setNoteOpen(false)
    window.setTimeout(() => {
      // WHY center: the shell's two choosers cover the bottom ~90px, so "nearest" would park the box under them.
      otherRef.current?.focus({ preventScroll: true })
      otherRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }, 0)
  }, [])

  const pick = useCallback(
    (option: NeedsOption) => {
      if (option.key === 'other') {
        openOther()
        return
      }
      setOtherOpen(false)
      cardRef.current?.focus({ preventScroll: true })
      onChoose(entry, option.key)
    },
    [entry, onChoose, openOther],
  )

  // Live shortcuts. WHY capture phase + preventDefault: the dashboard binds 1/2/3 to its A · B · C layouts on window;
  // on this page the numbers mean "choose option n", and the dashboard's handler honours defaultPrevented.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
      const card = cardRef.current
      if (!card || !card.isConnected) return
      const target = event.target
      const inside = target instanceof Node && card.closest('.vt-needs')?.contains(target)
      const onBody = target === document.body || target === document.documentElement
      if (!inside && !onBody) return
      if (isEditable(target)) {
        if (event.key === 'Escape') (target as HTMLElement).blur()
        return
      }
      if (event.shiftKey) return
      const key = event.key.toLowerCase()
      const index = ['1', '2', '3'].indexOf(key)
      if (index >= 0 && item.options[index]) {
        event.preventDefault()
        pick(item.options[index])
      } else if (key === 'o') {
        event.preventDefault()
        openOther()
      } else if (key === 's') {
        event.preventDefault()
        onSkip(entry)
      } else if (key === 'j') {
        event.preventDefault()
        onStep(1)
      } else if (key === 'k') {
        event.preventDefault()
        onStep(-1)
      } else if (key === ' ' && !(target instanceof HTMLElement && target.closest('button, summary, a'))) {
        event.preventDefault()
        setContextOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [entry, item.options, onSkip, onStep, openOther, pick])

  const blocks = blocksText(item)
  const opened = item.created.ts ? formatTs(item.created.ts) : null
  const openedAt = item.created.iteration != null ? `${doc.iteration?.unit ?? 'wave'} ${item.created.iteration}` : null
  const latest = item.updates.length ? item.updates[item.updates.length - 1] : null
  const otherText = choice === 'other' ? (draft?.note ?? '') : ''
  // The backend splits the "Filed at …" sentence off as provenance_md but leaves it at the head of context_base_md;
  // show it once (as provenance), never twice. Only an exact verbatim prefix is removed.
  const base = item.provenance_md && item.context_base_md.startsWith(item.provenance_md) ? item.context_base_md.slice(item.provenance_md.length).trimStart() : item.context_base_md

  return (
    <article ref={cardRef} className={`n4-card${choice ? ' n4-card-answered' : ''}`} tabIndex={-1} aria-label={`${item.local_id} ${item.title}`} data-testid="n4-card" data-item={item.id}>
      <p className="n4-meta vt-small">
        <span className="vt-num vt-strong">{item.local_id}</span>
        {multiTrack ? <span> · {doc.track_title}</span> : null}
        <span className={item.blocking_now ? 'vt-tone-warn' : 'vt-muted'}> · {GROUP_LABEL[item.group]}</span>
        {blocks ? <span className="vt-muted"> · blocks {blocks}</span> : null}
        {skipped && !choice ? (
          <span className="vt-faint">
            {' '}
            · skipped for now{' '}
            <button type="button" className="vt-btn n4-link" onClick={onUnskip}>
              un-skip
            </button>
          </span>
        ) : null}
      </p>
      <h2 className="n4-question">
        <Md text={item.ask} />
      </h2>
      {item.context_lead_md ? (
        <p className="n4-why">
          <span className="n4-why-label">Why it's asked</span>
          <Md text={item.context_lead_md} />
        </p>
      ) : null}

      <div className="n4-options" role="group" aria-label="Your answer">
        {item.options.map((option, index) => {
          const selected = option.key === 'other' ? choice === 'other' || otherOpen : choice === option.key
          return (
            <button
              key={option.key}
              type="button"
              className={`vt-btn n4-option n4-option-${option.key}`}
              aria-pressed={selected}
              onClick={() => pick(option)}
              data-testid={`n4-option-${option.key}`}
            >
              <span className="n4-key" aria-hidden>
                {index + 1}
              </span>
              <span className="n4-option-body">
                <span className="n4-option-label">
                  {option.key === 'other' ? 'Something else…' : option.label}
                  {option.recommended ? <span className="n4-tag n4-tag-rec">Recommended</span> : null}
                  {option.is_default ? <span className="n4-tag">{item.default.applies.unit === 'never' ? 'No default' : item.default.state === 'in_effect' ? 'Default · in effect' : `Default · after ${item.default.applies.unit} ${item.default.applies.after}`}</span> : null}
                  {selected && option.key !== 'other' ? <span className="n4-chosen">✓ your answer</span> : null}
                </span>
                {option.detail_md ? <Md className="n4-option-detail" text={option.detail_md} /> : option.key === 'other' ? <span className="n4-option-detail vt-faint">Write your own answer; it goes out as your words.</span> : null}
                {option.is_default ? <span className="n4-option-when">{defaultWhen(doc, item)}</span> : null}
              </span>
            </button>
          )
        })}
      </div>

      {otherOpen || choice === 'other' ? (
        <div className="n4-other">
          <textarea
            ref={otherRef}
            className="n4-textarea"
            rows={3}
            placeholder="Your answer, in your words. Enter saves and moves on; Shift+Enter for a new line."
            value={otherText}
            onChange={(event) => {
              const value = event.target.value
              answers.set(doc.track, item.local_id, { choice: value.trim() ? 'other' : null, note: value })
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && otherText.trim()) {
                event.preventDefault()
                onUnskip()
                onAdvance()
              }
            }}
            data-testid="n4-other-text"
          />
          <div className="n4-other-row vt-small">
            <button type="button" className="vt-btn n4-primary" disabled={!otherText.trim()} onClick={() => (onUnskip(), onAdvance())} data-testid="n4-other-save">
              Save and next ↵
            </button>
            <button
              type="button"
              className="vt-btn n4-link"
              onClick={() => {
                setOtherOpen(false)
                if (choice === 'other') answers.set(doc.track, item.local_id, { choice: null, note: '' })
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : choice ? (
        noteOpen ? (
          <textarea
            ref={noteRef}
            className="n4-textarea n4-note"
            rows={2}
            placeholder="A note to go with your answer (optional)"
            value={draft?.note ?? ''}
            onChange={(event) => answers.set(doc.track, item.local_id, { note: event.target.value })}
            data-testid="n4-note"
          />
        ) : (
          <p className="vt-small n4-after">
            <button
              type="button"
              className="vt-btn n4-link"
              onClick={() => {
                setNoteOpen(true)
                window.setTimeout(() => noteRef.current?.focus(), 0)
              }}
            >
              Add a note
            </button>
            <span className="vt-faint"> · </span>
            <button type="button" className="vt-btn n4-link" onClick={() => answers.set(doc.track, item.local_id, { choice: null, note: '' })}>
              Clear answer
            </button>
          </p>
        )
      ) : null}

      <details className="n4-context" open={contextOpen} onToggle={(event) => setContextOpen(event.currentTarget.open)} data-testid="n4-context">
        <summary>
          <span className="n4-context-title">Full context</span>
          <span className="vt-faint">
            {' '}
            · {item.context_md.length.toLocaleString()} characters
            {item.updates.length ? ` · ${item.updates.length} update${item.updates.length === 1 ? '' : 's'}, latest ${latest?.header}` : ''}
            {item.evidence.length ? ` · ${item.evidence.length} evidence` : ''}
          </span>
        </summary>
        <div className="n4-context-body">
          {item.provenance_md ? <p className="vt-small vt-faint"><Md text={item.provenance_md} /></p> : null}
          {item.updates.length ? (
            <div className="n4-updates">
              {[...item.updates].reverse().map((update, index) => (
                <div key={index} className="n4-update">
                  <p className="n4-section-label">
                    Update · {update.header}
                    {index === 0 ? ' · latest' : ''}
                  </p>
                  <p>
                    <Md text={update.text_md} />
                  </p>
                </div>
              ))}
              <p className="n4-section-label">The original question</p>
            </div>
          ) : null}
          {base ? (
            <p>
              <Md text={base} />
            </p>
          ) : (
            <p className="vt-faint">The loop recorded no question text beyond the title.</p>
          )}
          <p className="n4-section-label">Recommendation</p>
          <p>
            <Md text={item.recommendation_md} />
          </p>
          <p className="n4-section-label">Default</p>
          <p>
            <Md text={item.default.text_md} />
            <br />
            <span className="vt-faint vt-small">{defaultWhen(doc, item)}</span>
          </p>
          {item.evidence.length ? (
            <>
              <p className="n4-section-label">Evidence</p>
              <ul className="n4-evidence">
                {item.evidence.map((_, index) => (
                  <li key={index}>
                    <EvidenceLink backend={backend} doc={doc} item={item} index={index} projection={projection} />
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          <p className="vt-small vt-faint n4-provenance">
            {openedAt || opened ? `Opened ${[openedAt, opened].filter(Boolean).join(', ')}` : 'Opening time not recorded'}
            {item.updated.ts && item.updated.ts !== item.created.ts ? ` · updated ${formatTs(item.updated.ts)}` : ''}
            {` · loop status "${item.raw_status}" · ${item.kind}`}
            {` · answers go by ${doc.answer_channel.kind.replace('_', ' ')}${doc.answer_channel.target ? ` to ${doc.answer_channel.target}` : ''}`}
          </p>
        </div>
      </details>

      <footer className="n4-foot vt-small">
        <span>
          <button type="button" className="vt-btn n4-link" onClick={() => onStep(-1)} data-testid="n4-prev">
            ← Previous
          </button>
          <span className="vt-faint"> · </span>
          <button type="button" className="vt-btn n4-link" onClick={() => onSkip(entry)} data-testid="n4-skip">
            Skip for now
          </button>
          <span className="vt-faint"> · </span>
          <button type="button" className="vt-btn n4-link" onClick={() => onStep(1)} data-testid="n4-next">
            Next →
          </button>
        </span>
        <span className="vt-faint n4-keys">
          <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> choose · <kbd>O</kbd> something else · <kbd>S</kbd> skip · <kbd>J</kbd> <kbd>K</kbd> next, previous · <kbd>Space</kbd> context
        </span>
      </footer>
    </article>
  )
}

// ---- the pending review: every drafted answer in queue order, one line each; a line jumps back to its card.
function AnswerTray({ entries, answers, onPick, currentKey }: { entries: Entry[]; answers: NeedsProposalProps['answers']; onPick(key: string): void; currentKey: string | null }) {
  const rows = entries
    .map((entry) => ({ entry, draft: answers.get(entry.doc.track, entry.item.local_id) }))
    .filter(({ draft }) => effectiveChoice(draft))
  return (
    <div className="n4-tray-list">
      <p className="n4-section-label">Your answers{rows.length ? ` · ${rows.length}` : ''}</p>
      {rows.length ? (
        <ul>
          {rows.map(({ entry, draft }) => {
            const choice = effectiveChoice(draft) as Choice
            return (
              <li key={entry.key}>
                <button type="button" className="vt-btn n4-tray-row" aria-current={entry.key === currentKey ? 'true' : undefined} onClick={() => onPick(entry.key)}>
                  <span className="vt-num vt-strong">{entry.item.local_id}</span>{' '}
                  <span>{choice === 'other' ? 'Something else' : choiceLabel(entry.item, choice)}</span>
                  {draft?.note.trim() ? <span className="vt-muted">: {draft.note.trim()}</span> : null}
                  {!isComplete(draft) ? <span className="vt-tone-warn"> · needs a note</span> : null}
                </button>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="vt-small vt-faint">Nothing answered yet. Answers stay here as a draft until you copy them out; nothing is sent.</p>
      )}
    </div>
  )
}

// ---- the end of the queue
function DoneCard({
  docs,
  answers,
  needs,
  optional,
  answeredCount,
  skippedCount,
  answered,
  skipped,
  onPick,
}: NeedsProposalProps & {
  needs: Entry[]
  optional: Entry[]
  answeredCount: number
  skippedCount: number
  answered(entry: Entry): boolean
  skipped: Set<string>
  onPick(key: string): void
}) {
  const remaining = needs.filter((entry) => !answered(entry) && !skipped.has(entry.key))
  const skippedEntries = needs.filter((entry) => !answered(entry) && skipped.has(entry.key))
  const optionalOpen = optional.filter((entry) => !answered(entry))
  return (
    <article className="n4-card n4-done" data-testid="n4-done">
      <p className="n4-meta vt-small vt-muted">End of the queue</p>
      <h2 className="n4-question">
        {needs.length ? `${answeredCount} of ${needs.length} answered` : 'Nothing is waiting on you'}
        {skippedCount ? `, ${skippedCount} skipped` : ''}
        {remaining.length ? `, ${remaining.length} not looked at` : ''}
      </h2>
      <p className="n4-why">Copy your answers and paste them where the loop reads them. Nothing has been sent; these are drafts in this browser.</p>
      <CopyOut docs={docs} answers={answers} className="n4-done-copy" />
      <AnswerTray entries={[...needs, ...optional]} answers={answers} onPick={onPick} currentKey={null} />
      {skippedEntries.length || remaining.length ? (
        <p className="vt-small n4-after">
          {[...remaining, ...skippedEntries].map((entry, index) => (
            <span key={entry.key}>
              {index ? <span className="vt-faint"> · </span> : null}
              <button type="button" className="vt-btn n4-link" onClick={() => onPick(entry.key)}>
                Back to {entry.item.local_id}
                {skipped.has(entry.key) ? ' (skipped)' : ''}
              </button>
            </span>
          ))}
        </p>
      ) : null}
      {optionalOpen.length ? (
        <p className="vt-small n4-after">
          <button type="button" className="vt-btn n4-link" onClick={() => onPick(optionalOpen[0].key)}>
            Review the {optionalOpen.length} defaulting without you →
          </button>
          <span className="vt-faint"> Their defaults already apply; answer one only to override it.</span>
        </p>
      ) : null}
    </article>
  )
}

// ---- honest empty state: a track with no structured questions shows where its questions actually live.
function EmptyTracks({ docs, lone }: { docs: NeedsDoc[]; lone: boolean }) {
  return (
    <section className="n4-empty" data-testid="n4-empty">
      {lone ? <h2 className="vt-h2">Nothing here needs you</h2> : <p className="n4-section-label">Tracks with no structured questions</p>}
      {docs.map((doc) => (
        <div key={doc.track} className="n4-empty-track">
          {!lone || docs.length > 1 ? <p className="vt-strong">{doc.track_title}</p> : null}
          <p>
            {doc.items.length
              ? `All ${doc.items.length} of its questions are answered or closed.`
              : 'This loop keeps no needs-you file, so there is nothing to answer here.'}
          </p>
          {doc.source.note ? <p className="vt-small vt-muted">{doc.source.note}</p> : null}
          <p className="vt-small vt-muted">
            An answer would reach it by {doc.answer_channel.kind.replace('_', ' ')}
            {doc.answer_channel.target ? `: ${doc.answer_channel.target}` : ''}
            {doc.answer_channel.read_back ? `; read back ${doc.answer_channel.read_back}` : ''}.
          </p>
          {doc.source.paths.length ? (
            <ul className="n4-paths vt-small vt-faint">
              {doc.source.paths.map((path) => (
                <li key={path}>
                  <code>{path}</code>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
    </section>
  )
}

// ---- what the loop already settled, folded: proof the count is honest, never in the way.
function Decided({ decided }: { decided: { doc: NeedsDoc; item: NeedsItem }[] }) {
  const multi = new Set(decided.map(({ doc }) => doc.track)).size > 1
  return (
    <details className="n4-decided">
      <summary className="vt-small vt-muted">Already settled in the loop · {decided.length}</summary>
      <ul className="vt-small">
        {decided.map(({ doc, item }) => (
          <li key={item.id}>
            <span className="vt-num vt-strong">{item.local_id}</span> {item.title}{' '}
            <span className="vt-faint">
              · {GROUP_LABEL[item.group].toLowerCase()}
              {item.answer?.note ? ` · "${item.answer.note}"${item.answer.quoted ? '' : ' (integrator paraphrase)'}` : item.answer?.choice ? ` · ${choiceLabel(item, item.answer.choice)}` : ''}
              {item.answer && item.answer.by === null ? ' · closed by the loop without your words' : ''}
              {multi ? ` · ${doc.track_title}` : ''}
            </span>
          </li>
        ))}
      </ul>
    </details>
  )
}
