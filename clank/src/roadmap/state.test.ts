import { describe, expect, it } from 'vitest'
import { resolveView } from './state'

const has = (id: string) => ['RB0', 'RB1', 'OB0'].includes(id)

describe('resolveView (the controlled state, defaults filled)', () => {
  it('defaults everything missing', () => {
    expect(resolveView(undefined, has, true)).toEqual({ lens: 'ladder', orient: 'lr', card: 'compact', sel: null, tab: 'proof', trail: [] })
    expect(resolveView({}, has, true)).toEqual(resolveView(null, has, true))
  })

  it('keeps every valid value', () => {
    expect(resolveView({ lens: 'board', orient: 'td', card: 'rich', sel: 'RB1', tab: 'lineage', trail: ['RB0'] }, has, true))
      .toEqual({ lens: 'board', orient: 'td', card: 'rich', sel: 'RB1', tab: 'lineage', trail: ['RB0'] })
  })

  it('replaces what it does not recognise, and drops a rung the document does not hold', () => {
    expect(resolveView({ lens: 'spiral', orient: 'x', card: 'huge', sel: 'ZZ9', tab: 'gossip', trail: ['RB0'] }, has, true))
      .toEqual({ lens: 'ladder', orient: 'lr', card: 'compact', sel: null, tab: 'proof', trail: [] })
    expect(resolveView({ sel: 'RB1', trail: ['ZZ9', 'RB0', 7 as never] }, has, true).trail).toEqual(['RB0'])
  })

  it('shows Depth for Waves when no rung has a wave', () => {
    expect(resolveView({ lens: 'waves' }, has, false).lens).toBe('depth')
    expect(resolveView({ lens: 'waves' }, has, true).lens).toBe('waves')
  })
})
