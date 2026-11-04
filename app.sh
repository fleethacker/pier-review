#!/bin/bash
# Domino app entry point: the modeling API (:8000), the agents API (:8001) and the built UI (:8888) in one container.
# Only the UI port is exposed; its preview server proxies /api/modeling and /api/agents to the two services.
# Needs Python 3.12 with uv and Node 20 with npm (the Mooring-UI-Node20-Uv environment has both).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8888}"
export UV_LINK_MODE=copy

# --- Node 20 -----------------------------------------------------------------------------------------------------
node_major() { node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/'; }
if ! command -v npm >/dev/null 2>&1 || [ "$(node_major || echo 0)" -lt 20 ]; then
  echo "Node 20 with npm not found; downloading one for this run."
  NODE_DIR="${TMPDIR:-/tmp}/node-v20"
  if [ ! -x "$NODE_DIR/bin/node" ]; then
    mkdir -p "$NODE_DIR"
    curl -fsSL https://nodejs.org/dist/v20.18.1/node-v20.18.1-linux-x64.tar.xz | tar -xJ -C "$NODE_DIR" --strip-components=1
  fi
  export PATH="$NODE_DIR/bin:$PATH"
fi

# --- Python services -----------------------------------------------------------------------------------------------
uv sync --all-packages --frozen
export MODELING_API_URL="http://127.0.0.1:8000/api/v1"   # how the agents service reaches modeling
.venv/bin/uvicorn modeling_api.main:app --host 127.0.0.1 --port 8000 &
.venv/bin/uvicorn mooring_agents.api.main:app --host 127.0.0.1 --port 8001 &
trap 'kill $(jobs -p) 2>/dev/null || true' EXIT

# --- UI ------------------------------------------------------------------------------------------------------------
# Proxy targets are the service roots; the UI adds /api/v1 and /ws itself.
export MODELING_PROXY_TARGET="http://127.0.0.1:8000" AGENTS_PROXY_TARGET="http://127.0.0.1:8001"
export NODE_OPTIONS="--max-old-space-size=3072"
cd frontend/packages/web
npm ci --no-audit --no-fund
npm run build
npx vite preview --host 0.0.0.0 --port "$PORT" --strictPort
