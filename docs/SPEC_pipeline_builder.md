# SPEC — Visual Pipeline Builder (Glass Box Agent)

**Version:** 1.0
**Date:** 2026-04-18
**Author:** Gill (Architecture) + Claude (Drafting)
**Status:** Draft — 待審閱後進入 Phase 1 PoC
**前置文件：**
- `docs/data_pipeline_builder.md`（原始 idea）
- `docs/SPEC_pipeline_v2.md`（9-Stage Pipeline，本 Spec 承接其 Stage 3–6）

---

## 1. Context & Objective

### 1.1 核心動機
現行 Agent 走「LLM → 產 Python code → sandbox exec」路徑，面臨三個結構性問題：

1. **不確定性**：相同 prompt 產出不同 code，失敗率難降到零
2. **不可除錯**：code 失敗時 PE 看不懂 stack trace，只能重跑
3. **信任鴻溝**：半導體業規範要求可審計，PE 不敢把決策交給「AI 寫的 code」

### 1.2 目標
建立 **Visual Pipeline Builder** — Node-based DAG 編輯器，所有 Agent 決策以積木組合呈現；Agent 從「產碼者」退化為「操作 Builder 的使用者」，使 PE 能親眼看到、親手調整、親自授權部署。

### 1.3 核心設計哲學
**Glass Box Agent** — 對照 Claude Code 的 tool-use 模式：
- ❌ 不是「Agent 一次產出完整 Pipeline JSON」（Black Box）
- ✅ 是「Agent 呼叫 Builder API 一步步組裝」，每一步 PE 都看得到、可中斷、可接手

### 1.4 非目標（Out of Scope）
- 不取代 Copilot 對話介面（Copilot 仍存在，但會「在旁邊操作 Builder」）
- 不重寫既有 MCP / Skill / generic_tools（這些轉為 Builder 積木的底層 implementation）
- 不處理前端其他模組（Alarm Center、Console 不變動）
- 不涵蓋 multi-tenant / 權限細部設計（僅定義 PE admin vs 一般 user 粗分）

### 1.5 成功標準
上線 30 天內：
- [ ] 既有 17 個 V2 test cases 可用 Visual Pipeline 重建，結果等效
- [ ] Agent 產 Pipeline 草圖的成功率 ≥ 90%（一次到位不需 retry）
- [ ] PE 從「接到需求」到「部署規則」時間 < 15 分鐘
- [ ] Custom Block 使用率 ≤ 10%（標準積木庫覆蓋絕大多數場景）

---

## 2. Architecture & Design

### 2.1 整體架構圖

```
┌─────────────────────────────────────────────────────────────────┐
│                      aiops-app (Frontend)                       │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │       Pipeline Builder UI (React Flow + Custom)          │ │
│  │  ┌──────┬────────────────────────┬────────────────────┐  │ │
│  │  │ 積木 │      DAG Canvas         │  Node Inspector   │  │ │
│  │  │ Lib  │   (nodes + edges)       │  (param form)     │  │ │
│  │  ├──────┴────────────────────────┴────────────────────┤  │ │
│  │  │           Data Preview (bottom panel)              │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                                                           │ │
│  │   ⚡ Canvas Operation API (for Agent remote control)      │ │
│  │     add_node / connect / set_param / preview / undo      │ │
│  └───────────────────────────────────────────────────────────┘ │
└────────────────────┬────────────────────────────────────────────┘
                     │ WebSocket + HTTP
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                fastapi_backend_service (Backend)                 │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Pipeline Builder Service                                │   │
│  │  ├─ Block Catalog (DB-backed, 符合 CLAUDE.md 原則)        │   │
│  │  ├─ Pipeline CRUD (Draft/Pi-run/Production status)       │   │
│  │  ├─ Pipeline Execution Engine (DAG executor)             │   │
│  │  ├─ Intermediate Result Cache (per node output)          │   │
│  │  └─ Canvas Event Bus (Agent ↔ Frontend sync)            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Agent Orchestrator v3 (Glass Box mode)                  │   │
│  │  ├─ Tool: builder.add_node / connect / set_param / ...   │   │
│  │  ├─ Tool: builder.preview (讓 Agent 看中間資料)           │   │
│  │  ├─ Tool: builder.explain (向 PE 解釋當前步驟)            │   │
│  │  └─ 不再有 exec/sandbox tool（除非明確走 Custom Block）   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  底層資產（既有，作為積木的 implementation）                │   │
│  │  ├─ MCP Registry → 資料源積木                             │   │
│  │  ├─ generic_tools → 處理積木                              │   │
│  │  ├─ Skill Registry → 複合積木                             │   │
│  │  └─ sandbox_service → Custom Block 執行器（限縮用途）     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                     │
                     ▼
         PostgreSQL + ontology_simulator + LLM APIs
```

### 2.2 資料模型（DB Schema 新增）

