// STUB — owned by the roadmap session after the skeleton commit; keep these signatures.
//
// The roadmap is one widget inside the dashboard (docs/dashboard/VARIANTS.md, "Roadmap widget slot"): every variant
// places <RoadmapWidget> at L2 under its KPI view, as a quiet collapsed "Roadmap" section (closed = density 'calm',
// expanded = 'full'). Its state lives in the URL hash under `rm` (JSON) and is controlled by the variant; its view
// options live on the dashboard's settings page (ROADMAP_SETTINGS_SECTION), never in a toolbar.
// The shell reads this folder from Dashboard.tsx (runtime) and shared/types.ts (types only, erased), and the shared
// settings code is generic over sections, so the real widget may import ../shared without making a module cycle.

import type { JSX } from 'react'
import type { SettingsSection } from '@clank/api'

/** The widget's controlled state, kept by the variant in the URL hash under `rm`. */
export interface RoadmapWidgetState {
  lens?: string
  orient?: string
  card?: string
  sel?: string | null
}

/** The roadmap's view options (the settings page's Roadmap section). Empty until the roadmap session adds items. */
export type RoadmapSettings = Record<string, boolean | number | string>

export interface RoadmapWidgetProps {
  /** The track whose roadmap to show (`kinsim`, `rig`, ...). */
  track: string
  /** The roadmap document from useRoadmap; null while loading or when the track has none. */
  doc: unknown | null
  state: RoadmapWidgetState
  onState: (next: RoadmapWidgetState) => void
  /** Go to L3 evidence for that rung's latest judged run (or a rung note if none). */
  onOpenRung: (rungId: string) => void
  /** Go to the L3 file view at that path (and line). */
  onOpenEvidence: (ref: { path: string; line?: number }) => void
  /** 'calm' while the section is closed, 'full' when the reader expands it. */
  density: 'calm' | 'full'
  settings: RoadmapSettings
}

export interface RoadmapDocState {
  doc: unknown | null
  loading: boolean
  error: string | null
  /** Forces a server-side re-projection; the dashboard's own reload calls it so one refresh covers the page. */
  reload: () => void
}

const noReload = (): void => {}

export function RoadmapWidget(_props: RoadmapWidgetProps): JSX.Element {
  return (
    <p className="vt-faint vt-small" data-testid="vt-roadmap-stub">
      Roadmap widget pending (roadmap session)
    </p>
  )
}

/** Loads one track's roadmap document through the plugin backend (the `/roadmap` mount, backend/mounts.py). */
export function useRoadmap(_backend: unknown, _track: string): RoadmapDocState {
  return { doc: null, loading: false, error: null, reload: noReload }
}

/** The Roadmap section of the dashboard's settings page, in Clank's SettingsSection shape. */
export const ROADMAP_SETTINGS_SECTION: SettingsSection = { id: 'roadmap', title: 'Roadmap', items: [] }

export const defaultRoadmapSettings: RoadmapSettings = {}
