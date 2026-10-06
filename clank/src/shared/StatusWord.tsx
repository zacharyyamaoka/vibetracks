// A calm status: a dot plus a word, with an optional grey detail line under it.
// WHY colour only for warn/risk/stale (calm.css .vt-tone-*): ok and muted are the normal state and stay grey, so
// colour on the page always means "look here" (BRIEF, research principle 11).

import type { Status, Tone } from './model'
import { toneClass } from './model'

export interface StatusWordProps {
  status?: Status | null
  /** Overrides status.word / status.tone. */
  word?: string
  tone?: Tone
  /** A grey second line (e.g. "disk 90.36% · stop line 91.0%"). */
  detail?: string | null
  /** Hide the dot (inline use inside a sentence). */
  bare?: boolean
  title?: string
  className?: string
}

export function StatusWord({ status, word, tone, detail, bare, title, className }: StatusWordProps) {
  const text = word ?? status?.word ?? ''
  const resolved: Tone = tone ?? status?.tone ?? 'muted'
  const main = (
    <span className={`vt-status ${toneClass(resolved)} ${className ?? ''}`} data-tone={resolved} title={title}>
      {bare ? null : <span className="vt-dot" aria-hidden="true" />}
      <span className="vt-word">{text}</span>
    </span>
  )
  if (!detail) return main
  return (
    <span className="vt-status-stack">
      {main}
      <small>{detail}</small>
    </span>
  )
}
