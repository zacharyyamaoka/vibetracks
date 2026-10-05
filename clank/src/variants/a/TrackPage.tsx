// L2 · the Track page, in Zach's order (2026-10-04: "when I first click in, I want to see next, the key KPIs we are
// tracking (you already have a nice row format here) and then also the roadmap for what is next and what is the current
// rung"):
//   (a) the name (double-click to rename), one line of state, and "Needs you · N blocking · M open →";
//   (b) the key KPI rows: the scorecard, latest column emphasised;
//   (c) the Roadmap, a first-class section: calm by default (current rung, next), "Expand" shows the full board in place;
//   (d) the rig's deployments as a quiet sub-list, each opening its own page.
// Every track (loop or deployment) renders through this one template: "solve the display once".

import { useLayoutEffect, useRef, useState } from 'react'
import type { PluginBackend } from '@clank/api'
import type { Projection, Route, Track } from '../../shared'
import { Breadcrumb, StatusWord, childrenOf, formatKpiValue, formatValue, latestValue, northStar, trackById, valueAt } from '../../shared'
import { RoadmapWidget, type RoadmapSettings, type RoadmapWidgetState } from '../../roadmap'
import { evidenceOwningMedia, formatSince, unitWord } from './columns'
import { isReporting, lastMoved, needsCount, purposeOf, registryOf, sourceKind } from './live'
import { openRung, type Nav } from './nav'
import { TrackMenu, TrackName, type Renamer } from './rename'
import { useRegisteredRoadmap } from './roadmapReload'
import { Scorecard } from './Scorecard'
import { ProgressCell } from './TracksPage'

