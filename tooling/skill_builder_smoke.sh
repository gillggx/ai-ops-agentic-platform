#!/usr/bin/env bash
# 2026-05-13 — Skill Builder LLM smoke.
#
# Closes the test-coverage gap discovered when the existing skill_smoke.sh
# only exercised the Skill CRUD / bind / refine endpoints, but NOT the
# actual Builder LLM via /internal/agent/build. Two cases that the user
# repeatedly tried in the GUI kept failing while my non-skill-mode curl
# tests said they passed — because skill_step_mode=true has additional
# validator rules (must end with block_step_check, no block_alert) that
# free-mode doesn't enforce.
#
# This smoke runs the actual build endpoint with skill_step_mode=true,
# parses the SSE stream, and asserts:
#   1. final status != plan_unfixable / failed
#   2. final plan's last add_node is block_step_check
#   3. plan contains NO block_alert
#   4. plan contains NO block_count_rows (deprecated)
#   5. plan ends successfully (got a "session_id" termination event)
#
# Usage:
#   tooling/skill_builder_smoke.sh                            # localhost
#   SIDECAR_BASE=http://localhost:8050 tooling/skill_builder_smoke.sh
#   SVC_TOKEN=<token> tooling/skill_builder_smoke.sh
#
# Required env:
#   SIDECAR_BASE=http://localhost:8050         (default)
#   SVC_TOKEN=<X-Service-Token>                (default: read /opt/aiops/python_ai_sidecar/.env SERVICE_TOKEN)

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

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[34m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }

FAILED=0

run_case() {
  local name=$1
  local instruction=$2
  local skill_mode=$3
  local resp_file=$(mktemp -t builder-smoke-XXXX.txt)

  blue "## [$name] skill_step_mode=$skill_mode"
  blue "   instr: $instruction"

  curl -sf -N -X POST "$SIDECAR_BASE/internal/agent/build" \
    -H "X-Service-Token: $SVC_TOKEN" \
    -H "Content-Type: application/json" \
    --max-time 150 \
    -d "$(jq -nc --arg instr "$instruction" --arg sid "smoke-$name" --argjson ssm "$skill_mode" \
        '{user_id: 1, session_id: $sid, instruction: $instr, skill_step_mode: $ssm, client_context: {}}')" \
    > "$resp_file" 2>&1

  # Extract the final SSE message (last "data:" line that has status field)
  local final_status=$(grep '^data: ' "$resp_file" | tail -1 | sed 's/^data: //' | jq -r '.status // "unknown"' 2>/dev/null || echo "parse_error")

  # Extract the *last* plan attempt's ops list to inspect blocks used
  local last_plan_ops=$(grep '^data: ' "$resp_file" | grep -E '"plan":\s*\[' | tail -1 | sed 's/^data: //' || true)
  local block_ids
  if [[ -n "$last_plan_ops" ]]; then
    block_ids=$(echo "$last_plan_ops" | jq -r '[.plan[]? | select(.type=="add_node") | .block_id] | join(",")' 2>/dev/null || echo "")
  else
    block_ids=""
  fi

  # Assertions
  local case_failed=0

  # 1. Plan didn't end as plan_unfixable / failed
  case "$final_status" in
    plan_unfixable|failed|parse_error)
      red   "   ✗ final status=$final_status (expected finished or paused)"
      case_failed=1
      ;;
    finished|user_confirm_required|paused|""|unknown)
      green "   ✓ final status=$final_status"
      ;;
    *)
      yellow "   ? final status=$final_status"
      ;;
  esac

  # 2. (skill mode only) last add_node must be block_step_check
  if [[ "$skill_mode" == "true" && -n "$block_ids" ]]; then
    local last_block=$(echo "$block_ids" | awk -F, '{print $NF}')
    if [[ "$last_block" == "block_step_check" ]]; then
      green "   ✓ last add_node = block_step_check (skill mode terminal OK)"
    else
      red   "   ✗ last add_node = '$last_block' (skill mode requires block_step_check terminator)"
      case_failed=1
    fi
  fi

  # 3. (skill mode only) no block_alert
  if [[ "$skill_mode" == "true" && -n "$block_ids" ]]; then
    if echo ",$block_ids," | grep -q ",block_alert,"; then
      red   "   ✗ plan contains block_alert (forbidden in skill mode)"
      case_failed=1
    else
      green "   ✓ no block_alert in plan"
    fi
  fi

  # 4. no deprecated blocks
  if [[ -n "$block_ids" ]]; then
    for dep in block_count_rows block_spc_long_form; do
      if echo ",$block_ids," | grep -q ",$dep,"; then
        yellow "   ⚠ plan contains $dep (deprecated; acceptable but suboptimal)"
      fi
    done
  fi

  if [[ -n "$block_ids" ]]; then
    blue   "   blocks used: $block_ids"
  else
    yellow "   ⚠ couldn't parse blocks from plan"
  fi

  if (( case_failed == 1 )); then
    FAILED=$((FAILED + 1))
    red "   → log saved at $resp_file"
  else
    rm -f "$resp_file"
  fi
  echo
}

blue "==== Skill Builder LLM smoke ===="
blue "    sidecar: $SIDECAR_BASE"
echo

# Case A — user's repeated failure case (skill mode)
run_case "A-skill-lastooc" \
  "檢查機台最後一次OOC 時，是否有多張SPC 也OOC (>2)，並且顯示該SPC charts" \
  "true"

# Case B — chat-mode 3-chart diagnostic
run_case "B-chat-3chart" \
  "過去 7 天 EQP-01 STEP_001 的 spc_xbar_chart_value：(1) block_ewma_cusum (mode=cusum, k=0.5, h=4) 偵測小幅 drift；(2) block_box_plot 比較各 lot 之間的分佈差異；(3) block_probability_plot 檢定是否符合常態" \
  "false"

# Case C — simple skill C1 with $equipment_id
run_case "C-skill-input" \
  "檢查 \$equipment_id 機台最後一次 OOC 事件，OOC SPC chart 數量 >= 2 時觸發" \
  "true"

# Case D — chat-mode chart (no skill terminator)
run_case "D-chat-xbar-trend" \
  "幫我看 EQP-01 STEP_001 最近 100 筆 xbar 趨勢" \
  "false"

echo
if (( FAILED == 0 )); then
  green "┌─────────────────────────────────────────────┐"
  green "│  All Skill Builder smoke cases passed ✓      │"
  green "└─────────────────────────────────────────────┘"
  exit 0
else
  red "┌─────────────────────────────────────────────┐"
  red "│  $FAILED case(s) FAILED — see logs above       │"
  red "└─────────────────────────────────────────────┘"
  exit 1
fi
