// Renaming a work track, like renaming a chat (Zach, 2026-10-04: "internally keep an ID that doesn't change, but it's
// nice being able to rename the work track, just like I can rename a chat session").
//   - Double-click the name (home row or track page title), press F2 on it, or use "Rename track…" in its ⋯ menu.
//   - Enter or clicking away saves; Esc cancels. An unchanged name saves nothing.
//   - The save is POST /tracks/<id>/title {title, revision} (docs/dashboard/ADAPTERS.md "Renaming a track"): only the
//     note's vibe-title changes; the id, every URL and the roadmap key stay the same.
//   - The title goes out exactly as typed (no trim): the server validates it and its message shows inline.
//   - The revision is the one on screen when editing STARTED (renameFence.ts): a projection that refreshes mid-edit
//     never moves it, so another writer's change makes the save 409 instead of being overwritten silently.
//   - Optimistic: the new name shows at once and rolls back if the save fails. A 409 keeps the edit open with the
//     reader's text, shows the other title, and offers "Use theirs" or "Save mine anyway"; only that explicit choice
//     re-fences, on the revision the other title was read at.
// WHY only tracks with a registry revision: a deployment (can12) has no note of its own to rename, so it offers nothing
// rather than a control that cannot work (G2, no fake controls).

import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import type { PluginBackend } from '@clank/api'
import type { Projection, Track } from '../../shared'
import { trackById } from '../../shared'
import { registryOf } from './live'
import * as fence from './renameFence'

interface Override {
  title: string
  pending: boolean
  /** The note revision our own save produced (absent while pending): the fence for an edit started before the
   * projection has re-read the note, so a quick second rename does not 409 against our own first one. */
  revision?: string
}

export interface RenameNotice {
  track: string
  text: string
  tone: 'muted' | 'risk'
}

export interface RenameConflict {
  track: string
  /** The other writer's title and revision, once the projection has re-read the note; null while it is reading. */
  theirs: fence.Theirs | null
  /** The other change left the name as it was when this edit started (it touched something else in the note). */
  sameName: boolean
  useTheirs: () => void
  saveMine: () => void
}

export interface Renamer {
  titleOf: (track: Track) => string
  canRename: (track: Track) => boolean
  pending: (trackId: string) => boolean
  editing: string | null
  draft: string
  setDraft: (value: string) => void
  start: (track: Track) => void
  cancel: () => void
  submit: (track: Track) => void
  /** Clicking away: saves, except in a conflict or on a draft the server just refused (renameFence.onBlur). */
  blur: (track: Track) => void
  notice: RenameNotice | null
  conflict: RenameConflict | null
}

