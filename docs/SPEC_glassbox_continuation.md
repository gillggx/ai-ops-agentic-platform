# SPEC — Glass Box MAX_TURNS Continuation Prompt

**Date:** 2026-04-27
**Status:** Draft — pending approval
**Author:** Gill (Tech Lead) + Claude
**Trigger:** 2026-04-27 測試「STEP_001 最近怎樣？」→ 「趨勢圖表」path，Glass Box 跑到 MAX_TURNS=50 才一步沒呼 finish 就硬 fail，但 partial result 已經 95% 完成（13 nodes、6 charts、plan 6/7、40 ops）。

---

## 0. Motivation

### 0.1 觀察到的痛點

Glass Box agent 的 `MAX_TURNS=50` 是硬限制 — hit 之後直接 `mark_failed("Reached MAX_TURNS=50 without calling finish()")`。但實際上：

- 41% 的測試（`docs/QA_CHECKLIST_NEXT_PHASE.md` 估）卡在「最後一步 validate / finish」沒呼到
- Pipeline 多半已經 build 好（canvas 正確顯示），只差一個 tool call
- 使用者看到 `EXECUTION FAILED` 心裡 OS：「我看你都做了，再讓你跑一下會死嗎」

直接調高 MAX_TURNS 不行：
- 如果 agent 在 loop 卡死（同一 tool 重試），更高的上限只會燒更多 token
- 統計上 50 turns 對「正常 build」夠用；hit 50 = **異常**，但異常分兩種：
  - **接近完成 / 邊界 case**（再 5-10 turn 能收）→ 應該續跑
  - **真實卡死 / loop**（再給 N turn 也沒用）→ 應該停手

→ **不能讓 backend 自己判斷**。Backend 不知道 user 願意付多少額外 cost / 等多久。**讓 LLM 自評 + 把選擇權交回 user**。

### 0.2 設計目標

- MAX_TURNS hit 不再是 fail，是 **pause + ask**
- LLM 給簡短自評：已完成什麼、還剩什麼、估計再幾步
- User 三選一：**再給 N 步 / 我自己接手 / 停手用現有結果**
- 連續 N 次 MAX_TURNS 才硬 fail（防無限循環）

---

## 1. Architecture & Design

### 1.1 Sidecar 改動

#### `agent_builder/orchestrator.py`

```python
MAX_TURNS = 50                      # 不變
MAX_TURNS_PER_CONTINUATION = 20      # continuation 接續時的額外 budget
ABSOLUTE_MAX_TURNS = 120             # 50 + 20×3 + 安全閥；超過就硬 fail
```

`stream_agent_build()` MAX_TURNS hit 處改：

```python
# Before:
session.mark_failed(f"Reached MAX_TURNS={MAX_TURNS} without calling finish()")

# After:
total_turns_used = session.continuation_count * MAX_TURNS_PER_CONTINUATION + MAX_TURNS

if total_turns_used >= ABSOLUTE_MAX_TURNS:
    session.mark_failed(f"Reached ABSOLUTE_MAX_TURNS={ABSOLUTE_MAX_TURNS} after {session.continuation_count} continuations")
    yield StreamEvent(type="done", data={...})
    return

# Self-assessment LLM call (cheap, max_tokens=200)
assessment = await _self_assess_progress(session, client)

# Pause session — persist state to Java
await _pause_session_to_java(session, java_client)

# Emit continuation_request
yield StreamEvent(
    type="continuation_request",
    data={
        "session_id": session.session_id,
        "turns_used": total_turns_used,
        "ops_count": len(session.operations),
        "completed": assessment["completed"],   # list[str], ≤6 items
        "remaining": assessment["remaining"],   # list[str], ≤4 items
        "estimate": assessment["estimate"],      # int, suggested next budget
        "options": [
            {"id": "continue", "label": f"再給 {assessment['estimate']} 步", "additional_turns": assessment["estimate"]},
            {"id": "takeover", "label": "我自己接手"},
            {"id": "stop", "label": "停手用現有結果"},
        ],
    },
)
yield StreamEvent(type="done", data={"status": "paused", ...})
return
```

新 helper `_self_assess_progress(session, client)`:

```python
async def _self_assess_progress(session, client) -> dict:
    """One small LLM call asking the agent to summarize where it is."""
    prompt = (
        f"你跑了 {MAX_TURNS} turns 還沒呼 finish。基於目前 pipeline state 跟 conversation，"
        "用 JSON 回答（不要 markdown）：\n"
        '{"completed": ["≤20 字 done item × 最多 6 個"], '
        '"remaining": ["≤20 字 todo item × 最多 4 個"], '
        '"estimate": <int 5-20，預估還需幾 turn 完成>}'
    )
    # ... call client with last 4 messages + this prompt + max_tokens=200
    return parsed_json
```

