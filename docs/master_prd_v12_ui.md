# 🚀 Master PRD v12: AI Ops 平台 UI/UX 全面解耦與巢狀架構升級

## 1. 核心改版精神
本版本的核心目標是實現**「Top-Down 任務導向」**、**「MCP 與 Skill 的 N 對 N 解耦」**，以及**「Progressive Disclosure (漸進式揭露)」**。徹底捨棄開發者視角的底層元件管理，改以「戰情室大盤」作為唯一入口。

## 2. 畫面一：戰情指揮中心 (Mission Control Dashboard)
系統唯一入口，包含以下版塊：
* **全局 KPI (Global Metrics)**：活躍巡檢排程、24H 執行總數、攔截異常事件 (需以紅色高亮/脈衝效果呈現)、資源庫共用率。
* **監控中的排程 (Active Tasks)**：左側列表，需明確標示各 Task 套用的 `Skill` (紫色 Tag) 與 `MCP` (綠色 Tag) 以展現解耦特性。
* **24H 執行軌跡 (Execution Log)**：右側列表，若為 Abnormal 狀態，需在列表上直接預覽 LLM 診斷結論與專家處置 Action。

## 3. 畫面二：巢狀建構器 & 試跑終端 (Nested Builder & Console)
由 Dashboard 點擊新增排程後進入，採上下分割佈局。

### 3.1 上半部：巢狀設定區 (Nested Builder)
實作「俄羅斯娃娃」視覺層級：
* **[L1] 巡檢任務 (Task)**：最外層卡片，設定名稱與排程頻率。
* **[L2] 診斷技能 (Skill)**：包覆於 Task 內。支援 `選擇現有` / `建立全新`。需包含異常判斷條件 (Prompt)、有問題的物件 (Target Object)、專家建議處置。
* **[L3] 資料節點 (MCP)**：包覆於 Skill 內。支援 `選擇現有` / `建立全新`。需包含 DataSubject 選擇、測試參數輸入、加工意圖 (Python Prompt)。
* **漸進式揭露 (Collapsible UX)**：為保持版面清爽，`Data Review` (Raw Data)、`Format Review` (Output Schema) 以及 `Skill 系統設定檢查` 必須使用 HTML `<details>` 或對應折疊元件收納。

### 3.2 下半部：試跑輸出終端 (Try Run Console)
深色底色的固定面板，負責渲染 Try Run 結果。
* **黃金順序**：上方先顯示 Skill 診斷層 (Status, LLM Summary, 異常物件, 專家處置)；下方接著顯示 MCP 佐證層。
* **MCP 佐證層 Tabs**：必須包含 `📊 Charting`、`📑 Summary Data`、`💾 Raw Data` 三個切換頁籤。

## 5. MCP 正確執行流程規範 ⚡ CANONICAL SPEC — 每次修改必須遵守

> **任何涉及 MCP 呼叫的功能，開發前必須先對照此章節。違反此規範視為 bug。**

---

### 5.1 兩條執行路徑：黃金法則

| 路徑 | API | 使用時機 | LLM? | 輸入 |
|------|-----|---------|------|------|
| **A. try-run** | `POST /mcp-definitions/try-run` | **MCP Builder 建立全新 MCP** | ✅ LLM 生成 processing_script | `processing_intent` + `sample_data` |
| **B. run-with-data** | `POST /mcp-definitions/{id}/run-with-data` | **所有其他場景** | ❌ 直接跑已存 Python | `raw_data`（真實 DS 資料） |

**記憶口訣：只有「第一次建立」才叫 LLM，之後一律跑 Python。**

---

### 5.2 DS Input 處理規則

在呼叫任何 MCP 之前，**必須**先取得 Data Subject 所需的 input 參數：

```
DS.input_schema.fields  →  逐一確認每個 required field 有值  →  呼叫 DS endpoint fetch 真實資料  →  execute MCP script
```

**各場景如何取得 DS input：**

