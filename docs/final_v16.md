# Final v16 — Agentic OS：共生學習與確定性執行規範

> 本文件整合 v16.1 的協作學習願景，以及對其設計盲點的架構分析與落實建議。
> 狀態：Local 驗證階段，尚未上 Production。

---

## 1. 核心願景 (Vision)

v16.1 的核心是「**共生學習 (Symbiotic Learning)**」——系統不再單向執行指令，而是在 Planning 階段具備主動確認的意識，透過與用戶的互動縮短「意圖與執行」之間的鴻溝，並將人類的選擇轉化為長效記憶與模型行為補丁。

### 架構補充：從「規則 + 猜測」到「知識 + 確定性」

v16.1 的願景正確，但原始設計有一個根本矛盾：它依賴模型在執行期間「發現」它本應在 Stage 1 就已知道的靜態知識（工具 ID、參數格式），並依賴 Trap Memory 在失敗後補救——這是**行為層的修補，不是架構層的保證**。

**目標轉變：**

```
現在：Agent 靠「規則 + 猜測 + 失敗重試」運作
目標：Agent 靠「靜態知識注入 + 語義工具介面 + 雙層記憶」運作
```

三個核心原則：

1. **知識與行為分離**：靜態知識（工具目錄、ID、schema）在 Stage 1 完整注入，模型只負責推理與執行，不負責「發現」系統結構。
2. **工具介面語義化**：模型操作語義層（名稱、意圖），後端負責所有 ID 解析與關聯查找。
3. **記憶從被動到主動**：不只記失敗（Trap），也記成功模式（Pattern）；RAG 在 Stage 1 和 Stage 4 各觸發一次，時機與工具決策對齊。

---

## 2. 六階段協作工作流 (The Hybrid 6-Stage Loop)

### 🟢 Stage 1: Context Mapping（語義感知與完整知識注入）

**行為目標**：在模型開始推理前，確保它擁有完成任務所需的**所有靜態知識**與**相關歷史記憶**。

**詳細說明**：

**a. 語義解析**
識別訊息中的實體（機台 ID、批號、站點）與量化需求（時間範圍、筆數限制）。

**b. 意圖記憶檢索 (Intent-based Memory)**
根據用戶訊息語義從 Mem0 提取：
- 成功模式記憶（「查製程軌跡的正確流程是…」）
- Trap 記憶（「這類查詢曾失敗過，原因是…」）

**c. 工具目錄注入 [NEW — 關鍵修補]**
從 DB 動態載入並注入 System MCP 清單與 Custom MCP 清單：

```
## 可用 System MCPs（直接使用名稱，後端負責 ID 解析）
| name                    | 用途                  | 必填參數              |
|-------------------------|-----------------------|-----------------------|
| get_tool_trajectory     | 機台批次軌跡          | tool_id               |
| get_lot_trajectory      | Lot 製程軌跡          | lot_id                |
| get_process_context     | 製程站點上下文        | operation_number      |
| get_baseline_stats      | 基準線統計            | tool_id, param_name   |
| ...                     | ...                   | ...                   |
```

**設計理由**：模型在訓練資料中從未見過這個系統的 DB 主鍵。DB ID 是 runtime 的實作細節，不屬於任何文件，不能靠模型「猜」。工具目錄注入讓模型在進入 Stage 2 前就知道「有什麼工具、叫什麼名字、需要什麼參數」，根本不需要呼叫 `list_mcps` 或 `list_system_mcps`。

**Stage 1 結束的標準**：模型的 context 中已包含：
- ✅ 意圖相關的歷史記憶（成功模式優先，Trap 次之）
- ✅ 完整的 System MCP 目錄（name + 用途 + 參數）
- ✅ 完整的 Custom MCP 目錄（id + name + 用途）
- ✅ 用戶訊息中識別出的實體參數

---

### 🔵 Stage 2: Strategic Planning（多路徑計畫編排）

**行為目標**：基於 Stage 1 注入的完整知識，將任務解構為有確定性依據的執行計畫，並輸出可被驗證的 `<plan>` 標籤。

**詳細說明**：

**a. Plan A（主線）與 Plan B（容錯）生成**
兩個計畫必須基於 Stage 1 注入的工具目錄，不得引用未知的 mcp_id 或假設的參數值。

**b. 歧義偵測（置信度）**
當同一任務有多個合理路徑時，Agent 計算兩計畫的語義差異：
- 差異 > 30%：可直接進入 Stage 4 執行 Plan A
- 差異 < 30%：標註「待確認」，進入 Stage 3 請用戶選擇