```sql
-- 積木定義（Block 本身）
CREATE TABLE blocks (
    id              UUID PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    category        VARCHAR(32) NOT NULL,  -- source | transform | logic | output | custom
    version         VARCHAR(32) NOT NULL,  -- semver: 1.0.0
    status          VARCHAR(16) NOT NULL,  -- draft | pi_run | production | deprecated
    description     TEXT NOT NULL,         -- LLM 讀取用（符合 CLAUDE.md 原則）
    input_schema    JSONB NOT NULL,        -- 輸入 port 定義
    output_schema   JSONB NOT NULL,        -- 輸出 port 定義
    param_schema    JSONB NOT NULL,        -- JSON Schema for UI form
    implementation  JSONB NOT NULL,        -- {type: "mcp"|"tool"|"skill"|"python", ref: ...}
    is_custom       BOOLEAN DEFAULT FALSE, -- 是否為 Custom Block（走 sandbox）
    created_by      UUID REFERENCES users(id),
    approved_by     UUID REFERENCES users(id),  -- null until Production
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(name, version)
);

-- Pipeline 定義（一張 canvas = 一筆 pipeline）
CREATE TABLE pipelines (
    id              UUID PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    description     TEXT,
    status          VARCHAR(16) NOT NULL,  -- draft | pi_run | production | deprecated
    version         VARCHAR(32) NOT NULL,
    pipeline_json   JSONB NOT NULL,        -- 見 §4 定義
    created_by      UUID REFERENCES users(id),
    approved_by     UUID REFERENCES users(id),
    approved_at     TIMESTAMPTZ,
    parent_id       UUID REFERENCES pipelines(id),  -- 若為 fork 版本
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Pipeline 執行紀錄
CREATE TABLE pipeline_runs (
    id              UUID PRIMARY KEY,
    pipeline_id     UUID REFERENCES pipelines(id),
    pipeline_version VARCHAR(32) NOT NULL,  -- 快照當下版本
    triggered_by    VARCHAR(32) NOT NULL,   -- user | agent | schedule | event
    status          VARCHAR(16) NOT NULL,   -- running | success | failed
    node_results    JSONB,                  -- {node_id: {status, rows, duration_ms, error}}
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

-- Agent canvas 操作紀錄（用於教學 + audit）
CREATE TABLE canvas_operations (
    id              UUID PRIMARY KEY,
    pipeline_id     UUID REFERENCES pipelines(id),
    actor           VARCHAR(32) NOT NULL,   -- user | agent
    operation       VARCHAR(32) NOT NULL,   -- add_node | connect | set_param | ...
    payload         JSONB NOT NULL,
    reasoning       TEXT,                   -- Agent 的動機說明
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 3. 標準積木庫 Schema（Block Catalog）

### 3.1 積木定義通用格式

```json
{
  "id": "block_mcp_fetch",
  "name": "MCP 歷史查詢",
  "category": "source",
  "version": "1.0.0",
  "status": "production",
  "description": "拉取指定機台、時間區間的製程資料 (包含 SPC, APC, DC)。回傳 DataFrame，欄位包含 eventTime, toolID, lotID, step, chartType, value, spc_status。",
  "input_schema": [],
  "output_schema": [
    {
      "port": "data",
      "type": "dataframe",
      "columns": ["eventTime", "toolID", "lotID", "step", "chartType", "value", "spc_status"]
    }
  ],
  "param_schema": {
    "type": "object",
    "required": ["tool_id", "time_range"],
    "properties": {
      "tool_id": {
        "type": "string",
        "title": "機台 ID",
        "examples": ["EQP-01", "EQP-02"]
      },
      "time_range": {
        "type": "string",
        "title": "時間範圍",
        "enum": ["1h", "24h", "7d", "custom"]
      },
      "custom_start": { "type": "string", "format": "date-time" },
      "custom_end": { "type": "string", "format": "date-time" }
    }
  },
  "implementation": {
    "type": "mcp",
    "ref": "get_process_history"
  }
}
```

### 3.2 標準積木清單（已上線）

**目前版本（Phase 3.x + α + β + γ + δ + 4-A，共 25 個）** — seed.py 為 SSOT。

#### 類別一：資料源（Sources）— 2 個
| ID | Output | 說明 |
|---|---|---|
| `block_process_history` | `data` (df) | 底層 MCP `get_process_info`；SPC/APC/DC/RECIPE/FDC/EC flatten |
| **`block_mcp_call`** *(δ)* | `data` (df) | 通用 MCP 呼叫器；`mcp_name` + `args` 查 mcp_definitions 表，自動 flatten events/dataset/items/data/records/rows 回傳 |

#### 類別二：處理（Transforms）— 11 個
| ID | I/O | 說明 |
|---|---|---|
| `block_filter` | df → df | column/operator/value 過濾 |
| `block_join` | df+df → df | key-based 關聯併表 |
| `block_groupby_agg` | df → df | mean/sum/count/min/max/median/std |
| `block_shift_lag` | df → df | pandas shift(N) + delta |
| `block_rolling_window` | df → df | SMA / rolling std / min / max / sum / median |
| `block_delta` | df → df | 相鄰點 delta + is_rising / is_falling 旗標 |
| `block_sort` *(α)* | df → df | 多欄排序 + optional top-N |
| `block_histogram` *(α)* | df → df | 分布直方圖 (bin_left/right/center/count/density) |
| `block_unpivot` *(β)* | df → df | Wide→long melt（搭配 group_by 處理多 chart type） |
| `block_union` *(β)* | df + df → df | 縱向合併 (outer / intersect schema) |
| **`block_ewma`** *(γ)* | df → df | 指數加權移動平均（α smoothing） |

#### 類別三：邏輯與 ML（Logic）— 8 個（前 5 個採 **triggered + evidence** 統一介面）
| ID | I/O | 說明 |
|---|---|---|
| `block_threshold` | df → `triggered` + `evidence` | UCL/LCL bound 檢查 |
| `block_consecutive_rule` | df → `triggered` + `evidence` | Tail-based；最後 N 筆全 True 才觸發 |
| `block_weco_rules` | df → `triggered` + `evidence` | Nelson 8 條全套 R1..R8 *(β)* |
| `block_any_trigger` *(β)* | 4×bool + 4×df → `triggered` + `evidence` | OR 多 logic node + 合併 evidence（`source_port` 欄位做歸因） |
| `block_linear_regression` *(α)* | df → `stats` + `data` + `ci` | OLS + R² + residuals + confidence band |
| `block_cpk` *(β)* | df → `stats` | Process capability: Cp/Cpu/Cpl/Cpk/Pp/Ppk |
| **`block_correlation`** *(γ)* | df → `matrix` (long) | 多欄位 pairwise corr (pearson/spearman/kendall)，直接餵 heatmap |
| **`block_hypothesis_test`** *(γ)* | df → `stats` | Welch t-test / one-way ANOVA / chi-square independence |

#### 類別四：輸出（Outputs）— 2 個
| ID | I/O | 說明 |
|---|---|---|
| `block_chart` | df → `chart_spec` | 雙 renderer：Vega-Lite（簡單圖）/ Plotly ChartDSL（SPC / 多 y / 雙軸 / boxplot / heatmap）。**SPC mode 同時支援 `color="<col>"` 多系列 overlay**（emit `series_field`，frontend 一條 trace per 分組值，UCL/LCL/Center 仍全域疊加） |
| `block_alert` | `triggered`+`evidence` → `alert` (df) | 多 alert 允許（C8 於 β 撤銷） |

**合計：2 + 11 + 8 + 2 = 23 個標準積木**

**Validator 規則**：C1–C7 + C9（C8 SINGLE_ALERT 於 Phase β 撤銷；多 alert 合法）

**Phase 規劃**：
- Phase α（已完成）— 3 新 block + chart 擴充 4 模式
- Phase β（已完成）— `block_unpivot` / `block_union` / `block_cpk` / `block_any_trigger` + WECO 補 R3/R4/R7/R8 + 拔 C8
- **Phase γ（已完成）** — `block_correlation` / `block_hypothesis_test` / `block_ewma`
- **Phase δ（已完成）** — `block_mcp_call`（通用 MCP wrapper）
- Phase 4（未啟動）— diagnostic_rules migration + Custom Block + 舊 code-gen 下線

### 3.3 積木實作介面（Block Implementation Contract）

每個積木的 `implementation.type` 有 4 種：

```python
class BlockExecutor(ABC):
    @abstractmethod
    async def execute(
        self,
        params: dict,           # from param_schema
        inputs: dict[str, Any], # from connected upstream nodes
    ) -> dict[str, Any]:        # outputs by port name
        ...