| 場景 | DS Input 來源 | 處理方式 |
|------|--------------|---------|
| Nested Builder — 建立全新 MCP | `nb-mcp-sample-form` 表單（選完 DS 後動態渲染） | User 手動填入 |
| Nested Builder — 選擇現有 MCP | 選完 MCP 後，從 `mcp.data_subject_id` 取 DS，在 console 動態渲染相同表單 | User 手動填入 |
| Skill Builder — 執行 MCP 佐證 | `_runLoadedMcpData()` 已有正確 DS fetch 流程 | 現有正確，維持不動 |
| RoutineCheck 排程觸發 | `check.skill_input`（建立排程時由 user 填寫的固定參數）| 執行時從 skill_input 讀取；缺漏時動態補齊 |
| Copilot 對話 | LLM 從對話解析；缺漏的 required fields 透過 slot_filling 向 user 要 | slot_filling 機制 |
| Event-Driven Diagnosis | `event_params`（由事件觸發時帶入） | 現有正確，維持不動 |

---

### 5.3 各場景完整執行流程

#### Scenario A：Nested Builder — 選擇現有 MCP（`_nbMcpMode === 'select'`）

```
User 從下拉選擇 MCP
  → onchange: 讀取 mcp.data_subject_id → 找到 DS → 渲染 DS input 表單到 console panel
  → User 填寫表單參數（如 lot_id, equipment_id）

按下 ▶ Run
  → 1. 收集表單參數 _nbCollectFormParams()
  → 2. 用參數 fetch DS endpoint → raw_data（真實資料）
  → 3. POST /mcp-definitions/{mcpId}/run-with-data  ← 直接跑 Python, 無 LLM
       { raw_data: realData }
  → 4. 若 _nbSkillMode === 'new'：
       POST /skill-definitions/generate-code-diagnosis  ← LLM 只在這裡生成診斷碼
       { diagnostic_prompt, mcp_sample_outputs: {mcpName: mcpOutput} }
  → 5. 渲染 Skill 診斷 + MCP 佐證
```

#### Scenario B：Nested Builder — 建立全新 MCP（`_nbMcpMode === 'new'`）

```
User 選擇 DS → 表單動態渲染（_nbOnDsChange）
User 填寫加工意圖 processing_intent

按下 ▶ Run
  → 1. 收集表單參數 → fetch DS endpoint → sample_data
  → 2. POST /mcp-definitions/try-run  ← LLM 生成腳本（唯一正當時機）
       { processing_intent, data_subject_id, sample_data }
  → 3. 若 _nbSkillMode === 'new'：generate-code-diagnosis
  → 4. 渲染結果
```

#### Scenario C：RoutineCheck 排程執行

```
建立排程時（`_nbSaveRoutineCheck`）：
  → 讀取 Skill 綁定的 MCP → 取出 DS.input_schema.fields
  → 區分固定參數（user 在建立時填寫，存入 check.skill_input）
    vs 動態參數（從事件上下文或 problem_object 推導）

排程觸發時（`scheduler.py:run_routine_check_job`）：
  → 讀 check.skill_input（固定參數）
  → 補齊缺漏的動態參數（從 last_diagnosis_result.problem_object 或預設值）
  → _fetch_ds_data(endpoint, complete_params)  ← 真實 DS 資料
  → execute_script(mcp.processing_script, real_data)  ← 直接跑 Python
  → execute_diagnose_fn(skill.generated_code, mcp_output)  ← 診斷沙箱
```

#### Scenario D：Copilot 對話

```
User 輸入訊息
  → LLM 解析意圖 → 識別目標 MCP/Skill
  → 讀取 DS.input_schema.fields (required fields)
  → 比對：哪些 required 欄位已從對話確認？哪些缺漏？
  → 若有缺漏 → yield slot_filling
       { type: "slot_filling", missing: [{field, label, required}] }
  → 前端顯示提示 → user 補充
  → 所有 required 參數齊全後：
  → _fetch_ds_data(endpoint, params)
  → execute_script(mcp.processing_script, raw_data)  ← 直接跑 Python
  → yield mcp_result / skill_result
```

