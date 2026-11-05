#!/usr/bin/env python3
"""Browser half of `make demo-check`: drives the built UI in headless Chromium. Usage: demo_check_browser.py URL SCREENS_DIR

Prints one line per check: `PASS|FAIL|SKIP <name> | <detail>`. Needs Playwright and a Chromium it can launch
(PLAYWRIGHT_BROWSERS_PATH is honoured). Exit status is non-zero if any check failed.
"""

from __future__ import annotations

import re
import os
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

expect.set_options(timeout=45_000)  # expect() has its own timeout; headless software rendering is slow
URL = sys.argv[1]
SHOTS = Path(sys.argv[2])
failed = 0


def report(status: str, name: str, detail: str = "") -> None:
    global failed
    failed += status == "FAIL"
    print(f"{status} {name} | {detail}".rstrip(" |"), flush=True)


PAGE: list[Page] = []


def step(name: str, fn):
    try:
        report("PASS", name, fn() or "")
        return True
    except Exception as exc:  # noqa: BLE001
        lines = [ln.strip() for ln in str(exc).strip().splitlines() if ln.strip()]
        detail = " / ".join(lines[:3]) if lines else type(exc).__name__
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
        try:
            PAGE[0].screenshot(path=str(SHOTS / f"FAIL-{slug}.png"))
            detail += f" (screenshot FAIL-{slug}.png)"
        except Exception:  # noqa: BLE001
            pass
        report("FAIL", name, detail[:400])
        return False


