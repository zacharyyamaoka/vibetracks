// A media view refused for an ordinary reason (404, 403) recovers on "reload" once the file is back, while the
// projection keeps the SAME revision. On the REAL item page of a running lane.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/media_recover.mjs   (SKIPs cleanly without a lane or browser)
//
// What it pins (Codex audit 2026-10-05 round 4, finding 2): useMediaRefusals re-asked only 409 refusals after an
// accepted projection, so a 404 or 403 seen once stayed for good, even with the file restored and the revision
// unchanged (a reload keeps the same urls, so nothing else asks again). A write-up's own GET had the same hole.
//   1. VideoPair, sim side 404 -> restored -> its "reload" -> both players, no refusal line, same revision
//   2. the same with 403
//   3. VideoPair, real 409 + sim 404 (the stale line's reload, the control 611ad59 already had) -> restored -> both
//      players, no refusal line. This is the step that fails on 611ad59 without depending on the new control.
//   4. MediaView (a report frame, HEAD-checked) 404 -> restored -> reload -> the frame, no refusal line
//   5. MediaView (a text write-up, its own GET) 403 -> restored -> reload -> the text, no refusal line
// Every answer is made up in the browser: /projection is the lane's real answer pinned to one media_rev (so "same
// revision" is a fact of the run, not a hope), and /media answers whatever each step says. No lane file is read
// through a made-up revision and nothing is written.

import { at, check, finish, openLane } from './_lane.mjs'

const NAME = 'media_recover'
const { browser, page } = await openLane(NAME)

const REV = 'rev-same'
const status = new Map() // media id -> status the next answer gets (200 when absent)
const media = (id) => `**/api/plugins/vibetracks/media/${encodeURIComponent(id)}*`

