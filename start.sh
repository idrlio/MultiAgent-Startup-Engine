#!/usr/bin/env bash
# start.sh — Start AgentForge backend + frontend dev servers
# Usage: ./start.sh

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "  🚀 AgentForge"
echo "  ─────────────────────────────────"

# Check .env
if [ ! -f "$ROOT/.env" ]; then
  echo "  ⚠  No .env found — copying .env.example"
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "  ✏  Edit .env and add your ANTHROPIC_API_KEY, then re-run."
  exit 1
fi

# Check venv
if [ ! -d "$ROOT/venv" ]; then
  echo "  Creating Python virtual environment…"
  python3 -m venv "$ROOT/venv"
fi

source "$ROOT/venv/bin/activate"
echo "  Installing Python dependencies…"
pip install -q -r "$ROOT/requirements.txt"

# Check node_modules
if [ ! -d "$ROOT/ui/frontend/node_modules" ]; then
  echo "  Installing frontend dependencies…"
  cd "$ROOT/ui/frontend" && npm install --silent
fi

echo ""
echo "  Starting servers:"
echo "  • Backend  → http://localhost:8000"
echo "  • Frontend → http://localhost:5173"
echo "  ─────────────────────────────────"
echo "  Press Ctrl+C to stop both."
echo ""

# Run both in parallel, kill both on Ctrl+C
cleanup() { kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null; exit 0; }
trap cleanup SIGINT SIGTERM

cd "$ROOT"
PYTHONPATH="$ROOT" uvicorn ui.backend.main:app --reload --port 8000 --log-level warning &
BACKEND_PID=$!

cd "$ROOT/ui/frontend"
npm run dev --silent &
FRONTEND_PID=$!

wait
