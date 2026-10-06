// The revision fence of one rename, as pure functions (rename.tsx holds the React state; renameFence.check.mjs tests
// these without a browser).
//
// The rules (audit 2026-10-04 #6 and #8):
//   - The note revision is captured when editing STARTS and kept until the save resolves. A refreshed projection never
//     moves it: a draft typed against R1 is only ever saved against R1, so a concurrent writer's R2 makes it 409.
//   - On a 409 the edit stays open with the reader's text and shows the other title once the page has read it. Only an
//     explicit "Save mine anyway" re-fences, on the revision that other title was read at; "Use theirs" drops the draft.
//   - The title is sent exactly as typed: no trimming, no normalising. The server owns validation (empty,
//     whitespace-only, newline, length) and its message is shown inline.

export interface Base {
  /** The title the reader saw when the edit started (or the one "Save mine anyway" accepted). */
  title: string
  /** The note revision that title was read at; the only fence this draft is ever saved against. */
  revision: string
}

export interface Theirs {
  title: string
  revision: string
}

export type Phase =
  | { kind: 'editing' }
  /** The last save failed for a reason other than a conflict; `draft` is what was sent. */
  | { kind: 'failed'; draft: string; message: string }
  /** The note changed since `base`; `reported` is the revision the 409 named (null when it named none). */
  | { kind: 'conflict'; reported: string | null }

export interface Session {
  trackId: string
  base: Base
  draft: string
  phase: Phase
}

/** A new edit: the fence is the revision on screen right now, and nothing later replaces it on its own. */
export function begin(trackId: string, title: string, revision: string): Session {
  return { trackId, base: { title, revision }, draft: title, phase: { kind: 'editing' } }
}

/** The request a submit sends, or null when there is nothing to save (the exact text the edit started from).
 * WHY exact comparison: "  Grasping  " is a different title from "Grasping"; the server decides whether it is valid. */
export function request(session: Session): { title: string; revision: string } | null {
  if (session.draft === session.base.title) return null
  return { title: session.draft, revision: session.base.revision }
}

/** The other writer's title, once the projection has re-read the note: the track's revision there differs from the
 * one this draft was based on. null while the page still shows the old revision (the reload is in flight). */
export function theirsOf(session: Session, projectionTitle: string, projectionRevision: string | null): Theirs | null {
  if (session.phase.kind !== 'conflict') return null
  if (!projectionRevision || projectionRevision === session.base.revision) return null
  return { title: projectionTitle, revision: projectionRevision }
}

/** The reader chose to save their draft over `theirs`: re-fence on the revision they were shown, nothing newer. */
export function saveMineAnyway(session: Session, theirs: Theirs): Session {
  return { ...session, base: { title: theirs.title, revision: theirs.revision }, phase: { kind: 'editing' } }
}

export function conflicted(session: Session, reported: string | null): Session {
  return { ...session, phase: { kind: 'conflict', reported } }
}

export function failed(session: Session, message: string): Session {
  return { ...session, phase: { kind: 'failed', draft: session.draft, message } }
}

export function edited(session: Session, draft: string): Session {
  // Typing after a failure clears the stale message; a conflict stays until the reader picks a side.
  return { ...session, draft, phase: session.phase.kind === 'failed' ? { kind: 'editing' } : session.phase }
}

/** What a blur (clicking away) does. WHY not always "submit": in a conflict only the explicit buttons may save, and a
 * draft the server just refused would only be refused again (and the reopened editor would grab focus back). */
export function onBlur(session: Session): 'submit' | 'stay' {
  if (session.phase.kind === 'conflict') return 'stay'
  if (session.phase.kind === 'failed' && session.phase.draft === session.draft) return 'stay'
  return 'submit'
}
