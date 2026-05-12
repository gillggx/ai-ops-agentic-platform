#!/usr/bin/env bash
# 2026-05-13 — Skill Builder LLM smoke (rev 3: artifact-dumping).
#
# What it does:
#   1. POST /internal/agent/build with skill_step_mode toggle
#   2. Parse plan from SSE stream → replay as pipeline_json
#   3. POST /internal/pipeline/preview → execute pipeline for real
#   4. Assert each node ran (status=success); dump key node output details:
#       - dataframe: column count + row count + sample rows
#       - chart_spec: chart type, x/y axis fields, data point count + sample
#       - step_check: pass/value/threshold/note
#   5. Save FULL preview JSON to /tmp/smoke_artifacts/<case>.json per case
#      so I can `cat` it and see exactly what each node emitted.
#
# Why: prior versions said "✓ runs" without showing the data. User asked
# for tooling I can use to self-verify charts and data are CORRECT, not
# just present.
#
# Usage:
#   tooling/skill_builder_smoke.sh                            # localhost
#   tooling/skill_builder_smoke.sh --verbose                  # dump per-node previews inline
#   ARTIFACTS_DIR=/tmp/smk tooling/skill_builder_smoke.sh
#   SIDECAR_BASE=http://localhost:8050 tooling/skill_builder_smoke.sh

set -euo pipefail

VERBOSE=0
for arg in "$@"; do
  case "$arg" in
    --verbose|-v) VERBOSE=1;;
  esac
done

