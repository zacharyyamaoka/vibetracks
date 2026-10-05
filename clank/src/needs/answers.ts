// Zach's draft answers, one localStorage entry per track + item, so a half-answered page survives a reload.
// WHY localStorage and not a backend write: the backend is read-only by contract (mounts are GET only), and the
// answer's real destination is the loop's own channel, reached by Copy answers. Every access is try/catch wrapped:
// storage often fails on Clank/file origins, and the page must still work for this session.

import { useCallback, useMemo, useState } from 'react'
import { CHOICES, type Choice } from './types'

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
  get(track: string, localId: string): AnswerDraft | null
  /** Merge a change; `{choice: null, note: ''}` with no other content clears the entry. */
  set(track: string, localId: string, change: Partial<Pick<AnswerDraft, 'choice' | 'note'>>): void
  clear(track: string, localId?: string, localIds?: string[]): void
  /** Bumps on every change, for effects that depend on the drafts. */
  version: number
}

export function useAnswerStore(): AnswerStore {
  const [cache] = useState(() => new Map<string, AnswerDraft | null>())
  const [version, setVersion] = useState(0)
  const get = useCallback(
    (track: string, localId: string) => {
      const key = answerKey(track, localId)
      if (!cache.has(key)) cache.set(key, read(track, localId))
      return cache.get(key) ?? null
    },
    [cache],
  )
  const set = useCallback(
    (track: string, localId: string, change: Partial<Pick<AnswerDraft, 'choice' | 'note'>>) => {
      const key = answerKey(track, localId)
      const previous = cache.has(key) ? cache.get(key) : read(track, localId)
      const next: AnswerDraft = { choice: previous?.choice ?? null, note: previous?.note ?? '', updated: new Date().toISOString(), ...change }
      const empty = !next.choice && !next.note
      cache.set(key, empty ? null : next)
      write(track, localId, empty ? null : next)
      setVersion((n) => n + 1)
    },
    [cache],
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
