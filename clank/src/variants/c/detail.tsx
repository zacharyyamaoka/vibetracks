// Pane 3 of Variant C: the selected KPI as one object (number, change against its named baseline, target, status),
// its large SeriesChart on the track's shared x-axis, and — once a point is picked — that point's evidence (L3), with
// a run's metrics and real/sim video in place.

import { useEffect, useRef, useState } from 'react'
import type { EvidenceItem, Iteration, Kpi, MediaEntry, MediaRef, Track } from '../../shared'
import {
  EvidenceList,
  MediaView,
  N1_WORD,
  SLOT_NAMES,
  SeriesChart,
  StatusWord,
  VideoPlayer,
  deltaTone,
  deltaVsPrevious,
  describeDelta,
  evidenceAt,
  evidenceForValue,
  evidenceStatusTone,
  formatDay,
  formatKpiValue,
  formatN,
  formatNumber,
  formatTargetLabel,
  formatValue,
  latestValue,
  measuredValues,
  targetState,
  toneClass,
  valueAt,
} from '../../shared'
import type { TrackView } from './columns'
import { headline, headlineDelta } from './read'
import { formatLocal } from '../../shared/time'

export type Zone = 'tracks' | 'kpis' | 'chart' | 'evidence'

/** The evidence of one point: the items behind the KPI's value at that column (the provenance click), then the rest
 * of that column's items. */
export function evidenceLists(track: Track, kpi: Kpi, members: Iteration[]): { behind: EvidenceItem[]; rest: EvidenceItem[] } {
  const behind: EvidenceItem[] = []
  const seen = new Set<string>()
  for (const member of members) {
    for (const item of evidenceForValue(track, kpi, member.id)) {
      if (!seen.has(item.id)) {
        seen.add(item.id)
        behind.push(item)
      }
    }
  }
  const rest = members.flatMap((member) => evidenceAt(track, member.id)).filter((item) => !seen.has(item.id))
  return { behind, rest }
}

/** The column a KPI's L3 opens on by default: its newest measured column, else the newest column. */
export function defaultColumn(view: TrackView, kpi: Kpi): string | null {
  return latestValue(view.kpi(kpi))?.iteration ?? view.columns[view.columns.length - 1]?.id ?? null
}

export interface DetailPaneProps {
  track: Track
  view: TrackView
  kpi: Kpi
  columnId: string | null
  item: EvidenceItem | null
  /** The raw routed item when it is not an evidence id: `rung:<id>` with nothing behind it. */
  missingItem: string | null
  file: { path: string; line?: number } | null
  media: Record<string, MediaEntry>
  mediaUrl: (id: string) => string
  showDeltas: boolean
  zone: Zone
  cursor: string | null
  restOpen: boolean
  onToggleRest: () => void
  onSelectColumn: (columnId: string) => void
  onOpenItem: (item: EvidenceItem) => void
  onUp: () => void
}

