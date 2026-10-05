// The "Needs you" page's shell: loads /needs for the routed track (or all), keeps the draft answers, and renders the
// chosen proposal N1..N6. Route: `#vt?track=kinsim&needs=1` (any A/B/C variant; Dashboard.tsx checks `needs=1`).
// WHY a chooser of its own in the A · B · C switcher's corner: they choose different things (the needs page vs the
// dashboard layout), and A · B · C has no effect on this page, so Dashboard.tsx hides it here and this one pill
// takes its place.
// WHY the chooser is in the app and remembered: Zach's prototype-switch rule (a drop-down bottom-right, live,
// remembers the choice), the same as the A · B · C switcher.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PluginBackend } from '@clank/api'
import type { Projection } from '../shared/model'
import { parseRoute, type Route } from '../shared/route'
import { useNeeds } from './api'
import { useAnswerStore } from './answers'
import type { NeedsProposalDefinition } from './proposal'
import N1, { NAME as NAME_1 } from './n1'
import N2, { NAME as NAME_2 } from './n2'
import N3, { NAME as NAME_3 } from './n3'
import N4, { NAME as NAME_4 } from './n4'
import N5, { NAME as NAME_5 } from './n5'
import N6, { NAME as NAME_6 } from './n6'
import './needs.css'

export const NEEDS_PROPOSALS: NeedsProposalDefinition[] = [
  { key: 'n1', short: 'N1', name: NAME_1, component: N1 },
  { key: 'n2', short: 'N2', name: NAME_2, component: N2 },
  { key: 'n3', short: 'N3', name: NAME_3, component: N3 },
  { key: 'n4', short: 'N4', name: NAME_4, component: N4 },
  { key: 'n5', short: 'N5', name: NAME_5, component: N5 },
  { key: 'n6', short: 'N6', name: NAME_6, component: N6 },
]

// WHY N6 is the default for a viewer who never chose: both judges ranked the N1 lane + N2 context splice first, so a
// first visit lands on it; a stored choice still wins (the chooser remembers what Zach picked).
const DEFAULT_PROPOSAL = 'n6'

const STORAGE_KEY = 'vibetracks.dashboard.needsProposal'

function readStored(): string {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return NEEDS_PROPOSALS.some((proposal) => proposal.key === value) ? (value as string) : DEFAULT_PROPOSAL
  } catch {
    return DEFAULT_PROPOSAL
  }
}

function store(key: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, key)
  } catch {
    // Blocked storage: the choice holds for this page.
  }
}

// Route keys that belong to the needs page alone: `needs` itself and each proposal's private place (N1 `zen`/`zq`,
// N2 `ask`, N4 `n4card`, N5 `n5`, N6 anything starting `n6`). WHY the shell strips them and not each proposal: a key
// that leaks into the dashboard route survives the next needs visit and reopens a stale card; one seam here covers
// every proposal, including ones added later under an `n<k>` prefix.
const NEEDS_ONLY_KEYS = new Set(['needs', 'zen', 'zq', 'ask', 'n4card', 'n5'])

function isNeedsOnlyKey(key: string): boolean {
  return NEEDS_ONLY_KEYS.has(key) || /^n\d/.test(key)
}

/** The route with every needs-page key dropped: where leaving the needs page lands. */
export function withoutNeeds(route: Route): Route {
  const out: Route = {}
  for (const [key, value] of Object.entries(route)) if (value && !isNeedsOnlyKey(key)) out[key] = value
  return out
}

function hasNeedsOnlyKeys(route: Route): boolean {
  return Object.keys(route).some(isNeedsOnlyKey)
}

// WHY a mark in history.state for "the dashboard pushed this needs entry": Back then steps the history back to exactly
// where Zach was (the home table, a track page, a scrolled level); a needs page reached by reload or a pasted link has
// nothing of ours behind it, so Back drops the needs keys from the route instead of leaving the dashboard. The mark
// lives in the history entry (not only in memory) so it survives the shell unmounting under the settings page.
const ENTRY_MARK = 'vtNeedsEntry'
let pushedNeeds = false

function markedEntry(): boolean {
  const state = history.state as unknown
  return Boolean(state && typeof state === 'object' && (state as Record<string, unknown>)[ENTRY_MARK])
}

/** Open the needs page from anywhere in the dashboard (a home-table cell, a track page). `track` null = all tracks. */
export function openNeeds(navigate: (route: Route, mode?: 'push' | 'replace') => void, route: Route, track: string | null): void {
  pushedNeeds = true
  const next: Route = { ...withoutNeeds(route), needs: '1' }
  if (track) next.track = track
  else delete next.track
  navigate(next, 'push')
  const state = history.state as unknown
  if (state === null || state === undefined || (typeof state === 'object' && !Array.isArray(state))) {
    try {
      history.replaceState({ ...((state as Record<string, unknown> | null) ?? {}), [ENTRY_MARK]: true }, '', location.href)
    } catch {
      // The module flag still covers this session.
    }
  }
}