# 對應 implementation.type:
# - "mcp":    MCPBlockExecutor   (呼叫既有 MCP)
# - "tool":   ToolBlockExecutor  (呼叫 generic_tools 函式)
# - "skill":  SkillBlockExecutor (呼叫 skill_executor_service)
# - "python": CustomBlockExecutor (走 sandbox_service，限 Custom Block)
```

---

## 4. Pipeline JSON Schema

### 4.1 完整格式範例

```json
{
  "version": "1.0",
  "name": "EQP-01 SPC 連續 OOC 巡檢",
  "metadata": {
    "created_by": "agent|user_uuid",
    "tags": ["spc", "patrol"]
  },
  "nodes": [
    {
      "id": "n1",
      "block_id": "block_mcp_fetch",
      "block_version": "1.0.0",
      "position": { "x": 30, "y": 80 },
      "params": {
        "tool_id": "EQP-01",
        "time_range": "24h"
      }
    },
    {
      "id": "n2",
      "block_id": "block_filter",
      "block_version": "1.0.0",
      "position": { "x": 310, "y": 80 },
      "params": {
        "column": "step",
        "operator": "==",
        "value": "STEP_002"
      }
    },
    {
      "id": "n3",
      "block_id": "block_consecutive_rule",
      "block_version": "1.0.0",
      "position": { "x": 590, "y": 160 },
      "params": {
        "column": "value",
        "condition": "> UCL",
        "threshold": 3
      }
    },
    {
      "id": "n4",
      "block_id": "block_alert",
      "block_version": "1.0.0",
      "position": { "x": 870, "y": 160 },
      "params": {
        "severity": "HIGH",
        "message_template": "{tool_id} 連續 {threshold} 次 OOC"
      }
    }
  ],
  "edges": [
    { "id": "e1", "from": { "node": "n1", "port": "data" }, "to": { "node": "n2", "port": "data" } },
    { "id": "e2", "from": { "node": "n2", "port": "data" }, "to": { "node": "n3", "port": "data" } },
    { "id": "e3", "from": { "node": "n3", "port": "triggers" }, "to": { "node": "n4", "port": "records" } }
  ]
}
```

### 4.2 驗證規則（Pipeline Validator）

執行前必須通過：
1. **Schema 合法性** — 所有 node / edge 欄位齊全
2. **Block 存在性** — 所有 `block_id` + `block_version` 在 Catalog 內
3. **Block Status 合規** — Production pipeline 只能用 Production 積木
4. **Port 型別相容** — edge 兩端的 port type 必須匹配
5. **DAG 無循環** — 不可有環
6. **參數 schema 驗證** — 每個 node 的 params 通過該 block 的 `param_schema`
7. **起訖合理** — 至少一個 source node、至少一個 output node

---

## 5. Status 管理機制（Block & Pipeline）

### 5.1 三階段生命週期

```
      ┌──────────────────────────────────────────────────┐
      │                                                  │
   ┌──┴───┐   promote   ┌────────┐   promote   ┌────────┴───┐
   │ Draft│ ──────────▶ │ Pi-run │ ──────────▶ │ Production │
   └──────┘             └────────┘             └────────────┘
      ▲                     │                      │
      │                     │                      ▼
      │                     │                  ┌────────┐
      └─────────fork────────┴──────────────────│Deprecate│
                                               └────────┘
```

### 5.2 各狀態定義

| 狀態 | 可執行範圍 | 列入 Catalog | 可修改 | 權限 |
|---|---|---|---|---|
| **Draft** | 僅建立者個人環境 | ❌ 不列入 | ✅ 直接修改 | 建立者 |
| **Pi-run** | 指定 Pilot 機台 / 資料集 | ✅ 標 `[實驗中]` | ✅ 直接修改 | PE admin |
| **Production** | 全環境 | ✅ 標 `[生產]` | ❌ 需 fork 新版 | PE admin + approved |
| **Deprecated** | 唯讀，無法再引用 | ❌ 列入歷史 | ❌ | PE admin |

### 5.3 關鍵治理規則

1. **Pipeline 引用 Production 積木時鎖版本**
   - 儲存時寫入 `block_version` 明確版本號
   - 即使積木後續出新版，Pipeline 不自動升級
   - 需手動「更新積木版本」動作（類似 `npm update`）

2. **Production 不可直接修改**
   - 修改 = fork 出 Draft 版本 → 走完 promotion 流程 → 原版 Deprecated
   - `parent_id` 欄位記錄沿革

3. **Status 降級禁止**
   - Production ❌→ Draft / Pi-run
   - 只能 Deprecate 後 fork 新 Draft

4. **Review 欄位先留但晚做**
   - Schema 先包含 `approved_by` / `approved_at` / `review_note`
   - Phase 3 之後再實作 approval workflow（目前 PE admin 自己可 promote）

---

## 6. Agent-as-User：Tool API 設計（核心章節）

### 6.1 設計原則

Agent 不產 Pipeline JSON，而是**像使用者一樣操作 Builder**。每個操作都：
- 是獨立 tool call（走 Claude tool-use 機制）
- 在 Frontend canvas 上即時呈現（WebSocket push）
- 寫入 `canvas_operations` 表（可 replay / audit）
- 可被 PE 中斷或 override

### 6.2 Builder Tool API（Agent 可呼叫的工具）

```python
# === Canvas 操作類 ===
builder.list_blocks(
    category: str | None,
    status: str = "production",
) -> list[BlockSpec]
# 列出可用積木（從 DB 動態讀取，符合 CLAUDE.md 原則）

builder.add_node(
    block_id: str,
    block_version: str,
    position: {x: int, y: int},
    params: dict = {},
) -> node_id: str
# 加入節點，回傳 node_id 供後續操作

builder.remove_node(node_id: str) -> None

builder.connect(
    from_node: str,
    from_port: str,
    to_node: str,
    to_port: str,
) -> edge_id: str

builder.disconnect(edge_id: str) -> None

builder.set_param(
    node_id: str,
    key: str,
    value: Any,
) -> None

builder.move_node(
    node_id: str,
    position: {x: int, y: int},
) -> None

# === 檢視類 ===
builder.get_state() -> PipelineJSON
# 取得當前 canvas 完整狀態