**c. 計畫深度要求 [NEW]**
Planning 輸出必須包含每一步的工具名稱與關鍵參數。若輸出少於 50 tokens，視為規劃不足，自動重試一次（最多 1 次）：

```
✅ 合格：<plan>
  Step 1: execute_mcp(mcp_name='get_tool_trajectory', tool_id='EQP-01', limit=20)
  Step 2: 從 batches 讀取 spc_status，統計 OOC 次數
  Step 3: 回傳結果表格
</plan>

❌ 不合格：<plan>查 EQP-01</plan>  ← 少於 50 tokens，重新規劃
```

---

### 🟡 Stage 3: Human-in-the-loop（交互確認與計畫鎖定）

**行為目標**：在歧義存在時消除不確定性，建立人機共識；同時作為 Stage 4 執行失敗的升級入口。

**詳細說明**：

**a. 歧義確認流（來自 Stage 2）**
Blueprint Diff 呈現：在 UI 顯示 Plan A vs Plan B 的差異，讓用戶選擇方向。Agent 不得在用戶選擇前自行執行。

**b. 執行失敗升級流（來自 Stage 4）[NEW]**
當 Stage 4 的 Auto-Recovery 失敗後，暫停執行，在 chat bubble 呈現：
```
工具 [get_tool_trajectory] 在執行時失敗（錯誤：MCP_NOT_FOUND）。
我有以下選項：
A. 嘗試 Plan B（改用 get_lot_trajectory 從批次推算軌跡）
B. 我來手動指定正確參數
C. 跳過此步驟，繼續後續分析
```

**設計理由**：相比原本的「靜默失敗 → (無回答)」，升級流給用戶決策權，同時保留了完整的錯誤上下文。

**c. 快速確認原則**
若用戶意圖明確、計畫單一，Stage 3 應自動跳過（不打擾用戶），直接進入 Stage 4。Human-in-the-loop 只在真正有歧義或失敗時介入。

---

### 🔴 Stage 4: Execution（確定性執行 & 異常升級）

**行為目標**：用確定性的方式執行計畫，並在失敗時有序升級。

**詳細說明**：

**a. 工具記憶二次檢索 (Tool-based Memory) [v16.1 核心]**
在每次呼叫工具**前**，以工具名稱（`execute_mcp`、`execute_skill`）為 key 搜尋記憶，而非用用戶意圖搜尋：

```
呼叫 execute_mcp 前 →
  搜尋 tag=execute_mcp 的記憶 →
  找到「正確模式：用 mcp_name 而非 mcp_id」→
  按正確模式執行
```

**設計理由**：Stage 1 的 RAG 是基於用戶意圖（語義相似度），無法可靠地找到「工具呼叫錯誤」類型的記憶。Stage 4 的工具 tag 搜尋解決了這個時機問題。

**b. 三層恢復機制**
```
Level 1 — Auto-Recovery：若有 Plan B，自動切換，不打擾用戶
Level 2 — Escalation（4→3）：Plan B 也失敗，暫停並請求用戶決策
Level 3 — Graceful Degradation：用戶選擇跳過，記錄失敗並繼續後續步驟
```

**c. 工具介面語義化 [架構修補]**
`execute_mcp` 接受 `mcp_name`（字串）而非 `mcp_id`（整數）。後端負責 name → ID 解析：

```python
# 模型呼叫（語義層）
execute_mcp(mcp_name="get_tool_trajectory", params={"tool_id": "EQP-01", "limit": 20})

# 後端執行（關聯層）
mcp = db.query(MCPDefinition).filter_by(name="get_tool_trajectory").first()
result = run_mcp(mcp.id, params)
```

**設計理由**：DB 主鍵是後端實作細節，不屬於 LLM 的語義空間。強迫模型猜 integer ID 等於要求它知道一個它從未被告知的資訊。

---

### 🟠 Stage 5: Self-Reflection & Alignment（品質自省）

**行為目標**：在回傳結果前，自我檢查產出品質是否符合用戶意圖與工業標準。

**詳細說明**：

**自省清單**：
- 回傳的資料是否與用戶問題直接相關？
- 如果是診斷類，NORMAL/ABNORMAL 判斷是否有數據支撐？
- 如果是查詢類，資料是否完整、無空值異常？
- 視覺化結果是否清晰？

若自省不通過，觸發反饋流（5 → 2）重新規劃。

---

### 🟣 Stage 6: Interactive Learning（知識蒸餾與閉環回饋）

**行為目標**：將本次互動轉化為可被未來 Session 使用的智慧資產。

**詳細說明**：

**a. 成功模式記憶 [NEW — 與失敗 Trap 同等重要]**
每次成功完成多步驟查詢後，必須存入成功模式：

