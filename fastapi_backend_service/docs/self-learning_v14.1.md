# Agentic OS — 自我修正驗證地圖 v14.1
> Self-Correction & Validation Map — 全系統各層防守機制完整清單

---

## 目錄
1. [整體架構](#1-整體架構)
2. [Layer 1：沙盒防守（執行前）](#2-layer-1沙盒防守執行前)
3. [Layer 2：MCP Builder 生成流程](#3-layer-2mcp-builder-生成流程)
4. [Layer 3：Skill Builder 生成流程](#4-layer-3skill-builder-生成流程)
5. [Layer 4：沙盒執行層（執行時）](#5-layer-4沙盒執行層執行時)
6. [Layer 5：輸出正規化（執行後）](#6-layer-5輸出正規化執行後)
7. [Layer 6：Agent Orchestrator](#7-layer-6agent-orchestrator)
8. [Layer 7：Copilot Service](#8-layer-7copilot-service)
9. [Layer 8：Context Loader](#9-layer-8context-loader)
10. [Layer 9：跨 Session 記憶學習](#10-layer-9跨-session-記憶學習)
11. [Layer 10：前端防守](#11-layer-10前端防守)
12. [端對端流程圖（Try-Run）](#12-端對端流程圖try-run)
13. [端對端流程圖（Agent 執行 MCP）](#13-端對端流程圖agent-執行-mcp)
14. [端對端流程圖（Copilot Chat）](#14-端對端流程圖copilot-chat)
15. [驗證覆蓋率總表](#15-驗證覆蓋率總表)
16. [已知缺口與未來補強](#16-已知缺口與未來補強)

---

## 1. 整體架構

```
用戶輸入 / LLM 輸出
       │
       ▼
┌──────────────────────────────────────────────┐
│  Layer 1: 靜態掃描  (sandbox_service.py)      │
│  • 13 個禁止 pattern 正則                    │
│  • Import 白名單                             │
│  • Pre-injected library 去重                 │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│  Layer 2–3: Schema Guard  (mcp_builder_service)│
│  • McpTryRunOutputGuard (Pydantic)           │
│  • SkillCodeOutputGuard (靜態結構)            │
│  • llm_retry(max_retries=2)                  │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│  Layer 4: 沙盒執行  (sandbox_service.py)      │
│  • asyncio timeout (10s)                     │
│  • Plotly output rewrite                     │
│  • JSON 序列化正規化                         │
│  • diagnose() 返回鍵驗證                     │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│  Layer 5: 輸出正規化  (mcp_definition_service)│
│  • HTML chart 清理                           │
│  • 無效 chart JSON 丟棄                      │
│  • dataset 型別修復                          │
│  • Auto-chart fallback                       │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│  Layer 6–9: 上層服務防守                     │
│  • Agent Orchestrator: pre-flight, compaction │
│  • Copilot: slot-filling, intent guard       │
│  • Context Loader: soul fallback, RAG filter │
│  • Memory Service: conflict detect, trap     │
└──────────────────────────────────────────────┘
```

---

## 2. Layer 1：沙盒防守（執行前）

**檔案：** `app/services/sandbox_service.py`

### 2.1 靜態代碼掃描 `_static_check()`

| 觸發條件 | 防守規則 | 修正策略 |
|---------|---------|---------|
| 腳本含 `import requests` | 正則 `\bimport\s+(requests?|http|urllib|...)` | 立即拋出 `ValueError`，阻止執行 |
| 腳本含 `import os / sys` | 正則 `\bimport\s+(os|sys|subprocess|...)` | 立即拋出 `ValueError` |
| 腳本含 `open(` | 正則 `\bopen\s*\(` | 立即拋出 `ValueError` |
| 腳本含 `exec(` / `eval(` | 正則 `\b(exec|eval)\s*\(` | 立即拋出 `ValueError` |

**共 13 個禁止模式**，任何一個匹配即阻止執行，不需等到 runtime。

### 2.2 Import 白名單 `_safe_import()`

```
允許：json, math, statistics, re, datetime, collections, itertools,
      functools, operator, pandas, numpy, plotly, matplotlib, scipy,
      sklearn, 以及所有 CPython 內部模組（_strptime, _json 等）
拒絕：所有其他模組 → ImportError，列出允許清單
```

### 2.3 Pre-injected Library 去重 `_strip_preinjected_imports()`

| 問題 | 修正 |
|------|------|
| 腳本重複 `import plotly` 等已注入庫 | 正則替換為 `# [auto-removed: pre-injected]`，防止版本衝突 |

---

## 3. Layer 2：MCP Builder 生成流程

**檔案：** `app/services/mcp_builder_service.py`

### 3.1 LLM Output 結構驗證 `McpTryRunOutputGuard` (Pydantic)

```python
class McpTryRunOutputGuard(BaseModel):
    processing_script: str   # 必須含 "def process"
    output_schema: Dict      # 必須有 "fields" 陣列
    ui_render_config: Dict = {}
    input_definition: Dict = {}
    summary: str = ""
```

| 違規 | 錯誤消息 | 動作 |
|-----|---------|------|
| `processing_script` 無 `def process` | "processing_script 缺少 def process(data, params) 函式" | 拋出 ValidationError |
| `output_schema` 無 `fields` | "output_schema 必須有 'fields' 陣列" | 拋出 ValidationError |

### 3.2 LLM 重試迴圈 `llm_retry()`

```
嘗試 1: generate_for_try_run(error_context=None)
        ↓ McpTryRunOutputGuard 驗證
        ↓ [失敗] → error_context = str(ValidationError)
嘗試 2: generate_for_try_run(error_context=<錯誤詳情>)
        ↓ Prompt 附加：⚠️ 上一次生成的輸出驗證失敗，請修正...
        ↓ [失敗] → error_context = str(ValidationError2)
嘗試 3: generate_for_try_run(error_context=<錯誤詳情2>)
        ↓ [仍失敗] → 拋出 ValueError("LLM retry 失敗（共 3 次）：...")
```

**最大嘗試次數：3（初始 + 2 次 retry）**

### 3.3 圖表生成鐵律（System Prompt 層面）

| 意圖關鍵字 | 強制結果 |
|-----------|---------|
| 「輸出為列表」/ 「flat list」 | `ui_render.type="table"`, `charts=[]`, `chart_data=null` |
| 未出現「多張圖」 | 最多生成 1 張主圖 |
| 未明確要求衍生統計圖 | 禁止生成 count by X、summary bar 等 |

### 3.4 JSON 萃取容錯 `_extract_json()`

```
策略 1: 移除 markdown fence（```json...```）後解析
策略 2: 找第一個 { 後解析
策略 3: json.JSONDecoder.raw_decode()（只取第一個有效 JSON）
降級:  返回 {"intent": "general_chat", "is_ready": False}
```

---

## 4. Layer 3：Skill Builder 生成流程

**檔案：** `app/services/mcp_builder_service.py`

### 4.1 診斷代碼結構驗證 `SkillCodeOutputGuard`

```
必須含：def diagnose
回傳 dict 必須含："status", "diagnosis_message", "problem_object"
```

| 違規 | 錯誤消息 |
|-----|---------|
| 無 `def diagnose` | "診斷代碼必須包含 def diagnose(data) 函式" |
| 回傳缺 `status` | "diagnose() 回傳值必須包含 status/diagnosis_message/problem_object 鍵" |
| 回傳缺 `diagnosis_message` | 同上 |
| 回傳缺 `problem_object` | 同上 |

### 4.2 problem_object 型別修正

```python
# generate_code_diagnosis() 回傳後：
problem_object = raw_result.get("problem_object", {})
if not isinstance(problem_object, dict):
    logger.warning("problem_object 是 %s，正規化為 {}", type(problem_object).__name__)
    problem_object = {}
```

**觸發**：LLM 返回 `problem_object` 為字串或列表時自動修正。

### 4.3 Skill LLM 重試迴圈

與 MCP 相同的 `llm_retry(fn, SkillCodeOutputGuard.validate, max_retries=2)` 模式。

---

## 5. Layer 4：沙盒執行層（執行時）

**檔案：** `app/services/sandbox_service.py`

### 5.1 Plotly Output 自動改寫 `_rewrite_plotly_output()`

| LLM 生成錯誤寫法 | 自動修正為 | 原因 |
|----------------|-----------|------|
| `fig.to_html(...)` | `fig.to_json()` | 後者使用 Plotly encoder，處理 Timestamp/numpy |
| `fig.show()` | `# [removed: fig.show()]` | 沙盒中無 display 環境 |

日誌：`logger.warning("Rewrote Plotly output call")`

### 5.2 JSON 序列化正規化 `_make_json_serializable()`（遞迴）

| 類型 | 轉換規則 |
|-----|---------|
| `pandas.Timestamp` | `.isoformat()` |
| `pandas.NaT` / `pandas.NA` | `None` |
| `datetime.datetime` | `.isoformat()` |
| `datetime.date` | `.isoformat()` |
| `numpy.integer` / `numpy.floating` | `.item()` |
| `numpy.ndarray` | `.tolist()` |
| `dict` | 遞迴處理所有 value |
| `list` / `tuple` | 遞迴處理所有 element |

### 5.3 沙盒執行超時

```python
await asyncio.wait_for(loop.run_in_executor(None, _run_sync), timeout=10.0)
```

| 觸發 | 回應 |
|-----|------|
| 執行 > 10 秒 | `TimeoutError`："沙盒超時（10s），請簡化處理邏輯" |

### 5.4 diagnose() 返回結構驗證 `_run_diagnose_sync()`

```python
required_keys = {"status", "diagnosis_message", "problem_object"}
missing = required_keys - set(result.keys())
if missing:
    raise ValueError(f"diagnose() 缺少必需返回鍵：{missing}")
```

---

## 6. Layer 5：輸出正規化（執行後）

**檔案：** `app/services/mcp_definition_service.py`

### 6.1 `_normalize_output()` — 三層清理

**第 1 層：HTML 圖表清理**

```
chart_data 是 HTML 字串（含 "<html" 或 "<div"）
  → 刪除 chart_data，設為 None，logger.warning
charts[] 陣列中任何 HTML 字串
  → 過濾移除，logger.warning
```

**第 2 層：無效 chart JSON 丟棄**

```python
# P2 Fix（v14.2）
valid = []
for c in clean:
    try:
        json.loads(c)
        valid.append(c)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("chart entry 非合法 JSON，已丟棄")
ui["charts"] = valid
```

**第 3 層：dataset 型別修復**

```python
# P3 Fix（v14.2）
dataset = output_data.get("dataset")
if not isinstance(dataset, list):
    logger.warning("dataset 是 %s（非 list），重設為 []", type(dataset).__name__)
    output_data["dataset"] = []
```

### 6.2 Auto-Chart Fallback `_auto_chart()`

```
若 ui_render.type != "table" AND charts = [] AND dataset 非空
  → 嘗試從 dataset 用 pandas + plotly 自動生成圖表
  → 若成功：注入圖表 JSON
  → 若失敗：返回 None，前端顯示表格視圖
```

### 6.3 沙盒自動重試迴圈 `try_run()`

```
嘗試 1: execute_script(original_script, sample_data)
        ↓ [失敗]
        classify_error(str(exc))
        → MISSING_COLUMN / TYPE_MISMATCH / IMPORT_ERROR / EMPTY_DATA / SYNTAX_ERROR / LOGIC_ERROR
        呼叫 generate_for_try_run(error_context=f"[{label}] 上次腳本失敗：{error_msg}")
        ↓ LLM 生成修正版腳本
嘗試 2: execute_script(fixed_script, sample_data)
        ↓ [成功] → 繼續流程
        ↓ [失敗] → 呼叫 _analyze_sandbox_error() → 返回三部分分析報告
```

**六個 classify_error 標籤：**

| 標籤 | 觸發條件 | 給 LLM 的提示意義 |
|-----|---------|----------------|
| `MISSING_COLUMN` | KeyError 或 "column not found" | 欄位名稱錯誤，請檢查 DS schema |
| `TYPE_MISMATCH` | TypeError / ValueError | 型別轉換問題 |
| `IMPORT_ERROR` | ModuleNotFoundError | 使用了未允許的 module |
| `EMPTY_DATA` | NoneType / empty iterable | 資料集為空或 None |
| `SYNTAX_ERROR` | SyntaxError / IndentationError | 代碼縮排或語法錯誤 |
| `LOGIC_ERROR` | 其他所有 | 邏輯問題 |

---

## 7. Layer 6：Agent Orchestrator

**檔案：** `app/services/agent_orchestrator.py`

### 7.1 Pre-flight 參數驗證 `_preflight_validate()`

| 缺失項目 | 錯誤碼 | 自動提示 |
|---------|-------|---------|
| `mcp_id` 未提供 | `MISSING_MCP_ID` | "請先呼叫 list_mcps 取得 MCP 清單" |
| MCP 不存在 | `MCP_NOT_FOUND` | "MCP #{id} 不存在，請確認 ID" |
| 缺少必填參數 | `MISSING_PARAMS` | "缺少：{param1}, {param2}" |
| `skill_id` 未提供 | `MISSING_SKILL_ID` | 同上邏輯 |
| Skill 不存在 | `SKILL_NOT_FOUND` | 同上邏輯 |

**阻止執行**，不讓 null 參數傳入工具。

### 7.2 History Token 管理

| 機制 | 觸發 | 處理 |
|-----|-----|------|
| `_sanitize_history()` | tool_result > 6000 字 | 移除 `output_data`/`ui_render_payload`/`_raw_dataset`；若非 JSON 則截斷 |
| `_clean_history_boundary()` | 孤立的 tool_result | 刪除孤立 tool_result 與其前一條 assistant 消息 |
| `_compact_history()` | 累積 token > 60k | 保留最近 4 條完整；舊消息歸檔為 `<archive_summary>`（最多 20 行 × 200 字） |
| `_trim_for_llm()` | 每次 LLM 呼叫前 | 移除 UI payload；list 工具限 12 條；skill 結果只保留 `status`/`llm_readable_data` |

### 7.3 工具錯誤分類與 Trap `_derive_fix_rule()`

```
MISSING_MCP_ID  → Trap: "先呼叫 list_mcps"
MCP_NOT_FOUND   → Trap: "MCP #{id} 不存在"
MISSING_PARAMS  → Trap: "缺少參數：{list}"
SKILL_NOT_FOUND → Trap: "Skill #{id} 不存在"
APPROVAL_REJECTED → 不寫 Trap（用戶主動拒絕，非系統問題）
其他（error > 20 字，非超時）→ 寫入 Trap Memory
```

---

## 8. Layer 7：Copilot Service

**檔案：** `app/services/copilot_service.py`

### 8.1 必填參數推斷（四層優先序）

```
優先序 1: skill.param_mappings 顯式映射
優先序 2: MCP input_definition（非 DataSubject 源）
優先序 3: DataSubject input_schema
優先序 4: 空集合
```

每個 MCP 最終確定的必填參數清單都記錄在 `logger.debug()`。

### 8.2 Slot Filling 缺漏偵測

```python
still_missing = [f for f in required_fields if f not in merged_params]
if still_missing:
    yield question_sse(f"請提供 {', '.join(still_missing)}")
    return  # 不執行工具
```

**保證**：不向工具傳遞 null/缺失的必填參數。

### 8.3 Intent 解析守門（System Prompt）

```
⚠️ 鐵律：若使用者 prompt 未明確提供所有 required parameters 的值，
你絕對不得設 is_ready=true。
你必須設 is_ready=false 並向用戶要求補充資訊。
禁止捏造預設值或假設預設值。
```

### 8.4 五層 Skill 執行驗證

| 層 | 驗證項 | 失敗處理 |
|----|-------|---------|
| 1 | Skill 是否存在 | 返回 error SSE |
| 2 | MCP 是否存在（`mcp_id`） | 返回 error SSE |
| 3 | System MCP / DataSubject 是否存在 | 返回 error SSE |
| 4 | `processing_script` 非空 | 返回 error SSE |
| 5 | `generated_code`（診斷代碼）非空 | 返回 error SSE |

### 8.5 Output Status 正規化

```python
status = str(raw.get("status", "UNKNOWN")).upper()
if status not in {"NORMAL", "ABNORMAL"}:
    status = "ABNORMAL"  # 未知狀態保守歸為 ABNORMAL
```

---

## 9. Layer 8：Context Loader

**檔案：** `app/services/context_loader.py`

### 9.1 Soul Prompt 三層回退 `_load_soul()`

```
層 1: 用戶自訂 soul_override
層 2: 全局 SystemParameter（DB 配置）
層 3: _DEFAULT_SOUL（硬編碼預設值）
```

**保證**：Soul prompt 永遠非空。

### 9.2 Memory 搜尋與 Metadata 回退

```
主策略: WHERE task_type='{x}' AND data_subject='{y}' → 向量相似度排序
若主池 < top_k: 補充無 Metadata 標籤的舊記憶（二階段補充）
若無 query 且無 task_context: 跳過 RAG，返回空列表 + {"strategy": "skipped"}
```

---

## 10. Layer 9：跨 Session 記憶學習

**檔案：** `app/services/agent_memory_service.py`

### 10.1 三類記憶寫入

| 記憶類型 | 函式 | 格式前綴 | Metadata 鍵 | 觸發時機 |
|---------|------|---------|------------|---------|
| **Trap（負面教材）** | `write_trap()` | `[Trap]` | `tool_name` | 工具執行失敗 |
| **Preference（偏好）** | `write_preference()` | `[使用者偏好]` | `task_type`, `data_subject` | 用戶 HITL 修改參數 |
| **DS Schema 教訓** | `write_ds_schema_lesson()` | `[DS_Schema]` | `task_type=mcp_draft`, `data_subject=ds_name` | Try-Run 成功後（確認正確欄位） |

### 10.2 Trap 範例格式

```
[Trap] 2026-03-10T14:23:01 | Tool: draw_spc_chart
錯誤：Missing required field: sigma_level（截斷至 200 字）
Rule: 下次呼叫此工具時必須提供 sigma_level
```

### 10.3 DS Schema 教訓範例格式

```
[DS_Schema] 2026-03-10T14:23:01 | DS=SPC_OOC_Etch_CD
正確欄位: lot_id, tool_id, operation_number, timestamp, cd_value, sigma_level
錯誤猜測（若有）: lot_number, machine_id
```

### 10.4 診斷衝突偵測 `write_diagnosis_with_conflict_check()`

```
搜尋現有同 Skill + 同 target 記憶
  → 若找到衝突（NORMAL ↔ ABNORMAL 相反）：UPDATE 舊記憶而非 ADD
  → 若無衝突：ADD 新記憶
```

**衝突啟發式**（SQLite，無向量）：
- 令牌重疊率 < 0.4 → 不相關，跳過
- 重疊率 ≥ 0.4 且 status 相反 → 判定衝突

### 10.5 Memory 搜尋關鍵字保護

```python
tokens = [t for t in query.split() if len(t) >= 2]
if not tokens:
    return self._get_latest(user_id, top_k)  # 回退最新記憶
```

---

## 11. Layer 10：前端防守

**檔案：** `static/builder.js`, `static/app.js`

### 11.1 JWT 記憶體存儲（非 localStorage）

```javascript
let _token = null;  // memory-only：refresh 自動清除 → 強制 login
```

**效果**：瀏覽器重新整理即清除 token，用戶必須重新登入。

### 11.2 Run 按鈕前置驗證

```
按下 Run 前：
  - mcp_id 是否已選擇？
  - 所有 required DS input 是否填寫？
  - 若否：顯示 alert 並阻止 API 呼叫
```

### 11.3 `_nbRenderDataGrid` 非陣列保護

```javascript
if (!Array.isArray(rows)) {
    console.warn("DataGrid: rows 非陣列", rows);
    return '<p class="text-red-400">無法渲染：資料格式錯誤</p>';
}
```

---

## 12. 端對端流程圖（Try-Run）

```
用戶填入加工意圖 + DS Sample
        │
        ▼
[mcp_builder_service]
generate_for_try_run()
  ├─ llm_retry (max 3 次)
  │    ├─ 嘗試 1: LLM 生成 JSON
  │    │    └─ McpTryRunOutputGuard 驗證
  │    │         ├─ [OK] → 繼續
  │    │         └─ [失敗] → 附加錯誤上下文
  │    └─ 嘗試 2/3: LLM 重新生成（含錯誤詳情）
        │
        ▼
[sandbox_service]
  1. _static_check()    ← 禁止模式掃描
  2. _strip_preinjected_imports()
  3. _rewrite_plotly_output()
        │
        ▼
[mcp_definition_service.try_run()]
execute_script 嘗試 1
  ├─ [OK] → 繼續
  └─ [失敗] → classify_error()
              → LLM 修正腳本
              → execute_script 嘗試 2
                  ├─ [OK] → 繼續
                  └─ [失敗] → _analyze_sandbox_error()
                              → 返回三部分錯誤報告
        │
        ▼
[sandbox_service]
_make_json_serializable()   ← Timestamp/numpy 轉換
        │
        ▼
[mcp_definition_service]
_normalize_output()
  1. HTML chart 清理
  2. 無效 chart JSON 丟棄  (P2)
  3. dataset 型別修復     (P3)
  4. Auto-chart fallback
        │
        ▼
[agent_memory_service]
write_ds_schema_lesson()    ← 記住正確欄位（供下次 Try-Run 使用）
        │
        ▼
前端渲染
```

---

## 13. 端對端流程圖（Agent 執行 MCP）

```
用戶發送任務到 Agent
        │
        ▼
[context_loader]
Stage 1: _load_soul()      ← 三層回退保證非空
         RAG 搜尋記憶      ← Metadata 預過濾
         注入 [Trap]/[DS_Schema]/[使用者偏好]
        │
        ▼
[agent_orchestrator]
Stage 2: LLM 規劃
  _preflight_validate()    ← 驗證 mcp_id + 必填參數
  └─ [缺失] → 返回 MISSING_PARAMS，Agent 呼叫 list_mcps
        │
        ▼
[tool_dispatcher]
Stage 3: _call_api()
  └─ HTTP 失敗/JSON 解析失敗 → 結構化錯誤，不拋出
        │
        ▼
[sandbox_service + mcp_definition_service]
  (同 Try-Run 流程，靜態掃描 → 執行 → 正規化)
        │
        ▼
[agent_orchestrator]
_trim_for_llm()            ← 移除大型 UI payload
Stage 4: LLM 反思
        │
        ▼
[agent_orchestrator]
Stage 5: _compact_history() （若 token > 60k）
         _derive_fix_rule()
[agent_memory_service]
write_trap()               ← 若有錯誤，記住教訓
        │
        ▼
回覆用戶
```

---

## 14. 端對端流程圖（Copilot Chat）

```
用戶輸入自然語言
        │
        ▼
[copilot_service]
_parse_intent()
  System Prompt: 「缺少參數時 is_ready=false 鐵律」
        │
        ▼
參數推斷（四層優先序）
  param_mappings → input_definition → input_schema → 空
        │
        ▼
still_missing = required - provided
  ├─ [有缺漏] → question SSE → 等待用戶補充
  └─ [齊全] → 繼續
        │
        ▼
execute_mcp() / execute_skill()
  五層 Skill 驗證（存在性 + 代碼存在性）
  └─ [失敗] → error SSE
        │
        ▼
_normalize_output()        ← HTML/JSON/dataset 正規化
_auto_chart()              ← 無圖表時自動生成
        │
        ▼
status 正規化
  未知 status → "ABNORMAL"（保守策略）
        │
        ▼
回覆用戶
```

---

## 15. 驗證覆蓋率總表

| # | 機制 | 檔案 | 層級 | 觸發條件 | 修正策略 | 是否記憶學習 |
|---|-----|------|-----|---------|---------|------------|
| 1 | 靜態代碼掃描 | sandbox_service | L1 | 禁止 import/操作 | 拋出 ValueError，阻止執行 | ✗ |
| 2 | Import 白名單 | sandbox_service | L1 | 非白名單模組 | ImportError + 列出允許清單 | ✗ |
| 3 | Pre-injected 去重 | sandbox_service | L1 | 重複 import 已注入庫 | 正則替換為 # 注釋 | ✗ |
| 4 | McpTryRunOutputGuard | mcp_builder_service | L2 | LLM output 結構不完整 | Pydantic 驗證 → llm_retry | ✗ |
| 5 | LLM 重試迴圈 | mcp_builder_service | L2 | Schema Guard 驗證失敗 | 附加錯誤詳情，最多 3 次 | ✗ |
| 6 | 圖表生成鐵律 | mcp_builder_service | L2 | LLM 自行添加圖表 | System Prompt 層面防守 | ✗ |
| 7 | JSON 萃取容錯 | mcp_builder_service | L2 | Markdown fence/尾隨文字 | 三策略降級 | ✗ |
| 8 | SkillCodeOutputGuard | mcp_builder_service | L3 | 診斷函式結構錯誤 | 靜態檢查 → llm_retry | ✗ |
| 9 | problem_object 型別修正 | mcp_builder_service | L3 | problem_object 非 dict | 強制設為 {} | ✗ |
| 10 | Plotly Output 改寫 | sandbox_service | L4 | fig.to_html() 錯誤 | 正則替換為 json.dumps(fig.to_dict()) | ✗ |
| 11 | JSON 序列化正規化 | sandbox_service | L4 | Timestamp/numpy 類型 | 遞迴轉換為 JSON 相容型別 | ✗ |
| 12 | 沙盒執行超時 | sandbox_service | L4 | 執行 > 10 秒 | TimeoutError，提示簡化邏輯 | ✗ |
| 13 | diagnose() 返回驗證 | sandbox_service | L4 | 缺少 3 個必需鍵 | ValueError + 詳述缺失項 | ✗ |
| 14 | HTML chart 清理 | mcp_definition_service | L5 | chart_data 為 HTML | 丟棄 chart_data | ✗ |
| 15 | 無效 chart JSON 丟棄 | mcp_definition_service | L5 | chart 非合法 JSON | json.loads 驗證，不通過則丟棄 | ✗ |
| 16 | dataset 型別修復 | mcp_definition_service | L5 | dataset 非 list | 強制設為 [] | ✗ |
| 17 | Auto-chart Fallback | mcp_definition_service | L5 | 無圖表但有資料集 | 自動從 dataset 生成圖表 | ✗ |
| 18 | 沙盒自動重試 | mcp_definition_service | L5 | 沙盒第一次失敗 | classify_error → LLM 修正 → 重試 | ✗ |
| 19 | Pre-flight 驗證 | agent_orchestrator | L6 | 缺少 ID/必填參數 | 結構化錯誤 + 提示補救動作 | ✗ |
| 20 | History 截斷 | agent_orchestrator | L6 | tool_result > 6000 字 | 移除大欄位，降級截斷 | ✗ |
| 21 | History Compaction | agent_orchestrator | L6 | token > 60k | 歸檔老消息，保留最近 4 條 | ✗ |
| 22 | LLM 有向去肥胖 | agent_orchestrator | L6 | UI payload 污染 | 移除 output_data/ui_render | ✗ |
| 23 | Slot Filling | copilot_service | L7 | 必填參數缺漏 | question SSE，阻止工具調用 | ✗ |
| 24 | Intent 解析守門 | copilot_service | L7 | LLM 跳過參數驗證 | System Prompt 鐵律 | ✗ |
| 25 | 五層 Skill 驗證 | copilot_service | L7 | Skill/MCP/代碼不存在 | error SSE | ✗ |
| 26 | Status 正規化 | copilot_service | L7 | 未知 status 值 | 保守歸為 ABNORMAL | ✗ |
| 27 | Soul 三層回退 | context_loader | L8 | Soul prompt 缺失 | override → DB → 預設值 | ✗ |
| 28 | Memory 過濾回退 | context_loader | L8 | 過濾結果為空 | 跳過 RAG + 空列表 | ✗ |
| 29 | Trap 記憶 | agent_memory_service | L9 | 工具執行失敗 | 記住教訓 + tool_name Metadata | ✓ |
| 30 | Preference 記憶 | agent_memory_service | L9 | 用戶 HITL 修改 | 記住偏好 + task_type Metadata | ✓ |
| 31 | DS Schema 教訓 | agent_memory_service | L9 | Try-Run 成功後 | 記住正確欄位 + mcp_draft Metadata | ✓ |
| 32 | 衝突偵測 | agent_memory_service | L9 | 診斷結果矛盾 | UPDATE 舊記憶，不新增 | ✓ |
| 33 | JWT memory-only | app.js | L10 | 頁面 refresh | token 清除，強制 login | ✗ |
| 34 | DataGrid 非陣列保護 | builder.js | L10 | rows 非陣列 | 顯示格式錯誤提示 | ✗ |

**合計：34 個驗證機制，其中 4 個具備跨 Session 記憶學習能力**

---

## 16. 已知缺口與未來補強

| # | 缺口描述 | 優先級 | 建議補強 |
|---|---------|-------|---------|
| P1 | `write_ds_schema_lesson()` 已實作但未在 `try_run()` 成功路徑觸發 | 高 | 在 `try_run()` 成功後注入 `agent_memory_service.write_ds_schema_lesson()` |
| P2 | Stage 1 未預載 `[DS_Schema]` 記憶注入 MCP Try-Run Prompt | 高 | `context_loader.build()` 支援 `task_type="mcp_draft"` 過濾，注入至 system prompt |
| P3 | `draft_mcp` 的 `name` 和 `processing_intent` 從不驗證 | 中 | 在 `agent_draft_router.py` publish 前加格式驗證 |
| P4 | `_is_contradictory()` 使用令牌重疊啟發式（非向量） | 中 | 上 PostgreSQL + pgvector 後改為向量相似度判斷 |
| P5 | Copilot Auto-Chart 失敗後無日誌說明為何失敗 | 低 | `_auto_chart()` 增加具體 exception log |
| P6 | `_compact_history()` 壓縮摘要未使用 LLM（純截斷） | 低 | 可選：對 60k+ session 使用 LLM 生成語義摘要（成本 vs 品質取捨） |

---

*文件生成時間：2026-03-10*
*覆蓋版本：v14.2 Self-Healing Builder*
*下次更新：引入 pgvector 或完成 P1/P2 DS Schema 注入時*
