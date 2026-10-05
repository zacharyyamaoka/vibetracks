// Level 3 of Variant B: the bottom drawer for one iteration. Its marker and provenance, its evidence (the items behind
// the clicked point first), and the selected item inline: a run's metrics with its real and sim video side by side,
// a wave report in a frame, an audit write-up as text.
//
// WHY a drawer under the wall and not a new page: the wall stays in view above it with the cursor parked on the same
// column, so the reader sees the evidence AND every KPI's value at that iteration at once (Grafana's annotation panel,
// Rerun's selection panel). Esc or × closes it; Back climbs one step (item → iteration → wall).

import { useEffect, useMemo, useState } from 'react'
import type { EvidenceItem, Kpi, MediaRef, Projection, Track } from '../../shared'
import {
  MediaView,
  StatusWord,
  VideoPlayer,
  deltaVsPrevious,
  evidenceAt,
  evidenceForValue,
  evidenceStatusTone,
  formatDay,
  formatKpiValue,
  formatNumber,
  iterationById,
  kpisBySlot,
  toneClass,
  valueAt,
} from '../../shared'
import { columnIndexOfIteration, type Column } from './columns'
import { nWords, splitDelta } from './Wall'
import { formatLocal } from '../../shared/time'

export interface DrawerProps {
  projection: Projection
  track: Track
  columns: Column[]
  iterationId: string
  itemId: string | null
  kpiId: string | null
  /** An L3 file view asked for by the roadmap widget (onOpenEvidence). */
  file: { path: string; line?: number } | null
  /** A rung the roadmap widget asked for that has no judged run (onOpenRung's fallback). */
  rung: string | null
  mediaUrl: (id: string) => string
  showDeltas: boolean
  onClose: () => void
  onIteration: (iterationId: string) => void
  onItem: (itemId: string) => void
  onKpi: (kpiId: string | null) => void
}

const KIND_ORDER = ['run', 'report', 'video', 'gate', 'lane', 'audit', 'note']
const KIND_NAME: Record<string, string> = { run: 'Runs', report: 'Reports', video: 'Videos', gate: 'Gates', lane: 'Lanes', audit: 'Audits', note: 'Notes' }

