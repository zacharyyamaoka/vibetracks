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
import { useLayoutEffect, useRef } from 'react'
import { RoadmapWidget, type RoadmapDocState } from '../../roadmap'
import { trendDomain } from './columns'
import { blockingWords, isReporting, lastMoved, needsCount, registryOf, rungOf } from './live'
import { openRung, type Nav } from './nav'
import { TrackMenu, TrackName, type Renamer } from './rename'
import { useRegisteredRoadmap } from './roadmapReload'
import { provenOf, provenTitle } from './proven'
import { openNeeds } from '../../needs'
import { formatLocal } from '../../shared/time'
import { kpiGroupsOf } from './robotKpis'

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
  // WHY "nothing reported blocks a rung" plus a count of the silent tracks when only some report: a sum that skips the
  // unknown tracks is not a "0" for them, so the sentence must not claim the whole board is unblocked.
  const blockingSentence = blocking
    ? `${blocking} ${blocking === 1 ? 'question blocks' : 'questions block'} a rung`
    : unknownNeeds === tracks.length
      ? 'questions not reported yet'
      : unknownNeeds
        ? 'nothing reported blocks a rung'
        : 'nothing blocks a rung'
  const summary = [
    `${tracks.length} work ${tracks.length === 1 ? 'track' : 'tracks'}`,
    `${reporting} reporting`,
    ...(quiet ? [`${quiet} quiet past ${quiet === 1 ? 'its' : 'their'} stall rule`] : []),
    blockingSentence,
    ...(unknownNeeds && unknownNeeds < tracks.length ? [`questions not reported on ${unknownNeeds} ${unknownNeeds === 1 ? 'track' : 'tracks'}`] : []),
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
        <div className="vt-a-tablescroll">
          <table className="vt-table vt-a-tracks" aria-label="Work tracks">
            <colgroup>
              <col style={{ width: '18%' }} />
              <col style={{ width: '17%' }} />
              <col style={{ width: '19%' }} />
              <col style={{ width: '18%' }} />
              <col style={{ width: '11%' }} />
              <col style={{ width: '12%' }} />
              {/* WHY a fixed 52px and not 4%: the row end holds the rename menu and the chevron (~40px of fixed-size
                  controls); at 1280 a 4% column was 36px and the chevron printed past the table's right edge. */}
              <col style={{ width: 52 }} />
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
        </div>
      )}

      <p className="vt-a-foot vt-small vt-faint">
        {projection.source.live ? 'Live' : 'Snapshot'} · read <span title={formatLocal(projection.generated_at, { year: true })}>{formatLocal(projection.generated_at)}</span>
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
  // WHY one roadmap per row, shared by the rung and progress cells: the real useRoadmap polls; two calls would double it.
  const roadmap = useRegisteredRoadmap(backend, track.id)
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
        <ProgressCell track={track} showDeltas={showDeltas} roadmapDoc={roadmap.doc} />
      </td>
      <td>
        <RungCell track={track} nav={nav} roadmap={roadmap} />
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

/** The north star as one object: value (or value / scope), how it moved, and its trend; plus "· N proven" when the
 * track's roadmap document is loaded (proven.ts: the projector's own green + done counts). */
