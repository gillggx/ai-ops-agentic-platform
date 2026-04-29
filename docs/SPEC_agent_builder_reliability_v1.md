# SPEC — Agent / Pipeline Builder Reliability v1

**Date:** 2026-04-30
**Status:** Implemented + Deployed
**Author:** Gill (Tech Lead) + Claude
**Trigger:** 2026-04-29~30 連續多輪 builder mode 測試發現三類失敗（卡死 / 結果消失 / recursion limit），全部與 orchestrator_v2 ↔ Glass Box ↔ executor 之間的 mode-aware 規則不一致有關。

---

## 0. Motivation

### 0.1 觀察到的痛點

三個獨立 bug 在連續 session 內接連被使用者撞到，根因都指向「同一個 orchestrator 處理 chat 與 builder 兩種使用情境，但 prompt 與 render 路徑沒完全 mode-aware」：

| # | 觀察 | 觸發條件 |
|---|---|---|
| **B-1** | Builder mode 卡死在「計畫 0/N」 | 使用者問「檢查該站點 SPC，連 2 次 OOC」；agent 把 plan p1 設成「確認查詢範圍和需求」就停下等使用者 |
| **C-1** | Chat mode pipeline 設計完看不到、無法編輯 | 使用者在 chat 問「畫個 EQP-01 STEP_001 SPC chart」；build_pipeline_live 成功 + auto-run 跑完，但 chat thread 沒任何 card / 按鈕 |
| **R-1** | Builder mode `Recursion limit of 25 reached without hitting a stop condition` | Glass Box build 出 7-node pipeline，auto-run 失敗（generic unpivot 用 `chart_type` 名稱跟 downstream group_by 對不上），orchestrator 在多輪 retry 中撞到 LangGraph 預設遞迴上限 |

每一個都讓使用者看到「agent 看似在動但拿不到結果」的不可信任感。三個放在一起來解才有 leverage — 改完一個只是堵了一個漏洞。

### 0.2 設計原則

1. **Mode-aware 是核心**：chat / builder 是兩種使用情境，prompt 規則必須在最早的位置分支（`mode = state.get("mode") or "chat"`），不要讓兩邊規則疊加產生衝突。
2. **「不能呼叫的工具」不能寫進 prompt**：`declare_input` / `propose_pipeline_patch` 都被隱藏；prompt 提到只會讓 LLM 試呼叫然後失敗。
3. **Render path 不能假設 user 看到了什麼**：chat 沒 canvas overlay，pipeline 必須以 inline card 呈現；builder 有 canvas，反而不能再 emit card 重複。
4. **Recursion limit 是工程選擇，不是預設**：用 `60`（≈30 tool call）給 1 次 retry 留 head-room，但讓 anti-pattern guard 守住下限。
5. **Block 設計要為 LLM 命名「友善」**：generic unpivot 太抽象，LLM 必踩 column naming 坑。專用 block + 固定 output 欄位名是 prompt-engineering 換成 block-engineering 的代價最低做法。

---

## 1. Architecture & Design

### 1.1 受影響的元件

