// Variant A · Drill-down pages (asv grid → benchmark page → regressions; PyTorch HUD; Statuspage).
// One level per page, a breadcrumb on every page, and the place kept in the URL hash, so Back, Forward and the mouse
// back button climb exactly one level:
//   L1  Work tracks table ("The Table"), no deployments    #vt
//   L2  Track page: state, Needs you →, KPIs, Roadmap       #vt?track=kinsim
//   L3  Iteration page: what changed, KPI deltas, evidence  #vt?track=kinsim&iteration=W3[&kpi=…]
//       → one item (run metrics + video, report, audit)    #vt?track=can16&item=…
// WHY pages and not panes or a drawer: this is the composition under test (VARIANTS.md "A"); each level gets the whole
// width, so the scorecard can show every iteration and the run page can put real and sim video side by side.
// View options (x axis, deltas) come from the settings page via props.settings; this variant has no toolbar.

import { useCallback, useEffect, useRef, type ReactNode } from 'react'
import type { Projection, Track, VariantProps } from '../../shared'
import { Breadcrumb, evidenceById, iterationById, trackById } from '../../shared'
import './a.css'
import { ItemPage } from './ItemPage'
import { IterationPage } from './IterationPage'
import { makeNav, type Nav } from './nav'
import { TrackPage } from './TrackPage'
import { TracksPage } from './TracksPage'
import { useRenamer } from './rename'
import { RoadmapReloadProvider, useRoadmapReloadRegistry } from './roadmapReload'

export const NAME = 'Drill-down pages'

export default function VariantA(props: VariantProps) {
  const { projection, route, navigate, title, mediaUrl, settings, reload, backend } = props
  const nav = makeNav(route, navigate)
  const root = useRef<HTMLDivElement>(null)
  const xAxis = settings.dashboard.xAxis
  const showDeltas = settings.dashboard.showDeltas
  const track = trackById(projection, route.track)
  // WHY every reload goes through reloadPage: one refresh must cover the whole page, so the projection re-read also
  // forces each mounted roadmap to re-project (a fresh table under a stale roadmap reads as two different moments).
  const roadmapReloads = useRoadmapReloadRegistry()
  const reloadPage = useCallback(() => {
    reload()
    for (const reloadRoadmap of roadmapReloads) reloadRoadmap()
  }, [reload, roadmapReloads])
  const renamer = useRenamer(backend, projection, reloadPage)
  const cancelRename = renamer.cancel

  // WHY scroll to the top on a level change only: a new page starts at its top, but a sideways move inside a page
  // (open a video, expand Needs you) must not jump the reader away from what they just clicked.
  const page = `${route.track ?? ''}|${route.iteration ?? ''}|${route.item ?? ''}|${route.file ?? ''}|${route.rung ?? ''}`
  useEffect(() => {
    const scroller = root.current?.closest('.vt-scroll')
    if (scroller) scroller.scrollTop = 0
    // An edit left open on the page you navigated away from must not reappear elsewhere.
    cancelRename()
  }, [page, cancelRename])

  let body: ReactNode
  if (!track) {
    body = route.track ? (
      <Missing title={title} nav={nav} what={`No track “${route.track}” in this projection.`} />
    ) : (
      <TracksPage projection={projection} title={title} nav={nav} showDeltas={showDeltas} reload={reloadPage} backend={backend} renamer={renamer} />
    )
  } else if (route.file) {
    body = <FilePage projection={projection} track={track} title={title} nav={nav} mediaUrl={mediaUrl} />
  } else if (route.rung) {
    body = <Missing title={title} nav={nav} track={track} what={`Rung ${route.rung}: no judged run or note in this projection names it yet.`} />
  } else if (route.item) {
    const item = evidenceById(track, [route.item])[0]
    body = item ? (
      <ItemPage projection={projection} track={track} item={item} title={title} nav={nav} mediaUrl={mediaUrl} />
    ) : (
      <Missing title={title} nav={nav} track={track} what={`No evidence item “${route.item}” in ${track.title}.`} />
    )
  } else if (route.iteration) {
    const iteration = iterationById(track, route.iteration)
    body = iteration ? (
      <IterationPage projection={projection} track={track} iteration={iteration} title={title} nav={nav} mediaUrl={mediaUrl} showDeltas={showDeltas} />
    ) : (
      <Missing title={title} nav={nav} track={track} what={`No ${track.iteration.unit} “${route.iteration}” in ${track.title}.`} />
    )
  } else {
    body = (
      <TrackPage
        projection={projection}
        track={track}
        title={title}
        nav={nav}
        xAxis={xAxis}
        showDeltas={showDeltas}
        backend={backend}
        roadmapSettings={settings.roadmap}
        renamer={renamer}
        mediaUrl={mediaUrl}
      />
    )
  }
  return (
    <RoadmapReloadProvider registry={roadmapReloads}>
      <div ref={root} className="vt-a" data-testid="vt-variant-a">
        {body}
      </div>
    </RoadmapReloadProvider>
  )
}

/** A place the route names but the data does not hold: say so and offer the way up (never a blank page). */
function Missing({ title, nav, track, what }: { title: string; nav: Nav; track?: Track; what: string }) {
  return (
    <div className="vt-page vt-a-page" data-testid="vt-a-missing">
      <Breadcrumb items={[{ label: title, onClick: nav.tracks }, ...(track ? [{ label: track.title, onClick: () => nav.track(track.id) }] : []), { label: 'Not found' }]} />
      <p className="vt-muted">{what}</p>
      <p className="vt-small" style={{ marginTop: 10 }}>
        <button type="button" className="vt-btn vt-a-link" onClick={() => (track ? nav.track(track.id) : nav.tracks())}>
          ‹ Back to {track ? track.title : title}
        </button>
      </p>
    </div>
  )
}

/** The roadmap's onOpenEvidence target: the file opens in place when the media allowlist holds it; otherwise the path
 * is shown to copy, and the page says why it cannot open (the backend serves only allowlisted files). */
function FilePage({ projection, track, title, nav, mediaUrl }: { projection: Projection; track: Track; title: string; nav: Nav; mediaUrl: (id: string) => string }) {
  const path = nav.route.file as string
  const media = Object.values(projection.media).find((entry) => entry.path === path) ?? null
  return (
    <div className="vt-page vt-a-page" data-testid="vt-a-file">
      <Breadcrumb items={[{ label: title, onClick: nav.tracks }, { label: track.title, onClick: () => nav.track(track.id) }, { label: path.split('/').pop() ?? path }]} />
      <h1 className="vt-h2">{path.split('/').pop()}</h1>
      <p className="vt-sub">
        <code className="vt-a-code">{path}</code>
        {nav.route.line ? <span className="vt-faint"> · line {nav.route.line}</span> : null}
      </p>
      {media ? (
        <div className="vt-a-section">
          <a href={mediaUrl(media.id)} target="_blank" rel="noreferrer">
            Open {media.label}
          </a>
        </div>
      ) : (
        <p className="vt-a-section vt-faint">This file is not in the projection's media allowlist, so it cannot open here. Open the path above yourself.</p>
      )}
    </div>
  )
}