builder.preview(
    node_id: str,
    sample_size: int = 100,
) -> {columns: [...], rows: [...], total: int}
# 執行到指定節點，回傳中間資料（給 Agent 決定下一步）

builder.validate() -> {valid: bool, errors: [...]}
# 執行 §4.2 的所有驗證

# === 溝通類（對 PE 可見）===
builder.explain(message: str, node_ids: list[str] = []) -> None
# 在 UI 上以氣泡顯示 Agent 的說明，highlight 指定節點
# 範例："我已經加入 filter 節點過濾 STEP_002，接下來要加連續規則"

builder.ask_user(
    question: str,
    options: list[str] = [],
    default: str | None = None,
) -> str
# Agent 不確定時問 PE，UI 顯示選項讓 PE 點

# === 生命週期 ===
builder.commit(name: str, description: str = "") -> pipeline_id: str
# 儲存為 Draft

builder.undo() -> None
builder.redo() -> None
```

### 6.3 Agent 運作範例（逐步展示）

使用者：「幫我建一個規則盯著 EQP-01，xbar 連續 3 次 OOC 就發告警」

```python
# Step 1: Agent 先看有哪些積木可用
blocks = builder.list_blocks(category="source")
# [block_mcp_fetch, block_tool_status]

# Step 2: Agent 向使用者解釋計畫
builder.explain("我會用 4 個節點組這條規則：MCP 查詢 → 過濾 STEP → 連續規則 → 告警")

# Step 3: 加入資料源
n1 = builder.add_node(
    block_id="block_mcp_fetch",
    block_version="1.0.0",
    position={"x": 30, "y": 80},
    params={"tool_id": "EQP-01", "time_range": "24h"}
)
# Frontend canvas 動畫：節點淡入 (300ms)

# Step 4: Agent 先確認資料長什麼樣
preview = builder.preview(node_id=n1, sample_size=10)
# Agent 看到 columns 包含 chartType, value, step → 確認用 filter
builder.explain("資料含 500 筆，先過濾 STEP_002", node_ids=[n1])

# Step 5: 加 filter 節點
n2 = builder.add_node(
    block_id="block_filter", ...
    params={"column": "step", "operator": "==", "value": "STEP_002"}
)
builder.connect(n1, "data", n2, "data")
# Frontend canvas 動畫：連線繪製 (400ms)

# Step 6: 再次 preview 確認過濾結果
preview = builder.preview(node_id=n2)
# Agent 看到剩 83 筆 → OK

# Step 7: 加連續規則 + 告警
n3 = builder.add_node("block_consecutive_rule", ...)
builder.connect(n2, "data", n3, "data")
n4 = builder.add_node("block_alert", ...)
builder.connect(n3, "triggers", n4, "records")

# Step 8: 驗證 + 解釋
result = builder.validate()
builder.explain(
    "規則已完成，共 4 個節點。建議你檢查 threshold = 3 是否正確，"
    "並確認告警嚴重度。確認後按 Deploy。",
    node_ids=[n3, n4]
)
```

### 6.4 前後端同步機制

```
Agent tool call
      │
      ▼
Builder Service (apply operation)
      │
      ├─▶ update pipeline_draft state (in-memory / Redis)
      ├─▶ write canvas_operations table
      │
      ▼
WebSocket broadcast to frontend
      │
      ▼
