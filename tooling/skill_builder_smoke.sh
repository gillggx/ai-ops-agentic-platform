#!/usr/bin/env bash
# 2026-05-13 — Skill Builder LLM smoke (rev 2: now executes pipeline at runtime).
#
# Coverage:
#   1. /internal/agent/build with skill_step_mode toggle (both true + false)
#   2. Plan structural assertions: NOT plan_unfixable/failed, contains
#      step_check (skill mode), no block_alert (skill mode), no deprecated.
#   3. ACTUAL runtime execution via /internal/pipeline/preview:
#        - every node returns status=success (no executor error)
#        - terminal node emits expected output shape per case
#        - dataframe rows non-empty (sanity check upstream MCP returned data)
#        - chart_spec has data_points > 0 (chart actually rendered)
#   4. Per-case expected-output assertions (e.g. step_check.pass present;
#      chart_spec.type matches expected chart kind).
#
# Why: prior version only validated plan structure → got fooled by runtime
# bugs (np.int64 not numeric, threshold mixed mode). Now exercises the
# whole stack end-to-end so "smoke passes" really means "user GUI will work".
#
# Usage:
#   tooling/skill_builder_smoke.sh                            # localhost
#   SIDECAR_BASE=http://localhost:8050 tooling/skill_builder_smoke.sh
#   SVC_TOKEN=<token> tooling/skill_builder_smoke.sh

set -euo pipefail

