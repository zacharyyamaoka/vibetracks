"""Assert that no declaration authored in roadmap.css is discarded by the cascade, in the real Storybook.

WHY (Codex/recorder, 2026-10-05): shared/calm.css resets every `.vt-btn` with `.vt-dash button.vt-btn { all: unset }`
(specificity 0,2,1). A roadmap rule with fewer than that (`.vt-dash .vt-rm-mini`, 0,2,0) is silently wiped, whatever
its declarations say, so the Lineage rows lost their flex layout. Reading the stylesheet cannot find this, rendering can.

How: for every element that an `all:` reset matches, take the properties the roadmap's own rules set on it, read their
computed values as rendered, then read them again with the `all` reset removed from the cascade (the intended result:
the roadmap's rule beats the reset's defaults). A property that differs is an authored declaration the reset discarded.
Hover/focus rules are not matched (the check does not hover).

Run (Storybook already serving on 6006), from any directory:
  uv run --no-project --with playwright==1.55.0 python /home/bam/vibetracks-roadmap/clank/src/roadmap/cascade_check.py
Set STORYBOOK_URL to use another port. Options: --css PATH renders with that stylesheet text instead of the current roadmap.css (to see a previous revision:
  git show HEAD:clank/src/roadmap/roadmap.css > /tmp/old.css); --shots DIR also saves one screenshot per story.
Exit 0 when nothing is discarded and every roadmap button class the source renders was seen; 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

STORYBOOK = os.environ.get("STORYBOOK_URL", "http://127.0.0.1:6006")
HERE = Path(__file__).resolve().parent

# Runs in the story iframe. Returns one record per (element, discarded property).
PROBE = r"""
(cssOverride) => {
  const viteSheet = [...document.querySelectorAll('style')].find((s) => (s.getAttribute('data-vite-dev-id') || '').endsWith('roadmap/roadmap.css'))
  if (cssOverride !== null && viteSheet) viteSheet.textContent = cssOverride
  // Style rules of one sheet, through @layer / @supports blocks and the @media blocks that apply.
  const flatten = (rules, out) => {
    for (const rule of rules) {
      if (rule.selectorText !== undefined) out.push(rule)
      else if (rule.media && !window.matchMedia(rule.media.mediaText).matches) continue
      else if (rule.cssRules) flatten(rule.cssRules, out)
    }
    return out
  }
  const all = []
  for (const sheet of document.styleSheets) {
    let rules
    try { rules = flatten(sheet.cssRules, []) } catch { continue }
    const own = viteSheet ? sheet.ownerNode === viteSheet : false
    for (const rule of rules) all.push({ rule, own: own || (!viteSheet && /vt-rm-/.test(rule.selectorText)) })
  }
  const authored = all.filter((entry) => entry.own).map((entry) => entry.rule)
  // Chrome keeps `all: unset` as an item named `all` in rule.style (its value reads as empty), beside the other
  // declarations of the same rule (box-sizing, cursor, font, colour).
  const resets = all.filter((entry) => [...entry.rule.style].includes('all')).map((entry) => entry.rule)
  const matches = (el, rule) => { try { return el.matches(rule.selectorText) } catch { return false } }
  const found = []
  for (const el of document.querySelectorAll('.vt-dash *')) {
    const reset = resets.filter((rule) => matches(el, rule))
    if (!reset.length) continue
    const props = new Set()
    const autoMargin = new Set()
    for (const rule of authored) {
      if (!matches(el, rule)) continue
      for (const name of rule.style) {
        props.add(name)
        if (name.startsWith('margin') && rule.style.getPropertyValue(name) === 'auto') autoMargin.add(name)
      }
    }
    if (!props.size) continue
    const cs = getComputedStyle(el)
    const actual = new Map([...props].map((name) => [name, cs.getPropertyValue(name)]))
    // Lift only `all` (the rule's own box-sizing, cursor, font and colour stay, so layout is the same); put it back
    // first in the declaration order afterwards, because a later `all` would wipe the declarations before it.
    const saved = reset.map((rule) => [rule, [...rule.style].filter((name) => name !== 'all').map((name) => [name, rule.style.getPropertyValue(name), rule.style.getPropertyPriority(name)])])
    for (const [rule] of saved) rule.style.removeProperty('all')
    const intended = new Map([...props].map((name) => [name, getComputedStyle(el).getPropertyValue(name)]))
    for (const [rule, others] of saved) {
      for (const [name] of others) rule.style.removeProperty(name)
      rule.style.setProperty('all', 'unset')
      for (const [name, value, priority] of others) rule.style.setProperty(name, value, priority)
    }
    const classes = [...el.classList].filter((name) => name.startsWith('vt-rm-') || name === 'vt-btn')
    // A plain `.vt-btn` (a tab, a lens toggle) is named by the roadmap container it sits in.
    const parent = el.parentElement && el.parentElement.closest('[class*="vt-rm-"]')
    const within = parent ? [...parent.classList].find((name) => name.startsWith('vt-rm-')) : null
    if (within && classes.length === 1) classes.push(`in:${within}`)
    for (const name of props) {
      // An `auto` margin computes to the free space, which the button's UA chrome (the lifted reset's side effect) shifts;
      // it is discarded only when it collapsed to 0.
      const differs = autoMargin.has(name) ? actual.get(name) === '0px' && intended.get(name) !== '0px' : actual.get(name) !== intended.get(name)
      if (differs) found.push({ classes: classes.join('.'), tag: el.tagName.toLowerCase(), testid: el.getAttribute('data-testid'), prop: name, actual: actual.get(name), intended: intended.get(name) })
    }
    el.setAttribute('data-cascade-seen', classes.join('.'))
  }
  const seen = [...new Set([...document.querySelectorAll('[data-cascade-seen]')].map((el) => el.getAttribute('data-cascade-seen')))]
  return { found, seen, authored: authored.length, resets: resets.length }
}
"""


def story_ids(page_request) -> list[str]:
    entries = page_request.get(f"{STORYBOOK}/index.json").json()["entries"]
    return [key for key in entries if key.startswith("roadmap-") or key == "dashboard-variant-a--track-page-kinsim-roadmap-open"]


def rendered_button_classes() -> set[str]:
    """Every `vt-rm-*` class the roadmap source puts on a `vt-btn` (what the stories must between them exercise)."""
    found: set[str] = set()
    for source in HERE.glob("*.tsx"):
        for match in re.finditer(r'className="vt-btn ([^"]*)"|className=\{`vt-btn ([^`$]*)', source.read_text()):
            for name in (match.group(1) or match.group(2)).split():
                if name.startswith("vt-rm-"):
                    found.add(name)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--css", type=Path, default=None)
    parser.add_argument("--shots", type=Path, default=None)
    parser.add_argument("--stories", default=None, help="comma-separated story ids to run instead of every roadmap story")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    override = args.css.read_text() if args.css else None
    by_class: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    seen_classes: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for story in args.stories.split(",") if args.stories else story_ids(p.request.new_context()):
            page = browser.new_page(viewport={"width": 1200, "height": 900})
            try:
                page.goto(f"{STORYBOOK}/iframe.html?id={story}&viewMode=story", timeout=60000)
                page.wait_for_selector(".vt-dash .vt-btn", timeout=12000)
            except Exception as error:
                print(f"SKIPPED {story}: {str(error).splitlines()[0]}", file=sys.stderr)
                page.close()
                continue
            page.wait_for_timeout(700)
            results = [page.evaluate(PROBE, override)]
            if args.shots:
                args.shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(args.shots / f"{story}.png"))
            # Going to a lineage neighbour puts a trail (crumb, back button) on the card; probe that state too.
            neighbour = page.locator(".vt-rm-mini:not(.vt-rm-mini-strong)").first
            if neighbour.count():
                neighbour.click()
                page.wait_for_timeout(500)
                results.append(page.evaluate(PROBE, override))
            for result in results:
                for record in result["found"]:
                    by_class[record["classes"]][record["prop"]].add(f"{record['actual']} (intended {record['intended']})")
                for classes in result["seen"]:
                    seen_classes.update(name for name in classes.split(".") if not name.startswith("in:"))
            page.close()
        browser.close()
    discarded = sum(len(props) for props in by_class.values())
    for classes, props in sorted(by_class.items()):
        print(classes)
        for prop, values in sorted(props.items()):
            print(f"  {prop}: {'; '.join(sorted(values))[:140]}")
    unseen = sorted(rendered_button_classes() - seen_classes)
    print(f"DISCARDED DECLARATIONS: {discarded} across {len(by_class)} class sets")
    print(f"BUTTON CLASSES NOT RENDERED BY ANY STORY (not covered): {unseen or 'none'}")
    if args.json:
        args.json.write_text(json.dumps({"discarded": {c: {p: sorted(v) for p, v in props.items()} for c, props in by_class.items()}, "unseen": unseen}, indent=1))
    return 1 if discarded or unseen else 0


if __name__ == "__main__":
    sys.exit(main())
