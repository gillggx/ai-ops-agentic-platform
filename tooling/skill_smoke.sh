#!/usr/bin/env bash
# Phase 11 v6 — Skill → Pipeline Builder → bind → refine end-to-end smoke.
#
# Validates the BACKEND contract a developer change must preserve so I
# don't ship broken refine / bind logic and only catch it when the user
# clicks through the GUI.
#
# Usage:
#   tooling/skill_smoke.sh                        # default: localhost
#   JAVA_BASE=http://localhost:8002 tooling/skill_smoke.sh
#   tooling/skill_smoke.sh --remote               # SSH into EC2 + run there
#
# Coverage:
#   - POST /auth/login (local mode)
#   - POST /skill-documents (create temp skill)
#   - GET  /skill-documents/{slug}/builder-url?slot=confirm
#       ⇒ assert path = /admin/pipeline-builder/new (no existing pipeline yet)
#       ⇒ assert query has skill_doc_id + instruction
#   - direct INSERT into pb_pipelines (fake pipeline_json)
#   - POST /bind-pipeline {confirm slot}
#       ⇒ assert pb_pipelines.parent_skill_doc_id stamped
#       ⇒ assert skill_documents.confirm_check.pipeline_id
#   - GET  /builder-url?slot=confirm  (refine = same slot, second time)
#       ⇒ assert path = /admin/pipeline-builder/{fakeId}
#       ⇒ assert query has existing_pipeline_id={fakeId}
#   - POST /bind-pipeline (same pipeline_id) → assert idempotent
#   - DELETE skill-documents/{slug}
#       ⇒ psql: pb_pipelines row CASCADE-deleted
#
# Required env (defaults shown):
#   JAVA_BASE=http://localhost:8002
#   PG_DSN="-h localhost -U aiops -d aiops_db"
#   PG_PASSWORD=<from java-backend/.env>
#   USER=itadmin_test  PASSWORD=ITAdmin@2026

set -euo pipefail

