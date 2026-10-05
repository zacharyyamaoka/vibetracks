// Renaming a work track, like renaming a chat (Zach, 2026-10-04: "internally keep an ID that doesn't change, but it's
// nice being able to rename the work track, just like I can rename a chat session").
//   - Double-click the name (home row or track page title), press F2 on it, or use "Rename track…" in its ⋯ menu.
//   - Enter or clicking away saves; Esc cancels. An empty or unchanged name saves nothing.
//   - The save is POST /tracks/<id>/title {title, revision} (docs/dashboard/ADAPTERS.md "Renaming a track"): only the
//     note's vibe-title changes; the id, every URL and the roadmap key stay the same.
//   - Optimistic: the new name shows at once and rolls back if the save fails. A 409 means the note changed since this
//     page read it: say so quietly, reload, and keep the edit open with the reader's text.
// WHY only tracks with a registry revision: a deployment (can12) has no note of its own to rename, so it offers nothing
// rather than a control that cannot work (G2, no fake controls).

import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import type { PluginBackend } from '@clank/api'
import type { Projection, Track } from '../../shared'
import { registryOf } from './live'

const MAX_TITLE = 80
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f]/

interface Override {
  title: string
  pending: boolean
}

export interface RenameNotice {
  track: string
  text: string
  tone: 'muted' | 'risk'
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
  notice: RenameNotice | null
}

export function useRenamer(backend: PluginBackend, projection: Projection, reload: () => void): Renamer {
  const [overrides, setOverrides] = useState<Record<string, Override>>({})
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [notice, setNotice] = useState<RenameNotice | null>(null)

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
      if (!registryOf(track)?.revision) return
      setEditing(track.id)
      setDraft(overrides[track.id]?.title ?? track.title)
      setNotice(null)
    },
    [overrides],
  )
  const cancel = useCallback(() => {
    setEditing(null)
    setNotice(null)
  }, [])

  const submit = useCallback(
    (track: Track) => {
      const title = draft.trim()
      const shown = overrides[track.id]?.title ?? track.title
      if (!title || title === shown) {
        setEditing(null)
        setNotice(null)
        return
      }
      if (title.length > MAX_TITLE) {
        setNotice({ track: track.id, text: `${MAX_TITLE} characters at most (this is ${title.length})`, tone: 'risk' })
        return
      }
      if (CONTROL.test(title)) {
        setNotice({ track: track.id, text: 'one line, no control characters', tone: 'risk' })
        return
      }
      // WHY always the projection's revision (never the one a 409 reported): the reader should overwrite only a version
      // the page has shown them. A 409 reloads the projection; an Enter before that lands simply 409s again.
      const revision = registryOf(track)?.revision ?? null
      if (!revision) return
      const previous = overrides[track.id]
      const rollback = () =>
        setOverrides((current) => {
          const next = { ...current }
          if (previous) next[track.id] = previous
          else delete next[track.id]
          return next
        })
      const reopen = (text: string, tone: RenameNotice['tone']) => {
        setEditing(track.id)
        setDraft(title)
        setNotice({ track: track.id, text, tone })
      }
      setOverrides((current) => ({ ...current, [track.id]: { title, pending: true } }))
      setEditing(null)
      setNotice(null)
      backend
        .fetch(`/tracks/${encodeURIComponent(track.id)}/title`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, revision }),
        })
        .then(async (response) => {
          const body = (await response.json().catch(() => null)) as { title?: unknown; error?: unknown } | null
          if (response.ok) {
            const saved = typeof body?.title === 'string' ? body.title : title
            setOverrides((current) => ({ ...current, [track.id]: { title: saved, pending: false } }))
            reload()
            return
          }
          rollback()
          if (response.status === 409) {
            reload()
            reopen('Changed elsewhere, reloaded. Enter saves your name over it.', 'muted')
            return
          }
          reopen(`Not renamed: ${typeof body?.error === 'string' ? body.error : `HTTP ${response.status}`}`, 'risk')
        })
        .catch((error: unknown) => {
          rollback()
          reopen(`Not renamed: ${error instanceof Error ? error.message : String(error)}`, 'risk')
        })
    },
    [backend, draft, overrides, reload],
  )

  return { titleOf, canRename, pending, editing, draft, setDraft, start, cancel, submit, notice }
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
        onChange={(event) => renamer.setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
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
          settled.current = true
          renamer.submit(track)
        }}
      />
      {notice ? <NoticeLine notice={notice} /> : <span className="vt-a-rename-hint vt-small vt-faint">Enter saves · Esc cancels</span>}
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