Frontend canvas animates the change
```

**關鍵設計：**
- Operation 是**冪等**的（同樣的 add_node 兩次 → 第二次 no-op 或回傳相同 node_id）
- Frontend 也可發 operation（PE 手動操作）→ 走同一條 pipeline → Agent 下次 `get_state()` 會看到變更
- **動畫節流**：Agent 操作時每個 action 之間最少間隔 200ms（讓 PE 看得清楚）
- **暫停機制**：PE 可按 UI 的 pause 按鈕 → backend 拒絕 Agent 後續 operation → Agent 收到「已被暫停」錯誤 → 轉為等待

### 6.5 失敗處理

Agent tool call 失敗時（例：加錯 block、port 不相容），backend 回傳結構化錯誤：

```json
{
  "error": "PORT_TYPE_MISMATCH",
  "message": "n2.data (dataframe) 無法連到 n3.model (model)",
  "suggestion": "n3 需要的是 dataframe input port，應該用 n3.data"
}
```

Agent 收到後自動嘗試修正（就像我在 Claude Code 裡看到 Edit 失敗會再試一次）。

---

## 7. Custom Block 的安全邊界

### 7.1 定位
Custom Block 是 **Escape Hatch**，用於標準積木庫無法覆蓋的場景。**不是主路徑**。

### 7.2 建立權限
- 僅 PE admin 能看到「新增 Custom Block」按鈕
- 一般使用者看得到既有 Custom Block（若已 Production）但不能新建

### 7.3 執行機制
- 走既有 `sandbox_service`（保留）
- 與標準積木**資源隔離**：
  - 獨立 Python 子進程
  - Memory limit: 512MB
  - CPU time limit: 30s
  - Network: 禁用（除非明確允許）
  - FS: 禁用

### 7.4 視覺警示
Canvas 上 Custom Block：
- 紅色邊框
- Header 有 ⚠️ icon
- Hover 顯示「此節點執行自訂 Python code，已由 [PE admin] 簽核」

### 7.5 治理要求
- Custom Block 從 Draft → Production **必須** PE admin 簽核（不能自己簽自己）
- 任何 Custom Block 修改都會被記錄進 audit log
- Pipeline 引用 Custom Block 時，該 Pipeline 自動標註「含 Custom Block」標籤

---

## 8. Step-by-Step Execution Plan

### 📌 2026-04-18 實作進度 Snapshot

| Phase | 狀態 | 備註 |
|---|---|---|
| 1 — PoC | ✅ 完成 | DAG executor + 5 積木；p95 latency < 5s |
| 2 — MVP UI | ✅ 完成 | React Flow + 11 積木；Inspector schema-driven；per-node cache；row-limit 控制 |
| 3.1 — Glass Box Agent 骨幹 | ✅ 完成 | SSE streaming；13 tools；ephemeral session |
| 3.2 — Logic Node 統一 schema | ✅ 完成 | `triggered + evidence`；consecutive tail-based；alert 角色簡化；terminal-logic detection |
| 3.3 — SPC 標準圖 + Agent auto-run | ✅ 完成 | block_chart SPC 模式（UCL/LCL/OOC 紅圈）；Accept & Run → Pipeline Results panel；auto-patrol 視覺對齊 |
| α — 統計核心 + chart 擴充 | ✅ 完成 | `block_linear_regression` (CI band) / `block_histogram` / `block_sort` + chart 多 y / 雙軸 / boxplot / heatmap |
| β — 半導體常用 | ✅ 完成 | `block_cpk` / `block_union` / `block_unpivot` / `block_any_trigger` + WECO 補 R3/R4/R7/R8 + 拔 C8（允許多 alert） |
| γ — 進階分析 | ✅ 完成 | `block_correlation` (long-format matrix) / `block_hypothesis_test` (t/ANOVA/χ²) / `block_ewma` |
| δ — MCP 擴展入口 | ✅ 完成 | `block_mcp_call`（通用 MCP wrapper，`mcp_name` + `args`） |
| 4-B0 — Pipeline Inputs | ✅ 完成 | pipeline.inputs 變數宣告 + `"$name"` 引用；Inspector「→ 變數」綁定 + Run Dialog 提示；validator C10_UNDECLARED_INPUT_REF |
| 4-A — Skill migration + gap-fill blocks | ✅ 完成 | `skill_migrator.py`（pattern-based）+ 3 新/擴充積木：`block_count_rows` / `block_mcp_foreach`（asyncio.gather 並發 call MCP per row）/ `block_threshold` 加 Mode B（operator==/!=/>=/<=/>/< + target）；6 skill pilot → **4 full + 2 skeleton**（v2，見 [SKILL_MIGRATION_REPORT.md](SKILL_MIGRATION_REPORT.md)） |
| 4-B — Auto patrol → pipeline | ✅ 完成 | `auto_patrols.pipeline_id + input_binding` 欄位；`AutoPatrolService._execute_single_pipeline()` dual-routes 舊 skill vs 新 pipeline；`_resolve_input_binding` 解析 `$event.xxx` / `$context.xxx` / `$ENV.xxx` / literal；Alarm 從 `result_summary.triggered + evidence_node_id preview rows` 決策；舊 skill-based patrols 向下相容 |
| **4-A/B/C UI surface** | ✅ 完成 | **Skills page** 加 🔄 Pipeline 按鈕（dry-run preview modal + 確認後導向 Builder）；**Auto-patrol form** 加 execution mode tab + Pipeline dropdown + input binding 表格；**Pipeline list** 顯示「↩ from skill #X」chip；**Phase 4-C** 加 `PIPELINE_ONLY_MODE` feature flag — `execute_skill` 工具對 LLM 隱藏，prompt 附 pipeline-only directive |
| 4 — Migration | ⏳ 未啟動 | 既有 DR → Pipeline JSON；舊 code-gen path 下線；Custom Block 實作 |
| **Agent Patterns + multi-series overlay** (2026-04-27) | ✅ 完成 | Glass Box prompt 加 **Pattern D** — 多機台/多 lot/多 recipe 用單一 source(step 篩選) + `block_filter` operator='in' + `block_chart` `color="toolID"` (3 nodes，取代 5+ source/union 9 nodes 結構)；`block_chart` SPC mode 接受 `color`，emit ChartDSL `series_field`，前端依該 field 分組 trace；`block_process_history` 加 runtime guard 拒絕 comma-separated `tool_id`/`lot_id`/`step`，hint 指向 block_filter；`update_plan` 強制每輪 build `action="create"` 限 1 次（修改用 `update`）+ frontend AIAgentPanel ref-based plan card 就地替換 |

### Phase 1 — PoC（4 週，1 人）

**目標：驗證 Pipeline JSON → 執行 → 回傳結果 可跑通。**

- [ ] DB migration：`blocks`, `pipelines`, `pipeline_runs`, `canvas_operations`
- [ ] 實作 5 個最小積木：`mcp_fetch`, `filter`, `threshold`, `consecutive_rule`, `alert`
- [ ] Pipeline Execution Engine：
  - [ ] DAG topological sort
  - [ ] 逐節點執行 + output 傳遞
  - [ ] 中間結果快取（in-memory）
  - [ ] 錯誤處理
- [ ] Pipeline Validator（§4.2 規則）
- [ ] 簡易 REST API：`POST /pipelines/execute` (傳入 Pipeline JSON → 執行)
- [ ] 用 `curl` / Postman 手動建立一條 Pipeline JSON 執行成功

**Go/No-Go 判準：**
- 能執行一條 4-node Pipeline，結果與現有 diagnostic_rule 等效
- p95 latency < 5s

### Phase 2 — MVP UI（8 週，2 人）

**目標：PE 能手動在 UI 建立 / 編輯 / 部署 Pipeline。**

- [ ] Frontend：React Flow 整合
  - [ ] 左側積木庫（從 API 讀 catalog）
  - [ ] 中央畫布（拖拽、連線、選取）
  - [ ] 右側 Inspector（from JSON Schema 自動產表單）
  - [ ] 底部 Data Preview（點節點顯示資料）
- [ ] Canvas Operation API（§6.2）— 先實作 user 端觸發（WebSocket 對應 Agent 端以 mock 替代）
- [ ] 積木庫擴充到 14 個（§3.2 完整清單）
- [ ] Pipeline CRUD（Draft 狀態）
- [ ] Pipeline 執行整合：點「執行」→ 後端跑 → 結果回傳 UI
- [ ] Status 管理 UI：Draft → Pi-run → Production 切換按鈕
- [ ] Pipeline 版本歷史頁面

**Go/No-Go 判準：**
- PE 可獨立完成「EQP-01 SPC 連續 OOC 巡檢」範例（不靠 Agent）
- 從開啟 Builder 到 Deploy 成功 < 10 分鐘

### Phase 3 — Agent 協作（6 週，1.5 人）

**目標：Agent 可以「操作 Builder」產出 Pipeline。**

- [ ] 改寫 `agent_orchestrator_v2` → `agent_orchestrator_v3`
  - [ ] 新增 Builder Tool Set（§6.2 所有 API）
  - [ ] 移除 code-gen / sandbox tool（保留給 Custom Block 路徑）
  - [ ] System prompt 動態注入積木目錄（符合 CLAUDE.md 原則）
- [ ] WebSocket bridge：Agent tool call → Frontend 動畫
- [ ] Frontend 配合：
  - [ ] Agent 操作時顯示「Agent 正在工作中」浮層
  - [ ] PE 按 Pause / Take Over 按鈕
  - [ ] Agent explain 氣泡 UI
  - [ ] Agent ask_user 選項 UI
- [ ] Copilot 整合：對話框「@builder 幫我畫...」指令進入 Agent 模式
- [ ] 使用者測試：17 個 V2 test cases 改用 Agent-Operates-Builder 模式重跑

**Go/No-Go 判準：**
- Agent 產 Pipeline 草圖成功率 ≥ 90%
- PE 接手修改率 ≤ 30%（7 成以上 Pipeline 可直接部署）

### Phase 4 — Migration（4 週，1 人）

**目標：既有 Diagnostic Rules / MCP 遷移到 Pipeline Builder，舊 code-gen path 下線。**

- [ ] 撰寫 Migration 腳本：既有 `diagnostic_rules` → Pipeline JSON
- [ ] Custom Block 實作（§7）
- [ ] 舊 `mcp_builder_service` 改為生成 Pipeline JSON（不再生 Python code）
- [ ] 舊 `execute_analysis` mega-tool 廢除，導流到 Pipeline Builder
- [ ] 文件更新 + 使用者培訓

**Go/No-Go 判準：**
- 所有既有生產中規則 100% 遷移完成
- 連續 7 天無回歸

**總工時：~22 週（約 5.5 個月曆時間，2 人平均 team）**

---

## 9. 與既有系統的遷移路徑

### 9.1 模組對照表

| 既有模組 | 新架構角色 | 遷移策略 |
|---|---|---|
| `MCP Registry` | 資料源積木底層 | ✅ 直接包裝為 BlockExecutor |
| `Skill Registry` | 複合積木 / ML 積木底層 | ✅ 直接包裝為 BlockExecutor |
| `generic_tools/` | 處理積木底層 | ✅ 每個 tool 封裝成一個 block |
| `chart_middleware` | 輸出積木（block_chart）底層 | ✅ 直接呼叫 |
| `alarm_service` | 輸出積木（block_alert）底層 | ✅ 直接呼叫 |
| `mcp_builder_service` | 改為生 Pipeline JSON | 🟡 Phase 4 重寫 |
| `diagnostic_rule_service` | 改為儲存 Pipeline JSON | 🟡 Phase 4 重寫 |
| `sandbox_service` | 僅 Custom Block 用 | 🟡 保留，限縮入口 |
| `agent_orchestrator_v2` | 升級為 v3 (Glass Box) | 🔴 Phase 3 改寫 |
| `execute_analysis` mega-tool | 廢除 | 🔴 Phase 4 下線 |
| `SPEC_pipeline_v2` 9-Stage | Stage 3–6 = Visual Pipeline | ✅ 自然對接 |

### 9.2 與 9-Stage Pipeline 的分工

```
9-Stage Pipeline (既有 SPEC):
 Stage 1: Context Load          ← Agent 自動做
 Stage 2: LLM Planning          ← Agent 自動做
 Stage 3: Data Retrieval  ─┐
 Stage 4: Data Transform   │── Visual Pipeline Builder 接管
 Stage 5: Compute          │    (可由 Agent 或 PE 操作 Builder)
 Stage 6: Presentation    ─┘
 Stage 7: Self-Critique         ← Agent 自動做
 Stage 8: Memory Update         ← Agent 自動做
 Stage 9: Response              ← Agent 自動做
