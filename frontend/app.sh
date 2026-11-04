#!/bin/bash
# Serves the built UI. Set MODELING_API_URL / AGENTS_API_URL if the services are not on localhost:8000/:8001.
set -e
cd "$(dirname "$0")/packages/web"
npm install --no-audit --no-fund
npx vite build
exec npx vite preview --host 0.0.0.0 --port 8888 --strictPort
