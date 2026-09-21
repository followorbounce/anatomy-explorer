#!/usr/bin/env bash
# Serve the site locally (browsers block 3D model loading from file://).
cd "$(dirname "$0")"
PORT="${1:-8000}"
echo "Open http://localhost:$PORT/  (Ctrl+C to stop)"
exec python3 -m http.server "$PORT"
