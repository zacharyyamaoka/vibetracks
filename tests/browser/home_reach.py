"""Every live session stays reachable (r3, 2026-10-09): the replacement for two checks of B1's frozen
tests/browser/home_page.py that encode behaviour Zach removed on Oct 9 ("you have made agents too primary. Agents
work on tracks"; "Other sessions should not be collapsed … like in claude"):

- B1 "an 'Other sessions' toggle is on the page": the home's "Sessions on no track" section is gone; each of those
  sessions is now its own sidebar row (under its project after the tracks, or under Other).
- B1 "every live session is on the page" (with the default display): sessions under tracks are off by default now;
  each track row counts its agents and links to the track page's Agents tab.

So "none is ever dropped" (docs/peps/0001 §4) is measured where the sessions now live:

1. every live session no track matches is a sidebar row (``vt-side-session``);
2. every live session a track matched is a row of that track's Agents tab (``vt-track-agent``);
3. with Display > "Show sessions under tracks" turned ON explicitly, every matched live session is a home row again;
4. together they cover every live session in the document the page itself fetched (never a fixture).

    uv run --no-project --with playwright==1.55.0 python tests/browser/home_reach.py [URL]

URL defaults to $VT_HOME_URL, else http://127.0.0.1:4481/api/plugins/vibetracks/home/. An unreachable URL or a
missing browser is a SKIP (exit 0, said loudly), never a pass.
"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:4481/api/plugins/vibetracks/home/"
DEFAULT_CHROME = "/home/bam/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
failures = 0


def check(ok: bool, message: str) -> None:
    global failures
    print(f"{'ok  ' if ok else 'FAIL'} {message}", flush=True)
    if not ok:
        failures += 1


def ready(page) -> None:
    page.wait_for_selector('[data-testid="vt-home"][data-ready="1"]', timeout=120_000)
    page.wait_for_timeout(400)


def main(argv: list[str]) -> int:
    url = argv[0] if argv else os.environ.get("VT_HOME_URL", DEFAULT_URL)
    chrome = os.environ.get("CHROME", DEFAULT_CHROME)
    if not Path(chrome).exists():
        print(f"SKIP home_reach: no browser at {chrome}")
        return 0
    try:
        urllib.request.urlopen(url, timeout=10).read()
    except Exception as error:  # noqa: BLE001
        print(f"SKIP home_reach: page not reachable at {url} ({error})")
        return 0
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome, headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(15_000)
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url, wait_until="domcontentloaded")
            ready(page)
            doc = page.evaluate("window.__vtHomeDoc")
            tracks = [t for p in doc["projects"] for t in p["tracks"]]
            matched = {s["id"]: t["id"] for t in tracks for s in t["sessions"] if s["live"]}
            other = {s["id"] for s in doc["other_sessions"] if s["live"]}

            side = set(page.evaluate("() => [...document.querySelectorAll('[data-testid=\"vt-side-session\"]')].map((e) => e.dataset.sessionId)"))
            check(other <= side, f"1. every live session on no track is a sidebar row ({len(other & side)} of {len(other)}; "
                                 f"missing {sorted(other - side)[:4]})")

            in_tabs: set[str] = set()
            for track_id in sorted(set(matched.values())):
                page.goto(url + f"#/track/{track_id}?tab=agents", wait_until="domcontentloaded")
                ready(page)
                page.wait_for_selector('[data-testid="vt-track-agents"]')
                in_tabs |= set(page.evaluate("() => [...document.querySelectorAll('[data-testid=\"vt-track-agent\"]')].map((e) => e.dataset.sessionId)"))
            check(set(matched) <= in_tabs, f"2. every live session a track matched is on that track's Agents tab "
                                          f"({len(set(matched) & in_tabs)} of {len(matched)}; missing {sorted(set(matched) - in_tabs)[:4]})")

            page.goto(url + "#/", wait_until="domcontentloaded")
            ready(page)
            page.click('[data-testid="vt-home-display-button"]')
            toggle = '[data-testid="vt-home-display"] [data-act="toggle"][data-id="subs"]'
            if page.get_attribute(toggle, "aria-pressed") != "true":
                page.click(toggle)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            rows = set(page.evaluate("() => [...document.querySelectorAll('[data-testid=\"vt-home-session\"]')].map((e) => e.dataset.sessionId)"))
            check(set(matched) <= rows, f"3. with 'Show sessions under tracks' on, every matched live session is a home row "
                                       f"({len(set(matched) & rows)} of {len(matched)})")

            everything = set(matched) | other
            reachable = side | in_tabs | rows
            check(bool(everything) and everything <= reachable,
                  f"4. every live session in the document is reachable ({len(everything & reachable)} of {len(everything)})")
            check(not errors, f"no page errors {errors[:3] if errors else ''}")
        finally:
            browser.close()
    print(f"home_reach: {'FAIL (' + str(failures) + ')' if failures else 'PASS'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
