#!/usr/bin/env bash
# 2026-05-13 — Deterministic pipeline runtime smoke. NO LLM, NO browser.
#
# What it does:
#   1. For each fixture pipeline_json under tooling/pipeline_fixtures/:
#      POST to /internal/pipeline/preview, target = last node
#   2. Assert per-node status=success, no node error
#   3. For chart nodes: distinct eventTime count >= 3 (catches single-point bug)
#   4. For step_check nodes: value is numeric, not "error"/None
#   5. Dump full preview JSON to /tmp/pipeline_smoke/<case>.json
#
# Why: skill_builder_smoke / gui_smoke / skill-flow all include LLM →
# flaky → can't distinguish LLM bug from executor bug. This isolates
# executor + path infrastructure + chart engine from LLM judgment.
#
# Usage:
#   tooling/pipeline_smoke.sh
#   SIDECAR_BASE=http://localhost:8050 tooling/pipeline_smoke.sh
#   tooling/pipeline_smoke.sh --case case_a_last_ooc   # only one
#   tooling/pipeline_smoke.sh --remote                  # SSH EC2

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURES_DIR="${FIXTURES_DIR:-$REPO_ROOT/tooling/pipeline_fixtures}"
ART_DIR="${ARTIFACTS_DIR:-/tmp/pipeline_smoke}"
SIDECAR_BASE="${SIDECAR_BASE:-http://localhost:8050}"
SVC_TOKEN="${SVC_TOKEN:-}"
CASE_FILTER=""
REMOTE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --case) CASE_FILTER="$2"; shift 2 ;;
    --remote) REMOTE=1; shift ;;
    -h|--help) sed -n '1,40p' "$0"; exit 0 ;;
    *) echo "unknown: $1" >&2; exit 2 ;;
  esac
