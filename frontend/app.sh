#!/bin/bash
set -e
# Backends (the frontend proxies /api/* to these)
cd /mnt/code/frontend/packages/python-yolo && python main.py > /tmp/yolo.log 2>&1 &
cd /mnt/code/frontend/packages/ml && python model_server.py > /tmp/ml.log 2>&1 &

# Frontend
cd /mnt/code/frontend/packages/web
npm install --no-audit --no-fund
npx vite build
exec npx vite preview --host 0.0.0.0 --port 8888 --strictPort
