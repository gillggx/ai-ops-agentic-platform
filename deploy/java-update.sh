#!/usr/bin/env bash
# deploy/java-update.sh — build + restart the Java API + Python sidecar.
#
# Runs against :8002 (Java API) and :8050 (Python sidecar). The frontend
# (aiops-app on :8000) and ontology-simulator (:8012) live in update.sh —
# run them separately. Java uses Flyway migrations checked into
# java-backend/src/main/resources/db/migration/ (note: prod sets
# flyway.enabled=false, so V*.sql additions need a manual psql -f after
# `git pull`).
#
# Usage on the EC2 box:
#     cd /opt/aiops
#     bash deploy/java-update.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAVA_DIR="$APP_DIR/java-backend"
SIDECAR_DIR="$APP_DIR/python_ai_sidecar"
SIDECAR_VENV="/opt/aiops/venv_sidecar"

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

echo "🔄  Pulling latest..."
git -C "$APP_DIR" pull --ff-only

# ── Java fat jar ─────────────────────────────────────────────────────────
echo "☕  Building Java fat jar..."
cd "$JAVA_DIR"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/temurin-21-jdk-amd64}"
export PATH="$JAVA_HOME/bin:$PATH"
./gradlew bootJar --no-daemon -q
ls -la "$JAVA_DIR/build/libs/aiops-api.jar"

# ── Python sidecar venv ──────────────────────────────────────────────────
echo "🐍  Syncing sidecar venv..."
if [[ ! -d "$SIDECAR_VENV" ]]; then
  python3 -m venv "$SIDECAR_VENV"
fi
"$SIDECAR_VENV/bin/pip" install -q --upgrade pip
"$SIDECAR_VENV/bin/pip" install -q -r "$SIDECAR_DIR/requirements.txt"

# ── systemd units (idempotent install) ───────────────────────────────────
echo "📌  Installing / refreshing systemd units..."
sudo install -m 0644 "$APP_DIR/deploy/aiops-java-api.service"        /etc/systemd/system/
sudo install -m 0644 "$APP_DIR/deploy/aiops-python-sidecar.service" /etc/systemd/system/
sudo systemctl daemon-reload

# Env file bootstraps — only create if missing so real secrets aren't overwritten.
JAVA_ENV="$JAVA_DIR/.env"
SIDECAR_ENV="$SIDECAR_DIR/.env"
if [[ ! -f "$JAVA_ENV" ]]; then
  cp "$APP_DIR/deploy/aiops-java-api.env.example" "$JAVA_ENV"
  echo "    ⚠️  $JAVA_ENV created from template — fill in real secrets before continuing."
fi
if [[ ! -f "$SIDECAR_ENV" ]]; then
  cp "$APP_DIR/deploy/aiops-python-sidecar.env.example" "$SIDECAR_ENV"
  echo "    ⚠️  $SIDECAR_ENV created from template — fill in real secrets before continuing."
fi

# ── Restart (order matters: Java first so sidecar can reach /internal/*) ─
echo "🚀  Restarting services..."
sudo systemctl enable aiops-java-api.service aiops-python-sidecar.service
sudo systemctl restart aiops-java-api.service
wait_for_http "http://127.0.0.1:${AIOPS_JAVA_PORT:-8002}/actuator/health" "Java API"

sudo systemctl restart aiops-python-sidecar.service
wait_for_http "http://127.0.0.1:8050/internal/health" "Python sidecar (will 401 without token — timeout here means service down)" \
  || true  # /internal/health requires token, so HTTP 401 is expected — treat as OK.

# Real readiness probe (with token) — fail the deploy if this doesn't 200.
echo -n "    ⏳  Probing sidecar with service token ..."
SIDECAR_TOKEN=$(grep -E '^SERVICE_TOKEN=' "$SIDECAR_ENV" | cut -d= -f2)
if curl -sf -H "X-Service-Token: $SIDECAR_TOKEN" \
  "http://127.0.0.1:8050/internal/health" -o /dev/null; then
  echo " ✅  UP"
else
  echo " ❌  sidecar reachable but token rejected — check SERVICE_TOKEN match"
  exit 1
fi

echo ""
echo "✅  Java + Sidecar deploy complete."
echo "    - Java API : $(systemctl is-active aiops-java-api) on port ${AIOPS_JAVA_PORT:-8002}"
echo "    - Sidecar  : $(systemctl is-active aiops-python-sidecar) on port 8050"
echo "    - Frontend (:8000) + ontology (:8012) untouched — run deploy/update.sh for those"
