# Spec — v8 Per-Op Reflection (`reflect_op` 細粒度自我修正)

> 2026-05-13  
> Status: Draft, waiting for 「開始開發」  
> Builds on: v7 (reflect_plan + inspect_execution + exec_trace 已 ship)

---

## 1. Context & Objective

### 1.1 v7 status quo
v7 已 ship 的 self-correction 是「**finalize 後一次性整 plan 重寫**」：
- 整個 plan 跑完 → finalize 內 dry_run → inspect_execution 抓 3 signals → reflect_plan LLM 看整個 plan + NODE TRACE → 出**整份新 plan** → 全部 cursor 倒回 0 → 重跑

3x harness 結果：1/3 (v0 baseline 也是 1/3)，**通過品質提升**（verdict 變數值 0.0 < 2.0 而非 "error"），但通過率沒衝高。

### 1.2 v7 觀察到的問題
sidecar log 顯示 reflect_plan **會擺盪**：
```
inspect: 2 issues → reflect_plan #1 → inspect: 4 issues   ← 反思反而變多
                  → reflect_plan #2 → inspect: 4 issues
                  → MAX_REFLECT 用完 → ship partial fix
```

**Root cause**：LLM 一次重寫整 plan，修 A 時搖到 B，net 結果可能更差。整 plan 重寫 = 大 delta = 大風險。

### 1.3 v8 目標
把反思 scope 收**到單一 op**：
- op 跑完就驗 → 有錯就只改那 1 個 op（不動其他）
- LLM input 小 (1 個 op + 局部 trace) → output 小 (1 個 patch) → delta 小 → 不容易搞糟

### 1.4 為什麼這比「加大 MAX_REFLECT」好
| | 加大 MAX_REFLECT | per-op reflect (v8) |
|--|------------------|--------------------|
| 每次 LLM 工作量 | 重寫整 plan（15-25 ops） | 修 1 個 op (1 op) |
| 改 A 搖到 B 風險 | 高（看到整 plan） | 低（只看 1 op） |
| 收斂速度 | 慢 + 跌跌撞撞 | 快 + 局部 |
| LLM cost 上限 | 4×8192 tokens | 5-10 × 1024 tokens |
| 觀察性 | 「整 plan 比較差」 | 「op#N 修 1 次成功」 |

---

## 2. Architecture & Design

### 2.1 高層改動
```
v7:  add → connect → ... → finalize → inspect → reflect_plan (rewrite ALL)
v8:  add → connect → CHECK ALREADY-CAPTURED trace
                       ↓ rows=0 / error → reflect_op (LLM, patch 1 op)
                       ↓ ok → 繼續下一個 op
            → finalize → inspect → reflect_plan (保留為 safety net，處理 emergent issues)
```

### 2.2 已就位的基礎
v7 已 ship 的東西**直接複用**，不重做：
- `state.exec_trace` — call_tool_node 在 add/connect/set_param 後自動 preview，已寫入
- `ErrorEnvelope` (12 codes) — DATA_EMPTY / DATA_SHAPE_WRONG / STRUCTURE_* 等
- `trace_serializer.build_node_trace` — NODE TRACE 格式化
- `inspect_execution` + `reflect_plan` — 保留當 safety net

### 2.3 新增

#### 2.3.1 graph node: `reflect_op_node`
```python
async def reflect_op_node(state: BuildGraphState) -> dict[str, Any]:
    # 1. 取 just_done_node 的 op + envelope error + 局部 trace
    cursor = state["cursor"]
    failing_op = state["plan"][cursor - 1]  # 剛跑完的 op (cursor 已 advance)
    trace_slice = {...}  # exec_trace 中與 failing op 相關的 nodes（前 3 個 + 當前）
    
    # 2. LLM call — system prompt 簡短，只給局部資訊
    resp = await client.create(system=_REFLECT_OP_SYSTEM, messages=[...])
    decision = parse(resp)  # {"action": "patch_params" | "rollback", ...}
    
    # 3. 處理 LLM 輸出
    if decision["action"] == "patch_params":
        # 取代當前 op 的 params, 不增不減 op
        plan[cursor - 1]["params"] = decision["new_params"]
        # cursor 倒退 1 → 重 dispatch 同個 op
        return {"plan": plan, "cursor": cursor - 1, "exec_trace": cleaned}
    elif decision["action"] == "rollback":
        k = decision["rollback_to_cursor"]
        # k <= cursor - 3 限制（不能搬整 plan）
        # 清掉 op[k:] 的 result_status, exec_trace[k:] 清掉
        return {"cursor": k, "exec_trace": pruned, ...}
```

