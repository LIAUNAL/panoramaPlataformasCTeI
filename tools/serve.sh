#!/usr/bin/env sh
# Serve the static site locally: ./tools/serve.sh [port]  ->  http://localhost:8000
set -e
cd "$(dirname "$0")/.."
PORT="${1:-8000}"
[ -f docs/index.html ] || uv run python tools/build_landscape.py
echo "Panorama CTeI en http://localhost:$PORT"
exec python3 -m http.server "$PORT" --bind 127.0.0.1 --directory docs