export function useRenamer(backend: PluginBackend, projection: Projection, reload: () => void): Renamer {
  const [overrides, setOverrides] = useState<Record<string, Override>>({})
  const [session, setSession] = useState<fence.Session | null>(null)

  // WHY drop settled overrides on every new projection: once the backend has been re-read, the projection is the
  // truth; an override only bridges the gap between a save and that re-read.
  useEffect(() => {
    setOverrides((current) => {
      const kept = Object.fromEntries(Object.entries(current).filter(([, value]) => value.pending))
      return Object.keys(kept).length === Object.keys(current).length ? current : kept
    })
  }, [projection])

  const titleOf = useCallback((track: Track) => overrides[track.id]?.title ?? track.title, [overrides])
  const canRename = useCallback((track: Track) => Boolean(registryOf(track)?.revision), [])
  const pending = useCallback((trackId: string) => Boolean(overrides[trackId]?.pending), [overrides])

  const start = useCallback(
    (track: Track) => {
      const revision = registryOf(track)?.revision
      const override = overrides[track.id]
      // WHY not while our own save is in flight: its new revision is not known yet, so any fence chosen now is stale.
      if (!revision || override?.pending) return
      setSession(fence.begin(track.id, override?.title ?? track.title, override?.revision ?? revision))
    },
    [overrides],
  )
  const cancel = useCallback(() => setSession(null), [])
  const setDraft = useCallback((value: string) => setSession((current) => (current ? fence.edited(current, value) : current)), [])

  const send = useCallback(
    (track: Track, sent: fence.Session) => {
      const body = fence.request(sent)
      if (!body) {
        setSession(null)
        return
      }
      const previous = overrides[track.id]
      const rollback = () =>
        setOverrides((current) => {
          const next = { ...current }
          if (previous) next[track.id] = previous
          else delete next[track.id]
          return next
        })
      setOverrides((current) => ({ ...current, [track.id]: { title: body.title, pending: true } }))
      setSession(null)
      backend
        .fetch(`/tracks/${encodeURIComponent(track.id)}/title`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        .then(async (response) => {
          const answer = (await response.json().catch(() => null)) as { title?: unknown; error?: unknown; revision?: unknown } | null
          if (response.ok) {
            const saved = typeof answer?.title === 'string' ? answer.title : body.title
            const revision = typeof answer?.revision === 'string' ? answer.revision : undefined
            setOverrides((current) => ({ ...current, [track.id]: { title: saved, pending: false, revision } }))
            reload()
            return
          }
          rollback()
          if (response.status === 409) {
            // The draft and its original fence come back as they were; the projection re-read supplies their title.
            setSession(fence.conflicted(sent, typeof answer?.revision === 'string' ? answer.revision : null))
            reload()
            return
          }
          setSession(fence.failed(sent, typeof answer?.error === 'string' ? answer.error : `HTTP ${response.status}`))
        })
        .catch((error: unknown) => {
          rollback()
          setSession(fence.failed(sent, error instanceof Error ? error.message : String(error)))
        })
    },
    [backend, overrides, reload],
  )

  const submit = useCallback(
    (track: Track) => {
      if (!session || session.trackId !== track.id) return
      // WHY Enter does nothing in a conflict: only "Save mine anyway" may write over the other title.
      if (session.phase.kind === 'conflict') return
      send(track, session)
    },
    [send, session],
  )
  const blur = useCallback(
    (track: Track) => {
      if (!session || session.trackId !== track.id) return
      if (fence.onBlur(session) === 'submit') send(track, session)
    },
    [send, session],
  )

  const editing = session?.trackId ?? null
  const editedTrack = editing ? trackById(projection, editing) : null
  let conflict: RenameConflict | null = null
  if (session && session.phase.kind === 'conflict' && editedTrack) {
    const theirs = fence.theirsOf(session, editedTrack.title, registryOf(editedTrack)?.revision ?? null)
    conflict = {
      track: session.trackId,
      theirs,
      sameName: Boolean(theirs && theirs.title === session.base.title),
      useTheirs: () => setSession(null),
      saveMine: () => {
        if (theirs) send(editedTrack, fence.saveMineAnyway(session, theirs))
      },
    }
  }
  let notice: RenameNotice | null = null
  if (session?.phase.kind === 'failed') notice = { track: session.trackId, text: `Not renamed: ${session.phase.message}`, tone: 'risk' }

  return { titleOf, canRename, pending, editing, draft: session?.draft ?? '', setDraft, start, cancel, submit, blur, notice, conflict }
}

/** The track's name: plain text, or the inline editor while it is being renamed. `onOpen` makes a single click open
 * the track (the home row); a double click renames instead. */
export function TrackName({ track, renamer, onOpen, className }: {
  track: Track
  renamer: Renamer
  onOpen?: () => void
  className?: string
}) {
  const timer = useRef<number | null>(null)
  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current)
  }, [])
  const title = renamer.titleOf(track)
  const renamable = renamer.canRename(track)
  const editing = renamer.editing === track.id
  const notice = renamer.notice && renamer.notice.track === track.id ? renamer.notice : null

  if (editing) return <NameEditor track={track} renamer={renamer} notice={notice} className={className} />

  const rename = (event: MouseEvent) => {
    if (!renamable) return
    event.preventDefault()
    event.stopPropagation()
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
    renamer.start(track)
  }
  const keys = (event: KeyboardEvent) => {
    if (event.key === 'F2' && renamable) {
      event.preventDefault()
      event.stopPropagation()
      renamer.start(track)
    }
  }
  const pendingClass = renamer.pending(track.id) ? ' vt-a-saving' : ''
  const hint = renamable ? 'Double-click to rename' : undefined
  if (onOpen) {
    return (
      <>
        <button
          type="button"
          className={`vt-btn vt-a-name${pendingClass}${className ? ` ${className}` : ''}`}
          data-testid="vt-a-track-name"
          title={hint ? `${title} · ${hint.toLowerCase()}` : title}
          onKeyDown={keys}
          onClick={(event) => {
            event.stopPropagation()
            // WHY a short wait on a mouse click: the first click of a double click must not leave the page before the
            // second one can rename. Keyboard activation (detail 0) opens at once.
            if (event.detail === 0 || !renamable) return onOpen()
            if (event.detail > 1) return
            if (timer.current !== null) window.clearTimeout(timer.current)
            timer.current = window.setTimeout(() => {
              timer.current = null
              onOpen()
            }, 240)
          }}
          onDoubleClick={rename}
        >
          {title}
        </button>
        {notice ? <NoticeLine notice={notice} /> : null}
      </>
    )
  }
  return (
    <>
      <span
        className={`vt-a-title-text${pendingClass}${className ? ` ${className}` : ''}`}
        data-testid="vt-a-track-name"
        title={hint}
        tabIndex={renamable ? 0 : undefined}
        onKeyDown={keys}
        onDoubleClick={rename}
      >
        {title}
      </span>
      {notice ? <NoticeLine notice={notice} /> : null}
    </>
  )
}