```
┌─────────────────────────────────────────────────────────────┐
│  python_ai_sidecar/agent_orchestrator_v2/                    │
│  ├── orchestrator.py        ★ recursion_limit 25 → 60        │
│  ├── nodes/load_context.py  ★ 全段 mode-aware；builder 重寫    │
│  └── nodes/tool_execute.py  ★ chat mode pb_pipeline card emit │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  python_ai_sidecar/pipeline_builder/blocks/                   │
│  ├── spc_long_form.py       ★ NEW — process_history → SPC long│
│  ├── apc_long_form.py       ★ NEW — process_history → APC long│
│  └── __init__.py            ★ BUILTIN_EXECUTORS 加 2 行       │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  java-backend/src/main/resources/db/migration/                │
│  └── V6__spc_apc_long_form_blocks.sql  ★ pb_blocks rows       │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  aiops-app/src/components/copilot/PbPipelineCard.tsx          │
│  (no change — already supports the card we now emit)          │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 B-1 — Builder Mode prompt 重整

**問題**：原本 prompt 結構是「先給通用規則，後段再 override」，五處衝突疊加：

| 衝突 | 位置（before） | 行為 |
|---|---|---|
| Plan template 寫死「確認需求 → 取資料 → ...」 | load_context.py:71-102 | builder 模式 LLM 也照抄 → p1 變「確認需求」→ 等使用者 |
| `PIPELINE_ONLY_MODE` 教 LLM「先 search_published_skills + 等使用者同意才 build」 | load_context.py:128-133 | 跟 builder 的「直接 build」直接衝突 |
| Builder section 教 LLM 呼叫 `declare_input` | load_context.py:243-244 | 這個 tool 在 orchestrator_v2 不存在，是 Glass Box sub-agent 的 op |
| 「proceed build」沒對應到具體 tool | load_context.py:242 | LLM 不知道「proceed build」=「呼 build_pipeline_live(goal=…)」 |
| `Use<current_state>` 教 LLM 「不要呼 build_pipeline_live」 | load_context.py:213-225 | 跟 builder 直接衝突 |

**Fix**：
1. 把 `mode = state.get("mode") or "chat"` 提前到 line 70 上下，所有下游分支共用
2. Plan-First 改 mode-aware：builder 用 3-item template（規劃結構 / build / 收尾），不再有「確認需求」字眼
3. PIPELINE_ONLY_MODE / Use<current_state> 兩段都包在 `if mode != "builder"` 裡
4. Builder section 全文重寫，開頭加「⚠️ 以下覆蓋上方 Plan-First / Pipeline-Only / Use<current_state> 規則」
5. 拿掉所有 `declare_input` 字眼，改成 4 條 routing examples（user msg → tool call）
6. 加 anti-pattern 黑名單（mark plan done with note 「等待使用者」/ 連續呼 build_pipeline_live）
7. 既有的 [tool_execute.py:529-563 結構性 guard](python_ai_sidecar/agent_orchestrator_v2/nodes/tool_execute.py#L529-L563) 維持作為 backstop

### 1.3 C-1 — Chat Mode pb_pipeline render_card

**問題**：[tool_execute.py:701-733](python_ai_sidecar/agent_orchestrator_v2/nodes/tool_execute.py#L701-L733) 處理 `build_pipeline_live` 成功後只做兩件事：
- persist snapshot 到 agent_sessions
- emit pb_glass_done / pb_run_done 兩個 SSE event

**註解寫的**："No render card — the overlay already showed everything live."

但這只在 builder mode 成立（canvas overlay 顯示 Glass Ops live）。Chat mode 沒 canvas，pipeline 直接從畫面消失，使用者看到 agent 說「pipeline 建好了」但找不到任何結果或編輯入口。

**Fix**：在 `if tool_name == "build_pipeline_live" ... status in {finished, success}` 區塊內，snapshot persist 之後加：

```python
if state.get("mode") != "builder" and pipeline_json:
    ar = result.get("auto_run") or {}
    new_render_cards.append({
        "type": "pb_pipeline",
        "pipeline_json": pipeline_json,
        "node_results": ar.get("node_results") or {},
        "result_summary": ar.get("result_summary"),
        "run_id": None,
    })
```

Card shape 對齊既有 [PbPipelineCardData / PbPipelineAdHocCard](aiops-app/src/components/copilot/PbPipelineCard.tsx)；frontend 自動 render「Edit in Builder / Save as Skill / Expand」三個 CTA。

### 1.4 R-1 — Recursion limit + Auto-run retry guidance

**問題**：LangGraph 預設 `recursion_limit = 25` 太緊，builder turn 涉及 update_plan + build_pipeline_live + auto-run 失敗 retry 至少 14 hops；加上 LLM 自己亂打 update_plan 重試會輕易撞牆。撞牆後使用者看到 raw error 訊息，體驗很糟。

**Fix（兩處同時動）**：

1. **Bump recursion_limit**（[orchestrator.py](python_ai_sidecar/agent_orchestrator_v2/orchestrator.py)）：
   ```python
   config = {
       "configurable": {...},
       "recursion_limit": 60,    # was implicit default 25
   }
   ```
   60 hops ≈ 30 tool call，1 次 retry 的工作量綽綽有餘；不放更高（100+）是因為真死循環時 anti-pattern guard 會在 30 hops 內收斂。

2. **Builder retry guidance**（[load_context.py builder section](python_ai_sidecar/agent_orchestrator_v2/nodes/load_context.py)）：
   ```
   ## Auto-Run 失敗處理（最多 1 次 retry）
   build_pipeline_live 回 success 但伴隨 pb_run_error
     → 再呼 1 次 build_pipeline_live，goal 寫『修正 nodeX 的 ___ 參數』
     → 仍失敗 → 純文字告訴使用者並 stop
     → ❌ 不要呼第三次、不要 update_plan 重跑（會撞 limit）
   ```

   **注意**：`propose_pipeline_patch` 已被隱藏（_LLM_HIDDEN_TOOLS），retry 統一走 build_pipeline_live with targeted goal — sub-agent 看到 canvas 會 in-place edit，不重建。

### 1.5 SPC / APC Long-form Blocks（消除 R-1 的 root cause）

R-1 的觸發點是 Glass Box sub-agent 用 generic `block_unpivot` 拼湊 SPC reshape，自己決定 `variable_name='chart_type'`，但下游 groupby 寫 `chart_type` 而拿到的 column 是 unpivot 預設的 `variable`（或別的拼字）→ COLUMN_NOT_FOUND → auto-run fail → retry → recursion limit。

**根本性修法**：兩個 zero-param 專用 block，**output 欄位名固定**：

| Block | Output columns |
|---|---|
| `block_spc_long_form` | `chart_name, value, ucl, lcl, is_ooc` + id 欄位 (eventTime, toolID, lotID, step, …) |
| `block_apc_long_form` | `param_name, value` + id 欄位（含 `apc_id`） |

**經典 pipeline 寫進 description**：
```
process_history(step=$step)
  → spc_long_form
  → consecutive_rule(flag_column=is_ooc, count=2,
                     sort_by=eventTime, group_by=chart_name)
  → alert(severity=HIGH)
