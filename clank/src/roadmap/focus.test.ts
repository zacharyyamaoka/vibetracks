import { describe, expect, it } from 'vitest'
import { focusIsFree, restoreBoardFocus, viewKey } from './focus'
import { resolveView } from './state'

// Stand-ins for DOM elements: the decision is the whole test.
const card = () => { const calls: Array<{ preventScroll: boolean }> = []; return { calls, focus: (options: { preventScroll: boolean }) => { calls.push(options) } } }
const BODY = { tag: 'body' }

describe('restoreBoardFocus (history Back/Forward must leave the arrow keys working)', () => {
  it('focuses the picked card, without scrolling, when a restored state finds focus on the body', () => {
    const picked = card()
    expect(restoreBoardFocus(true, 'R1', new Map([['R1', picked], ['R2', card()]]), { activeElement: BODY, body: BODY })).toBe(true)
    expect(picked.calls).toEqual([{ preventScroll: true }])
  })

  it('focuses it when there is no active element at all', () => {
    const picked = card()
    expect(restoreBoardFocus(true, 'R1', new Map([['R1', picked]]), { activeElement: null, body: BODY })).toBe(true)
    expect(picked.calls).toHaveLength(1)
  })

  it('never takes focus from an input or another widget', () => {
    const picked = card()
    expect(restoreBoardFocus(true, 'R1', new Map([['R1', picked]]), { activeElement: { tag: 'input' }, body: BODY })).toBe(false)
    expect(picked.calls).toHaveLength(0)
  })

  it('does nothing for a change this widget made itself, with nothing picked, or without that card on the board', () => {
    const picked = card()
    const cards = new Map([['R1', picked]])
    const free = { activeElement: BODY, body: BODY }
    expect(restoreBoardFocus(false, 'R1', cards, free)).toBe(false)
    expect(restoreBoardFocus(true, null, cards, free)).toBe(false)
    expect(restoreBoardFocus(true, 'R9', cards, free)).toBe(false)
    expect(picked.calls).toHaveLength(0)
  })

  it('focusIsFree is true only for null, undefined and the body', () => {
    expect(focusIsFree(null, BODY)).toBe(true)
    expect(focusIsFree(BODY, BODY)).toBe(true)
    expect(focusIsFree({}, BODY)).toBe(false)
  })
})

describe('viewKey (own change vs. one that arrived from history)', () => {
  const has = () => true
  it('is equal for equal views and differs when the pick, tab, lens or trail differs', () => {
    const view = (state: Record<string, unknown>) => viewKey(resolveView(state, has, true))
    expect(view({ sel: 'R1', tab: 'proof' })).toBe(view({ sel: 'R1' }))
    expect(view({ sel: 'R1' })).not.toBe(view({ sel: 'R2' }))
    expect(view({ sel: 'R1' })).not.toBe(view({ sel: 'R1', tab: 'lineage' }))
    expect(view({ sel: 'R1' })).not.toBe(view({ sel: 'R1', lens: 'depth' }))
    expect(view({ sel: 'R1', trail: ['R0'] })).not.toBe(view({ sel: 'R1' }))
  })
})