def shot(page: Page, name: str) -> None:
    page.screenshot(path=str(SHOTS / f"{name}.png"))


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("DEMO_CHECK_BROWSER_EXECUTABLE"), args=["--enable-unsafe-swiftshader"])
        # Reduced motion also stops the streaming particles that keep Cesium rendering, which frees the CPU the physics
        # tools need (a saturated CPU makes the planner roughly 7x slower and can pass their 30 s limit).
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, reduced_motion="reduce")
        page.set_default_timeout(45_000)
        PAGE.append(page)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        def on_console(m):
            if m.type != "error":
                return
            try:  # the format string alone ("%s ...") hides what React is complaining about
                text = " | ".join(str(a.json_value())[:200] for a in m.args) or m.text
            except Exception:  # noqa: BLE001
                text = m.text
            errors.append(f"console: {text[:500]} at {m.location}")

        page.on("console", on_console)

        def load():
            page.goto(URL, wait_until="load")
            expect(page.get_by_text("All results limited: seed data")).to_be_visible()
            expect(page.get_by_role("button", name="Ask the agent to plan")).to_be_enabled()
            saved = page.locator("select").filter(has=page.locator("option", has_text="demo-check supported-limited"))
            saved.select_option(label="demo-check supported-limited")
            expect(page.get_by_text("Overall AMBER", exact=True).first).to_be_visible()
            shot(page, "01-loaded")
            return "app loaded against the services; seed-data banner visible"

        def sources():
            expect(page.get_by_label("Data sources")).to_be_visible()
            text = page.get_by_label("Data sources").inner_text().lower()
            assert "unavailable" in text and "mock" in text, "source states should include mock and unavailable"
            assert "waves" in text and "never shown as zero" in text
            return "waves, wake and telemetry say unavailable; environment says mock"

        def lines():
            text = page.locator("aside").first.inner_text()
            assert re.search(r"\bL?1\b", text), "no lines listed"
            return "lines listed with their analysis"

        def intake():
            page.get_by_role("button", name="Assess conditions").click()
            expect(page.get_by_text("Mooring condition")).to_be_visible(timeout=90_000)
            text = page.locator("aside").first.inner_text()
            assert "MST" in text and "Deterministic summary" in text, "intake result should state MST and where the summary came from"
            shot(page, "02a-intake")
            return "intake assessment shown with MST, windows and a labeled deterministic summary"

        def plan():
            attempts = 0
            for attempts in range(1, 4):
                page.get_by_role("button", name="Ask the agent to plan").click()
                expect(page.get_by_role("button", name=re.compile("Create safety sheet|Rebuild safety sheet"))).to_be_visible(timeout=150_000)
                text = page.locator("aside").first.inner_text().lower()
                # Under software-rendered WebGL the CPU is scarce and a physics tool can pass its 30 s limit; the UI says
                # so plainly and the user just asks again. Unloaded, the same plan finishes in a few seconds.
                if "exceeded its" not in text and "took too long" not in text:
                    break
                if attempts == 3:
                    raise AssertionError("the planner timed out three times in a row")
                page.wait_for_timeout(3000)
            shot(page, "02-plan")
            note = f" (took {attempts} attempts: transient timeout under CPU load)" if attempts > 1 else ""
            return f"planner ran (SSE steps), plan applied to the canvas{note}"

        def sheet():
            dialog = page.get_by_role("dialog").first
            attempts = 0
            for attempts in range(1, 4):
                page.get_by_role("button", name=re.compile("Create safety sheet|Rebuild safety sheet")).click()
                try:
                    expect(dialog).to_be_visible(timeout=75_000)
                    break
                except AssertionError:
                    # The physics tools can exceed their 30 s limit while software-rendered WebGL holds the CPU; the UI
                    # shows a readable error and the button stays available, so retry like a user would.
                    if attempts == 3:
                        raise
                    page.wait_for_timeout(3000)
            shot(page, "03-sheet")
            dialog.locator("input").first.fill("Demo Check")
            dialog.get_by_role("button", name="Approve", exact=True).click()
            expect(dialog.get_by_text(re.compile(r"approval\(s\) recorded"))).to_be_visible()
            expect(dialog.get_by_role("button", name=re.compile("print", re.I))).to_be_enabled(timeout=30_000)
            shot(page, "04-approved")
            note = f" (took {attempts} attempts: transient service timeout)" if attempts > 1 else ""
            return f"sheet rendered, approval recorded, print available{note}"

        def motion_replay():
            page.get_by_role("button", name="Close", exact=True).first.click()
            page.get_by_role("button", name="Open motion view").click()
            page.get_by_role("button", name="Replay recording").click()
            view = page.get_by_role("dialog", name="Motion view")
            expect(view.get_by_text(re.compile("validity: limited", re.I))).to_be_visible()
            expect(view.get_by_text(re.compile("MOCK", re.I)).first).to_be_visible()
            expect(view.get_by_text(re.compile("rm0-v1", re.I))).to_be_visible()
            view.get_by_role("button", name="Play", exact=True).click()
            page.wait_for_timeout(4000)
            text = view.inner_text()
            assert "Ocean swell: unavailable" in text, "wave components must read unavailable"
            assert "not simulated" in text.lower(), "heave must read not simulated"
            shot(page, "05-motion-replay")
            return "replay shows validity, provenance, schema badges; waves unavailable; heave not simulated"

        def motion_map():
            view = page.get_by_role("dialog", name="Motion view")
            view.get_by_role("button", name="Map 2D/3D").click()
            expect(view.get_by_text(re.compile("Not drawn:.*roll and pitch"))).to_be_visible()
            view.get_by_role("button", name="Port quarter").click()
            page.wait_for_timeout(2500)
            shot(page, "05a-motion-map-3d")
            view.get_by_role("button", name="Top", exact=True).click()
            page.wait_for_timeout(1500)
            view.get_by_role("button", name="Plan", exact=True).click()
            expect(view.get_by_text("Forces on the ship")).to_be_visible()
            return "map mode draws the frame in Cesium (3D port-quarter and top), lists what it did not draw, and returns to plan"

        def motion_live():
            view = page.get_by_role("dialog", name="Motion view")
            view.get_by_role("button", name="Start session").click()
            expect(view.get_by_text(re.compile("live session", re.I))).to_be_visible()
            expect(view.get_by_role("button", name="Resume")).to_be_enabled(timeout=30_000)
            view.get_by_role("button", name="Resume").click()
            page.wait_for_timeout(3500)
            seconds = 0.0
            for _ in range(40):
                m = re.search(r"Time\s+(\d+\.\d) s", view.inner_text())
                seconds = float(m.group(1)) if m else 0.0
                if seconds > 1.0:
                    break
                page.wait_for_timeout(500)
            assert seconds > 1.0, f"simulation time did not advance (read {seconds} s)"
            shot(page, "06-motion-live")
            view.get_by_role("button", name="Pause", exact=True).click()
            view.get_by_role("button", name="Reset", exact=True).click()
            page.wait_for_timeout(1500)
            shot(page, "07-motion-reset")
            return "live session ran through the WebSocket proxy: resume, pause, reset"

        def units():
            page.get_by_role("button", name="Close", exact=True).first.click()
            page.get_by_role("button", name="Metric").click()
            page.get_by_role("button", name="Open motion view").click()
            expect(page.get_by_role("dialog", name="Motion view")).to_be_visible()
            text = page.get_by_role("dialog", name="Motion view").inner_text()
            assert re.search(r"\d\s?m\b", text) or "kN" in text, "metric units not applied in the motion view"
            page.get_by_role("button", name="Close", exact=True).first.click()
            page.get_by_role("button", name="Navy").click()
            return "Navy/Metric toggle applies to the motion view"

        def vision():
            # A real (small) image on disk is needed for the file chooser.
            img = SHOTS / "01-loaded.png"
            page.get_by_label("Berth image").set_input_files(str(img))
            page.get_by_role("button", name="Analyze image").click()
            expect(page.get_by_text("draft: needs your confirmation")).to_be_visible()
            confirm = page.get_by_role("button", name="Confirm and use this berth")
            assert confirm.is_disabled(), "confirm must stay disabled until flagged items are ticked"
            # One pass in the page: there can be dozens of flagged items and each Playwright click is slow here.
            page.evaluate("() => document.querySelectorAll('input[type=checkbox]').forEach((el) => { if (!el.checked) el.click(); })")
            shot(page, "08-vision-review")
            assert confirm.is_enabled(), "confirm should open once every flagged item is ticked"
            confirm.click()
            expect(page.get_by_role("status").filter(has_text="Saved")).to_be_visible()
            page.wait_for_timeout(2000)
            shot(page, "09-vision-saved")
            expect(page.get_by_text(re.compile("berth data: estimated", re.I))).to_be_visible()
            return "image analyzed, flagged items gated the confirm button, berth saved and selected, labeled with estimated catalog provenance (no pixel extraction claimed)"

        step("Load the app and see the standing seed-data banner", load)
        step("Data-source panel is honest", sources)
        step("Analyzed lines are listed", lines)
        step("Intake agent assessment", intake)
        if step("Phase 1: agent plans (SSE steps)", plan):
            step("Phase 1: safety sheet, approval and print", sheet)
        if step("Motion: open the view and replay the recording", motion_replay):
            step("Motion: Cesium map mode with 3D camera presets", motion_map)
            step("Motion: live session through the proxy", motion_live)
            step("Motion: units toggle", units)

        step("Berth vision: upload, review, confirm, use", vision)

        def clean():
            real = [e for e in errors if "GL Driver" not in e]
            assert not real, f"{len(real)} browser errors, first: {real[0]}"
            return "no page errors or console errors"

        step("No browser errors during the whole flow", clean)
        browser.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