export function DetailPane(props: DetailPaneProps) {
  const { track, view, kpi, columnId, item, showDeltas, onSelectColumn } = props
  const viewKpi = view.kpi(kpi)
  const head = headline(track, kpi)
  const delta = headlineDelta(kpi, head)
  const never = measuredValues(kpi).length === 0
  const where = targetState(kpi, head.value)
  const column = view.columns.find((it) => it.id === columnId) ?? null
  const latestCol = latestValue(viewKpi)?.iteration ?? null
  const strip = view.columns.length <= 8

  return (
    <div data-testid="vt-c-detail" data-kpi={kpi.id}>
      <p className="vt-label">
        {kpi.slot} · {SLOT_NAMES[kpi.slot]}
      </p>
      <h2 className="vt-h2">{kpi.label}</h2>
      <div className="vt-c-hero">
        <span className={`vt-c-big vt-num${head.value ? '' : ' vt-gap'}`} data-testid="vt-c-headline">
          {head.text}
        </span>
        <span className="vt-c-hero-side">
          <span className="vt-muted vt-small">{head.label}</span>
          {showDeltas && delta ? (
            <span className={`vt-small ${toneClass(deltaTone(delta))}`} data-testid="vt-c-headline-delta">
              {describeDelta(kpi, delta)}
            </span>
          ) : null}
        </span>
      </div>
      <p className="vt-c-context vt-small">
        <span className="vt-muted">
          {formatTargetLabel(kpi)}
          {where ? ` · ${where}` : ''}
          {kpi.baseline ? ` · baseline ${kpi.baseline.label}${kpi.baseline.value !== null ? ` = ${formatValue(kpi.baseline.value, kpi.unit)}` : ''}` : ' · no baseline pinned'}
        </span>
        <StatusWord status={kpi.status} />
      </p>
      {kpi.note ? <p className="vt-faint vt-small vt-c-note">{kpi.note}</p> : null}

      {never ? (
        <div className="vt-c-missing" data-testid="vt-c-missing">
          <p className="vt-strong">Not measured at any {track.iteration.unit} yet</p>
          <p className="vt-muted vt-small">
            {kpi.values.find((value) => value.note)?.note ?? `No ${track.iteration.unit} carries a reading for this KPI.`}
          </p>
          {head.aggregate ? (
            <p className="vt-muted vt-small">
              Only a day-level figure exists: {head.text} ({head.label}). There is no per-{track.iteration.unit} point to open.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="vt-c-chart">
          <SeriesChart
            kpi={viewKpi}
            iterations={view.columns}
            selected={columnId}
            onSelectIteration={onSelectColumn}
            height={item ? 136 : 196}
            leftMargin={56}
          />
          {strip ? (
            <div className="vt-c-strip" style={{ paddingLeft: 56, paddingRight: 14 }} data-testid="vt-c-strip">
              {view.columns.map((col) => {
                const value = valueAt(viewKpi, col.id)
                const measured = Boolean(value?.measured)
                return (
                  <button
                    key={col.id}
                    type="button"
                    className={`vt-btn vt-c-cell${col.id === columnId ? ' vt-c-cell-sel' : ''}${col.id === latestCol ? ' vt-c-cell-latest' : ''}`}
                    title={`${col.label}: ${col.marker}${value?.note ? ` · ${value.note}` : ''}`}
                    onClick={() => onSelectColumn(col.id)}
                  >
                    <span className={measured ? 'vt-num' : 'vt-gap'}>{measured ? formatKpiValue(kpi, value) : '—'}</span>
                    <small className="vt-faint">{measured ? (value?.n !== null && value?.n !== undefined ? `n ${value.n}` : ' ') : 'no reading'}</small>
                  </button>
                )
              })}
            </div>
          ) : null}
        </div>
      )}

      {column ? (
        <PointEvidence {...props} column={column} />
      ) : never ? null : (
        <p className="vt-c-hint vt-small">
          <button type="button" className="vt-btn vt-c-link" data-testid="vt-c-open-latest" onClick={() => latestCol && onSelectColumn(latestCol)}>
            Open the evidence of {view.columns.find((it) => it.id === latestCol)?.label ?? 'the latest point'} →
          </button>
          <span className="vt-faint"> or click any point. Every point links to what changed there.</span>
        </p>
      )}
    </div>
  )
}

function PointEvidence(props: DetailPaneProps & { column: Iteration }) {
  const { track, view, kpi, column, item, missingItem, file, showDeltas, zone, cursor, restOpen, onToggleRest, onOpenItem, onUp, mediaUrl, media } = props
  const members = view.members[column.id] ?? [column]
  const viewKpi = view.kpi(kpi)
  const value = valueAt(viewKpi, column.id)
  const change = value?.measured ? deltaVsPrevious(viewKpi, value) : null
  const lists = evidenceLists(track, kpi, members)
  const section = useRef<HTMLElement>(null)
  useEffect(() => {
    const element = section.current
    if ((!item && !missingItem && !file) || !element) return
    const pane = element.closest('.vt-c-pane') as HTMLElement | null
    const reveal = () => element.scrollIntoView({ block: 'start', behavior: 'instant' as ScrollBehavior })
    reveal()
    // WHY keep re-revealing for a moment: on a pasted link Clank re-opens the file and the dock re-mounts the panel
    // about a second after the first render, which resets every pane's scroll to the top and would leave the opened
    // run below the fold. Any wheel, pointer or key input from the reader ends it at once.
    let userMoved = false
    const stop = () => {
      userMoved = true
    }
    pane?.addEventListener('wheel', stop, { passive: true })
    pane?.addEventListener('pointerdown', stop)
    window.addEventListener('keydown', stop)
    const poll = window.setInterval(() => {
      if (!userMoved && pane && element.isConnected && pane.scrollTop < 8 && element.offsetTop > pane.clientHeight / 2) reveal()
    }, 150)
    const end = window.setTimeout(() => window.clearInterval(poll), 3500)
    return () => {
      window.clearInterval(poll)
      window.clearTimeout(end)
      pane?.removeEventListener('wheel', stop)
      pane?.removeEventListener('pointerdown', stop)
      window.removeEventListener('keydown', stop)
    }
  }, [item?.id, missingItem, file?.path]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section ref={section} className={`vt-c-l3${zone === 'evidence' ? ' vt-c-zone-active' : ''}`} data-testid="vt-c-l3" data-column={column.id}>
      <h3 className="vt-h3">
        {column.label} <span className="vt-faint vt-small">{formatDay(column.date)}</span>
      </h3>
      {members.length === 1 ? (
        <p className="vt-muted vt-small vt-c-marker">{members[0].marker}</p>
      ) : (
        <ul className="vt-c-markers vt-small">
          {members.map((member) => (
            <li key={member.id}>
              <span className="vt-strong">{member.label}</span> <span className="vt-muted">{member.marker}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="vt-small vt-c-point">
        <span className="vt-faint">{kpi.label} here </span>
        <span className="vt-strong vt-num">{value?.measured ? formatKpiValue(kpi, value) : 'not measured'}</span>
        {value?.measured && formatN(value) ? <span className="vt-muted"> · {formatN(value)}</span> : null}
        {value?.measured && value.spread !== null ? <span className="vt-muted"> · spread {formatValue(value.spread, kpi.unit)}</span> : null}
        {showDeltas && change ? <span className={toneClass(deltaTone(change))}> · {describeDelta(kpi, change)}</span> : null}
        {value?.note ? <span className="vt-faint"> · {value.note}</span> : null}
      </p>

      {file ? (
        <FileView file={file} media={media} mediaUrl={mediaUrl} onUp={onUp} />
      ) : missingItem ? (
        <div className="vt-c-run">
          <button type="button" className="vt-btn vt-c-link vt-small" onClick={onUp}>
            ← {column.label} evidence
          </button>
          <p className="vt-muted" style={{ marginTop: 8 }}>
            No evidence item in this projection names {missingItem.replace(/^rung:/, 'rung ')}: no judged run, lane or rung note carries it.
          </p>
        </div>
      ) : item ? (
        <RunDetail
          item={item}
          kpi={kpi}
          column={column}
          value={lists.behind.some((candidate) => candidate.id === item.id) ? value : null}
          siblings={[...lists.behind, ...lists.rest]}
          mediaUrl={mediaUrl}
          onOpenItem={onOpenItem}
          onUp={onUp}
        />
      ) : (
        <>
          <p className="vt-label vt-c-list-label">
            Behind this point · {lists.behind.length}
          </p>
          <EvidenceList
            items={lists.behind}
            mediaUrl={mediaUrl}
            selectedItem={zone === 'evidence' ? cursor : null}
            onSelectItem={onOpenItem}
            empty={`No evidence item is linked to ${kpi.label} at ${column.label}${value?.note ? ` (${value.note})` : ''}.`}
          />
          {lists.rest.length ? (
            <>
              <button type="button" className="vt-btn vt-c-disclosure vt-c-rest" aria-expanded={restOpen} data-testid="vt-c-rest-toggle" onClick={onToggleRest}>
                <span className="vt-c-caret" aria-hidden="true">{restOpen ? '▾' : '▸'}</span>
                Everything else in {column.label} · {lists.rest.length}
              </button>
              {restOpen ? (
                <EvidenceList items={lists.rest} mediaUrl={mediaUrl} selectedItem={zone === 'evidence' ? cursor : null} onSelectItem={onOpenItem} />
              ) : null}
            </>
          ) : null}
        </>
      )}
    </section>
  )
}

// ------------------------------------------------------------------------------------------------ run detail

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

/** One evidence item opened: what it is, which KPI point it stands behind, its metrics, its videos side by side
 * (real first), then any report or audit write-up. WHY a real/sim pair side by side: the sim–real gap is the rig's
 * whole question, and the eye compares two videos best when they sit next to each other. */
function RunDetail({
  item,
  kpi,
  column,
  value,
  siblings,
  mediaUrl,
  onOpenItem,
  onUp,
}: {
  item: EvidenceItem
  kpi: Kpi
  column: Iteration
  value: ReturnType<typeof valueAt>
  siblings: EvidenceItem[]
  mediaUrl: (id: string) => string
  onOpenItem: (item: EvidenceItem) => void
  onUp: () => void
}) {
  const index = siblings.findIndex((candidate) => candidate.id === item.id)
  const previous = index > 0 ? siblings[index - 1] : null
  const next = index >= 0 && index < siblings.length - 1 ? siblings[index + 1] : null
  const metrics = Object.entries(item.metrics)
    .map(([key, raw]) => [key, metricText(raw)] as const)
    .filter(([, text]) => text !== null)
  const videos = item.media.filter((media) => media.kind === 'video')
  const ordered = [...videos.filter((media) => /^real/i.test(media.label)), ...videos.filter((media) => !/^real/i.test(media.label))]
  const linkMedia: MediaRef[] = item.links
    .filter((link) => link.kind === 'media' && link.media)
    .map((link) => ({ id: link.media as string, kind: 'html', label: link.label }))
  const documents = [...item.media.filter((media) => media.kind !== 'video'), ...linkMedia.filter((media) => !item.media.some((m) => m.id === media.id))]
  const [docOpen, setDocOpen] = useState<string | null>(documents[0]?.id ?? null)
  useEffect(() => setDocOpen(documents[0]?.id ?? null), [item.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const openDoc = documents.find((media) => media.id === docOpen) ?? null
  const thin = value?.n !== null && value?.n !== undefined && value.n <= 1

  return (
    <div className="vt-c-run" data-testid="vt-c-run-detail" data-item-id={item.id}>
      <div className="vt-c-run-nav vt-small">
        <button type="button" className="vt-btn vt-c-link" data-testid="vt-c-run-up" onClick={onUp}>
          ← {column.label} evidence
        </button>
        {index >= 0 ? (
          <span className="vt-faint vt-num">
            {index + 1} of {siblings.length}
          </span>
        ) : null}
        {previous ? (
          <button type="button" className="vt-btn vt-c-link" title={previous.title} onClick={() => onOpenItem(previous)}>
            ‹ previous
          </button>
        ) : null}
        {next ? (
          <button type="button" className="vt-btn vt-c-link" title={next.title} onClick={() => onOpenItem(next)}>
            next ›
          </button>
        ) : null}
      </div>
      <p className="vt-label" style={{ marginTop: 14 }}>
        {item.kind}
      </p>
      <h3 className="vt-h2 vt-c-run-title">
        {item.title}
        {item.status ? <StatusWord word={item.status} tone={evidenceStatusTone(item.status)} className="vt-small" /> : null}
      </h3>
      <p className="vt-faint vt-small vt-num" title={item.when ?? undefined}>{item.when ? formatLocal(item.when) : 'no timestamp recorded'}</p>
      {value ? (
        <p className="vt-small vt-muted" style={{ marginTop: 6 }}>
          Behind {kpi.label} at {column.label}: <span className="vt-strong vt-num">{formatKpiValue(kpi, value)}</span>
          {formatN(value) ? ` · ${formatN(value)}` : ''}
          {thin ? <span className="vt-tone-warn"> · {N1_WORD}</span> : null}
        </p>
      ) : null}

      {metrics.length ? (
        <dl className="vt-c-metrics vt-num">
          {metrics.map(([key, text]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="vt-faint vt-small" style={{ marginTop: 10 }}>No metrics recorded for this {item.kind}.</p>
      )}
      {item.note ? <p className="vt-muted vt-small" style={{ marginTop: 8 }}>{item.note}</p> : null}

      {ordered.length ? (
        <div className="vt-c-videos" data-testid="vt-c-videos">
          {ordered.map((media) => (
            <figure key={media.id} data-media-id={media.id}>
              <figcaption className="vt-small">
                <span>{media.label}</span>
                <a href={mediaUrl(media.id)} target="_blank" rel="noreferrer" className="vt-faint">
                  Open in new tab
                </a>
              </figcaption>
              <VideoPlayer src={mediaUrl(media.id)} label={media.label} />
            </figure>
          ))}
        </div>
      ) : item.kind === 'run' ? (
        <p className="vt-faint vt-small" style={{ marginTop: 10 }}>No video was recorded for this run.</p>
      ) : null}

      {documents.length ? (
        <div className="vt-c-docs">
          {documents.length > 1 ? (
            <div className="vt-ev-media" style={{ margin: '0 0 4px' }}>
              {documents.map((media) => (
                <button key={media.id} type="button" className="vt-chip-btn" aria-pressed={media.id === docOpen} onClick={() => setDocOpen(media.id === docOpen ? null : media.id)}>
                  {media.label}
                </button>
              ))}
            </div>
          ) : null}
          {openDoc ? <MediaView media={openDoc} url={mediaUrl(openDoc.id)} onClose={documents.length > 1 ? () => setDocOpen(null) : undefined} /> : null}
        </div>
      ) : null}

      {item.links.some((link) => link.kind !== 'media') ? (
        <ul className="vt-c-links vt-small">
          {item.links
            .filter((link) => link.kind !== 'media')
            .map((link) => (
              <li key={`${link.label}-${link.value}`}>
                <span className="vt-faint">{link.label}</span> <code className="vt-mono">{link.value}</code>
              </li>
            ))}
        </ul>
      ) : null}
    </div>
  )
}

/** The roadmap's "open evidence" target (a file and line). The backend serves only allowlisted media, so a path in
 * the allowlist opens in place and any other path is shown as text to copy, with the reason. */
function FileView({ file, media, mediaUrl, onUp }: { file: { path: string; line?: number }; media: Record<string, MediaEntry>; mediaUrl: (id: string) => string; onUp: () => void }) {
  const entry = Object.values(media).find((candidate) => candidate.path === file.path) ?? null
  return (
    <div className="vt-c-run" data-testid="vt-c-file">
      <button type="button" className="vt-btn vt-c-link vt-small" onClick={onUp}>
        ← back
      </button>
      <p className="vt-label" style={{ marginTop: 14 }}>
        file
      </p>
      <p className="vt-mono" style={{ wordBreak: 'break-all' }}>
        {file.path}
        {file.line ? `:${file.line}` : ''}
      </p>
      {entry ? (
        <MediaView media={entry} url={mediaUrl(entry.id)} />
      ) : (
        <p className="vt-muted vt-small" style={{ marginTop: 8 }}>
          This file is not in the projection's media allowlist, so the dashboard cannot open it. Copy the path above.
        </p>
      )}
    </div>
  )
}

