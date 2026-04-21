#!/usr/bin/env bash
# deploy/java-rollback.sh — stop Java + Python sidecar, leave old Python running.
#
# Safe to run any time — it only stops the *new* services and makes sure the
# *old* fastapi-backend is still serving. The cutover to Java itself is a
# Frontend env-var flip (not done here), so rollback means:
#   1. Flip FASTAPI_BASE_URL back to :8001 in aiops-app/.env.local
#   2. systemctl restart aiops-app
#   3. Run this script to stop the Java services
#
# Usage:
#     cd /opt/aiops
#     bash deploy/java-rollback.sh
set -euo pipefail

echo "🛑  Stopping Java API + Python sidecar..."
sudo systemctl stop aiops-python-sidecar.service || true
sudo systemctl stop aiops-java-api.service || true

echo "🔍  Verifying old Python fastapi-backend is still up..."
if systemctl is-active --quiet fastapi-backend.service; then
  echo "    ✅  fastapi-backend.service active"
else
  echo "    ⚠️  fastapi-backend.service NOT active — starting it now"
  sudo systemctl start fastapi-backend.service
fi

if curl -sf --max-time 5 http://127.0.0.1:8001/health -o /dev/null; then
  echo "    ✅  :8001 responding"
else
  echo "    ❌  :8001 NOT responding — investigate manually"
  exit 1
fi

echo ""
echo "✅  Rollback complete."
echo "    - aiops-java-api       : $(systemctl is-active aiops-java-api 2>/dev/null || echo stopped)"
echo "    - aiops-python-sidecar : $(systemctl is-active aiops-python-sidecar 2>/dev/null || echo stopped)"
echo "    - fastapi-backend      : $(systemctl is-active fastapi-backend)"
echo ""
echo "Don't forget to restore FASTAPI_BASE_URL=http://localhost:8001 in"
echo "aiops-app/.env.local and restart aiops-app if you had flipped it."
