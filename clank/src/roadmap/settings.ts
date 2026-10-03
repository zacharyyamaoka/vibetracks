// The roadmap's settings: preferences about how the board is drawn, as opposed to navigation state (lens, picked rung),
// which the dashboard keeps in its URL hash. Declared as a Clank settings section; the dashboard's settings page renders
// it (shared/SettingsView.tsx) and hands its values to the widget as `settings`, keyed by item key (shared/settings.ts).
//
// WHY a declarative section the dashboard renders itself (Zach, Oct 3: "it's important that the tool bar is actually
// usable. This line setting should instead be in a settings page, so that eventually, when you deploy in a Clank
// workbench or something else, you can put access to it in the plugin settings page"): Clank's plugin API can register
// a section, but it has no reader a plugin can call to get the stored value back, so the dashboard renders this same
// section in its own settings view for now. Registering it with Clank's page is the follow-up once Clank exposes a
// reader; the section is already in the shape `registerSettings` takes, so it moves over unchanged.

import type { SettingsSection } from '@clank/api'

/** The roadmap's view options (the settings page's Roadmap section), keyed by item key. */
export type RoadmapSettings = Record<string, boolean | number | string>

export type EdgeStyle = 'curve' | 'elbow'

export const defaultRoadmapSettings: RoadmapSettings = { edges: 'curve' }

export const ROADMAP_SETTINGS_SECTION: SettingsSection = {
  id: 'roadmap',
  title: 'Roadmap',
  items: [
    {
      key: 'edges',
      title: 'Lines',
      description: 'How dependency lines are drawn on the roadmap',
      type: 'enum',
      default: 'curve',
      options: [{ value: 'curve', label: 'Curved' }, { value: 'elbow', label: 'Elbow' }],
      scope: 'app',
    },
  ],
}

/** The edge style in `settings`; anything missing or unrecognised falls back to the default (curved). */
export function edgeStyle(settings: RoadmapSettings | null | undefined): EdgeStyle {
  const value = settings?.edges
  return value === 'curve' || value === 'elbow' ? value : 'curve'
}
