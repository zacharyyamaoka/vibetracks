// L2 · the Track page: one calm answer (state + north star as level and rate), a collapsed "Needs you", then the KPI
// scorecard, the track's reports, and the Roadmap widget slot (collapsed). Every track (loop or deployment) renders
// through this one template: "solve the display once".

import type { Projection, Route, Track } from '../../shared'
import {
  Breadcrumb,
  StatusWord,
  blockingQuestions,
  childrenOf,
  formatKpiValue,
  formatValue,
  latestValue,
  northStar,
  trackById,
  valueAt,
} from '../../shared'
import { RoadmapWidget, useRoadmap, type RoadmapSettings, type RoadmapWidgetState } from '../../roadmap'
import type { PluginBackend } from '@clank/api'
import { evidenceOwningMedia, formatSince, unitWord } from './columns'
import type { Nav } from './nav'
import { Scorecard } from './Scorecard'

export function TrackPage({ projection, track, title, nav, xAxis, showDeltas, backend, roadmapSettings }: {
  projection: Projection
  track: Track
  title: string
  nav: Nav
  xAxis: 'iteration' | 'day'
  showDeltas: boolean
  backend: PluginBackend
  roadmapSettings: RoadmapSettings
}) {
  const route = nav.route
  const parent = track.parent ? trackById(projection, track.parent) : null
  const children = childrenOf(projection, track.id)
  return (
    <div className="vt-page vt-a-page" data-testid="vt-a-l2" data-track={track.id}>
      <Breadcrumb
        items={[
          { label: title, onClick: nav.tracks },
          ...(parent ? [{ label: parent.title, onClick: () => nav.track(parent.id) }] : []),
          { label: track.title },
        ]}
      />
      <h1 className="vt-h1">{track.title}</h1>
      <p className="vt-sub">{track.summary}</p>

      <dl className="vt-a-props">
        <dt>Status</dt>
        <dd>
          <StatusWord status={track.state} />
          <span className="vt-faint"> {track.state.detail}{track.state.since ? ` · since ${formatSince(track.state.since)}` : ''}</span>
        </dd>
        <dt>North star</dt>
        <dd>
          <NorthStarLine track={track} />
        </dd>
        <dt>Needs you</dt>
        <dd>
          <NeedsYou track={track} open={route.nq === '1'} onToggle={() => nav.go({ ...route, nq: route.nq === '1' ? undefined : '1' }, 'replace')} />
        </dd>
        {children.length ? (
          <>
            <dt>Deployments</dt>
            <dd>
              {children.map((child, index) => (
                <span key={child.id}>
                  {index > 0 ? <span className="vt-faint"> · </span> : null}
                  <button type="button" className="vt-btn vt-a-link" onClick={() => nav.track(child.id)}>
                    {child.title}
                  </button>{' '}
                  <StatusWord status={child.state} bare className="vt-small" />
                </span>
              ))}
            </dd>
          </>
        ) : null}
      </dl>

      <section className="vt-a-section">
        <h2 className="vt-h3">
          Scorecard <span className="vt-a-h-note">
            {track.kpis.length} KPIs × {track.iterations.length} {unitWord(track, track.iterations.length)}
            {xAxis === 'day' ? ' grouped by day' : ''} · latest emphasised · a cell or column opens its evidence
          </span>
        </h2>
        <Scorecard
          track={track}
          xAxis={xAxis}
          showDeltas={showDeltas}
          selectedKpi={route.kpi ?? null}
          onOpenColumn={(column) => nav.iteration(track.id, column.opens)}
          onOpenCell={(kpi, column) => nav.iteration(track.id, column.opens, { kpi: kpi.id })}
        />
      </section>

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

      <RoadmapSection track={track} nav={nav} backend={backend} settings={roadmapSettings} />
    </div>
  )
}

