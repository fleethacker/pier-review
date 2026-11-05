"""Exercise launcher lifecycle with tiny local HTTP services, no installs/providers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
STUB = r'''
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

tool = Path(sys.argv[0]).name
stage = "uv" if tool == "uv" else ("npm-build" if "build" in sys.argv else "npm-ci")
if tool in {"uv", "npm"} and os.environ.get("APP_TEST_PAUSE_STAGE") == stage:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    def terminate(*_):
        child.wait(timeout=5)
        sys.exit(0)
    signal.signal(signal.SIGTERM, terminate)
    with open(os.environ["APP_TEST_PID_LOG"], "a") as stream:
        stream.write(json.dumps({"name": stage, "pid": os.getpid()}) + "\n")
        stream.write(json.dumps({"name": stage + "-child", "pid": child.pid}) + "\n")
    time.sleep(60)
if tool == "uv":
    sys.exit(0)
if tool == "npm":
    sys.exit(17 if os.environ.get("APP_TEST_BUILD_FAIL") and "build" in sys.argv else 0)
if tool == "node" and "-e" in sys.argv:
    sys.exit(1 if os.environ.get("APP_TEST_OLD_NODE") else 0)
name = "ui" if tool == "node" else ("modeling" if "modeling_api" in sys.argv[1] else "agents")
port = int(sys.argv[sys.argv.index("--port") + 1])
with open(os.environ["APP_TEST_PID_LOG"], "a") as stream:
    stream.write(json.dumps({"name": name, "pid": os.getpid()}) + "\n")
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(503 if os.environ.get("APP_TEST_UNHEALTHY") == name else 200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
    def log_message(self, *args):
        pass
server = HTTPServer(("127.0.0.1", port), Handler)
server.timeout = 0.05
while True:
    if Path(os.environ["APP_TEST_FAIL_FILE"]).exists() and os.environ.get("APP_TEST_FAIL_SERVICE") == name:
        sys.exit(0)  # even an unexpected clean service exit must stop the app
    server.handle_request()
'''


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def launcher(tmp_path):
    shutil.copy(ROOT / "app.sh", tmp_path / "app.sh")
    bindir = tmp_path / "bin"
    venv = tmp_path / ".venv/bin"
    web = tmp_path / "frontend/packages/web"
    for directory in (bindir, venv, web):
        directory.mkdir(parents=True)
    for executable in (bindir / "uv", bindir / "node", bindir / "npm", venv / "uvicorn"):
        executable.write_text(f"#!{sys.executable}\n" + STUB)
        executable.chmod(0o755)
    (venv / "python").symlink_to(sys.executable)
    ports = set()
    while len(ports) < 3:
        ports.add(free_port())
    ui, modeling, agents = ports
    env = {
        **os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
        "PORT": str(ui), "MODELING_PORT": str(modeling), "AGENTS_PORT": str(agents),
        "APP_STARTUP_TIMEOUT_S": "3", "APP_TEST_PID_LOG": str(tmp_path / "children.jsonl"),
        "APP_TEST_FAIL_FILE": str(tmp_path / "fail"),
    }
    processes = []

    def launch(**overrides):
        proc = subprocess.Popen(["/bin/bash", str(tmp_path / "app.sh")], env={**env, **overrides},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        processes.append(proc)
        return proc

    yield tmp_path, launch
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
        proc.communicate(timeout=10)


def children(path):
    log = path / "children.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def wait_for_children(path, proc, count=3):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if len(children(path)) == count:
            return
        if proc.poll() is not None:
            pytest.fail(f"launcher stopped early: {proc.communicate()[0]}")
        time.sleep(0.05)
    pytest.fail(f"expected {count} children, got {children(path)}")


def assert_reaped(path):
    for child in children(path):
        with pytest.raises(ProcessLookupError):
            os.kill(child["pid"], 0)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_launcher_signal_stops_all_services(launcher, signum):
    path, launch = launcher
    proc = launch()
    wait_for_children(path, proc)
    proc.send_signal(signum)
    output, _ = proc.communicate(timeout=10)
    assert proc.returncode == 128 + signum, output
    assert_reaped(path)


@pytest.mark.parametrize("stage", ["uv", "npm-ci", "npm-build"])
@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_launcher_signal_during_bootstrap_stops_installer_and_descendants(launcher, stage, signum):
    path, launch = launcher
    proc = launch(APP_TEST_PAUSE_STAGE=stage)
    wait_for_children(path, proc, count=2)
    proc.send_signal(signum)
    output, _ = proc.communicate(timeout=10)
    assert proc.returncode == 128 + signum, output
    assert {child["name"] for child in children(path)} == {stage, stage + "-child"}
    assert_reaped(path)


@pytest.mark.parametrize("service", ["modeling", "agents", "ui"])
def test_launcher_service_exit_stops_siblings(launcher, service):
    path, launch = launcher
    proc = launch(APP_TEST_FAIL_SERVICE=service)
    wait_for_children(path, proc)
    (path / "fail").touch()
    output, _ = proc.communicate(timeout=10)
    assert proc.returncode == 1, output
    assert "exited unexpectedly (status 0)" in output
    assert_reaped(path)


def test_launcher_unhealthy_api_never_starts_ui(launcher):
    path, launch = launcher
    proc = launch(APP_TEST_UNHEALTHY="agents", APP_STARTUP_TIMEOUT_S="0.5")
    output, _ = proc.communicate(timeout=10)
    assert proc.returncode == 1, output
    assert "did not become ready" in output
    assert {child["name"] for child in children(path)} == {"modeling", "agents"}
    assert_reaped(path)


@pytest.mark.parametrize("setting,expected", [("APP_TEST_BUILD_FAIL", ""), ("APP_TEST_OLD_NODE", "Node >=22.17")])
def test_launcher_prerequisite_failure_starts_no_services(launcher, setting, expected):
    path, launch = launcher
    proc = launch(**{setting: "1"})
    output, _ = proc.communicate(timeout=10)
    assert proc.returncode != 0
    assert expected in output
    assert not children(path)
