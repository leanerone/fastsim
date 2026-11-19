#!/usr/bin/env bash
# FastSim startup script (Linux / macOS / Git Bash)
cd "$(dirname "$0")/backend"
echo "Starting FastSim backend on http://127.0.0.1:8000 ..."
exec python3 -m fastsim.app --host 127.0.0.1 --port 8000 "$@"
