#!/usr/bin/env bash
# deploy/update.sh — 滾動更新（零停機）
# 在 server 上執行：cd /opt/aiops && bash deploy/update.sh [--rebuild-frontend]
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REBUILD=false
[[ "${1:-}" == "--rebuild-frontend" ]] && REBUILD=true

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
fi

echo "🔁  重啟服務..."
# Try systemctl first; fall back to pkill so systemd Restart=on-failure kicks in
if sudo -n systemctl restart fastapi-backend ontology-simulator 2>/dev/null; then
  echo "  systemctl restart OK"
else
  echo "  ⚠️  sudo systemctl failed — using pkill fallback (systemd will auto-restart)"
  pkill -TERM -f "venv_backend/bin/uvicorn"   2>/dev/null || true
  pkill -TERM -f "venv_ontology/bin/python"   2>/dev/null || true
fi

sleep 5
sudo -n systemctl is-active --quiet fastapi-backend   2>/dev/null && echo "  ✅  fastapi-backend  RUNNING" || echo "  ❌  fastapi-backend  FAILED (check: journalctl -u fastapi-backend -n 20)"
sudo -n systemctl is-active --quiet ontology-simulator 2>/dev/null && echo "  ✅  ontology-simulator  RUNNING" || echo "  ❌  ontology-simulator  FAILED (check: journalctl -u ontology-simulator -n 20)"
echo ""
echo "✅  更新完成"
