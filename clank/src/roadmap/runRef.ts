// What a proof row's run button opens (Codex V11): that run's own recorded evidence file at its recorded line, never
// the rung's latest run. The "see the latest run" action is separate (FocusPanel's ProofTab, onOpenRung).

import type { RoadmapEvidence } from './doc'

export function runRef(item: Pick<RoadmapEvidence, 'abs' | 'line'>): { path: string; line?: number } | null {
  // WHY absolute only: the dashboard's file view takes an absolute path; a relative one or an unresolved link
  // (abs null, why_unresolved set) has nothing to open, and the row says so instead of opening something else.
  if (typeof item.abs !== 'string' || !item.abs.startsWith('/')) return null
  return item.line ? { path: item.abs, line: item.line } : { path: item.abs }
}
