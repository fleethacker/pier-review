#!/bin/bash
# Domino/local demo entry point: two loopback APIs behind the UI proxy on :8888.
# Install uv and Node >=22.17 with npm in the app environment before launching.
set -euo pipefail
cd "$(dirname "$0")"

export PORT="${PORT:-8888}"
# Normal application startup makes an explicit honest source choice. Operators can
# override this with coops, replay or mock; auto never falls through to mock.
export MOORING_ENV_SOURCE="${MOORING_ENV_SOURCE:-auto}"

# Bootstrap must be supervised before the project Python interpreter exists.
# Bash job control gives each background installer a process group on macOS and
# Linux; terminating the launcher also terminates npm/uv and their descendants.
set -m
bootstrap_pid=""
bootstrap_cleanup() {
  if [ -n "$bootstrap_pid" ]; then
    kill -TERM -- "-$bootstrap_pid" 2>/dev/null || true
    local deadline=$((SECONDS + 5))
    while kill -0 -- "-$bootstrap_pid" 2>/dev/null && [ "$SECONDS" -lt "$deadline" ]; do
      sleep 0.1
    done
    kill -KILL -- "-$bootstrap_pid" 2>/dev/null || true
    wait "$bootstrap_pid" 2>/dev/null || true
    bootstrap_pid=""
  fi
}
trap 'trap "" TERM INT; bootstrap_cleanup' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

bootstrap_step() {
  local status=0
  "$@" &
  bootstrap_pid=$!
  wait "$bootstrap_pid" || status=$?
  bootstrap_cleanup
  return "$status"
}

for tool in uv node npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing $tool. Install uv and Node >=22.17 with npm in the app environment; see docs/DEPLOYMENT_READINESS.md." >&2
    exit 1
  fi
done
# The locked Cesium packages require >=22.17.0, including in a Node 20 Domino image.
if ! bootstrap_step node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 17) ? 0 : 1)'; then
  echo "Node >=22.17 is required by the locked UI dependencies. Update the app environment." >&2
  exit 1
fi

export UV_LINK_MODE=copy
bootstrap_step uv sync --all-packages --frozen
# Assign after the shell starts, which may strip outer DYLD_ variables on macOS.
if [ -n "${PDF_LIBRARY_PATH:-}" ]; then
  export DYLD_FALLBACK_LIBRARY_PATH="$PDF_LIBRARY_PATH"
fi
export MODELING_PORT="${MODELING_PORT:-8000}"
export AGENTS_PORT="${AGENTS_PORT:-8001}"
export MODELING_API_URL="http://127.0.0.1:${MODELING_PORT}/api/v1"
export MODELING_PROXY_TARGET="http://127.0.0.1:${MODELING_PORT}"
export AGENTS_PROXY_TARGET="http://127.0.0.1:${AGENTS_PORT}"
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=3072}"
# VITE_MAPBOX_TOKEN, when configured on the app, is read by Vite at build time.
# The public pk. token is bundled in the UI; no token keeps the offline imagery fallback.
bootstrap_step npm --prefix frontend/packages/web ci --no-audit --no-fund
bootstrap_step npm --prefix frontend/packages/web run build

# Supervise direct child processes, so SIGTERM and a failed backend stop the whole
# app. Python supplies the same process-group cleanup on Linux and macOS.
set +m
trap - EXIT TERM INT
exec .venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

root = Path.cwd()
web = root / "frontend/packages/web"
children = []


def stop(signum, _frame):
    raise SystemExit(128 + signum)


def spawn(name, command, cwd=root):
    child = subprocess.Popen(command, cwd=cwd, start_new_session=True)
    children.append((name, child))


def require_running():
    for name, child in children:
        code = child.poll()
        if code is not None:
            raise RuntimeError(f"{name} exited unexpectedly (status {code})")


def wait_ready(url, name, timeout, health=False):
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        require_running()
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200 and (not health or json.loads(response.read(65536)).get("status") == "ok"):
                    require_running()
                    return
                last = f"HTTP {response.status}"
        except (OSError, ValueError, AttributeError) as exc:
            last = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"{name} did not become ready at {url}: {last}")


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    port = int(os.environ.get("PORT", "8888"))
    modeling_port = int(os.environ["MODELING_PORT"])
    agents_port = int(os.environ["AGENTS_PORT"])
    timeout = float(os.environ.get("APP_STARTUP_TIMEOUT_S", "60"))
    ports = (port, modeling_port, agents_port)
    if any(not 1 <= value <= 65535 for value in ports) or len(set(ports)) != 3 or not 0 < timeout <= 600:
        raise ValueError("PORT, MODELING_PORT and AGENTS_PORT must be distinct in 1..65535; APP_STARTUP_TIMEOUT_S must be >0 and <=600")
    uvicorn = str(root / ".venv/bin/uvicorn")
    spawn("modeling", [uvicorn, "modeling_api.main:app", "--host", "127.0.0.1", "--port", str(modeling_port)])
    spawn("agents", [uvicorn, "mooring_agents.api.main:app", "--host", "127.0.0.1", "--port", str(agents_port)])
    wait_ready(f"http://127.0.0.1:{modeling_port}/api/v1/health", "modeling", timeout, health=True)
    wait_ready(f"http://127.0.0.1:{agents_port}/api/v1/health", "agents", timeout, health=True)
    spawn("UI", ["node", str(web / "node_modules/vite/bin/vite.js"), "preview", "--host", "0.0.0.0", "--port", str(port), "--strictPort"], web)
    wait_ready(f"http://127.0.0.1:{port}/", "UI", timeout)
    wait_ready(f"http://127.0.0.1:{port}/api/modeling/api/v1/health", "modeling proxy", timeout, health=True)
    wait_ready(f"http://127.0.0.1:{port}/api/agents/api/v1/health", "agents proxy", timeout, health=True)
    print(f"Demo app ready on :{port}; modeling and agents are reachable through the UI proxy.", flush=True)
    while True:
        require_running()
        time.sleep(0.5)
except (OSError, RuntimeError, ValueError) as exc:
    print(f"App startup/runtime failure: {exc}", file=sys.stderr, flush=True)
    sys.exit(1)
finally:
    # Ignore repeated signals while reaping the groups; cap shutdown at five seconds.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    for _, child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    for _, child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    for _, child in children:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
PY
