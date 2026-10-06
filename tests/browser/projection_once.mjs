// The dashboard reads /projection once on first load, however many dashboards Clank keeps mounted.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/projection_once.mjs   (SKIPs cleanly without a lane or browser)
//
// What it pins (verifier, 2026-10-05, item b): one first load started four /projection reads (React's double effect
// times the two mounted viewers: Clank keeps a second one in a hidden tab). Two were aborted and two completed, so the
// backend did two full live builds for one page open. useProjection now shares one in-flight read per backend and
// per kind (read | rebuild), through the same sharedRequests that useNeeds uses (needs/share.ts). Here the REAL page is
// loaded and every /projection request it sends is counted, then the page must still show what it read.
// A "reload" must still re-read: the second half presses the media view's reload signal and counts exactly one more.

import { at, check, finish, openLane } from './_lane.mjs'

const NAME = 'projection_once'
const { browser, page } = await openLane(NAME, { width: 1440, height: 900 })

try {
  const requests = []
  const failed = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (/\/api\/plugins\/vibetracks\/projection$/.test(url.pathname)) requests.push(`/projection${url.search}`)
  })
  page.on('requestfailed', (request) => {
    if (/\/api\/plugins\/vibetracks\/projection(\?|$)/.test(new URL(request.url()).pathname + new URL(request.url()).search)) failed.push(request.failure()?.errorText ?? '?')
  })
  await page.goto(at('vt'), { waitUntil: 'networkidle' })
  await page.locator('[data-testid=vt-dashboard]').first().waitFor({ timeout: 15000 })
  // WHY a settle wait after networkidle: a late second viewer or a re-run effect would send its request after the first
  // answer; give it time to show up before counting.
  await page.waitForTimeout(2500)
  console.log(`first load: ${JSON.stringify(requests)} (aborted ${failed.length})`)
  check(requests.length === 1, `/projection is requested once on first load (${requests.length})`)
  check(failed.length === 0, `no /projection request is started and then aborted (${failed.length})`)
  const shown = await page.evaluate(() => {
    const dash = document.querySelector('[data-testid=vt-dashboard]')
    const text = dash?.textContent ?? ''
    return Boolean(dash && !/Loading the projection/.test(text) && text.length > 40)
  })
  check(shown, 'the dashboard shows the projection it read (not stuck loading)')

  // A reload is a real re-read: exactly one more request, never answered by the read that finished before it.
  const before = requests.length
  const reloaded = await page.evaluate(async () => {
    const button = document.querySelector('[data-testid=vt-a-reload]')
    if (!(button instanceof HTMLElement)) return false
    button.click()
    return true
  })
  if (reloaded) {
    await page.waitForTimeout(2500)
    const after = requests.slice(before)
    console.log(`after reload: ${JSON.stringify(after)}`)
    check(after.length === 1, `the tracks page's reload re-reads /projection exactly once (${after.length})`)
  } else {
    check(false, 'the tracks page has its reload control (vt-a-reload)')
  }
} catch (error) {
  check(false, `the journey ran (${error instanceof Error ? error.message.split('\n')[0] : error})`)
} finally {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)
