// L1 · the home page: one quiet row per WORK TRACK (Zach, 2026-10-04: "on the first page we just want to see the
// different work tracks essentially"), in the registry's priority order, however many tracks the registry holds.
// WHY no deployments here: CAN 12 and CAN 16 are evidence inside the rig track (its page lists them); on the home page
// they read as two more loops, which they are not ("you can get rid of the deployments on the first page").
// Columns, in "The Table"'s calm language: Name · Status · Progress (north star + trend) · Current rung → next ·
// Last moved (live heartbeat, stale marked) · Needs you. A track that is not reporting says why, in grey, and claims
// no numbers.

import type { PluginBackend } from '@clank/api'
import type { Projection, Track } from '../../shared'
import {
  StatusWord,
  Sparkline,
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
import { RoadmapWidget, useRoadmap } from '../../roadmap'
import { trendDomain } from './columns'
import { isReporting, lastMoved, needsCount, registryOf } from './live'
import { openRung, type Nav } from './nav'
import { TrackMenu, TrackName, type Renamer } from './rename'

export function TracksPage({ projection, title, nav, showDeltas, reload, backend, renamer }: {
  projection: Projection
  title: string
  nav: Nav
  showDeltas: boolean
  reload: () => void
  backend: PluginBackend
  renamer: Renamer
}) {
  // topLevelTracks keeps projection order, which the live build sets to the registry's vibe-priority order.
  const tracks = topLevelTracks(projection)
  const reporting = tracks.filter(isReporting).length
  const quiet = tracks.filter((track) => lastMoved(projection, track).stale).length
  const counts = tracks.map(needsCount)
  const blocking = counts.reduce((sum, count) => sum + (count.blocking ?? 0), 0)
  const unknownNeeds = counts.filter((count) => count.blocking === null).length
  const summary = [
    `${tracks.length} work ${tracks.length === 1 ? 'track' : 'tracks'}`,
    `${reporting} reporting`,
    ...(quiet ? [`${quiet} quiet past ${quiet === 1 ? 'its' : 'their'} stall rule`] : []),
    blocking ? `${blocking} ${blocking === 1 ? 'question blocks' : 'questions block'} a rung` : unknownNeeds === tracks.length ? 'questions not reported yet' : 'nothing blocks a rung',
  ]
  return (
    <div className="vt-page vt-a-page" data-testid="vt-a-l1">
      <h1 className="vt-h1">{title}</h1>
      <p className="vt-sub" data-testid="vt-data-proof">
        {summary.join(' · ')}
      </p>

      {tracks.length === 0 ? (
        <p className="vt-a-section vt-faint">No work tracks in the registry yet.</p>
      ) : (
        <table className="vt-table vt-a-tracks" aria-label="Work tracks">
          <colgroup>
            <col style={{ width: '20%' }} />
            <col style={{ width: '17%' }} />
            <col style={{ width: '19%' }} />
            <col style={{ width: '19%' }} />
            <col style={{ width: '11%' }} />
            <col style={{ width: '10%' }} />
            <col style={{ width: '4%' }} />
          </colgroup>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Current rung → next</th>
              <th>Last moved</th>
              <th>Needs you</th>
              <th aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {tracks.map((track) => (
              <TrackRow key={track.id} projection={projection} track={track} nav={nav} showDeltas={showDeltas} backend={backend} renamer={renamer} />
            ))}
          </tbody>
        </table>
      )}

      <p className="vt-a-foot vt-small vt-faint">
        {projection.source.live ? 'Live' : 'Snapshot'} · read {projection.generated_at.replace('T', ' ').slice(0, 16)}
        {projection.source.live ? '' : ` · snapshot of ${formatDay(projection.as_of)}`} ·{' '}
        <button type="button" className="vt-btn vt-a-link" onClick={reload} data-testid="vt-a-reload">
          Reload
        </button>
      </p>
    </div>
  )
}

function TrackRow({ projection, track, nav, showDeltas, backend, renamer }: {
  projection: Projection
  track: Track
  nav: Nav
  showDeltas: boolean
  backend: PluginBackend
  renamer: Renamer
}) {
  const open = () => nav.track(track.id)
  const reporting = isReporting(track)
  return (
    <tr className={`vt-row-link vt-a-trackrow${reporting ? '' : ' vt-a-quiet'}`} data-testid="vt-a-track-row" data-track={track.id} onClick={open}>
      <td>
        <TrackName track={track} renamer={renamer} onOpen={open} />
      </td>
      <td>
        {/* WHY clamped to two lines with the whole detail on hover: adapters write long state details ("tier 2 · 30 of 30
            cells · …"); on the glance page they would make every row a paragraph. The track page shows it in full. */}
        <span className="vt-a-statuscell" title={track.state.detail ?? undefined}>
          <StatusWord status={track.state} detail={track.state.detail} />
        </span>
      </td>
      <td>
        <ProgressCell track={track} showDeltas={showDeltas} />
      </td>
      <td>
        <RungCell track={track} nav={nav} backend={backend} />
      </td>
      <td>
        <MovedCell projection={projection} track={track} />
      </td>
      <td>
        <NeedsCell track={track} nav={nav} />
      </td>
      <td className="vt-a-rowend">
        <TrackMenu track={track} renamer={renamer} />
        <span className="vt-a-chev" aria-hidden="true">
          ›
        </span>
      </td>
    </tr>
  )
}

/** The north star as one object: value (or value / scope), how it moved, and its trend. */
export function ProgressCell({ track, showDeltas }: { track: Track; showDeltas: boolean }) {
  const star = northStar(track)
  if (!star) {
    return (
      <span className="vt-faint" title={isReporting(track) ? 'this track declares no north star' : 'not reporting: no numbers claimed'}>
        —
      </span>
    )
  }
  const latest = latestValue(star)
  const delta = deltaVsBaseline(star)
  const aggregate = star.aggregate && star.aggregate.value !== null ? star.aggregate : null
  // WHY the aggregate for a deployment: its last session is one condition mix of many; the day summary ("day 07-29
  // median", n 57) is the honest headline, and the session series stays in the sparkline.
  const headline = aggregate ? formatValue(aggregate.value, star.unit) : formatKpiValue(star, latest)
  const detail = aggregate
    ? `${aggregate.label}${aggregate.n !== null ? ` · n ${aggregate.n}` : ''}`
    : showDeltas && delta
      ? describeDelta(star, delta)
      : latest
        ? formatN(latest)
        : ''
  return (
    <span className="vt-a-prog" title={star.label}>
      <span className="vt-a-two">
        <strong className="vt-num">{headline}</strong>
        <small>{detail || star.label}</small>
      </span>
      <Sparkline
        values={star.values.map((v) => (v.measured ? v.value : null))}
        step={star.target?.kind === 'scope'}
        domain={trendDomain(star)}
        ariaLabel={`${star.label} over ${track.iterations.length} ${track.iteration.unit}s`}
      />
    </span>
  )
}

/** Where the loop is on its roadmap and what comes next: the roadmap widget's own calm answer when the track's roadmap
 * has loaded (one source for that sentence, never a second derivation here); otherwise the track's current iteration,
 * and a grey word for why there is no roadmap line. */
function RungCell({ track, nav, backend }: { track: Track; nav: Nav; backend: PluginBackend }) {
  const roadmap = useRoadmap(backend, track.id)
  const declared = Boolean(registryOf(track)?.roadmap)
  if (roadmap.doc !== null) {
    const widget = {
      track: track.id,
      doc: roadmap.doc,
      state: {},
      onState: () => undefined,
      onOpenRung: (rungId: string) => openRung(track, nav, rungId),
      onOpenEvidence: () => nav.track(track.id),
      density: 'calm' as const,
      settings: {},
      loading: roadmap.loading,
    }
    return (
      <span className="vt-a-rungcell" onClick={(event) => event.target instanceof HTMLButtonElement && event.stopPropagation()}>
        <RoadmapWidget {...widget} />
      </span>
    )
  }
  const current = track.iterations.length ? track.iteration.label : null
  const why = roadmap.loading
    ? 'loading roadmap…'
    : roadmap.error
      ? 'roadmap could not load'
      : declared
        ? 'roadmap not reported yet'
        : 'no roadmap declared'
  return (
    <span className="vt-a-two" title={roadmap.error ?? undefined}>
      {current ? <span>{current}</span> : <span className="vt-faint">—</span>}
      <small>{current ? `current ${track.iteration.unit} · ${why}` : why}</small>
    </span>
  )
}

function MovedCell({ projection, track }: { projection: Projection; track: Track }) {
  const moved = lastMoved(projection, track)
  return (
    <span className="vt-a-two" title={moved.detail ?? undefined}>
      <span className={moved.stale ? 'vt-tone-stale' : moved.unknown ? 'vt-faint' : undefined} data-testid="vt-a-moved">
        {moved.text}
      </span>
      {moved.stale ? <small className="vt-tone-stale">stale</small> : moved.detail ? <small>{moved.detail}</small> : null}
    </span>
  )
}

/** "N blocking · M open", linking to the track's Needs-you page (#vt?track=<id>&needs=1). Unknown is said, never 0. */
export function NeedsCell({ track, nav }: { track: Track; nav: Nav }) {
  const count = needsCount(track)
  const go = (event: { stopPropagation: () => void }) => {
    event.stopPropagation()
    nav.go({ track: track.id, needs: '1' })
  }
  let body
  if (count.open === null) body = <span className="vt-faint">not reported</span>
  else if (count.open === 0) body = <span className="vt-faint">nothing open</span>
  else {
    body = (
      <span className="vt-a-two vt-num">
        {count.blocking ? <b className="vt-tone-warn">{count.blocking} blocking</b> : <span className="vt-muted">none blocking</span>}
        <small>{count.open} open</small>
      </span>
    )
  }
  return (
    <button type="button" className="vt-btn vt-a-needs-cell" data-testid="vt-a-needs-link" title="Open what needs you on this track" onClick={go}>
      {body}
    </button>
  )
}
