// node:test check for the calm colour rule on the Needs-you variants N1-N6, variant A and the shared language.
// Run: node --experimental-strip-types --test /home/bam/vibetracks-dashboard/clank/src/needs/calmColour.check.mjs
// WHY `.check.mjs` and not `.test.mjs`: a peer's vitest run picks up *.test.* and would run this under its own loader.
//
// The rule (calm.css header; Codex audit 2026-10-04 #13 and 2026-10-05 round 2 finding 7): colour only for exceptions.
// The accent blue is left for the keyboard focus ring ONLY; recommendation tags, selected chips, draft bubbles,
// completion meters, ticked settings and data ink are ordinary states and stay grey. Round 2 found N4's recommended tag
// and N5's chips, tag, rule and meter still blue after round 1 fixed the charts: this check reads every stylesheet and
// inline style in those trees and fails on any accent use outside a :focus-visible outline, so the next one cannot
// slip in unnoticed. (Variants B and C are separate compositions with their own rules and are not scanned here.)

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = new URL('..', import.meta.url).pathname
const ROOTS = [join(SRC, 'needs'), join(SRC, 'variants/a'), join(SRC, 'shared')]

function files(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) files(path, out)
    else if (/\.(css|tsx|ts)$/.test(name)) out.push(path)
  }
  return out
}

/** Every `selector { body }` rule in a stylesheet, comments removed, nested blocks (@layer, @media) flattened. */
function rules(css) {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const out = []
  const stack = []
  let start = 0
  for (let i = 0; i < clean.length; i++) {
    if (clean[i] === '{') {
      stack.push({ selector: clean.slice(start, i).trim(), at: i + 1 })
      start = i + 1
    } else if (clean[i] === '}') {
      const open = stack.pop()
      if (open && !open.selector.startsWith('@')) out.push({ selector: open.selector, body: clean.slice(open.at, i) })
      start = i + 1
    } else if (clean[i] === ';') {
      // A declaration (or an @import) ends: the next selector starts after it.
      start = i + 1
    }
  }
  return out
}

/** The token definitions themselves (`--vt-accent: #…`) are allowed; every USE must be a focus ring. */
function accentUses(css) {
  const bad = []
  for (const rule of rules(css)) {
    for (const declaration of rule.body.split(';')) {
      if (!/var\(--vt-accent/.test(declaration)) continue
      if (/^\s*--vt-accent(-soft)?\s*:/.test(declaration)) continue
      const property = declaration.split(':')[0].trim()
      const focusRing = /:focus-visible/.test(rule.selector) && /^outline(-color)?$/.test(property)
      if (!focusRing) bad.push(`${rule.selector.replace(/\s+/g, ' ')} { ${declaration.trim()} }`)
    }
  }
  return bad
}

test('the accent colours only keyboard focus rings in N1-N6, variant A and the shared calm language', () => {
  const offenders = []
  for (const root of ROOTS) {
    for (const path of files(root)) {
      const text = readFileSync(path, 'utf8')
      if (path.endsWith('.css')) {
        for (const use of accentUses(text)) offenders.push(`${relative(SRC, path)}: ${use}`)
      } else {
        // Inline styles and SVG attributes: any var(--vt-accent…) in code (comments mentioning it are fine).
        const code = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
        if (/var\(--vt-accent/.test(code)) offenders.push(`${relative(SRC, path)}: inline accent`)
      }
    }
  }
  assert.deepEqual(offenders, [])
})

test('the oracle can fail: an accent tag, chip or meter is caught', () => {
  assert.equal(accentUses('@layer base { .a .n4-tag-rec { color: var(--vt-accent); background: var(--vt-accent-soft); } }').length, 2)
  assert.equal(accentUses(".x .chip[aria-pressed='true'] { box-shadow: 0 0 0 1px var(--vt-accent); }").length, 1)
  assert.equal(accentUses('.x .meter > span { background: var(--vt-accent); }').length, 1)
  assert.equal(accentUses('.x .opt:focus-visible { outline: 2px solid var(--vt-accent); }').length, 0)
  assert.equal(accentUses('.vt-dash { --vt-accent: #2383e2; --vt-accent-soft: rgba(1,2,3,.1); }').length, 0)
})
