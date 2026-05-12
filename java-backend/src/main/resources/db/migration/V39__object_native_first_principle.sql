-- V39 — Object-native pipeline first principle (2026-05-13).
--
-- Background:
--   Phase 1 of the object-native refactor switched the canonical pipeline
--   data type from "flat table" to "list of arbitrarily nested objects".
--   Path syntax (`a.b` / `a[].b`) is now supported everywhere a column ref
--   is accepted, and three new navigation blocks (block_pluck / block_unnest /
--   block_select) let LLMs traverse hierarchies without JOIN gymnastics.
--
--   This entry codifies the "keep data hierarchical unless aggregation
--   requires flattening" first principle so plan_node retrieves it as
--   context. Lives in agent_knowledge per CLAUDE.md description-driven
--   policy (NOT in system prompts, NOT in block descriptions — those
--   describe the block, not the cross-cutting data principle).

INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       'Pipeline 資料是 object，table 只是視圖',
       'Pipeline 的 canonical 資料型別是「list of 任意巢狀 objects」，不是「flat table」。
Table 視圖是「所有 object 恰好沒有 nested 欄位」的特例 — 由 UI dynamic-flatten 出來，
**不是運算層級的限制**。

設計原則:
  - **資料保持原本 hierarchical shape**。MCP 回 nested 就讓它 nested；別搶著 flatten。
  - **需要時才 flatten/unnest**：
      * 想 filter / step_check **單一 nested 欄位** → 直接 column=''a.b'' (path 文法)
      * 想 group by **array element** → 先 block_unnest 再 block_groupby_agg
      * 想瘦身寬表 / 重組 shape → block_select [{path:..., as:...}]
      * 想抽單欄成 series → block_pluck path=''a.b''
  - **path 文法在所有 column-ref 參數都有效**：
      * filter.column / sort.columns[].column / step_check.column / compute.expression.column
      * groupby_agg.group_by / groupby_agg.agg_column / join.key
      * chart x / y / value_column / category_column / group_by / dimensions
  - **chart 不需要先 flatten**：x=''spc_summary.ooc_count'' chart 會自己 materialize 出 column。
  - **`==` 跟 `=` 是 alias**（SQL / Python 兩派都接受）。

❌ 常見反模式:
  - 為了每次運算先把 nested 全部 flatten 成寬表 → 失去 hierarchy，違反 first principle
  - 用 block_join 自我 join 來「過濾 source by 衍生條件」→ filter + sort 一條 chain 即可
  - 用「壓平 + group by + count」實現一個自然是 list.length 的計數 → 用 block_compute 的 length 或保留 nested array 直接讀

✅ 範例 — 「機台最後一次 process 有幾張 SPC chart 是 OOC」:
  1. block_process_history (tool_id=X, limit=1, order=eventTime desc)
     → 假設 record 形如 { tool_id, event_time, spc_charts: [{name, status}, ...] }
  2a. 路線 A（保持 hierarchical）:
      block_pluck path=''spc_charts[]'' → 一欄是 list-of-objects
      → block_unnest column=''spc_charts'' → 多筆 records
      → block_filter column=''status'' operator=''='' value=''OOC''
      → block_step_check aggregate=''count'' operator=''>='' threshold=2
  2b. 路線 B（單一 path 就解決）:
      如果 record 含 spc_summary.ooc_count 預先計好:
      → block_step_check column=''spc_summary.ooc_count'' operator=''>='' threshold=2
      （兩個 node 就結束）

⚠ Validator final-state 規則:
  - 所有 column-ref 在最終 pipeline state 都必須能在 upstream 找到（path-aware 比對）
  - 任何用了 column-ref 但沒 inbound edge 的 node 會被擋（dangling ref）
  - Op 順序不限，validator 看 final state，不看 add_node / set_param / connect 的先後',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (SELECT 1 FROM agent_knowledge WHERE title = 'Pipeline 資料是 object，table 只是視圖');