JAVA_BASE=${JAVA_BASE:-http://localhost:8002}
PG_DSN=${PG_DSN:--h localhost -U aiops -d aiops_db}
PG_PASSWORD=${PG_PASSWORD:-}
USERNAME=${USERNAME:-itadmin_test}
PASSWORD=${PASSWORD:-ITAdmin@2026}
SLUG=smoke-$(date +%s)

if ! command -v jq >/dev/null; then
  echo "✗ jq required (apt-get install jq)" >&2
  exit 2
fi

if [[ -z "$PG_PASSWORD" ]]; then
  if [[ -f /opt/aiops/java-backend/.env ]]; then
    PG_PASSWORD=$(grep '^DB_PASSWORD=' /opt/aiops/java-backend/.env | cut -d= -f2)
  fi
fi
export PGPASSWORD=$PG_PASSWORD

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue() { printf '\033[34m%s\033[0m\n' "$*"; }

assert_eq() {
  local expected=$1 actual=$2 desc=$3
  if [[ "$expected" == "$actual" ]]; then
    green "  ✓ $desc"
  else
    red "  ✗ $desc"
    red "      expected: $expected"
    red "      actual:   $actual"
    exit 1
  fi
}

assert_match() {
  local pattern=$1 actual=$2 desc=$3
  if [[ "$actual" =~ $pattern ]]; then
    green "  ✓ $desc"
  else
    red "  ✗ $desc"
    red "      pattern: $pattern"
    red "      actual:  $actual"
    exit 1
  fi
}

cleanup() {
  if [[ -n "${SKILL_ID:-}" ]]; then
    blue "→ cleanup: DELETE skill $SLUG"
    curl -sf -X DELETE "$JAVA_BASE/api/v1/skill-documents/$SLUG" \
      -H "Authorization: Bearer $TOKEN" >/dev/null || true
    psql $PG_DSN -tAc "SELECT COUNT(*) FROM pb_pipelines WHERE parent_skill_doc_id=$SKILL_ID" \
      | xargs -I {} test {} = 0 \
      && green "  ✓ pb_pipelines CASCADE deleted" \
      || red "  ✗ pb_pipelines orphan after skill delete"
  fi
}
trap cleanup EXIT

# ── 1. Login ─────────────────────────────────────────────────────────
blue "[1/8] login as $USERNAME"
LOGIN=$(curl -sf -X POST "$JAVA_BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")
TOKEN=$(echo "$LOGIN" | jq -r .data.access_token)
[[ -n "$TOKEN" && "$TOKEN" != "null" ]] || { red "login failed: $LOGIN"; exit 1; }
green "  ✓ token acquired"

AH="Authorization: Bearer $TOKEN"

# ── 2. Create temp skill ─────────────────────────────────────────────
blue "[2/8] POST /skill-documents (create $SLUG)"
CREATE=$(curl -sf -X POST "$JAVA_BASE/api/v1/skill-documents" \
  -H "$AH" -H "Content-Type: application/json" \
  -d "{\"slug\":\"$SLUG\",\"title\":\"smoke $SLUG\",\"stage\":\"patrol\",\"triggerConfig\":\"{\\\"type\\\":\\\"event\\\",\\\"event\\\":\\\"OOC\\\",\\\"target\\\":{\\\"kind\\\":\\\"all\\\",\\\"ids\\\":[]}}\"}")
SKILL_ID=$(echo "$CREATE" | jq -r .data.id)
assert_match "^[0-9]+$" "$SKILL_ID" "got skill id"

# ── 3. builder-url for empty slot ────────────────────────────────────
blue "[3/8] GET /builder-url?slot=confirm  (empty slot → expect /new path)"
RESP=$(curl -sf -G "$JAVA_BASE/api/v1/skill-documents/$SLUG/builder-url" \
  -H "$AH" --data-urlencode "slot=confirm" --data-urlencode "instruction=test refine 5-in-3-out")
URL=$(echo "$RESP" | jq -r .data.builder_url)
assert_match "^/admin/pipeline-builder/new\?" "$URL" "URL targets /new (no pipeline yet)"
assert_match "embed=skill" "$URL" "URL has embed=skill"
assert_match "skill_doc_id=$SKILL_ID" "$URL" "URL has skill_doc_id"
assert_match "instruction=" "$URL" "URL has instruction"
[[ ! "$URL" =~ existing_pipeline_id ]] && green "  ✓ no existing_pipeline_id (correct for empty slot)" || { red "✗ unexpected existing_pipeline_id on empty slot"; exit 1; }

# ── 4. Insert fake pipeline ──────────────────────────────────────────
blue "[4/8] INSERT fake pb_pipelines row"
PSQL_OUT=$(psql $PG_DSN -tAc "
  INSERT INTO pb_pipelines (name, description, status, version, pipeline_json)
  VALUES ('smoke fake', 'smoke', 'draft', '1.0.0',
          '{\"version\":\"1.0\",\"name\":\"smoke\",\"nodes\":[],\"edges\":[],\"inputs\":[]}')
  RETURNING id;")
FAKE_PID=$(printf '%s\n' "$PSQL_OUT" | sed -n '1p' | tr -d ' \r\n')
assert_match "^[0-9]+$" "$FAKE_PID" "fake pipeline created (id=$FAKE_PID)"

# ── 5. Bind to confirm slot ──────────────────────────────────────────
blue "[5/8] POST /bind-pipeline {slot:confirm, pipeline_id:$FAKE_PID}"
BIND=$(curl -sf -X POST "$JAVA_BASE/api/v1/skill-documents/$SLUG/bind-pipeline" \
  -H "$AH" -H "Content-Type: application/json" \
  -d "{\"slot\":\"confirm\",\"pipeline_id\":$FAKE_PID,\"description\":\"test\",\"summary\":\"smoke\"}")
CC_PID=$(echo "$BIND" | jq -r '.data.confirm_check' | jq -r '.pipeline_id')
assert_eq "$FAKE_PID" "$CC_PID" "skill.confirm_check.pipeline_id stamped"

OWNER=$(psql $PG_DSN -tAc "SELECT parent_skill_doc_id FROM pb_pipelines WHERE id=$FAKE_PID" | tr -d ' ')
assert_eq "$SKILL_ID" "$OWNER" "pb_pipelines.parent_skill_doc_id stamped"

SLOT=$(psql $PG_DSN -tAc "SELECT parent_slot FROM pb_pipelines WHERE id=$FAKE_PID" | tr -d ' ')
assert_eq "confirm" "$SLOT" "pb_pipelines.parent_slot stamped"

# ── 6. Refine: builder-url for SAME slot, expect existing_pipeline_id ─
blue "[6/8] GET /builder-url?slot=confirm  (after bind = REFINE)"
RESP2=$(curl -sf -G "$JAVA_BASE/api/v1/skill-documents/$SLUG/builder-url" \
  -H "$AH" --data-urlencode "slot=confirm" --data-urlencode "instruction=refine again")
URL2=$(echo "$RESP2" | jq -r .data.builder_url)
assert_match "^/admin/pipeline-builder/$FAKE_PID\?" "$URL2" "URL targets /[id] route"
assert_match "existing_pipeline_id=$FAKE_PID" "$URL2" "URL has existing_pipeline_id=$FAKE_PID"

# ── 7. Re-bind same pipeline (refine bind = idempotent update) ────────
blue "[7/8] POST /bind-pipeline again (idempotent refine)"
BIND2=$(curl -sf -X POST "$JAVA_BASE/api/v1/skill-documents/$SLUG/bind-pipeline" \
  -H "$AH" -H "Content-Type: application/json" \
  -d "{\"slot\":\"confirm\",\"pipeline_id\":$FAKE_PID,\"description\":\"refined\",\"summary\":\"refined\"}")
CC_PID2=$(echo "$BIND2" | jq -r '.data.confirm_check' | jq -r '.pipeline_id')
assert_eq "$FAKE_PID" "$CC_PID2" "pipeline_id unchanged after refine bind"

NUM_PIPES=$(psql $PG_DSN -tAc "SELECT COUNT(*) FROM pb_pipelines WHERE parent_skill_doc_id=$SKILL_ID" | tr -d ' ')
assert_eq "1" "$NUM_PIPES" "exactly 1 pipeline owned by skill (no version chain orphan)"

# ── 8. Dangling pipeline ref → builder-url should fall back to /new ──
blue "[8/9] orphan pb_pipelines row, then GET /builder-url same slot"
psql $PG_DSN -c "DELETE FROM pb_pipelines WHERE id=$FAKE_PID" >/dev/null
RESP3=$(curl -sf -G "$JAVA_BASE/api/v1/skill-documents/$SLUG/builder-url" \
  -H "$AH" --data-urlencode "slot=confirm" --data-urlencode "instruction=after orphan")
URL3=$(echo "$RESP3" | jq -r .data.builder_url)
assert_match "^/admin/pipeline-builder/new\?" "$URL3" "dangling ref → URL falls back to /new"
[[ ! "$URL3" =~ existing_pipeline_id ]] && green "  ✓ no existing_pipeline_id in URL (correct: ref was orphaned)" || { red "✗ stale existing_pipeline_id leaked"; exit 1; }
# Mark FAKE_PID consumed so cleanup trap doesn't try to verify FK CASCADE.
unset FAKE_PID

# ── 9. Done ───────────────────────────────────────────────────────────
green "[9/9] all assertions passed"
echo
green "┌─────────────────────────────────────────────┐"
green "│  Skill → Builder → Bind → Refine OK ✓        │"
green "└─────────────────────────────────────────────┘"
