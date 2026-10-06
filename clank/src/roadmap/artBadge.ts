// How an art thumbnail's badge ("0.1 m/s", "×2", "N×") fits inside its box. Pure, so it is tested without a DOM.
//
// WHY (the Lineage tab's 34 px thumbnails): the badge used a fixed 9 px font and hung 2 px past the box, so a 7-character
// speed was wider than the whole thumbnail and spilled over the rung id and title beside it. The badge now scales with
// the box and stays inside it; when even the smallest legible size does not fit, it is dropped from the picture and its
// text moves to the thumbnail's title and aria-label (truthful-rendering rule: nothing is hidden without a way to see it).

/** The badge's usual size, and the smallest that is still legible. */
export const BADGE_FONT_MAX = 9
export const BADGE_FONT_MIN = 8
/** Horizontal room the badge's padding and the box edge take, and the glyph width as a fraction of the font size (generous: a proportional face). */
export const BADGE_PAD = 6
export const BADGE_GLYPH_EM = 0.62

/** The font size that fits `badge` inside a box `boxWidth` px wide, or null when none at or above the legible minimum does. */
export function badgeFontSize(badge: string, boxWidth: number): number | null {
  const glyphs = Array.from(badge).length
  if (glyphs === 0) return null
  const fits = (boxWidth - BADGE_PAD) / (glyphs * BADGE_GLYPH_EM)
  const size = Math.min(BADGE_FONT_MAX, Math.floor(fits * 10) / 10)
  return size >= BADGE_FONT_MIN ? size : null
}
