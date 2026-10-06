// The widget's controlled state. The dashboard keeps it in its URL hash under `rm` (JSON) and owns its history, so the
// widget keeps none: it reads this, fills defaults for what is missing or unrecognised, and reports every change
// through onState. WHY no history of its own (replacing the kinsim dashboard's navigation.ts): one Back stack for the
// whole dashboard, and the hash already is one.

import type { Lens, Orient } from './graph'

/** The widget's controlled state, kept by the variant in the URL hash under `rm`. `tab` and `trail` are the focus
 * card's tab and its breadcrumb; pass the whole object back so Back restores them too. */
export interface RoadmapWidgetState {
  lens?: string
  orient?: string
  card?: string
  sel?: string | null
  tab?: string
  trail?: string[]
}

export type CardSize = 'compact' | 'rich'
export type FocusTab = 'proof' | 'lineage' | 'details'

export interface RoadView {
  lens: Lens
  orient: Orient
  card: CardSize
  sel: string | null
  tab: FocusTab
  trail: string[]
}

const LENSES: Lens[] = ['ladder', 'depth', 'board', 'waves']
const TABS: FocusTab[] = ['proof', 'lineage', 'details']

/** The state with defaults (Ladder, →, Compact, nothing picked, Proof). A picked rung the model does not hold is
 * dropped, the trail keeps only rungs it holds, and Waves falls back to Depth when no rung has a wave. */
export function resolveView(state: RoadmapWidgetState | null | undefined, has: (id: string) => boolean, hasWaves: boolean): RoadView {
  const value = state ?? {}
  let lens: Lens = LENSES.includes(value.lens as Lens) ? (value.lens as Lens) : 'ladder'
  if (lens === 'waves' && !hasWaves) lens = 'depth'
  const sel = typeof value.sel === 'string' && has(value.sel) ? value.sel : null
  return {
    lens,
    orient: value.orient === 'td' ? 'td' : 'lr',
    card: value.card === 'rich' ? 'rich' : 'compact',
    sel,
    tab: TABS.includes(value.tab as FocusTab) ? (value.tab as FocusTab) : 'proof',
    trail: sel && Array.isArray(value.trail) ? value.trail.filter((id): id is string => typeof id === 'string' && has(id)).slice(-8) : [],
  }
}
