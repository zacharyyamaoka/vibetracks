"""Smoke-test every Storybook story headlessly: no page error, no console error, a non-empty root, play passed.

Reads Storybook's own /index.json (so a new story is covered without a list here), opens each story's iframe in
headless Chrome, waits for Storybook to report the story rendered (and its play function, if any, finished), then
fails the story on any uncaught page error, any console error, a failed play, or an empty #storybook-root. Writes one
screenshot per story and summary.json into the output directory.

Run (Storybook already serving on 6006):
  cd ~/vibetracks-roadmap/clank && uv run --no-project --with playwright==1.55.0 python stories/smoke.py

WHY channel="chrome": Playwright's bundled Chromium is not installed on this machine; the system Chrome is.
WHY the iframe and not the manager UI: the question is "does each component render on its fixture", and the iframe is
exactly that page with nothing of Storybook's chrome around it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_OUT = Path("/home/bam/vibetracks/reports/media/vibetracks-storybook-2026-10-05")

# Storybook's preview signals, read off the iframe's own channel: a story is done when it rendered and, if it has a
# play function, the play function finished; an exception or a failed play is reported on the same channel.
WAIT_FOR_STORY = """
(storyId) => new Promise((resolve) => {
  const preview = window.__STORYBOOK_PREVIEW__;
  const channel = window.__STORYBOOK_ADDONS_CHANNEL__;
  const done = (status, detail) => resolve({ status, detail: detail ? String(detail).slice(0, 2000) : null });
  if (!channel) return done('no-channel');
  setTimeout(() => done('timeout', 'no storyRendered within 45 s'), 45000);
  channel.on('storyRendered', (id) => { if (!id || id === storyId) done('rendered'); });
  channel.on('storyErrored', (error) => done('errored', error && (error.description || error.title)));
  channel.on('storyThrewException', (error) => done('threw', error && (error.message || error)));
  channel.on('playFunctionThrewException', (error) => done('play-threw', error && (error.message || error)));
  channel.on('storyMissing', () => done('missing'));
  // Already rendered before we attached: Storybook keeps the render phase on its preview's story render.
  const render = preview && preview.currentRender;
  if (render && render.phase === 'completed') done('rendered');
  if (render && render.phase === 'errored') done('errored', 'render phase errored');
})
"""


def is_browser_favicon(url: str) -> bool:
    """WHY this one URL is not a story error: Chrome itself asks the first page of a context for /favicon.ico, and
    Storybook's iframe serves none; no component makes that request, so it says nothing about the story."""

    return url.split("?", 1)[0].endswith("/favicon.ico")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:6006", help="Storybook base URL (dev server or a static build served over http)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the screenshots and summary.json go")
    parser.add_argument("--only", default="", help="substring filter on story ids")
    parser.add_argument(
        "--allow-missing-fixtures",
        action="store_true",
        help="pass a story that shows the 'Fixture missing' line (by default that fails: the component was never drawn)",
    )
    parser.add_argument("--settle-ms", type=int, default=1200, help="wait after render for async loads and glides")
    args = parser.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=1)
        index_page = context.new_page()
        index = index_page.request.get(f"{args.url}/index.json").json()
        index_page.close()
        stories = [entry for entry in index["entries"].values() if entry.get("type") == "story" and args.only in entry["id"]]
        stories.sort(key=lambda entry: entry["id"])
        for entry in stories:
            story_id = entry["id"]
            page = context.new_page()
            page_errors: list[str] = []
            console_errors: list[str] = []
            failed_requests: list[str] = []
            page.on("pageerror", lambda error, sink=page_errors: sink.append(str(error)))
            page.on(
                "console",
                lambda message, sink=console_errors: sink.append(f"{message.text} @ {message.location.get('url', '')}")
                if message.type == "error" and not is_browser_favicon(message.location.get("url", ""))
                else None,
            )
            page.on(
                "response",
                lambda response, sink=failed_requests: sink.append(f"{response.status} {response.url}") if response.status >= 400 else None,
            )
            t0 = time.time()
            page.goto(f"{args.url}/iframe.html?id={story_id}&viewMode=story", wait_until="domcontentloaded", timeout=60_000)
            try:
                outcome = page.evaluate(WAIT_FOR_STORY, story_id)
            except Exception as error:  # noqa: BLE001 - a hung or crashed page is a failed story, reported as such
                outcome = {"status": "timeout", "detail": str(error)[:500]}
            page.wait_for_timeout(args.settle_ms)
            root_text = page.evaluate("() => (document.querySelector('#storybook-root')?.innerText || '').trim()")
            root_children = page.evaluate("() => document.querySelector('#storybook-root')?.childElementCount || 0")
            # The decorator's "Fixture missing" line (stories/decorators.tsx): the story rendered, but not the component.
            fixture_missing = page.evaluate("() => document.querySelector('[data-testid=story-fixture-missing]')?.dataset.missing ?? null")
            shot = out / f"{story_id}.png"
            page.screenshot(path=str(shot), full_page=False)
            problems = []
            if outcome["status"] != "rendered":
                problems.append(f"story {outcome['status']}: {outcome.get('detail')}")
            if page_errors:
                problems.append(f"page errors: {page_errors}")
            if console_errors:
                problems.append(f"console errors: {console_errors}")
            if failed_requests:
                problems.append(f"failed requests: {failed_requests}")
            if fixture_missing and not args.allow_missing_fixtures:
                problems.append(f"fixture missing: {fixture_missing} (capture with stories/capture_fixtures.py)")
            if root_children == 0 or not root_text:
                problems.append("empty #storybook-root")
            results.append(
                {
                    "id": story_id,
                    "title": entry["title"],
                    "name": entry["name"],
                    "ok": not problems,
                    "problems": problems,
                    "root_text_chars": len(root_text),
                    "fixture_missing": fixture_missing,
                    "ms": round((time.time() - t0) * 1000),
                    "screenshot": str(shot),
                }
            )
            note = f"  (fixture missing: {fixture_missing})" if fixture_missing else ""
            print(f"{'PASS' if not problems else 'FAIL'}  {entry['title']} / {entry['name']}{note}" + (f"\n      {problems}" if problems else ""), flush=True)
            page.close()
        browser.close()

    passed = sum(1 for result in results if result["ok"])
    summary = {
        "storybook": args.url,
        "stories": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "fixture_missing": sum(1 for result in results if result["fixture_missing"]),
        "seconds": round(time.time() - started, 1),
        "out": str(out),
        "results": results,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\n{passed} of {len(results)} stories passed ({summary['fixture_missing']} showing \"Fixture missing\") in {summary['seconds']} s; summary {out / 'summary.json'}")
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