```

**Stage 3–6 的 Pipeline JSON** 就是 Visual Builder 的 canvas 狀態。Agent 在這四個 stage 走的是 Glass Box 模式。

### 9.3 使用者動線變化

**現況：**
```
PE 在 Copilot 問問題
 → Agent 跑 code-gen + exec (黑盒)
 → 回傳結果 + chart
```

**新架構：**
```
PE 在 Copilot 問問題
 → Copilot 決定「這需要建 Pipeline」
 → 右側打開 Pipeline Builder
 → Agent 開始操作 Builder (PE 看著組)
 → Agent 呼叫 explain() 解釋每一步
 → PE 可隨時 Pause / Take Over
 → 完成後 PE 點 Deploy
```

---

## 10. Edge Cases & Risks

### 10.1 技術風險

| # | 風險 | 機率 | 影響 | 緩解 |
|---|---|---|---|---|
| R1 | DAG 中間結果快取 OOM（大資料集） | 高 | 中 | 取樣策略 + 只快取 preview window；正式執行用 streaming |
| R2 | Agent 操作過多 token 爆炸 | 中 | 中 | 每個 operation return 精簡；`get_state` 可指定 scope |
| R3 | WebSocket 斷線導致 canvas 狀態不一致 | 中 | 中 | 前端定期 `get_state` resync；operation 編號追蹤 |
| R4 | 積木 schema 演化破壞既有 Pipeline | 中 | 高 | Pipeline 鎖 `block_version`；升級走 migration |
| R5 | Custom Block 被濫用取代標準積木 | 中 | 中 | UI 限縮入口 + 使用率 KPI 追蹤 |
| R6 | Pipeline 執行時間過長 UX 不佳 | 中 | 中 | Async 執行 + Progress UI + streaming preview |

### 10.2 組織風險

| # | 風險 | 緩解 |
|---|---|---|
| O1 | PE 不信任 Agent 操作 Builder，還是要自己手動 | Phase 3 培訓 + Agent explain 要夠清楚 |
| O2 | 新需求來了沒對應積木 → 大量 Custom Block | PE 提報機制 + 工程師定期新增標準積木 |
| O3 | 積木版本爆炸（每個 PE 都 fork 自己的） | Production 積木限 PE admin 建立 |

### 10.3 邊界情境

- **空 Pipeline**：無 node 時 Validator 拒絕，Builder 不允許 Deploy
- **孤立節點**：不連上任何 source 或 output 時 Validator 警告
- **無限資料流**：Source 拉了 1000 萬筆 → preview 自動取樣前 1000 筆
- **Agent 陷入迴圈**：同樣的 operation 重複 5 次 → backend 強制停止 Agent
- **Production Pipeline 執行中 source MCP 掛掉**：Pipeline Run 失敗但前一次成功結果保留
- **多人同編**：目前不支援（Phase 5+），單人編輯鎖 pipeline_id

### 10.4 Rollback 計畫

每個 Phase 獨立 rollback：
- Phase 1：PoC 失敗 → 放棄新架構，繼續用 code-gen
- Phase 2：UI 失敗 → 保留 backend engine 給 Agent 用，放棄 UI
- Phase 3：Agent 整合失敗 → Builder 保留人工模式
- Phase 4：Migration 失敗 → 新舊並行（新規則用 Builder、舊規則留 code-gen）

---

## 11. 成本與 ROI

### 11.1 成本
- **工時：** ~22 週 / 5.5 個月（2 人平均）/ ~8.5–9.5 人月
- **基礎設施：** 可能需要 Redis（中間結果快取）— 若無則用 in-memory + DB spill
- **前端新套件：** React Flow (MIT) — 零成本

### 11.2 效益（對比現況）

| 面向 | 現況 | 新架構 |
|---|---|---|
| Agent 成功率 | ~70%（需重試） | ~95%（JSON 驗證強） |
| PE 新建規則時間 | > 1 hr（靠工程師） | < 15 min（自助） |
| 除錯時間 | 高（看不到中間態） | 低（Data Preview） |
| 審計可行性 | 低（exec code） | 高（DAG + version） |
| 產業合規 | 邊緣 | 符合 |
| Agent 重構後 code 減少 | — | sandbox_service 80% 可裁 |

### 11.3 策略價值
- **信任建立**：從「AI 幫你做」→「AI 陪你做」，關鍵心智轉換
- **資產沉澱**：每條 Pipeline / Block 都是組織資產（vs 一次性 code）
- **可擴展性**：新積木 = 新能力，邊際成本遞減
- **人才友善**：PE 不需要學 Python，工程師不需要懂製程也能擴充積木庫

---

## 12. 開放議題（Phase 1 前需決策）

- [ ] **Q1** — 中間結果快取用 Redis 還是 in-memory？若無 Redis 實例，要不要在此專案順便建？
- [ ] **Q2** — Pipeline JSON 版本格式（v1.0）未來升級機制？（目前建議：schema_version 欄位 + migration script）
- [ ] **Q3** — 前端 React Flow 是否要自研包裝層？還是直接用其元件？
- [ ] **Q4** — Custom Block 的 sandbox limit（512MB / 30s）是否合理？需要 PE 先看過實際使用情境
- [ ] **Q5** — Agent 操作動畫節流 200ms 是否過慢？是否需要「快速模式」讓熟練 PE 跳過動畫
- [ ] **Q6** — Multi-user 同時編輯一個 Pipeline：Phase 幾納入？先假設不支援
- [ ] **Q7** — 積木的 i18n：目前 description 寫中文，未來要不要支援英文介面？

---

## 13. 附錄：核心介面速查

### 13.1 積木 JSON Schema（縮寫）
```json
{
  "id": "...", "name": "...", "category": "source|transform|logic|output|custom",
  "version": "x.y.z", "status": "draft|pi_run|production|deprecated",
  "description": "...",
  "input_schema": [{"port": "...", "type": "...", "columns": [...]}],
  "output_schema": [{"port": "...", "type": "...", "columns": [...]}],
  "param_schema": { /* JSON Schema */ },
  "implementation": { "type": "mcp|tool|skill|python", "ref": "..." }
}
```

### 13.2 Pipeline JSON Schema（縮寫）
```json
{
  "version": "1.0",
  "name": "...",
  "nodes": [{"id", "block_id", "block_version", "position", "params"}],
  "edges": [{"id", "from": {"node","port"}, "to": {"node","port"}}]
}
```

### 13.3 Builder Tool API 速查表
| 分類 | Tool |
|---|---|
| 查詢 | `list_blocks`, `get_state`, `preview`, `validate` |
| 編輯 | `add_node`, `remove_node`, `connect`, `disconnect`, `set_param`, `move_node` |
| 歷史 | `undo`, `redo`, `commit` |
| 溝通 | `explain`, `ask_user` |

---

## 14. Phase 1 實作子規格（PoC）

> **狀態：** Approved 2026-04-18，已啟動開發
> **範圍：** 純 backend，無 UI、無 Agent 整合
> **預估：** ~8 working days

### 14.1 已決策的實作選擇

| 議題 | 決策 | 理由 |
|---|---|---|
| 中間結果快取 | **In-memory dict**（單 worker 內） | PoC 階段夠用，Phase 2+ 視需求升級 Redis |
| 模組位置 | `app/services/pipeline_builder/` | 獨立子模組，邊界清楚 |
| DB migration | **create_all + seed**（無 Alembic） | 依 CLAUDE.md 現行慣例 |
| ID 型別 | `Integer autoincrement` | 對齊既有 models 慣例（非 UUID） |
| JSON 欄位 | `Text` column（app 層 serialize） | 對齊既有 models（Postgres + SQLite 相容） |

### 14.2 對 §2.2 DB Schema 的修正（以實作為準）

原 SPEC §2.2 寫 UUID + JSONB，實作時調整為：
- `id`: `Integer primary_key autoincrement`
- JSON 欄位: `Text`，在 app 層做 `json.dumps` / `json.loads`
- FK: 對齊既有風格（`ForeignKey(..., ondelete="...")`）
- 其他欄位與 §2.2 等價（只是型別換皮）

### 14.3 檔案結構

```
fastapi_backend_service/app/
├── models/
│   ├── block.py                      ★ 新增
│   ├── pipeline.py                   ★ 新增
│   ├── pipeline_run.py               ★ 新增
│   └── canvas_operation.py           ★ 新增
├── schemas/
│   ├── block.py                      ★ 新增
│   └── pipeline.py                   ★ 新增（含 Pipeline JSON schema）
├── repositories/
│   ├── block_repository.py           ★ 新增
│   └── pipeline_repository.py        ★ 新增
├── services/
│   └── pipeline_builder/             ★ 新增子模組
│       ├── __init__.py
│       ├── executor.py               # DAG 執行器
│       ├── validator.py              # 7 條驗證規則
│       ├── cache.py                  # In-memory cache
│       ├── block_registry.py         # 從 DB 讀積木目錄
│       ├── seed.py                   # 5 個積木的 seed data
│       └── blocks/
│           ├── __init__.py
│           ├── base.py               # BlockExecutor ABC
│           ├── mcp_fetch.py
│           ├── filter.py
│           ├── threshold.py
│           ├── consecutive_rule.py
│           └── alert.py
└── routers/
    └── pipeline_builder_router.py    ★ 新增
