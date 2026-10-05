// "Copy answers": one action that builds the export (exportAnswers.ts), tries the clipboard, and ALWAYS ends with the
// text in a pre-selected textarea. WHY the textarea every time: clipboard writes are often refused on Clank/file
// origins and in a background panel, and a copy that silently failed is worse than none; the selected text is one
// Ctrl+C away whatever happened.

import { useEffect, useRef, useState } from 'react'
import type { AnswerStore } from './answers'
import { exportAnswers, type ExportResult } from './exportAnswers'
import type { NeedsDoc } from './types'

export interface CopyOutProps {
  docs: NeedsDoc[]
  answers: AnswerStore
  /** The button's words; default "Copy answers". */
  label?: string
  className?: string
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to execCommand
  }
  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    area.remove()
    return ok
  } catch {
    return false
  }
}

export function CopyOut({ docs, answers, label = 'Copy answers', className }: CopyOutProps) {
  const [result, setResult] = useState<(ExportResult & { copied: boolean }) | null>(null)
  const area = useRef<HTMLTextAreaElement>(null)
  const preview = exportAnswers(docs, answers.get)
  const count = preview.exported.length

  useEffect(() => {
    if (result && area.current) {
      area.current.focus()
      area.current.select()
    }
  }, [result])

  const run = async () => {
    const built = exportAnswers(docs, answers.get)
    const copied = built.markdown ? await copyText(built.markdown) : false
    setResult({ ...built, copied })
  }

  return (
    <div className={`vt-needs-copyout ${className ?? ''}`} data-testid="vt-needs-copyout">
      <button
        type="button"
        className="vt-btn vt-needs-copy-btn"
        disabled={count === 0}
        aria-disabled={count === 0}
        title={count === 0 ? 'Answer at least one item first' : `Copy ${count} answer${count === 1 ? '' : 's'} as markdown`}
        onClick={() => void run()}
        data-testid="vt-needs-copy"
      >
        {label}
        {count ? ` (${count})` : ''}
      </button>
      {preview.skipped.length ? (
        <span className="vt-small vt-tone-warn" style={{ marginLeft: 10 }}>
          {preview.skipped.length} left out: {preview.skipped.map((skip) => `${skip.id.split(':').pop()} ${skip.reason}`).join('; ')}
        </span>
      ) : null}
      {result ? (
        <div className="vt-needs-copy-result">
          <p className="vt-small vt-muted" role="status">
            {result.copied ? `Copied ${result.exported.length} answer${result.exported.length === 1 ? '' : 's'}.` : 'The clipboard refused; the text below is selected, press Ctrl+C.'}{' '}
            Paste it into the loop's chat
            {docs.some((doc) => doc.answer_channel.row_schema) ? ', or append the jsonl rows to the answers file' : ''}.
          </p>
          <textarea
            ref={area}
            className="vt-needs-copy-area"
            readOnly
            value={result.markdown}
            rows={Math.min(18, Math.max(4, result.markdown.split('\n').length + 1))}
            onFocus={(event) => event.currentTarget.select()}
            data-testid="vt-needs-copy-area"
          />
        </div>
      ) : null}
    </div>
  )
}
