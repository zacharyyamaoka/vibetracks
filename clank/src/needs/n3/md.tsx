// A deliberately tiny markdown reader for the loops' verbatim text: paragraphs, "- " bullet lines, `code` and
// **bold**. WHY not a markdown library: the loops write only these four forms, and every other character must stay
// on screen exactly as authored (truthful rendering); React elements only, never innerHTML, so a path or a quote in
// the text can never become markup.

import type { ReactNode } from 'react'

export function Inline({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g)
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith('`') && part.endsWith('`') && part.length > 1) return <code key={index}>{part.slice(1, -1)}</code>
        if (part.startsWith('**') && part.endsWith('**') && part.length > 3) return <strong key={index}>{part.slice(2, -2)}</strong>
        return part ? <span key={index}>{part}</span> : null
      })}
    </>
  )
}

export function Md({ text, className }: { text: string; className?: string }) {
  const lines = text.split('\n')
  const blocks: ReactNode[] = []
  let bullets: string[] = []
  const flush = () => {
    if (!bullets.length) return
    const items = bullets
    bullets = []
    blocks.push(
      <ul key={`ul${blocks.length}`}>
        {items.map((item, index) => (
          <li key={index}>
            <Inline text={item} />
          </li>
        ))}
      </ul>,
    )
  }
  for (const line of lines) {
    if (/^\s*-\s+/.test(line)) {
      bullets.push(line.replace(/^\s*-\s+/, ''))
      continue
    }
    flush()
    if (!line.trim()) continue
    blocks.push(
      <p key={`p${blocks.length}`}>
        <Inline text={line} />
      </p>,
    )
  }
  flush()
  return <div className={`vt-n3-md ${className ?? ''}`}>{blocks}</div>
}