tests/
└── pipeline_builder/                 ★ 新增
    ├── test_validator.py
    ├── test_executor.py
    ├── test_blocks.py
    └── fixtures/
        └── sample_pipeline.json
```

### 14.4 任務清單（T1–T11）

| # | 任務 | 預估 | 產出檔案 |
|---|---|---|---|
| T1 | DB models + Pydantic schemas | 0.5 day | `models/{block,pipeline,pipeline_run,canvas_operation}.py`, `schemas/{block,pipeline}.py` |
| T2 | Block & Pipeline repositories | 0.5 day | `repositories/{block,pipeline}_repository.py` |
| T3 | Block Executor base + 5 blocks | 2 days | `services/pipeline_builder/blocks/*.py` |
| T4 | In-memory cache | 0.3 day | `services/pipeline_builder/cache.py` |
| T5 | Pipeline Validator（7 規則） | 0.5 day | `services/pipeline_builder/validator.py` |
| T6 | DAG Executor | 1.5 days | `services/pipeline_builder/executor.py` |
| T7 | Block Registry | 0.5 day | `services/pipeline_builder/block_registry.py` |
| T8 | Seed data on lifespan | 0.3 day | `services/pipeline_builder/seed.py` + `main.py` 擴充 |
| T9 | REST API router | 0.5 day | `routers/pipeline_builder_router.py` |
| T10 | Unit + integration tests | 1 day | `tests/pipeline_builder/*.py` |
| T11 | 4-node sample + curl 驗證 | 0.5 day | `tests/pipeline_builder/fixtures/sample_pipeline.json` |

### 14.5 Phase 1 QA Checklist（驗收項目）

開發完成後在 `docs/phase_1_test_report.md` 逐項勾選：

#### A. DB Schema 驗收
- [ ] A1：`blocks` 表成功建立，欄位對齊 §2.2（Integer id、Text JSON）
- [ ] A2：`pipelines` 表成功建立
- [ ] A3：`pipeline_runs` 表成功建立
- [ ] A4：`canvas_operations` 表成功建立
- [ ] A5：啟動時 5 個 standard blocks 被 seed 到 `blocks` 表（idempotent — 重啟不重複）

#### B. Block Executor 驗收（T3）
- [ ] B1：`block_mcp_fetch` 能呼叫既有 MCP `get_process_history` 回傳 dataframe
- [ ] B2：`block_filter` 能用 `==`, `>`, `<`, `contains` 等運算子過濾
- [ ] B3：`block_threshold` 能標記 upper / lower / both bound 違反
- [ ] B4：`block_consecutive_rule` 能正確計算「連續 N 次」並支援 group_by
- [ ] B5：`block_alert` 能寫入 `alarms` 表
- [ ] B6：每個積木在輸入錯誤參數時回傳結構化錯誤（非 Python traceback）

#### C. Validator 驗收（T5 — 7 條規則）
- [ ] C1：Schema 合法性檢查 — 缺欄位時拒絕
- [ ] C2：Block 存在性檢查 — 不存在的 block_id 拒絕
- [ ] C3：Block Status 合規 — Draft block 不能在 Production pipeline 中使用
- [ ] C4：Port 型別相容 — dataframe 連到 scalar port 拒絕
- [ ] C5：DAG 無循環 — 有環時拒絕
- [ ] C6：參數 schema 驗證 — 參數違反 param_schema 時拒絕
- [ ] C7：起訖合理 — 無 source 或無 output 時拒絕

#### D. Executor 驗收（T6）
- [ ] D1：Topological sort 正確（多分支 pipeline）
- [ ] D2：中間結果正確傳遞（上游 output → 下游 input）
- [ ] D3：Cache hit 時不重算（同一 run 內）
- [ ] D4：節點失敗時記錄錯誤到 `pipeline_runs.node_results` 並停止下游
- [ ] D5：成功 run 完整寫入 `pipeline_runs`（含 duration、rows）

#### E. REST API 驗收（T9）
- [ ] E1：`POST /api/pipeline-builder/execute` 接收 Pipeline JSON 並執行
- [ ] E2：`GET /api/pipeline-builder/blocks` 回傳 catalog
- [ ] E3：`GET /api/pipeline-builder/runs/{id}` 回傳執行紀錄
- [ ] E4：驗證失敗時回 422 + 結構化 errors
- [ ] E5：執行失敗時回 500 + error detail（不洩漏 internals）

#### F. 端對端驗收（T11）
- [ ] F1：4-node sample pipeline（`mcp_fetch → filter → consecutive_rule → alert`）curl 執行成功
- [ ] F2：結果與現有 diagnostic_rule 等效（取一條既有規則對比）
- [ ] F3：p95 latency < 5 秒（小資料集，< 1000 rows）
- [ ] F4：Validator 能在執行前攔截 7 條錯誤情境

#### G. 測試覆蓋率（T10）
- [ ] G1：`services/pipeline_builder/` 單元測試覆蓋率 ≥ 70%
- [ ] G2：至少 1 個 integration test 跑完整 pipeline
- [ ] G3：Validator 的 7 條規則各有對應 test

#### H. 非功能需求
- [ ] H1：啟動時不阻塞 lifespan（seed 失敗不擋啟動）
- [ ] H2：Log 有足夠 context（pipeline_id、node_id、error type）
- [ ] H3：不破壞既有測試（原 test suite pass rate 不降）

### 14.6 完成後產出

1. **`docs/phase_1_test_report.md`** — 逐項 QA 結果 + 性能數據 + screenshots/logs
2. **Phase 2 補充 spec**（若 Phase 1 全通過）— 展開 §8 Phase 2 的 UI 實作細節與開放議題

---

**END OF SPEC**

此 Spec 為規劃草稿，Phase 1 已於 2026-04-18 授權啟動。
- §14 為 Phase 1 實作子規格
- Phase 2+ 仍待 Phase 1 驗收通過後再展開

---

## Phase 4 現況摘要（2026-04-18 末）

| 子階段 | 狀態 | 交付 |
|---|---|---|
| 4-A Skill Migration | ✅ | `skill_migrator.py` + 6/6 pilot（4 full + 2 skeleton）|
| 4-B Auto Patrol | ✅ | `auto_patrols.pipeline_id + input_binding` 雙軌執行 |
| 4-B0 Pipeline Inputs | ✅ | `inputs[]` + `$name` 變數 + Run Dialog |
| 4-C MVP | ✅ | `PIPELINE_ONLY_MODE` flag（llm_call + system_text patch）|
| **4-D Publishing** | ✅ | [`docs/SPEC_phase_4d.md`](./SPEC_phase_4d.md)；PR-C 整包上線（pb_published_skills + doc_generator + telemetry + Agent tools） |
| **4-lifecycle** | ✅ | 5-stage: draft/validating/locked/active/archived + pipeline_kind 分流 + C11/C12 validators |
| **4-evidence** | ✅ | Evidence 永遠 audit trail（全部 rows + triggered_row）+ Edge selection/EdgeInspector + Chart empty placeholder |
| 4-E Legacy 下線 | ⏳ | 未啟動 |

**Part 1 Cleanup**（2026-04-18）：Pipeline list 加 checkbox 批次刪除 + 每 row 🗑 按鈕（僅 draft/deprecated），清理舊 E2E 測試 pipeline。
