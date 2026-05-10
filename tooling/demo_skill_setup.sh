#!/usr/bin/env bash
# Phase 11 v6 — clean up all test artifacts + build ONE demo skill with
# C1 + 1 checklist step, both backed by hand-crafted clean pipelines.
# Survivor for user inspection at /skills.

set -euo pipefail

JAVA_BASE=${JAVA_BASE:-http://localhost:8002}
PG_DSN=${PG_DSN:--h localhost -U aiops -d aiops_db}
PG_PASSWORD=${PG_PASSWORD:-}
USERNAME=${USERNAME:-itadmin_test}
PASSWORD=${PASSWORD:-ITAdmin@2026}
DEMO_SLUG=${DEMO_SLUG:-demo-ocap-5in3out}

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
AH="Authorization: Bearer $TOKEN"
green "  ✓ token acquired"

# ── 2. Wipe test artifacts ──────────────────────────────────────────
blue "[2/6] wipe all e2e-* and real-* test skills"
TEST_SLUGS=$(psql $PG_DSN -tAc "
  SELECT slug FROM skill_documents
   WHERE slug LIKE 'e2e-%' OR slug LIKE 'real-%' OR slug LIKE 'smoke-%'
   ORDER BY id;
")
COUNT=$(echo "$TEST_SLUGS" | grep -c . || true)
if [[ "$COUNT" -gt 0 ]]; then
  while IFS= read -r slug; do
    [[ -z "$slug" ]] && continue
    curl -sf -X DELETE "$JAVA_BASE/api/v1/skill-documents/$slug" -H "$AH" >/dev/null \
      && echo "    - deleted $slug" || echo "    - FAIL $slug"
  done <<< "$TEST_SLUGS"
fi
green "  ✓ $COUNT test skills wiped"

# Also wipe the legacy ooc-tool-5in3out-check (V27 left it with null pipeline_id;
# we replace it with a fresh demo).
blue "    legacy 'ooc-tool-5in3out-check' skill"
curl -sf -X DELETE "$JAVA_BASE/api/v1/skill-documents/ooc-tool-5in3out-check" -H "$AH" >/dev/null 2>&1 \
  && green "    ✓ deleted" || echo "    (not present)"

# ── 3. Hand-craft TWO clean pipelines ──────────────────────────────
blue "[3/6] insert clean pipelines"

# Pipeline A — C1 confirm: "Has there been ≥ 1 OOC in last 1h?"
# Threshold is permissive so the gate usually PASSES → checklist proceeds.
PIPE_C1='{
  "version":"1.0","name":"DEMO — C1 confirm (≥1 OOC in 1h)","metadata":{},
  "inputs":[{"name":"tool_id","type":"string","required":true,"description":""}],
  "nodes":[
    {"id":"n1","block_id":"block_process_history","block_version":"1.0.0",
     "position":{"x":40,"y":80},
     "params":{"tool_id":"$tool_id","object_name":"SPC","time_range":"1h","limit":200}},
    {"id":"n2","block_id":"block_filter","block_version":"1.0.0",
     "position":{"x":260,"y":80},
     "params":{"column":"spc_status","operator":"==","value":"OOC"}},
    {"id":"n3","block_id":"block_count_rows","block_version":"1.0.0","position":{"x":480,"y":80},"params":{}},
    {"id":"n4","block_id":"block_step_check","block_version":"1.0.0",
     "position":{"x":700,"y":80},
     "params":{"operator":">=","threshold":1,"aggregate":"count",
               "note":"近 1h OOC ≥ 1 才繼續"}}
  ],
  "edges":[
    {"id":"e1","from":{"node":"n1","port":"data"},"to":{"node":"n2","port":"data"}},
    {"id":"e2","from":{"node":"n2","port":"data"},"to":{"node":"n3","port":"data"}},
    {"id":"e3","from":{"node":"n3","port":"data"},"to":{"node":"n4","port":"data"}}
  ]
}'

# Pipeline B — Step 01 check: "Is the OOC volume in last 24h abnormally high (≥ 5)?"
# This tells us whether the alarm is a one-off vs a chronic issue.
PIPE_S1='{
  "version":"1.0","name":"DEMO — step 01 (24h OOC ≥ 5 abnormal)","metadata":{},
  "inputs":[{"name":"tool_id","type":"string","required":true,"description":""}],
  "nodes":[
    {"id":"n1","block_id":"block_process_history","block_version":"1.0.0",
     "position":{"x":40,"y":80},
     "params":{"tool_id":"$tool_id","object_name":"SPC","time_range":"24h","limit":500}},
    {"id":"n2","block_id":"block_filter","block_version":"1.0.0",
     "position":{"x":260,"y":80},
     "params":{"column":"spc_status","operator":"==","value":"OOC"}},
    {"id":"n3","block_id":"block_count_rows","block_version":"1.0.0","position":{"x":480,"y":80},"params":{}},
    {"id":"n4","block_id":"block_step_check","block_version":"1.0.0",
     "position":{"x":700,"y":80},
     "params":{"operator":">=","threshold":5,"aggregate":"count",
               "note":"24h OOC count ≥ 5 = chronic issue"}}
  ],
  "edges":[
    {"id":"e1","from":{"node":"n1","port":"data"},"to":{"node":"n2","port":"data"}},
    {"id":"e2","from":{"node":"n2","port":"data"},"to":{"node":"n3","port":"data"}},
    {"id":"e3","from":{"node":"n3","port":"data"},"to":{"node":"n4","port":"data"}}
  ]
}'

