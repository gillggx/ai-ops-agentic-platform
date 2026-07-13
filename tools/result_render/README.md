# result_render — 成品目檢的 headless 渲染

Build 完工前把最終 chart/table 用「跟使用者看到一模一樣」的前端 SVG 引擎
渲染成 PNG，給 vision judge（Haiku）對照建圖目標。sidecar 端邏輯在
`python_ai_sidecar/agent_builder/result_vision.py`；verifier 閘在
`phase_verifier._final_result_gate`。

| 檔 | 作用 |
|---|---|
| `entry.ts` | 瀏覽器端入口：`window.__renderResult({kind, spec|columns+rows})` |
| `bundle.js` | esbuild 打包（80KB、無 React）— **進 repo**；改 charts/ 後跑 `build.sh` 重建 |
| `render.mjs` | `node render.mjs payload.json out.png`（Playwright headless chromium）|

## EC2 前置（一次性，已於 2026-07-13 裝好）
```bash
cd /opt/aiops/tools/result_render && ln -s ../../aiops-app/node_modules node_modules
cd /opt/aiops/aiops-app && npx playwright install chromium --with-deps   # ~500MB
```

## 開關
- `RESULT_VISION_CHECK=0` 關目檢（只剩 deterministic 規格檢 chart_spec_gaps）
- `RESULT_VISION_MODEL` 換 judge 模型（預設 claude-haiku-4-5）

## 校準紀錄
judge 只攔重大可見偏差（空圖/單色/型態錯/完全沒管制線）；小數位、圖例順序、
序列差 1-2 個一律放行；guidance 禁杜撰參數名。首輪未校準版曾把好圖判死
（挑 17.50 vs 17.5005）— 改 prompt 後 2/2 過。