function NorthStarLine({ track }: { track: Track }) {
  const star = northStar(track)
  if (!star) return <span className="vt-faint">no north star declared</span>
  const latest = latestValue(star)
  const aggregate = star.aggregate && star.aggregate.value !== null ? star.aggregate : null
  if (aggregate) {
    return (
      <span>
        <b className="vt-num">{formatValue(aggregate.value, star.unit)}</b> {star.label.toLowerCase()}
        <span className="vt-faint">
          {' '}· {aggregate.label}
          {aggregate.n !== null ? ` · n ${aggregate.n}` : ''} · last session {formatKpiValue(star, latest)}
          {latest?.n !== null && latest?.n !== undefined ? ` (n ${latest.n})` : ''}
        </span>
      </span>
    )
  }
  // Progress = level + rate (research): the level against scope, and the move since the pinned baseline.
  const base = star.baseline
  const baseValue = base ? valueAt(star, base.iteration) : null
  const steps = base && latest ? track.iterations.findIndex((it) => it.id === latest.iteration) - track.iterations.findIndex((it) => it.id === base.iteration) : 0
  const moved = base && base.value !== null && latest?.value !== null && latest ? latest.value - base.value : null
  return (
    <span>
      <b className="vt-num">{formatKpiValue(star, latest)}</b> {star.label.toLowerCase()}
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

function NeedsYou({ track, open, onToggle }: { track: Track; open: boolean; onToggle: () => void }) {
  const total = track.needs_you.length
  if (total === 0) return <span className="vt-faint">no open question recorded</span>
  const blocking = blockingQuestions(track)
  const rest = track.needs_you.filter((q) => q.blocks.length === 0)
  return (
    <div>
      <button type="button" className="vt-btn vt-a-disclose" onClick={onToggle} aria-expanded={open} data-testid="vt-a-needs-toggle">
        {blocking.length ? <b className="vt-tone-warn">{blocking.length} block a rung</b> : <span>none block a rung</span>}
        <span className="vt-faint"> · {total} open</span>
        <span className="vt-a-caret" aria-hidden="true">{open ? '⌄' : '›'}</span>
      </button>
      {open ? (
        <div className="vt-a-needs" data-testid="vt-a-needs">
          <ul>
            {blocking.map((q) => (
              <li key={q.id}>
                <span className="vt-faint vt-num">{q.id}</span>
                <span>{q.q}</span>
                <span className="vt-faint">
                  blocks {q.blocks.join(', ')} · {q.default ? `default “${q.default}”${q.applies ? ` applies ${q.applies}` : ''}` : 'no default recorded'}
                </span>
              </li>
            ))}
          </ul>
          {rest.length ? (
            <>
              <p className="vt-label vt-a-needs-sub">Block nothing · {rest.length}</p>
              <ul className="vt-a-needs-quiet">
                {rest.map((q) => (
                  <li key={q.id}>
                    <span className="vt-faint vt-num">{q.id}</span>
                    <span>{q.q}</span>
                    <span className="vt-faint">{q.default ? `default “${q.default}”` : 'no default recorded'}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
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

/** The Roadmap widget slot (VARIANTS.md): a quiet collapsed section on the Track page; closed = density 'calm', open =
 * 'full' in place. Its state is the `rm` route key (JSON); its rung and evidence clicks route to this variant's L3. */
function RoadmapSection({ track, nav, backend, settings }: { track: Track; nav: Nav; backend: PluginBackend; settings: RoadmapSettings }) {
  const route = nav.route
  const open = route.rmopen === '1'
  const { doc } = useRoadmap(backend, track.id)
  const state = parseRoadmapState(route.rm)
  const setRoute = (patch: Route) => nav.go({ ...route, ...patch }, 'replace')
  return (
    <section className="vt-a-section vt-a-roadmap" data-testid="vt-a-roadmap">
      <button type="button" className="vt-btn vt-a-disclose vt-h3" aria-expanded={open} onClick={() => setRoute({ rmopen: open ? undefined : '1' })}>
        Roadmap <span className="vt-a-caret" aria-hidden="true">{open ? '⌄' : '›'}</span>
      </button>
      <div className="vt-a-roadmap-body">
        <RoadmapWidget
          track={track.id}
          doc={doc}
          state={state}
          onState={(next) => setRoute({ rm: JSON.stringify(next) })}
          onOpenRung={(rungId) => openRung(track, nav, rungId)}
          onOpenEvidence={(ref) => nav.go({ track: track.id, rm: route.rm, rmopen: route.rmopen, file: ref.path, line: ref.line !== undefined ? String(ref.line) : undefined })}
          density={open ? 'full' : 'calm'}
          settings={settings}
        />
      </div>
    </section>
  )
}

/** onOpenRung: the rung's latest judged run ("BT1 · regression r1"), else the latest note naming it, else a rung page
 * that says there is no evidence (missing is explicit, never a dead click). */
export function openRung(track: Track, nav: Nav, rungId: string): void {
  const items = track.iterations.flatMap((it) => track.evidence.by_iteration[it.id] ?? [])
  const pattern = new RegExp(`(^|[^A-Z0-9])${rungId.replace(/[^A-Za-z0-9]/g, '')}([^A-Z0-9]|$)`)
  const runs = items.filter((item) => item.kind === 'run' && pattern.test(item.title))
  const notes = items.filter((item) => item.kind === 'note' && (pattern.test(item.title) || pattern.test(item.note ?? '') || Object.keys(item.metrics).includes(rungId)))
  const hit = runs[runs.length - 1] ?? notes[notes.length - 1]
  if (hit) nav.item(track.id, hit.id)
  else nav.go({ track: track.id, rm: nav.route.rm, rmopen: nav.route.rmopen, rung: rungId })
}
