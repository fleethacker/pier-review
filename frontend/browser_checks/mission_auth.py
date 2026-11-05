#!/usr/bin/env python3
"""Authenticated Missions browser smoke against an isolated, real local stack.

From the repository root (requires `npm ci` in frontend/packages/web):
  uv run --all-packages --with playwright --with pillow python frontend/browser_checks/mission_auth.py

If Playwright Chromium is absent, set DEMO_CHECK_BROWSER_EXECUTABLE to an installed
Chrome executable. macOS Google Chrome is detected automatically. Optional:
  --artifacts /tmp/mission-auth-smoke

The check starts loopback modeling + Vite on free ports, creates a temporary random
bearer key in subprocess environments, and tears the stack down on exit. It does not
write .env files, save HAR/traces/headers, or print credentials. SQLite, screenshots,
GeoJSON and logs remain under /tmp. Fixtures say SYNTHETIC and are not operational
observations. No remote data or agents service is required. Browser requests receive
no injected Authorization header: the application must supply it itself.

This checks the documented local build-time bearer transport, not production login,
credential secrecy in a served JS bundle, gateway/SSE authentication, or physics.
API shapes: contract/modeling.openapi.yaml; setup: docs/DEPLOYMENT_READINESS.md;
mission semantics: docs/MISSION_STORYBOARD.md. No generated contracts are changed.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlparse, parse_qs

import httpx
from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "frontend/packages/web"
CAPTION = "SYNTHETIC AUTH TEST IMAGE"
REPORT = "SYNTHETIC AUTH TEST REPORT"


def free_port(used: set[int]) -> int:
    for _ in range(20):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in used:
            used.add(port)
            return port
    raise RuntimeError("Could not reserve a separate local port.")


def wait_ready(url: str, process: subprocess.Popen, timeout: float = 25) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Local service exited before readiness; inspect temporary service logs.")
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError("Local service did not become ready within the startup deadline.")


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    artifacts = (args.artifacts or Path(tempfile.mkdtemp(prefix="mission-auth-", dir="/tmp"))).resolve()
    if not artifacts.is_relative_to(Path("/tmp").resolve()):
        parser.error("Use an artifacts directory under /tmp.")
    artifacts.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(40)
    mission_name = f"SYNTHETIC AUTH SMOKE {secrets.token_hex(4)} — offline test fixture"
    results: list[dict] = []
    processes: list[subprocess.Popen] = []
    logs = []

    def passed(name: str, detail: str = "") -> None:
        results.append({"name": name, "passed": True, "detail": detail})
        print(f"PASS {name}" + (f" | {detail}" if detail else ""), flush=True)

    try:
        vite = WEB / "node_modules/.bin/vite"
        if not vite.exists():
            raise RuntimeError("Run npm ci in frontend/packages/web before this check.")
        used: set[int] = set()
        api_port, ui_port = free_port(used), free_port(used)
        api_url, ui_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{ui_port}"
        environment = dict(os.environ)
        environment.update({
            "AGENTS_LLM_PROVIDER": "none",
            "MOORING_AUTH_REQUIRED": "1",
            "MOORING_API_KEYS": json.dumps({"synthetic-browser-smoke": token}),
            "MOORING_DB": str(artifacts / "synthetic.sqlite"),
            "MOORING_ENV_SOURCE": "mock",
            "MOORING_RATE_PER_MINUTE": "600",
            "MODELING_PROXY_TARGET": api_url,
            "VITE_MODELING_URL": "",
            "VITE_API_BEARER_TOKEN": token,
            "VITE_MAPBOX_TOKEN": "",
        })
        for name, command, cwd in (
            ("modeling", [sys.executable, "-m", "uvicorn", "modeling_api.main:app", "--host", "127.0.0.1", "--port", str(api_port), "--no-access-log"], ROOT),
            ("vite", [str(vite), "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"], WEB),
        ):
            log = (artifacts / f"{name}.log").open("wb")
            logs.append(log)
            processes.append(subprocess.Popen(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        wait_ready(f"{api_url}/api/v1/health", processes[0])
        wait_ready(ui_url, processes[1])
        print(f"Local stack: {ui_url} -> {api_url}; artifacts: {artifacts}", flush=True)

        with httpx.Client(base_url=f"{api_url}/api/v1", headers={"Authorization": f"Bearer {token}"}, timeout=20) as client:
            response = client.post("/missions", json={
                "name": mission_name,
                "vessel_id": "SYNTHETIC-NOT-A-VESSEL",
                "description": "Fabricated coordinates and image for authentication transport testing only. Not operational observations.",
            })
            response.raise_for_status()
            mission_id = response.json()["mission_id"]
            fixes = [
                {"t_utc": "2026-11-05T12:00:00Z", "lat": 36.95, "lon": -76.33, "source": "synthetic-auth-smoke", "quality": "unknown"},
                {"t_utc": "2026-11-05T12:01:00Z", "lat": 36.951, "lon": -76.329, "source": "synthetic-auth-smoke", "quality": "unknown"},
            ]
            response = client.post(f"/missions/{mission_id}/track", json={"fixes": fixes})
            response.raise_for_status()
            assert response.json()["accepted"] == 2, "Synthetic fixes were not accepted."
            image = Image.new("RGB", (320, 160), (12, 35, 56))
            ImageDraw.Draw(image).text((16, 40), "SYNTHETIC AUTH TEST\nNot operational imagery", fill=(240, 200, 80))
            stream = io.BytesIO()
            image.save(stream, "PNG")
            response = client.post(f"/missions/{mission_id}/media", files={"image": ("synthetic-auth.png", stream.getvalue(), "image/png")},
                                   data={"metadata": json.dumps({"captured_utc": "2026-11-05T12:00:30Z", "caption": CAPTION})})
            response.raise_for_status()
            media_path = response.json()["url"]
            response = client.post(f"/missions/{mission_id}/reports", json={"t_utc": "2026-11-05T12:00:40Z", "title": REPORT, "body": "Synthetic test report; no operational information."})
            response.raise_for_status()
            export_path = f"/api/v1/missions/{mission_id}/storyboard.geojson"
            for name, path in (("Unauthenticated image rejected", media_path), ("Unauthenticated export rejected", export_path)):
                denied = httpx.get(f"{api_url}{path}", timeout=10)
                assert denied.status_code == 401, f"Expected 401, received {denied.status_code}."
                passed(name)

        with sync_playwright() as playwright:
            executable = os.environ.get("DEMO_CHECK_BROWSER_EXECUTABLE")
            mac_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            if not executable and mac_chrome.exists():
                executable = str(mac_chrome)
            browser = playwright.chromium.launch(executable_path=executable, args=["--enable-unsafe-swiftshader"])
            context = browser.new_context(viewport={"width": 1600, "height": 1000}, reduced_motion="reduce", accept_downloads=True)
            # Deny external map/font requests; this is an offline test of local transports.
            context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).hostname in {"127.0.0.1", "localhost"} else route.abort())
            context.add_init_script("""(() => {
              window.__missionAuthBlobs = {created: [], revoked: []};
              const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
              URL.createObjectURL = blob => { const url = create(blob); window.__missionAuthBlobs.created.push(url); return url; };
              URL.revokeObjectURL = url => { window.__missionAuthBlobs.revoked.push(url); return revoke(url); };
            })();""")
            page = context.new_page()
            page.set_default_timeout(20_000)
            expect.set_options(timeout=20_000)
            requests: list[dict] = []
            responses: list[tuple[str, int]] = []
            errors: list[str] = []
            page.on("request", lambda request: requests.append({"url": request.url, "authorized": request.headers.get("authorization") == f"Bearer {token}"}))
            page.on("response", lambda response: responses.append((response.url, response.status)))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"{ui_url}/?app=missions", wait_until="load")
            mission_button = page.get_by_role("button", name=re.compile(re.escape(mission_name)))
            expect(mission_button).to_be_visible()
            mission_button.click()
            expect(mission_button).to_have_attribute("aria-pressed", "true")
            expect(page.get_by_text("Sample data (mock fixture, backend unavailable)")).to_have_count(0)
            passed("Synthetic fixture visible from authenticated service", "No sample fallback; actual mission API responses.")
            mission_reads = [request for request in requests if urlparse(request["url"]).path.endswith("/api/v1/missions")]
            assert mission_reads and all(request["authorized"] for request in mission_reads)
            passed("Browser mission list sends Authorization")

            page.get_by_role("list", name="Events").get_by_role("button", name=re.compile(CAPTION)).click()
            shown = page.get_by_role("img", name=CAPTION)
            expect(shown).to_be_visible()
            page.wait_for_function("caption => [...document.images].filter(image => image.alt === caption).every(image => image.complete && image.naturalWidth === 320)", arg=CAPTION)
            image_src = shown.get_attribute("src")
            assert image_src and image_src.startswith("blob:"), "Image must use an authorized blob URL."
            image_urls = page.locator("img").evaluate_all("(images, caption) => images.filter(image => image.alt === caption).map(image => image.src)", CAPTION)
            passed("Authenticated image decodes as blob", "320 × 160 synthetic PNG.")
            media_reads = [request for request in requests if urlparse(request["url"]).path.endswith(media_path)]
            assert media_reads and all(request["authorized"] for request in media_reads)
            assert any(urlparse(url).path.endswith(media_path) and status == 200 for url, status in responses)
            passed("Image request carries Authorization and returns 200")
            page.screenshot(path=str(artifacts / "authenticated-image.png"))

            with page.expect_download() as pending:
                page.get_by_role("button", name="Download GeoJSON", exact=True).click()
            download = pending.value
            assert download.suggested_filename == f"{mission_id}.geojson"
            assert download.url.startswith("blob:"), "Download must use an authorized blob URL."
            export_file = artifacts / "synthetic-mission.geojson"
            download.save_as(export_file)
            exported = json.loads(export_file.read_text())
            assert exported["type"] == "FeatureCollection"
            assert any(feature.get("properties", {}).get("title") == CAPTION for feature in exported["features"])
            passed("Browser GeoJSON download contains the synthetic image event")
            export_reads = [request for request in requests if urlparse(request["url"]).path.endswith(export_path)]
            assert export_reads and all(request["authorized"] for request in export_reads)
            assert any(urlparse(url).path.endswith(export_path) and status == 200 for url, status in responses)
            passed("GeoJSON request carries Authorization and returns 200")

            page.get_by_role("list", name="Events").get_by_role("button", name=re.compile(REPORT)).click()
            page.wait_for_function("urls => urls.every(url => window.__missionAuthBlobs.revoked.includes(url))", arg=[*image_urls, download.url])
            passed("Image and download object URLs are released")
            urls = [request["url"] for request in requests] + [page.url]
            urls += page.locator("[href], [src]").evaluate_all("els => els.flatMap(el => [el.getAttribute('href'), el.getAttribute('src')]).filter(Boolean)")
            for url in urls:
                assert token not in unquote(url), "Credential appeared in a request or DOM URL."
                assert not ({"token", "access_token", "api_key", "authorization", "bearer"} & {key.lower() for key in parse_qs(urlparse(url).query)}), "Credential query parameter found."
            assert not any(request["authorized"] and urlparse(request["url"]).hostname not in {"127.0.0.1", "localhost"} for request in requests)
            passed("No URL token leakage or authenticated off-service requests")
            assert not errors, "JavaScript page errors: " + "; ".join(errors)
            passed("No browser JavaScript page errors")
            page.screenshot(path=str(artifacts / "authenticated-export.png"))
            context.close()
            browser.close()
    except Exception as error:
        detail = str(error).replace(token, "[REDACTED]")[:1200]
        results.append({"name": "Authenticated mission browser smoke", "passed": False, "detail": detail})
        print(f"FAIL authenticated mission browser smoke | {detail}", flush=True)
    finally:
        for process in reversed(processes):
            stop(process)
        for log in logs:
            log.close()
        summary = {"passed": sum(item["passed"] for item in results), "failed": sum(not item["passed"] for item in results), "skipped": 0,
                   "fixture": "synthetic; not operational observations", "checks": results}
        (artifacts / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"RESULT {summary['passed']} passed, {summary['failed']} failed, 0 skipped | {artifacts}", flush=True)
    return int(any(not item["passed"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
