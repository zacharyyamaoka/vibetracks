// Level 3: the evidence behind a point. Each item is one quiet row (kind · title · status), its metrics in one grey
// line, and its media as small buttons that open in place (video plays, report renders, audit text shows).
// WHY in place and not a modal: the reader keeps the chart and the row they came from in view (progressive
// disclosure, one deliberate click deeper), and Back still closes it when the variant routes `item`.

import { useState } from 'react'
import type { EvidenceItem, MediaRef, Tone } from './model'
import { formatNumber } from './model'
import { MediaView } from './MediaView'
import { StatusWord } from './StatusWord'

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
              {item.when ? <span className="vt-faint vt-small vt-num">{item.when.replace('T', ' ').slice(0, 16)}</span> : null}
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
            {item.note ? <p className="vt-ev-note">{item.note}</p> : null}
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