done

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
gray()   { printf '\033[90m%s\033[0m\n' "$*"; }
blue()   { printf '\033[34m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

# --remote = ssh + run there
if (( REMOTE == 1 )); then
  blue "→ running on EC2"
  scp -i ~/Desktop/ai-ops-key.pem -r "$REPO_ROOT/tooling/pipeline_fixtures" \
    "$REPO_ROOT/tooling/pipeline_smoke.sh" ubuntu@43.213.71.239:/tmp/ 2>&1 | tail -3
  exec ssh -i ~/Desktop/ai-ops-key.pem ubuntu@43.213.71.239 \
    "mkdir -p /tmp/pipeline_fixtures && cp -r /tmp/pipeline_fixtures/* /tmp/pipeline_fixtures/ 2>/dev/null; \
     FIXTURES_DIR=/tmp/pipeline_fixtures bash /tmp/pipeline_smoke.sh ${CASE_FILTER:+--case $CASE_FILTER}"
fi

if [[ -z "$SVC_TOKEN" && -f /opt/aiops/python_ai_sidecar/.env ]]; then
  SVC_TOKEN=$(grep '^SERVICE_TOKEN=' /opt/aiops/python_ai_sidecar/.env | cut -d= -f2)
fi
if [[ -z "$SVC_TOKEN" ]]; then
  red "✗ SVC_TOKEN env required (or sidecar .env on host)"
  exit 2
fi

mkdir -p "$ART_DIR"

FAILED=0
TOTAL=0

run_fixture() {
  local fix_file=$1
  local name
  name=$(basename "$fix_file" .json)
  if [[ -n "$CASE_FILTER" && "$name" != "$CASE_FILTER" ]]; then return; fi
  TOTAL=$((TOTAL + 1))

  blue "## [$name]"
  local pipeline_json
  pipeline_json=$(cat "$fix_file")

  # Find ALL terminal nodes (no outgoing edges) — preview each so every
  # branch executes. Single-target preview only walks ancestors of that
  # target → side-branch chart nodes wouldn't run.
  local terminals
  terminals=$(echo "$pipeline_json" | jq -r '
    .edges as $edges |
    .nodes |
    map(.id) |
    map(select(. as $nid | $edges | all(.from.node != $nid))) | .[]')

  local resp_file="$ART_DIR/${name}.json"
  echo '{"per_target": {}}' > "$resp_file"

  for target in $terminals; do
    gray "  → preview target=$target"
    local payload
    payload=$(jq -nc --argjson pj "$pipeline_json" --arg tid "$target" \
      '{pipeline_json: $pj, node_id: $tid, sample_size: 200}')
    local single_file="$ART_DIR/${name}.${target}.resp.json"
    curl -s -X POST "$SIDECAR_BASE/internal/pipeline/preview" \
      -H "X-Service-Token: $SVC_TOKEN" -H "Content-Type: application/json" \
      --max-time 90 -d "$payload" > "$single_file"
    # Merge: per_target[target] = response (read from file, avoid arg-list-too-long)
    jq --arg t "$target" --slurpfile r "$single_file" \
      '.per_target[$t] = $r[0]' "$resp_file" > "${resp_file}.tmp" \
      && mv "${resp_file}.tmp" "$resp_file"
  done

  # For assertions below, combine all node results from all targets into one map.
  local merged
  merged=$(jq '[.per_target | to_entries[] | .value.all_node_results // {}] | add // {}' "$resp_file")
  # Write a flattened view for the assertion logic below.
  echo "$merged" > "${resp_file}.merged.json"

  local case_failed=0

  # Preview-level status — check each target preview succeeded
  local n_failed_targets
  n_failed_targets=$(jq '[.per_target | to_entries[] | select(.value.status != "success")] | length' "$resp_file")
  if (( n_failed_targets > 0 )); then
    red "  ✗ $n_failed_targets target preview(s) failed at endpoint level"
    jq -r '.per_target | to_entries[] | select(.value.status != "success") | "      \(.key): \(.value.detail // .value.status)"' "$resp_file" | while read l; do red "$l"; done
    case_failed=1
  fi

  # Per-node assertions (merged from all target runs)
  local n_nodes_run
  n_nodes_run=$(jq 'keys | length' "${resp_file}.merged.json")
  local n_failed
  n_failed=$(jq '[to_entries[] | select(.value.error != null)] | length' "${resp_file}.merged.json")

  if [[ "$n_failed" == "0" ]]; then
    green "  ✓ $n_nodes_run nodes executed (across all terminals)"
  else
    red "  ✗ $n_failed node(s) failed at runtime:"
    jq -r 'to_entries[] | select(.value.error != null) | "      \(.key): \(.value.error)"' "${resp_file}.merged.json" | while read l; do red "$l"; done
    case_failed=1
  fi

  # === Chart-spec assertions: distinct eventTime >= 3 ===
  # Handle two preview shapes:
  #   (a) non-facet: preview[port].snapshot = {type, data: [...]}
  #   (b) facet:     preview[port] = {type:"list", sample: [{type, data: [...]}, ...]}
  while IFS=$'\t' read -r nid port chart_type panel_idx ndata distinct_x; do
    if [[ "$chart_type" == "null" || -z "$chart_type" ]]; then continue; fi
    local label
    if [[ -n "$panel_idx" && "$panel_idx" != "_" ]]; then
      label="chart '$nid'.$port[panel $panel_idx] type=$chart_type"
    else
      label="chart '$nid'.$port type=$chart_type"
    fi
    if (( distinct_x < 3 )); then
      red "  ✗ $label: only $distinct_x distinct eventTime values (ndata=$ndata) — single-point bug"
      case_failed=1
    else
      green "  ✓ $label: $ndata data points, $distinct_x distinct eventTimes"
    fi
  done < <(jq -r '
    to_entries[] |
    select(.value.status == "success") |
    .key as $nid |
    (.value.preview // {} | to_entries[]?) |
    .key as $port |
    .value as $blob |
    if ($blob.snapshot?.data | type) == "array" then
      [[$nid, $port, $blob.snapshot.type, "_", ($blob.snapshot.data | length), ($blob.snapshot.data | map(.eventTime // null) | unique | length)]]
    elif ($blob.type == "list") and ($blob.sample? | type) == "array" then
      [$blob.sample | to_entries[] | [$nid, $port, .value.type, (.key | tostring), (.value.data | length), (.value.data | map(.eventTime // null) | unique | length)]]
    else [] end
    | .[] | @tsv' "${resp_file}.merged.json" 2>/dev/null)

  # === step_check verdict assertions ===
  while IFS=$'\t' read -r nid pass value note; do
    if [[ -z "$value" ]]; then continue; fi
    if [[ "$value" == "error" || "$value" == "null" ]]; then
      red "  ✗ step_check '$nid': value=$value (pipeline failed before verdict)"
      case_failed=1
    elif [[ "$note" == *"not numeric"* || "$note" == *"error"* ]]; then
      red "  ✗ step_check '$nid': bad note='$note'"
      case_failed=1
    else
      green "  ✓ step_check '$nid': pass=$pass value=$value note='$note'"
    fi
  done < <(jq -r '
    to_entries[] |
    .key as $nid |
    .value.preview?.check?.rows[0]? // empty |
    [$nid, (.pass | tostring), (.value | tostring), (.note // "")] |
    @tsv' "${resp_file}.merged.json" 2>/dev/null)

  gray "  artifact: $resp_file"
  if (( case_failed )); then FAILED=$((FAILED + 1)); fi
  echo
}

blue "═══ Pipeline runtime smoke (no LLM, no browser) ═══"
blue "  sidecar:   $SIDECAR_BASE"
blue "  fixtures:  $FIXTURES_DIR"
blue "  artifacts: $ART_DIR/"
echo

for fix in "$FIXTURES_DIR"/*.json; do
  [[ -f "$fix" ]] || continue
  run_fixture "$fix"
done

if (( FAILED == 0 && TOTAL > 0 )); then
  green "═══════════════════════════════════════════════════════════"
  green "  $TOTAL/$TOTAL fixtures passed ✓ (executor + path + chart engine sound)"
  green "═══════════════════════════════════════════════════════════"
  exit 0
elif (( TOTAL == 0 )); then
  red "no fixtures matched"; exit 1
else
  red "═══════════════════════════════════════════════════════════"
  red "  $FAILED / $TOTAL fixtures FAILED — see artifacts in $ART_DIR/"
  red "═══════════════════════════════════════════════════════════"
  exit 1
fi
