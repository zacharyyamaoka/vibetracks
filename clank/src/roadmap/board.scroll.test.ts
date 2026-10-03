import { describe, expect, it } from 'vitest'
import { PANEL_RESERVE, REVEAL_MARGIN, boardContentWidth, scrollToReveal } from './scroll'

// A 978 px wide, 400 px tall viewport: the focus panel covers the right PANEL_RESERVE px, leaving 508 px clear.
const view = (left: number, top: number) => ({ left, top, width: 978, height: 400 })
const CLEAR = 978 - PANEL_RESERVE

describe('scrollToReveal (Codex I02: a selected card must end up left of the focus panel)', () => {
  it('scrolls a card at the far right of a narrow board fully clear of the panel, with a margin', () => {
    // Codex's case: RB8 at x=712..768 on a 786 px board, maximum natural scroll zero.
    const box = { x: 712, y: 100, w: 56, h: 22 }
    const target = scrollToReveal(box, view(0, 0), PANEL_RESERVE)
    expect(target.left).toBeGreaterThan(0)
    expect(box.x + box.w - target.left).toBeLessThanOrEqual(CLEAR - REVEAL_MARGIN)
    expect(box.x - target.left).toBeGreaterThanOrEqual(0)
  })

  it('does not move for a card that is already clear of the panel', () => {
    const box = { x: 100, y: 100, w: 56, h: 22 }
    expect(scrollToReveal(box, view(0, 0), PANEL_RESERVE)).toEqual({ left: 0, top: 0 })
    expect(scrollToReveal({ x: 600, y: 150, w: 56, h: 22 }, view(300, 50), PANEL_RESERVE)).toEqual({ left: 300, top: 50 })
  })

  it('treats a card under the panel as not in view even when it is inside the viewport', () => {
    const box = { x: 700, y: 100, w: 56, h: 22 }
    expect(box.x + box.w).toBeLessThan(978)
    expect(scrollToReveal(box, view(0, 0), PANEL_RESERVE).left).not.toBe(0)
  })

  it('treats a card that touches the panel edge without the margin as not clear', () => {
    const box = { x: CLEAR - 56, y: 100, w: 56, h: 22 }
    expect(scrollToReveal(box, view(0, 0), PANEL_RESERVE).left).toBeGreaterThan(0)
  })

  it('scrolls back left for a card left of the viewport', () => {
    const target = scrollToReveal({ x: 40, y: 100, w: 56, h: 22 }, view(500, 0), PANEL_RESERVE)
    expect(target.left).toBeLessThanOrEqual(40)
    expect(target.left).toBeGreaterThanOrEqual(0)
  })

  it('reveals vertically: below the fold scrolls down, above scrolls up, clear stays put', () => {
    const below = scrollToReveal({ x: 100, y: 900, w: 56, h: 22 }, view(0, 0), PANEL_RESERVE)
    expect(below.top).toBeGreaterThan(0)
    expect(900 - below.top).toBeGreaterThanOrEqual(0)
    expect(922 - below.top).toBeLessThanOrEqual(400)
    const above = scrollToReveal({ x: 100, y: 20, w: 56, h: 22 }, view(0, 600), PANEL_RESERVE)
    expect(above.top).toBeLessThanOrEqual(20)
    expect(above.top).toBeGreaterThanOrEqual(0)
    expect(scrollToReveal({ x: 100, y: 120, w: 56, h: 22 }, view(0, 50), PANEL_RESERVE).top).toBe(50)
  })

  it('never returns a negative scroll position', () => {
    expect(scrollToReveal({ x: 2, y: 2, w: 56, h: 22 }, view(300, 300), PANEL_RESERVE)).toEqual({ left: 0, top: 0 })
  })

  it('keeps a floor on the visible width so a viewport narrower than the panel does not scroll nonsense', () => {
    const target = scrollToReveal({ x: 300, y: 10, w: 56, h: 22 }, { left: 0, top: 0, width: 400, height: 300 }, PANEL_RESERVE)
    expect(Number.isFinite(target.left)).toBe(true)
    expect(target.left).toBeGreaterThanOrEqual(0)
  })

  it('leaves room to scroll: a card at the right edge of the board ends up clear of the panel once the browser clamps the target', () => {
    // Codex's geometry: a 786 px board, RB8 flush with its right edge, in a 978 px viewport.
    const boardWidth = 786
    const box = { x: 712, y: 100, w: 56, h: 22 }
    const target = scrollToReveal(box, view(0, 0), PANEL_RESERVE)
    const maxScroll = (picked: boolean) => Math.max(0, boardContentWidth(boardWidth, picked) - 978)
    const landed = (picked: boolean) => Math.min(target.left, maxScroll(picked))
    // Without a picked rung there is no extra room and nothing to scroll, which is the bug.
    expect(maxScroll(false)).toBe(0)
    expect(box.x + box.w + REVEAL_MARGIN - landed(false)).toBeGreaterThan(CLEAR)
    expect(box.x + box.w + REVEAL_MARGIN - landed(true)).toBeLessThanOrEqual(CLEAR)
    expect(box.x - landed(true)).toBeGreaterThanOrEqual(0)
  })

  it('adds no trailing space when nothing is picked', () => {
    expect(boardContentWidth(786, false)).toBe(786)
    expect(boardContentWidth(786, true)).toBe(786 + PANEL_RESERVE + REVEAL_MARGIN)
  })

  it('narrow pane (Codex J01): a card wider than the clear area ends with its right edge at or before the panel', () => {
    // A ~600 px pane leaves 600 - 470 = 130 px left of the panel, 118 px of it clear after the margin; a rich card is
    // 120 px. The old 200 px floor centred it in a clear area that did not exist and left it 28 px under the panel.
    const pane = { left: 0, top: 0, width: 600, height: 400 }
    const panelLeft = pane.width - PANEL_RESERVE
    for (const x of [0, 260, 515, 900]) {
      const box = { x, y: 100, w: 120, h: 88 }
      const target = scrollToReveal(box, pane, PANEL_RESERVE)
      expect(box.x + box.w - target.left, `card at ${x}`).toBeLessThanOrEqual(panelLeft)
      expect(box.x - target.left, `card at ${x}`).toBeGreaterThanOrEqual(0)
    }
  })

  it('narrow pane: a card that fits the actual clear width is placed fully clear of the panel, with the margin', () => {
    const pane = { left: 0, top: 0, width: 600, height: 400 }
    const box = { x: 515, y: 100, w: 56, h: 22 }
    const target = scrollToReveal(box, pane, PANEL_RESERVE)
    expect(box.x + box.w + REVEAL_MARGIN - target.left).toBeLessThanOrEqual(pane.width - PANEL_RESERVE)
  })

  it('narrow pane: a card already clear stays where it is', () => {
    expect(scrollToReveal({ x: 312, y: 100, w: 56, h: 22 }, { left: 300, top: 0, width: 600, height: 400 }, PANEL_RESERVE)).toEqual({ left: 300, top: 0 })
  })
})
