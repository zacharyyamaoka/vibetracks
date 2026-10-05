// The "Needs you" page's shell: loads /needs for the routed track (or all), keeps the draft answers, and renders the
// chosen proposal N1..N5. Route: `#vt?track=kinsim&needs=1` (any A/B/C variant; Dashboard.tsx checks `needs=1`).
// WHY a chooser of its own, stacked ABOVE the A · B · C switcher: they choose different things (the needs page vs
// the dashboard layout) and both must stay reachable; side by side they would collide at narrow widths.
// WHY the chooser is in the app and remembered: Zach's prototype-switch rule (a drop-down bottom-right, live,
// remembers the choice), the same as the A · B · C switcher.

import { useCallback, useState } from 'react'
import type { PluginBackend } from '@clank/api'
import type { Projection } from '../shared/model'
import type { Route } from '../shared/route'
import { useNeeds } from './api'
import { useAnswerStore } from './answers'
import type { NeedsProposalDefinition } from './proposal'
import N1, { NAME as NAME_1 } from './n1'
import N2, { NAME as NAME_2 } from './n2'
import N3, { NAME as NAME_3 } from './n3'
import N4, { NAME as NAME_4 } from './n4'
import N5, { NAME as NAME_5 } from './n5'
import './needs.css'

export const NEEDS_PROPOSALS: NeedsProposalDefinition[] = [
  { key: 'n1', short: 'N1', name: NAME_1, component: N1 },
  { key: 'n2', short: 'N2', name: NAME_2, component: N2 },
  { key: 'n3', short: 'N3', name: NAME_3, component: N3 },
  { key: 'n4', short: 'N4', name: NAME_4, component: N4 },
  { key: 'n5', short: 'N5', name: NAME_5, component: N5 },
]

const STORAGE_KEY = 'vibetracks.dashboard.needsProposal'

function readStored(): string {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return NEEDS_PROPOSALS.some((proposal) => proposal.key === value) ? (value as string) : NEEDS_PROPOSALS[0].key
  } catch {
    return NEEDS_PROPOSALS[0].key
  }
}

function store(key: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, key)
  } catch {
    // Blocked storage: the choice holds for this page.
  }
}

// WHY a module flag for "we pushed the needs entry": Back then steps the history back to exactly where Zach was (the
// home table, a track page, a scrolled level); a needs page reached by reload or a pasted link has nothing of ours
// behind it, so Back drops `needs` from the route instead of leaving the dashboard.
let pushedNeeds = false

/** Open the needs page from anywhere in the dashboard (a home-table cell, a track page). `track` null = all tracks. */
export function openNeeds(navigate: (route: Route, mode?: 'push' | 'replace') => void, route: Route, track: string | null): void {
  pushedNeeds = true
  const next: Route = { ...route, needs: '1' }
  if (track) next.track = track
  else delete next.track
  navigate(next, 'push')
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
    if (pushedNeeds) {
      pushedNeeds = false
      history.back()
      return
    }
    const rest: Route = { ...route }
    delete rest.needs
    navigate(rest, 'replace')
  }, [navigate, route])
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
        navigate={navigate}
        onBack={onBack}
      />
      <div className="vt-switcher vt-needs-switcher" role="group" aria-label="Needs-you proposal" data-testid="vt-needs-switcher">
        <span className="vt-switch-label">Needs you</span>
        {NEEDS_PROPOSALS.map((item) => (
          <button
            key={item.key}
            type="button"
            className="vt-btn"
            aria-pressed={item.key === proposal.key}
            data-testid={`vt-needs-switch-${item.key}`}
            title={`${item.short} · ${item.name}`}
            onClick={() => choose(item.key)}
          >
            {item.short}
            {item.name && item.name !== 'Placeholder' ? ` · ${item.name}` : ''}
          </button>
        ))}
      </div>
    </div>
  )
}
