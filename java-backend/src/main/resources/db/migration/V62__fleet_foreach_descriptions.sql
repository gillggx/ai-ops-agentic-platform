-- AUTO-GENERATED from seed.py (hardening #2, 2026-06-25).
-- Strengthen block_list_objects + block_mcp_foreach descriptions to make the
-- fleet 'all machines' fan-out pattern (list_objects -> mcp_foreach -> unnest)
-- + wiring explicit. UPDATE only (Flyway off in prod -> apply via psql on EC2).
-- Agent reads description from pb_blocks, so this is what makes it take effect.
BEGIN;
UPDATE pb_blocks SET description = $DESC$== What ==
列出 ontology master 物件清單（機台 / 批次 / 站點 / APC 參數 / SPC chart）。
用 `kind` enum 一次選一種，內部 dispatch 到對應 system MCP 並回傳 DataFrame。

== When to use ==
- ✅ 「列出所有機台」「目前有哪些 active lot」「這 20 站的清單」→ kind=tool/lot/step
- ✅ 「APC 參數有哪些」「SPC chart 類型」→ kind=apc/spc
- ✅ **「全廠 / 所有機台 / 每一台」要逐台查資料 → 這是唯一正解**：
     kind='tool' 取機台清單 → 接 block_mcp_foreach 逐台呼叫資料 MCP。
     ⚠ 不要只用 block_process_history 查單台 — 那只會得到一台的資料、漏掉「所有機台」語意。
     完整鏈：list_objects(kind='tool') → mcp_foreach(get_process_info, args_template={'toolID':'$tool_id'})
       → block_unnest（展開每台的事件）→ filter → groupby → ...
- ❌ 查 process 歷史 / 趨勢 → 用 block_process_history
- ❌ 查告警 / 摘要 / 沒在 5 種 kind 內的 list MCP → 用 block_mcp_call

== kind → MCP 對應 ==
- kind='tool' → list_tools  （回傳每台機台 + status / busy_lot）
- kind='lot'  → list_active_lots   （回傳 active lot + current_step / cycle）
- kind='step' → list_steps  （回傳 process flow 的 step 清單）
- kind='apc'  → list_apcs   （回傳 APC 參數 master）
- kind='spc'  → list_spcs   （回傳 SPC chart 類型 master）

== Params ==
kind (string, required) 五擇一: 'tool' | 'lot' | 'step' | 'apc' | 'spc'
args (object, optional)  forward 給對應 MCP 的 query params；多數 list MCP 不需要參數

== Output ==
port: data (dataframe) — 欄位由對應 MCP 的回傳結構決定（每個 object 的 key 變一個 column）。
查欄位細節請看對應 MCP 的 description（從 mcp_definitions 動態讀）。

== Common mistakes ==
⚠ 跟 block_mcp_call 的差異：本 block 只服務 5 種 list 類；其他 MCP 仍走 block_mcp_call
⚠ kind 是 enum 字串（'tool' / 'lot' / ...），不是 MCP 名（'list_tools'）；寫錯 → INVALID_PARAM
⚠ args 是 object（dict），不是 string

== Errors ==
- INVALID_PARAM      : kind 不在 5 種 enum 內，或 args 型別不對
- MCP_NOT_FOUND      : 對應 MCP 沒註冊（需檢查 system MCP seed）
- INVALID_MCP_CONFIG : MCP api_config 缺 endpoint_url
- MCP_HTTP_ERROR     : MCP 回 4xx/5xx
- MCP_UNREACHABLE    : 網路不通
$DESC$
  WHERE name = 'block_list_objects' AND version = '1.0.0';
UPDATE pb_blocks SET description = $DESC$== What ==
對上游 DataFrame 每一 row 呼叫指定 MCP，把 response 合併成新欄位。
Async concurrent — `max_concurrency` 限制同時 in-flight 的 HTTP 請求數（預設 5）。

== When to use ==
- ✅ **全廠 fan-out**：「所有機台 / 全廠 / 各機台」的 SPC/OOC/資料 →
     block_list_objects(kind='tool') → mcp_foreach(mcp_name='get_process_info',
     args_template={'toolID':'$tool_id'}) → block_unnest 展開每台事件 → filter/groupby。
     **接在 block_list_objects 後面就是『所有機台』的正解**（不是改用單台 process_history）。
- ✅ 「每筆 OOC process 查一次 fault context」→ process_history → filter(OOC) → mcp_foreach(get_fdc_context)
- ✅ 「每個 lot 查一次 recipe 詳細設定」→ upstream df → mcp_foreach(get_recipe_detail, '$lotID')
- ✅ enrichment 場景：用上游 row 的某欄當 MCP args，擴充更多資訊
- ❌ 單次 MCP call（不依賴 df 每一 row）→ 用 block_mcp_call（不是 foreach）
- ❌ 要 join 兩個 df → 用 block_join
- ❌ 上游 > 500 rows → 請先 filter / limit，避免 MCP 洪流

== Params ==
mcp_name        (string, required) MCP 名稱（必須註冊在 mcp_definitions 表）
args_template   (object, required) 傳給 MCP 的 args；值可用 `$col_name` 引用當前 row 欄位，e.g. {'targetID':'$lotID'}
result_prefix   (string, opt) 合併時的欄位前綴（避免名稱衝突；e.g. 'apc_'）
max_concurrency (integer, opt, default 5, max 20) 同時 in-flight 的請求數

== Result merging ==
- dict 回傳 → 每 key 轉成欄位（加 prefix）
- list[dict] → 取第 1 筆（1:1 展開）
- 其他 → 存成 `<prefix>raw` JSON 欄位

== Output ==
port: data (dataframe) — 原 df 加上 MCP 回傳的新欄位

== Common mistakes ==
⚠ args_template 裡的 `$col_name` 要精準對上 upstream df 欄位名（case-sensitive）
⚠ 沒給 result_prefix 時欄位可能跟 upstream 重名 → 上游欄位會被覆蓋
⚠ 上游 > 500 rows 直接 TOO_MANY_ROWS；先 filter 或 limit
⚠ 單一 call 失敗會讓整個 block fail（fail-fast，無 per-row skip）

== Errors ==
- MCP_NOT_FOUND     : mcp_name 沒註冊
- TOO_MANY_ROWS     : 上游 > 500 rows
- MCP_UNREACHABLE   : MCP 連不上
- TEMPLATE_MISSING_COL : args_template 裡的 $col 上游找不到

== Performance tips ==
- max_concurrency 開大（10~20）可加速，但別打爆 MCP server
- 先 filter 縮小上游 rows，foreach 成本線性於 row 數
$DESC$
  WHERE name = 'block_mcp_foreach' AND version = '1.0.0';
COMMIT;
