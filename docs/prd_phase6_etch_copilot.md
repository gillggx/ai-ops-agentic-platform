# Phase 6 終極版：半導體蝕刻製程診斷 Agent 與 LLM 智能建構器

## 1. 產品升級目標 (Product Vision)
將系統全面轉型為專為半導體晶圓廠 (Fab) 打造的 AI 診斷平台。
1. **執行期 (Runtime)**：以「蝕刻製程 SPC OOC」為核心場景，Agent 具備資深製程工程師 (PE) 的排障思維。
2. **設計期 (Design-time)**：導入 LLM 作為 UX 核心元件，提供自動參數映射 (Auto-Mapping)、邏輯防呆 (Validation) 與智能提示 (Suggestion)，徹底消滅「空白畫布綜合症」。

---

## 2. 領域資料模型 (Domain Ontology)
廢除所有舊有 IT 測試工具 (如 CPU/Network)，全面採用以下半導體規格。**注意：所有的 `description` 為強制必填，此為 LLM 智能映射與提示的唯一依據。**

### 2.1 核心事件 (Event): `SPC_OOC_Etch_CD`
- `lot_id` (string): 發生異常的產品批號。
- `eqp_id` (string): 處理該批號的蝕刻機台代碼。
- `chamber_id` (string): 機台內實際執行製程的反應室代碼。
- `recipe_name` (string): 該批號使用的製程配方名稱。
- `rule_violated` (string): 觸發的 SPC 規則 (例如：超出 3 sigma、連續 9 點在同側)。
- `consecutive_ooc_count` (integer): 該機台/配方近期連續發生 OOC 的次數。
- `control_limit_type` (string): 觸發的是 UCL (上限) 還是 LCL (下限)。

### 2.2 診斷工具 (MCP Tools)
1. **`mcp_check_apc_params`**
   - 描述：檢查 APC 模型的前饋/反饋補償參數是否達到飽和上限。
   - Input: `target_equipment` (string, 對應機台), `target_chamber` (string, 對應反應室)
2. **`mcp_check_recipe_offset`**
   - 描述：查詢 MES/RMS 確認配方近期是否有人為修改紀錄。
   - Input: `recipe_id` (string, 對應配方), `equipment_id` (string, 對應機台)
3. **`mcp_check_equipment_constants`**
   - 描述：連線機台比對 EC 黃金基準值，尋找硬體老化或氣體流量飄移徵兆。
   - Input: `eqp_name` (string, 對應機台), `chamber_name` (string, 對應反應室)

---

## 3. Builder API (智能建構器端點)
在 `routers/builder_router.py` 實作三大設計期輔助 API：
1. **`POST /auto-map` (智能映射)**
   - 傳入 Event 與 MCP Input Schema，利用 LLM 比對語意，自動建立對應關係 (如：`eqp_id` -> `target_equipment`)。
2. **`POST /validate-logic` (語意防呆)**
   - 傳入 User 撰寫的診斷 Prompt 與 MCP Output Schema，利用 LLM 檢查 User 是否要求了 MCP 未提供的數據。
3. **`POST /suggest-logic` (智能提示引擎)**
   - 傳入 Event Schema，利用 LLM 解析屬性 (如 consecutive_ooc_count)，並回傳 3~5 條專業排障邏輯提示，引導 User 設定 Skill。

---

## 4. 執行期診斷大腦 (Agent Runtime Logic)
1. **分診工具 (`mcp_event_triage`)**：接收如「機台 EAP01 發生 AEI CD 異常」，必須解析並回傳 `SPC_OOC_Etch_CD` 事件與建議的 3 個蝕刻 MCP。
2. **System Prompt**：更新為「你是一位台積電資深蝕刻製程工程師。若配方有人為修改，歸咎人為失誤；若 EC 偏離，歸咎硬體老化並建議 EE 介入；若前兩者正常但 APC 飽和，建議執行 Chamber Wet Clean。」

---

## 5. 底層驗證腳本約定 (Acceptance Criteria)
必須建立 `tests/test_phase6_etch_copilot.py`，完整驗證：
1. `suggest-logic` API 是否能根據 SPC Event 給出專業提示。
2. `auto-map` API 是否能精準將名稱不同的機台參數連線。
3. 執行 Agent Loop，驗證是否正確走完半導體排障流程。