// L1 · the Tracks table ("The Table" from round 2, the one Zach liked): one quiet row per track, deployments indented
// under the loop they serve. A row opens its Track page (L2).
// Research applied: three-level drill-down (glance level), number + trend + context as one object (Progress cell:
// value / scope, sparkline, delta vs the named baseline), status colour only for exceptions, missing data explicit.

import type { Projection, Track } from '../../shared'
import {
  StatusWord,
  Sparkline,
  blockingQuestions,
  childrenOf,
  deltaVsBaseline,
  describeDelta,
  formatDay,
  formatKpiValue,
  formatN,
  formatValue,
  latestValue,
  northStar,
  topLevelTracks,
} from '../../shared'
import { latestDated, relativeDay, trendDomain, totalBlocking } from './columns'
import type { Nav } from './nav'

export function TracksPage({ projection, title, nav, showDeltas, reload }: {
  projection: Projection
  title: string
  nav: Nav
  showDeltas: boolean
  reload: () => void
}) {
  const loops = topLevelTracks(projection)
  const exceptions = loops.filter((track) => track.state.tone === 'warn' || track.state.tone === 'risk' || track.state.tone === 'stale')
  const blocking = totalBlocking(projection)
  const summary = [
    `${loops.length} ${loops.length === 1 ? 'loop' : 'loops'}${exceptions.length ? `: ${exceptions.map((t) => `1 ${t.state.word.toLowerCase()}`).join(', ')}` : ''}`,
    blocking ? `${blocking} ${blocking === 1 ? 'question blocks' : 'questions block'} a rung` : 'nothing blocks a rung',
  ]
  return (
    <div className="vt-page vt-a-page" data-testid="vt-a-l1">
      <h1 className="vt-h1">{title}</h1>
      <p className="vt-sub" data-testid="vt-data-proof">
        {formatDay(projection.as_of)} · {summary.join(' · ')}
      </p>

      <table className="vt-table vt-a-tracks" aria-label="Tracks">
        <colgroup>
          <col style={{ width: '23%' }} />
          <col style={{ width: '22%' }} />
          <col style={{ width: '25%' }} />
          <col style={{ width: '14%' }} />
          <col style={{ width: '12%' }} />
          <col style={{ width: '4%' }} />
        </colgroup>
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Progress</th>
            <th>Last moved</th>
            <th>Needs you</th>
            <th aria-hidden="true" />
          </tr>
        </thead>
        <tbody>
          {loops.map((loop) => (
            <TrackRows key={loop.id} projection={projection} track={loop} nav={nav} showDeltas={showDeltas} />
          ))}
        </tbody>
      </table>

      <p className="vt-a-foot vt-small vt-faint">
        {projection.source.live ? 'Live' : 'Snapshot'} of {formatDay(projection.as_of)} · built {projection.generated_at.replace('T', ' ').slice(0, 16)}
        {projection.source.live ? '' : ' · not live yet (the live adapter is still to do)'} ·{' '}
        <button type="button" className="vt-btn vt-a-link" onClick={reload} data-testid="vt-a-reload">
          Reload
        </button>
      </p>
    </div>
  )
}

function TrackRows({ projection, track, nav, showDeltas }: { projection: Projection; track: Track; nav: Nav; showDeltas: boolean }) {
  const children = childrenOf(projection, track.id)
  return (
    <>
      <TrackRow projection={projection} track={track} nav={nav} showDeltas={showDeltas} />
      {children.length ? (
        <tr className="vt-group vt-a-subgroup">
          <td colSpan={6}>Deployments · evidence for the {track.title}</td>
        </tr>
      ) : null}
      {children.map((child) => (
        <TrackRow key={child.id} projection={projection} track={child} nav={nav} showDeltas={showDeltas} indent />
      ))}
    </>
  )
}

function TrackRow({ projection, track, nav, showDeltas, indent }: { projection: Projection; track: Track; nav: Nav; showDeltas: boolean; indent?: boolean }) {
  const star = northStar(track)
  const latest = star ? latestValue(star) : null
  const moved = latestDated(track)
  const blocking = blockingQuestions(track).length
  const open = track.needs_you.length
  const delta = star ? deltaVsBaseline(star) : null
  const aggregate = star?.aggregate && star.aggregate.value !== null ? star.aggregate : null
  // WHY the aggregate for a deployment: its last session is one condition mix of many; the day summary ("day 07-29
  // median", n 57) is the honest headline (task brief), and the session series stays in the sparkline.
  const headline = aggregate && star ? formatValue(aggregate.value, star.unit) : star ? formatKpiValue(star, latest) : '—'
  const headlineDetail = aggregate
    ? `${aggregate.label}${aggregate.n !== null ? ` · n ${aggregate.n}` : ''}`
    : showDeltas && star && delta
      ? describeDelta(star, delta)
      : star && latest
        ? formatN(latest)
        : ''
  return (
    <tr
      className={`vt-row-link vt-a-trackrow${indent ? ' vt-a-indent' : ''}`}
      data-testid="vt-a-track-row"
      data-track={track.id}
      onClick={() => nav.track(track.id)}
    >
      <td>
        <button type="button" className="vt-btn vt-a-name" onClick={(event) => { event.stopPropagation(); nav.track(track.id) }}>
          {track.title}
        </button>
      </td>
      <td>
        <StatusWord status={track.state} detail={track.state.detail} />
      </td>
      <td>
        <span className="vt-a-prog" title={star ? star.label : 'no north star'}>
          <span className="vt-a-two">
            <strong className="vt-num">{headline}</strong>
            {headlineDetail ? <small>{headlineDetail}</small> : null}
          </span>
          {star ? (
            <Sparkline
              values={star.values.map((v) => (v.measured ? v.value : null))}
              step={star.target?.kind === 'scope'}
              domain={trendDomain(star)}
              ariaLabel={`${star.label} over ${track.iterations.length} ${track.iteration.unit}s`}
            />
          ) : null}
        </span>
      </td>
      <td>
        <span className="vt-a-two">
          {relativeDay(moved?.date ?? null, projection.as_of)}
          <small>{track.iteration.label}</small>
        </span>
      </td>
      <td>
        {open === 0 ? (
          <span className="vt-faint" title="no open question recorded">—</span>
        ) : (
          <span className="vt-a-two vt-num">
            {blocking ? <b className="vt-tone-warn">{blocking} blocking</b> : <span className="vt-muted">none blocking</span>}
            <small>{open} open</small>
          </span>
        )}
      </td>
      <td className="vt-a-chev" aria-hidden="true">
        ›
      </td>
    </tr>
  )
}