```
記憶內容：「查詢機台製程軌跡的正確做法：
  execute_mcp(mcp_name='get_tool_trajectory', params={tool_id, limit})
  → 回傳 batches 陣列，每筆含 lot_id, spc_status, apc_id
  → 直接從 batches 讀資料，無需再查個別 lot」
記憶 tag：[api_pattern, get_tool_trajectory, success]
```

**b. 失敗 Trap 記憶 [v16.1 現有機制]**
工具失敗時記錄：工具名稱 + 錯誤碼 + 正確替代做法。

**c. 記憶優先級**
成功模式優先注入（Stage 1 RAG 結果排序）。相同語義的成功模式存在時，Trap 記憶降級為輔助警示。

---

## 3. 多階段跳轉邏輯 (Jump Logic)

```
正常流：  1 → 2 → [3] → 4 → 5 → 6
                   ↑
              （歧義時才進入）

反饋流：  5 → 2（品質不佳，重新規劃）

升級流：  4 → 3（執行失敗，請求人類決策）
          3 → 4（用戶確認後繼續）
```

---

## 4. 記憶架構（雙層 RAG）

| 層次 | 觸發時機 | 搜尋 Key | 記憶類型 |
|------|---------|---------|---------|
| 第一層：意圖檢索 | Stage 1，對話開始 | 用戶訊息語義 | 成功模式、領域知識 |
| 第二層：工具校驗 | Stage 4，每次工具呼叫前 | 工具名稱 tag | Trap 記憶、工具使用警示 |

**設計理由**：
第一層用語義找「這類問題的正確做法」；第二層用工具名稱找「這個工具的已知陷阱」。兩層互補，覆蓋原本 Trap Memory 因時機錯誤而無效的問題。

---

## 5. 工具 Schema 語義化規範

所有工具輸入參數應遵循以下原則：

| 原則 | 說明 | 範例 |
|------|------|------|
| 用名稱，不用 ID | 模型操作語義層，後端解析 ID | `mcp_name="get_tool_trajectory"` |
| 用描述，不用代碼 | 錯誤訊息用自然語言描述問題 | `"找不到名為 X 的 MCP"` |
| 必填參數明確宣告 | schema 中清楚標示 required | `"required": ["mcp_name", "params"]` |

---

## 6. 實作優先順序

按影響力由高到低，建議依序實作：

### Phase A（根治問題，無需 UI 改動）
1. **Stage 1 工具目錄注入**：`ContextLoader.build()` 從 DB 載入 MCP 清單，注入 system prompt
2. **`execute_mcp` 支援 `mcp_name`**：tool schema + dispatcher 改為 name-based，後端查 ID
3. **成功模式記憶**：Stage 6 成功後呼叫 `save_memory` 存入 Pattern 記憶

### Phase B（強化可靠性）
4. **Stage 4 工具 tag RAG**：執行工具前，以工具名稱搜尋 Trap 記憶
5. **Planning 深度驗證**：`<plan>` 少於 50 tokens 時自動重試
6. **其他工具語義化**：`analyze_data`、`execute_jit`、`patch_mcp` 同步改為 name-based

### Phase C（Human-in-the-loop，需 UI 配合）
7. **Stage 3 歧義確認 UI**：Blueprint Diff 呈現 Plan A vs B
8. **Stage 4→3 升級流**：執行失敗後在 chat bubble 呈現選項，等待用戶決策

---

## 7. 設計決策記錄（Why）

| 決策 | 原始設計 | 最終設計 | 理由 |
|------|---------|---------|------|
| MCP 識別方式 | `mcp_id: integer` | `mcp_name: string` | DB 主鍵不屬於模型語義空間，強迫猜測必然失敗 |
| 工具目錄取得方式 | 模型呼叫 `list_mcps`（runtime 發現） | Stage 1 直接注入（靜態知識） | list_ 工具存在的意義是「建立草稿時選擇」，不是「執行時確認 ID」 |
| Trap Memory 觸發時機 | Stage 1（意圖 RAG） | Stage 1（意圖）+ Stage 4（工具 tag）| 工具相關的 Trap 無法被意圖 RAG 可靠地撈到 |
| 記憶類型 | 只記失敗（Trap） | 失敗（Trap）+ 成功（Pattern）| 成功模式讓 Stage 1 直接載入正確做法，根本不走到失敗路徑 |
| Human-in-the-loop 時機 | 每次規劃都確認 | 只在歧義或失敗升級時介入 | 過度確認破壞用戶體驗；模型有確定性基礎時不應打擾用戶 |
