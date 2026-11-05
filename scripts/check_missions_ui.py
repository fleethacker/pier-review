#!/usr/bin/env python3
"""Drive the Missions app (S5 storyboard, S6 transit) in headless Chromium against a real modeling backend.

Usage: check_missions_ui.py URL SCREENS_DIR   (URL is the UI origin, e.g. http://127.0.0.1:4010/; ?app=missions is added)
Env:   DEMO_CHECK_BROWSER_EXECUTABLE  path of an installed Chrome, if Playwright's Chromium is not installed.
Prints `PASS|FAIL <name> | <detail>`; exit status is non-zero if any check failed. Needs Pillow and Playwright.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import time
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, expect, sync_playwright

expect.set_options(timeout=30_000)
URL = sys.argv[1].rstrip("/") + "/?app=missions"
SHOTS = Path(sys.argv[2])
SHOTS.mkdir(parents=True, exist_ok=True)
failed = 0
MISSION = f"Hampton Roads sortie {os.getpid()}"  # unique per run: the backend keeps missions between runs
T0 = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


def report(status: str, name: str, detail: str = "") -> None:
    global failed
    failed += status == "FAIL"
    print(f"{status} {name} | {detail}".rstrip(" |"), flush=True)


def step(page: Page, name: str, fn) -> bool:
    try:
        report("PASS", name, fn() or "")
        return True
    except Exception as exc:  # noqa: BLE001
        lines = [ln.strip() for ln in str(exc).strip().splitlines() if ln.strip()]
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
        page.screenshot(path=str(SHOTS / f"FAIL-{slug}.png"))
        report("FAIL", name, " / ".join(lines[:3])[:400])
        return False


def pos_at(sec: float) -> tuple[float, float]:
    """Ship leaves Norfolk heading east then north-east over 2 h (Hampton Roads)."""
    f = sec / 7200
    return 36.95 + 0.06 * f, -76.33 + 0.17 * f


def csv_track() -> str:
    rows = ["time,lat,lon,heading,sog,hdop"]
    for s in range(0, 7201, 30):
        if 3000 < s < 3600:  # 10 minute recording gap, 12:50-13:00
            continue
        lat, lon = pos_at(s)
        rows.append(f"{(T0 + timedelta(seconds=s)).strftime('%Y-%m-%dT%H:%M:%SZ')},{lat:.6f},{lon:.6f},75,9.5,1.0")
    return "\n".join(rows) + "\n"


def gpx_track() -> str:
    pts = []
    for s in range(7230, 8400, 30):  # 14:00:30 - 14:20
        lat, lon = pos_at(7200)
        lon += 0.00004 * (s - 7200)
        pts.append(f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><time>{(T0 + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>')
    return '<?xml version="1.0"?><gpx version="1.1" creator="check"><trk><trkseg>' + "".join(pts) + "</trkseg></trk></gpx>"


def jpeg(local: datetime, offset: str, lat: float, lon: float) -> bytes:
    img = Image.new("RGB", (320, 200), (30, 90, 160))
    exif = Image.Exif()
    sub = exif.get_ifd(0x8769)
    sub[36867] = local.strftime("%Y:%m:%d %H:%M:%S")
    sub[36881] = offset
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = ("N" if lat >= 0 else "S"), ((abs(lat)), 0, 0)
    gps[3], gps[4] = ("E" if lon >= 0 else "W"), ((abs(lon)), 0, 0)
    gps[1], gps[2] = "N", (int(lat), int((lat % 1) * 60), ((lat * 60) % 1) * 60)
    gps[3], gps[4] = "W", (int(abs(lon)), int((abs(lon) % 1) * 60), ((abs(lon) * 60) % 1) * 60)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def dt_local(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M")


def main() -> int:
    errors: list[str] = []
    bad_responses: list[str] = []
    out = SHOTS / "data"
    out.mkdir(exist_ok=True)
    (out / "track.csv").write_text(csv_track())
    (out / "track.gpx").write_text(gpx_track())
    # image 1 on the track (12:20 UTC, camera local time EDT-less: offset +00:00); image 2 in the gap; image 3 camera slow 2 min
    t1 = T0 + timedelta(minutes=20)
    t2 = T0 + timedelta(minutes=55)
    t3 = T0 + timedelta(minutes=90, seconds=-120)  # camera clock 2 min slow
    (out / "on_track.jpg").write_bytes(jpeg(t1, "+00:00", *pos_at(1200)))
    (out / "in_gap.jpg").write_bytes(jpeg(t2, "+00:00", *pos_at(3300)))
    (out / "clock_off.jpg").write_bytes(jpeg(t3, "+00:00", *pos_at(5400)))

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("DEMO_CHECK_BROWSER_EXECUTABLE"), args=["--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, reduced_motion="reduce")
        page.set_default_timeout(30_000)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text[:300]} at {m.location.get('url')}"))
        page.on("response", lambda r: r.status >= 400 and bad_responses.append(f"{r.status} {r.request.method} {r.url}"))
        page.goto(URL, wait_until="load")

        def create_mission():
            expect(page.get_by_role("tab", name="Storyboard")).to_be_visible()
            f = page.get_by_role("form", name="Create mission")
            f.get_by_label("Mission name").fill(MISSION)
            f.get_by_label("Vessel id (hull number, MMSI)").fill("DDG-99")
            f.get_by_role("button", name="Create").click()
            expect(page.get_by_role("button", name=re.compile(MISSION))).to_be_visible()
            expect(page.get_by_text("Sample data (mock fixture")).to_have_count(0)

        if not step(page, "create mission", create_mission):
            return 1

        def upload(fmt, name, detail_re):
            f = page.get_by_role("form", name="Upload track file")
            f.locator("input[type=file]").set_input_files(str(out / name))
            f.get_by_label("Format").select_option(fmt) if f.locator("select").count() else page.get_by_label("Format").click()
            f.get_by_role("button", name="Upload track").click()
            expect(page.get_by_role("region", name="Track ingest result")).to_contain_text(detail_re)

        step(page, "upload CSV track", lambda: upload("csv", "track.csv", re.compile("csv")))
        step(page, "upload GPX track", lambda: upload("gpx", "track.gpx", re.compile("gpx")))

        def images():
            for fname, clock, caption in [("on_track.jpg", "", "On the track"), ("in_gap.jpg", "", "Inside the gap"), ("clock_off.jpg", "120", "Camera clock slow")]:
                f = page.get_by_role("form", name="Upload image")
                f.locator("input[type=file]").set_input_files(str(out / fname))
                f.get_by_label("Camera clock offset (seconds to add; camera slow = positive)").fill(clock)
                f.get_by_label("Caption").fill(caption)
                f.get_by_role("button", name="Upload image").click()
                expect(page.get_by_role("list", name="Events").get_by_text(caption)).to_be_visible()

        step(page, "upload 3 JPEGs", images)

        def reports():
            lat, lon = pos_at(4800)  # 13:20; stated 1 km north (0.009 deg)
            for title, t, stated in [("Bridge log entry", T0 + timedelta(minutes=10), None), ("Stated position report", T0 + timedelta(minutes=80), (lat + 0.009, lon))]:
                f = page.get_by_role("form", name="Add report")
                f.get_by_label("Time (UTC)").fill(dt_local(t))
                f.get_by_label("Title").fill(title)
                if stated:
                    f.get_by_label("Stated latitude (optional)").fill(f"{stated[0]:.6f}")
                    f.get_by_label("Stated longitude (optional)").fill(f"{stated[1]:.6f}")
                f.get_by_role("button", name="Add report").click()
                expect(page.get_by_role("list", name="Events").get_by_text(title)).to_be_visible()

        step(page, "add 2 reports", reports)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(SHOTS / "01-storyboard.png"))

        def summary():
            s = page.get_by_role("region", name="Mission summary")
            expect(s).to_contain_text("Longest gap")
            return s.inner_text().replace("\n", " ")[:200]

        step(page, "summary stats", summary)

        def scrub():
            slider = page.get_by_role("slider", name="Mission time")
            lo, hi = int(slider.get_attribute("min")), int(slider.get_attribute("max"))
            def set_to(ms):
                slider.evaluate("(el, v) => { const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; s.call(el, String(v)); el.dispatchEvent(new Event('input', {bubbles: true})); }", ms)
            t_ms = int(T0.timestamp() * 1000)
            set_to(t_ms + 30 * 60_000)
            expect(page.get_by_text(re.compile(r"ship at 3[67]\.\d+, -76\.\d+"))).to_be_visible()
            a = slider.get_attribute("aria-valuetext")
            set_to(t_ms + 55 * 60_000)
            expect(page.get_by_text("position not established", exact=True)).to_be_visible()
            page.screenshot(path=str(SHOTS / "02-scrub-in-gap.png"))
            set_to(t_ms + 100 * 60_000)
            expect(page.get_by_text(re.compile(r"ship at 3[67]\.\d+, -76\.\d+"))).to_be_visible()
            return f"span {hi - lo} ms; mid-track valuetext: {a}"

        step(page, "scrubber moves ship, gap not established", scrub)

        def events():
            ev = page.get_by_role("list", name="Events")
            gap_row = ev.get_by_role("button", name=re.compile("Inside the gap"))
            expect(gap_row).to_contain_text("position not established")
            gap_row.click()
            d = page.get_by_role("region", name="Event detail")
            expect(d.locator("img")).to_be_visible()
            expect(d).to_contain_text("Position not established")
            page.wait_for_function("() => [...document.querySelectorAll('section[aria-label=\"Event detail\"] img')].every(i => i.complete && i.naturalWidth > 0)")
            page.screenshot(path=str(SHOTS / "03-image-in-gap.png"))
            ev.get_by_role("button", name=re.compile("On the track")).click()
            expect(d).to_contain_text("On the track")
            expect(d.locator("img")).to_be_visible()
            page.wait_for_function("() => [...document.querySelectorAll('section[aria-label=\"Event detail\"] img')].every(i => i.complete && i.naturalWidth === 320)")
            ev.get_by_role("button", name=re.compile("Camera clock slow")).click()
            expect(d).to_contain_text("Camera clock slow")
            return "clicked 3 images; bytes decoded (naturalWidth 320)"

        step(page, "event click jumps; image bytes load; gap flagged", events)

        def discrepancy():
            ev = page.get_by_role("list", name="Events")
            row = ev.get_by_role("button", name=re.compile("Stated position report"))
            expect(row).to_contain_text(re.compile(r"\d+ m off"))
            row.click()
            d = page.get_by_role("region", name="Event detail")
            expect(d).to_contain_text(re.compile(r"differs from the track by (9\d\d|10\d\d) m"))
            page.screenshot(path=str(SHOTS / "04-discrepancy.png"))
            return row.inner_text().replace("\n", " ")

        step(page, "report discrepancy (~1 km)", discrepancy)

        def geojson():
            href = page.get_by_role("link", name="Download GeoJSON").get_attribute("href")
            r = page.request.get(href)
            assert r.ok, f"{r.status} {href}"
            gj = r.json()
            assert gj.get("type") == "FeatureCollection" and gj["features"], "empty GeoJSON"
            return f"{href}: {len(gj['features'])} features"

        step(page, "GeoJSON download", geojson)

        # ---- transit ----
        page.get_by_role("tab", name="Transit").click()

        def run_preset(title: str, shot: str):
            page.get_by_label("Preset").select_option(label=title)
            page.get_by_role("button", name="Run", exact=True).click()
            expect(page.get_by_role("button", name="Run", exact=True)).to_be_enabled(timeout=180_000)
            expect(page.get_by_role("table", name="Vessels")).to_be_visible()
            expect(page.get_by_role("list", name="Transit events").locator("li").first).to_be_visible()
            expect(page.get_by_text(re.compile("assum", re.I)).first).to_be_visible()
            assert page.get_by_role("table", name="Vessels").locator("tbody tr").count() >= 1
            play = page.get_by_role("button", name="Play")
            play.click()
            page.wait_for_timeout(1500)
            slider = page.get_by_role("slider", name="Simulation time")
            v1 = float(slider.input_value())
            page.wait_for_timeout(1500)
            v2 = float(slider.input_value())
            assert v2 > v1, f"playback did not advance ({v1} -> {v2})"
            page.get_by_role("button", name="Pause").click()
            page.screenshot(path=str(SHOTS / shot))
            hi = float(slider.get_attribute("max"))
            slider.evaluate("(el, v) => { const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; s.call(el, String(v)); el.dispatchEvent(new Event('input', {bubbles: true})); }", hi * 0.93)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(SHOTS / shot.replace(".png", "-late.png")))
            return f"vessels={page.get_by_role('table', name='Vessels').locator('tbody tr').count()}, clock {v1:.0f}->{v2:.0f}"

        expect(page.get_by_label("Preset").locator("option").first).to_be_attached()
        labels = page.get_by_label("Preset").locator("option").all_inner_texts()
        report("PASS", "presets load", " | ".join(labels))
        tug = next((l for l in labels if "tug" in l.lower()), None)
        two = next((l for l in labels if "two" in l.lower()), None)
        if tug:
            step(page, "transit ddg-inbound-tug-assisted", lambda: run_preset(tug, "05-transit-tug.png"))

            def save():
                page.get_by_role("button", name="Save as mission").click()
                page.get_by_role("tab", name="Storyboard").wait_for()
                expect(page.get_by_role("tab", name="Storyboard")).to_have_attribute("aria-selected", "true", timeout=30_000)
                expect(page.get_by_role("slider", name="Mission time")).to_be_visible()
                page.wait_for_timeout(1500)
                page.screenshot(path=str(SHOTS / "06-saved-mission-tug.png"))
                return page.get_by_role("slider", name="Mission time").get_attribute("aria-valuetext")

            step(page, "save tug transit as mission -> storyboard", save)
            page.get_by_role("tab", name="Transit").click()
        else:
            report("FAIL", "tug preset", f"not in {labels}")
        if two:
            step(page, "transit two-vessels", lambda: run_preset(two, "07-transit-two.png"))

            def save2():
                page.get_by_role("button", name="Save as mission").click()
                expect(page.get_by_role("tab", name="Storyboard")).to_have_attribute("aria-selected", "true", timeout=30_000)
                expect(page.get_by_role("slider", name="Mission time")).to_be_visible()
                names = page.get_by_role("heading", name="Missions").locator("xpath=..").locator("li button").all_inner_texts()
                page.screenshot(path=str(SHOTS / "08-saved-mission-two.png"))
                return f"{len(names)} missions listed"

            step(page, "save two-vessel transit as missions", save2)
        else:
            report("FAIL", "two-vessels preset", f"not in {labels}")
        # ---- backup camera (preset, real backend) ----
        def camera_preset():
            page.get_by_role("tab", name="Camera").click()
            page.get_by_role("button", name="Preset", exact=True).click()
            expect(page.get_by_role("region", name="Prediction limits")).to_contain_text("Limited", timeout=60_000)
            expect(page.get_by_text(re.compile(r"Predicted pier contact in \d+ s")).first).to_be_visible()
            expect(page.get_by_text("Hazards not checked: coastline")).to_be_visible()
            expect(page.get_by_text("Sample prediction")).to_have_count(0)
            page.screenshot(path=str(SHOTS / "10-camera-preset.png"))
            for name, text in [("Rudder 15° port", "Closest approach"), ("Engine astern half", "Closest approach"), ("Tug push to starboard (port shoulder)", "Tug push|contact|Closest")]:
                page.get_by_role("group", name="What if").get_by_role("button", name=name).click()
                expect(page.get_by_text(re.compile(text)).first).to_be_visible(timeout=30_000)
                expect(page.get_by_role("group", name="What if").get_by_role("button", name=name)).to_have_attribute("aria-pressed", "true")
            page.screenshot(path=str(SHOTS / "11-camera-whatif.png"))

        step(page, "camera preset overlay + what-ifs", camera_preset)

        def camera_transit():
            page.get_by_role("tab", name="Transit").click()
            if tug:
                page.get_by_label("Preset").select_option(label=tug)
            page.get_by_role("button", name="Run", exact=True).click()
            expect(page.get_by_role("button", name="Run", exact=True)).to_be_enabled(timeout=180_000)
            page.get_by_role("table", name="Vessels").locator("tbody tr").first.click()
            reqs: list[float] = []
            page.on("request", lambda r: "predict/trajectory" in r.url and reqs.append(time.time()))
            page.get_by_label(re.compile("Backup camera")).check()
            page.get_by_role("button", name="Play").click()
            page.wait_for_timeout(9000)
            expect(page.get_by_text(re.compile(r"Closest approach|Predicted .* contact")).first).to_be_visible()
            page.screenshot(path=str(SHOTS / "12-transit-camera.png"))
            page.get_by_role("button", name="Pause").click()
            gaps = [b - a for a, b in zip(reqs, reqs[1:])]
            assert len(reqs) >= 3, f"only {len(reqs)} predictions"
            assert min(gaps) >= 0.9, f"requests too frequent: {gaps}"
            return f"{len(reqs)} predictions in 9 s"

        step(page, "transit backup camera follows vessel, <=1/s", camera_transit)
        browser.close()

    uncaught = [e for e in errors]
    report("FAIL" if uncaught else "PASS", "console errors", "; ".join(uncaught)[:800])
    report("FAIL" if bad_responses else "PASS", "4xx/5xx responses", "; ".join(bad_responses)[:800])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