---

### 5.4 禁止項目（NEVER DO）

1. **禁止**在非 MCP Builder 場景呼叫 `POST /mcp-definitions/try-run`
2. **禁止**以 `sample_data: null` 或 `sample_data: {}` 呼叫任何 MCP 執行 endpoint
3. **禁止**在執行前跳過 DS input 收集步驟（靜默繼續 = bug）
4. **禁止**新增任何「直接呼叫 execute_script」的路徑而不先 fetch 真實 DS 資料
5. **禁止**在 Copilot/RoutineCheck 中以 LLM 生成 processing_script（只有建立時才生成）

---

## 4. UI 原型參考 (Reference HTML Artifacts)
請參考以下 HTML 結構與 Tailwind 樣式邏輯進行 Component 重構。

**(1) Dashboard Prototype**
```html
<div class="grid grid-cols-4 gap-4 mb-6"><div class="bg-white rounded p-4 border shadow-sm"><p class="text-xs font-bold text-slate-500">活躍巡檢排程</p><h3 class="text-2xl font-bold">12</h3></div><div class="bg-white rounded p-4 border-red-200 shadow-sm"><p class="text-xs font-bold text-red-600">攔截異常事件</p><h3 class="text-2xl font-bold text-red-700">5</h3></div></div>
<div class="flex gap-6"><div class="w-5/12"><h2 class="font-bold">Active Tasks</h2><div class="border rounded p-4 bg-white border-l-4 border-red-500"><h4>SPC 異常巡檢</h4><p class="text-xs text-purple-700">Skill: 檢查連續異常</p><p class="text-xs text-emerald-700">MCP: Query SPC</p></div></div><div class="w-7/12"><h2 class="font-bold">Execution Log</h2><div class="bg-white border p-3 flex gap-4 bg-red-50/30"><div class="text-xs">11:00</div><div class="font-bold">SPC 異常巡檢</div><div class="text-xs text-red-600 font-bold">ABNORMAL</div></div></div></div>

**(2) Nested Builder & Console Prototype**

<div class="flex-1 flex flex-col"><div class="h-3/5 p-6 bg-slate-50"><div class="bg-white rounded border p-5 border-l-8 border-slate-800"><h2 class="font-bold">1. Task</h2><div class="bg-slate-50 border p-4 rounded border-l-4 border-purple-500 mt-4"><h3 class="font-bold text-sm">2. Skill</h3><div class="bg-white border p-4 rounded border-l-4 border-emerald-500 mt-2"><h4 class="font-bold text-xs">3. MCP</h4><details class="text-[10px] bg-slate-50 p-2"><summary>👁️ Data Review (Raw Data)</summary>JSON...</details><details class="text-[10px] bg-emerald-50 p-2 mt-2"><summary>📐 Format Review</summary>Schema...</details></div><textarea placeholder="異常判斷條件"></textarea><textarea placeholder="有問題的物件 Target Object"></textarea></div></div></div><div class="h-2/5 bg-slate-900 text-white flex flex-col"><div class="p-2 bg-slate-950 text-emerald-400 text-xs">Try Run Console</div><div class="flex-1 p-4 bg-slate-200 text-slate-800"><div class="bg-white border-t-4 border-red-500 p-4 mb-4"><span class="text-red-600 font-bold text-xs">ABNORMAL</span><p>LLM 診斷...</p></div><div class="bg-white border p-4"><div class="flex gap-4 border-b pb-2"><span class="text-blue-600 font-bold text-sm">📊 Charting</span><span class="text-slate-500 text-sm">📑 Summary</span><span class="text-slate-500 text-sm">💾 Raw Data</span></div><div class="h-32 bg-slate-50 border-dashed border-2 text-slate-400">[ Plotly Render Area ]</div></div></div></div></div>