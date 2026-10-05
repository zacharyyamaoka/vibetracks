// The item page's real|sim video pair when the backend refuses its media with 409, on the REAL page of a running lane.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/media_pair_stale.mjs   (SKIPs cleanly without a lane or browser)
//
// What it pins (verifier, 2026-10-05, item c): on a /media 409 the pair kept two dead players at 0:00 and two
// "open in new tab" links that would only 409 again. It must show MediaView's calm line instead, "This changed since
// you opened it: reload", with no players, no links and no "Play both"; and that reload must be a real control:
//   1. the real video answers 409 -> one stale line, 0 players, 0 links, 0 "Play both" in the pair
//   2. "reload" re-reads /projection (a real request), and while the backend still refuses, the line stays
//   3. the backend opens the file again, "reload" -> both players are back, with their links, and no stale line
//   4. a non-409 refusal (404) on one side -> that side says "Could not load", the other side still plays
//   5. MediaView (which now shares the pair's check, useMediaRefusals) still shows the line for a text write-up's 409
// Every refusal is made up in the browser (route interception); the lane's real files are not touched.

import { at, check, finish, openLane } from './_lane.mjs'

const NAME = 'media_pair_stale'
const { browser, page } = await openLane(NAME)

try {
  await page.goto(at('vt'), { waitUntil: 'networkidle' })
  const target = await page.evaluate(async () => {
    const body = await (await fetch('/api/plugins/vibetracks/projection')).json()
    for (const track of body.tracks) {
      for (const items of Object.values(track.evidence?.by_iteration ?? {})) {
        for (const item of items) {
          const videos = (item.media ?? []).filter((media) => media.kind === 'video')
          const real = videos.find((media) => /^real\b/i.test(media.label))
          const sim = videos.find((media) => /^sim\b/i.test(media.label))
          if (real && sim) return { track: track.id, item: item.id, real: real.id, sim: sim.id }
        }
      }
    }
    return null
  })
  if (!target) {
    check(false, 'the projection has an item with a real|sim video pair')
  } else {
    console.log(`item ${target.track}/${target.item}: real=${target.real} sim=${target.sim}`)
    // WHY the trailing *: media URLs carry ?rev=<media_rev>; a glob without it never matches.
    const media = (id) => `**/api/plugins/vibetracks/media/${encodeURIComponent(id)}*`
    let realStatus = 409
    let simStatus = 200
    const answer = (status) => (route) =>
      status === 200
        ? route.continue()
        : route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ error: status === 409 ? 'changed since shown' : 'not found' }) }).catch(() => {})
    await page.route(media(target.real), (route) => answer(realStatus)(route))
    await page.route(media(target.sim), (route) => answer(simStatus)(route))
    let projectionReads = 0
    page.on('request', (request) => {
      if (/\/api\/plugins\/vibetracks\/projection$/.test(new URL(request.url()).pathname)) projectionReads++
    })

    const pair = page.locator('[data-testid=vt-a-item] [data-testid=vt-a-pair]').first()
    const inPair = async () => ({
      stale: await pair.locator('[data-testid=vt-media-stale]').count(),
      videos: await pair.locator('video').count(),
      links: await pair.locator('a').count(),
      playBoth: await pair.locator('[data-testid=vt-a-play-both]').count(),
      errors: await pair.locator('[data-testid=vt-media-error]').count(),
      text: (await pair.textContent()) ?? '',
    })
    const itemHash = `vt?track=${encodeURIComponent(target.track)}&item=${encodeURIComponent(target.item)}`

    // 1. The real side answers 409.
    await page.goto(at(itemHash), { waitUntil: 'networkidle' })
    await pair.locator('[data-testid=vt-media-stale]').waitFor({ timeout: 5000 }).catch(() => {})
    let seen = await inPair()
    console.log(`409: ${JSON.stringify({ ...seen, text: seen.text.slice(0, 120) })}`)
    check(seen.stale === 1, 'a 409 shows the one calm stale line in the pair')
    check(/This changed since you opened it:\s*reload/.test(seen.text), 'the line reads "This changed since you opened it: reload"')
    check(seen.videos === 0, `no player is left at 0:00 (${seen.videos})`)
    check(seen.links === 0, `no "open in new tab" link that would only 409 (${seen.links})`)
    check(seen.playBoth === 0, 'no "Play both" with nothing to play')

    // 2. Reload while the backend still refuses: a real /projection read, and the line stays.
    const readsBefore = projectionReads
    await pair.getByRole('button', { name: 'reload' }).click()
    await page.waitForTimeout(2000)
    seen = await inPair()
    check(projectionReads > readsBefore, `"reload" re-reads /projection (${projectionReads - readsBefore} read)`)
    check(seen.stale === 1 && seen.videos === 0, 'still refused after the reload: the line stays, no players')

    // 3. The backend opens the file again: reload recovers both players.
    realStatus = 200
    await pair.getByRole('button', { name: 'reload' }).click()
    await pair.locator('video').nth(1).waitFor({ timeout: 6000 }).catch(() => {})
    seen = await inPair()
    check(seen.stale === 0 && seen.videos === 2, `reload recovers both players once the backend opens the file (videos ${seen.videos}, stale ${seen.stale})`)
    check(seen.links === 2 && seen.playBoth === 1, 'both links and "Play both" are back')

    // 4. A 404 on the sim side only.
    simStatus = 404
    await page.goto(at('vt'), { waitUntil: 'networkidle' })
    await page.goto(at(itemHash), { waitUntil: 'networkidle' })
    await pair.locator('[data-testid=vt-media-error]').waitFor({ timeout: 5000 }).catch(() => {})
    seen = await inPair()
    check(seen.stale === 0, 'a 404 is not reported as "changed"')
    check(seen.errors === 1 && /Could not load: HTTP 404/.test(seen.text), 'the refused side says "Could not load: HTTP 404"')
    check(seen.videos === 1, `the other side still plays (${seen.videos} player)`)
  }

  // 5. MediaView: a text write-up whose GET answers 409.
  const doc = await page.evaluate(async () => {
    const body = await (await fetch('/api/plugins/vibetracks/projection')).json()
    for (const track of body.tracks) {
      for (const items of Object.values(track.evidence?.by_iteration ?? {})) {
        for (const item of items) {
          const media = item.media ?? []
          const texts = media.filter((entry) => entry.kind === 'text')
          if (texts.length === 1 && media.length === 1) return { track: track.id, item: item.id, id: texts[0].id }
        }
      }
    }
    return null
  })
  if (!doc) {
    console.log('no item with a single text write-up: MediaView step skipped')
  } else {
    await page.route(`**/api/plugins/vibetracks/media/${encodeURIComponent(doc.id)}*`, (route) =>
      route.fulfill({ status: 409, contentType: 'application/json', body: '{"error":"changed since shown"}' }).catch(() => {}),
    )
    await page.goto(at(`vt?track=${encodeURIComponent(doc.track)}&item=${encodeURIComponent(doc.item)}`), { waitUntil: 'networkidle' })
    const view = page.locator('[data-testid=vt-a-item] [data-testid=vt-media-view]').first()
    await view.locator('[data-testid=vt-media-stale]').waitFor({ timeout: 5000 }).catch(() => {})
    check((await view.locator('[data-testid=vt-media-stale]').count()) === 1, "MediaView: a text write-up's 409 shows the stale line")
    check((await view.locator('a').count()) === 0 && (await view.locator('[data-testid=vt-media-text]').count()) === 0, 'MediaView: no "Open in new tab" and no text under it')
  }
} catch (error) {
  check(false, `the journey ran (${error instanceof Error ? error.message.split('\n')[0] : error})`)
} finally {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)
