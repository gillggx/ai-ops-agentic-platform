#!/usr/bin/env bash
# deploy/update.sh — POC rolling update for skill library (aiops-app only).
# 用法：cd /opt/aiops && bash deploy/update.sh
#
# POC scope: simulator removed. Java + sidecar redeploy lives in
# deploy/java-update.sh.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

# ── aiops-app build (Next.js standalone) ──────────────────────────────────
REBUILD_APP=false
if [[ "${1:-}" == "--force-rebuild" ]]; then
  REBUILD_APP=true
elif [[ ! -d "$APP_DIR/aiops-app/.next/standalone" ]]; then
  echo "⚡  .next/standalone not found — auto-enabling rebuild"
  REBUILD_APP=true
elif git -C "$APP_DIR" diff HEAD@{1} HEAD --name-only 2>/dev/null \
     | grep -qE "^aiops-app/"; then
  echo "⚡  aiops-app changed — auto-enabling rebuild"
  REBUILD_APP=true
fi

if $REBUILD_APP; then
  echo "🔨  Building aiops-app..."
  cd "$APP_DIR/aiops-app"
  npm ci --silent
  # build:prod fails fast when INTERNAL_API_TOKEN / NEXTAUTH_SECRET / FASTAPI_BASE_URL
  # are missing or placeholder. EC2 prod env must export them before this runs.
  npm run build:prod
  cp -r .next/static .next/standalone/.next/static 2>/dev/null || true
  cp -r public .next/standalone/public 2>/dev/null || true
  echo "    ✅  aiops-app build 完成"
else
  echo "⏭  aiops-app unchanged — skip build"
fi

# ── Restart services ──────────────────────────────────────────────────────
echo "🔁  重啟服務..."
# update.sh only covers aiops-app. Java + sidecar redeploy lives in
# deploy/java-update.sh — run that separately when those change.
sudo -n fuser -k 8000/tcp 2>/dev/null || true
sleep 1

if sudo -n systemctl restart aiops-app 2>/dev/null; then
  echo "    systemctl restart OK"
else
  echo "    ⚠️  sudo systemctl unavailable — pkill fallback"
  pkill -9 -f "node.*standalone/server.js" 2>/dev/null || true
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

FRONTEND_OK=false
JAVA_OK=false
SIDECAR_OK=false

wait_for_http "http://127.0.0.1:8000" "AIOps app (8000)" && FRONTEND_OK=true
wait_for_http "http://127.0.0.1:8002/api/v1/health" "Java API (8002)" && JAVA_OK=true
# Sidecar replies 401 without service token — that still means it's UP.
if curl -sf --max-time 3 http://127.0.0.1:8050/internal/health -o /dev/null 2>/dev/null \
  || curl -s --max-time 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8050/internal/agent/chat 2>/dev/null | grep -qE "^(401|405|422)$"; then
  SIDECAR_OK=true
fi

echo ""
echo "════════════════════════════════════════"
echo "  Deploy Summary"
echo "════════════════════════════════════════"
$FRONTEND_OK && echo "  ✅  AIOps app             (8000)  HEALTHY" \
             || echo "  ❌  AIOps app             (8000)  FAILED"
$JAVA_OK     && echo "  ✅  Java API              (8002)  HEALTHY" \
             || echo "  ❌  Java API              (8002)  FAILED"
$SIDECAR_OK  && echo "  ✅  Python sidecar        (8050)  HEALTHY" \
             || echo "  ❌  Python sidecar        (8050)  FAILED"
echo "════════════════════════════════════════"

if ! $FRONTEND_OK || ! $JAVA_OK || ! $SIDECAR_OK; then
  echo ""
  echo "❌  Deploy FAILED — check: journalctl -u <service-name> -n 50"
  exit 1
fi

echo ""
echo "✅  更新完成"