```

LLM 看 catalog 直接命中（名稱含 `spc` / `apc` keyword + description 開頭就有 ✅ 範例），不用拼湊；output 名固定，下游 group_by 不會猜錯。

V6 migration 同時更新 `block_consecutive_rule.description`，append 一段「Multi-metric pattern」指向新 block，讓 LLM 從 consecutive_rule 角度反向找到正確 reshape 路徑。

---

## 2. Implementation Detail

### 2.1 SpcLongFormBlockExecutor

[python_ai_sidecar/pipeline_builder/blocks/spc_long_form.py](python_ai_sidecar/pipeline_builder/blocks/spc_long_form.py)

```python
_SPC_FIELD_RE = re.compile(r"^spc_(.+)_(value|ucl|lcl|is_ooc)$")
_ID_COLUMNS_DEFAULT = ("eventTime", "toolID", "lotID", "step",
                        "spc_status", "fdc_classification")

class SpcLongFormBlockExecutor(BlockExecutor):
    block_id = "block_spc_long_form"

    async def execute(self, *, params, inputs, context):
        df = inputs.get("data")
        # Group spc_*_<field> columns by chart name → one frame per chart →
        # concat. Each frame has [id_cols..., chart_name=<chart>, value, ucl, lcl, is_ooc].
```

**Edge cases**：
- empty input → return empty DF with declared schema (downstream handle gracefully)
- 沒有任何 `spc_*` column → raise `NO_SPC_COLUMNS`（user 上游選錯 object_name）
- partial fields（只有 value 沒 ucl）→ 缺的填 `pd.NA`

### 2.2 ApcLongFormBlockExecutor

[python_ai_sidecar/pipeline_builder/blocks/apc_long_form.py](python_ai_sidecar/pipeline_builder/blocks/apc_long_form.py)

```python
_APC_PREFIX = "apc_"
_APC_META_COLS = {"apc_id"}  # id meta — kept as id col, not reshaped

class ApcLongFormBlockExecutor(BlockExecutor):
    block_id = "block_apc_long_form"

    async def execute(self, *, params, inputs, context):
        param_cols = [c for c in df.columns
                      if c.startswith(_APC_PREFIX) and c not in _APC_META_COLS]
        out = df.melt(id_vars=present_id_cols, value_vars=param_cols,
                      var_name="param_name", value_name="value")
        out["param_name"] = out["param_name"].str.removeprefix(_APC_PREFIX)