export function Drawer(props: DrawerProps) {
  const { track, columns, iterationId, itemId, kpiId, file, rung, onClose, onIteration, onItem, onKpi } = props
  const iteration = iterationById(track, iterationId)
  const index = track.iterations.findIndex((it) => it.id === iterationId)
  const previous = index > 0 ? track.iterations[index - 1] : null
  const next = index >= 0 && index < track.iterations.length - 1 ? track.iterations[index + 1] : null
  const items = evidenceAt(track, iterationId)
  const kpi = kpiId ? track.kpis.find((candidate) => candidate.id === kpiId) ?? null : null
  const behind = kpi ? evidenceForValue(track, kpi, iterationId) : []
  const item = itemId ? items.find((candidate) => candidate.id === itemId) ?? null : null
  const column = columns[columnIndexOfIteration(columns, iterationId)]
  const groups = useMemo(() => {
    const byKind = new Map<string, EvidenceItem[]>()
    for (const evidence of items) byKind.set(evidence.kind, [...(byKind.get(evidence.kind) ?? []), evidence])
    return [...byKind.entries()].sort((a, b) => kindRank(a[0]) - kindRank(b[0]))
  }, [items])

  if (!iteration) {
    return (
      <section className="vt-b-drawer" data-testid="vt-b-drawer">
        <header className="vt-b-dhead">
          <p className="vt-muted">No iteration “{iterationId}” in {track.title}.</p>
          <button type="button" className="vt-btn vt-b-x" aria-label="Close (Esc)" onClick={onClose}>
            ×
          </button>
        </header>
      </section>
    )
  }

  const unit = track.iteration.unit
  return (
    <section className="vt-b-drawer" role="region" aria-label={`Evidence for ${iteration.label}`} data-testid="vt-b-drawer" data-iteration={iteration.id}>
      <header className="vt-b-dhead">
        <div className="vt-b-dtitle">
          <span className="vt-h3">{iteration.label}</span>
          <span className="vt-faint vt-small">{iteration.date ? formatDay(iteration.date) : 'no date recorded'}</span>
          {column && column.iterations.length > 1 ? (
            <span className="vt-faint vt-small">
              {unit} {column.iterations.findIndex((it) => it.id === iteration.id) + 1} of {column.iterations.length} on {column.label}
            </span>
          ) : null}
          <span className="vt-b-dmarker" title={iteration.marker}>
            {iteration.marker}
          </span>
        </div>
        <nav className="vt-b-dnav">
          <button type="button" className="vt-btn vt-b-navbtn" disabled={!previous} onClick={() => previous && onIteration(previous.id)} data-testid="vt-b-prev" title="Previous (←)">
            ‹ {previous ? previous.label : ''}
          </button>
          <button type="button" className="vt-btn vt-b-navbtn" disabled={!next} onClick={() => next && onIteration(next.id)} data-testid="vt-b-next" title="Next (→)">
            {next ? next.label : ''} ›
          </button>
          <button type="button" className="vt-btn vt-b-x" aria-label="Close (Esc)" title="Close (Esc)" onClick={onClose} data-testid="vt-b-close">
            ×
          </button>
        </nav>
      </header>
      <div className="vt-b-dbody">
        <div className="vt-b-dlist" data-testid="vt-b-dlist">
          {rung ? <p className="vt-b-notice">No judged run is recorded for rung {rung}; showing {iteration.label}, its latest {unit}.</p> : null}
          {kpi ? (
            <div className="vt-b-dgroup">
              <div className="vt-b-dgh">
                <span>
                  Behind <b>{kpi.label}</b> at {iteration.label} · <span className="vt-num">{formatKpiValue(kpi, valueAt(kpi, iterationId))}</span>
                </span>
                <button type="button" className="vt-btn vt-b-link" onClick={() => onKpi(null)}>
                  clear
                </button>
              </div>
              {behind.length ? (
                behind.map((evidence) => <ItemRow key={`k-${evidence.id}`} item={evidence} selected={evidence.id === itemId} onSelect={onItem} />)
              ) : (
                <p className="vt-faint vt-small vt-b-empty">{valueAt(kpi, iterationId)?.note ?? 'No evidence item is linked to this point.'}</p>
              )}
            </div>
          ) : null}
          {groups.length === 0 ? <p className="vt-faint vt-b-empty">No evidence recorded at {iteration.label}.</p> : null}
          {groups.map(([kind, list]) => (
            <div key={kind} className="vt-b-dgroup">
              <div className="vt-b-dgh">
                <span>{KIND_NAME[kind] ?? kind}</span>
                <span className="vt-faint vt-num">{list.length}</span>
              </div>
              {list.map((evidence) => (
                <ItemRow key={evidence.id} item={evidence} selected={evidence.id === itemId} onSelect={onItem} />
              ))}
            </div>
          ))}
        </div>
        <div className="vt-b-ddetail" data-testid="vt-b-detail">
          {file ? (
            <FileView projection={props.projection} file={file} mediaUrl={props.mediaUrl} />
          ) : item ? (
            <ItemDetail key={item.id} track={track} item={item} iterationId={iterationId} mediaUrl={props.mediaUrl} onKpi={onKpi} />
          ) : (
            <IterationSummary track={track} iterationId={iterationId} showDeltas={props.showDeltas} items={items} onItem={onItem} onKpi={onKpi} />
          )}
        </div>
      </div>
    </section>
  )
}

function kindRank(kind: string): number {
  const at = KIND_ORDER.indexOf(kind)
  return at < 0 ? KIND_ORDER.length : at
}

function ItemRow({ item, selected, onSelect }: { item: EvidenceItem; selected: boolean; onSelect: (id: string) => void }) {
  const videos = item.media.filter((media) => media.kind === 'video').length
  const summary = Object.entries(item.metrics)
    .filter(([, value]) => typeof value === 'number' || typeof value === 'string')
    .slice(0, 2)
    .map(([key, value]) => `${key} ${typeof value === 'number' ? formatNumber(value) : value}`)
  if (videos) summary.push(videos === 1 ? '▶ video' : `▶ ${videos} videos`)
  return (
    <button
      type="button"
      className={`vt-btn vt-b-ev${selected ? ' is-selected' : ''}`}
      aria-current={selected ? 'true' : undefined}
      onClick={() => onSelect(item.id)}
      data-testid="vt-b-ev"
      data-item-id={item.id}
    >
      <span className="vt-b-ev-title">{item.title}</span>
      {item.status ? <StatusWord word={item.status} tone={evidenceStatusTone(item.status)} bare className="vt-small" /> : <span />}
      {summary.length ? <small className="vt-b-ev-sub">{summary.join(' · ')}</small> : null}
    </button>
  )
}

