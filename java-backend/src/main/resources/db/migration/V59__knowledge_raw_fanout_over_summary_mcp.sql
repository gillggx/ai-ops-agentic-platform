-- V59: steer multi-entity OOC aggregation toward RAW fan-out, not the
-- pre-aggregated summary MCP.
--
-- Why (spc-ooc, 2026-06-14): with V58 execute-layer injection on, id 36's
-- Pattern B steered the agent to block_mcp_call(get_process_summary). That
-- dropped p1 (19 -> ~5) but shifted churn into p2 (6 -> 12-29) because
-- get_process_summary's by_tool output has a description<->runtime column
-- mismatch (doc promises ooc_count, runtime exposes count), so the agent
-- thrashes finding the sort column. Decision: prefer computing from raw
-- events (get_process_info + foreach + groupby) — the data path is explicit
-- and auditable; a summary endpoint is a black box whose field semantics may
-- not match the need. Pattern B removed from id 36/37; raw fan-out is the only
-- documented path. get_process_summary stays registered+active but is no
-- longer steered to.
--
-- Principle, not case rule (CLAUDE.md §0): "prefer raw fan-out over a
-- pre-aggregated summary MCP" generalises across any count/ranking query.
--
-- Body changed -> embedding cleared so the sidecar's embedding_backfill
-- (30s loop) re-embeds; until then the row is absent from RAG (search
-- filters embedding IS NOT NULL). Flyway is DISABLED in prod — apply via psql.
-- ids are prod-current (2026-06-14).

UPDATE agent_knowledge SET body = $KB36$當 user 問「N 個機台今天 OOC」「全廠 OOC 排名」「各站點 OOC 分布」「比較多台機台的數據」「哪些機台...」「所有機台...」等跨多 entity 的查詢 / 聚合時：

[注意] 關鍵限制：block_process_history 的 tool_id / lot_id / step 三擇一必填（runtime enforced）。無法用 tool_id=None / 'ALL' / '*' 拉全廠。plan 不能把「取得所有機台資料」當成一個 raw_data phase 用 process_history 解決。

[正解] raw fan-out（從 raw 事件自己聚合）：
1. raw_data phase 1: block_list_objects(kind='tool') 取機台清單
2. raw_data phase 2: block_mcp_foreach(mcp_name='get_process_info',
   args_template={'tool_id': '$tool_id', 'time_range': '24h', 'object_name': 'SPC'}) 對每台跑
3. transform phase: block_union 合併 -> block_filter(OOC) -> block_groupby_agg(toolID, count) -> block_sort(desc)
4. 呈現 phase: 排名用 block_bar_chart 或 block_data_view（出表）

[原則] 優先從 raw 事件自己算（get_process_info + foreach + groupby），不要依賴預先聚合的 summary MCP（如 get_process_summary）。raw fan-out 的資料路徑是顯式、可稽核的；summary endpoint 是黑箱，欄位語義不一定跟需求對得上。即使只要 count / 排名，也走這條 raw 路。

[不要]：
- 為了 plan「一個 raw_data phase」而 hard-code tool_id='EQP-01' 拉單台 — 偏離 user 多機台需求
- 用 tool_id={'tools': '*'} 或 tool_id='ALL' — 都會被 type / value 驗證拒
- 把對的 list_objects / mcp_foreach 架構建好後又 remove — 看到 verifier reject 才砍，不要預期性砍

[ok] plan「raw_data」phase 的可接受輸出：list_objects 機台清單、mcp_foreach 逐台 get_process_info 結果 都算 raw_data。$KB36$,
    updated_at = now()
 WHERE id = 36;

UPDATE agent_knowledge SET body = $KB37$當 user 列出 N 個具名機台（例如「EQP-01 EQP-02 EQP-03」「比較 EQP-01 跟 EQP-02」）時，pipeline 設計：

[不要] 絕對禁止 tool_id='ALL' / 'all' / '*' / None — block_process_history runtime 雖然 simulator 可能容錯，但這是 undefined behavior，拿到的資料 row count 不固定、不是「真正 N 台的合集」。

[正解] N x process_history + block_union（從 raw 事件自己算）：
1. raw_data phase 1: block_process_history(tool_id='EQP-01', time_range=...) -> df1
2. raw_data phase 2: block_process_history(tool_id='EQP-02', time_range=...) -> df2
3. (再加一個 block_process_history per tool)
4. transform phase: block_union(on_schema_mismatch='outer') 合 N 個 df
5. 接下游 unnest / filter / groupby / sort / chart

[原則] 優先從 raw 事件自己算，不要依賴預先聚合的 summary MCP（get_process_summary）。raw 路徑顯式可稽核；summary endpoint 是黑箱、欄位語義不一定對得上。即使只要 count / 排名也走 raw。

[注意] 「所有機台」(N 不明) 不是這條 entry 的範圍（看 id=36）— 那條走 list_objects + mcp_foreach 逐台 get_process_info。$KB37$,
    updated_at = now()
 WHERE id = 37;

-- Force re-embed (body changed). embedding_backfill (30s) repopulates.
UPDATE agent_knowledge SET embedding = NULL WHERE id IN (36, 37);