try {
  const revisionsServed = []
  await page.route('**/api/plugins/vibetracks/projection*', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    body.media_rev = REV
    revisionsServed.push(REV)
    await route.fulfill({ response, json: body })
  })

  await page.goto(at('vt'), { waitUntil: 'networkidle' })
  const targets = await page.evaluate(async () => {
    const body = await (await fetch('/api/plugins/vibetracks/projection')).json()
    const found = {}
    for (const track of body.tracks) {
      for (const items of Object.values(track.evidence?.by_iteration ?? {})) {
        for (const item of items) {
          const list = item.media ?? []
          const videos = list.filter((m) => m.kind === 'video')
          const real = videos.find((m) => /^real\b/i.test(m.label))
          const sim = videos.find((m) => /^sim\b/i.test(m.label))
          if (!found.pair && real && sim) found.pair = { track: track.id, item: item.id, real: real.id, sim: sim.id }
          if (!found.html && list.length === 1 && list[0].kind === 'html') found.html = { track: track.id, item: item.id, id: list[0].id }
          if (!found.text && list.length === 1 && list[0].kind === 'text') found.text = { track: track.id, item: item.id, id: list[0].id }
        }
      }
    }
    return found
  })
  const ids = [targets.pair?.real, targets.pair?.sim, targets.html?.id, targets.text?.id].filter(Boolean)
  for (const id of ids) {
    await page.route(media(id), (route) => {
      const code = status.get(id) ?? 200
      const head = route.request().method() === 'HEAD'
      if (code === 200) {
        return route.fulfill({ status: 200, contentType: id === targets.text?.id ? 'text/plain; charset=utf-8' : id === targets.html?.id ? 'text/html' : 'video/mp4', body: head ? '' : id === targets.text?.id ? 'restored write-up' : '' }).catch(() => {})
      }
      return route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify({ error: `made-up ${code}` }) }).catch(() => {})
    })
  }
  let projectionReads = 0
  page.on('request', (request) => {
    if (/\/api\/plugins\/vibetracks\/projection$/.test(new URL(request.url()).pathname)) projectionReads++
  })
  // WHY 20 s waits: on this shared box (load average 60+ with other sessions' runs) a 5 s wait timed out before the
  // refusal line rendered, failing a correct build; the wait is only an upper bound, so a fast run is unaffected.
  const hashOf = (target) => `vt?track=${encodeURIComponent(target.track)}&item=${encodeURIComponent(target.item)}`
  const revsIn = (locator) =>
    locator.evaluate((root) => [...root.querySelectorAll('[src*="/media/"], [href*="/media/"]')].map((el) => new URL(el.getAttribute('src') ?? el.getAttribute('href'), location.href).searchParams.get('rev')))
  // Open a fresh page state at `hash`: leave to the tracks page first so every view mounts and asks anew.
  const openAt = async (hash) => {
    await page.goto(at('vt'), { waitUntil: 'networkidle' })
    await page.goto(at(hash), { waitUntil: 'networkidle' })
  }
  const pressReload = async (scope, testId) => {
    const before = projectionReads
    const button = testId ? scope.locator(`[data-testid=${testId}]`).first() : scope.getByRole('button', { name: 'reload' }).first()
    if (!(await button.count())) return { pressed: false, reads: 0 }
    await button.click()
    await page.waitForTimeout(1500)
    return { pressed: true, reads: projectionReads - before }
  }

  if (!targets.pair) {
    check(false, 'the projection has an item with a real|sim video pair')
  } else {
    const pair = page.locator('[data-testid=vt-a-item] [data-testid=vt-a-pair]').first()
    const seen = async () => ({
      videos: await pair.locator('video').count(),
      errors: await pair.locator('[data-testid=vt-media-error]').count(),
      stale: await pair.locator('[data-testid=vt-media-stale]').count(),
      text: ((await pair.textContent()) ?? '').replace(/\s+/g, ' '),
    })

    // 1 and 2: one ordinary refusal on the sim side, then the file comes back under the same revision.
    for (const code of [404, 403]) {
      status.clear()
      status.set(targets.pair.sim, code)
      await openAt(hashOf(targets.pair))
      await pair.locator('[data-testid=vt-media-error]').waitFor({ timeout: 20000 }).catch(() => {})
      let state = await seen()
      check(state.errors === 1 && state.text.includes(`Could not load: HTTP ${code}`), `${code}: the sim side says "Could not load: HTTP ${code}"`)
      const revBefore = await revsIn(pair)
      status.set(targets.pair.sim, 200)
      const reload = await pressReload(pair, 'vt-media-reload')
      check(reload.pressed, `${code}: the refusal line offers "reload"`)
      check(reload.reads >= 1, `${code}: "reload" re-reads /projection (${reload.reads})`)
      await pair.locator('video').nth(1).waitFor({ timeout: 20000 }).catch(() => {})
      state = await seen()
      const revAfter = await revsIn(pair)
      check(revAfter.length > 0 && revAfter.every((rev) => rev === REV) && revBefore.every((rev) => rev === REV), `${code}: the revision is unchanged across the reload (${JSON.stringify([...new Set(revAfter)])})`)
      check(state.videos === 2 && state.errors === 0 && state.stale === 0, `${code}: after the file is back and "reload", both players show and no refusal line (videos ${state.videos}, errors ${state.errors}, stale ${state.stale})`)
    }

    // 3: a 409 beside a 404; the stale line's reload must recover BOTH once both files open.
    status.clear()
    status.set(targets.pair.real, 409)
    status.set(targets.pair.sim, 404)
    await openAt(hashOf(targets.pair))
    await pair.locator('[data-testid=vt-media-stale]').waitFor({ timeout: 20000 }).catch(() => {})
    check((await seen()).stale === 1, '409 + 404: the pair shows the stale line')
    status.clear()
    const reload = await pressReload(pair, null)
    check(reload.pressed && reload.reads >= 1, `409 + 404: the stale line's "reload" re-reads /projection (${reload.reads})`)
    await pair.locator('video').nth(1).waitFor({ timeout: 20000 }).catch(() => {})
    const state = await seen()
    check(state.videos === 2 && state.errors === 0 && state.stale === 0, `409 + 404: both players back, no refusal line (videos ${state.videos}, errors ${state.errors}, stale ${state.stale}: "${state.text.slice(0, 90)}")`)
  }

  // 4: MediaView over a report frame (HEAD-checked).
  if (!targets.html) {
    console.log('no item with a single report: MediaView frame step skipped')
  } else {
    status.clear()
    status.set(targets.html.id, 404)
    await openAt(hashOf(targets.html))
    const view = page.locator('[data-testid=vt-a-item] [data-testid=vt-media-view]').first()
    await view.locator('[data-testid=vt-media-error]').waitFor({ timeout: 20000 }).catch(() => {})
    check((await view.locator('[data-testid=vt-media-error]').count()) === 1, 'report 404: MediaView says "Could not load"')
    status.clear()
    const reload = await pressReload(view, 'vt-media-reload')
    check(reload.pressed && reload.reads >= 1, `report 404: its "reload" re-reads /projection (${reload.reads})`)
    await view.locator('iframe').waitFor({ timeout: 20000 }).catch(() => {})
    check((await view.locator('iframe').count()) === 1 && (await view.locator('[data-testid=vt-media-error]').count()) === 0, 'report 404 -> restored -> reload: the frame shows, no refusal line')
    check((await revsIn(view)).every((rev) => rev === REV), 'report: the revision is unchanged')
  }

  // 5: MediaView over a text write-up (its own GET, no HEAD).
  if (!targets.text) {
    console.log('no item with a single text write-up: text step skipped')
  } else {
    status.clear()
    status.set(targets.text.id, 403)
    await openAt(hashOf(targets.text))
    const view = page.locator('[data-testid=vt-a-item] [data-testid=vt-media-view]').first()
    await view.locator('[data-testid=vt-media-error]').waitFor({ timeout: 20000 }).catch(() => {})
    check(/Could not load: HTTP 403/.test((await view.textContent()) ?? ''), 'write-up 403: MediaView says "Could not load: HTTP 403"')
    status.clear()
    const reload = await pressReload(view, 'vt-media-reload')
    check(reload.pressed && reload.reads >= 1, `write-up 403: its "reload" re-reads /projection (${reload.reads})`)
    await view.locator('[data-testid=vt-media-text]').waitFor({ timeout: 20000 }).catch(() => {})
    check((await view.locator('[data-testid=vt-media-text]').textContent().catch(() => null)) === 'restored write-up' && (await view.locator('[data-testid=vt-media-error]').count()) === 0, 'write-up 403 -> restored -> reload: the text shows, no refusal line')
  }
  check(revisionsServed.every((rev) => rev === REV), 'every /projection answer carried the same revision')
} catch (error) {
  check(false, `the journey ran (${error instanceof Error ? error.message.split('\n')[0] : error})`)
} finally {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)