/** The iteration with nothing selected yet: what changed, where the numbers come from, and every KPI there. */
function IterationSummary({ track, iterationId, showDeltas, items, onItem, onKpi }: { track: Track; iterationId: string; showDeltas: boolean; items: EvidenceItem[]; onItem: (id: string) => void; onKpi: (id: string) => void }) {
  const iteration = iterationById(track, iterationId)
  if (!iteration) return null
  const report = items.find((evidence) => evidence.kind === 'report')
  const provenance = iteration.provenance
  return (
    <div className="vt-b-summary">
      <h3 className="vt-h3">What changed at {iteration.label}</h3>
      <p className="vt-b-changed">{iteration.marker}</p>
      {report ? (
        <p style={{ marginTop: 8 }}>
          <button type="button" className="vt-chip-btn" onClick={() => onItem(report.id)} data-testid="vt-b-open-report">
            Open {report.title}
          </button>
        </p>
      ) : null}
      <p className="vt-b-prov">
        <span>from</span> <code>{provenance.pointer}</code>
        {provenance.source ? (
          <>
            {' '}
            <span>of</span> <code>{provenance.source}</code>
          </>
        ) : null}
        {provenance.derived ? <span> · {provenance.derived}</span> : null}
      </p>
      <h3 className="vt-h3" style={{ marginTop: 18 }}>
        Every KPI at {iteration.label}
      </h3>
      <table className="vt-b-kpis">
        <tbody>
          {kpisBySlot(track).flatMap((group) =>
            group.kpis.map((kpi) => <KpiLine key={kpi.id} kpi={kpi} iterationId={iterationId} showDeltas={showDeltas} onKpi={onKpi} />),
          )}
        </tbody>
      </table>
    </div>
  )
}

function KpiLine({ kpi, iterationId, showDeltas, onKpi }: { kpi: Kpi; iterationId: string; showDeltas: boolean; onKpi: (id: string) => void }) {
  const value = valueAt(kpi, iterationId)
  const measured = Boolean(value?.measured && value.value !== null)
  const delta = measured && showDeltas ? deltaVsPrevious(kpi, value) : null
  const split = delta ? splitDelta(kpi, delta) : null
  return (
    <tr>
      <td>
        <button type="button" className="vt-btn vt-b-link" onClick={() => onKpi(kpi.id)} title="Show the evidence behind this point">
          {kpi.label}
        </button>
      </td>
      <td className={`vt-num${measured ? '' : ' vt-faint'}`} title={value?.note ?? undefined}>
        {measured ? formatKpiValue(kpi, value) : 'not measured'}
      </td>
      <td className="vt-small">
        {split ? (
          <>
            <span className={toneClass(split.tone)}>{split.text}</span>
            {split.flag ? <span className="vt-tone-warn"> · {split.flag}</span> : null}
          </>
        ) : measured && value?.n !== null && value?.n !== undefined ? (
          <span className="vt-faint">{nWords(value.n)}</span>
        ) : null}
      </td>
    </tr>
  )
}

