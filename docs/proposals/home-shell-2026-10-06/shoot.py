#!/usr/bin/env python3
"""Drive the five prototypes headlessly: stills (1440 + 390), gate measurements, interaction proof, V1 hero video.

    uv run --no-project --with playwright==1.55.0 python /home/bam/vibetracks/reports/media/vibetracks-home-proposals-2026-10-06/shoot.py

Uses the cached Chromium 1243 build (Playwright 1.55's own build is not installed on this box).
Writes media/*.webp, media/hero.webm, media/hero.gif and media/proof.json; run build.py afterwards.
"""
import json
import pathlib
import shutil
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
MEDIA = HERE / "media"
APP = f"file://{HERE / 'app.html'}"
CHROME = "/home/bam/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
VARIANTS = ["v1", "v2", "v3", "v4", "v5"]
TMP = pathlib.Path(tempfile.mkdtemp(prefix="vt-shoot-"))


def webp(png: pathlib.Path, name: str, width: int | None = None, q: int = 72) -> None:
    vf = ["-vf", f"scale={width}:-1:flags=lanczos"] if width else []
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), *vf, "-c:v", "libwebp", "-quality", str(q), str(MEDIA / name)], check=True)


def open_page(browser, w, h, state, rec=False):
    page = browser.new_page(viewport={"width": w, "height": h})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{APP}{'?rec=1' if rec else ''}#{state}")
    page.wait_for_timeout(150)
    return page, errors


def overflow(page) -> dict:
    return page.evaluate("""() => { const m = document.querySelector('.main');
      return { doc: document.documentElement.scrollWidth, vw: innerWidth, main: m ? m.scrollWidth - m.clientWidth : 0 }; }""")


def shoot(page, name, width=None, q=72):
    png = TMP / (name + ".png")
    page.screenshot(path=str(png))
    webp(png, name + ".webp", width, q)
    shutil.copy(png, TMP / ("keep-" + name + ".png"))


def interaction_proof(browser, v) -> dict:
    """g1: every brief element works by REAL clicks, measured from the DOM afterwards."""
    page, errors = open_page(browser, 1440, 900, f"{v}/home")
    r = {}
    q = lambda sel: page.locator(sel).count()
    rows_before = q(".trow, table.ledger tr.click")
    page.click("[data-act=toggle][data-id=bam]")
    r["collapse"] = q(".trow, table.ledger tr.click") < rows_before
    page.click("[data-act=toggle][data-id=bam]")
    r["expand"] = q(".trow, table.ledger tr.click") == rows_before
    page.click("[data-act=view][data-id=board]")
    r["board"] = q(".board, .swim") == 1
    page.click("[data-act=hl][data-id=bam]")
    r["highlight"] = q(".dim") > 0
    page.click("[data-act=hlmode][data-id=filter]")
    r["filter"] = page.evaluate("() => [...document.querySelectorAll('.card, .mini')].length") == 5
    page.click("[data-act=hl][data-id='']")
    page.click("[data-act=view][data-id=rows]")
    r["rows_again"] = q(".board, .swim") == 0
    side_on_home = q(".side") > 0
    page.locator("main [data-act=project][data-id=bam]").first.click()
    r["project_page"] = page.evaluate("() => document.querySelector('.vtp').dataset.page") == "project:bam"
    r["side_on_drill_in"] = q(".side") == 1
    if q(".side.rail"):
        page.hover(".side.rail")
        page.wait_for_timeout(200)
    page.locator(".side [data-act=track][data-id=rig]").click()
    r["track_page_from_side"] = page.evaluate("() => document.querySelector('.vtp').dataset.page") == "track:rig"
    r["back"] = (page.click("[data-act=back]") or True) and page.evaluate("() => document.querySelector('.vtp').dataset.page") == "project:bam"
    page.click("[data-act=home]") if q("main [data-act=home]") == 0 else page.locator("main [data-act=home]").first.click()
    page.locator("[data-act=new]").first.click()
    page.select_option("#vtp-pick", "~/hyper_rgb")
    page.click("[data-act=dlg-add]")
    r["one_folder_default_name"] = page.get_attribute("#vtp-name", "placeholder").startswith("hyper_rgb") and page.is_enabled("[data-act=dlg-create]")
    page.select_option("#vtp-pick", "~/zach_brain")
    page.click("[data-act=dlg-add]")
    r["two_folders_need_name"] = not page.is_enabled("[data-act=dlg-create]")
    page.fill("#vtp-name", "Spectral R&D")
    page.click("[data-act=dlg-create]")
    page.wait_for_timeout(100)
    r["created"] = page.locator("main", has_text="Spectral R&D").count() > 0 or page.locator(".side", has_text="Spectral R&D").count() > 0
    r["note_sidebar_on_home"] = "yes" if side_on_home else "no"
    # Oct 6 feedback features, by real clicks / drags
    page.goto(f"{APP}#{v}/home/board"); page.reload(); page.wait_for_timeout(150)
    page.click("[data-act=hl][data-id=bbt]"); page.click("[data-act=hlmode][data-id=filter]")
    src = page.locator("[draggable=true][data-id=bbt]").first
    dst = page.locator("[data-drop=done]").first
    src.drag_to(dst, target_position={'x': 60, 'y': 40}); page.wait_for_timeout(150)
    r["drag_to_done"] = page.evaluate("() => VTP.T.bbt.state") == "done"
    r["board_has_done_and_archived"] = page.locator("[data-drop=done]").count() > 0 and page.locator("[data-drop=archived]").count() > 0
    page.goto(f"{APP}#{v}/track/grasping"); page.reload(); page.wait_for_timeout(150)
    if page.locator("[data-act=tab][data-id=overview]").count():
        page.click("[data-act=tab][data-id=overview]")
    r["kpi_small_multiples"] = page.locator(".mcell").count() == 4 and page.locator(".gate").count() == 3
    if page.locator("[data-act=tab][data-id=experiments]").count():
        page.click("[data-act=tab][data-id=experiments]")
    page.locator(".xnode[data-id=g07]").click()
    r["experiment_detail"] = "Reject grasps" in page.locator(".xdetail").inner_text()
    if page.locator("[data-act=tab][data-id=auditor]").count():
        page.click("[data-act=tab][data-id=auditor]")
    r["auditor_rounds"] = page.locator(".around").count() == 3
    page.goto(f"{APP}#{v}/track/vt-exp"); page.reload(); page.wait_for_timeout(150)
    if page.locator("[data-act=tab][data-id=overview]").count():
        page.click("[data-act=tab][data-id=overview]")
    r["discover_optimize_locked"] = page.is_disabled("[data-act=mode][data-v=optimize]")
    page.locator("[data-act=prop][data-v=yes]").first.click()
    r["discover_accept_unlocks"] = page.is_enabled("[data-act=mode][data-v=optimize]")
    page.goto(f"{APP}#{v}/project/bam"); page.reload(); page.wait_for_timeout(150)
    r["lead_lag_chart"] = page.locator("svg[aria-label^='North star']").count() == 1
    r["errors"] = errors
    page.close()
    return r


