"""Interaction checks for the liveness chrome, driven against a real panel.

Not collected by `unittest discover` (that only picks up `test*.py`) because it
needs a browser. It builds its own track — one `running` claim that went quiet
47 minutes ago, one claimed two minutes ago — serves it on an ephemeral port,
drives it, and tears everything down, so it is repeatable:

    uv run --isolated --with playwright python tests/browser_liveness.py
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import expect, sync_playwright  # noqa: E402

from vibetracks.server import VibeTracksApplication, VibeTracksHandler  # noqa: E402

PROJECT_ID = "liveness-demo"

DESCRIPTOR = f"""filters:
  and:
    - 'note["vibe-track"] == "feature"'
    - 'file.inFolder("features")'
vibetracks:
  id: {PROJECT_ID}
  title: Liveness demo
  description: "One honest claim and one that went quiet."
  source: features
  areas:
    canvas: Selection, movement, viewport
    docs: The durable reasoning trail
"""

# (id, status, area, title, seconds since the file last changed)
NOTES = [
    ("F-1", "running", "canvas", "Rebuild the selection overlay", 47 * 60),
    ("F-2", "running", "canvas", "Zoom-invariant handles", 2 * 60),
    ("F-3", "review", "docs", "Write up the canvas pass", 60),
    ("F-4", "backlog", "docs", "Retire the old gallery", 5 * 60 * 60),
]

CHECKS: list[str] = []


def check(label: str, condition: bool) -> None:
    CHECKS.append(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        print("\n".join(CHECKS))
        raise AssertionError(label)


def build_track(root: Path) -> Path:
    (root / "features").mkdir(parents=True)
    descriptor = root / "Project.vibetrack"
    descriptor.write_text(DESCRIPTOR, encoding="utf-8")
    now = time.time()
    for feature_id, status, area, title, age in NOTES:
        note = root / "features" / f"{feature_id}.md"
        note.write_text(
            f"---\nvibe-track: feature\nvibe-id: {feature_id}\nvibe-status: {status}\n"
            f"vibe-areas: [{area}]\n---\n# {title}\n\nDurable context lives here.\n",
            encoding="utf-8",
        )
        os.utime(note, (now - age, now - age))
    return descriptor


@contextmanager
def panel(descriptor: Path):
    application = VibeTracksApplication(descriptor)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(VibeTracksHandler, application=application))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run(base: str, root: Path) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        # ---- deep links -------------------------------------------------
        page.goto(base + "#focus")
        expect(page.locator(".view-heading h2")).to_have_text("Focus", timeout=15_000)
        check("#focus deep link opens the Focus view", True)

        page.goto(base + "#kanban/canvas")
        expect(page.locator(".view-heading h2")).to_have_text("Kanban", timeout=10_000)
        expect(page.locator("#area-filters .area-chip.active")).to_have_text("canvas")
        check("#kanban/<area> opens that view scoped to that track", True)
        check("a scoped link shows only that lane", page.locator(".feature-row").count() == 2)

        page.locator('#area-filters .area-chip[data-area="docs"]').click()
        page.wait_for_function("() => location.hash === '#kanban/docs'", timeout=5_000)
        check("changing the area rewrites the deep link", True)

        page.goto(base + "#kanban")
        expect(page.locator("#area-filters .area-chip.active")).to_have_text("All areas")
        check("a link with no area means unfiltered, not 'whatever was selected'", True)

        # ---- staleness --------------------------------------------------
        expect(page.locator(".pulse-item.alarm")).to_have_text("1 stale running", timeout=10_000)
        stale_card = page.locator(".ticket", has=page.locator(".stale-tag"))
        check("exactly one card is marked stale", stale_card.count() == 1)
        check("the stale card is the quiet running claim",
              "Rebuild the selection overlay" in stale_card.inner_text())
        fresh_running = page.locator(".ticket", has_text="Zoom-invariant handles")
        check("a recently touched running claim is not marked stale",
              fresh_running.locator(".stale-tag").count() == 0)
        check("cards carry an age", page.locator(".ticket .age").count() == len(NOTES))
        check("the running metric names the stale count",
              "stale" in page.locator(".metric.warn").inner_text())

        # ---- what is new since you looked --------------------------------
        page.evaluate(
            f"() => localStorage.setItem('vibetracks.lastSeen.{PROJECT_ID}',"
            " String(Date.now() - 30 * 60 * 1000))")
        page.reload()
        news = page.locator('[data-pulse="fresh"]')
        expect(news).to_have_text("2 new since you looked", timeout=10_000)
        check("the board counts what changed since the last look", True)

        news.click()
        expect(news).to_have_class("pulse-item news active", timeout=5_000)
        check("the new-work chip filters the board down",
              page.locator(".feature-row").count() == 2)
        news.click()
        check("clicking it again restores the whole board",
              page.locator(".feature-row").count() == len(NOTES))

        page.locator('[data-pulse="seen"]').click()
        expect(page.locator('[data-pulse="fresh"]')).to_have_count(0, timeout=5_000)
        check("marking the board seen clears the new markers", True)
        check("and clears the per-card dots", page.locator(".fresh-dot").count() == 0)

        # ---- a file changing on disk reappears as new --------------------
        note = root / "features" / "F-4.md"
        note.write_text(note.read_text(encoding="utf-8") + "\nTouched by the browser check.\n",
                        encoding="utf-8")
        expect(page.locator('[data-pulse="fresh"]')).to_have_text(
            "1 new since you looked", timeout=15_000)
        check("a note edited on disk shows up as new within one poll", True)

        browser.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        descriptor = build_track(root)
        with panel(descriptor) as base:
            run(base, root)
    print("\n".join(CHECKS))
    print(f"\n{len(CHECKS)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
