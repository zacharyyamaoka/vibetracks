// The contract every "Needs you" proposal (n1..n5) implements. A proposal owns ONLY its own folder.

import type { ComponentType } from 'react'
import type { PluginBackend } from '@clank/api'
import type { Projection } from '../shared/model'
import type { Route } from '../shared/route'
import type { AnswerStore } from './answers'
import type { NeedsDoc } from './types'

export interface NeedsProposalProps {
  /** The track in the route (`#vt?track=kinsim&needs=1`), or null for every track (`#vt?needs=1`). */
  track: string | null
  /** `[doc]` for one track, every track's doc otherwise. Items arrive sorted: blocking, no default, by when the default fires. */
  docs: NeedsDoc[]
  /** The one track's doc, when a track is routed. */
  doc: NeedsDoc | null
  loading: boolean
  error: string | null
  /** Re-read the loops' live files. */
  reload(): void
  /** Draft answers, persisted per track + item; pass to <CopyOut answers>. Render <StaleDraftNotice> in every card's
   * answer area: get() hides a stale draft, and only the notice tells Zach it exists. */
  answers: AnswerStore
  /** The settings page's "Include questions whose default is already in effect" (shared/settings.ts). A lane that
   * queues only what wants Zach adds the defaulting ones when this is on. WHY a setting and not a page button
   * (Codex audit 2026-10-04, finding 13): it changes what the queue shows, a view option, and view options live only on
   * the settings page. */
  includeDefaulting: boolean
  /** Open the dashboard's settings page (the plain-text pointer beside a count of items this view leaves out). */
  openSettings(): void
  backend: PluginBackend
  /** The dashboard projection when loaded (for <EvidenceLink projection>); may be null. */
  projection: Projection | null
  route: Route
  navigate(route: Route, mode?: 'push' | 'replace'): void
  /** Leave the needs page: steps Back when the dashboard pushed it, else drops `needs` from the route. */
  onBack(): void
}

export interface NeedsProposalDefinition {
  key: string
  /** N1..N5 */
  short: string
  name: string
  component: ComponentType<NeedsProposalProps>
}
