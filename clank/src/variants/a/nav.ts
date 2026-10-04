// Where variant A can go. One level per page; every deeper step is a pushState (so Back climbs exactly one level) and
// every sideways move inside a page (open a media item, expand "Needs you", prev/next iteration) is a replaceState.
// WHY carry `rm` and `rmopen` on every route of a track: the roadmap widget's state lives in the hash (VARIANTS.md
// "Roadmap widget slot"), and a drill into evidence and back must not reset the reader's roadmap view.

import type { Route } from '../../shared'

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
