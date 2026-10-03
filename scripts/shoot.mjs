// Headless proof shot of the dashboard inside the real Clank shell (never a visible window).
//
//   node /home/bam/vibetracks-dashboard/scripts/shoot.mjs [--url http://127.0.0.1:4390/] [--out shot.png]
//        [--variant a|b|c] [--hash '#vt?track=kinsim'] [--click <css>] [--key <key>] [--w 1440] [--h 900] [--wait 1500]
//
// It opens Clank at <url>?vtdash=Agent%20work.vtdash, waits for the dashboard viewer, optionally presses the
// variant switcher and sets a route hash, then screenshots and prints measured facts (variant, data proof, console
// errors) as JSON. WHY measured facts: a screenshot of a page that silently failed to load looks like a calm page.
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require('/home/bam/claude-transcript-viewer/node_modules/playwright-core')

const args = process.argv.slice(2)
const opt = (key, fallback) => {
  const index = args.indexOf(`--${key}`)
  return index >= 0 ? args[index + 1] : fallback
}
const base = opt('url', 'http://127.0.0.1:4390/')
const out = opt('out', '/home/bam/vibetracks-dashboard/docs/dashboard/proof/dashboard.png')
const variant = opt('variant', null)
const hash = opt('hash', '')
const width = Number(opt('w', 1440))
const height = Number(opt('h', 900))
const wait = Number(opt('wait', 1500))
const url = `${base.replace(/\/?$/, '/')}?vtdash=Agent%20work.vtdash${hash}`

const browser = await chromium.launch({
  headless: true,
  executablePath: '/home/bam/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell',
})
const errors = []
try {
  const context = await browser.newContext({ viewport: { width, height } })
  const page = await context.newPage()
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(String(error)))
  const failed = []
  page.on('response', (response) => {
    if (response.status() >= 400) failed.push(`${response.status()} ${response.url().replace(/^https?:\/\/[^/]+/, '')}`)
  })
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="vt-dashboard"]', { timeout: 60000 })
  if (variant) {
    await page.click(`[data-testid="vt-switch-${variant}"]`)
  }
  const click = opt('click', null)
  if (click) {
    await page.waitForTimeout(500)
    await page.locator(click).first().click()
  }
  const key = opt('key', null)
  if (key) {
    await page.locator('[data-testid="vt-dashboard"]').focus()
    await page.keyboard.press(key)
  }
  await page.waitForTimeout(wait)
  const facts = await page.evaluate(() => {
    const root = document.querySelector('[data-testid="vt-dashboard"]')
    const switcher = document.querySelector('[data-testid="vt-switcher"]')
    const box = switcher?.getBoundingClientRect()
    return {
      variant: root?.getAttribute('data-variant') ?? null,
      proof: document.querySelector('[data-testid="vt-data-proof"]')?.textContent ?? null,
      switcher: switcher ? { text: switcher.textContent, right: Math.round(window.innerWidth - (box?.right ?? 0)), bottom: Math.round(window.innerHeight - (box?.bottom ?? 0)) } : null,
      hash: location.hash,
    }
  })
  await page.screenshot({ path: out })
  console.log(JSON.stringify({ url, out, ...facts, errors: errors.filter((e) => !e.startsWith('Failed to load resource')), failedRequests: failed }, null, 1))
} finally {
  await browser.close()
}