#### `agent_builder/session.py`

新增 fields on `AgentBuilderSession`:

```python
class AgentBuilderSession:
    # ... existing
    status: Literal["running", "finished", "failed", "cancelled", "paused"]  # add "paused"
    continuation_count: int = 0  # how many times user said "continue"
```

`pause_to_java()` / `resume_from_java()` — 序列化 session 給 Java 存（用既有 `agent_sessions` table 的 `state_json` 欄位）。

### 1.2 新 endpoint: `/internal/agent/build/continue`

`python_ai_sidecar/routers/agent.py` 加：

```python
class ContinueBuildRequest(BaseModel):
    session_id: str
    additional_turns: int = 20  # capped to MAX_TURNS_PER_CONTINUATION

@router.post("/build/continue")
async def build_continue(req: ContinueBuildRequest, caller: ...) -> EventSourceResponse:
    # 1. Load paused session from Java
    session = await resume_from_java(req.session_id, java_client)
    if session.status != "paused":
        raise HTTPException(409, "session not in paused state")

    # 2. Increment continuation_count
    session.continuation_count += 1
    session.status = "running"

    # 3. Re-run stream_agent_build with the same registry — orchestrator will
    #    use total_turns_used to compare against ABSOLUTE_MAX_TURNS
    async def _gen():
        async for ev in stream_agent_build(session, registry, ...):
            yield ev
    return EventSourceResponse(_gen())
```

### 1.3 Java proxy

`AgentProxyController.java` 加：

```java
@PostMapping(path = "/build/continue", produces = TEXT_EVENT_STREAM_VALUE)
@PreAuthorize(Authorities.ADMIN_OR_PE)
public SseEmitter buildContinue(@RequestBody Map<String, Object> body,
                                @AuthenticationPrincipal AuthPrincipal caller) {
    String sessionId = asString(body.get("sessionId"));
    if (sessionId == null) sessionId = asString(body.get("session_id"));
    Integer turns = asInt(body.get("additionalTurns"));
    if (turns == null) turns = asInt(body.get("additional_turns"));

    Map<String,Object> req = Map.of("session_id", sessionId, "additional_turns", turns != null ? turns : 20);
    return bridgeSse(sidecar.postSse("/internal/agent/build/continue", req, caller), "build_continue");
}
```

### 1.4 Frontend

#### 新 component `<ContinuationCard>`

`aiops-app/src/components/copilot/ContinuationCard.tsx`：

```tsx
interface ContinuationData {
  sessionId: string;
  turnsUsed: number;
  opsCount: number;
  completed: string[];
  remaining: string[];
  estimate: number;
  options: Array<{ id: string; label: string; additionalTurns?: number }>;
}

function ContinuationCard({ data, onPick }: { data: ContinuationData; onPick: (option: any) => void }) {
  return (
    <div /* ... 風格跟 ClarifyCard 一致 */>
      <div>⏸ 已跑 {data.turnsUsed} 步、{data.opsCount} 個 ops，估計再 {data.estimate} 步可完成。</div>
      <div>
        <strong>已完成：</strong>
        <ul>{data.completed.map(c => <li key={c}>✓ {c}</li>)}</ul>
        <strong>還剩：</strong>
        <ul>{data.remaining.map(r => <li key={r}>○ {r}</li>)}</ul>
      </div>
      <div>
        {data.options.map(opt => <button onClick={() => onPick(opt)}>{opt.label}</button>)}
      </div>
    </div>
  );
}
```

#### `AIAgentPanel` (chat path) + `AgentBuilderPanel` (Pipeline Builder path) dispatcher

新 SSE event case：

```ts
case "continuation_request": {
  const data: ContinuationData = ev.data;
  // Stash session_id so the next pick knows which session to resume
  pausedSessionRef.current = data.sessionId;
  setChatHistory(prev => [...prev, {
    id: nextId(), role: "continuation", content: "",
    continuation: data,
  }]);
  break;
}
```

ContinuationCard onPick 處理：

```tsx
const handlePick = async (option) => {
  if (option.id === "stop") {
    // Just close — current state is on canvas
    return;
  }
  if (option.id === "takeover") {
    router.push(`/admin/pipeline-builder?resume=${data.sessionId}`);
    return;
  }
  // option.id === "continue"
  await fetch("/api/agent/build/continue", {
    method: "POST",
    body: JSON.stringify({
      session_id: data.sessionId,
      additional_turns: option.additionalTurns ?? 20,
    }),
  });
  // SSE stream继续，might emit another continuation_request
};
```

---

## 2. Step-by-Step Execution Plan

