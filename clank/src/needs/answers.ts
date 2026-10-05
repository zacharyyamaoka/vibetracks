// Zach's draft answers, one localStorage entry per track + item, so a half-answered page survives a reload.
// WHY localStorage and not a backend write: the backend is read-only by contract (mounts are GET only), and the
// answer's real destination is the loop's own channel, reached by Copy answers. Every access is try/catch wrapped:
// storage often fails on Clank/file origins, and the page must still work for this session.
// The rules (fingerprint binding, live vs stale, offered choices, what a note alone means) live in answerRules.ts,
// shared with the exporter; this file is the store every proposal N1-N6 reads through.

import { useCallback, useMemo, useState } from 'react'
import type { NeedsDoc, NeedsItem } from './types'
import { boundDraft, draftState, isAnswerable, parseStoredDraft, type AnswerDraft, type StaleDraft } from './answerRules'

export * from './answerRules'

const PREFIX = 'vibetracks.needs.answer'

export function answerKey(track: string, localId: string): string {
  return `${PREFIX}:${track}:${localId}`
}

function read(track: string, localId: string): AnswerDraft | null {
  try {
    return parseStoredDraft(window.localStorage.getItem(answerKey(track, localId)))
  } catch {
    return null
  }
}

function write(track: string, localId: string, draft: AnswerDraft | null): void {
  try {
    if (draft === null) window.localStorage.removeItem(answerKey(track, localId))
    else {
      // The transient flag is never stored: it is recomputed from the item on every read.
      const { offersOther: _transient, ...stored } = draft
      window.localStorage.setItem(answerKey(track, localId), JSON.stringify(stored))
    }
  } catch {
    // Blocked storage: the draft lives in memory for this page; Copy answers still works.
  }
}

export interface AnswerStore {
  /** The LIVE draft only: bound to the question as it reads now, on an item that is still open, with a choice the
   * item offers. A stale draft reads as null here (never shown as answered); see stale(). */
  get(track: string, localId: string): AnswerDraft | null
  /** The draft Zach must reconfirm or discard before it counts, or null. */
  stale(track: string, localId: string): StaleDraft | null
  /** The stored draft as saved, live or stale. Pass this to exportAnswers so Copy can NAME what it leaves out. */
  stored(track: string, localId: string): AnswerDraft | null
  /** Merge a change into the live draft and bind it to the question as it reads now; `{choice: null, note: ''}`
   * clears the entry. A choice the item does not offer is never recorded, and an item that is not open (or not in
   * the shown docs) takes no draft. A change to an item with a stale draft starts a NEW draft: the stale one's words
   * are not carried into it, because Zach has not reconfirmed them. */
  set(track: string, localId: string, change: Partial<Pick<AnswerDraft, 'choice' | 'note'>>): void
  /** Re-bind a stale draft to the question as it reads now (Zach read it again and keeps his answer). */
  reconfirm(track: string, localId: string): void
  clear(track: string, localId?: string, localIds?: string[]): void
  /** Bumps on every change, for effects that depend on the drafts. */
  version: number
}

function itemKey(track: string, localId: string): string {
  return `${track}\u0000${localId}`
}

/** `<track>\0<local_id>` -> the item, for every item in `docs`. */
export function itemIndex(docs: NeedsDoc[]): Map<string, NeedsItem> {
  const map = new Map<string, NeedsItem>()
  for (const doc of docs) for (const item of doc.items) map.set(itemKey(doc.track, item.local_id), item)
  return map
}

/**
 * The drafts for the items in `docs`. Pass the docs the page shows: every read and write is checked against them.
 *
 * WHY the rule lives here and not per proposal: drafts are shared by N1-N6 and outlive builds; a rule in one proposal
 * (N6 once filtered unoffered choices with its own wrapper) leaves the other five showing and copying what it hides.
 * WHY an item not in the docs reads as null: nothing can say what such a draft answered, and nothing renders it.
 */
export function useAnswerStore(docs: NeedsDoc[] = []): AnswerStore {
  const [cache] = useState(() => new Map<string, AnswerDraft | null>())
  const [version, setVersion] = useState(0)
  const items = useMemo(() => itemIndex(docs), [docs])
  const stored = useCallback(
    (track: string, localId: string) => {
      const key = answerKey(track, localId)
      if (!cache.has(key)) cache.set(key, read(track, localId))
      return cache.get(key) ?? null
    },
    [cache],
  )
  const save = useCallback(
    (track: string, localId: string, draft: AnswerDraft | null) => {
      cache.set(answerKey(track, localId), draft)
      write(track, localId, draft)
      setVersion((n) => n + 1)
    },
    [cache],
  )
  const get = useCallback(
    (track: string, localId: string) => {
      const item = items.get(itemKey(track, localId))
      return item ? draftState(stored(track, localId), item).live : null
    },
    [stored, items],
  )
  const stale = useCallback(
    (track: string, localId: string) => {
      const item = items.get(itemKey(track, localId))
      return item ? draftState(stored(track, localId), item).stale : null
    },
    [stored, items],
  )
  const set = useCallback(
    (track: string, localId: string, change: Partial<Pick<AnswerDraft, 'choice' | 'note'>>) => {
      const item = items.get(itemKey(track, localId))
      if (!item || !isAnswerable(item)) return
      const keys = new Set(item.options.map((option) => option.key))
      // The live draft as the item can take it, so a note typed under a stale choice never re-saves that choice.
      const previous = draftState(stored(track, localId), item).live
      let choice = change.choice === undefined ? (previous?.choice ?? null) : change.choice
      if (choice && !keys.has(choice)) choice = previous?.choice ?? null
      const note = change.note === undefined ? (previous?.note ?? '') : change.note
      save(track, localId, !choice && !note ? null : boundDraft(item, choice, note))
    },
    [stored, items, save],
  )
  const reconfirm = useCallback(
    (track: string, localId: string) => {
      const item = items.get(itemKey(track, localId))
      const current = item ? draftState(stored(track, localId), item).stale : null
      if (!item || !current || !current.reconfirmable) return
      save(track, localId, boundDraft(item, current.draft.choice, current.draft.note))
    },
    [stored, items, save],
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
  return useMemo(() => ({ get, stale, stored, set, reconfirm, clear, version }), [get, stale, stored, set, reconfirm, clear, version])
}