PID_C1=$(psql $PG_DSN -tAc "
  INSERT INTO pb_pipelines (name, description, status, version, pipeline_json)
  VALUES ('DEMO — C1 confirm (≥1 OOC in 1h)', '5-in-3-out demo', 'draft', '1.0.0', \$X\$$PIPE_C1\$X\$)
  RETURNING id;" | sed -n '1p' | tr -d ' \r\n')
PID_S1=$(psql $PG_DSN -tAc "
  INSERT INTO pb_pipelines (name, description, status, version, pipeline_json)
  VALUES ('DEMO — step 01 (24h OOC ≥ 5)', '5-in-3-out demo', 'draft', '1.0.0', \$X\$$PIPE_S1\$X\$)
  RETURNING id;" | sed -n '1p' | tr -d ' \r\n')

green "  ✓ pipelines created: confirm=#$PID_C1, step=#$PID_S1"

# ── 4. Create demo skill ────────────────────────────────────────────
blue "[4/6] create demo skill $DEMO_SLUG"
TRIG='{"type":"event","event":"OOC","target":{"kind":"all","ids":[]}}'
# Wire is SNAKE_CASE (Jackson config on aiops-java-api) — must use
# trigger_config / not triggerConfig. Camel keys silently drop to {}.
SKILL=$(curl -sf -X POST "$JAVA_BASE/api/v1/skill-documents" \
  -H "$AH" -H "Content-Type: application/json" \
  -d "$(jq -n --arg slug "$DEMO_SLUG" --arg trig "$TRIG" \
        '{slug:$slug, title:"DEMO — OCAP 5-in-3-out check (hand-crafted)", stage:"patrol", domain:"ETCH", description:"當機台被 SPC 系統判為 OCAP 觸發時，先用 1h OOC ≥ 1 確認異常存在；接著查 24h 是否有 chronic 多次 OOC 事件。", trigger_config:$trig}')")
SKILL_ID=$(echo "$SKILL" | jq -r .data.id)
green "  ✓ skill #$SKILL_ID at /skills/$DEMO_SLUG"

# ── 5. Bind both pipelines via /bind-pipeline ──────────────────────
blue "[5/6] bind C1 + step 01"

curl -sf -X POST "$JAVA_BASE/api/v1/skill-documents/$DEMO_SLUG/bind-pipeline" \
  -H "$AH" -H "Content-Type: application/json" \
  -d "$(jq -nc --argjson pid "$PID_C1" \
        '{slot:"confirm", pipeline_id:$pid, description:"近 1h 是否真的有 OOC", summary:"先確認機台真的有 OOC 才繼續，避免 false alarm 浪費值班工程師"}')" >/dev/null
green "  ✓ C1 bound (pipeline #$PID_C1)"

curl -sf -X POST "$JAVA_BASE/api/v1/skill-documents/$DEMO_SLUG/bind-pipeline" \
  -H "$AH" -H "Content-Type: application/json" \
  -d "$(jq -nc --argjson pid "$PID_S1" \
        '{slot:"step:NEW", pipeline_id:$pid, description:"檢查機台 24h 內 OOC 是否 ≥ 5（chronic 訊號）", summary:"≥5 = chronic issue → 升級為 PE 工單"}')" >/dev/null
green "  ✓ step 01 bound (pipeline #$PID_S1)"

# ── 6. Smoke run to confirm 跑得動 ──────────────────────────────────
blue "[6/6] /run smoke (EQP-01 trigger payload)"
RUN=$(curl -sN -X POST "$JAVA_BASE/api/v1/skill-documents/$DEMO_SLUG/run" \
  -H "$AH" -H "Content-Type: application/json" -H "Accept: text/event-stream" \
  -d '{"trigger_payload":{"tool_id":"EQP-01","lot_id":"LOT-0001","step":"STEP_005","chamber_id":"CH-1","spc_chart":"xbar_chart","severity":"high"},"is_test":true}')

echo "$RUN" | python3 -c "
import sys, json
text = sys.stdin.read()
print()
for f in text.split('\n\n'):
    f = f.strip()
    if not f: continue
    evt = ''
    data = ''
    for line in f.split('\n'):
        if line.startswith('event:'): evt = line[6:].strip()
        elif line.startswith('data:'): data = line[5:].strip()
    if evt in ('confirm_done', 'step_done', 'done'):
        try:
            d = json.loads(data)
            if evt == 'confirm_done':
                print(f'  C1 confirm:  status={d.get(\"status\")}, value={d.get(\"value\")}, note={d.get(\"note\")}')
            elif evt == 'step_done':
                print(f'  Step 01:     status={d.get(\"status\")}, value={d.get(\"value\")}, note={d.get(\"note\")}')
            elif evt == 'done':
                print(f'  Run done:    {len(d.get(\"step_results\", []))} step results, run_id={d.get(\"run_id\")}')
        except Exception as e:
            print(f'  {evt}: parse failed ({e})')
"

echo
green "┌─────────────────────────────────────────────────────┐"
green "│  Demo skill ready at: /skills/$DEMO_SLUG"
green "│  Open in browser to inspect Author + Execute mode    │"
green "└─────────────────────────────────────────────────────┘"
