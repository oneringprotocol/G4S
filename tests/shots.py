"""Headless walk-through: every day, both tabs, replay; reports page errors and banned wording.

Usage: python3 tests/shots.py [base_url] [out_dir]
Uses Brave/Chrome if Playwright's own Chromium is not installed.
"""
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "tests/out")
OUT.mkdir(parents=True, exist_ok=True)
BANNED = re.compile(r"operations sheet|ops sheet|\bdepot\b|\byard\b|sheet ?1|not confirmed|after hours|[A-Za-z]-[A-Za-z]|[A-Za-z]'[A-Za-z]", re.I)
BROWSERS = ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]

errors = []
with sync_playwright() as p:
    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    try:
        br = p.chromium.launch()
    except Exception:
        br = p.chromium.launch(executable_path=exe)
    for scheme in ("light", "dark"):
        pg = br.new_page(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
        pg.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        pg.on("console", lambda m: m.type == "error" and errors.append("console: %s" % m.text))
        pg.goto(BASE + "/?d=2026-10-14")
        pg.wait_for_selector(".trip", timeout=20000)
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(OUT / ("route_%s.png" % scheme)))
        if scheme == "dark":
            continue
        days = pg.eval_on_selector_all("#daysel option", "o => o.map(x => x.value)")
        for d in days:
            pg.select_option("#daysel", d)
            pg.wait_for_function("d => window.location.search.includes(d)", arg=d)
            pg.wait_for_selector(".trip")
            txt = pg.inner_text("body")
            for m in BANNED.finditer(txt):
                errors.append("wording on %s: ...%s..." % (d, txt[max(m.start() - 30, 0):m.end() + 30].replace("\n", " ")))
        pg.select_option("#daysel", "2026-10-14")
        pg.wait_for_timeout(800)
        pg.click(".kpi.oz")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(OUT / "route_outside.png"))
        pg.click(".kpi.oz")
        pg.click(".trip[data-n='2']")
        pg.wait_for_timeout(1200)
        pg.screenshot(path=str(OUT / "route_trip2.png"))
        pg.click("#m-replay")
        pg.wait_for_timeout(500)
        pg.click("#rp-play")
        pg.wait_for_timeout(4000)
        pg.screenshot(path=str(OUT / "replay.png"))
        pg.click("#rp-play")
        pg.click("#tab-mileage")
        pg.wait_for_selector("#chart svg", timeout=20000)
        pg.wait_for_timeout(800)
        txt = pg.inner_text("body")
        for m in BANNED.finditer(txt):
            errors.append("wording on mileage: ...%s..." % txt[max(m.start() - 30, 0):m.end() + 30].replace("\n", " "))
        pg.screenshot(path=str(OUT / "mileage.png"), full_page=True)
        pg.set_viewport_size({"width": 390, "height": 844})
        pg.click("#tab-route")
        pg.wait_for_timeout(1500)
        sw = pg.evaluate("document.documentElement.scrollWidth")
        if sw > 391:
            errors.append("horizontal scroll at phone width: %d px" % sw)
        pg.screenshot(path=str(OUT / "phone.png"))
    br.close()

print("\n".join(errors) if errors else "OK: no page errors, no banned wording")
sys.exit(1 if errors else 0)
