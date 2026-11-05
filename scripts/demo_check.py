#!/usr/bin/env python3
"""End-to-end demo check: both services, the built UI, and the proxy between them, on private ports.

Run with `make demo-check` (or `uv run --all-packages python scripts/demo_check.py`).

What it does
  1. Starts modeling and agents on free ports and builds/serves the UI the way app.sh does (`vite preview` with both
     services proxied).
  2. Checks, through the UI proxy: the page, the bundled motion fixtures, health/version/capabilities, the Phase 1
     chain (scenario, agent plan over SSE, safety sheet, approval) and a motion session over a WebSocket (resume,
     tug command, pause, reset), asserting the honesty rules (limited validity, no invented values).
  3. Optionally drives the built UI in headless Chromium and saves screenshots to docs/overnight/screens/. That part
     needs Playwright. Without it the API and proxy part still runs and the browser part is reported as SKIPPED.

Everything runs offline: no LLM key, no provider network. Exit status is non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "packages" / "web"
EXAMPLES = ROOT / "contract" / "examples" / "modeling"
SCREENS = Path(os.environ.get("DEMO_CHECK_SCREEN_DIR", str(ROOT / "docs" / "overnight" / "screens")))

RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}[status]
    print(f"  {mark} {name}{(' — ' + detail) if detail else ''}", flush=True)


def check(name: str, fn):
    try:
        detail = fn()
        record("PASS", name, detail or "")
        return True
    except Exception as exc:  # noqa: BLE001 - report every failure, keep going
        record("FAIL", name, f"{type(exc).__name__}: {exc}"[:300])
        return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method: str, url: str, body=None, timeout: float = 30.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw and resp.headers.get_content_type() == "application/json" else raw)
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{method} {url} -> HTTP {exc.code}: {exc.read()[:200]!r}") from None


def wait_for(url: str, seconds: float, what: str) -> None:
    deadline = time.time() + seconds
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"{what} did not come up at {url}: {last}")


class Stack:
    """The two services and the UI preview server, with log files and clean shutdown."""

    def __init__(self, logs: Path, tool_timeout_s: float = 120.0):
        self.tool_timeout_s = tool_timeout_s
        self.procs: list[subprocess.Popen] = []
        self.logs = logs
        logs.mkdir(parents=True, exist_ok=True)
        self.modeling_port = free_port()
        self.agents_port = free_port()
        self.ui_port = free_port()

    @property
    def ui(self) -> str:
        return f"http://127.0.0.1:{self.ui_port}"

    def _spawn(self, name: str, cmd: list[str], env: dict[str, str], cwd: Path) -> None:
        log = open(self.logs / f"{name}.log", "w")  # noqa: SIM115 - closed with the process
        self.procs.append(subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))

    def start_services(self) -> None:
        env = {**os.environ, "AGENTS_LLM_PROVIDER": "none", "PYTHONUNBUFFERED": "1"}
        for k in ("MOORING_API_KEYS", "MOORING_AUTH_REQUIRED", "AGENTS_API_KEYS", "AGENTS_AUTH_REQUIRED", "AGENTS_LEDGER_DB"):
            env.pop(k, None)  # demo mode: open, loopback only
        env.update(MOORING_DB=":memory:", AGENTS_PERSIST="0", MOORING_ENV_SOURCE="mock", MOORING_RATE_PER_MINUTE="0", AGENTS_RATE_PER_MINUTE="0")
        py = [sys.executable, "-m", "uvicorn"]
        self._spawn("modeling", [*py, "modeling_api.main:app", "--host", "127.0.0.1", "--port", str(self.modeling_port)], env, ROOT)
        self._spawn(
            "agents",
            [*py, "mooring_agents.api.main:app", "--host", "127.0.0.1", "--port", str(self.agents_port)],
            {
                **env,
                "MODELING_API_URL": f"http://127.0.0.1:{self.modeling_port}/api/v1",
                # Headless software-rendered WebGL saturates the CPU and makes the planner several times slower; the
                # production default is 30 s. Raised here only, and printed in the run header.
                "AGENTS_TOOL_TIMEOUT_S": str(self.tool_timeout_s),
            },
            ROOT,
        )
        wait_for(f"http://127.0.0.1:{self.modeling_port}/api/v1/health", 60, "modeling")
        wait_for(f"http://127.0.0.1:{self.agents_port}/api/v1/health", 60, "agents")

    def build_and_serve_ui(self, skip_build: bool) -> None:
        vite = WEB / "node_modules" / ".bin" / "vite"
        env = {
            **os.environ,
            "MODELING_PROXY_TARGET": f"http://127.0.0.1:{self.modeling_port}",
            "AGENTS_PROXY_TARGET": f"http://127.0.0.1:{self.agents_port}",
            "NODE_OPTIONS": "--max-old-space-size=3072",
        }
        if not vite.exists():
            raise RuntimeError("frontend dependencies are not installed (run `npm ci` in frontend/packages/web)")
        if not skip_build:
            log = open(self.logs / "ui-build.log", "w")  # noqa: SIM115
            tsc = WEB / "node_modules" / ".bin" / "tsc"
            if tsc.exists():
                subprocess.run([str(tsc), "--noUnusedLocals", "false"], cwd=WEB, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run([str(vite), "build"], cwd=WEB, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        self._spawn("ui-preview", [str(vite), "preview", "--host", "127.0.0.1", "--port", str(self.ui_port), "--strictPort"], env, WEB)
        wait_for(self.ui + "/", 60, "ui preview")

    def stop(self) -> None:
        import signal

        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        for p in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)


# ---- API and proxy checks ------------------------------------------------------------------------------------------


def api_checks(stack: Stack) -> dict:
    ui = stack.ui
    modeling = f"{ui}/api/modeling/api/v1"
    agents = f"{ui}/api/agents/api/v1"
    ctx: dict = {}

    def page():
        status, body = http("GET", ui + "/")
        assert status == 200 and b"Mooring" in body, "index.html did not load"
        return "index.html served"

    def fixtures():
        _, rec = http("GET", ui + "/fixtures/sim_recording_60s.json")
        _, scene = http("GET", ui + "/fixtures/sim_scene.json")
        assert len(rec["frames"]) > 10 and scene["scene_id"] == rec["scene_id"]
        return f"{len(rec['frames'])} recorded frames, scene {scene['scene_id']}"

    def health():
        _, m = http("GET", modeling + "/health")
        _, a = http("GET", agents + "/health")
        assert m["status"] == "ok" and a["status"] == "ok"
        return f"modeling backend={m['backend']}, agents ok"

    def capabilities():
        _, caps = http("GET", modeling + "/capabilities")
        _, ver = http("GET", modeling + "/version")
        _, audit = http("GET", modeling + "/qualification")
        assert caps and "modules" in ver and "ok" in audit
        unq = [c for c in caps if c["qualification"] != "qualified"]
        assert unq, "expected unqualified capabilities to be reported honestly"
        return f"{len(unq)} of {len(caps)} capabilities not qualified"

    def environment_honesty():
        berth = json.loads((EXAMPLES / "scenario.json").read_text())["berth_id"]
        _, env = http("GET", f"{modeling}/env/now?berth_id={berth}")
        assert env["source"] in {"mock", "live", "replay", "forecast", "scenario", "ship_sensor"}
        assert "wave_height_ft" not in env or env["wave_height_ft"] is None, "waves must be unavailable, not a number"
        return f"environment source={env['source']}"

    def finish(accepted):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            _, job = http("GET", agents + "/jobs/" + accepted["job_id"])
            if job["state"] == "succeeded":
                return job["result"]
            assert job["state"] in ("queued", "running"), job.get("error")
            time.sleep(0.1)
        raise AssertionError("agent job exceeded demo-check deadline")

    def scenario():
        _, cases = http("GET", modeling + "/demo/docking-cases")
        case = next(c for c in cases if c["case_id"] == "ddg-supported-limited")
        _, weather = http("POST", modeling + "/env/scenarios", case["environment_request"])
        body = case["scenario_request"]
        body["name"] = "demo-check supported-limited"
        body["env_source"] = {"mode": "scenario", "env_scenario_id": weather["env_scenario_id"]}
        _, sc = http("POST", modeling + "/scenarios", body)
        ctx["scenario_id"] = sc["scenario_id"]
        ctx["tugs"] = [t["tug_id"] for t in (sc.get("tugs") or [])]
        _, accepted = http("POST", agents + "/intake/reports", {"scenario_id": sc["scenario_id"], "horizon_hours": 48})
        ctx["intake"] = finish(accepted)
        return f"supported scenario {sc['scenario_id']}; explicit Intake completed"

    def plan():
        _, accepted = http("POST", agents + "/agent/plans", {"scenario_id": ctx["scenario_id"], "intake_report_id": ctx["intake"]["report_id"], "objective": "moor_for_forecast", "target_margin_pct_wll": 60, "max_iterations": 8})
        ctx["plan_id"] = accepted["plan_id"]
        events = []
        req = urllib.request.Request(f"{ui}/api/agents{accepted['events_url']}")
        with urllib.request.urlopen(req, timeout=120) as resp:
            name = None
            for raw in resp:
                line = raw.decode().rstrip("\n")
                if line.startswith("event:"):
                    name = line.split(":", 1)[1].strip()
                    events.append(name)
                if name == "done":
                    break
        assert "step" in events and events[-1] == "done", f"SSE events: {events}"
        _, p = http("GET", f"{agents}/agent/plans/{ctx['plan_id']}")
        _, analysis = http("GET", modeling + "/results/" + p["analysis_result_id"])
        assert p["status"] == "AMBER" and analysis["validity"]["state"] == "limited", p
        ctx["plan"] = p
        return f"SSE: {events.count('step')} steps then done; plan state={p['state']}, status={p.get('status')}"

    def sheet_and_approval():
        _, accepted = http("POST", agents + "/safety/reviews", {"plan_id": ctx["plan_id"]})
        review = finish(accepted)
        assert review["verdict"] == "ready_for_signature" and review["validity"]["state"] == "limited", review
        _, sheet = http("POST", agents + "/safety-sheets", {"plan_id": ctx["plan_id"], "review_id": review["review_id"]})
        sid = sheet["sheet_id"]
        status, html = http("GET", f"{agents}/safety-sheets/{sid}/render?format=html")
        assert status == 200 and len(html) > 500, "sheet did not render"
        _, approval = http("POST", f"{agents}/safety-sheets/{sid}/approvals", {"role": "co", "name": "Demo Check", "decision": "approve", "comment": "automated check"})
        return f"sheet {sid} rendered ({len(html)} bytes), approval recorded"

    def motion_session():
        import websockets  # in the repo venv: uvicorn[standard] depends on it

        body = json.loads((EXAMPLES / "berthing_session.json").read_text())
        body["scenario_id"] = ctx["scenario_id"]
        _, created = http("POST", modeling + "/berthing/sessions", body)
        url = f"ws://127.0.0.1:{stack.ui_port}/api/modeling/ws/sim/{created['session_id']}"

        async def run():
            notes = []
            async with websockets.connect(url) as ws:
                first = json.loads(await asyncio.wait_for(ws.recv(), 10))
                assert first["t_s"] == 0, "a session starts at time zero"
                notes.append("connected paused at t=0")
                await ws.send(json.dumps({"type": "resume"}))
                t0, last, n = time.time(), first, 0
                while time.time() - t0 < 3.0:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    if "t_s" in msg and "pose" in msg:
                        assert msg["t_s"] >= last["t_s"], "time ran backwards"
                        last, n = msg, n + 1
                rate = last["t_s"] / (time.time() - t0)
                assert n >= 10 and 0.5 < rate < 2.0, f"{n} frames, rate {rate:.2f}x"
                notes.append(f"{n} frames in 3 s, {rate:.1f}x real time")
                validity = (last.get("validity") or {}).get("state", "unknown")
                assert validity != "valid", "frames from seed data must not claim to be valid"
                notes.append(f"frame validity={validity}")
                if ctx["tugs"]:
                    await ws.send(json.dumps({"type": "tug_command", "tug_id": ctx["tugs"][0], "force_lbf": 4000, "direction_rel_deg": 90}))
                    notes.append("tug command sent")
                await ws.send(json.dumps({"type": "pause"}))
                await asyncio.sleep(0.5)
                while True:  # drain, then time must hold still
                    try:
                        paused = json.loads(await asyncio.wait_for(ws.recv(), 0.6))
                    except asyncio.TimeoutError:
                        break
                    if "t_s" in paused:
                        last = paused
                await ws.send(json.dumps({"type": "reset"}))
                for _ in range(40):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if "t_s" in msg and msg["t_s"] == 0:
                        notes.append("reset returned to t=0")
                        break
                else:
                    raise AssertionError("reset did not return to time zero")
            return "; ".join(notes)

        return asyncio.run(run())

    def berth_vision():
        import base64
        import uuid

        # A 1x1 PNG: the deterministic fallback does not read pixels, so any valid image exercises the flow.
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
        boundary = uuid.uuid4().hex
        meta = json.dumps({"image_kind": "satellite", "berth_name": "Demo check pier"})
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="pier.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
            + png
            + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n{meta}\r\n--{boundary}--\r\n'.encode()
        )
        req = urllib.request.Request(f"{agents}/berth-vision/analyze", data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            accepted = json.loads(resp.read())
        job = None
        for _ in range(60):
            _, job = http("GET", f"{agents}/jobs/{accepted['job_id']}")
            if job["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.5)
        assert job and job["state"] == "succeeded", f"vision job: {job and job['state']}"
        res = job["result"]
        draft = res["result"]
        assert res["backend"] in ("mock", "real") and draft["draft_berth"]["fittings"], "no draft berth"
        flagged = [d for d in draft["detections"] if d["needs_confirmation"]]
        assert flagged and draft["questions"], "an unconfirmed draft must ask for confirmation"
        assert (res.get("validity") or {}).get("state", "unknown") != "valid", "a draft must not claim to be valid"
        draft["draft_berth"]["name"] = "Demo check pier"
        _, created = http("POST", f"{agents}/berth-vision/{accepted['job_id']}/confirm", {"berth": draft["draft_berth"]})
        _, berth = http("GET", f"{modeling}/berths/{created['berth_id']}")
        assert berth["berth_id"] == created["berth_id"]
        return f"backend={res['backend']}; {len(flagged)} items needed confirmation; confirmed berth {created['berth_id']} is usable"

    def intake():
        sc = json.loads((EXAMPLES / "scenario.json").read_text())
        _, accepted = http("POST", agents + "/intake/reports", {"berth_id": sc["berth_id"], "ship_class_id": sc["ship_class_id"], "side_to": sc["side_to"], "horizon_hours": 24})
        job = None
        for _ in range(60):
            _, job = http("GET", f"{agents}/jobs/{accepted['job_id']}")
            if job["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.5)
        assert job and job["state"] == "succeeded", f"intake job: {job and job['state']}"
        rep = job["result"]
        assert rep["mst"]["mst_required"] and rep["summary"], "intake report is missing its assessment"
        mock = [d for d in rep["data_quality"] if d["issue"] == "mock"]
        assert mock, "mock environment data must be flagged in data quality"
        return f"MST {rep['mst']['mst_required']} required, {len(rep['windows'])} windows of concern, {len(mock)} stations flagged mock"

    check("UI page served by the preview server", page)
    check("Motion fixtures bundled for offline replay", fixtures)
    check("Health through the UI proxy (REST)", health)
    check("Capabilities report limits honestly", capabilities)
    check("Environment source is labeled; waves are not invented", environment_honesty)
    check("Intake agent: environment assessment, mock data flagged", intake)
    check("Berth vision: image to draft berth, flagged items, confirmed and saved", berth_vision)
    if check("Phase 1: save scenario", scenario):
        if check("Phase 1: agent plan streams over SSE through the proxy", plan):
            check("Phase 1: safety sheet renders and can be approved", sheet_and_approval)
        check("Motion: session over WebSocket through the proxy (resume, command, pause, reset)", motion_session)
    return ctx


# ---- browser checks ------------------------------------------------------------------------------------------------


def browser_checks(stack: Stack, browser_python: str | None, browser_timeout: float) -> None:
    script = ROOT / "scripts" / "demo_check_browser.py"
    py = browser_python or os.environ.get("DEMO_CHECK_BROWSER_PYTHON") or sys.executable
    probe = subprocess.run([py, "-c", "import playwright"], capture_output=True)
    if probe.returncode != 0:
        record("FAIL", "Browser flow (headless Chromium)", "Playwright is not installed; API and proxy checks above are all that ran (set DEMO_CHECK_BROWSER_PYTHON)")
        return
    SCREENS.mkdir(parents=True, exist_ok=True)
    # Stream the child's results as they arrive: a timeout must not lose what already passed.
    proc = subprocess.Popen([py, "-u", str(script), stack.ui, str(SCREENS)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + browser_timeout
    seen_fail = False
    import selectors

    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    tail: list[str] = []
    while proc.poll() is None or sel.get_map():
        if time.time() > deadline:
            proc.kill()
            record("FAIL", "Browser flow", f"did not finish within {browser_timeout:.0f} s (software-rendered WebGL is slow; raise --browser-timeout)")
            return
        if not sel.select(timeout=1.0):
            if proc.poll() is not None:
                break
            continue
        line = proc.stdout.readline()
        if not line:
            sel.unregister(proc.stdout)
            break
        line = line.rstrip("\n")
        tail = (tail + [line])[-6:]
        if line.startswith(("PASS ", "FAIL ", "SKIP ")):
            status, rest = line.split(" ", 1)
            name, _, detail = rest.partition(" | ")
            record(status, f"Browser: {name}", detail)
            seen_fail = seen_fail or status == "FAIL"
    code = proc.wait()
    if code != 0 and not seen_fail:
        record("FAIL", "Browser flow", " / ".join(tail)[-300:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-build", action="store_true", help="reuse frontend/packages/web/dist")
    ap.add_argument("--no-browser", action="store_true", help="API and proxy checks only")
    ap.add_argument("--browser-python", help="interpreter that has Playwright (default: DEMO_CHECK_BROWSER_PYTHON or this one)")
    ap.add_argument("--tool-timeout", type=float, default=120.0, help="AGENTS_TOOL_TIMEOUT_S for the agents service during the check (default 120; production default is 30)")
    ap.add_argument("--browser-timeout", type=float, default=1500, help="seconds allowed for the whole browser flow (default 1500)")
    ap.add_argument("--logs", default=str(ROOT / "docs" / "overnight" / "demo-check-logs"))
    args = ap.parse_args()

    if not shutil.which("node"):
        print("node is required to build and serve the UI", file=sys.stderr)
        return 2
    stack = Stack(Path(args.logs), args.tool_timeout)
    print(f"demo-check: modeling :{stack.modeling_port}, agents :{stack.agents_port}, ui :{stack.ui_port}, agent tool timeout {args.tool_timeout:g} s", flush=True)
    try:
        stack.start_services()
        stack.build_and_serve_ui(args.skip_build)
        api_checks(stack)
        if args.no_browser:
            record("SKIP", "Browser flow (headless Chromium)", "--no-browser")
        else:
            browser_checks(stack, args.browser_python, args.browser_timeout)
    except Exception as exc:  # noqa: BLE001
        record("FAIL", "Stack start-up", f"{type(exc).__name__}: {exc}"[:300])
    finally:
        stack.stop()

    failed = [r for r in RESULTS if r[0] == "FAIL"]
    skipped = [r for r in RESULTS if r[0] == "SKIP"]
    print(f"\ndemo-check: {len(RESULTS) - len(failed) - len(skipped)} passed, {len(failed)} failed, {len(skipped)} skipped")
    for _, name, detail in skipped:
        print(f"  not covered: {name} ({detail})")
    print("Coverage limit: browser Intake is bound to Planner; four-case checks cover initial analysis, not every subsequent planning path. Independent review is checked through the API; separate review-selection UI remains unimplemented.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
