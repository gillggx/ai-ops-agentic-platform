# SLASH-17 Baseline — 2026-06-23

Full e2e run of all 17 production slash commands through the v30 builder, on the
shipped config (HEAD ad12ef5: goal_plan retry A/B + phase_verifier leaf-check C
+ canonical block seed; KIMI K2.5 via OpenRouter). Score: **16 success / 1 fail**.

Regenerate: `bash tools/slash17/run.sh <label>` + `python tools/slash17/grade_strict.py <label>`.

| # | command | prompt | built nodes | time | status |
|---|---|---|---|---|---|
| 1 | spc-trend | 幫我看 EQP-01 STEP_001 最近 100 筆 xbar 趨勢 | 4n → line_chart | 171s | OK |
| 2 | spc-ooc | 過去 24h 哪些機台 SPC OOC 最多?列前 5 名 | 5n → data_view | 267s | OK |
| 3 | spc-cpk | 比較 EQP-01 STEP_001 過去 7 天 R、Cpk、Cpk_std 趨勢 | 4n → line_chart | 148s | OK |
| 4 | spc-multi-tool | 比較 EQP-01~05 STEP_001 xbar，彩色 line chart | 5n → line_chart | 159s | OK |
| 5 | spc-drift | 7 天 ewma_cusum + box_plot + 常態檢定 | 6n → ewma_cusum/box_plot/probability_plot | 156s | OK |
| 6 | spc-xbar-r-pair | EQP-01 STEP_001 7 天 X-bar 管制圖（WECO） | 4n → xbar_r | 123s | OK |
| 7 | spc-multi-step | EQP-01 三站 xbar（spc_panel） | 7n → spc_panel+line_chart×2 | 290s | OK |
| 8 | spc-tool-box | EQP-01 各 lot xbar 分佈 box_plot | 4n → box_plot | 158s | OK |
| 9 | spc-normality | xbar 常態性檢定 Q-Q | 4n → probability_plot | 131s | OK |
| 10 | spc-cusum | 14 天 EWMA-CUSUM 漂移偵測 | 4n → ewma_cusum | 164s | OK |
| 11 | apc-drift | APC etch_time_offset 24h 趨勢+drift（weco） | 3n → line_chart | 380s | OK |
| 12 | apc-trend | APC etch_time_offset 24h 趨勢 | 3n → line_chart | 147s | OK |
| 13 | apc-recipe-compare | 每 recipe APC etch_time_offset box plot 對比 | 5n (handover) | 278s | **FAIL** |
| 14 | patrol-status | 機台狀態快照標異常 | 8n → data_view×2 | 332s | OK |
| 15 | ooc-ranking | EQP-01/02/03 OOC groupby toolID bar chart | 7n → bar_chart | 302s | OK |
| 16 | ooc-pareto | OOC groupby chart_name bar chart | 5n → block_pareto | 109s | OK* |
| 17 | step-yield | 各 STEP OOC，依 step 分組，bar chart | 4n → bar_chart | 124s | OK |

Avg ~3 min/case. Slowest: apc-drift 380s, patrol-status 332s.

## Known issues (carry into next round)

1. **apc-recipe-compare FAIL — Fix C regression (the leaf-check loops).**
   Build reached `handover_pending` after 20 rounds. `phase_verifier._check_leaf`
   (the 2026-06-23 non-output-leaf rule) repeatedly REJECTed phase p2 with
   "orphan: data node is a leaf (no downstream)" — the agent built block_pluck /
   block_select as dangling side-branches off the box_plot chain, the leaf-check
   bounced it, and the agent kept re-adding leaves instead of connecting/removing
   → infinite reject loop → handover. **Fix C lacks a bounded-reject / fallback**
   (after K leaf-rejects on a phase: auto-prune the dangling leaf, or let it pass
   to finalize). This is the "agent 收到回饋仍修不好" case the Fix C spec flagged.

2. **`ooc-pareto` (16) first run HUNG** — a transient server-side build stall
   (agentic_phase_loop stopped progressing). Re-run was clean (5n, 109s). Not
   reproducible, but exposed a tooling gap:

3. **slash17 driver has NO wall-clock cap.** When a build stalls server-side the
   SSE keepalive keeps the stream alive, so the driver's `requests` timeout never
   fires and it hangs forever (cost us ~30 min this run). Mirror chat_driver's
   per-case wall-clock cap.