#### 2.3.2 state field 新增
```python
class BuildGraphState(TypedDict, total=False):
    # ...
    reflect_op_attempts: dict[str, int]   # {logical_id: count} per-op budget
    last_op_issue: Optional[dict]          # envelope of issue at just-done op
```

#### 2.3.3 routing 改 `_route_after_call`
```python
def _route_after_call(state):
    cursor = state["cursor"]; plan = state["plan"]
    
    # 既有：op error → repair_op (schema 級錯誤)
    if just_done_op.result_status == "error":
        return "repair_op" if attempts < MAX_OP_REPAIR else "repair_plan"
    
    # 新增：op ok 但 exec_trace 顯示語意/資料問題 → reflect_op
    just_touched = get_just_touched_logical_id(plan, cursor)
    if just_touched:
        snap = state["exec_trace"].get(just_touched)
        issue = detect_op_issue(snap)   # rows=0 / error in snap.error / etc.
        if issue:
            attempts = state["reflect_op_attempts"].get(just_touched, 0)
            if attempts < MAX_REFLECT_OP:  # = 2
                return "reflect_op"
            # budget 用完 — 帶傷往下走，最後 finalize-time inspect 還會抓
    
    # 既有：cursor < len → dispatch_op；done → finalize
    return ...
```

#### 2.3.4 detect_op_issue 判定條件
| Trigger | 來源 | Envelope code |
|---------|------|--------------|
| rows == 0 後（>=3 ops 跑過） | exec_trace[lid].rows | DATA_EMPTY |
| exec_trace[lid].error is not None | exec_trace[lid].error | DATA_SHAPE_WRONG |
| (預留) chart_spec missing 必要 field | preview snapshot | （v8.1 再加） |

**只在 cursor >= 3 才開始檢查** — 前 1-2 個 source op 還沒 connect input，rows=0 可能是正常中間態。

### 2.4 reflect_op LLM 介面

#### 2.4.1 system prompt（精簡版，~800 tokens）
```
你是 op-level 修正器。你只看到 1 個失敗的 op 跟它前 2-3 個 upstream op 的執行結果。
你的任務：判斷該怎麼修這個 op，不要動其他 op。

兩個選擇:
  A. patch_params: 改這個 op 的 params（params 寫法跟 add_node/set_param 一樣）
  B. rollback: 如果 root cause 在 upstream 第 K 個 op，回到 K 重跑（最多 K = N-3）

輸出 JSON:
  {"action": "patch_params", "new_params": {...}, "reason": "..."} 
  OR
  {"action": "rollback", "rollback_to_cursor": K, "new_params_for_K": {...}, "reason": "..."}

只看 block description / param_schema 找約束，不要憑空編值。
```

#### 2.4.2 user message
```
USER PROMPT: {state.instruction[:400]}

FAILING OP at cursor {N}:
  {op_dict pretty-printed}

UPSTREAM TRACE (op N-3 to N):
{build_node_trace(plan[N-3:N+1], exec_trace[...])}

ISSUE detected at op {N}:
  code: {envelope.code}
  message: {envelope.message}
  expected: {envelope.expected}
  rationale: {envelope.rationale}

Block schema for {op.block_id}:
  {block_registry[op.block_id].param_schema}

請出修正方案 (JSON only).
```

### 2.5 與 reflect_plan 的關係

| 階段 | 處理者 | scope | 觸發 |
|------|--------|------|------|
| 跑 op 時 | repair_op (既有) | 改 op param | ToolError raise (schema 不過) |
| 跑 op 後 | **reflect_op (新)** | 改 op param / rollback | exec_trace 顯示 rows=0 / data error |
| 整 plan 後 | reflect_plan (既有) | 重寫整 plan | finalize-time inspect (emergent: single_point_chart, structural) |

reflect_op + reflect_plan 不衝突 — reflect_op 修 local issue 修不掉就 fallthrough，finalize-time 還有最後一道 inspect_execution + reflect_plan。

---

## 3. Step-by-Step Execution Plan

### Phase A: state + routing 基礎 (~45 min)
1. `state.py` 加 `reflect_op_attempts: dict[str, int]` + `last_op_issue: Optional[dict]`
2. `state.py initial_state` 初始化新欄位
3. `nodes/execute.py` 加 `_detect_op_issue(snap)` helper（rows=0 / error 判定）

