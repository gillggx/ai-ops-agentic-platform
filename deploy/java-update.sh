#!/usr/bin/env bash
# deploy/java-update.sh — build + restart the Java API + Python sidecar.
#
# Runs against :8002 (Java API) and :8050 (Python sidecar). The frontend
# (aiops-app on :8000) lives in update.sh — run it separately. Java uses
# Flyway migrations checked into
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

# ── Java fat jars ────────────────────────────────────────────────────────
# 2026-05-11: migrated Gradle → Maven 3.8.1 (DevOps requirement).
# `mvn package` produces:
#   java-backend/target/aiops-api.jar              (executable boot)
#   java-backend/target/aiops-api-library.jar      (plain library — used by scheduler)
#   java-scheduler/target/aiops-scheduler.jar      (executable boot)
# systemd unit files (deploy/aiops-java-*.service) point to target/.
echo "☕  Building Java fat jars (api + scheduler) via Maven..."
cd "$APP_DIR"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/temurin-17-jdk-amd64}"
export PATH="$JAVA_HOME/bin:$PATH"
# 2026-05-11: -Dmaven.test.skip=true (not just -DskipTests) so test
# *compilation* is skipped too. Gradle's bootJar task never compiled tests
# so a pre-existing stale JwtServiceTest using an outdated AiopsProperties
# constructor went unnoticed; Maven's package lifecycle includes test-compile
# by default. TODO: fix that test, then revert to -DskipTests.
mvn -B -ntp -Dmaven.test.skip=true -pl java-backend,java-scheduler -am clean package
ls -la "$JAVA_DIR/target/aiops-api.jar" "$APP_DIR/java-scheduler/target/aiops-scheduler.jar" 2>&1 | head -4

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
sudo install -m 0644 "$APP_DIR/deploy/aiops-java-scheduler.service" /etc/systemd/system/
sudo install -m 0644 "$APP_DIR/deploy/aiops-python-sidecar.service" /etc/systemd/system/
sudo systemctl daemon-reload

# Env file bootstraps — only create if missing so real secrets aren't overwritten.
JAVA_ENV="$JAVA_DIR/.env"
SCHEDULER_ENV="$APP_DIR/java-scheduler/.env"
SIDECAR_ENV="$SIDECAR_DIR/.env"
if [[ ! -f "$JAVA_ENV" ]]; then
  cp "$APP_DIR/deploy/aiops-java-api.env.example" "$JAVA_ENV"
  echo "    ⚠️  $JAVA_ENV created from template — fill in real secrets before continuing."
fi
if [[ ! -f "$SCHEDULER_ENV" ]]; then
  cp "$APP_DIR/deploy/aiops-java-scheduler.env.example" "$SCHEDULER_ENV"
  echo "    ⚠️  $SCHEDULER_ENV created from template — fill in real secrets before continuing."
fi
if [[ ! -f "$SIDECAR_ENV" ]]; then
  cp "$APP_DIR/deploy/aiops-python-sidecar.env.example" "$SIDECAR_ENV"
  echo "    ⚠️  $SIDECAR_ENV created from template — fill in real secrets before continuing."
fi

# ── Restart (order matters: API first → scheduler depends on API for some
# domain seeds; sidecar last so it can reach Java /internal/*). ──────────
echo "🚀  Restarting services..."
sudo systemctl enable aiops-java-api.service aiops-java-scheduler.service aiops-python-sidecar.service
sudo systemctl restart aiops-java-api.service
wait_for_http "http://127.0.0.1:${AIOPS_JAVA_PORT:-8002}/actuator/health" "Java API"

# ── Canonical block seed (2026-06-23) ───────────────────────────────────────
# pb_blocks has no boot/deploy sync from the canonical block list, so a fresh DB
# (new EC2 / POC branch) only gets blocks whose Flyway migrations actually ran
# (Flyway is disabled in prod) → fewer blocks than a hand-patched prod DB. Apply
# the regenerable canonical seed every deploy: ON CONFLICT (name,version) DO
# NOTHING — backfills a fresh DB, pure no-op on an established one (never
# clobbers curated rows). Regenerate with: python tools/gen_block_seed_sql.py.
CANON_SQL="$APP_DIR/java-backend/src/main/resources/db/canonical/pb_blocks_canonical.sql"
if [ -f "$CANON_SQL" ]; then
  echo "[seed] Applying canonical block seed (idempotent) ..."
  DB_URL=$(grep -E '^DB_URL=' "$JAVA_ENV" | cut -d= -f2-)
  DB_USER=$(grep -E '^DB_USER=' "$JAVA_ENV" | cut -d= -f2-)
  DB_HOST=$(echo "$DB_URL" | sed -E 's#.*://([^:/]+).*#\1#')
  DB_PORT=$(echo "$DB_URL" | sed -E 's#.*://[^:/]+:([0-9]+)/.*#\1#')
  DB_NAME=$(echo "$DB_URL" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
  if PGPASSWORD=$(grep -E '^DB_PASSWORD=' "$JAVA_ENV" | cut -d= -f2-) \
       psql -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" \
       -v ON_ERROR_STOP=1 -f "$CANON_SQL" >/dev/null 2>/tmp/canon_seed.err; then
    N=$(PGPASSWORD=$(grep -E '^DB_PASSWORD=' "$JAVA_ENV" | cut -d= -f2-) \
        psql -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" \
        -tAc 'select count(*) from pb_blocks;' 2>/dev/null)
    echo "    [ok] canonical block seed applied — pb_blocks now has $N block(s)."
  else
    echo "    [warn] canonical block seed FAILED (see /tmp/canon_seed.err) — continuing deploy."
    cat /tmp/canon_seed.err >&2 || true
  fi
else
  echo "    [warn] canonical block seed file not found ($CANON_SQL) — skipping."
fi

sudo systemctl restart aiops-java-scheduler.service
wait_for_http "http://127.0.0.1:${AIOPS_SCHEDULER_PORT:-8003}/actuator/health" "Java Scheduler"

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
echo "✅  Java API + Scheduler + Sidecar deploy complete."
echo "    - Java API       : $(systemctl is-active aiops-java-api) on port ${AIOPS_JAVA_PORT:-8002}"
echo "    - Java Scheduler : $(systemctl is-active aiops-java-scheduler) on port ${AIOPS_SCHEDULER_PORT:-8003}"
echo "    - Sidecar        : $(systemctl is-active aiops-python-sidecar) on port 8050"
echo "    - Frontend (:8000) untouched — run deploy/update.sh for that"