function NoticeLine({ notice }: { notice: RenameNotice }) {
  return (
    <span className={`vt-a-rename-notice vt-small ${notice.tone === 'risk' ? 'vt-tone-risk' : 'vt-faint'}`} role="status" data-testid="vt-a-rename-notice">
      {notice.text}
    </span>
  )
}

function NameEditor({ track, renamer, notice, className }: { track: Track; renamer: Renamer; notice: RenameNotice | null; className?: string }) {
  const input = useRef<HTMLInputElement>(null)
  // WHY a settled flag: Enter or Esc ends the edit, and the blur that follows the input's removal must not save again.
  const settled = useRef(false)
  useEffect(() => {
    settled.current = false
    input.current?.focus()
    input.current?.select()
  }, [])
  const stop = (event: MouseEvent) => event.stopPropagation()
  const conflict = renamer.conflict && renamer.conflict.track === track.id ? renamer.conflict : null
  // WHY mousedown preventDefault on the choice buttons: the input keeps focus, so no blur races the click.
  const keepFocus = (event: MouseEvent) => event.preventDefault()
  return (
    <span className="vt-a-rename" onClick={stop} onDoubleClick={stop} onMouseDown={stop}>
      <input
        ref={input}
        className={`vt-a-rename-input${className ? ` ${className}` : ''}`}
        data-testid="vt-a-rename-input"
        aria-label={`Rename ${track.title}`}
        value={renamer.draft}
        spellCheck={false}
        size={Math.max(12, Math.min(48, renamer.draft.length + 2))}
        onChange={(event) => {
          settled.current = false
          renamer.setDraft(event.target.value)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            if (conflict) return
            settled.current = true
            renamer.submit(track)
          } else if (event.key === 'Escape') {
            event.preventDefault()
            event.stopPropagation()
            settled.current = true
            renamer.cancel()
          }
        }}
        onBlur={() => {
          if (settled.current) return
          renamer.blur(track)
        }}
      />
      {conflict ? (
        <span className="vt-a-rename-conflict vt-small" role="status" data-testid="vt-a-rename-conflict">
          {conflict.theirs ? (
            <>
              <span className="vt-muted" data-testid="vt-a-rename-theirs">
                {conflict.sameName
                  ? `The note changed elsewhere; its name is still “${conflict.theirs.title}”.`
                  : `Renamed elsewhere to “${conflict.theirs.title}”.`}
              </span>{' '}
              <button type="button" className="vt-btn vt-a-link" data-testid="vt-a-rename-use-theirs" onMouseDown={keepFocus} onClick={() => {
                settled.current = true
                conflict.useTheirs()
              }}>
                Use theirs
              </button>
              {' · '}
              <button type="button" className="vt-btn vt-a-link" data-testid="vt-a-rename-save-mine" onMouseDown={keepFocus} onClick={() => {
                settled.current = true
                conflict.saveMine()
              }}>
                Save mine anyway
              </button>
            </>
          ) : (
            <span className="vt-faint">Changed elsewhere since you started; reading the other version… Esc cancels.</span>
          )}
        </span>
      ) : notice ? (
        <NoticeLine notice={notice} />
      ) : (
        <span className="vt-a-rename-hint vt-small vt-faint">Enter saves · Esc cancels</span>
      )}
    </span>
  )
}

/** The small ⋯ menu beside a track's name. It holds only real actions; today that is "Rename track…". */
export function TrackMenu({ track, renamer }: { track: Track; renamer: Renamer }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (event: Event) => {
      if (root.current && event.target instanceof Node && !root.current.contains(event.target)) setOpen(false)
    }
    const esc = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc, true)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', esc, true)
    }
  }, [open])
  if (!renamer.canRename(track)) return null
  return (
    <span ref={root} className="vt-a-menu" onClick={(event) => event.stopPropagation()}>
      <button
        type="button"
        className="vt-btn vt-a-menu-btn"
        aria-label={`Actions for ${renamer.titleOf(track)}`}
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="vt-a-track-menu"
        onClick={() => setOpen((value) => !value)}
      >
        ⋯
      </button>
      {open ? (
        <span className="vt-a-menu-pop" role="menu">
          <button
            type="button"
            role="menuitem"
            className="vt-btn vt-a-menu-item"
            data-testid="vt-a-menu-rename"
            onClick={() => {
              setOpen(false)
              renamer.start(track)
            }}
          >
            Rename track…
          </button>
        </span>
      ) : null}
    </span>
  )
}
