"""The home fits its window at every desktop width (r3, 2026-10-09), written before the fix. Found on live Stable
(main d0b4b5a) by the home-variants agent: at 1280 px the Rows grid overflows its columns, at 1100 px the page scrolls
sideways; 390 px (the phone layout) is fine.

    uv run --no-project --with playwright==1.55.0 python tests/browser/home_widths.py [URL]

At 1440, 1280, 1100 and 900 px wide (dark, the default 288 px sidebar), in each of Rows, Table, Board and Cards:

- the page never scrolls sideways (``scrollWidth <= clientWidth`` on the document);
- in Rows and Table, every row's visible cells sit inside the header grid's box, and each column (``c-*``) starts at one
  x on every row (the columns stay aligned after lower-priority ones drop out);
- at 1280 px with the sidebar dragged to its widest (480 px), the same holds: column drops follow the space the page
  actually has, not only the window.

URL defaults to $VT_HOME_URL, else http://127.0.0.1:4481/api/plugins/vibetracks/home/. An unreachable URL or a
missing browser is a SKIP (exit 0, said loudly), never a pass.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:4481/api/plugins/vibetracks/home/"
DEFAULT_CHROME = "/home/bam/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
WIDTHS = (1440, 1280, 1100, 900)
failures = 0

MEASURE = """() => {
  const doc = document.documentElement;
  const out = {scroll: doc.scrollWidth, client: doc.clientWidth, outside: [], columns: {}};
  const head = document.querySelector('.tree .thead');
  if (head) {
    const box = head.getBoundingClientRect();
    for (const row of [head, ...document.querySelectorAll('.tree .tr')]) {
      for (const cell of row.children) {
        const cs = getComputedStyle(cell);
        const r = cell.getBoundingClientRect();
        if (cs.display === 'none' || r.width === 0) continue;
        if (r.left < box.left - 0.5 || r.right > box.right + 0.5) out.outside.push([row.dataset.trackId || row.className, cell.className, Math.round(r.left), Math.round(r.right), Math.round(box.right)]);
        const k = [...cell.classList].find((c) => c.startsWith('c-'));
        if (k) (out.columns[k] = out.columns[k] || new Set()).add(Math.round(r.left));
      }
      if (row.scrollWidth > row.clientWidth + 1) out.outside.push([row.dataset.trackId || row.className, 'row content wider than the row', row.scrollWidth, row.clientWidth]);
    }
  }
  out.columns = Object.fromEntries(Object.entries(out.columns).map(([k, v]) => [k, [...v]]));
  return out;
}"""


def check(ok: bool, message: str) -> None:
    global failures
    print(f"{'ok  ' if ok else 'FAIL'} {message}", flush=True)
    if not ok:
        failures += 1


def ready(page) -> None:
    page.wait_for_selector('[data-testid="vt-home"][data-ready="1"]', timeout=120_000)
    page.wait_for_timeout(500)


def measure(page, tag: str) -> None:
    for key, view in (("1", "rows"), ("2", "table"), ("3", "board"), ("4", "cards")):
        page.keyboard.press(key)
        page.wait_for_timeout(250)
        m = page.evaluate(MEASURE)
        check(m["scroll"] <= m["client"], f"{tag} {view}: no sideways scroll (scrollWidth {m['scroll']} vs clientWidth {m['client']})")
        if view in ("rows", "table"):
            check(not m["outside"], f"{tag} {view}: every cell inside the header grid {json.dumps(m['outside'][:3])}")
            misaligned = {k: v for k, v in m["columns"].items() if len(v) != 1}
            check(m["columns"] and not misaligned, f"{tag} {view}: each column starts at one x on every row {json.dumps(misaligned or sorted(m['columns']))}")


def main(argv: list[str]) -> int:
    url = argv[0] if argv else os.environ.get("VT_HOME_URL", DEFAULT_URL)
    chrome = os.environ.get("CHROME", DEFAULT_CHROME)
    if not Path(chrome).exists():
        print(f"SKIP home_widths: no browser at {chrome}")
        return 0
    try:
        urllib.request.urlopen(url, timeout=10).read()
    except Exception as error:  # noqa: BLE001
        print(f"SKIP home_widths: page not reachable at {url} ({error})")
        return 0
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome, headless=True)
        try:
            for width in WIDTHS:
                ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme="dark")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.goto(url, wait_until="domcontentloaded")
                ready(page)
                measure(page, f"[{width}]")
                check(not errors, f"[{width}] no page errors {errors[:2] if errors else ''}")
                ctx.close()
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
            ctx.add_init_script("try { const s = JSON.parse(localStorage.getItem('vt-home-ui-v1') || '{}'); s.v = 2; s.sideW = 480; "
                                "localStorage.setItem('vt-home-ui-v1', JSON.stringify(s)); } catch (e) {}")
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")
            ready(page)
            side = page.evaluate("document.querySelector('[data-testid=vt-home-sidebar]').getBoundingClientRect().width")
            check(abs(side - 480) < 1, f"[1280 + 480 px sidebar] the sidebar is at its widest ({side})")
            measure(page, "[1280 + 480 px sidebar]")
            ctx.close()
        finally:
            browser.close()
    print(f"home_widths: {'FAIL (' + str(failures) + ')' if failures else 'PASS'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
