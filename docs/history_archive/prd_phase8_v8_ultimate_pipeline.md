# Phase 8：企業級 RBAC 與 Data-to-Decision 決策管線 (v8 終極完整版)

## 1. 架構核心理念 (Core Philosophy & RBAC)
系統導入三層解耦架構與角色權限：
1. **IT Admin (造磚者)**：維護 `Data Subjects` (定義資料源與 API 連線)。
2. **Expert / 資深 PE (蓋房者)**：嚴格區分「資料處理 (MCP)」與「邏輯判斷 (Skill)」。LLM 在建構過程中全程擔任 UX Copilot，協助 Schema 定義、對應與圖表生成。
3. **General User (居住者)**：在診斷工作站觸發排障。

---

## 2. IT 基礎建設：Data Subject 與 內建 KPI
### 2.1 Data Subject 擴充
Data Subject 必須包含 `api_config` (endpoint_url, method, headers)，並定義明確的 `input_schema` 與 `output_schema`。

### 2.2 內建三大半導體 KPI (Mock APIs)
在 `routers/mock_data_router.py` 實作：
- **A. APC (`/apc`)**：Input `lot_id`, `operation_number`。回傳多點位陣列與補償狀態。
- **B. Recipe (`/recipe`)**：Input `lot_id`, `tool_id`, `operation_number`。回傳參數與**動態計算的「12 小時前」最後修改時間**。
- **C. EC (`/ec`)**：Input `tool_id`。回傳機台硬體參數基準。
*(系統啟動時需自動將此三者註冊為 Data Subjects)*

---

## 3. Expert 建構管線 A：Event 定義
- **Event Type & Description**：定義異常事件 (如 `SPC_OOC_Etch`)。
- **Attributes**：Expert 可動態新增 `lot_id`, `tool_id` 等屬性，**強制規定必須填寫 Type 與 Description**，此為 LLM 自動映射之命脈。

---

## 4. Expert 建構管線 B：MCP Builder (資料加工與視覺化建構器)
MCP 負責將 Raw Data 轉換為「處理後的 Dataset」與「視覺化圖表」。
**UX 流程：**
1. **選定 Data Subject**：選擇底層資料源，系統載入其 Raw Format。
2. **定義加工意圖 (LLM 輔助)**：
   - User 輸入：「計算移動平均線並標示 OOC 點位」。
   - **LLM 背景任務**：產生 Python 處理腳本 (Sandbox 執行)，並**自動定義新的 Output Dataset Schema**。
3. **定義 UI 呈現 (UI Render)**：
   - **LLM 背景任務**：根據新產生的 Dataset，自動建議並定義適合的圖表呈現 (如：`Trend Chart` 搭配特定 X/Y 軸，或 `Table`)。
4. **定義 MCP Input**：
   - **LLM 背景任務**：分析此加工邏輯需要什麼 Input 參數 (部分繼承自 Data Subject，部分為新增的加工條件)。

---

## 5. Expert 建構管線 C：Skill Builder (決策大腦與事件整合器)
Skill 負責「觸發條件設定」、「參數映射」與「最終診斷」。
**UX 流程：**
1. **選定觸發 Event**：選擇系統異常事件。
2. **尋找與綁定 MCP**：挑選建構好的 MCP (可多選)。
3. **條件與參數整合 (LLM Context Mapping)**：
   - **LLM 背景任務**：自動比對 Event Attribute 與 MCP Input Definition，將 `event.tool_id` 綁定至 `mcp.tool_id`。若有缺漏，提示 User 手動輸入或設預設值。
4. **撰寫診斷邏輯 (Diagnostic Prompt)**：
   - 介面展示出 MCP 執行後產生的 **Output Dataset Schema**。
   - User 根據此 Output 撰寫邏輯 (例：「檢視 Dataset 的 ooc_points，若連續 3 點則判定硬體飄移」)。

---

## 6. 介面寬度與操作體驗強制規範
所有的 Builder 介面 (Data Subject, Event, MCP, Skill) 必須採用大型的滑出抽屜 (Right Drawer) 或滿版精靈 (Wizard)，寬度至少需佔據畫面的 **50% ~ 60% (`w-[60vw]`)**，確保 JSON Schema、圖表預覽與 LLM 提示有足夠閱讀空間。