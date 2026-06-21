#!/bin/bash
# SLASH-17 regression run wrapper. Runs all 17 production slash commands through
# the v30 builder e2e (against the LOCAL sidecar) and captures per-case results,
# then a window file the grader uses for round-counting.
#
# SECRET: SVC_TOKEN is the sidecar X-Service-Token. NEVER hardcode it — export it
# in the calling shell (it lives in python_ai_sidecar/.env on the host).
#
# Usage (on the EC2 host, sidecar running on :8050):
#   export SVC_TOKEN=...            # from python_ai_sidecar/.env
#   bash tools/slash17/run.sh <label>
#   python3 tools/slash17/grade_strict.py <label>
#
# Env overrides:
#   SIDECAR_BASE  (default http://localhost:8050)
#   PYTHON        (default /opt/aiops/venv_sidecar/bin/python)
#   RESULTS_DIR   (default /tmp) — where s17_<label>.{json,log,window} land
set -euo pipefail

LABEL="${1:?usage: run.sh <label>}"
: "${SVC_TOKEN:?export SVC_TOKEN first (sidecar X-Service-Token, see python_ai_sidecar/.env)}"
SIDECAR_BASE="${SIDECAR_BASE:-http://localhost:8050}"
PYTHON="${PYTHON:-/opt/aiops/venv_sidecar/bin/python}"
RESULTS_DIR="${RESULTS_DIR:-/tmp}"
HERE="$(cd "$(dirname "$0")" && pwd)"

OUT_FILE="$RESULTS_DIR/s17_${LABEL}.json"
T0=$(date +%s)
SVC_TOKEN="$SVC_TOKEN" SIDECAR_BASE="$SIDECAR_BASE" OUT_FILE="$OUT_FILE" \
  "$PYTHON" "$HERE/slash17_driver.py" > "$RESULTS_DIR/s17_${LABEL}.log" 2>&1
T1=$(date +%s)

echo "$T0 $T1" > "$RESULTS_DIR/s17_${LABEL}.window"
echo "DONE_${LABEL} window=$T0..$T1 elapsed=$((T1-T0))s"
