#!/usr/bin/env bash
# scripts/warm-build-caches.sh
#
# Phase 4 (project-restructure / internal-network transfer):
# Run on a machine that HAS internet access to pre-populate every build
# tool's cache. After this completes, the contents of:
#   ~/.gradle/caches
#   ~/.npm/_cacache
#   /opt/wheels (created by this script)
# can be tarballed and shipped to an air-gapped environment, where:
#   ./gradlew bootJar --offline
#   npm ci --offline
#   pip install --no-index --find-links /opt/wheels -r requirements.txt
# all succeed without contacting the public internet.
#
# Usage:
#   bash scripts/warm-build-caches.sh
#
# Outputs:
#   - $HOME/.gradle/caches      (gradle deps)
#   - $HOME/.npm/_cacache       (npm deps)
#   - /opt/wheels/sidecar       (sidecar pip wheels)
#   - /opt/wheels/simulator     (simulator pip wheels)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHEELS_BASE="${WHEELS_BASE:-/opt/wheels}"

echo "════════════════════════════════════════════════════════════"
echo "  warm-build-caches.sh"
echo "  Repo: $REPO_ROOT"
echo "  Wheels output: $WHEELS_BASE"
echo "════════════════════════════════════════════════════════════"
echo ""

# ── 1. Gradle: resolve all dependencies for both subprojects ──────────────
echo "☕  Gradle — resolving Java + Scheduler dependencies..."
cd "$REPO_ROOT"
./gradlew --refresh-dependencies dependencies \
  -p java-backend \
  -p java-scheduler \
  --console=plain 2>&1 | tail -20
echo ""
echo "  ✅  Gradle caches warmed at ~/.gradle/caches/modules-2/"
echo ""

# Build the bootJars too — this exercises the full compile path so any
# transitive dep that's only needed at compile time gets cached.
echo "☕  Gradle — building bootJars (compile-time deps)..."
./gradlew :java-backend:bootJar :java-scheduler:bootJar --console=plain 2>&1 | tail -10
echo "  ✅  bootJars built"
echo ""

# ── 2. npm: aiops-app + simulator/frontend ───────────────────────────────
echo "📦  npm — aiops-app deps..."
cd "$REPO_ROOT/aiops-app"
npm ci 2>&1 | tail -3
echo "  ✅  aiops-app node_modules ready"
echo ""

if [[ -d "$REPO_ROOT/ontology_simulator/frontend" ]]; then
  echo "📦  npm — ontology_simulator/frontend deps..."
  cd "$REPO_ROOT/ontology_simulator/frontend"
  npm ci 2>&1 | tail -3
  echo "  ✅  simulator frontend node_modules ready"
fi
echo ""

# ── 3. pip wheels for sidecar + simulator ────────────────────────────────
mkdir -p "$WHEELS_BASE/sidecar" "$WHEELS_BASE/simulator"

echo "🐍  pip — downloading sidecar wheels to $WHEELS_BASE/sidecar/..."
python3 -m pip download \
  -r "$REPO_ROOT/python_ai_sidecar/requirements.txt" \
  -d "$WHEELS_BASE/sidecar" \
  --no-cache-dir 2>&1 | tail -5
echo "  ✅  $(ls "$WHEELS_BASE/sidecar" | wc -l) wheel files in $WHEELS_BASE/sidecar/"
echo ""

echo "🐍  pip — downloading simulator wheels to $WHEELS_BASE/simulator/..."
python3 -m pip download \
  -r "$REPO_ROOT/ontology_simulator/requirements.txt" \
  -d "$WHEELS_BASE/simulator" \
  --no-cache-dir 2>&1 | tail -5
echo "  ✅  $(ls "$WHEELS_BASE/simulator" | wc -l) wheel files in $WHEELS_BASE/simulator/"
echo ""

# ── 4. Summary + tarball hint ───────────────────────────────────────────
echo "════════════════════════════════════════════════════════════"
echo "  Done. To ship to an air-gapped environment, tar these:"
echo ""
echo "    tar czf gradle-caches.tar.gz   -C \$HOME .gradle/caches"
echo "    tar czf npm-caches.tar.gz      -C \$HOME .npm/_cacache"
echo "    tar czf node-modules.tar.gz    aiops-app/node_modules"
echo "    tar czf sidecar-wheels.tar.gz  -C $WHEELS_BASE sidecar"
echo "    tar czf simulator-wheels.tar.gz -C $WHEELS_BASE simulator"
echo ""
echo "  On the target air-gapped machine, restore + run with --offline:"
echo "    ./gradlew bootJar --offline"
echo "    cd aiops-app && npm ci --offline"
echo "    pip install --no-index --find-links $WHEELS_BASE/sidecar \\"
echo "        -r python_ai_sidecar/requirements.txt"
echo "════════════════════════════════════════════════════════════"
