#!/usr/bin/env bash
# deploy/update.sh — 滾動更新（三服務 + health check）
# 用法：cd /opt/aiops && bash deploy/update.sh [--rebuild-simulator-frontend]
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REBUILD_SIM=false
[[ "${1:-}" == "--rebuild-simulator-frontend" ]] && REBUILD_SIM=true

# Auto-enable simulator frontend rebuild if out/ is missing
SIM_FRONTEND="$APP_DIR/ontology_simulator/frontend"
if [[ ! -d "$SIM_FRONTEND/out" ]]; then
  echo "⚡  Simulator out/ not found — auto-enabling rebuild"
  REBUILD_SIM=true
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

# ── Python dependencies ───────────────────────────────────────────────────
echo "🐍  更新 pip 依賴..."
/opt/aiops/venv_backend/bin/pip install -q \
  -r "$APP_DIR/fastapi_backend_service/requirements.txt" asyncpg
/opt/aiops/venv_ontology/bin/pip install -q \
  -r "$APP_DIR/ontology_simulator/requirements.txt"

# ── Alembic migrations ────────────────────────────────────────────────────
echo "🗃️   執行 Alembic migrations..."
cd "$APP_DIR/fastapi_backend_service"
export PYTHONPATH="$APP_DIR/fastapi_backend_service"
/opt/aiops/venv_backend/bin/alembic upgrade head 2>/dev/null || echo "    ⚠️  alembic skipped (no migration head)"

# ── aiops-app build (Next.js standalone) ──────────────────────────────────
echo "🔨  Building aiops-app..."
cd "$APP_DIR/aiops-app"
npm ci --silent
npm run build
# Copy static + public into standalone for self-contained serving
cp -r .next/static .next/standalone/.next/static 2>/dev/null || true
cp -r public .next/standalone/public 2>/dev/null || true
echo "    ✅  aiops-app build 完成"

# ── Simulator frontend (optional) ─────────────────────────────────────────
if $REBUILD_SIM; then
  echo "🔨  Building Simulator frontend..."
  cd "$SIM_FRONTEND"
  npm ci --silent && npm run build
  echo "    ✅  Simulator frontend build 完成 → out/ $(du -sh out | cut -f1)"
fi

# ── Restart services ──────────────────────────────────────────────────────
echo "🔁  重啟服務..."
# Kill stale processes on target ports
sudo -n fuser -k 8000/tcp 2>/dev/null || true
sudo -n fuser -k 8001/tcp 2>/dev/null || true
sudo -n fuser -k 8012/tcp 2>/dev/null || true
sleep 1

if sudo -n systemctl restart fastapi-backend aiops-app ontology-simulator 2>/dev/null; then
  echo "    systemctl restart OK"
else
  echo "    ⚠️  sudo systemctl unavailable — pkill fallback"
  pkill -9 -f "venv_backend/bin/uvicorn"  2>/dev/null || true
  pkill -9 -f "node.*standalone/server.js" 2>/dev/null || true
  pkill -9 -f "venv_ontology/bin/uvicorn"  2>/dev/null || true
  echo "    Waiting 20s for systemd to respawn..."
  sleep 20
fi

# ── Update nginx ──────────────────────────────────────────────────────────
NGINX_CONF="/etc/nginx/sites-available/aiops"
DOMAIN_FILE="$APP_DIR/.nginx_domain"
if [[ -f "$DOMAIN_FILE" ]]; then
  CURRENT_DOMAIN=$(cat "$DOMAIN_FILE")
  sed "s/YOUR_DOMAIN/$CURRENT_DOMAIN/g" "$APP_DIR/deploy/nginx.conf" \
    | sudo tee "$NGINX_CONF" > /dev/null
  echo "    nginx.conf updated (domain=$CURRENT_DOMAIN)"
else
  echo "    ⚠️  .nginx_domain not found — nginx.conf not updated (run setup.sh once)"
fi
if sudo -n nginx -t 2>/dev/null && sudo -n nginx -s reload 2>/dev/null; then
  echo "    nginx reload OK"
else
  echo "    ⚠️  nginx reload skipped"
fi

# ── Health checks ─────────────────────────────────────────────────────────
echo ""
echo "🔍  Health checks..."

BACKEND_OK=false
FRONTEND_OK=false
ONTOLOGY_OK=false

wait_for_http "http://127.0.0.1:8001/health" "FastAPI backend (8001)" && BACKEND_OK=true
wait_for_http "http://127.0.0.1:8000" "AIOps app (8000)" && FRONTEND_OK=true
wait_for_http "http://127.0.0.1:8012/api/v1/status" "Ontology simulator (8012)" && ONTOLOGY_OK=true

echo ""
echo "════════════════════════════════════════"
echo "  Deploy Summary"
echo "════════════════════════════════════════"
$FRONTEND_OK && echo "  ✅  AIOps app             (8000)  HEALTHY" \
             || echo "  ❌  AIOps app             (8000)  FAILED"
$BACKEND_OK  && echo "  ✅  FastAPI backend       (8001)  HEALTHY" \
             || echo "  ❌  FastAPI backend       (8001)  FAILED"
$ONTOLOGY_OK && echo "  ✅  Ontology simulator    (8012)  HEALTHY" \
             || echo "  ❌  Ontology simulator    (8012)  FAILED"
echo "════════════════════════════════════════"

if ! $BACKEND_OK || ! $FRONTEND_OK || ! $ONTOLOGY_OK; then
  echo ""
  echo "❌  Deploy FAILED — check: journalctl -u <service-name> -n 50"
  exit 1
fi

echo ""
echo "✅  更新完成"
