// The needs page reads /needs once on first load, however many dashboards Clank keeps mounted.
// Run: node /home/bam/vibetracks-dashboard/tests/browser/needs_once.mjs   (SKIPs cleanly without a lane or browser)
//
// What it pins (verifier, 2026-10-05): /needs?track=kinsim was fetched about four times at once on first load (React's
// double effect times the mounted viewers). useNeeds now shares one in-flight read per (track | all) key
// (needs/share.ts; its rules are unit-checked in needs/share.check.mjs). Here the REAL page is loaded and every /needs
// request it sends is counted: one per key, and the page still shows the doc it read.

import { at, check, finish, openLane } from './_lane.mjs'

const NAME = 'needs_once'
const { browser, page } = await openLane(NAME, { width: 1440, height: 900 })

try {
  const requests = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (/\/api\/plugins\/vibetracks\/needs$/.test(url.pathname)) requests.push(`${url.pathname.split('/vibetracks')[1]}${url.search}`)
  })
  await page.goto(at('vt?track=kinsim&needs=1'), { waitUntil: 'networkidle' })
  await page.locator('[data-testid=vt-needs]').first().waitFor({ timeout: 15000 })
  // WHY a settle wait after networkidle: a late second viewer or a re-run effect would send its request after the first
  // answer; give it time to show up before counting.
  await page.waitForTimeout(2500)
  const perKey = new Map()
  for (const request of requests) perKey.set(request, (perKey.get(request) ?? 0) + 1)
  console.log(`requests: ${JSON.stringify(Object.fromEntries(perKey))}`)
  check(perKey.get('/needs?track=kinsim') === 1, `/needs?track=kinsim is read once on first load (${perKey.get('/needs?track=kinsim') ?? 0})`)
  check([...perKey.values()].every((count) => count === 1), 'no /needs key is read twice on first load')
  const shown = await page.evaluate(() => {
    const shell = document.querySelector('[data-testid=vt-needs]')
    return Boolean(shell && !/Loading/.test(shell.textContent ?? '') && (shell.textContent ?? '').length > 40)
  })
  check(shown, 'the needs page shows the doc it read (not stuck loading)')
} catch (error) {
  check(false, `the journey ran (${error instanceof Error ? error.message.split('\n')[0] : error})`)
} finally {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await browser.close()
}
finish(NAME)
