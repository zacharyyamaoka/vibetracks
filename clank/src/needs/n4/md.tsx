// The loops write lightly marked-up prose (`code spans`, **bold**, "- " list lines). N4 renders exactly those three
// marks and nothing else. WHY so little: truthful rendering, so every authored character except the markers stays on
// screen, and a full markdown parser would quietly re-flow the loops' hand-made lists and brackets.

import { Fragment, type ReactNode } from 'react'

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*)/g

export function Md({ text, className }: { text: string | null | undefined; className?: string }) {
  if (!text) return null
  const parts: ReactNode[] = []
  let last = 0
  let key = 0
  for (const match of text.matchAll(INLINE)) {
    const index = match.index ?? 0
    if (index > last) parts.push(<Fragment key={key++}>{text.slice(last, index)}</Fragment>)
    const token = match[0]
    if (token.startsWith('`')) parts.push(<code key={key++}>{token.slice(1, -1)}</code>)
    else parts.push(<strong key={key++}>{token.slice(2, -2)}</strong>)
    last = index + token.length
  }
  if (last < text.length) parts.push(<Fragment key={key++}>{text.slice(last)}</Fragment>)
  // pre-wrap keeps the loops' own line breaks and "- " lists exactly as written.
  return <span className={`n4-md ${className ?? ''}`}>{parts}</span>
}
