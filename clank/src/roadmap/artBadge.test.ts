import { describe, expect, it } from 'vitest'
import { BADGE_FONT_MAX, BADGE_FONT_MIN, BADGE_GLYPH_EM, BADGE_PAD, badgeFontSize } from './artBadge'

describe('badgeFontSize (the badge must fit inside its thumbnail)', () => {
  it('drops a belt-speed badge at the 34 px lineage size, where it is wider than the thumbnail', () => {
    expect(badgeFontSize('0.1 m/s', 34)).toBeNull()
    expect(badgeFontSize('0.3 m/s', 34)).toBeNull()
  })

  it('keeps short badges at the lineage size, and every badge on a 52 px card and the 104 px focus art', () => {
    expect(badgeFontSize('×2', 34)).toBe(BADGE_FONT_MAX)
    expect(badgeFontSize('N×', 34)).toBe(BADGE_FONT_MAX)
    expect(badgeFontSize('0.1 m/s', 52)).toBe(BADGE_FONT_MAX)
    expect(badgeFontSize('0.1 m/s', 104)).toBe(BADGE_FONT_MAX)
  })

  it('scales down between the legible bounds instead of overflowing', () => {
    const size = badgeFontSize('0.1 m/s', 42)
    expect(size).not.toBeNull()
    expect(size!).toBeGreaterThanOrEqual(BADGE_FONT_MIN)
    expect(size!).toBeLessThan(BADGE_FONT_MAX)
  })

  it('whenever it says a size, the estimated text plus padding is no wider than the box', () => {
    for (const badge of ['0.1 m/s', '0.25 m/s', 'static', '×3', 'N×', '12.5 m/s'])
      for (let width = 10; width <= 120; width += 1) {
        const size = badgeFontSize(badge, width)
        if (size !== null) expect(Array.from(badge).length * BADGE_GLYPH_EM * size + BADGE_PAD).toBeLessThanOrEqual(width + 1e-9)
      }
  })
})
