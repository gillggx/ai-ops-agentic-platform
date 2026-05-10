#!/usr/bin/env bash
# Phase 11 v6 — REAL skill end-to-end: build a hand-crafted clean
# pipeline (deterministic, no LLM), bind it to a skill, run it against
# the simulator, verify SkillRunner reads pass/fail correctly.
#
# This is the 「跑得動才算成功」 verification — the agent's pipeline-
# generation quality is a separate concern; this validates the runner +
# bind + step_check loop works for any clean pipeline.

set -euo pipefail

JAVA_BASE=${JAVA_BASE:-http://localhost:8002}
PG_DSN=${PG_DSN:--h localhost -U aiops -d aiops_db}
PG_PASSWORD=${PG_PASSWORD:-}
USERNAME=${USERNAME:-itadmin_test}
PASSWORD=${PASSWORD:-ITAdmin@2026}
SLUG=real-$(date +%s)

if [[ -z "$PG_PASSWORD" && -f /opt/aiops/java-backend/.env ]]; then
  PG_PASSWORD=$(grep '^DB_PASSWORD=' /opt/aiops/java-backend/.env | cut -d= -f2)
fi
export PGPASSWORD=$PG_PASSWORD

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue() { printf '\033[34m%s\033[0m\n' "$*"; }

# ── 1. Login ────────────────────────────────────────────────────────
blue "[1/6] login"
LOGIN=$(curl -sf -X POST "$JAVA_BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")
TOKEN=$(echo "$LOGIN" | jq -r .data.access_token)
[[ -n "$TOKEN" && "$TOKEN" != "null" ]] || { red "login failed"; exit 1; }
green "  ✓ token acquired"
AH="Authorization: Bearer $TOKEN"

# ── 2. Create skill ─────────────────────────────────────────────────
blue "[2/6] create skill $SLUG"
SKILL=$(curl -sf -X POST "$JAVA_BASE/api/v1/skill-documents" \
  -H "$AH" -H "Content-Type: application/json" \
  -d "{\"slug\":\"$SLUG\",\"title\":\"REAL — recent 5 lots OOC ≥ 3\",\"stage\":\"patrol\",\"triggerConfig\":\"{\\\"type\\\":\\\"event\\\",\\\"event\\\":\\\"OOC\\\",\\\"target\\\":{\\\"kind\\\":\\\"all\\\",\\\"ids\\\":[]}}\"}")
SKILL_ID=$(echo "$SKILL" | jq -r .data.id)
green "  ✓ skill #$SKILL_ID"

# ── 3. Insert hand-crafted clean pipeline ───────────────────────────
# 4-block chain: process_history → filter(spc_status=OOC) → count_rows
# → step_check (≥3 = pass means we want to FAIL the gate, hence "is_real")
# Inputs: tool_id (from event payload). Run will fetch SPC snapshots
# from EQP-01 last 24h, count OOC ones, check >= 3.
blue "[3/6] insert clean pipeline"
PIPE_JSON='{
  "version": "1.0",
  "name": "REAL clean OOC counter",
  "metadata": {},
  "inputs": [{"name": "tool_id", "type": "string", "required": true, "description": ""}],
  "nodes": [
    {"id": "n1", "block_id": "block_process_history", "block_version": "1.0.0",
     "position": {"x": 40, "y": 80},
     "params": {"tool_id": "$tool_id", "object_name": "SPC", "time_range": "24h", "limit": 200}},
    {"id": "n2", "block_id": "block_filter", "block_version": "1.0.0",
     "position": {"x": 260, "y": 80},
     "params": {"column": "spc_status", "operator": "==", "value": "OOC"}},
    {"id": "n3", "block_id": "block_count_rows", "block_version": "1.0.0",
     "position": {"x": 480, "y": 80}, "params": {}},
    {"id": "n4", "block_id": "block_step_check", "block_version": "1.0.0",
     "position": {"x": 700, "y": 80},
     "params": {"operator": ">=", "threshold": 3, "aggregate": "count",
                "note": "REAL: 24h OOC count >= 3"}}
  ],
  "edges": [
    {"id": "e1", "from": {"node": "n1", "port": "data"}, "to": {"node": "n2", "port": "data"}},
    {"id": "e2", "from": {"node": "n2", "port": "data"}, "to": {"node": "n3", "port": "data"}},
    {"id": "e3", "from": {"node": "n3", "port": "data"}, "to": {"node": "n4", "port": "data"}}
  ]
}'
PSQL_OUT=$(psql $PG_DSN -tAc "
  INSERT INTO pb_pipelines (name, description, status, version, pipeline_json)
  VALUES ('REAL clean OOC counter', 'hand-crafted', 'draft', '1.0.0', \$PJ\$$PIPE_JSON\$PJ\$)
  RETURNING id;")
PID=$(printf '%s\n' "$PSQL_OUT" | sed -n '1p' | tr -d ' \r\n')
[[ "$PID" =~ ^[0-9]+$ ]] || { red "INSERT failed: $PSQL_OUT"; exit 1; }
green "  ✓ pipeline #$PID"

# ── 4. Bind to confirm slot ─────────────────────────────────────────
blue "[4/6] bind pipeline #$PID to confirm slot"
BIND=$(curl -sf -X POST "$JAVA_BASE/api/v1/skill-documents/$SLUG/bind-pipeline" \
  -H "$AH" -H "Content-Type: application/json" \
  -d "{\"slot\":\"confirm\",\"pipeline_id\":$PID,\"description\":\"24h OOC count >= 3\",\"summary\":\"REAL\"}")
echo "$BIND" | jq -r '.data.confirm_check' >/dev/null \
  && green "  ✓ confirm_check stamped"

# ── 5. Run the skill via /run SSE ───────────────────────────────────
blue "[5/6] /run with EQP-01 trigger payload"
RUN=$(curl -sN -X POST "$JAVA_BASE/api/v1/skill-documents/$SLUG/run" \
  -H "$AH" -H "Content-Type: application/json" -H "Accept: text/event-stream" \
  -d '{"trigger_payload":{"tool_id":"EQP-01","lot_id":"LOT-0001","step":"STEP_005","chamber_id":"CH-1","spc_chart":"xbar_chart","severity":"high"},"is_test":true}')

# Parse SSE: find data line that follows 'event:confirm_done'.
# Use python for robust SSE frame extraction (awk RS doesn't work well here).
echo "  raw confirm_done frame:"
echo "$RUN" | python3 -c "
import sys
text = sys.stdin.read()
frames = text.split('\n\n')
for f in frames:
    if 'event:confirm_done' in f:
        print('   ', f.replace('\n', ' | '))
        break
"
DATA_LINE=$(echo "$RUN" | python3 -c "
import sys
text = sys.stdin.read()
frames = text.split('\n\n')
for f in frames:
    if 'event:confirm_done' in f:
        for line in f.split('\n'):
            if line.startswith('data:'):
                print(line[5:].strip())
        break
")
CONFIRM_STATUS=$(echo "$DATA_LINE" | jq -r .status 2>/dev/null || echo "?")
CONFIRM_VALUE=$(echo "$DATA_LINE" | jq -r .value 2>/dev/null || echo "?")
CONFIRM_NOTE=$(echo "$DATA_LINE" | jq -r .note 2>/dev/null || echo "?")
echo
green "  ✓ confirm step ran"
echo "  status=$CONFIRM_STATUS  value=$CONFIRM_VALUE  note=$CONFIRM_NOTE"

if [[ "$CONFIRM_VALUE" == "error" ]]; then
  red "  ✗ pipeline errored — not 跑的動"
  echo "  full SSE:"
  echo "$RUN" | sed 's/^/    /'
  exit 1
fi
if [[ "$CONFIRM_STATUS" != "pass" && "$CONFIRM_STATUS" != "fail" ]]; then
  red "  ✗ unexpected status: $CONFIRM_STATUS"
  exit 1
fi
green "  ✓ real pass/fail verdict (跑的動)"

# ── 6. Cleanup (kept by default for inspection) ─────────────────────
if [[ "${SKIP_CLEANUP:-0}" != "1" ]]; then
  blue "[6/6] cleanup skill (set SKIP_CLEANUP=1 to keep)"
  curl -sf -X DELETE "$JAVA_BASE/api/v1/skill-documents/$SLUG" -H "$AH" >/dev/null
  green "  ✓ skill deleted"
else
  blue "[6/6] kept skill $SLUG for inspection"
fi

echo
green "┌─────────────────────────────────────────────────┐"
green "│  REAL skill ran end-to-end ✓ — 跑的動            │"
green "│  status=$CONFIRM_STATUS  value=$CONFIRM_VALUE                       │"
green "└─────────────────────────────────────────────────┘"