### Phase B: reflect_op_node (~75 min)
1. 新 `nodes/reflect_op.py`，包含 `_REFLECT_OP_SYSTEM` + LLM call
2. 用既有 trace_serializer 取 upstream slice
3. 處理兩種 action: patch_params (cursor--) + rollback (cursor = K + 清 trace[K:])
4. tracer integration (record_llm + record_step)

### Phase C: graph wiring (~30 min)
1. `graph.py` add_node("reflect_op", reflect_op_node)
2. 改 `_route_after_call`: op ok 後 check exec_trace → 有 issue 且 budget 沒滿 → "reflect_op"
3. add_edge: "reflect_op" → "call_tool" (cursor 已倒退，重 dispatch + 重跑)
4. MAX_REFLECT_OP = 2 constant

### Phase D: rollback 細節 (~30 min)
1. rollback action: clear `exec_trace` 從 K 之後的 entries
2. clear `plan[K..N].result_status` (mark for rerun)
3. 不重置 logical_to_real — 因為節點還在 canvas，只是 param 要改
4. 限制 K >= N - 3（不能往回太遠）

### Phase E: smoke + 3x harness (~30 min)
1. Unit-test _detect_op_issue
2. Unit-test reflect_op patch_params + rollback decisions
3. Deploy to EC2 + restart sidecar
4. Run harness 3x; expect 2-3 / 3 pass given the architectural improvement

**Total est: 3-3.5 hours**

---

## 4. Edge Cases & Risks

### 4.1 LLM patch 也錯
- reflect_op #1 fail → reflect_op #2 fail → budget 滿 → fallthrough 到下一個 dispatch_op，帶傷往下走
- 最後 finalize-time inspect 還會抓 emergent → reflect_plan safety net

### 4.2 rollback 無限循環
- 限制：rollback_to_cursor K 必須 < 當前 cursor
- 每個 op 的 reflect_op_attempts 各自獨立計數，不共用
- 如果 op@K 也被 rollback 過，加碼 attempts，2 次後 ban

### 4.3 preview 慢
- 已有設計（v7）：preview sample_size=5（很快）
- preview 跑不出來時 `_snapshot_node` 已 graceful: error field 填，不會 block 流程

### 4.4 reflect_op 跟 repair_op 競爭
- 兩個都在 op 後 fire，但條件不同：
  - repair_op: op result_status == "error" (ToolError raise)
  - reflect_op: op result_status == "ok" 但 exec_trace 顯示 data issue
- 互斥 — graph route 用 if/elif

### 4.5 增加的 LLM cost
- 估每 build: per-op reflect 0-3 次（多數 op 沒問題）+ 最終 reflect_plan 0-2 次
- 比起 v7 (固定 0-2 次 reflect_plan 全 plan 重寫)，**總 token 可能差不多甚至少**
  - reflect_op 1 次 ≈ 1500 tokens；reflect_plan 1 次 ≈ 60K tokens (整 catalog)
  - 1 次 reflect_plan = 40 次 reflect_op，所以 budget tradeoff OK

---

## 5. 不做的事

- ❌ 不改 plan_node — 第一次 plan 出問題還是走 repair_plan / reflect_plan（既有路徑）
- ❌ 不改 ErrorEnvelope — 既有 12 codes 夠用
- ❌ 不為 reflect_op 寫 catalog-aware system prompt — 改 1 個 op 不需要看整 catalog，省 token
- ❌ 不刪 reflect_plan — finalize-time 還是要 safety net 抓 emergent issues
- ❌ 不在 set_param 後馬上 reflect — set_param 不會獨立 fail（總是搭配 add/connect）

---

## 6. 觀察指標

成功定義：
1. harness 3x pass rate ≥ 2/3（v7 是 1/3）
2. reflect_plan 平均觸發次數降低（因為 reflect_op 先處理掉 local issues）
3. 不引入新 regression（既有過的 case 還是要過）

如果 (1) 沒達成 → reflect_op 收斂機制要再 tune (e.g. 加大 attempts, 改 prompt)
如果 (2) 反而升高 → 表示 reflect_op 沒抓到問題，或 LLM 不接受 patch 形式

---

## 7. Out of Scope（未來再做）

- chart_spec missing field 偵測（v8.1）
- Cross-op issue（n3 看 n2，但發現 root cause 在 n1）由 rollback 處理，rollback distance > 3 留 v9
- streaming reflect (邊修邊 SSE 給 frontend 顯示「fixing op#N...」) 留 v9

---

## 8. 授權

請回「開始開發」確認進入實作。
