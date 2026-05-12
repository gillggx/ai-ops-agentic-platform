-- V42 — 2026-05-13: agent_knowledge update for nested-by-default.
--
-- Replaces the V39 entry with the new "三步式 SPC pipeline" pattern that
-- reflects nested-default + the block_unnest workflow.

UPDATE agent_knowledge
SET body = 'Pipeline 的 canonical 資料型別是「list of 任意巢狀 objects」，不是「flat table」。
Table 視圖是「所有 object 恰好沒有 nested 欄位」的特例 — 由 UI dynamic-flatten 出來，
**不是運算層級的限制**。

設計原則:
  - **資料保持原本 hierarchical shape**。block_process_history 預設 nested=true，
    回傳含 spc_charts[] (array of {name,value,ucl,lcl,is_ooc,status}) + spc_summary 預算值。
  - **需要時才 flatten/unnest**：
      * 想 filter / step_check **單一 nested 欄位** → 直接 column=''a.b'' (path 文法)
      * 想 group by **array element** → 先 block_unnest 再 block_groupby_agg
      * 想瘦身寬表 / 重組 shape → block_select [{path:..., as:...}]
      * 想抽單欄成 series → block_pluck path=''a.b''
  - **path 文法在所有 column-ref 參數都有效**（dot 跟 [] 都認）。
  - **`==` 跟 `=` 是 alias**（SQL / Python 兩派都接受）。

⭐ **SPC chart blocks 自動相容 nested**：block_xbar_r / block_imr / block_ewma_cusum /
   block_weco_rules / block_consecutive_rule 都在入口 ensure_flat_spc，**不用為它們設
   nested=false**。它們會自動把 spc_charts[] 還原成 spc_<chart>_<field> 扁平欄位再算。

✅ 三步式 SPC 分析 pipeline（推薦範例）:
  1. block_process_history (tool_id=X, step=Y, time_range=Z)  ← nested 預設 true
  2. block_unnest (column=''spc_charts'')      ← 每張 chart 一筆 row，欄位含 name/value/ucl/lcl/is_ooc/status
  3. block_filter (column=''name'', operator=''='', value=''xbar_chart'')   ← 想看 xbar 就 filter chart name
  4. 接下游 chart block 或 block_step_check / block_threshold

✅ 「機台最後一次 process 有幾張 SPC chart OOC」(2-3 個 node):
  - block_process_history (tool_id=X, limit=1)
  - block_threshold (column=''spc_summary.ooc_count'', bound_type=''lower'', lower_bound=2)
  - block_alert (triggered 從 threshold.triggered, evidence 從 threshold.evidence)

❌ DEPRECATED — 不要用:
  - block_spc_long_form：被 block_unnest(column=''spc_charts'') 取代
  - block_count_rows：被 block_step_check(aggregate=''count'') 或 path 引用取代

❌ 常見反模式:
  - 為了每次運算先把 nested 全部 flatten 成寬表 → 失去 hierarchy，違反 first principle
  - 用 block_join 自我 join 來「過濾 source by 衍生條件」→ filter + sort 一條 chain 即可
  - 用「壓平 + group by + count」實現一個自然是 list.length 的計數 → 用 block_compute 的 length 或保留 nested array 直接讀

⚠ Validator final-state 規則:
  - 所有 column-ref 在最終 pipeline state 都必須能在 upstream 找到（path-aware 比對）
  - 任何用了 column-ref 但沒 inbound edge 的 node 會被擋（dangling ref）
  - Op 順序不限，validator 看 final state，不看 add_node / set_param / connect 的先後',
    updated_at = now()
WHERE title = 'Pipeline 資料是 object，table 只是視圖';