export function ProgressCell({ track, showDeltas, roadmapDoc = null }: { track: Track; showDeltas: boolean; roadmapDoc?: unknown }) {
  const star = northStar(track)
  const proven = <ProvenNote doc={roadmapDoc} />
  if (!star) {
    return (
      <span className="vt-a-two">
        <span className="vt-faint" title={isReporting(track) ? 'this track declares no north star' : 'not reporting: no numbers claimed'}>
          —
        </span>
        {provenOf(roadmapDoc) ? <small>{proven}</small> : null}
      </span>
    )
  }
  const latest = latestValue(star)
  const delta = deltaVsBaseline(star)
  const aggregate = star.aggregate && star.aggregate.value !== null ? star.aggregate : null
  // WHY the aggregate for a deployment: its last session is one condition mix of many; the day summary ("day 07-29
  // median", n 57) is the honest headline, and the session series stays in the sparkline.
  const headline = aggregate ? formatValue(aggregate.value, star.unit) : formatKpiValue(star, latest)
  // WHY the label for a grouped track (the rig): its north star is a robot KPI read once from the KPI table, so "n = 26"
  // alone would not say what 2.63° is.
  const detail = aggregate
    ? `${aggregate.label}${aggregate.n !== null ? ` · n ${aggregate.n}` : ''}`
    : kpiGroupsOf(track)
      ? star.label
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
        {/* WHY its own line: appended to the detail it wrapped the 19%-wide cell to four lines ("+15 vs start / (freeze)
            · 4 proven / (not current)"); one more short line keeps both readable. */}
        {provenOf(roadmapDoc) ? <small>{proven}</small> : null}
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

/** "4 proven" or "4 proven (not current)", or nothing when the roadmap document is absent or carries no counts. */
export function ProvenNote({ doc }: { doc: unknown }) {
  const proven = provenOf(doc)
  if (!proven) return null
  return (
    <span className="vt-num" data-testid="vt-a-proven" data-stale={proven.stale} title={provenTitle(proven)}>
      <span style={{ whiteSpace: 'nowrap' }}>{proven.proven} proven</span>
      {proven.stale ? (
        <>
          {' '}
          <span className="vt-tone-stale" style={{ whiteSpace: 'nowrap' }}>
            (not current)
          </span>
        </>
      ) : null}
    </span>
  )
}

/** Where the loop is on its roadmap and what comes next, from the best source there is, in this order:
 *   (a) the roadmap widget's own calm answer when the track's roadmap document has loaded (one source for that
 *       sentence, never a second derivation here);
 *   (b) the track's `rung`, which the adapter read from the loop's own status file, in the loop's own words;
 *   (c) the newest iteration, labelled "latest <unit>" so it can never read as the current rung, and a grey word for
 *       why there is no rung line. */
function RungCell({ track, nav, roadmap }: { track: Track; nav: Nav; roadmap: RoadmapDocState }) {
  const declared = Boolean(registryOf(track)?.roadmap)
  const widgetBox = useRef<HTMLSpanElement>(null)
  // WHY the widget's text as the cell's title: the home row clamps the widget's sentence to two lines, so its whole
  // text must stay one hover away (truthful rendering); the widget is another session's, so read what it drew.
  useLayoutEffect(() => {
    const box = widgetBox.current
    if (box) box.title = (box.textContent ?? '').replace(/\s+/g, ' ').trim()
  })
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
      <span ref={widgetBox} className="vt-a-rungcell" onClick={(event) => event.target instanceof HTMLButtonElement && event.stopPropagation()}>
        <RoadmapWidget {...widget} />
      </span>
    )
  }
  const rung = rungOf(track)
  if (rung) {
    return (
      <span className="vt-a-two" data-testid="vt-a-rung" data-rung-source="track" title={[rung.current, `next: ${rung.next ?? 'not reported'}`, `from ${rung.source}`].join('\n')}>
        <span className="vt-a-clamp-2">{rung.current}</span>
        <small className="vt-a-clamp-2">{rung.next !== null ? `next: ${rung.next}` : 'next not reported'}</small>
      </span>
    )
  }
  const latest = track.iterations.length ? track.iterations[track.iterations.length - 1] : null
  const why = roadmap.loading
    ? 'loading roadmap…'
    : roadmap.error
      ? 'roadmap could not load'
      : declared
        ? 'rung not reported yet'
        : 'no roadmap declared'
  const label = latest ? `latest ${track.iteration.unit}: ${track.iteration.label}` : null
  return (
    <span className="vt-a-two" data-testid="vt-a-rung" data-rung-source="iteration" title={[label, why, roadmap.error].filter(Boolean).join('\n') || undefined}>
      {label ? <span className="vt-a-clamp-2">{label}</span> : <span className="vt-faint">—</span>}
      <small>{why}</small>
    </span>
  )
}

// WHY one line with an explicit ellipsis for the detail (its source label, "grasping_ledger"): the glance row must
// stay one or two lines tall, and a wrapped source label made the grasping row three lines at 1440; the whole label
// stays one hover away in the line's own title (truthful rendering: cut visibly, never silently).
function MovedCell({ projection, track }: { projection: Projection; track: Track }) {
  const moved = lastMoved(projection, track)
  return (
    <span className="vt-a-two vt-a-movedcell" title={moved.detail ?? undefined}>
      <span className={`vt-a-oneline${moved.stale ? ' vt-tone-stale' : moved.unknown ? ' vt-faint' : ''}`} data-testid="vt-a-moved" title={moved.text}>
        {moved.text}
      </span>
      {moved.stale ? (
        <small className="vt-tone-stale vt-a-oneline" title={moved.detail ?? 'stale'}>
          stale
        </small>
      ) : moved.detail ? (
        <small className="vt-a-oneline" data-testid="vt-a-moved-source" title={moved.detail}>
          {moved.detail}
        </small>
      ) : null}
    </span>
  )
}

/** "N blocking · M open", linking to the track's Needs-you page (#vt?track=<id>&needs=1). Unknown is said, never 0. */
export function NeedsCell({ track, nav }: { track: Track; nav: Nav }) {
  const count = needsCount(track)
  const go = (event: { stopPropagation: () => void }) => {
    event.stopPropagation()
    // WHY openNeeds and not nav.go: it marks the entry as pushed by the dashboard, so the needs page's Back returns
    // HERE (the home table) instead of dropping `needs` and landing on the track page.
    openNeeds(nav.go, nav.route, track.id)
  }
  let body
  if (count.open === null) body = <span className="vt-faint">not reported</span>
  else if (count.open === 0) body = <span className="vt-faint">nothing open</span>
  else {
    body = (
      <span className="vt-a-two vt-num">
        {count.blocking ? (
          <b className="vt-tone-warn">{blockingWords(count.blocking)}</b>
        ) : (
          <span className={count.blocking === null ? 'vt-faint' : 'vt-muted'} title={count.blocking === null ? 'the blocking count was not reported' : undefined}>
            {blockingWords(count.blocking)}
          </span>
        )}
        <small>{`${count.open}\u00a0open`}</small>
      </span>
    )
  }
  return (
    <button type="button" className="vt-btn vt-a-needs-cell" data-testid="vt-a-needs-link" title="Open what needs you on this track" onClick={go}>
      {body}
    </button>
  )
}