```

**Edge case**：自動剝掉 `apc_` 前綴 — 使用者寫 `group_by=param_name` 會看到 `Pressure / Temperature`，不是 `apc_Pressure`。這對 alert title 可讀性也有幫助。

### 2.3 V6 Flyway migration

[V6__spc_apc_long_form_blocks.sql](java-backend/src/main/resources/db/migration/V6__spc_apc_long_form_blocks.sql)：

- 兩個 INSERT，`ON CONFLICT (name, version) DO UPDATE` — 等冪
- description 用 PG dollar-quoted string `$desc$...$desc$`（多行 + 含 emoji）
- UPDATE `block_consecutive_rule` 用 `WHERE description NOT LIKE '%Multi-metric pattern (PR-V6)%'` guard，重跑也只 append 一次

**部署注意**：prod 環境 Flyway disabled（`application-prod.yml: flyway.enabled: false`），V6 跟前面 V1~V5 一樣需要手動執行：
```bash
ssh ec2 "sudo -u postgres psql -d aiops_db -f /path/to/V6.sql"
ssh ec2 "sudo -u postgres psql -d aiops_db -c \"INSERT INTO flyway_schema_history ... VALUES (..., '6', ...)\""
```

### 2.4 Frontend 變更

零變更。[PbPipelineCard.tsx](aiops-app/src/components/copilot/PbPipelineCard.tsx) 早就支援 `pb_pipeline` 卡片型別 + Edit/Save/Expand 按鈕；[AIAgentPanel.tsx:959](aiops-app/src/components/copilot/AIAgentPanel.tsx#L959) 也已經會處理 tool_done 帶的 card。Backend 補 emit 之後整條鏈通了。

---

## 3. Migration & Rollout

### 3.1 已部署狀態（2026-04-30）

| 改動 | 狀態 |
|---|---|
| Python sidecar code | ✅ 已 push + sidecar restart |
| Java jar | ✅ 已 rebuild + restart |
| V6 SQL | ✅ 手動執行 + flyway_schema_history 補 row |
| 前端 | 零改動，沿用 [PbPipelineCard](aiops-app/src/components/copilot/PbPipelineCard.tsx) |

### 3.2 回歸驗證 checklist

| Case | Mode | 預期 |
|---|---|---|
| 「畫個 EQP-01 STEP_001 SPC chart」 | chat | PbPipelineCard 出現於 chat thread，含 Edit/Run/Expand |
| 「現在有幾個 alarm」 | chat | 直接從 `<current_state>` 文字回答（不開 pipeline） |
| 跑 published skill | chat | `pb_pipeline_published` card（既有路徑不影響） |
| 「檢查該站點所有 SPC charts 連 2 次 OOC」 | builder | 4-node：`process_history → spc_long_form → consecutive_rule → alert` |
| 「STEP_001 任一 APC 參數連 3 次 > 100」 | builder | 5-node：`+ threshold` |
| 故意丟壞 input（step="不存在"） | builder | 1 次 retry 後純文字 stop，不撞 recursion limit |

### 3.3 監控信號

| 指標 | 期望 |
|---|---|
| orchestrator_v2 `Recursion limit ... reached` 錯誤頻率 | 大幅下降（從 multi-per-day → 接近 0） |
| Glass Box 裡 generic `block_unpivot` 的使用率 | SPC/APC 場景下顯著降，改用 long_form |
| Chat mode build 後使用者點 Edit-in-Builder 的比率 | 從 0%（看不到按鈕）變正常 |
| auto-run 第 1 次成功率 | 上升（column naming 不再亂） |

---

## 4. Edge Cases & Risks

| 風險 | 處理 |
|---|---|
| `recursion_limit=60` 變相鼓勵 LLM 多動作 | builder retry guidance 限 1 次 + tool_execute anti-pattern guard 限制無意義 update_plan 迴圈 |
| `pb_pipeline` card 在 chat 顯示位置 | 已驗證 [AIAgentPanel.tsx:959-983](aiops-app/src/components/copilot/AIAgentPanel.tsx#L959-L983) 處理 |
| build_pipeline_live `status='failed'`（Glass Box hit MAX_TURNS） | tool_execute 條件 `status in {"finished","success"}`，不會 push 空 card |
| Hybrid pipeline auto_run skipped | card 仍 push，使用者可去 builder 手動 Run |
| ON_DUTY 角色（無 build_pipeline_live tool） | 路徑不會走到 builder mode 分支 |
| Glass Box sub-agent 自己 50 turn 也快撞限 | 短期：spc/apc_long_form 讓 sub-agent 不用湊 unpivot+rename，turn 用量降；長期再考慮 sub-agent prompt 優化 |
| 既有 pipeline 用 `block_unpivot` 處理 SPC 場景 | 不破壞 — generic unpivot 仍存在；新 block 是平行選項 |
| Chart name 有特殊字元（中文/dot） | melt 後 chart_name 是 string，不影響 group_by |
| APC long_form 含非數值欄位（status string） | 第一版只取 `apc_<param>` 純值欄位；status 類另論 |

---

## 5. 不在此 Spec 範圍

- FDC / EC / Recipe 的 long-form blocks（YAGNI，等使用者要再加）
- Glass Box sub-agent 自己的 prompt 優化（agent_builder/prompt.py）
- ContinuationCard「再給 8 步」誤觸 takeover 的視覺 bug（前面查過 onClick 沒問題，需重現）
- Cron 5/6-field 標準化（boot warning，獨立議題）

---

## 6. References

- [SPEC_pipeline_builder.md](./SPEC_pipeline_builder.md) — block catalog 主文件，已同步加入 V6 兩個新 block
- [SPEC_glassbox_continuation.md](./SPEC_glassbox_continuation.md) — Glass Box MAX_TURNS pause/continue 機制
- [SPEC_phase_5_ux_5to7.md](./SPEC_phase_5_ux_5to7.md) — build_pipeline_live + Glass Ops 串流體系
- [python_ai_sidecar/SPEC.md](../python_ai_sidecar/SPEC.md) — sidecar 整體架構（block 數已從 27 → 29）

---

## Changelog

| Date | Change |
|---|---|
| 2026-04-30 | Initial draft + implementation + deploy |
