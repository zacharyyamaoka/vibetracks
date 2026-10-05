// Level 3: the evidence behind a point. Each item is one quiet row (kind · title · status), its metrics in one grey
// line, and its media as small buttons that open in place (video plays, report renders, audit text shows).
// WHY in place and not a modal: the reader keeps the chart and the row they came from in view (progressive
// disclosure, one deliberate click deeper), and Back still closes it when the variant routes `item`.

import { useLayoutEffect, useRef, useState } from 'react'
import type { EvidenceItem, MediaRef, Tone } from './model'
import { formatNumber } from './model'
import { MediaView } from './MediaView'
import { StatusWord } from './StatusWord'
import { formatLocal } from './time'

export interface EvidenceListProps {
  items: EvidenceItem[]
  /** Media id -> URL (shared/api.ts mediaUrl bound to the backend). */
  mediaUrl: (id: string) => string
  /** Controlled: the media id open right now (route it to keep place); uncontrolled when absent. */
  openMedia?: string | null
  onOpenMedia?: (mediaId: string | null, item: EvidenceItem) => void
  /** Highlight one item (e.g. the routed `item`). */
  selectedItem?: string | null
  onSelectItem?: (item: EvidenceItem) => void
  /** What to say when there is no item (missing data is an explicit state). */
  empty?: string
  className?: string
}

const KIND_LABEL: Record<string, string> = {
  run: 'run',
  lane: 'lane',
  audit: 'audit',
  gate: 'gate',
  report: 'report',
  video: 'video',
  note: 'note',
}

/** Grey for the normal outcomes; colour only for the exceptions a reader should notice. */
export function evidenceStatusTone(status: string | null): Tone {
  if (!status) return 'muted'
  const s = status.toLowerCase()
  if (['failed', 'parked', 'aborted', 'below gate', 'above gate', 'skipped'].includes(s)) return 'warn'
  if (s.startsWith('unsound')) return 'warn'
  return 'muted'
}

/** A stored text shown whole or folded at `lines` lines, with an explicit "Show all (N characters)" / "Show less".
 * WHY a fold and never a cut: the build sends the complete stored value (audit 2026-10-04 #10: a 642-character
 * intervention arrived as 600 with "…" and nothing exposed the rest), so the page keeps a glance-sized block and the
 * whole value is one click away. WHY pre-wrap: the authored line breaks and spaces are part of the value (truthful
 * rendering); `anywhere` wraps a long path instead of widening the page. The toggle appears only when the text really
 * overflows the fold, measured, so a short note carries no control that does nothing. */
export function FoldText({ text, lines = 6, className, testId }: { text: string; lines?: number; className?: string; testId?: string }) {
  const box = useRef<HTMLParagraphElement>(null)
  const [open, setOpen] = useState(false)
  const [overflows, setOverflows] = useState(false)
  useLayoutEffect(() => {
    const element = box.current
    if (!element || open) return
    // Measured while folded: the clamp hides lines, so scrollHeight > clientHeight means there is more to show.
    const measure = () => setOverflows(element.scrollHeight > element.clientHeight + 1)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [text, open, lines])
  const characters = Array.from(text).length
  return (
    <div className={`vt-fold ${className ?? ''}`} data-testid={testId} data-open={open ? 'true' : 'false'}>
      <p ref={box} className={`vt-fold-text${open ? '' : ' vt-fold-closed'}`} style={open ? undefined : { WebkitLineClamp: lines }}>
        {text}
      </p>
      {overflows || open ? (
        <button type="button" className="vt-btn vt-fold-toggle" aria-expanded={open} data-testid="vt-fold-toggle" onClick={() => setOpen(!open)}>
          {open ? 'Show less' : `Show all (${characters.toLocaleString()} characters)`}
        </button>
      ) : null}
    </div>
  )
}

function metricText(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'number') return formatNumber(value)
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    return entries.length ? entries.map(([k, v]) => `${k} ${typeof v === 'number' ? formatNumber(v) : String(v)}`).join(' · ') : null
  }
  return String(value)
}

export function EvidenceList({ items, mediaUrl, openMedia, onOpenMedia, selectedItem, onSelectItem, empty, className }: EvidenceListProps) {
  const [localOpen, setLocalOpen] = useState<string | null>(null)
  const controlled = openMedia !== undefined
  const open = controlled ? openMedia : localOpen
  const setOpen = (id: string | null, item: EvidenceItem) => {
    if (!controlled) setLocalOpen(id)
    onOpenMedia?.(id, item)
  }

  if (items.length === 0) {
    return <p className={`vt-faint ${className ?? ''}`}>{empty ?? 'No evidence recorded for this point.'}</p>
  }
  return (
    <ul className={`vt-evidence ${className ?? ''}`} data-testid="vt-evidence-list">
      {items.map((item) => {
        const metrics = Object.entries(item.metrics)
          .map(([key, value]) => [key, metricText(value)] as const)
          .filter(([, text]) => text !== null)
        const openHere: MediaRef | undefined = item.media.find((media) => media.id === open)
        return (
          <li
            key={item.id}
            data-testid="vt-evidence-item"
            data-item-id={item.id}
            data-kind={item.kind}
            aria-current={selectedItem === item.id ? 'true' : undefined}
            style={selectedItem === item.id ? { background: 'var(--vt-hover)' } : undefined}
          >
            <div className="vt-ev-head">
              <span className="vt-ev-kind">{KIND_LABEL[item.kind] ?? item.kind}</span>
              {onSelectItem ? (
                <button type="button" className="vt-btn vt-ev-title" onClick={() => onSelectItem(item)}>
                  {item.title}
                </button>
              ) : (
                <span className="vt-ev-title">{item.title}</span>
              )}
              {item.status ? <StatusWord word={item.status} tone={evidenceStatusTone(item.status)} bare className="vt-small" /> : null}
              {item.when ? <span className="vt-faint vt-small vt-num" title={formatLocal(item.when, { year: true })}>{formatLocal(item.when)}</span> : null}
            </div>
            {metrics.length ? (
              <div className="vt-ev-metrics">
                {metrics.map(([key, text]) => (
                  <span key={key}>
                    {key} <b>{text}</b>
                  </span>
                ))}
              </div>
            ) : null}
            {item.note ? <FoldText key={item.note} text={item.note} className="vt-ev-note" testId="vt-ev-note" /> : null}
            {item.media.length ? (
              <div className="vt-ev-media">
                {item.media.map((media) => (
                  <button
                    key={media.id}
                    type="button"
                    className="vt-chip-btn"
                    aria-pressed={open === media.id}
                    data-testid="vt-media-button"
                    data-media-id={media.id}
                    onClick={() => setOpen(open === media.id ? null : media.id, item)}
                  >
                    {media.kind === 'video' ? '▶ ' : ''}
                    {media.label}
                  </button>
                ))}
              </div>
            ) : null}
            {openHere ? <MediaView media={openHere} url={mediaUrl(openHere.id)} onClose={() => setOpen(null, item)} /> : null}
          </li>
        )
      })}
    </ul>
  )
}