/** Step Back past every needs entry we pushed, then make sure no needs-only key is left in the landing route. */
function stepOutOfNeeds(navigate: (route: Route, mode?: 'push' | 'replace') => void): void {
  let guard = 0
  const onPop = () => {
    const landed = parseRoute(location.hash)
    // A proposal that pushed (instead of replacing) left more needs entries behind ours: keep stepping.
    if (landed.needs === '1' && markedEntry() && guard++ < 20) {
      history.back()
      return
    }
    window.removeEventListener('popstate', onPop)
    if (landed.needs === '1' || hasNeedsOnlyKeys(landed)) navigate(withoutNeeds(landed), 'replace')
  }
  window.addEventListener('popstate', onPop)
  history.back()
}

export interface NeedsShellProps {
  backend: PluginBackend
  route: Route
  navigate(route: Route, mode?: 'push' | 'replace'): void
  projection: Projection | null
}

export function NeedsShell({ backend, route, navigate, projection }: NeedsShellProps) {
  const track = route.track ?? null
  const needs = useNeeds(backend, track)
  const answers = useAnswerStore()
  const [key, setKey] = useState(readStored)
  const choose = useCallback((next: string) => {
    setKey(next)
    store(next)
  }, [])
  const onBack = useCallback(() => {
    if (markedEntry() || pushedNeeds) {
      pushedNeeds = false
      stepOutOfNeeds(navigate)
      return
    }
    navigate(withoutNeeds(route), 'replace')
  }, [navigate, route])
  // WHY proposals get a wrapped navigate: any move off the needs page (an evidence link to an item page, a breadcrumb)
  // must drop the proposal's private keys too, not only the Back button.
  const proposalNavigate = useCallback(
    (next: Route, mode?: 'push' | 'replace') => navigate(next.needs === '1' ? next : withoutNeeds(next), mode),
    [navigate],
  )
  const proposal = NEEDS_PROPOSALS.find((candidate) => candidate.key === key) ?? NEEDS_PROPOSALS[0]
  const Proposal = proposal.component
  return (
    <div className="vt-needs" data-testid="vt-needs" data-proposal={proposal.key}>
      <div className="vt-needs-back-row">
        <button type="button" className="vt-btn vt-muted vt-small" onClick={onBack} data-testid="vt-needs-back">
          ← Back
        </button>
      </div>
      <Proposal
        track={track}
        docs={needs.docs}
        doc={needs.doc}
        loading={needs.loading}
        error={needs.error}
        reload={needs.reload}
        answers={answers}
        backend={backend}
        projection={projection}
        route={route}
        navigate={proposalNavigate}
        onBack={onBack}
      />
      <ProposalChooser current={proposal} onChoose={choose} />
    </div>
  )
}

/** One compact pill ("N6 · Lane + context ▾") that opens the list of proposals upward.
 * WHY collapsed: the full row of six named buttons sat over the bottom-right of every needs page and covered answer
 * controls (N3's rig T2 recommendation hit-tested to the chooser). One pill is ~200-260px wide; the page's bottom
 * padding (needs.css) clears it at max scroll. */
function ProposalChooser({ current, onChoose }: { current: NeedsProposalDefinition; onChoose: (key: string) => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (event: PointerEvent) => {
      if (box.current && event.target instanceof Node && !box.current.contains(event.target)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setOpen(false)
    }
    window.addEventListener('pointerdown', onDown, true)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', onDown, true)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])
  const label = useMemo(() => labelOf(current), [current])
  return (
    <div ref={box} className="vt-switcher vt-needs-switcher" role="group" aria-label="Needs-you proposal" data-testid="vt-needs-switcher" data-open={open}>
      {open ? (
        <div className="vt-needs-switch-menu" role="menu" aria-label="Needs-you proposals">
          {NEEDS_PROPOSALS.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitemradio"
              className="vt-btn"
              aria-checked={item.key === current.key}
              aria-pressed={item.key === current.key}
              data-testid={`vt-needs-switch-${item.key}`}
              title={labelOf(item)}
              onClick={() => {
                onChoose(item.key)
                setOpen(false)
              }}
            >
              {labelOf(item)}
            </button>
          ))}
        </div>
      ) : null}
      <button
        type="button"
        className="vt-btn vt-needs-switch-pill"
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="vt-needs-switch-pill"
        title="Switch the Needs-you proposal"
        onClick={() => setOpen(!open)}
      >
        <span className="vt-switch-label">Needs you</span>
        {label}
        <span className="vt-needs-switch-caret" aria-hidden="true">
          {open ? '▴' : '▾'}
        </span>
      </button>
    </div>
  )
}

function labelOf(item: NeedsProposalDefinition): string {
  return item.name && item.name !== 'Placeholder' ? `${item.short} · ${item.name}` : item.short
}