/** One evidence item: its metrics, the KPI points it stands behind, and its media inline. */
function ItemDetail({ track, item, iterationId, mediaUrl, onKpi }: { track: Track; item: EvidenceItem; iterationId: string; mediaUrl: (id: string) => string; onKpi: (id: string) => void }) {
  const videos = item.media.filter((media) => media.kind === 'video')
  const others = item.media.filter((media) => media.kind !== 'video')
  const [open, setOpen] = useState<string | null>(others[0]?.id ?? null)
  useEffect(() => setOpen(others[0]?.id ?? null), [item.id])
  const opened: MediaRef | undefined = others.find((media) => media.id === open)
  const metrics = Object.entries(item.metrics).filter(([, value]) => value !== null && value !== undefined && value !== '')
  const supports = track.kpis
    .map((kpi) => ({ kpi, value: valueAt(kpi, iterationId) }))
    .filter(({ value }) => value?.evidence.includes(item.id))
  const [copied, setCopied] = useState<string | null>(null)

  return (
    <div className="vt-b-item" data-testid="vt-b-item" data-item-id={item.id}>
      <h3 className="vt-h3">{item.title}</h3>
      <p className="vt-b-itemmeta">
        <span>{item.kind}</span>
        {item.status ? <StatusWord word={item.status} tone={evidenceStatusTone(item.status)} bare /> : null}
        {item.when ? <span className="vt-num" title={formatLocal(item.when, { year: true })}>{formatLocal(item.when)}</span> : null}
      </p>
      {videos.length ? (
        <div className={`vt-b-videos${videos.length > 1 ? ' is-pair' : ''}`}>
          {videos.map((media) => (
            <figure key={media.id} data-testid="vt-b-video" data-media-id={media.id}>
              <figcaption>
                {media.label}
                <a href={mediaUrl(media.id)} target="_blank" rel="noreferrer">
                  Open in new tab
                </a>
              </figcaption>
              <VideoPlayer src={mediaUrl(media.id)} label={media.label} />
            </figure>
          ))}
        </div>
      ) : null}
      {metrics.length ? (
        <dl className="vt-b-metrics">
          {metrics.map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd className="vt-num">{metricText(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {item.note ? <p className="vt-b-itemnote">{item.note}</p> : null}
      {supports.length ? (
        <div className="vt-b-supports">
          <span className="vt-label">Counts toward</span>
          {supports.map(({ kpi, value }) => (
            <button key={kpi.id} type="button" className="vt-btn vt-b-support" onClick={() => onKpi(kpi.id)} title="Show every item behind this point">
              {kpi.label} · <span className="vt-num">{formatKpiValue(kpi, value)}</span>
              {value?.n !== null && value?.n !== undefined ? <span className="vt-faint"> · {nWords(value.n)}</span> : null}
            </button>
          ))}
        </div>
      ) : null}
      {others.length ? (
        <div className="vt-b-others">
          {others.length > 1 ? (
            <div className="vt-b-chips">
              {others.map((media) => (
                <button key={media.id} type="button" className="vt-chip-btn" aria-pressed={open === media.id} onClick={() => setOpen(open === media.id ? null : media.id)} data-testid="vt-media-button">
                  {media.label}
                </button>
              ))}
            </div>
          ) : null}
          {opened ? <MediaView media={opened} url={mediaUrl(opened.id)} onClose={others.length > 1 ? () => setOpen(null) : undefined} /> : null}
        </div>
      ) : null}
      {item.links.length ? (
        <ul className="vt-b-links">
          {item.links.map((link, i) => (
            <li key={i}>
              <span className="vt-label">{link.label}</span>{' '}
              {link.kind === 'media' && link.media ? (
                <a href={mediaUrl(link.media)} target="_blank" rel="noreferrer">
                  open
                </a>
              ) : (
                <>
                  <code>{link.value}</code>{' '}
                  <button
                    type="button"
                    className="vt-btn vt-b-link"
                    onClick={() => {
                      void navigator.clipboard?.writeText(link.value ?? '').then(() => setCopied(link.value ?? null), () => setCopied(null))
                    }}
                  >
                    {copied === link.value ? 'copied' : 'copy'}
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      {!videos.length && !others.length && !metrics.length && !item.note ? <p className="vt-faint">This item carries no metrics or media.</p> : null}
    </div>
  )
}

function metricText(value: unknown): string {
  if (typeof value === 'number') return formatNumber(value)
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (value && typeof value === 'object') return Object.entries(value as Record<string, number>).map(([k, v]) => `${k} ${formatNumber(v)}`).join(' · ')
  return String(value)
}

/** The roadmap widget's file reference: opened in place when the file is in the media allowlist, else said plainly. */
function FileView({ projection, file, mediaUrl }: { projection: Projection; file: { path: string; line?: number }; mediaUrl: (id: string) => string }) {
  const media = Object.values(projection.media).find((entry) => entry.path === file.path)
  return (
    <div className="vt-b-item">
      <h3 className="vt-h3">File</h3>
      <p className="vt-b-prov">
        <code>
          {file.path}
          {file.line ? `:${file.line}` : ''}
        </code>
      </p>
      {media ? (
        <MediaView media={media} url={mediaUrl(media.id)} />
      ) : (
        <p className="vt-faint" style={{ marginTop: 8 }}>
          This file is not in the dashboard's media allowlist, so it cannot be shown here.
        </p>
      )}
    </div>
  )
}
