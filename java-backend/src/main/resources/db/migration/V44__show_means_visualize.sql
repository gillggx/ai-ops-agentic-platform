-- V44 — 2026-05-13: "Visualize ≠ list" agent_knowledge rule.
--
-- Background:
--   User reported "檢查機台最後一次OOC ... 並且顯示該SPC charts" produced a
--   pipeline that ENDED with block_data_view listing chart names + values.
--   That's a table, NOT trend charts. LLM took a shortcut.
--
--   Hardlined at validator level (validate.py Pass 4.7 d2): plan must
--   contain at least one chart-emitting block when instruction has
--   visualization keywords. This knowledge entry adds the rule to
--   plan_node's always-on context so the LLM picks the right block on
--   the first attempt.

INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       '「顯示 / show / chart / plot / 趨勢」= 視覺化，必須含 chart block',
       '當 user instruction 出現「顯示 / 畫 / 趨勢 / chart / plot / show / visualize / 圖表」這類關鍵字時，pipeline **必須包含至少一個 chart 區塊**。block_data_view（表格）**不算** — user 想看的是圖（趨勢線、bar、box-plot 等），不是名單。

範例:
  Instruction: 「檢查機台最後一次OOC，並且顯示該SPC charts」

  ❌ 錯誤 plan:
    process_history → unnest → filter(is_ooc=true) → data_view + step_check
    （只列出 OOC chart 名單 — semantically missing「顯示」意圖）

  ✅ 正確 plan:
    process_history(nested=true) → unnest(spc_charts) → filter(is_ooc=true) →
    block_line_chart(x=eventTime, y=value, facet=name, ucl_column=ucl, lcl_column=lcl)
    （+ block_step_check for verdict in skill mode）
    這樣每張 OOC chart 都有自己的 trend panel（facet=small multiples）。

可選的 chart block 對照:
  - 時序趨勢（多 chart 並列）→ block_line_chart with facet=chart_name
  - SPC 嚴格 X̄/R + WECO highlight → block_xbar_r
  - 各 lot 分佈比較 → block_box_plot (x=lotID, y=value)
  - 小幅 drift 偵測 → block_ewma_cusum
  - 分類計數 → block_bar_chart / block_pareto
  - 常態檢定 → block_probability_plot

per-row 重新拉資料畫 N 張 trend:
  - 已有 chart_name 欄位 + 時序 → block_line_chart 的 facet param 切 small multiples（最簡單）
  - 需要再 fan-out MCP 拉細節 → block_mcp_foreach + downstream chart block',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (SELECT 1 FROM agent_knowledge WHERE title = '「顯示 / show / chart / plot / 趨勢」= 視覺化，必須含 chart block');
