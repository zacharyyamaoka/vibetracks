// Where variant A can go. One level per page; every deeper step is a pushState (so Back climbs exactly one level) and
// every sideways move inside a page (open a media item, expand "Needs you", prev/next iteration) is a replaceState.
// WHY carry `rm` and `rmopen` on every route of a track: the roadmap widget's state lives in the hash (VARIANTS.md
// "Roadmap widget slot"), and a drill into evidence and back must not reset the reader's roadmap view.

import type { Route, Track } from '../../shared'

export interface Nav {
  route: Route
  go: (next: Route, mode?: 'push' | 'replace') => void
  /** L1. */
  tracks: () => void
  /** L2. */
  track: (trackId: string, extra?: Route) => void
  /** L3: one iteration (optionally with a KPI highlighted). */
  iteration: (trackId: string, iterationId: string, extra?: Route) => void
  /** L3: one evidence item (run detail, report, audit). */
  item: (trackId: string, itemId: string, extra?: Route) => void
}

export function makeNav(route: Route, navigate: (route: Route, mode?: 'push' | 'replace') => void): Nav {
  const keep = (trackId: string): Route => (trackId === route.track ? { rm: route.rm, rmopen: route.rmopen } : {})
  const go = (next: Route, mode: 'push' | 'replace' = 'push') => navigate(clean(next), mode)
  return {
    route,
    go,
    tracks: () => go({}),
    track: (trackId, extra) => go({ track: trackId, ...keep(trackId), ...extra }),
    iteration: (trackId, iterationId, extra) => go({ track: trackId, ...keep(trackId), iteration: iterationId, ...extra }),
    item: (trackId, itemId, extra) => go({ track: trackId, ...keep(trackId), item: itemId, ...extra }),
  }
}

function clean(route: Route): Route {
  const out: Route = {}
  for (const [key, value] of Object.entries(route)) if (value) out[key] = value
  return out
}

/** A roadmap rung click (onOpenRung): the rung's latest judged run ("BT1 · regression r1"), else the latest note naming
 * it, else a rung page that says there is no evidence (missing is explicit, never a dead click). */
export function openRung(track: Track, nav: Nav, rungId: string): void {
  const items = track.iterations.flatMap((it) => track.evidence.by_iteration[it.id] ?? [])
  const pattern = new RegExp(`(^|[^A-Z0-9])${rungId.replace(/[^A-Za-z0-9]/g, '')}([^A-Z0-9]|$)`)
  const runs = items.filter((item) => item.kind === 'run' && pattern.test(item.title))
  const notes = items.filter((item) => item.kind === 'note' && (pattern.test(item.title) || pattern.test(item.note ?? '') || Object.keys(item.metrics).includes(rungId)))
  const hit = runs[runs.length - 1] ?? notes[notes.length - 1]
  if (hit) nav.item(track.id, hit.id)
  else nav.go({ track: track.id, rm: nav.route.rm, rmopen: nav.route.rmopen, rung: rungId })
}
