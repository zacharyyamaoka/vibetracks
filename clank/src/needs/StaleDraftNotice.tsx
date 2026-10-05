// The calm notice a card shows when Zach's draft for it is STALE (answerRules.ts): the question changed since he drafted
// it, it was drafted before drafts were bound, or the loop has settled the item. It quotes his draft whole and offers
// Reconfirm (re-bind it to the question as it reads now) and Discard. Every proposal renders it in its answer area.
// WHY a notice and not a silent drop: the stale draft is Zach's own words; the store never shows it as answered and
// Copy never exports it, so without this he would not know it exists or why it vanished from the copy.

import type { AnswerStore } from './answers'
import { staleText } from './answerRules'
import { choiceLabel } from './exportAnswers'
import type { NeedsDoc, NeedsItem } from './types'

export interface StaleDraftNoticeProps {
  answers: AnswerStore
  doc: NeedsDoc
  item: NeedsItem
  className?: string
}

export function StaleDraftNotice({ answers, doc, item, className }: StaleDraftNoticeProps) {
  const stale = answers.stale(doc.track, item.local_id)
  if (!stale) return null
  const { draft } = stale
  // The drafted option in the dashboard's words; an option the item no longer offers is named by its generic label.
  const option = draft.choice ? choiceLabel(item, draft.choice) : null
  const offered = !draft.choice || item.options.some((candidate) => candidate.key === draft.choice)
  const reason = staleText(stale)
  return (
    <div className={`vt-needs-stale ${className ?? ''}`} role="note" data-testid="vt-needs-stale" data-reason={stale.reason} data-item={item.id}>
      <p className="vt-small">
        <span className="vt-strong">{reason.charAt(0).toUpperCase() + reason.slice(1)}.</span>{' '}
        <span className="vt-muted">
          It is not in the copy.
          {stale.reconfirmable ? ' Reconfirm it against the question as it reads now, discard it, or answer again below (that replaces it).' : ''}
          {stale.reason !== 'settled' && !offered ? ' The option you picked is no longer offered: discard it, or answer again below.' : ''}
          {stale.reason === 'settled' ? ' There is nothing left to answer here; discard it when you have read it.' : ''}
        </span>
      </p>
      <p className="vt-small vt-muted vt-needs-stale-draft">
        Your draft: {option ? <span className="vt-strong">{option}</span> : <span>no option</span>}
        {draft.note ? (
          <>
            {' + note:'}
            {/* The note exactly as saved: pre-wrap keeps its line breaks and edge whitespace visible. */}
            <span className="vt-needs-stale-note" data-testid="vt-needs-stale-note">
              {draft.note}
            </span>
          </>
        ) : null}
      </p>
      <p className="vt-small vt-needs-stale-actions">
        {stale.reconfirmable ? (
          <button type="button" className="vt-btn vt-needs-stale-btn" onClick={() => answers.reconfirm(doc.track, item.local_id)} data-testid="vt-needs-stale-reconfirm">
            Reconfirm
          </button>
        ) : null}
        <button type="button" className="vt-btn vt-needs-stale-btn" onClick={() => answers.clear(doc.track, item.local_id)} data-testid="vt-needs-stale-discard">
          Discard
        </button>
      </p>
    </div>
  )
}
