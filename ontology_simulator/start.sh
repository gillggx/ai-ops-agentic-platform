#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "=== OntologySimulator Startup ==="

# ── NATS ──────────────────────────────────────────────────────
echo "[0/3] Ensuring NATS server (port 4222)..."
if nc -z localhost 4222 2>/dev/null; then
  echo "      NATS already running ✅"
else
  brew services start nats-server 2>/dev/null || true
  sleep 1
  nc -z localhost 4222 2>/dev/null \
    && echo "      NATS started ✅" \
    || echo "      ⚠️  NATS unavailable — OOC events will be skipped"
fi

# ── MongoDB ──────────────────────────────────────────────────
echo "[1/3] Starting MongoDB..."
brew services start mongodb/brew/mongodb-community 2>/dev/null || true

# ── Kill anything on port 8001 ────────────────────────────────
PIDS=$(lsof -ti :8001 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  echo "[2/3] Freeing port 8001 (PID $PIDS)..."
  kill $PIDS
  sleep 1
else
  echo "[2/3] Port 8001 is free."
fi

# ── Backend ───────────────────────────────────────────────────
echo "[3/3] Starting FastAPI backend on :8001..."
cd "$PROJECT_DIR"
.venv/bin/python main.py &
BACKEND_PID=$!
echo "      Backend PID: $BACKEND_PID"

# Wait for backend to be ready
sleep 2

# ── Frontend ──────────────────────────────────────────────────
echo "[4/3] Starting Next.js frontend on :3000..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!
echo "      Frontend PID: $FRONTEND_PID"

echo ""
echo "✓ All services started"
echo "  Dashboard  → http://localhost:3000"
echo "  API Docs   → http://localhost:8001/docs"
echo ""
echo "Press Ctrl+C to stop everything."

# Trap Ctrl+C and kill both processes
trap "echo ''; echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM

wait
