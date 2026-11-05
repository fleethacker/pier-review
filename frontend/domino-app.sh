#!/bin/bash
# Domino app entry for environments whose Node is older than the UI needs (the Mooring-UI-Node20-Uv image has Node 20;
# the locked Cesium packages need Node >=22.17). Provides an official Node 22.17 build for this run, verified against
# nodejs.org's published SHA-256, then runs the repository's app.sh unchanged. Use app.sh directly once the app
# environment ships Node >=22.17 (see docs/DEPLOYMENT_READINESS.md).
set -euo pipefail
cd "$(dirname "$0")/.."

NODE_VERSION="v22.17.0"
needs_node() {
  ! command -v node >/dev/null 2>&1 && return 0
  node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 22 || (a === 22 && b >= 17) ? 1 : 0)'
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
exec ./app.sh "$@"