export function TrackPage({ projection, track, title, nav, xAxis, showDeltas, backend, roadmapSettings, renamer }: {
  projection: Projection
  track: Track
  title: string
  nav: Nav
  xAxis: 'iteration' | 'day'
  showDeltas: boolean
  backend: PluginBackend
  roadmapSettings: RoadmapSettings
  renamer: Renamer
}) {
  const route = nav.route
  const parent = track.parent ? trackById(projection, track.parent) : null
  const children = childrenOf(projection, track.id)
  const moved = lastMoved(projection, track)
  const purpose = purposeOf(track)
  return (
    <div className="vt-page vt-a-page" data-testid="vt-a-l2" data-track={track.id}>
      <Breadcrumb
        items={[
          { label: title, onClick: nav.tracks },
          ...(parent ? [{ label: renamer.titleOf(parent), onClick: () => nav.track(parent.id) }] : []),
          { label: renamer.titleOf(track) },
        ]}
      />

      {/* (a) name, state, needs */}
      <h1 className="vt-h1 vt-a-titleline" data-testid="vt-a-title">
        <TrackName track={track} renamer={renamer} />
        <TrackMenu track={track} renamer={renamer} />
      </h1>
      <p className="vt-a-stateline" data-testid="vt-a-stateline">
        <StatusWord status={track.state} />
        {track.state.detail ? <span className="vt-faint"> · {track.state.detail}</span> : null}
        {track.state.since ? <span className="vt-faint"> · since {formatSince(track.state.since)}</span> : null}
        <span className="vt-faint"> · last moved </span>
        <span className={moved.stale ? 'vt-tone-stale' : 'vt-faint'} title={moved.detail ?? undefined}>
          {moved.text}
          {moved.stale ? ' (stale)' : ''}
        </span>
      </p>
      <NeedsLine track={track} nav={nav} />
      {purpose ? (
        <Purpose key={track.id} text={purpose} source={registryOf(track)?.note_path ?? null} />
      ) : isReporting(track) && track.summary ? (
        <Purpose key={track.id} text={track.summary} source={null} />
      ) : null}

      {/* (b) the key KPI rows */}
      <section className="vt-a-section" data-testid="vt-a-kpis">
        <h2 className="vt-h3">
          Key KPIs{' '}
          {track.kpis.length ? (
            <span className="vt-a-h-note">
              {track.kpis.length} KPIs × {track.iterations.length} {unitWord(track, track.iterations.length)}
              {xAxis === 'day' ? ' grouped by day' : ''} · latest emphasised · a cell or column opens its evidence
            </span>
          ) : null}
        </h2>
        {track.kpis.length ? (
          <>
            <p className="vt-a-northstar vt-small">
              <span className="vt-faint">North star </span>
              <NorthStarLine track={track} />
            </p>
            <Scorecard
              track={track}
              xAxis={xAxis}
              showDeltas={showDeltas}
              selectedKpi={route.kpi ?? null}
              onOpenColumn={(column) => nav.iteration(track.id, column.opens)}
              onOpenCell={(kpi, column) => nav.iteration(track.id, column.opens, { kpi: kpi.id })}
            />
          </>
        ) : (
          <p className="vt-faint vt-small" data-testid="vt-a-no-kpis">
            No KPIs reported yet{isReporting(track) ? '' : ` · ${track.state.detail ?? 'not reporting'}`}.
          </p>
        )}
      </section>

      {/* (c) the roadmap: a loop's, never a deployment's (a deployment is evidence inside its loop's roadmap) */}
      {track.parent === null ? <RoadmapSection track={track} nav={nav} backend={backend} settings={roadmapSettings} /> : null}

      {/* (d) deployments */}
      {children.length ? (
        <section className="vt-a-section" data-testid="vt-a-deployments">
          <h2 className="vt-h3">
            Deployments <span className="vt-a-h-note">evidence for this track</span>
          </h2>
          <table className="vt-table vt-a-deploys" aria-label="Deployments">
            <colgroup>
              <col style={{ width: '30%' }} />
              <col style={{ width: '28%' }} />
              <col style={{ width: '26%' }} />
              <col style={{ width: '16%' }} />
            </colgroup>
            <tbody>
              {children.map((child) => {
                const childMoved = lastMoved(projection, child)
                return (
                  <tr key={child.id} className="vt-row-link" data-testid="vt-a-deploy-row" data-track={child.id} onClick={() => nav.track(child.id)}>
                    <td>
                      <button type="button" className="vt-btn vt-a-deploy-name" onClick={(event) => { event.stopPropagation(); nav.track(child.id) }}>
                        {child.title}
                      </button>
                    </td>
                    <td>
                      <StatusWord status={child.state} detail={child.state.detail} />
                    </td>
                    <td>
                      <ProgressCell track={child} showDeltas={showDeltas} />
                    </td>
                    <td>
                      <span className="vt-a-two" title={childMoved.detail ?? undefined}>
                        <span className={childMoved.stale ? 'vt-tone-stale' : undefined}>{childMoved.text}</span>
                        <small>{sourceKind(child) === 'snapshot' ? 'from a snapshot' : child.iteration.label}</small>
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      ) : null}

      {track.links.length ? (
        <p className="vt-a-links vt-small">
          <span className="vt-faint">Links</span>
          {track.links.map((link) => {
            const owner = link.kind === 'media' && link.media ? evidenceOwningMedia(track, link.media) : null
            if (owner && link.media) {
              return (
                <button
                  key={link.label}
                  type="button"
                  className="vt-btn vt-a-link"
                  data-testid="vt-a-report-link"
                  onClick={() => nav.item(track.id, owner.item, { media: link.media })}
                >
                  {link.label}
                </button>
              )
            }
            return (
              <span key={link.label} className="vt-muted" title={link.value}>
                {link.label} <code className="vt-a-code">{link.value}</code>
              </span>
            )
          })}
        </p>
      ) : null}
    </div>
  )
}

/** The track's purpose (the note's whole first paragraph), clamped to three lines with an explicit "more" that opens it
 * in place and "less" that closes it. No toggle when it fits.
 * WHY a clamp and not a cut: the build now sends the whole paragraph; the page stays a glance (state, needs, KPIs above
 * the fold) and the rest of the paragraph is one click away, never dropped. */
function Purpose({ text, source }: { text: string; source: string | null }) {
  const box = useRef<HTMLParagraphElement>(null)
  const [open, setOpen] = useState(false)
  const [overflows, setOverflows] = useState(false)
  useLayoutEffect(() => {
    const element = box.current
    if (!element || open) return
    // Measured while clamped: the clamp hides lines, so scrollHeight > clientHeight means there is more to show.
    const measure = () => setOverflows(element.scrollHeight > element.clientHeight + 1)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [text, open])
  return (
    <div className="vt-a-purposebox" data-testid="vt-a-purpose">
      <p ref={box} className={`vt-sub vt-a-purpose${open ? '' : ' vt-a-clamp-3'}`} title={source ? `from ${source}` : undefined}>
        {text}
      </p>
      {overflows || open ? (
        <button type="button" className="vt-btn vt-a-link vt-a-more" aria-expanded={open} data-testid="vt-a-purpose-toggle" onClick={() => setOpen(!open)}>
          {open ? 'less' : 'more'}
        </button>
      ) : null}
    </div>
  )
}

/** "Needs you · 2 blocking · 5 open →", opening the track's Needs-you page (#vt?track=<id>&needs=1). */
function NeedsLine({ track, nav }: { track: Track; nav: Nav }) {
  const count = needsCount(track)
  const words =
    count.open === null
      ? 'not reported'
      : count.open === 0
        ? 'nothing open'
        : `${count.blocking ?? 0} blocking · ${count.open} open`
  return (
    <p className="vt-a-needsline">
      <button type="button" className="vt-btn vt-a-needs-go" data-testid="vt-a-needs-line" onClick={() => nav.go({ track: track.id, needs: '1' })}>
        <span>Needs you</span>
        <span className="vt-faint"> · </span>
        <span className={count.blocking ? 'vt-tone-warn' : 'vt-faint'}>{words}</span>
        <span className="vt-a-arrow" aria-hidden="true"> →</span>
      </button>
    </p>
  )
}

// WHY star.label verbatim, never lower-cased: lower-casing turned detection's "test mIoU (E3)" into "test miou (e3)"
// and CAN 16's "(RMS)" into "(rms)" — authored labels keep every character (truthful rendering, 2026-10-04 check).
function NorthStarLine({ track }: { track: Track }) {
  const star = northStar(track)
  if (!star) return <span className="vt-faint">none declared</span>
  const latest = latestValue(star)
  const aggregate = star.aggregate && star.aggregate.value !== null ? star.aggregate : null
  if (aggregate) {
    return (
      <span>
        <b className="vt-num">{formatValue(aggregate.value, star.unit)}</b> {star.label}
        <span className="vt-faint">
          {' '}· {aggregate.label}
          {aggregate.n !== null ? ` · n ${aggregate.n}` : ''} · last session {formatKpiValue(star, latest)}
          {latest?.n !== null && latest?.n !== undefined ? ` (n ${latest.n})` : ''}
        </span>
      </span>
    )
  }
  // Progress = level + rate: the level against scope, and the move since the pinned baseline.
  const base = star.baseline
  const baseValue = base ? valueAt(star, base.iteration) : null
  const steps = base && latest ? track.iterations.findIndex((it) => it.id === latest.iteration) - track.iterations.findIndex((it) => it.id === base.iteration) : 0
  const moved = base && base.value !== null && latest?.value !== null && latest ? latest.value - base.value : null
  return (
    <span>
      <b className="vt-num">{formatKpiValue(star, latest)}</b> {star.label}
      {moved !== null && base && steps > 0 ? (
        <span className="vt-faint">
          {' '}· {moved >= 0 ? '+' : '−'}
          {Math.abs(moved)} over {steps} {unitWord(track, steps)} since {base.label}
          {baseValue?.n !== null && baseValue?.n !== undefined && baseValue.n <= 1 ? ' · unconfirmed · repeat needed' : ''}
        </span>
      ) : null}
    </span>
  )
}

function parseRoadmapState(raw: string | undefined): RoadmapWidgetState {
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw) as unknown
    return parsed && typeof parsed === 'object' ? (parsed as RoadmapWidgetState) : {}
  } catch {
    return {}
  }
}

/** The Roadmap section: first-class on the track page, under the KPI rows. Calm by default (density 'calm': the current
 * rung and what's next); "Expand" switches it to 'full' in place. The widget's own state is the `rm` route key (JSON),
 * the expansion is `rmopen`, so Back and a reload keep both. */
function RoadmapSection({ track, nav, backend, settings }: { track: Track; nav: Nav; backend: PluginBackend; settings: RoadmapSettings }) {
  const route = nav.route
  const open = route.rmopen === '1'
  const roadmap = useRegisteredRoadmap(backend, track.id)
  const setRoute = (patch: Route) => nav.go({ ...route, ...patch }, 'replace')
  // WHY a spread object: `loading` is the real widget's prop (roadmap branch); the stub here does not declare it yet,
  // and a spread passes it to both without a type error.
  const widget = {
    track: track.id,
    doc: roadmap.doc,
    state: parseRoadmapState(route.rm),
    onState: (next: RoadmapWidgetState) => setRoute({ rm: JSON.stringify(next) }),
    onOpenRung: (rungId: string) => openRung(track, nav, rungId),
    onOpenEvidence: (ref: { path: string; line?: number }) =>
      nav.go({ track: track.id, rm: route.rm, rmopen: route.rmopen, file: ref.path, line: ref.line !== undefined ? String(ref.line) : undefined }),
    density: open ? ('full' as const) : ('calm' as const),
    settings,
    loading: roadmap.loading,
  }
  return (
    <section className="vt-a-section vt-a-roadmap" data-testid="vt-a-roadmap">
      <div className="vt-a-section-head">
        <h2 className="vt-h3">Roadmap</h2>
        <button
          type="button"
          className="vt-btn vt-a-link vt-small"
          aria-expanded={open}
          data-testid="vt-a-roadmap-expand"
          onClick={() => setRoute({ rmopen: open ? undefined : '1' })}
        >
          {open ? 'Collapse' : 'Expand'}
        </button>
      </div>
      <div className="vt-a-roadmap-body">
        <RoadmapWidget {...widget} />
        {roadmap.error ? (
          <p className="vt-small vt-tone-risk" role="alert">
            The roadmap could not load: {roadmap.error}
          </p>
        ) : null}
      </div>
    </section>
  )
}
