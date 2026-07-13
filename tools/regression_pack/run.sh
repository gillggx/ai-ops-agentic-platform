#!/usr/bin/env bash
# 回歸腳本包 (P4-4c, 2026-07-13) — 把 2026-07-12/13 踩過的 builder / chat 案例
# 固化成一鍵回歸。動到 builder / verifier / chart 引擎 / ChatOps 前先跑這包。
#
# 用法：
#   bash tools/regression_pack/run.sh              # 全跑（~5 分鐘，3 個 LLM case）
#   AIOPS_BASE=https://aiops-gill.com bash tools/regression_pack/run.sh
#
# 前置：aiops-app/node_modules 有 playwright；PLAYWRIGHT_BROWSERS_PATH 已裝瀏覽器；
#       SSH key ~/Desktop/ai-ops-key.pem（sort 單測跑在 EC2 venv）。
# 注意：LLM case 非決定性 — 單次 FAIL 先重跑確認（穩定判定要 3 連過）。
set -uo pipefail
cd "$(dirname "$0")"
export REG_OUT="${REG_OUT:-/tmp/aiops-regression}"
mkdir -p "$REG_OUT"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"
# ESM bare import 解析靠檔案位置向上找 node_modules — 借 aiops-app 的（symlink）。
[ -e node_modules ] || ln -s ../../aiops-app/node_modules node_modules
SSH_KEY="${AIOPS_SSH_KEY:-$HOME/Desktop/ai-ops-key.pem}"
SSH_HOST="${AIOPS_SSH_HOST:-ubuntu@aiops-gill.com}"
PASS=0; FAIL=0; declare -a RESULTS

run_case() {
  local name="$1"; shift
  echo "── $name ─────────────────────────────"
  if "$@"; then PASS=$((PASS+1)); RESULTS+=("PASS  $name");
  else FAIL=$((FAIL+1)); RESULTS+=("FAIL  $name"); fi
}

# 1. block_sort 多鍵/逗號解析（deterministic 單測，EC2 sidecar venv）
sort_unit() {
  ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SSH_HOST" 'cd /opt/aiops && sudo -u ubuntu venv_sidecar/bin/python - <<PYEOF
import asyncio, pandas as pd
from python_ai_sidecar.pipeline_builder.blocks.sort import SortBlockExecutor
df = pd.DataFrame({"toolID":["B","A","A","B"],"eventTime":["t3","t2","t1","t4"],"v":[1,2,3,4]})
async def main():
    ex = SortBlockExecutor()
    for spec in ["toolID,eventTime", ["toolID,eventTime"], ["toolID","eventTime"]]:
        out = await ex.execute(params={"columns": spec}, inputs={"data": df}, context=None)
        got = list(zip(out["data"]["toolID"], out["data"]["eventTime"]))
        assert got == [("A","t1"),("A","t2"),("B","t3"),("B","t4")], (spec, got)
asyncio.run(main()); print("sort unit PASS")
PYEOF'
}
run_case "sort 多鍵/逗號解析（單測）" sort_unit

# 2. 多機台分色 trend（user case 20260712-232934 — series_field + P1 剪枝回歸）
run_case "多機台分色 trend 建圖（LLM）" \
  bash -c 'node qa_chatops_build.mjs 2>&1 | tee "$REG_OUT/trend.log" | tail -3; grep -q "build result: done" "$REG_OUT/trend.log"'

# 3. scatter 迴歸線 + R²（D6 / P2b）
run_case "scatter 迴歸線建圖（LLM）" \
  bash -c 'node qa_p2_scatter.mjs 2>&1 | tee "$REG_OUT/scatter.log" | tail -3; grep -q "build result: done" "$REG_OUT/scatter.log"'

# 4. 我的偏好頁 + 手冊表分離
run_case "偏好頁/手冊分離" \
  bash -c 'node qa_prefs.mjs 2>&1 | tee "$REG_OUT/prefs.log"; ! grep -q FAIL "$REG_OUT/prefs.log"'

echo
echo "════════ 回歸結果 ════════"
printf '%s\n' "${RESULTS[@]}"
echo "PASS=$PASS FAIL=$FAIL  (截圖/log: $REG_OUT)"
[ "$FAIL" -eq 0 ]