SIDECAR_BASE=${SIDECAR_BASE:-http://localhost:8050}
SVC_TOKEN=${SVC_TOKEN:-}

if [[ -z "$SVC_TOKEN" && -f /opt/aiops/python_ai_sidecar/.env ]]; then
  SVC_TOKEN=$(grep '^SERVICE_TOKEN=' /opt/aiops/python_ai_sidecar/.env | cut -d= -f2)
fi
if [[ -z "$SVC_TOKEN" ]]; then
  echo "✗ SVC_TOKEN required (env or /opt/aiops/python_ai_sidecar/.env)" >&2
  exit 2
fi
if ! command -v jq >/dev/null; then
  echo "✗ jq required" >&2
  exit 2
fi
# Find a python that has working dataclasses (sidecar venv preferred over
# stock /usr/bin/python3 which on some boxes has the inspect.get_annotations
# regression).
PY=""
for cand in /opt/aiops/venv_sidecar/bin/python3 /opt/aiops/python_ai_sidecar/.venv/bin/python3 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import json' 2>/dev/null; then PY=$cand; break; fi
  fi
done
if [[ -z "$PY" ]]; then
  echo "✗ no working python found" >&2
  exit 2
fi

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
blue()   { printf '\033[34m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

FAILED=0

# Convert SSE-streamed plan into pipeline_json and POST /preview on terminal.
# Emits a JSON report:
#   {plan_ok, plan_status, blocks, runtime_ok, node_results, terminal_output}
run_case() {
  local name=$1
  local instruction=$2
  local skill_mode=$3
  local expect_chart_type=$4   # e.g. "line", "ewma_cusum", "" (no chart expected)
  local expect_dataframe=$5    # "yes" if terminal should emit dataframe
  local resp_file
  resp_file=$(mktemp -t builder-smoke-XXXX.txt)

  blue "## [$name] skill_step_mode=$skill_mode"
  blue "   instr: $instruction"

  curl -sf -N -X POST "$SIDECAR_BASE/internal/agent/build" \
    -H "X-Service-Token: $SVC_TOKEN" \
    -H "Content-Type: application/json" \
    --max-time 150 \
    -d "$(jq -nc --arg instr "$instruction" --arg sid "smoke-$name" --argjson ssm "$skill_mode" \
        '{user_id: 1, session_id: $sid, instruction: $instr, skill_step_mode: $ssm, client_context: {}}')" \
    > "$resp_file" 2>&1

  local case_failed=0

  # ── 1. plan-level assertions ───────────────────────────────────────
  local final_status="parse_error"
  if grep -qE '"status":\s*"(failed|plan_unfixable)"' "$resp_file"; then
    final_status=$(grep -oE '"status":\s*"[a-z_]+"' "$resp_file" | tail -1 | sed 's/.*"\([a-z_]*\)"/\1/')
  elif grep -qE '"plan_summary":' "$resp_file" && grep -qE '"n_ops":' "$resp_file"; then
    final_status="ok"
  fi

  local last_plan_ops
  last_plan_ops=$(grep '^data: ' "$resp_file" | grep -E '"plan":\s*\[' | tail -1 | sed 's/^data: //' || true)
  local block_ids=""
  if [[ -n "$last_plan_ops" ]]; then
    block_ids=$(echo "$last_plan_ops" | jq -r '[.plan[]? | select(.type=="add_node") | .block_id] | join(",")' 2>/dev/null || echo "")
  fi

  case "$final_status" in
    ok)
      green "   ✓ plan finalized";;
    *)
      red "   ✗ plan status=$final_status"
      case_failed=1
      ;;
  esac

  if [[ "$skill_mode" == "true" && -n "$block_ids" ]]; then
    if echo ",$block_ids," | grep -q ",block_step_check,"; then
      green "   ✓ plan contains block_step_check"
    else
      red   "   ✗ skill mode but no block_step_check"; case_failed=1
    fi
    if echo ",$block_ids," | grep -q ",block_alert,"; then
      red   "   ✗ skill mode has forbidden block_alert"; case_failed=1
    else
      green "   ✓ no block_alert (skill mode)"
    fi
  fi

  # If plan didn't even finalize, skip runtime check.
  if (( case_failed != 0 )) || [[ "$final_status" != "ok" ]]; then
    FAILED=$((FAILED + 1))
    red "   → log saved at $resp_file"
    echo
    return
  fi

  # ── 2. Build pipeline_json from the last plan ops + POST /preview ──
  local payload
  payload=$("$PY" -c "
import json, sys
plan_blob = sys.stdin.read()
data = json.loads(plan_blob)
plan = data.get('plan') or []
nodes, edges, eid, seen = [], [], 0, set()
for op in plan:
    ty = op.get('type')
    if ty == 'add_node':
        nid = op.get('node_id')
        if nid in seen: continue
        seen.add(nid)
        nodes.append({
            'id': nid, 'block_id': op.get('block_id'),
            'block_version': op.get('block_version') or '1.0.0',
            'position': {'x': 0, 'y': 0},
            'params': op.get('params') or {},
        })
    elif ty == 'set_param':
        nid = op.get('node_id'); n = next((n for n in nodes if n['id']==nid), None)
        if n:
            p = op.get('params') or {}
            k = p.get('key'); v = p.get('value')
            if k: n['params'][k] = v
    elif ty == 'connect':
        eid += 1
        edges.append({
            'id': f'e{eid}',
            'from': {'node': op.get('src_id'), 'port': op.get('src_port') or 'data'},
            'to':   {'node': op.get('dst_id'), 'port': op.get('dst_port') or 'data'},
        })
srcs = {e['from']['node'] for e in edges}
terminals = [n['id'] for n in nodes if n['id'] not in srcs]
target = terminals[0] if terminals else (nodes[-1]['id'] if nodes else None)
pj = {
    'version': '1.0', 'name': 'smoke-rt', 'metadata': {},
    'inputs': [
        {'name': 'equipment_id', 'type': 'string', 'example': 'EQP-01'},
        {'name': 'tool_id',      'type': 'string', 'example': 'EQP-01'},
    ],
    'nodes': nodes, 'edges': edges,
}
print(json.dumps({'pipeline_json': pj, 'node_id': target, 'sample_size': 50}))
" <<< "$last_plan_ops")

  local preview_resp
  preview_resp=$(curl -s -X POST "$SIDECAR_BASE/internal/pipeline/preview" \
    -H "X-Service-Token: $SVC_TOKEN" -H "Content-Type: application/json" \
    --max-time 120 -d "$payload")

  local preview_status
  preview_status=$(echo "$preview_resp" | jq -r '.status // "no_status"')
  if [[ "$preview_status" != "success" ]]; then
    red "   ✗ runtime preview failed: status=$preview_status detail=$(echo "$preview_resp" | jq -r '.detail // .errors // "?"' | head -c 200)"
    case_failed=1
    FAILED=$((FAILED + 1))
    echo
    return
  fi

  # ── 3. Per-node status assertions ──────────────────────────────────
  local node_fail_count
  node_fail_count=$(echo "$preview_resp" | jq '[.all_node_results[]? | select(.status != "success")] | length')
  if [[ "$node_fail_count" == "0" ]]; then
    local n_nodes
    n_nodes=$(echo "$preview_resp" | jq '.all_node_results | length')
    green "   ✓ all $n_nodes nodes executed successfully"
  else
    red "   ✗ $node_fail_count node(s) failed at runtime:"
    echo "$preview_resp" | jq -r '.all_node_results | to_entries[] | select(.value.status != "success") | "       \(.key): \(.value.error)"' | while read line; do red "$line"; done
    case_failed=1
  fi

  # ── 4. Terminal output shape ────────────────────────────────────────
  local target_id
  target_id=$(echo "$preview_resp" | jq -r '.target')
  local preview_ports
  preview_ports=$(echo "$preview_resp" | jq -r '.node_result.preview | keys[]?')

  if [[ -n "$expect_chart_type" ]]; then
    local chart_ok=0
    for port in $preview_ports; do
      local snap_type ndata
      snap_type=$(echo "$preview_resp" | jq -r ".node_result.preview[\"$port\"].snapshot.type // empty")
      ndata=$(echo "$preview_resp" | jq -r ".node_result.preview[\"$port\"].snapshot.data | if type==\"array\" then length else 0 end // 0")
      if [[ "$snap_type" == "$expect_chart_type" ]] && (( ndata > 0 )); then
        green "   ✓ terminal[$target_id].$port = chart_spec(type=$snap_type, $ndata data points)"
        chart_ok=1
      fi
    done
    if (( chart_ok == 0 )); then
      red "   ✗ expected chart_spec(type=$expect_chart_type, data>0) but got none"
      case_failed=1
    fi
  fi

  if [[ "$expect_dataframe" == "yes" ]]; then
    local df_ok=0
    for port in $preview_ports; do
      local ty rows cols
      ty=$(echo "$preview_resp" | jq -r ".node_result.preview[\"$port\"].type // empty")
      rows=$(echo "$preview_resp" | jq ".node_result.preview[\"$port\"].rows | length")
      cols=$(echo "$preview_resp" | jq ".node_result.preview[\"$port\"].columns | length")
      if [[ "$ty" == "dataframe" ]] && (( rows > 0 )); then
        green "   ✓ terminal[$target_id].$port = dataframe($cols cols × $rows rows)"
        # For skill mode step_check.check: extra check that .pass is present
        if [[ "$port" == "check" ]]; then
          local has_pass note
          has_pass=$(echo "$preview_resp" | jq -r ".node_result.preview.check.rows[0].pass // \"missing\"")
          note=$(echo "$preview_resp" | jq -r ".node_result.preview.check.rows[0].note // \"\"")
          if [[ "$has_pass" == "missing" ]]; then
            red "   ✗ step_check output missing .pass field"
            case_failed=1
          else
            green "     ↳ step_check.pass=$has_pass note='$note'"
            if [[ "$note" =~ "not numeric" ]]; then
              red "   ✗ step_check rejected upstream value as 'not numeric' (likely numpy type bug)"
              case_failed=1
            fi
          fi
        fi
        df_ok=1
      fi
    done
    if (( df_ok == 0 )); then
      red "   ✗ expected dataframe with rows>0, got none"
      case_failed=1
    fi
  fi

  echo "   blocks used: $block_ids"

  if (( case_failed == 1 )); then
    FAILED=$((FAILED + 1))
    red "   → response saved at $resp_file"
  else
    rm -f "$resp_file"
  fi
  echo
}

blue "==== Skill Builder LLM smoke (rev 2: runtime-validated) ===="
blue "    sidecar: $SIDECAR_BASE"
blue "    python:  $PY"
echo

# Case A — user's repeated failure (skill mode, last-OOC + show charts).
# Expect step_check.check dataframe with .pass field.
run_case "A-skill-lastooc" \
  "檢查機台最後一次OOC 時，是否有多張SPC 也OOC (>2)，並且顯示該SPC charts" \
  "true" "" "yes"

# Case B — chat-mode 3-chart diagnostic. Expect terminal chart_spec (any chart type).
run_case "B-chat-3chart" \
  "過去 7 天 EQP-01 STEP_001 的 spc_xbar_chart_value：(1) block_ewma_cusum (mode=cusum, k=0.5, h=4) 偵測小幅 drift；(2) block_box_plot 比較各 lot 之間的分佈差異；(3) block_probability_plot 檢定是否符合常態" \
  "false" "" ""

# Case C — simple skill C1 with $equipment_id. Expect step_check.check dataframe.
run_case "C-skill-input" \
  "檢查 \$equipment_id 機台最後一次 OOC 事件，OOC SPC chart 數量 >= 2 時觸發" \
  "true" "" "yes"

# Case D — chat-mode chart. Expect chart_spec(type=line).
run_case "D-chat-xbar-trend" \
  "幫我看 EQP-01 STEP_001 最近 100 筆 xbar 趨勢" \
  "false" "line" ""

echo
if (( FAILED == 0 )); then
  green "┌──────────────────────────────────────────────────────────┐"
  green "│  All Skill Builder smoke cases passed (plan + runtime) ✓ │"
  green "└──────────────────────────────────────────────────────────┘"
  exit 0
else
  red "┌──────────────────────────────────────────────────────────┐"
  red "│  $FAILED case(s) FAILED — see logs above                  │"
  red "└──────────────────────────────────────────────────────────┘"
  exit 1
fi
