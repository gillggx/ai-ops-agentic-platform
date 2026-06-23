#!/bin/bash
# Chat-mode eval run wrapper (W1). Runs the chat orchestrator over a batch of
# operations questions and captures behaviour signals per case. Runs on the EC2
# host (sidecar not publicly exposed).
#
# SECRET: SVC_TOKEN is the sidecar X-Service-Token. NEVER hardcode it.
#
# Usage:
#   export SVC_TOKEN=...            # from python_ai_sidecar/.env
#   bash tools/chat_eval/run.sh [label]
#   python3 tools/chat_eval/grade_chat.py [label]
#
# Env: SIDECAR_BASE (default http://localhost:8050), PYTHON
#      (default /opt/aiops/venv_sidecar/bin/python), RESULTS_DIR (default /tmp).
set -euo pipefail

LABEL="${1:-baseline}"
: "${SVC_TOKEN:?export SVC_TOKEN first (sidecar X-Service-Token, see python_ai_sidecar/.env)}"
SIDECAR_BASE="${SIDECAR_BASE:-http://localhost:8050}"
PYTHON="${PYTHON:-/opt/aiops/venv_sidecar/bin/python}"
RESULTS_DIR="${RESULTS_DIR:-/tmp}"
HERE="$(cd "$(dirname "$0")" && pwd)"

OUT_FILE="$RESULTS_DIR/chat_eval_${LABEL}.json"
SVC_TOKEN="$SVC_TOKEN" SIDECAR_BASE="$SIDECAR_BASE" OUT_FILE="$OUT_FILE" \
  "$PYTHON" "$HERE/chat_driver.py" | tee "$RESULTS_DIR/chat_eval_${LABEL}.log"
echo "results -> $OUT_FILE"
