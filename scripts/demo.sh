#!/usr/bin/env bash
# One-command local demo (Linux/macOS/Git Bash):   ./scripts/demo.sh
# Creates the Python environment, installs dependencies, builds everything from data/raw/train.csv
# (skipping finished steps), starts the API on :8000 and the frontend on :5173.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

cd "$root/backend"
[ -d .venv ] || python3 -m venv .venv
PY=".venv/bin/python"; [ -x "$PY" ] || PY=".venv/Scripts/python"
[ "${SKIP_INSTALL:-0}" = "1" ] || "$PY" -m pip install -r requirements.txt
"$PY" -m app.bootstrap

echo "Starting the API on http://localhost:8000 ..."
"$PY" -m uvicorn app.main:app --port 8000 &
api_pid=$!
trap 'kill $api_pid 2>/dev/null || true' EXIT

cd "$root/frontend"
[ -d node_modules ] || npm install
echo "Starting the frontend on http://localhost:5173 (demo accounts: see README)"
npm run dev
