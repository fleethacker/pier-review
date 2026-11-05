#!/bin/bash
# Domino app entry point for the exercise simulator.
#
# Serves the built page on :$PORT (8888 by default) and, when it can, the small exercise service on a loopback port
# behind it, which hands the page its Mapbox token and keeps the shared scenario library. The simulation runs in the
# browser, so the page still works if the service does not start: it then keeps scenarios in the browser and asks for a
# token.
#
# App environment variables worth setting: MAPBOX_TOKEN (a public pk. token, served to the page at run time) and
# EXERCISE_DATA_DIR (a path on a persistent volume for the shared library; /mnt/data/exercise by default).
set -euo pipefail
cd "$(dirname "$0")"

export PORT="${PORT:-8888}"
export EXERCISE_PORT="${EXERCISE_PORT:-8200}"
export EXERCISE_DATA_DIR="${EXERCISE_DATA_DIR:-/mnt/data/exercise}"
export EXERCISE_PROXY_TARGET="http://127.0.0.1:${EXERCISE_PORT}"
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=3072}"

# Vite 7 needs a newer Node than some app images ship. Fetch an official build for this run, checked against the
# published SHA-256, exactly as the mooring app does.
NODE_VERSION="v22.17.0"
needs_node() {
  command -v node >/dev/null 2>&1 || return 0
  ! node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 22 || (a === 22 && b >= 17) ? 0 : 1)'
}
if needs_node; then
  dir="${TMPDIR:-/tmp}/node-${NODE_VERSION}"
  if [ ! -x "$dir/bin/node" ]; then
    echo "Node >=22.17 not found; fetching official Node ${NODE_VERSION} for this run."
    tarball="node-${NODE_VERSION}-linux-x64.tar.xz"
    work="$(mktemp -d)"
    curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/${tarball}" -o "$work/$tarball"
    curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/SHASUMS256.txt" -o "$work/SHASUMS256.txt"
    (cd "$work" && grep " ${tarball}\$" SHASUMS256.txt | sha256sum -c -)
    mkdir -p "$dir"
    tar -xJf "$work/$tarball" -C "$dir" --strip-components=1
    rm -rf "$work"
  fi
  export PATH="$dir/bin:$PATH"
fi
echo "Using node $(node -v), npm $(npm -v)"

# Start from a clean tree: the project directory an app starts from is not always as clean as a fresh clone, and a
# leftover node_modules makes npm fail while reading what is already there.
rm -rf node_modules

# With a lockfile, `npm ci` installs the pinned tree and never resolves versions itself. Without one, `npm install` has
# to build the tree from registry metadata, and npm 10.9 dies doing it here ("Cannot read properties of null (reading
# 'edgesOut')"), which is what kept this app from starting. Keep the lockfile committed.
install() {
  if [ -f package-lock.json ]; then
    npm ci --no-audit --no-fund
  else
    echo "No package-lock.json: falling back to npm install, which npm 10.9 is known to fail on here." >&2
    npm install --no-audit --no-fund
  fi
}
if ! install; then
  echo "--- npm debug log ---" >&2
  for log in "${HOME:-/home/ubuntu}"/.npm/_logs/*-debug-0.log; do
    [ -f "$log" ] && { echo "$log" >&2; tail -n 60 "$log" >&2; }
  done
  exit 1
fi
npm run build

# The service is optional, so a failure here is a warning, not the end of the app.
service_pid=""
cleanup() {
  trap '' TERM INT
  if [ -n "$service_pid" ]; then
    kill -TERM "$service_pid" 2>/dev/null || true
    wait "$service_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if command -v uv >/dev/null 2>&1; then
  echo "Starting the exercise service on :${EXERCISE_PORT} (library in ${EXERCISE_DATA_DIR})."
  (cd server && exec uv run --quiet uvicorn exercise_api.main:app --host 127.0.0.1 --port "${EXERCISE_PORT}") &
  service_pid=$!
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${EXERCISE_PORT}/api/v1/health" >/dev/null 2>&1; then
      echo "The exercise service is up."
      break
    fi
    if ! kill -0 "$service_pid" 2>/dev/null; then
      echo "The exercise service stopped; serving the page without it (scenarios stay in the browser)." >&2
      service_pid=""
      break
    fi
    sleep 1
  done
else
  echo "No uv in this environment; serving the page without the service (scenarios stay in the browser)." >&2
fi

echo "Serving the exercise simulator on :${PORT}."
exec node node_modules/vite/bin/vite.js preview --host 0.0.0.0 --port "${PORT}" --strictPort
