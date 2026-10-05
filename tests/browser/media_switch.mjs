// Switching documents in the REAL MediaView: an item page on a running lane, its document chips clicked A then B.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/media_switch.mjs   (SKIPs cleanly without a lane or browser)
//
// What it pins (Codex audit 2026-10-04 #11, and 2026-10-05 round 2 finding 5: no checked-in test covered it): A's
// error must never stay on screen once B has loaded, and a slow answer for A must never overwrite B.
//   1. A answers 404, then B answers 200: B's text shows, and no error.
//   2. A is slow (its 404 lands AFTER B's 200): still B's text, and no error.
// Both documents' answers are made up here in the browser (route interception); the lane's real files are not read.

import { at, check, finish, openLane } from './_lane.mjs'

const NAME = 'media_switch'
const { browser, page } = await openLane(NAME)

try {
  await page.goto(at('vt'), { waitUntil: 'networkidle' })
  // An item with at least two text documents, from the projection the page itself reads.
  const target = await page.evaluate(async () => {
    const body = await (await fetch('/api/plugins/vibetracks/projection')).json()
    for (const track of body.tracks) {
      for (const items of Object.values(track.evidence?.by_iteration ?? {})) {
        for (const item of items) {
          const texts = (item.media ?? []).filter((media) => media.kind === 'text')
          if (texts.length >= 2) return { track: track.id, item: item.id, a: texts[0], b: texts[1] }
        }
      }
    }
    return null
  })
  if (!target) {
    check(false, 'the projection has an item with two text documents to switch between')
  } else {
    console.log(`item ${target.track}/${target.item}: A=${target.a.id} B=${target.b.id}`)
    const token = `B-${Date.now()}`
    let aDelay = 0
    // WHY the trailing *: media URLs carry ?rev=<media_rev> since the media revision binding; a glob without it never matches.
    const media = (id) => `**/api/plugins/vibetracks/media/${encodeURIComponent(id)}*`
    await page.route(media(target.a.id), async (route) => {
      if (aDelay) await new Promise((resolve) => setTimeout(resolve, aDelay))
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"not found"}' }).catch(() => {})
    })
    await page.route(media(target.b.id), (route) => route.fulfill({ status: 200, contentType: 'text/plain; charset=utf-8', body: `${token}\nsecond line` }))

    const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const chip = (label) => page.locator('[data-testid=vt-a-doc]').filter({ hasText: new RegExp(`^${escape(label)}$`) }).first()
    const view = page.locator('[data-testid=vt-media-view]')

    // 1. A (404) -> B (200).
    await page.goto(at(`vt?track=${encodeURIComponent(target.track)}&item=${encodeURIComponent(target.item)}`), { waitUntil: 'networkidle' })
    await chip(target.a.label).click()
    await page.locator('[data-testid=vt-media-error]').waitFor({ timeout: 5000 })
    check(await page.locator('[data-testid=vt-media-error]').isVisible(), "A's 404 shows as an error while A is open")
    await chip(target.b.label).click()
    // WHY wait and then assert, not waitFor(text): with the old bug the text never appears; the check must say why.
    await page.locator('[data-testid=vt-media-text]').waitFor({ timeout: 5000 }).catch(() => {})
    check((await view.getAttribute('data-media-id')) === target.b.id, 'the view now holds B')
    check((await page.locator('[data-testid=vt-media-text]').count()) === 1 && (await page.locator('[data-testid=vt-media-text]').textContent())?.startsWith(token), "B's text shows")
    check((await page.locator('[data-testid=vt-media-error]').count()) === 0, "A's error is gone")

    // 2. A slow: its 404 arrives after B's text.
    aDelay = 1500
    await page.goto(at(`vt?track=${encodeURIComponent(target.track)}&item=${encodeURIComponent(target.item)}`), { waitUntil: 'networkidle' })
    await page.reload({ waitUntil: 'networkidle' })
    await chip(target.a.label).click()
    await page.waitForTimeout(100)
    await chip(target.b.label).click()
    await page.locator('[data-testid=vt-media-text]').waitFor({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(aDelay + 500)
    check((await page.locator('[data-testid=vt-media-text]').count()) === 1 && (await page.locator('[data-testid=vt-media-text]').textContent())?.startsWith(token), "B's text still shows after A's late 404")
    check((await page.locator('[data-testid=vt-media-error]').count()) === 0, "A's late 404 never reaches the screen")
  }
} catch (error) {
  check(false, `the journey ran (${error instanceof Error ? error.message : error})`)
} finally {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)
