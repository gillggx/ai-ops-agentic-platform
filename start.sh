#!/usr/bin/env bash
# start.sh — 一鍵啟動所有服務
#   1. NATS (brew service)
#   2. OntologySimulator (port 8012)
#   3. FastAPI Backend (port 8000)
#   4. aiops-app Next.js frontend (port 3000)
#
# 用法：./start.sh [--logs]
#   --logs     啟動後 tail -f 所有 log（Ctrl-C 停止 tail，服務繼續跑）

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Python / Node interpreters ────────────────────────────────────────────────
BACKEND_UVICORN="$REPO_ROOT/.venv/bin/uvicorn"
ONTOLOGY_PYTHON="$REPO_ROOT/ontology_simulator/.venv/bin/python"
[ -f "$BACKEND_UVICORN" ] || BACKEND_UVICORN="uvicorn"
[ -f "$ONTOLOGY_PYTHON" ] || ONTOLOGY_PYTHON="python3"

# ── Parse flags ───────────────────────────────────────────────────────────────
SHOW_LOGS=false
for arg in "$@"; do
  [ "$arg" = "--logs" ] && SHOW_LOGS=true
done

# ── 0. Ensure NATS is running ─────────────────────────────────────────────────
echo "📡  確認 NATS server (port 4222)..."
if nc -z localhost 4222 2>/dev/null; then
  echo "    NATS already running ✅"
else
  echo "    Starting NATS via brew services..."
  brew services start nats-server 2>/dev/null || true
  sleep 1
  if nc -z localhost 4222 2>/dev/null; then
    echo "    NATS started ✅"
  else
    echo "    ⚠️  NATS failed to start — OOC events will be skipped"
  fi
fi

# ── 1. Kill any leftover processes on our ports ───────────────────────────────
echo ""
echo "🛑  清除 port 8000 / 8012 / 3000..."
for PORT in 8000 8012 3000; do
  PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "    kill $PORT → PID(s): $PIDS"
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
  fi
done
sleep 1

# ── 2. Ensure Postgres is running ─────────────────────────────────────────────
echo ""
echo "🐘  確認 PostgreSQL..."
if /opt/homebrew/opt/postgresql@17/bin/pg_isready -h localhost -p 5432 -q 2>/dev/null; then
  echo "    PostgreSQL already running ✅"
else
  echo "    Starting PostgreSQL via brew services..."
  brew services start postgresql@17 2>/dev/null || true
  sleep 2
  if /opt/homebrew/opt/postgresql@17/bin/pg_isready -h localhost -p 5432 -q 2>/dev/null; then
    echo "    PostgreSQL started ✅"
  else
    echo "    ❌  PostgreSQL failed to start — backend will crash"
  fi
fi

# ── 3. Start OntologySimulator backend (port 8012) ───────────────────────────
echo ""
echo "🚀  啟動 OntologySimulator (port 8012)..."
mkdir -p "$REPO_ROOT/logs"
LOG_ONTO="$REPO_ROOT/logs/ontology_simulator.log"
cd "$REPO_ROOT/ontology_simulator"
nohup "$ONTOLOGY_PYTHON" main.py > "$LOG_ONTO" 2>&1 &
ONTO_PID=$!
echo "    PID=$ONTO_PID  log=$LOG_ONTO"

# ── 4. Start FastAPI Backend (port 8000) ─────────────────────────────────────
echo ""
echo "🚀  啟動 FastAPI Backend (port 8000)..."
LOG_FAST="$REPO_ROOT/logs/fastapi_backend.log"
cd "$REPO_ROOT/fastapi_backend_service"
nohup "$BACKEND_UVICORN" main:app --host 0.0.0.0 --port 8000 --log-level info > "$LOG_FAST" 2>&1 &
FAST_PID=$!
echo "    PID=$FAST_PID  log=$LOG_FAST"

# ── 5. Start aiops-app Next.js frontend (port 3000) ─────────────────────────
echo ""
echo "🚀  啟動 aiops-app Next.js (port 3000)..."
LOG_NEXT="$REPO_ROOT/logs/aiops-app.log"
cd "$REPO_ROOT/aiops-app"
# Install deps if node_modules missing
if [ ! -d "node_modules" ]; then
  echo "    npm install..."
  npm install --silent 2>&1 | tail -3
fi
nohup npx next dev --port 3000 > "$LOG_NEXT" 2>&1 &
NEXT_PID=$!
echo "    PID=$NEXT_PID  log=$LOG_NEXT"
cd "$REPO_ROOT"

# ── 6. HTTP health checks (max 30s each) ─────────────────────────────────────
echo ""
echo "⏳  等待服務就緒..."

wait_http() {
  local url="$1" label="$2" deadline=$(( $(date +%s) + 30 ))
  printf "    %-40s" "$label"
  while true; do
    if curl -sf --max-time 2 "$url" -o /dev/null 2>/dev/null; then
      echo "✅"
      return 0
    fi
    (( $(date +%s) >= deadline )) && echo "✗ timeout (30s)" && return 1
    sleep 1
    printf "."
  done
}

ONTO_OK=false; FAST_OK=false; NEXT_OK=false
wait_http "http://127.0.0.1:8012/api/v1/status"  "OntologySimulator (8012)"  && ONTO_OK=true  || true
wait_http "http://127.0.0.1:8000/health"          "FastAPI Backend (8000)"    && FAST_OK=true  || true
wait_http "http://127.0.0.1:3000"                 "aiops-app (3000)"         && NEXT_OK=true  || true

# ── 7. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
$FAST_OK  && echo "  ✅  FastAPI Backend      → http://localhost:8000" \
          || echo "  ❌  FastAPI Backend      → tail $LOG_FAST"
$ONTO_OK  && echo "  ✅  OntologySimulator    → http://localhost:8012" \
          || echo "  ❌  OntologySimulator    → tail $LOG_ONTO"
$NEXT_OK  && echo "  ✅  aiops-app            → http://localhost:3000" \
          || echo "  ❌  aiops-app            → tail $LOG_NEXT"
echo ""
echo "  📡  API Docs    → http://localhost:8000/docs"
nc -z localhost 4222 2>/dev/null \
  && echo "  ✅  NATS Server          → nats://localhost:4222" \
  || echo "  ⚠️   NATS Server         未運行"
echo "════════════════════════════════════════════════════════"
echo ""
echo "停止所有服務："
echo "  kill $ONTO_PID $FAST_PID $NEXT_PID"
echo "  或：lsof -ti tcp:8000,8012,3000 | xargs kill -9"

# ── 8. Optional: tail logs ────────────────────────────────────────────────────
if $SHOW_LOGS; then
  echo ""
  echo "📋  tail -f logs (Ctrl-C 停止 tail，服務繼續跑)..."
  tail -f "$LOG_FAST" "$LOG_ONTO" "$LOG_NEXT"
fi