def scale_proof(browser, v) -> dict:
    page, _ = open_page(browser, 1440, 900, f"{v}/home")
    page.click("[data-act=scale]")
    page.wait_for_timeout(100)
    m = page.evaluate("""() => { const main = document.querySelector('.main'); const H = innerHeight;
      const rows = [...new Set([...document.querySelectorAll('.st.st-needs, .bi.needs')].map(e => e.closest('.trow, tr.click, .bi, .card')).filter(Boolean))];
      const ids = new Set(rows.map(r => r.dataset.id));
      const above = new Set(rows.filter(r => { const t = r.getBoundingClientRect().top; return t > 0 && t < H - 20; }).map(r => r.dataset.id));
      return { pageHeight: main.scrollHeight, screens: +(main.scrollHeight / H).toFixed(1), needsTracks: ids.size, needsTracksAboveFold: above.size }; }""")
    page.click("[data-act=view][data-id=board]")
    page.wait_for_timeout(100)
    m["boardSidewaysPx"] = page.evaluate("() => { const b = document.querySelector('.board, .swim'); const sc = b.closest('.tscroll') || b; return sc.scrollWidth - sc.clientWidth; }")
    page.close()
    return m


def gate_widths(browser, v) -> dict:
    out = {}
    for label, state in [("home", f"{v}/home"), ("board", f"{v}/home/board"), ("project", f"{v}/project/bam"), ("track", f"{v}/track/rig")]:
        for w, h in [(390, 844), (1440, 900)]:
            page, errors = open_page(browser, w, h, state)
            o = overflow(page)
            out[f"{label}@{w}"] = {"ok": o["doc"] <= o["vw"] and o["main"] <= 1, **o, "errors": errors}
            page.close()
    return out


