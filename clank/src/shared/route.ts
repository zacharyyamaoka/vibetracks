// Where the reader is (track → KPI → iteration → evidence item), kept in the URL hash so browser Back/Forward and
// reload keep place (BRIEF fr1: "each level is one deliberate action away, keeps place (URL/back works)").
//
// WHY the hash and not the viewer's viewState: viewState survives a layout restore but not Back; Zach's reference
// apps (Notion, Linear, Grafana) all answer Back with the previous level. WHY one shared route for all variants: the
// A · B · C switcher then keeps the selection, so the same track/KPI can be compared across variants in one click.
// WHY pushState for a deeper level and replaceState for a sideways move: Back should climb a level, not replay every
// hover-free click along a row.

import { useCallback, useEffect, useState } from 'react'

export interface Route {
  track?: string
  kpi?: string
  iteration?: string
  item?: string
  /** Variants may keep extra keys (a tab, a compare pair); they round-trip untouched. */
  [key: string]: string | undefined
}

const PREFIX = '#vt'

export function parseRoute(hash: string): Route {
  if (!hash.startsWith(PREFIX)) return {}
  const query = hash.slice(PREFIX.length).replace(/^\?/, '')
  const route: Route = {}
  for (const [key, value] of new URLSearchParams(query)) if (value) route[key] = value
  return route
}

export function formatRoute(route: Route): string {
  const params = new URLSearchParams()
  for (const key of ['track', 'kpi', 'iteration', 'item']) if (route[key]) params.set(key, route[key] as string)
  for (const [key, value] of Object.entries(route)) if (value && !params.has(key)) params.set(key, value)
  const query = params.toString()
  return query ? `${PREFIX}?${query}` : ''
}

/** 1 = glance (no track), 2 = one track's KPIs over iterations, 3 = evidence (an iteration or an item is open). */
export function routeLevel(route: Route): 1 | 2 | 3 {
  if (!route.track) return 1
  if (route.iteration || route.item) return 3
  return 2
}

const listeners = new Set<() => void>()
function notify(): void {
  for (const listener of listeners) listener()
}

/** Navigate: `push` (default) adds a Back step, `replace` changes place without one. */
export function navigate(route: Route, mode: 'push' | 'replace' = 'push'): void {
  const url = `${location.pathname}${location.search}${formatRoute(route)}`
  try {
    if (mode === 'push') history.pushState(history.state, '', url)
    else history.replaceState(history.state, '', url)
  } catch {
    location.hash = formatRoute(route)
  }
  notify()
}

/** The current route and a navigate function; re-renders on Back/Forward and on any navigate(). */
export function useRoute(): [Route, (route: Route, mode?: 'push' | 'replace') => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute(location.hash))
  useEffect(() => {
    const sync = () => setRoute(parseRoute(location.hash))
    listeners.add(sync)
    window.addEventListener('popstate', sync)
    window.addEventListener('hashchange', sync)
    return () => {
      listeners.delete(sync)
      window.removeEventListener('popstate', sync)
      window.removeEventListener('hashchange', sync)
    }
  }, [])
  const go = useCallback((next: Route, mode: 'push' | 'replace' = 'push') => navigate(next, mode), [])
  return [route, go]
}
