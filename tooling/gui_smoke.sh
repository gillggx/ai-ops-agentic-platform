#!/usr/bin/env bash
# 2026-05-13 — GUI-level smoke wrapper. Drives Playwright e2e specs that
# verify what `skill_builder_smoke.sh` can't reach: the React rendering of
# ResultInspector + ChartDSL SVG. Saves screenshots + SVG dumps to
# $ARTIFACTS_DIR so I can review what the user would see.
#
# Usage:
#   tooling/gui_smoke.sh                          # run all GUI suites
#   tooling/gui_smoke.sh --suite inspector        # only ResultInspector
#   tooling/gui_smoke.sh --suite chart            # only chart-render
#   tooling/gui_smoke.sh --headed                 # visible browser (local debug)
#   PW_BASE=https://aiops-gill.com tooling/gui_smoke.sh
#   ARTIFACTS_DIR=/tmp/gui_smk tooling/gui_smoke.sh
#
# Prereqs (one-time):
#   cd aiops-app && npm install
#   npx playwright install chromium    # ~250MB browser download

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$REPO_ROOT/aiops-app"
ART_DIR="${ARTIFACTS_DIR:-$REPO_ROOT/test-results/gui-smoke}"
SUITE="all"
HEADED=""
PW_BASE_DEFAULT="https://aiops-gill.com"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite) SUITE="$2"; shift 2 ;;
    --headed) HEADED="--headed"; shift ;;
    -h|--help)
      sed -n '1,/^set -/p' "$0" | head -n 20
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[34m%s\033[0m\n' "$*"; }
gray()  { printf '\033[90m%s\033[0m\n' "$*"; }

mkdir -p "$ART_DIR"

# Map --suite → spec file(s)
case "$SUITE" in
  all)
    SPECS=(gui-result-inspector.spec.ts gui-chart-render.spec.ts)
    ;;
  inspector)  SPECS=(gui-result-inspector.spec.ts) ;;
  chart)      SPECS=(gui-chart-render.spec.ts) ;;
  *)
    red "✗ unknown suite '$SUITE' (use: all|inspector|chart)"
    exit 2 ;;
esac

cd "$APP_DIR"

# Ensure dependencies installed (offline-friendly skip)
if [[ ! -d node_modules/@playwright/test ]]; then
  blue "→ installing playwright deps (one-time)"
  npm install --no-audit --no-fund >/dev/null 2>&1 || {
    red "✗ npm install failed"
    exit 3
  }
fi

# Ensure chromium installed
if ! npx playwright --version >/dev/null 2>&1; then
  red "✗ playwright CLI not available"
  exit 3
fi
if ! ls node_modules/playwright-core/.local-browsers/chromium-* >/dev/null 2>&1 \
   && ! ls ~/.cache/ms-playwright/chromium-* >/dev/null 2>&1; then
  blue "→ installing chromium (~250 MB, one-time)"
  npx playwright install chromium 2>&1 | tail -5 || {
    red "✗ chromium install failed"
    exit 3
  }
fi

blue "═══ GUI smoke ═══"
blue "  base:      ${PW_BASE:-$PW_BASE_DEFAULT}"
blue "  artifacts: $ART_DIR/"
blue "  suite:     $SUITE  (${#SPECS[@]} spec file(s))"
echo

FAILED=0

export PW_BASE="${PW_BASE:-$PW_BASE_DEFAULT}"
export GUI_SMOKE_ARTIFACTS="$ART_DIR"

for spec in "${SPECS[@]}"; do
  blue "── running: $spec"
  if npx playwright test \
       --config e2e/playwright.config.ts \
       --project=desktop-1920 \
       --reporter=list \
       $HEADED \
       "e2e/$spec" 2>&1 | tee "$ART_DIR/$(basename "$spec" .ts).log"; then
    green "  ✓ $spec passed"
  else
    red   "  ✗ $spec failed — see $ART_DIR/$(basename "$spec" .ts).log"
    FAILED=$((FAILED + 1))
  fi
  echo
done

# Summarize artifacts
echo
blue "── artifacts collected ──"
if [[ -d "$ART_DIR" ]]; then
  find "$ART_DIR" -maxdepth 2 -type f \( -name "*.png" -o -name "*.svg" -o -name "*.log" -o -name "*.html" \) 2>/dev/null \
    | head -40 | while read -r f; do
    sz=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo "?")
    gray "  $f  ($sz bytes)"
  done
fi
echo

if (( FAILED == 0 )); then
  green "═══════════════════════════════════════════════════════════"
  green "  All GUI smoke suites passed ✓"
  green "═══════════════════════════════════════════════════════════"
  echo "  Review screenshots: $ART_DIR/"
  exit 0
else
  red "═══════════════════════════════════════════════════════════"
  red "  $FAILED suite(s) FAILED"
  red "═══════════════════════════════════════════════════════════"
  echo "  Open screenshots: file://$ART_DIR/"
  exit 1
fi
