"""Memory and CPU soak test of the CTeI landscape dashboard (Playwright + system Chrome + CDP).

Repeats the tab round trip that used to degrade the page: open the 3D constellation, toggle the
group layout and pick a cluster, go to the thematic system, the map, the matrix and the last tab, and back to the
constellation. After each round it forces a garbage collection and records the JS heap, DOM
nodes and event listeners; it also measures CPU while the constellation is hidden and the
frame rate while it is shown.

Usage (with the dashboard running, e.g. `panoramaCTeI ui --no-open`):
    uv run --no-project --with playwright python tools/qa_memory.py [http://localhost:8000/] [rounds]
Exit 1 if memory keeps growing, the hidden tab still burns CPU or the frame rate collapses.
"""
import os
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/"
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 12
MB = 1024 * 1024


def metrics(cdp):
    cdp.send("HeapProfiler.collectGarbage")
    m = {x["name"]: x["value"] for x in cdp.send("Performance.getMetrics")["metrics"]}
    return {"heap": m["JSHeapUsedSize"] / MB, "nodes": int(m["Nodes"]),
            "listeners": int(m["JSEventListeners"]), "task": m["TaskDuration"]}


def cpu_share(page, cdp, seconds=3):
    """Fraction of one core spent on main-thread tasks while the page sits idle."""
    before = cdp.send("Performance.getMetrics")["metrics"]
    page.wait_for_timeout(seconds * 1000)
    after = cdp.send("Performance.getMetrics")["metrics"]
    task = lambda ms: next(x["value"] for x in ms if x["name"] == "TaskDuration")
    return (task(after) - task(before)) / seconds


def fps(frame, seconds=2):
    return frame.evaluate("""(s) => new Promise(done => { let n = 0; const t0 = performance.now();
      const step = t => { n++; if (t - t0 < s * 1000) requestAnimationFrame(step); else done(n / s); };
      requestAnimationFrame(step); setTimeout(() => done(n / s), s * 1000 + 1500); })""", seconds)


def tab(page, name, wait=900):
    page.click(f"nav button[data-view='{name}']")
    page.wait_for_timeout(wait)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False, args=[
        # The window sits off-screen; keep Chrome from pausing rendering of an occluded window.
        "--window-position=4000,4000", "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding", "--disable-background-timer-throttling"])
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    cdp = page.context.new_cdp_session(page)
    cdp.send("Performance.enable")
    page.goto(BASE + "#sistema")
    page.wait_for_timeout(1500)
    last = page.eval_on_selector_all("nav button[data-view]", "bs => bs[bs.length - 1].dataset.view")
    tab(page, "constelacion", 3000)
    frame = page.frame_locator("#frame3d")
    child = page.frames[1]
    clusters = child.eval_on_selector_all("#famselect option", "os => os.map(o => o.value)")[1:]
    rows = []
    for r in range(ROUNDS):
        frame.locator("#grouplayout").click()
        page.wait_for_timeout(700)
        frame.locator("#famselect").select_option(clusters[r % len(clusters)])
        page.wait_for_timeout(500)
        tab(page, "sistema")
        tab(page, "mapa")
        tab(page, "matriz")
        tab(page, last)
        tab(page, "constelacion", 1200)
        rows.append(metrics(cdp))
        print(f"round {r + 1:2}: heap {rows[-1]['heap']:6.1f} MB  nodes {rows[-1]['nodes']:6}  "
              f"listeners {rows[-1]['listeners']:5}", flush=True)
    shown_fps = fps(child)
    shown_cpu = cpu_share(page, cdp)
    tab(page, "sistema", 2500)
    hidden_cpu = cpu_share(page, cdp)

    # Compare the second half with the first: a leak keeps climbing, a warm cache levels off.
    half = len(rows) // 2
    growth = rows[-1]["heap"] - rows[half]["heap"]
    node_growth = rows[-1]["nodes"] - rows[half]["nodes"]
    listener_growth = rows[-1]["listeners"] - rows[half]["listeners"]
    checks = [
        ("JS heap stable over the last half of the rounds (< 3 MB)", growth < 3, f"{growth:+.1f} MB"),
        ("DOM nodes stable over the last half (< 300)", node_growth < 300, f"{node_growth:+d}"),
        ("event listeners stable over the last half (< 50)", listener_growth < 50, f"{listener_growth:+d}"),
        ("constellation hidden: main thread almost idle (< 5 % of a core)", hidden_cpu < 0.05, f"{hidden_cpu:.1%}"),
        ("constellation shown: smooth animation (>= 40 fps)", shown_fps >= 40, f"{shown_fps:.0f} fps"),
        ("constellation shown: main thread below 60 % of a core", shown_cpu < 0.6, f"{shown_cpu:.1%}"),
        ("no JavaScript errors", not errors, "; ".join(errors)[:200]),
    ]
    for name, ok, detail in checks:
        print(("PASS " if ok else "FAIL ") + name + ": " + detail, flush=True)
    # os._exit: closing Chrome after the CDP soak can hang Playwright; the results are already printed.
    os._exit(0 if all(ok for _, ok, _ in checks) else 1)
