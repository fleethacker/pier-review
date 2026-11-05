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
from urllib.parse import urlparse

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
        allowed_hosts = {"127.0.0.1", "localhost", urlparse(URL).hostname}
        page.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).hostname in allowed_hosts else route.abort())
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        intake_context: dict = {}
        def on_console(m):
            if m.type != "error":
                return
            try:  # the format string alone ("%s ...") hides what React is complaining about
                text = " | ".join(str(a.json_value())[:200] for a in m.args) or m.text
            except Exception:  # noqa: BLE001
                text = m.text
            errors.append(f"console: {text[:500]} at {m.location}")

        page.on("console", on_console)

        def tab(name: str) -> None:
            """The mooring panels live in tabs on the top bar; open the one a step needs."""
            t = page.get_by_role("tab", name=name, exact=True)
            t.click()
            expect(t).to_have_attribute("aria-selected", "true")

        def landing():
            page.goto(URL.rstrip("/") + "/", wait_until="load")
            apps = page.get_by_role("list", name="Applications")
            expect(apps.get_by_role("button", name="Open Mooring Assistant")).to_be_visible()
            expect(apps.get_by_role("button", name="Open Mission simulation")).to_be_visible()
            shot(page, "00-landing")
            apps.get_by_role("button", name="Open Mooring Assistant").click()
            expect(page.get_by_role("tab", name="Setup", exact=True)).to_have_attribute("aria-selected", "true")
            assert "app=mooring" in page.url, page.url
            return "landing page lists Mooring Assistant and Mission simulation; the box opens Mooring Assistant on its Setup tab"

        def load():
            if "app=mooring" not in page.url:
                page.goto(URL.rstrip("/") + "/?app=mooring", wait_until="load")
            expect(page.get_by_text("All results limited: seed data")).to_be_visible()
            tab("Plan & review")
            expect(page.get_by_role("button", name="Ask the agent to plan")).to_be_enabled()
            tab("Setup")
            saved = page.locator("select").filter(has=page.locator("option", has_text="demo-check supported-limited"))
            saved.select_option(label="demo-check supported-limited")
            tab("Lines")
            expect(page.get_by_text("Overall AMBER", exact=True).first).to_be_visible()
            shot(page, "01-loaded")
            return "app loaded against the services; seed-data banner visible"

        def sources():
            tab("Conditions")
            expect(page.get_by_label("Data sources")).to_be_visible()
            text = page.get_by_label("Data sources").inner_text().lower()
            assert "unavailable" in text and "mock" in text, "source states should include mock and unavailable"
            assert "waves" in text and "never shown as zero" in text
            return "waves, wake and telemetry say unavailable; environment says mock"

        def lines():
            tab("Lines")
            text = page.locator("aside").first.inner_text()
            assert re.search(r"\bL?1\b", text), "no lines listed"
            return "lines listed with their analysis"

        def intake():
            tab("Conditions")
            with page.expect_response(lambda r: r.url.endswith("/api/v1/intake/reports") and r.request.method == "POST") as submitted:
                page.get_by_role("button", name="Assess conditions").click()
            response = submitted.value
            assert response.ok, "intake submission failed"
            intake_context["scenario_id"] = response.request.post_data_json["scenario_id"]
            job_id = response.json()["job_id"]
            expect(page.get_by_text("Mooring condition")).to_be_visible(timeout=90_000)
            job = page.request.get(f"{URL}/api/agents/api/v1/jobs/{job_id}").json()
            assert job["state"] == "succeeded", job
            report = job["result"]
            intake_context["report_id"] = report["report_id"]
            assert report["current"]["wind_speed_kt"] == 4 and report["current"]["wind_gust_kt"] == 5, "Intake ignored the saved scenario"
            text = page.locator("aside").first.inner_text()
            assert "MST" in text and "Deterministic summary" in text, "intake result should state MST and where the summary came from"
            shot(page, "02a-intake")
            return "selected scenario assessed with MST, windows and deterministic summary; current wind matches the saved inputs"

        def plan():
            tab("Plan & review")
            attempts = 0
            for attempts in range(1, 4):
                with page.expect_response(lambda r: r.url.endswith("/api/v1/agent/plans") and r.request.method == "POST") as submitted:
                    page.get_by_role("button", name="Ask the agent to plan").click()
                response = submitted.value
                assert response.ok, "plan submission failed"
                body = response.request.post_data_json
                assert body.get("intake_report_id") == intake_context.get("report_id") and body.get("intake_report_id"), "Planner did not receive the displayed Intake report"
                assert body["scenario_id"] == intake_context["scenario_id"], "Planner changed the assessed scenario"
                expect(page.get_by_role("button", name=re.compile("Create safety sheet|Rebuild safety sheet"))).to_be_visible(timeout=150_000)
                text = page.locator("aside").first.inner_text().lower()
                # Under software-rendered WebGL the CPU is scarce and a physics tool can pass its 30 s limit; the UI says
                # so plainly and the user just asks again. Unloaded, the same plan finishes in a few seconds.
                if "exceeded its" not in text and "took too long" not in text:
                    break
                if attempts == 3:
                    raise AssertionError("the planner timed out three times in a row")
                page.wait_for_timeout(3000)
            plan_id = response.json()["plan_id"]
            result = page.request.get(f"{URL}/api/agents/api/v1/agent/plans/{plan_id}").json()
            assert result["status"] == "AMBER" and result["intake_report_id"] == intake_context["report_id"], result
            analysis = page.request.get(f"{URL}/api/modeling/api/v1/results/{result['analysis_result_id']}").json()
            assert analysis["validity"]["state"] == "limited", analysis
            shot(page, "02-plan")
            note = f" (took {attempts} attempts: transient timeout under CPU load)" if attempts > 1 else ""
            return f"planner used the displayed Intake and scenario, returned AMBER/limited, and applied its plan{note}"

        review_context: dict = {}

        def review():
            create = page.get_by_role("button", name=re.compile("Create safety sheet|Rebuild safety sheet"))
            assert create.is_disabled(), "the sheet must not be buildable before the independent review"
            with page.expect_response(lambda r: r.url.endswith("/api/v1/safety/reviews") and r.request.method == "POST") as submitted:
                page.get_by_role("button", name="Run independent review").click()
            response = submitted.value
            assert response.ok, "review submission failed"
            body = response.request.post_data_json
            assert body.get("intake_report_id") == intake_context.get("report_id"), "review was not bound to the Planner's Intake report"
            section = page.get_by_label("Independent safety review")
            expect(section.get_by_text(re.compile(r"^Review \S+ · "))).to_be_visible(timeout=120_000)
            job = page.request.get(f"{URL}/api/agents/api/v1/jobs/{response.json()['job_id']}").json()
            assert job["state"] == "succeeded", job
            result = job["result"]
            assert result["plan_id"] == body["plan_id"], "review is of a different plan"
            review_context.update(review_id=result["review_id"], status=result["status"], verdict=result["verdict"])
            assert result["review_id"] in section.inner_text(), "review identity not shown"
            expect(create).to_be_enabled()
            shot(page, "02b-review")
            return f"independent review {result['status']}/{result['verdict']} bound to the Planner's Intake report; sheet unlocked only after it"

        def sheet():
            dialog = page.get_by_role("dialog").first
            attempts = 0
            for attempts in range(1, 4):
                with page.expect_request(lambda r: r.url.endswith("/api/v1/safety-sheets") and r.method == "POST") as created:
                    page.get_by_role("button", name=re.compile("Create safety sheet|Rebuild safety sheet")).click()
                assert created.value.post_data_json.get("review_id") == review_context.get("review_id"), "sheet was not built from the displayed review"
                try:
                    expect(dialog).to_be_visible(timeout=75_000)
                    break
                except AssertionError:
                    # The physics tools can exceed their 30 s limit while software-rendered WebGL holds the CPU; the UI
                    # shows a readable error and the button stays available, so retry like a user would.
                    if attempts == 3:
                        raise
                    page.wait_for_timeout(3000)
            identity = dialog.get_by_label("Sheet review identity")
            expect(identity).to_contain_text(review_context["review_id"])
            shot(page, "03-sheet")
            dialog.locator("input").first.fill("Demo Check")
            dialog.get_by_role("button", name="Approve", exact=True).click()
            expect(dialog.get_by_text(re.compile(r"approval\(s\) recorded"))).to_be_visible()
            expect(dialog.get_by_role("button", name=re.compile("print", re.I))).to_be_enabled(timeout=30_000)
            shot(page, "04-approved")
            note = f" (took {attempts} attempts: transient service timeout)" if attempts > 1 else ""
            return f"sheet rendered with its review identity, approval recorded, print available{note}"

        def motion_replay():
            page.get_by_role("button", name="Close", exact=True).first.click()
            tab("Motion")
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
            tab("Setup")
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

        step("Landing page: a box per application opens it", landing)
        step("Load the app and see the standing seed-data banner", load)
        step("Data-source panel is honest", sources)
        step("Analyzed lines are listed", lines)
        step("Intake agent assessment", intake)
        if step("Phase 1: agent plans (SSE steps)", plan):
            if step("Phase 1: explicit independent safety review", review):
                step("Phase 1: safety sheet, approval and print", sheet)
        if step("Motion: open the view and replay the recording", motion_replay):
            step("Motion: Cesium map mode with 3D camera presets", motion_map)
            step("Motion: live session through the proxy", motion_live)
            step("Motion: units toggle", units)

        step("Berth vision: upload, review, confirm, use", vision)

        def four_cases():
            base = f"{URL}/api/modeling/api/v1"
            cases = page.request.get(base + "/demo/docking-cases").json()
            for case in cases:
                env = page.request.post(base + "/env/scenarios", data=case["environment_request"]).json()
                body = {**case["scenario_request"], "env_source": {"mode": "scenario", "env_scenario_id": env["env_scenario_id"]}}
                case["saved_id"] = page.request.post(base + "/scenarios", data=body).json()["scenario_id"]
            page.reload(wait_until="load")
            tab("Plan & review")
            expect(page.get_by_role("button", name="Ask the agent to plan")).to_be_enabled()
            for case in cases:
                expected = ("AMBER", "limited") if case["case_id"] == "ddg-supported-limited" else (
                    ("RED", "limited") if case["case_id"] == "ddg-overloaded" else ("RED", "invalid"))
                def matches(r):
                    if not r.url.endswith("/api/v1/mooring/analyze") or r.request.method != "POST":
                        return False
                    body = r.request.post_data_json
                    return (body["environment"]["wind_speed_kt"] == case["environment_request"]["wind_speed_kt"]
                            and body["environment"]["water_level_mllw_ft"] == case["environment_request"]["water_level_mllw_ft"]
                            and len(body["config"]["lines"]) == len(case["analysis_request"]["config"]["lines"]))
                tab("Setup")
                with page.expect_response(matches) as analyzed:
                    page.locator("select").filter(has=page.locator(f"option[value='{case['saved_id']}']")).select_option(case["saved_id"])
                response = analyzed.value
                assert response.ok, f"{case['case_id']} failed with HTTP {response.status}"
                result = response.json()
                assert (result["status"], result["validity"]["state"]) == expected, (case["case_id"], result)
                tab("Lines")
                expect(page.get_by_text(f"Overall {expected[0]}", exact=True).first).to_be_visible()
                if expected[1] == "invalid":
                    expect(page.get_by_text("Line loads unavailable", exact=False).first).to_be_visible()
                shot(page, case["case_id"])
            return "saved supported, overloaded, invalid-depth and underconstrained inputs show their expected initial outcomes; invalid loads withheld"

        step("Four saved-scenario analysis outcomes", four_cases)

        def demo_case_panel():
            tab("Setup")
            panel = page.get_by_label("Demo cases")
            expected = {"ddg-supported-limited": ("AMBER", "limited"), "ddg-overloaded": ("RED", "limited"),
                        "ddg-invalid-data": ("RED", "invalid"), "ddg-undetermined": ("RED", "invalid")}
            cases = page.request.get(f"{URL}/api/modeling/api/v1/demo/docking-cases").json()
            assert {c["case_id"] for c in cases} == set(expected), "unexpected demo case list"
            rows = panel.get_by_role("listitem")
            expect(rows).to_have_count(4)
            outcomes = page.get_by_label("Case outcomes")
            for i, case in enumerate(cases):
                status, validity = expected[case["case_id"]]
                rows.nth(i).get_by_role("button", name=re.compile("^(Load|Reload)$")).click()
                expect(outcomes.get_by_text(f"validity {validity}").first).to_be_visible(timeout=60_000)
                text = outcomes.inner_text().lower()  # labels are uppercased by CSS
                assert "initial: plan as supplied" in text and status.lower() in text, (case["case_id"], text[:300])
                assert "run the planning agent on this case" in text, "a final outcome was shown before planning this case"
                shot(page, f"10-case-{case['case_id']}")
            return "each named case loads from the panel with its initial outcome; final outcome waits for Planner and review"

        step("Demo-case panel: initial vs final outcomes", demo_case_panel)

        def advance_planning():
            # Back on the saved supported scenario: bind a labeled training series, assess arrivals >= 24 h ahead, apply.
            tab("Setup")
            page.locator("select").filter(has=page.locator("option", has_text="demo-check supported-limited")).select_option(label="demo-check supported-limited")
            tab("Lines")
            expect(page.get_by_text("Overall AMBER", exact=True).first).to_be_visible()
            tab("Advance (24 h+)")
            panel_source = page.get_by_label("Forecast source")
            assert "unavailable" in panel_source.inner_text(), "public forecast must read unavailable until D2 lands"
            page.get_by_role("button", name="Use training scenario").click()
            cov = page.get_by_label("Series coverage")
            expect(cov.get_by_text(re.compile(r": covered\."))).to_be_visible(timeout=60_000)
            assert "not a weather forecast" in cov.inner_text()
            with page.expect_response(lambda r: r.url.endswith("/api/v1/mooring/forecast-plan") and r.request.method == "POST") as submitted:
                page.get_by_role("button", name="Assess arrivals").click()
            body = submitted.value.request.post_data_json
            assert body["forecast_binding"]["source"] == "supplied" and body["holding_hours"] == 6, body.get("forecast_binding")
            result = page.get_by_label("Advance planning result")
            expect(result.get_by_label("Arrival alternatives")).to_be_visible(timeout=240_000)
            text = result.inner_text()
            assert "validity limited" in text, "forecast planning must stay limited"
            shot(page, "11-advance-planning")
            if "Selected arrival" in text:
                result.get_by_role("button", name="Apply selected configuration").click()
                expect(result.get_by_role("status").filter(has_text="Applied the configuration")).to_be_visible()
                assert "Recheck required" not in result.inner_text(), "applying the selected configuration must not mark it stale"
                page.get_by_label("Holding hours").fill("12")
                expect(result.get_by_text(re.compile("Recheck required"))).to_be_visible()
                assert result.get_by_role("button", name="Apply selected configuration").is_disabled()
                return "training series bound and covered; alternatives assessed; selected configuration applied; changed holding marks recheck required"
            return "training series bound and covered; alternatives assessed; no arrival supported (no configuration published)"

        step("Advance planning: training series, alternatives, apply, recheck", advance_planning)

        def clean():
            real = [e for e in errors if "GL Driver" not in e]
            assert not real, f"{len(real)} browser errors, first: {real[0]}"
            return "no page errors or console errors"

        step("No browser errors during the whole flow", clean)
        browser.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