SIDECAR_BASE=${SIDECAR_BASE:-http://localhost:8050}
SVC_TOKEN=${SVC_TOKEN:-}
ARTIFACTS_DIR=${ARTIFACTS_DIR:-/tmp/smoke_artifacts}

if [[ -z "$SVC_TOKEN" && -f /opt/aiops/python_ai_sidecar/.env ]]; then
  SVC_TOKEN=$(grep '^SERVICE_TOKEN=' /opt/aiops/python_ai_sidecar/.env | cut -d= -f2)
fi
if [[ -z "$SVC_TOKEN" ]]; then
  echo "✗ SVC_TOKEN required" >&2; exit 2
fi
if ! command -v jq >/dev/null; then
  echo "✗ jq required" >&2; exit 2
fi
PY=""
for cand in /opt/aiops/venv_sidecar/bin/python3 /opt/aiops/python_ai_sidecar/.venv/bin/python3 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import json' 2>/dev/null; then PY=$cand; break; fi
done
[[ -z "$PY" ]] && { echo "✗ no working python" >&2; exit 2; }

mkdir -p "$ARTIFACTS_DIR"

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
blue()   { printf '\033[34m%s\033[0m\n' "$*"; }
gray()   { printf '\033[90m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

FAILED=0

dump_node_output() {
  local preview_resp=$1
  local node_id=$2
  local block_id=$3

  # Iterate over the node's preview ports
  local ports
  ports=$(echo "$preview_resp" | jq -r ".all_node_results[\"$node_id\"].preview | keys[]?")
  for port in $ports; do
    local entry
    entry=$(echo "$preview_resp" | jq ".all_node_results[\"$node_id\"].preview[\"$port\"]")
    local ty
    ty=$(echo "$entry" | jq -r '.type // empty')
    if [[ "$ty" == "dataframe" ]]; then
      local cols rows total
      cols=$(echo "$entry" | jq -r '.columns | join(", ")')
      rows=$(echo "$entry" | jq '.rows | length')
      total=$(echo "$entry" | jq -r '.total // .rows | length')
      gray "       ├─ $port (dataframe): $rows row(s) of $total total"
      gray "       │   cols: $cols"
      # Special-case block_step_check: show pass/value/threshold/note
      if [[ "$block_id" == "block_step_check" ]]; then
        local pass val thr op agg col note ev
        pass=$(echo "$entry" | jq '.rows[0].pass')
        val=$(echo "$entry" | jq '.rows[0].value')
        thr=$(echo "$entry" | jq '.rows[0].threshold')
        op=$(echo "$entry" | jq -r '.rows[0].operator')
        agg=$(echo "$entry" | jq -r '.rows[0].aggregate')
        col=$(echo "$entry" | jq -r '.rows[0].column')
        note=$(echo "$entry" | jq -r '.rows[0].note')
        ev=$(echo "$entry" | jq '.rows[0].evidence_rows')
        local color=red
        [[ "$pass" == "true" ]] && color=green
        $color "       │   STEP_CHECK: pass=$pass value=$val ${op} threshold=$thr (aggregate=$agg col=$col rows=$ev)"
        gray "       │   note: $note"
      else
        # Show first row content (compact)
        local sample
        sample=$(echo "$entry" | jq -c '.rows[0] // {}' | head -c 280)
        gray "       │   sample row: $sample"
      fi
    else
      local snap_type ndata
      snap_type=$(echo "$entry" | jq -r '.snapshot.type // empty')
      if [[ -n "$snap_type" ]]; then
        ndata=$(echo "$entry" | jq '.snapshot.data | if type=="array" then length else 0 end')
        local x_field y_field title
        x_field=$(echo "$entry" | jq -r '.snapshot.x // .snapshot.x_field // empty')
        y_field=$(echo "$entry" | jq -r '.snapshot.y | if type=="array" then join(",") else . // "" end')
        title=$(echo "$entry" | jq -r '.snapshot.title // ""')
        gray "       ├─ $port (chart_spec): type=$snap_type, $ndata data points"
        [[ -n "$title" ]] && gray "       │   title: $title"
        [[ -n "$x_field" ]] && gray "       │   x=$x_field  y=$y_field"
        # First & last data point
        local first last
        first=$(echo "$entry" | jq -c '.snapshot.data[0] // {}' | head -c 220)
        last=$(echo "$entry" | jq -c '.snapshot.data[-1] // {}' | head -c 220)
        gray "       │   first pt: $first"
        gray "       │   last pt:  $last"
      else
        gray "       ├─ $port: (unknown shape)"
      fi
    fi
  done
}

run_case() {
  local name=$1
  local instruction=$2
  local skill_mode=$3
  local expect_chart_type=$4
  local expect_check_node=$5  # "yes" if we expect a step_check verdict

  local resp_file artifact_file
  resp_file=$(mktemp -t builder-smoke-XXXX.txt)
  artifact_file="$ARTIFACTS_DIR/$name.json"

  blue "## [$name] skill_step_mode=$skill_mode"
  blue "   instr: $instruction"

  curl -sf -N -X POST "$SIDECAR_BASE/internal/agent/build" \
    -H "X-Service-Token: $SVC_TOKEN" \
    -H "Content-Type: application/json" \
    --max-time 150 \
    -d "$(jq -nc --arg instr "$instruction" --arg sid "smoke-$name" --argjson ssm "$skill_mode" \
        '{user_id:1, session_id:$sid, instruction:$instr, skill_step_mode:$ssm, client_context:{}}')" \
    > "$resp_file" 2>&1

  local case_failed=0

  # plan-level assertions
  local final_status="parse_error"
  if grep -qE '"status":\s*"(failed|plan_unfixable)"' "$resp_file"; then
    final_status=$(grep -oE '"status":\s*"[a-z_]+"' "$resp_file" | tail -1 | sed 's/.*"\([a-z_]*\)"/\1/')
  elif grep -qE '"plan_summary":' "$resp_file" && grep -qE '"n_ops":' "$resp_file"; then
    final_status="ok"
  fi

  local last_plan_ops block_ids=""
  last_plan_ops=$(grep '^data: ' "$resp_file" | grep -E '"plan":\s*\[' | tail -1 | sed 's/^data: //' || true)
  [[ -n "$last_plan_ops" ]] && block_ids=$(echo "$last_plan_ops" | jq -r '[.plan[]? | select(.type=="add_node") | .block_id] | join(",")' 2>/dev/null || echo "")

  case "$final_status" in
    ok) green "   ✓ plan finalized";;
    *) red "   ✗ plan status=$final_status"; case_failed=1;;
  esac

  if [[ "$skill_mode" == "true" && -n "$block_ids" ]]; then
    if echo ",$block_ids," | grep -q ",block_step_check,"; then
      green "   ✓ plan contains block_step_check"
    else
      red "   ✗ skill mode missing block_step_check"; case_failed=1
    fi
    if echo ",$block_ids," | grep -q ",block_alert,"; then
      red "   ✗ skill mode contains block_alert"; case_failed=1
    fi
  fi

  if (( case_failed )) || [[ "$final_status" != "ok" ]]; then
    FAILED=$((FAILED + 1))
    red "   → SSE log: $resp_file"
    echo; return
  fi

  # build pipeline_json + POST preview
  local payload
  payload=$("$PY" -c "
import json, sys
data=json.loads(sys.stdin.read())
plan=data.get('plan') or []
nodes,edges,eid,seen=[],[],0,set()
for op in plan:
  ty=op.get('type')
  if ty=='add_node':
    nid=op.get('node_id')
    if nid in seen: continue
    seen.add(nid)
    nodes.append({'id':nid,'block_id':op.get('block_id'),'block_version':op.get('block_version') or '1.0.0','position':{'x':0,'y':0},'params':op.get('params') or {}})
  elif ty=='set_param':
    nid=op.get('node_id'); n=next((n for n in nodes if n['id']==nid),None)
    if n:
      p=op.get('params') or {}; k=p.get('key'); v=p.get('value')
      if k: n['params'][k]=v
  elif ty=='connect':
    eid+=1
    edges.append({'id':f'e{eid}','from':{'node':op.get('src_id'),'port':op.get('src_port') or 'data'},'to':{'node':op.get('dst_id'),'port':op.get('dst_port') or 'data'}})
srcs={e['from']['node'] for e in edges}
terminals=[n['id'] for n in nodes if n['id'] not in srcs]
target=terminals[0] if terminals else (nodes[-1]['id'] if nodes else None)
print(json.dumps({'pipeline_json':{'version':'1.0','name':'smk','metadata':{},'inputs':[{'name':'equipment_id','type':'string','example':'EQP-01'},{'name':'tool_id','type':'string','example':'EQP-01'}],'nodes':nodes,'edges':edges},'node_id':target,'sample_size':100}))
" <<< "$last_plan_ops")

  local preview_resp preview_status
  preview_resp=$(curl -s -X POST "$SIDECAR_BASE/internal/pipeline/preview" \
    -H "X-Service-Token: $SVC_TOKEN" -H "Content-Type: application/json" --max-time 120 -d "$payload")
  echo "$preview_resp" > "$artifact_file"
  preview_status=$(echo "$preview_resp" | jq -r '.status // "no_status"')

  if [[ "$preview_status" != "success" ]]; then
    red "   ✗ preview status=$preview_status"
    red "   ✗ artifact: $artifact_file"
    case_failed=1
    FAILED=$((FAILED + 1))
    echo; return
  fi

  local n_nodes node_fail_count
  n_nodes=$(echo "$preview_resp" | jq '.all_node_results | length')
  node_fail_count=$(echo "$preview_resp" | jq '[.all_node_results[]? | select(.status != "success")] | length')
  if [[ "$node_fail_count" == "0" ]]; then
    green "   ✓ all $n_nodes nodes executed"
  else
    red "   ✗ $node_fail_count node(s) failed:"
    echo "$preview_resp" | jq -r '.all_node_results | to_entries[] | select(.value.status != "success") | "       \(.key): \(.value.error)"' | while read line; do red "$line"; done
    case_failed=1
  fi

  # ── Dump each node's output ──
  echo "   ─ Node-by-node output:"
  local pj_nodes=$(echo "$payload" | jq -c '.pipeline_json.nodes[]')
  while IFS= read -r node_json; do
    local nid block params_keys
    nid=$(echo "$node_json" | jq -r '.id')
    block=$(echo "$node_json" | jq -r '.block_id')
    params_keys=$(echo "$node_json" | jq -r '.params | keys | join(",")')
    local nstatus rows dur
    nstatus=$(echo "$preview_resp" | jq -r ".all_node_results[\"$nid\"].status // \"?\"")
    rows=$(echo "$preview_resp" | jq -r ".all_node_results[\"$nid\"].rows // \"\"")
    dur=$(echo "$preview_resp" | jq -r ".all_node_results[\"$nid\"].duration_ms // 0 | floor")
    if [[ "$nstatus" == "success" ]]; then
      green "     ╭─ $nid ($block) rows=$rows ${dur}ms params=[$params_keys]"
      dump_node_output "$preview_resp" "$nid" "$block"
    else
      local err
      err=$(echo "$preview_resp" | jq -r ".all_node_results[\"$nid\"].error")
      red "     ╭─ $nid ($block) FAILED: $err"
    fi
  done <<< "$pj_nodes"
  echo "     ╰────────────────"

  # ── Top-level assertions ──
  local target_id
  target_id=$(echo "$preview_resp" | jq -r '.target')
  local target_block
  target_block=$(echo "$preview_resp" | jq -r ".all_node_results[\"$target_id\"] as \$n | .all_node_results | keys[]" | head -1)

  # Chart assertion
  if [[ -n "$expect_chart_type" ]]; then
    local found_chart=0
    local ports
    ports=$(echo "$preview_resp" | jq -r ".all_node_results[\"$target_id\"].preview | keys[]?")
    for port in $ports; do
      local stype npts
      stype=$(echo "$preview_resp" | jq -r ".all_node_results[\"$target_id\"].preview[\"$port\"].snapshot.type // empty")
      npts=$(echo "$preview_resp" | jq ".all_node_results[\"$target_id\"].preview[\"$port\"].snapshot.data | if type==\"array\" then length else 0 end")
      if [[ "$stype" == "$expect_chart_type" ]] && (( npts > 0 )); then
        green "   ✓ terminal[$target_id].$port: chart $stype with $npts data points"
        found_chart=1
      fi
    done
    if (( found_chart == 0 )); then
      red "   ✗ expected chart type='$expect_chart_type' with data points; got none"
      case_failed=1
    fi
  fi

  # step_check assertion
  if [[ "$expect_check_node" == "yes" ]]; then
    local check_rows
    check_rows=$(echo "$preview_resp" | jq '[.all_node_results[] | select(.preview.check) | .preview.check.rows[0]] | length')
    if [[ "$check_rows" == "0" ]]; then
      red "   ✗ expected step_check verdict, got none"
      case_failed=1
    else
      local pass val note has
      has=$(echo "$preview_resp" | jq '[.all_node_results[] | select(.preview.check) | .preview.check.rows[0] | has("pass")] | first')
      pass=$(echo "$preview_resp" | jq '[.all_node_results[] | select(.preview.check) | .preview.check.rows[0].pass] | first')
      val=$(echo "$preview_resp" | jq '[.all_node_results[] | select(.preview.check) | .preview.check.rows[0].value] | first')
      note=$(echo "$preview_resp" | jq -r '[.all_node_results[] | select(.preview.check) | .preview.check.rows[0].note] | first')
      if [[ "$has" != "true" ]]; then
        red "   ✗ step_check.check.rows[0] missing 'pass' field"; case_failed=1
      elif [[ "$note" == *"not numeric"* ]]; then
        red "   ✗ step_check note='$note' (numeric-coercion bug)"; case_failed=1
      else
        green "   ✓ step_check verdict: pass=$pass value=$val ($note)"
      fi
    fi
  fi

  echo "   📁 artifact: $artifact_file"
  echo "   blocks: $block_ids"
  if (( case_failed )); then
    FAILED=$((FAILED + 1))
    red "   → check artifact above"
  fi
  echo
}

blue "═══ Skill Builder LLM smoke (rev 3: data-dumping) ═══"
blue "    sidecar:   $SIDECAR_BASE"
blue "    artifacts: $ARTIFACTS_DIR/"
blue "    python:    $PY"
echo

run_case "A-skill-lastooc" \
  "檢查機台最後一次OOC 時，是否有多張SPC 也OOC (>2)，並且顯示該SPC charts" \
  "true" "" "yes"

run_case "B-chat-3chart" \
  "過去 7 天 EQP-01 STEP_001 的 spc_xbar_chart_value：(1) block_ewma_cusum (mode=cusum, k=0.5, h=4) 偵測小幅 drift；(2) block_box_plot 比較各 lot 之間的分佈差異；(3) block_probability_plot 檢定是否符合常態" \
  "false" "" ""

run_case "C-skill-input" \
  "檢查 \$equipment_id 機台最後一次 OOC 事件，OOC SPC chart 數量 >= 2 時觸發" \
  "true" "" "yes"

run_case "D-chat-xbar-trend" \
  "幫我看 EQP-01 STEP_001 最近 100 筆 xbar 趨勢" \
  "false" "line" ""

echo
if (( FAILED == 0 )); then
  green "═══════════════════════════════════════════════════════════"
  green "  All cases passed (plan + runtime + data assertions) ✓"
  green "═══════════════════════════════════════════════════════════"
  echo "  Artifacts: $ARTIFACTS_DIR/{A,B,C,D}-*.json"
  exit 0
else
  red "═══════════════════════════════════════════════════════════"
  red "  $FAILED case(s) FAILED"
  red "═══════════════════════════════════════════════════════════"
  echo "  Inspect artifacts: $ARTIFACTS_DIR/{A,B,C,D}-*.json"
  exit 1
fi
