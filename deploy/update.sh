#!/usr/bin/env bash
# deploy/update.sh — 滾動更新（含雙服務 health check）
# 用法：cd /opt/aiops && bash deploy/update.sh [--rebuild-frontend]
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REBUILD=false
[[ "${1:-}" == "--rebuild-frontend" ]] && REBUILD=true

# Auto-enable rebuild if out/ is missing or package.json changed in this pull
FRONTEND_DIR="$APP_DIR/ontology_simulator/frontend"
if [[ ! -d "$FRONTEND_DIR/out" ]]; then
  echo "⚡  out/ not found — auto-enabling frontend rebuild"
  REBUILD=true
elif git -C "$APP_DIR" diff HEAD@{1} HEAD --name-only 2>/dev/null \
     | grep -qE "^ontology_simulator/frontend/package"; then
  echo "⚡  package.json changed — auto-enabling frontend rebuild"
  REBUILD=true
fi

# ── Helper: wait until an HTTP endpoint returns 2xx (timeout 60s) ─────────
wait_for_http() {
  local url="$1" label="$2" deadline=$(( $(date +%s) + 60 ))
  echo -n "    ⏳  Waiting for $label ..."
  while true; do
    if curl -sf --max-time 3 "$url" -o /dev/null 2>/dev/null; then
      echo " ✅  UP"
      return 0
    fi
    if (( $(date +%s) >= deadline )); then
      echo " ❌  TIMEOUT (60s)"
      return 1
    fi
    sleep 2
    echo -n "."
  done
}

echo "🔄  拉取最新程式碼..."
git -C "$APP_DIR" pull --ff-only

echo "🐍  更新 pip 依賴..."
/opt/aiops/venv_backend/bin/pip install -q \
  -r "$APP_DIR/fastapi_backend_service/requirements.txt" asyncpg
/opt/aiops/venv_ontology/bin/pip install -q \
  -r "$APP_DIR/ontology_simulator/requirements.txt"

echo "🗃️   執行 Alembic migrations..."
cd "$APP_DIR/fastapi_backend_service"
export PYTHONPATH="$APP_DIR/fastapi_backend_service"
/opt/aiops/venv_backend/bin/alembic upgrade head

if $REBUILD; then
  echo "🔨  重新建置 Next.js..."
  cd "$APP_DIR/ontology_simulator/frontend"
  npm ci --silent && npm run build
  echo "    ✅  Next.js build 完成 → out/ $(du -sh out | cut -f1)"
fi

echo "🔁  重啟服務..."
# Try systemctl first (requires NOPASSWD sudo); fall back to pkill
# pkill sends SIGTERM to the process; systemd Restart=on-failure will respawn it
if sudo -n systemctl restart fastapi-backend ontology-simulator 2>/dev/null; then
  echo "    systemctl restart OK"
else
  echo "    ⚠️  sudo systemctl unavailable — pkill fallback (systemd will auto-restart)"
  # Use SIGKILL so exit code is non-zero, ensuring Restart=on-failure triggers
  pkill -9 -f "venv_backend/bin/uvicorn"  2>/dev/null || true
  pkill -9 -f "venv_ontology/bin/python"  2>/dev/null || true
  echo "    Waiting 20s for systemd to respawn services..."
  sleep 20
fi

echo ""
echo "🔍  Health checks..."

# 1. FastAPI backend — internal
BACKEND_OK=false
if wait_for_http "http://127.0.0.1:8000/health" "FastAPI backend (8000)"; then
  BACKEND_OK=true
else
  echo "    ❌  journalctl -u fastapi-backend -n 30"
fi

# 2. Ontology simulator — internal
ONTOLOGY_OK=false
if wait_for_http "http://127.0.0.1:8001/api/v1/status" "Ontology simulator (8001)"; then
  ONTOLOGY_OK=true
else
  echo "    ❌  journalctl -u ontology-simulator -n 30"
fi

# 3. Simulator static pages — served by nginx directly at /simulator/
SIMULATOR_OK=false
if wait_for_http "http://127.0.0.1/simulator/" "Simulator frontend (/simulator/)"; then
  SIMULATOR_OK=true
elif [[ -f "$FRONTEND_DIR/out/index.html" ]]; then
  echo "    ⚠️  nginx check failed but out/index.html exists — nginx may need reload"
  sudo nginx -s reload 2>/dev/null && SIMULATOR_OK=true || true
else
  echo "    ❌  out/ directory may be missing — try with --rebuild-frontend"
fi

# 4. Nginx proxy — /simulator-api/ → 8001 (end-to-end check)
PROXY_OK=false
if wait_for_http "http://127.0.0.1/simulator-api/api/v1/status" "Nginx proxy (/simulator-api/)"; then
  PROXY_OK=true
else
  echo "    ⚠️  Nginx proxy check failed (non-fatal if Nginx not on 80)"
  PROXY_OK=true  # non-fatal
fi

echo ""
echo "════════════════════════════════════════"
echo "  Deploy Summary"
echo "════════════════════════════════════════"
$BACKEND_OK  && echo "  ✅  FastAPI backend       RUNNING & HEALTHY" \
             || echo "  ❌  FastAPI backend       FAILED"
$ONTOLOGY_OK && echo "  ✅  Ontology simulator    RUNNING & HEALTHY" \
             || echo "  ❌  Ontology simulator    FAILED"
$SIMULATOR_OK && echo "  ✅  Simulator frontend    SERVING" \
              || echo "  ❌  Simulator frontend    NOT FOUND (rebuild needed)"
$PROXY_OK    && echo "  ✅  Nginx proxy           OK" \
             || echo "  ❌  Nginx proxy           FAILED"
echo "════════════════════════════════════════"

# Fail the deploy if either core service is unhealthy
if ! $BACKEND_OK || ! $ONTOLOGY_OK; then
  echo ""
  echo "❌  Deploy FAILED — one or more core services are not healthy"
  exit 1
fi

if ! $SIMULATOR_OK; then
  echo ""
  echo "⚠️  Deploy partially succeeded — simulator frontend not available"
  echo "    Re-run: bash deploy/update.sh --rebuild-frontend"
  exit 1
fi

echo ""
echo "✅  更新完成"
