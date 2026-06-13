-- V57: planner principle — multi-entity comparison should be ONE source +
-- filter('in'), NOT one fetch phase per entity + union.
--
-- Root cause (spc-multi-tool, 2026-06-13): goal_plan mirrors an enumerated
-- "EQP-01,EQP-02,...,EQP-05" instruction into 5 separate raw_data fetch phases,
-- then needs block_union to merge them. block_union takes only 2 inputs, so 5
-- sources can't be chained cleanly -> 3 process_history nodes left orphan ->
-- failed_structural.
--
-- Verified workable (real executor): process_history(step, no tool_id) ->
-- filter(toolID in [...]) -> unnest(spc_charts) -> filter(name='xbar_chart') ->
-- line_chart(series_field=toolID) produces a valid multi-tool chart, 5 nodes,
-- no union, no orphans.
--
-- Read by goal_plan via list_high_priority_knowledge (priority='high', global,
-- no embedding needed). Flyway is disabled in prod — apply manually with psql.

INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       '多 entity 比較（多機台/lot/step/recipe）→ 單一 source + filter(''in''),不要每個 entity 拆一個 fetch phase',
       '當需求是「比較 / 列出多個機台（或 lot / step / recipe）」且把它們**枚舉**出來
（e.g.「EQP-01,EQP-02,…,EQP-05」）時，這是 PLAN 層的切法原則：

✅ 正解 — plan **一個** data 階段，不是每個 entity 一個：
   source（block_process_history **不設 tool_id**，拿全部）
   → block_filter(column=toolID, operator=''in'', value=[...]) 縮到要的那幾個
   → 之後 transform / chart 用 series_field（或 facet）依該維度分組上色。
   實證可跑（real executor 驗過）：
   process_history(step=STEP_001) → filter(toolID in [EQP-01..05])
   → unnest(spc_charts) → filter(name=''xbar_chart'')
   → line_chart(x=eventTime, y=value, series_field=toolID)  = 5 node、出多機台 chart。

⛔ 禁止 — 每個 entity 拆一個 fetch phase 再 union：
   block_union 只吃 2 個 input，N 個 source 會 chain 不齊 → 留下 orphan node
   → failed_structural。「5 台機台 = 5 個 process_history phase + union」是反模式。

適用於任何「多 entity 比較」（多 tool / 多 lot / 多 step / 多 recipe），不限機台。
核心：別把 instruction 裡枚舉的 entity，一對一變成 N 個 source phase。',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (
  SELECT 1 FROM agent_knowledge
  WHERE title = '多 entity 比較（多機台/lot/step/recipe）→ 單一 source + filter(''in''),不要每個 entity 拆一個 fetch phase'
);
