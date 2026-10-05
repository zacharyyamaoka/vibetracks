// L3 · one evidence item: a run's metrics and its video (real and sim side by side when both exist), a report in a
// frame, an audit write-up as text. And the way back to the change: "This feeds" lists the KPI points this item stands
// behind, each a click to that iteration with the KPI highlighted (provenance runs both ways).

import { useRef } from 'react'
import type { EvidenceItem, Kpi, MediaRef, Projection, Track } from '../../shared'
import {
  Breadcrumb,
  MediaView,
  N1_WORD,
  Sparkline,
  StatusWord,
  evidenceStatusTone,
  formatKpiValue,
  formatNumber,
  iterationById,
  trackById,
  valueDomain,
} from '../../shared'
import type { Nav } from './nav'
import { formatLocal } from '../../shared/time'

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

export function ItemPage({ projection, track, item, title, nav, mediaUrl }: {
  projection: Projection
  track: Track
  item: EvidenceItem
  title: string
  nav: Nav
  mediaUrl: (id: string) => string
}) {
  const route = nav.route
  const parent = track.parent ? trackById(projection, track.parent) : null
  const iteration = iterationById(track, item.iteration)
  const metrics = Object.entries(item.metrics)
    .map(([key, value]) => [key, metricText(value)] as const)
    .filter(([, text]) => text !== null)
  const missing = Object.entries(item.metrics).filter(([, value]) => value === null).map(([key]) => key)
  const videos = item.media.filter((media) => media.kind === 'video')
  const real = videos.find((media) => /^real\b/i.test(media.label))
  const sim = videos.find((media) => /^sim\b/i.test(media.label))
  const pair = real && sim ? [real, sim] : null
  const otherVideos = videos.filter((media) => !pair?.includes(media))
  const documents = item.media.filter((media) => media.kind !== 'video')
  const openDoc: MediaRef | null = documents.find((media) => media.id === route.media) ?? (documents.length === 1 && videos.length === 0 ? documents[0] : null)
  const feeds = track.kpis
    .map((kpi) => ({ kpi, value: kpi.values.find((v) => v.evidence.includes(item.id)) ?? null }))
    .filter((entry): entry is { kpi: Kpi; value: NonNullable<typeof entry.value> } => entry.value !== null)

  return (
    <div className="vt-page vt-a-page" data-testid="vt-a-item" data-item={item.id}>
      <Breadcrumb
        items={[
          { label: title, onClick: nav.tracks },
          ...(parent ? [{ label: parent.title, onClick: () => nav.track(parent.id) }] : []),
          { label: track.title, onClick: () => nav.track(track.id) },
          ...(iteration ? [{ label: iteration.label, onClick: () => nav.iteration(track.id, iteration.id, { kpi: route.kpi }) }] : []),
          { label: item.title },
        ]}
      />
      <h1 className="vt-h1 vt-a-h1-item">{item.title}</h1>
      <p className="vt-sub">
        {item.kind}
        {item.status ? (
          <>
            {' · '}
            <StatusWord word={item.status} tone={evidenceStatusTone(item.status)} bare />
          </>
        ) : null}
        {/* WHY the raw stamp as a title: the line shows local time to the minute; the stored value (seconds, source zone) stays one hover away. */}
        {item.when ? <span title={formatLocal(item.when, { year: true })}>{` · ${formatLocal(item.when)}`}</span> : ''}
        {iteration ? ` · ${iteration.label}` : ''}
      </p>

      {item.kind === 'run' ? (
        <p className="vt-a-nline vt-small">
          <span className="vt-muted">One run (n = 1): a change it shows on its own is {N1_WORD}.</span>
        </p>
      ) : null}

      {metrics.length ? (
        <dl className="vt-a-props vt-a-metrics" data-testid="vt-a-metrics">
          {metrics.map(([key, text]) => (
            <div key={key} className="vt-a-prop">
              <dt>{key}</dt>
              <dd className="vt-num">{text}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {missing.length ? <p className="vt-small vt-faint">Not recorded for this item: {missing.join(' · ')}</p> : null}
      {item.note ? <p className="vt-a-note">{item.note}</p> : null}

      {pair ? <VideoPair pair={pair} mediaUrl={mediaUrl} /> : null}
      {otherVideos.map((media) => (
        <section key={media.id} className="vt-a-section">
          <MediaView media={media} url={mediaUrl(media.id)} />
        </section>
      ))}
      {documents.length ? (
        <section className="vt-a-section">
          <div className="vt-a-docbar" hidden={documents.length === 1 && videos.length === 0}>
            {documents.map((media) => (
              <button
                key={media.id}
                type="button"
                className="vt-chip-btn"
                aria-pressed={openDoc?.id === media.id}
                data-testid="vt-a-doc"
                onClick={() => nav.go({ ...route, media: openDoc?.id === media.id ? undefined : media.id }, 'replace')}
              >
                {media.label}
              </button>
            ))}
          </div>
          {openDoc ? (
            <div className="vt-a-doc">
              <MediaView media={openDoc} url={mediaUrl(openDoc.id)} onClose={documents.length > 1 || videos.length ? () => nav.go({ ...route, media: undefined }, 'replace') : undefined} />
            </div>
          ) : null}
        </section>
      ) : null}
      {item.media.length === 0 ? <p className="vt-small vt-faint vt-a-section">No media recorded for this item.</p> : null}

      {item.links.length ? (
        <p className="vt-small vt-a-section">
          {item.links.map((link) => (
            <span key={link.label} className="vt-muted">
              {link.label}{' '}
              {link.kind === 'media' && link.media ? (
                <a href={mediaUrl(link.media)} target="_blank" rel="noreferrer">
                  open
                </a>
              ) : (
                <code className="vt-a-code">{link.value}</code>
              )}
            </span>
          ))}
        </p>
      ) : null}

      <section className="vt-a-section" data-testid="vt-a-feeds">
        <h2 className="vt-h3">This feeds</h2>
        {feeds.length === 0 ? (
          <p className="vt-small vt-faint">No KPI point names this item as its evidence; it is context for {iteration?.label ?? 'its iteration'}.</p>
        ) : (
          <table className="vt-table vt-a-feeds">
            <tbody>
              {feeds.map(({ kpi, value }) => {
                const at = iterationById(track, value.iteration)
                return (
                  <tr key={kpi.id} className="vt-row-link" onClick={() => nav.iteration(track.id, value.iteration, { kpi: kpi.id })}>
                    <td>
                      <button type="button" className="vt-btn vt-a-kpilabel" onClick={(event) => { event.stopPropagation(); nav.iteration(track.id, value.iteration, { kpi: kpi.id }) }}>
                        {kpi.label}
                      </button>
                    </td>
                    <td className="vt-num vt-strong">{formatKpiValue(kpi, value)}</td>
                    <td className="vt-small vt-faint">at {at?.label ?? value.iteration}{value.n !== null ? ` · n ${value.n}` : ''}</td>
                    <td>
                      <Sparkline
                        values={kpi.values.map((v) => (v.measured ? v.value : null))}
                        selected={kpi.values.findIndex((v) => v.iteration === value.iteration)}
                        domain={valueDomain(kpi)}
                        width={96}
                        ariaLabel={`${kpi.label} across ${track.iteration.unit}s`}
                      />
                    </td>
                    <td>
                      <StatusWord status={kpi.status} className="vt-small" />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

/** Real and sim side by side on one action (research: level 3 is a synced multi-panel viewer). "Play both" restarts
 * both clips together; each keeps its native controls. WHY loop only short clips: a 1-second step response is
 * unreadable played once, but an 85 MB bench recording must not loop on its own. */
function VideoPair({ pair, mediaUrl }: { pair: MediaRef[]; mediaUrl: (id: string) => string }) {
  const refs = useRef<Array<HTMLVideoElement | null>>([])
  const playBoth = () => {
    for (const video of refs.current) {
      if (!video) continue
      video.currentTime = 0
      void video.play().catch(() => undefined)
    }
  }
  return (
    <section className="vt-a-section" data-testid="vt-a-pair">
      <p className="vt-a-pairbar vt-small">
        <button type="button" className="vt-chip-btn" onClick={playBoth} data-testid="vt-a-play-both">
          ▶ Play both
        </button>
        <span className="vt-faint">real and sim of this run, restarted together</span>
      </p>
      <div className="vt-a-pair">
        {pair.map((media, index) => (
          <figure key={media.id}>
            <figcaption className="vt-small">
              <span className="vt-strong">{media.label}</span>
              {' · '}
              <a href={mediaUrl(media.id)} target="_blank" rel="noreferrer">
                open in new tab
              </a>
            </figcaption>
            <video
              ref={(element) => {
                refs.current[index] = element
              }}
              src={mediaUrl(media.id)}
              controls
              preload="metadata"
              playsInline
              muted
              aria-label={media.label}
              data-testid="vt-video"
              onLoadedMetadata={(event) => {
                event.currentTarget.loop = event.currentTarget.duration < 10
              }}
            />
          </figure>
        ))}
      </div>
    </section>
  )
}