| Order | Item | Effort | Notes |
|---|---|---|---|
| 1 | session.py：add `status="paused"` + `continuation_count` + serialize/resume | 0.25 day | Java agent_session table 應該已經能存 |
| 2 | orchestrator.py：MAX_TURNS hit → self-assess + emit continuation_request | 0.25 day | |
| 3 | New endpoint `/internal/agent/build/continue` | 0.25 day | mostly mirroring `/build` |
| 4 | Java proxy `/api/v1/agent/build/continue` | 0.1 day | record + Map handler |
| 5 | Frontend `ContinuationCard` + SSE dispatcher case | 0.5 day | both AIAgentPanel + AgentBuilderPanel |
| 6 | Test：人為設 `MAX_TURNS=10` 跑 5 機台 → ContinuationCard → 點「再給 20 步」→ 完成 | 0.15 day | |

**Total ≈ 1.5 day**.

---

## 3. Edge Cases & Risks

| Risk | 嚴重 | Mitigation |
|---|---|---|
| Session state 大（messages 50+ 條）→ Java agent_session 欄位塞不下 | 🟡 Med | 既有 schema `state_json` 是 JSONB，pg JSONB 上限 1GB；50 messages × 5KB 完全沒問題 |
| Self-assessment LLM call 噴錯 / 回非 JSON | 🟢 Low | catch + fall back to generic「估 10 步」+ default options |
| User 點「再給 20 步」後 agent 又卡死 → 連續 prompt 很煩 | 🟡 Med | `ABSOLUTE_MAX_TURNS=120` 硬上限；連 3 次 continuation 還沒 finish 就 takeover 不問 |
| 「我自己接手」session_id 跨頁面傳遞 | 🟢 Low | URL query param `?resume=<session_id>`；Pipeline Builder 看到 resume 就從 Java 載入 paused state |
| Resume 時 Anthropic prompt cache 已過期（5min TTL）→ 第一個 continuation call 變慢 | 🟢 Low | 預期行為；只增加 ~3s latency，不影響功能 |
| 多人同時 continue 同一 session | 🔴 High | session 加 `lock_token`，第二個 continue request 回 409 conflict + 帶 owner user_id |
| 中途 user takeover 但又改主意要 agent 接回 | 🟡 Med | 暫不支援；handoff 是單向。要做就是另一個 SPEC |

---

## 4. Open Questions

1. **continuation_request event 也要在 chat 路徑（V2 orchestrator）emit 嗎？** V2 chat 也有 `MAX_ITERATIONS=10`，但目前一旦 hit 就 force_synthesis（不是 fail）。建議：chat 路徑 **不動**，這個 SPEC 只 cover Glass Box build 路徑。
2. **estimate 範圍要不要 cap？** 如果 LLM 自評說「再 50 步」呢？建議 hard-clamp 到 [5, 20] 區間，避免一次 continuation 又跑爆。
3. **pause/resume 用 Java 還是純 sidecar？** Java 已有 `agent_sessions` table；用既有設施比 sidecar 自己存 in-memory 安全（可跨 sidecar 重啟存活）。
4. **Pipeline Builder 頁面怎麼接收 takeover state？** 目前 `/admin/pipeline-builder` 不知道怎麼從 paused session_id 載入 partial pipeline_json。需要：
   - Pipeline Builder 頁面看到 `?resume=<session_id>` query → 呼 `GET /api/v1/agent/sessions/<id>` 拿 paused state → 把 pipeline_json 餵進 BuilderContext
   - 估 0.5 day extra（不在上面 1.5 day estimate 內）
5. **Continuation 的 token 計費透明度？** 第一次 build 已經花了一筆，user 點「再給 20 步」會再付一筆。要不要在 ContinuationCard 顯示估計 cost（e.g.「約 $0.15」）讓 user 知情？建議 **v2 加，v1 先不做**。

---

## 5. 預期使用者體驗

**Before（現況）：**
```
[plan 6/7]
[40 ops]
✗ EXECUTION FAILED: Reached MAX_TURNS=50 without calling finish()
[partial canvas 顯示，但建構未完成]
```

**After（這 SPEC 上線）：**
```
[plan 6/7]
[40 ops]
[ContinuationCard]
  ⏸ 已跑 50 步、40 個 ops，估計再 5 步可完成。
  ✓ 已完成：建 STEP_001 source / 加 4 個 chart / filter EQP-07
  ○ 還剩：驗證 pipeline / 呼 finish

  [再給 20 步] [我自己接手] [停手用現有結果]
```

User 點「再給 20 步」→ Glass Box 從 turn 51 接續，5 個 turn 內呼 finish → ✅ 成功完成。

---

請 review。確認要做就回「開始開發」；想先補 §4 哪一題（特別是 #4 takeover handoff）也可以說。
