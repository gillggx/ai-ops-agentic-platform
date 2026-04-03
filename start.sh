#!/usr/bin/env bash
# start.sh — 啟動所有服務（FastAPI Backend + OntologySimulator）
# 用法：./start.sh [--no-build]
#   --no-build  跳過 Next.js 靜態建置（已有 out/ 時使用）

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Python interpreters (prefer repo venvs) ───────────────────────────────────
BACKEND_UVICORN="$REPO_ROOT/.venv/bin/uvicorn"
ONTOLOGY_PYTHON="$REPO_ROOT/ontology_simulator/.venv/bin/python"
[ -f "$BACKEND_UVICORN" ] || BACKEND_UVICORN="uvicorn"
[ -f "$ONTOLOGY_PYTHON" ] || ONTOLOGY_PYTHON="python3"

# ── Parse flags ───────────────────────────────────────────────────────────────
# Default: skip build if out/ already exists (dev-friendly).
# Pass --build to force rebuild; --no-build to always skip.
FORCE_BUILD=false
SKIP_BUILD=false
for arg in "$@"; do
  [ "$arg" = "--build"    ] && FORCE_BUILD=true
  [ "$arg" = "--no-build" ] && SKIP_BUILD=true
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
    echo "    ⚠️  NATS failed to start — OOC events will be skipped (HTTP API unaffected)"
  fi
fi

# ── 1. Kill any process on port 8000 / 8001 ──────────────────────────────────
echo "🛑  清除 port 8000 / 8001..."
for PORT in 8000 8001; do
  PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "    kill $PORT → PID(s): $PIDS"
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
  fi
done
sleep 1

# ── 2. Build Next.js static export ───────────────────────────────────────────
FRONTEND_DIR="$REPO_ROOT/ontology_simulator/frontend"

NEED_BUILD=false
if $SKIP_BUILD; then
  NEED_BUILD=false
elif $FORCE_BUILD; then
  NEED_BUILD=true
elif [ ! -d "$FRONTEND_DIR/out" ]; then
  NEED_BUILD=true  # first run: no out/ yet
fi

if $NEED_BUILD && [ -f "$FRONTEND_DIR/package.json" ]; then
  echo ""
  echo "🔨  建置 Next.js 前端..."
  cd "$FRONTEND_DIR"
  if npm run build 2>&1; then
    echo "✅  前端建置完成 → out/ ($(du -sh out 2>/dev/null | cut -f1 || echo '?'))"
  else
    echo "❌  前端建置失敗，中止啟動" >&2
    exit 1
  fi
  cd "$REPO_ROOT"
else
  echo "⏭️  跳過前端建置（out/ 已存在；--build 可強制重建）"
fi

# ── 3. Start OntologySimulator backend (port 8001) ───────────────────────────
echo ""
echo "🚀  啟動 OntologySimulator (port 8001)..."
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
nohup "$BACKEND_UVICORN" main:app --host 0.0.0.0 --port 8000 > "$LOG_FAST" 2>&1 &
FAST_PID=$!
echo "    PID=$FAST_PID  log=$LOG_FAST"

# ── 5. HTTP health checks (max 30s each) ─────────────────────────────────────
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
    (( $(date +%s) >= deadline )) && echo "❌  timeout" && return 1
    sleep 1
    printf "."
  done
}

ONTO_OK=false; FAST_OK=false; SIM_OK=false; NEXUS_OK=false
wait_http "http://127.0.0.1:8001/api/v1/status"  "OntologySimulator (8001)"  && ONTO_OK=true  || true
wait_http "http://127.0.0.1:8000/health"          "FastAPI Backend (8000)"    && FAST_OK=true  || true
wait_http "http://127.0.0.1:8000/simulator/"       "Simulator UI (/simulator/)" && SIM_OK=true  || true
wait_http "http://127.0.0.1:8000/simulator/nexus/" "Ontology Nexus (/nexus/)"  && NEXUS_OK=true || true

# ── 6. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
$FAST_OK  && echo "  ✅  FastAPI Backend      → http://localhost:8000" \
          || echo "  ❌  FastAPI Backend      起動失敗 → tail $LOG_FAST"
$ONTO_OK  && echo "  ✅  OntologySimulator    → http://localhost:8001" \
          || echo "  ❌  OntologySimulator    起動失敗 → tail $LOG_ONTO"
$SIM_OK   && echo "  ✅  MES 模擬器 (iframe)  → http://localhost:8000  (Sidebar Page 2)" \
          || echo "  ⚠️   MES 模擬器          未就緒"
$NEXUS_OK && echo "  ✅  Ontology Nexus       → http://localhost:8000  (Sidebar Nexus)" \
          || echo "  ⚠️   Ontology Nexus      未就緒（需確認 out/nexus/ 存在）"
echo ""
echo "  📡  API Docs    → http://localhost:8000/docs"
echo "  🔬  v2 Fanout   → http://localhost:8001/api/v2/ontology/orphans"
nc -z localhost 4222 2>/dev/null \
  && echo "  ✅  NATS Server          → nats://localhost:4222" \
  || echo "  ⚠️   NATS Server         未運行（OOC event 不會觸發 Auto-Patrol）"
echo "════════════════════════════════════════════════════════"
echo ""
echo "停止：kill $ONTO_PID $FAST_PID"
echo "  或：lsof -ti tcp:8000,8001 | xargs kill -9"
