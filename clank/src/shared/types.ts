// The contract between the shell (Dashboard.tsx) and a variant. A variant is one React component in
// src/variants/<x>/index.tsx that receives these props and renders all three levels.

import type { ReactNode } from 'react'
import type { PluginBackend } from '@clank/api'
import type { Projection } from './model'
import type { Route } from './route'
import type { DashboardSettings, SettingsUpdate } from './settings'
import type { RoadmapSettings } from '../roadmap'

export interface VariantProps {
  projection: Projection
  /** Media id -> same-origin URL (video src, iframe src, link href). */
  mediaUrl: (id: string) => string
  /** Where the reader is (URL hash), shared by all variants so the switcher keeps the selection. */
  route: Route
  /** Go to a place: 'push' adds a Back step (a deeper level), 'replace' moves sideways. */
  navigate: (route: Route, mode?: 'push' | 'replace') => void
  /** Re-read the projection; `{ rebuild: true }` reruns the adapter first. */
  reload: (options?: { rebuild?: boolean }) => void
  /** The .vtdash file's title ("Agent work"). */
  title: string
  backend: PluginBackend
  /** The reader's view options from the settings page (the header's gear). Read them; never add a toolbar control
   * for a view option — add an item to DASHBOARD_SETTINGS_SECTION instead (docs/dashboard/VARIANT-KIT.md). */
  settings: { dashboard: DashboardSettings; roadmap: RoadmapSettings }
  /** Merge a change into the saved settings: `setSettings({ dashboard: { xAxis: 'day' } })`. */
  setSettings: (update: SettingsUpdate) => void
}

export interface VariantDefinition {
  key: 'a' | 'b' | 'c'
  letter: 'A' | 'B' | 'C'
  name: string
  component: (props: VariantProps) => ReactNode
}
