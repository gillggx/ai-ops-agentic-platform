#!/usr/bin/env bash
# start.sh — 啟動所有服務（FastAPI Backend + OntologySimulator）
# 用法：./start.sh [--no-build]
#   --no-build  跳過 Next.js 靜態建置

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. 終止佔用 port 8000 / 8001 的程序 ─────────────────────────────────────
echo "🛑  正在終止 port 8000 / 8001 上的程序..."
for PORT in 8000 8001; do
  PIDS=$(lsof -ti tcp:$PORT 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "    kill port $PORT → PID(s): $PIDS"
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
  fi
done
sleep 1

# ── 2. （可選）重新建置 Next.js 靜態檔案 ────────────────────────────────────
FRONTEND_DIR="$REPO_ROOT/ontology_simulator/frontend"
BUILD_FLAG=true
for arg in "$@"; do
  [ "$arg" = "--no-build" ] && BUILD_FLAG=false
done

if $BUILD_FLAG && [ -f "$FRONTEND_DIR/package.json" ]; then
  echo "🔨  建置 OntologySimulator 前端 (Next.js export)..."
  cd "$FRONTEND_DIR"
  npm run build 2>&1 | tail -5
  cd "$REPO_ROOT"
  echo "✅  前端建置完成 → ontology_simulator/frontend/out/"
else
  echo "⏭️  跳過前端建置（--no-build 或 package.json 不存在）"
fi

# ── 3. 啟動 OntologySimulator 後端 (port 8001) ───────────────────────────────
echo ""
echo "🚀  啟動 OntologySimulator (port 8001)..."
LOG_ONTO="$REPO_ROOT/logs/ontology_simulator.log"
mkdir -p "$REPO_ROOT/logs"
cd "$REPO_ROOT/ontology_simulator"
nohup python main.py > "$LOG_ONTO" 2>&1 &
ONTO_PID=$!
echo "    PID=$ONTO_PID  log=$LOG_ONTO"

# ── 4. 啟動 FastAPI Backend Service (port 8000) ───────────────────────────────
echo ""
echo "🚀  啟動 FastAPI Backend Service (port 8000)..."
LOG_FAST="$REPO_ROOT/logs/fastapi_backend.log"
cd "$REPO_ROOT/fastapi_backend_service"
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --reload > "$LOG_FAST" 2>&1 &
FAST_PID=$!
echo "    PID=$FAST_PID  log=$LOG_FAST"

# ── 5. 等待服務就緒 ──────────────────────────────────────────────────────────
echo ""
echo "⏳  等待服務啟動..."
sleep 3

check_port() {
  lsof -ti tcp:$1 >/dev/null 2>&1
}

for i in {1..10}; do
  ONTO_OK=false; FAST_OK=false
  check_port 8001 && ONTO_OK=true
  check_port 8000 && FAST_OK=true
  $ONTO_OK && $FAST_OK && break
  sleep 1
done

echo ""
echo "────────────────────────────────────────────────────────"
$ONTO_OK && echo "  ✅  OntologySimulator  → http://localhost:8001" \
         || echo "  ❌  OntologySimulator 啟動失敗，請查看 $LOG_ONTO"
$FAST_OK && echo "  ✅  FastAPI Backend    → http://localhost:8000" \
         || echo "  ❌  FastAPI Backend 啟動失敗，請查看 $LOG_FAST"
echo ""
echo "  📊  MES 模擬器（iframe） → http://localhost:8000  (第2頁)"
echo "  📊  MES 模擬器（獨立）   → http://localhost:8000/simulator/"
echo "  📡  API Docs             → http://localhost:8000/docs"
echo "────────────────────────────────────────────────────────"
echo ""
echo "停止所有服務：kill $ONTO_PID $FAST_PID"
echo "  或：lsof -ti tcp:8000,8001 | xargs kill -9"
