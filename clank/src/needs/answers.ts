// Zach's draft answers, one localStorage entry per track + item, so a half-answered page survives a reload.
// WHY localStorage and not a backend write: the backend is read-only by contract (mounts are GET only), and the
// answer's real destination is the loop's own channel, reached by Copy answers. Every access is try/catch wrapped:
// storage often fails on Clank/file origins, and the page must still work for this session.

import { useCallback, useMemo, useState } from 'react'
import { CHOICES, type Choice, type NeedsDoc } from './types'

export interface AnswerDraft {
  /** null = no choice clicked yet; a note alone exports as `other`. */
  choice: Choice | null
  note: string
  /** ISO time of the last edit. */
  updated: string
}

const PREFIX = 'vibetracks.needs.answer'

export function answerKey(track: string, localId: string): string {
  return `${PREFIX}:${track}:${localId}`
}

function read(track: string, localId: string): AnswerDraft | null {
  try {
    const raw = window.localStorage.getItem(answerKey(track, localId))
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<AnswerDraft>
    // WHY CHOICES and not a hand list: grasping's `approve` was dropped on every reload by a list that predated it.
    const choice = (CHOICES as unknown[]).includes(value.choice) ? (value.choice as Choice) : null
    return { choice, note: typeof value.note === 'string' ? value.note : '', updated: typeof value.updated === 'string' ? value.updated : '' }
  } catch {
    return null
  }
}

function write(track: string, localId: string, draft: AnswerDraft | null): void {
  try {
    if (draft === null) window.localStorage.removeItem(answerKey(track, localId))
    else window.localStorage.setItem(answerKey(track, localId), JSON.stringify(draft))
  } catch {
    // Blocked storage: the draft lives in memory for this page; Copy answers still works.
  }
}

/** The choice an export carries: an explicit click wins; a note alone means `other`; nothing means unanswered. */
export function effectiveChoice(draft: AnswerDraft | null | undefined): Choice | null {
  if (!draft) return null
  if (draft.choice) return draft.choice
  return draft.note.trim() ? 'other' : null
}

/** A draft is exportable when it has a choice, and `other` carries a non-blank note (the note IS the answer). */
export function isComplete(draft: AnswerDraft | null | undefined): boolean {
  const choice = effectiveChoice(draft)
  if (!choice) return false
  return choice !== 'other' || Boolean(draft?.note.trim())
}

export interface AnswerStore {
  /** The draft as the item can take it: a stored choice the item does not offer is dropped (see offeredDraft). */
  get(track: string, localId: string): AnswerDraft | null
  /** Merge a change; `{choice: null, note: ''}` with no other content clears the entry. A choice the item does not
   * offer is never recorded. */
  set(track: string, localId: string, change: Partial<Pick<AnswerDraft, 'choice' | 'note'>>): void
  clear(track: string, localId?: string, localIds?: string[]): void
  /** Bumps on every change, for effects that depend on the drafts. */
  version: number
}

/** `<track>\0<local_id>` -> the option keys that item offers, for every item in `docs`. */
export type OfferedChoices = Map<string, Set<Choice>>

function offeredKey(track: string, localId: string): string {
  return `${track}\u0000${localId}`
}

export function offeredChoices(docs: NeedsDoc[]): OfferedChoices {
  const map: OfferedChoices = new Map()
  for (const doc of docs) for (const item of doc.items) map.set(offeredKey(doc.track, item.local_id), new Set(item.options.map((option) => option.key)))
  return map
}

/**
 * A stored draft as `offered` allows it: a choice the item does not offer is dropped; a note left behind stays only
 * where "something else" exists to carry it (a note alone exports as `other`); an item not in the loaded docs is left
 * as stored (nothing renders or exports it).
 *
 * WHY in the shared store and not per proposal: drafts are shared by N1-N6 and outlive builds, so a stale
 * `accept_recommendation` (an older build, a keypress before the guard, a loop that dropped its recommendation) sat on
 * grasping and detection items, which offer no recommendation. N2-N5 then showed "✓ recommendation" and N3-N5 copied
 * `accept_recommendation` out for an option that does not exist; only N6 filtered it, with its own wrapper. WHY a
 * read-side rule and not a cleanup sweep: a view must never rewrite what Zach saved behind his back; the next edit of
 * that item writes the cleaned draft.
 */
export function offeredDraft(draft: AnswerDraft | null, keys: Set<Choice> | undefined): AnswerDraft | null {
  if (!draft || !keys || !draft.choice || keys.has(draft.choice)) return draft
  return draft.note.trim() && keys.has('other') ? { ...draft, choice: null } : null
}

/** The drafts for the items in `docs`. Pass the docs the page shows: every get() and set() is checked against them. */
export function useAnswerStore(docs: NeedsDoc[] = []): AnswerStore {
  const [cache] = useState(() => new Map<string, AnswerDraft | null>())
  const [version, setVersion] = useState(0)
  const offered = useMemo(() => offeredChoices(docs), [docs])
  const stored = useCallback(
    (track: string, localId: string) => {
      const key = answerKey(track, localId)
      if (!cache.has(key)) cache.set(key, read(track, localId))
      return cache.get(key) ?? null
    },
    [cache],
  )
  const get = useCallback(
    (track: string, localId: string) => offeredDraft(stored(track, localId), offered.get(offeredKey(track, localId))),
    [stored, offered],
  )
  const set = useCallback(
    (track: string, localId: string, change: Partial<Pick<AnswerDraft, 'choice' | 'note'>>) => {
      const key = answerKey(track, localId)
      const keys = offered.get(offeredKey(track, localId))
      // The previous draft as the item can take it, so a note typed under a stale choice never re-saves that choice.
      const previous = offeredDraft(stored(track, localId), keys)
      const next: AnswerDraft = { choice: previous?.choice ?? null, note: previous?.note ?? '', updated: new Date().toISOString(), ...change }
      if (next.choice && keys && !keys.has(next.choice)) next.choice = previous?.choice ?? null
      const empty = !next.choice && !next.note
      cache.set(key, empty ? null : next)
      write(track, localId, empty ? null : next)
      setVersion((n) => n + 1)
    },
    [cache, stored, offered],
  )
  const clear = useCallback(
    (track: string, localId?: string, localIds?: string[]) => {
      const ids = localId ? [localId] : (localIds ?? [])
      for (const id of ids) {
        cache.set(answerKey(track, id), null)
        write(track, id, null)
      }
      setVersion((n) => n + 1)
    },
    [cache],
  )
  return useMemo(() => ({ get, set, clear, version }), [get, set, clear, version])
}