def hero(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(TMP / "vid"), record_video_size={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.goto(f"{APP}?rec=1#v1/home")
    page.wait_for_timeout(300)

    def glide(sel, click=True, pause=700, nth=0):
        box = page.locator(sel).nth(nth).bounding_box()
        page.mouse.move(box["x"] + min(box["width"] / 2, 60), box["y"] + box["height"] / 2, steps=18)
        page.wait_for_timeout(120)
        if click:
            page.mouse.down(); page.mouse.up()
        page.wait_for_timeout(pause)

    page.mouse.move(640, 300)
    page.wait_for_timeout(1000)
    glide("[data-act=view][data-id=board]", pause=700)
    glide("[data-act=hl][data-id=bbt]", pause=350)
    glide("[data-act=hlmode][data-id=filter]", pause=500)
    src = page.locator("[draggable=true][data-id=bbt]").first.bounding_box()
    dst = page.locator("[data-drop=done]").first.bounding_box()
    page.mouse.move(src["x"] + 60, src["y"] + 30, steps=12); page.wait_for_timeout(120)
    page.mouse.down(); page.mouse.move(src["x"] + 90, src["y"] + 40, steps=4); page.mouse.move(dst["x"] + 80, dst["y"] + 60, steps=20); page.wait_for_timeout(120); page.mouse.up()
    page.wait_for_timeout(1100)
    glide("[data-act=hl][data-id='']", pause=300)
    glide("[data-act=view][data-id=rows]", pause=400)
    glide("main [data-act=project][data-id=bam]", pause=1600)
    glide(".side [data-act=track][data-id=grasping]", pause=1200)
    glide("[data-act=tab][data-id=experiments]", pause=700)
    glide(".xnode[data-id=g07]", pause=900)
    glide("[data-act=tab][data-id=auditor]", pause=1000)
    glide(".side [data-act=track][data-id=rig]", pause=800)
    glide("main [data-act=session]", pause=1500)
    video = page.video.path()
    ctx.close()
    raw = pathlib.Path(video)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(raw), "-vf", "scale=1024:-2:flags=lanczos", "-c:v", "libvpx-vp9", "-crf", "47", "-b:v", "0", "-row-mt", "1", "-an", str(MEDIA / "hero.webm")], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(raw), "-vf",
                    "fps=4,scale=560:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=32:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                    str(MEDIA / "hero.gif")], check=True)


def main():
    MEDIA.mkdir(exist_ok=True)
    proof = {"interactions": {}, "widths": {}, "scale": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        for v in VARIANTS:
            for label, state in [("home", f"{v}/home"), ("board", f"{v}/home/board"), ("project", f"{v}/project/bam"), ("track", f"{v}/track/rig")]:
                page, _ = open_page(browser, 1440, 900, state)
                shoot(page, f"{v}-{label}", width=1100, q=60)
                page.close()
            page, _ = open_page(browser, 390, 844, f"{v}/home")
            shoot(page, f"{v}-phone", q=60)
            page.close()
            page, _ = open_page(browser, 390, 844, f"{v}/track/rig")
            shoot(page, f"{v}-phone-track", q=70)
            page.close()
            proof["interactions"][v] = interaction_proof(browser, v)
            proof["widths"][v] = gate_widths(browser, v)
            proof["scale"][v] = scale_proof(browser, v)
        for name, state in [("feat-experiments", "v1/track/grasping/experiments"), ("feat-auditor", "v1/track/rig/auditor"), ("feat-discover", "v1/track/vt-exp")]:
            page, _ = open_page(browser, 1440, 900, state)
            if name == "feat-experiments":
                page.locator(".xnode[data-id=g07]").click(); page.wait_for_timeout(100)
            shoot(page, name, width=1100, q=62)
            page.close()
        # shared: the Codex-style New project dialog, with two folders added and a custom name
        page, _ = open_page(browser, 1440, 900, "v1/home")
        page.click("[data-act=new]")
        page.select_option("#vtp-pick", "~/bam_ws"); page.click("[data-act=dlg-add]")
        page.select_option("#vtp-pick", "~/clank-workbench"); page.click("[data-act=dlg-add]")
        page.select_option("#vtp-pick", "~/viser-3d-viewer"); page.click("[data-act=dlg-add]")
        page.fill("#vtp-name", "BAM Robotics")
        page.wait_for_timeout(100)
        shoot(page, "dialog", width=1200, q=72)
        page.close()
        page, _ = open_page(browser, 1440, 900, "v1/home")
        page.click("[data-act=scale]")
        for pid in ["bam", "ctv", "pyblocks", "vt", "bbox", "bbt", "syn0", "syn1", "syn2", "syn3"]:
            page.click(f"[data-act=toggle][data-id={pid}]")
        shoot(page, "v1-scale-collapsed", width=1200, q=70)
        page.close()
        hero(browser)
        browser.close()
    (MEDIA / "proof.json").write_text(json.dumps(proof, indent=1))
    for v in VARIANTS:
        bad = [k for k, x in proof["interactions"][v].items() if x is False]
        wbad = [k for k, x in proof["widths"][v].items() if not x["ok"]]
        print(v, "interactions FAIL:" if bad else "interactions ok", bad, "| widths FAIL:" if wbad else "| widths ok", wbad, "| scale", proof["scale"][v])
    print("tmp pngs:", TMP)


if __name__ == "__main__":
    main()
