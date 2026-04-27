# SPEC — Context Engineering Phase 2: ReAct Loop Token Diet

**Date:** 2026-04-27
**Status:** Draft — pending approval
**Author:** Gill (Tech Lead) + Claude
**Predecessor:** [SPEC_context_engineering.md](SPEC_context_engineering.md) — Phase 1（dynamic context + intent gate）已部署
**Reviewer note:** Gemini 評過 Phase 1，建議補 §1.D / §1.E 兩招 + 把 tiktoken 收進來

---

## 0. Motivation

Phase 1 成果：「現在最嚴重 alarm」從 162k → 23k tokens（−86%）。但**未解問題**：

- vague → build 仍要 150-240k tokens（Glass Box 內部 25+ 次 LLM call）
- V2 chat 每個 outer iteration 都重付 25k system+tools 整包（**沒用 prompt cache**）
- `TOKEN_THRESHOLD=8000 chars`（≈2k tokens）對 200k window 是 over-compress，反而多燒摘要 LLM call
- 23 個 tools schema 一律全送（5k tokens），即使該意圖只可能用 3 個
- Tool 回傳 raw data 沒 truncation 防護 — 一筆 50k 的 process_history 直接灌回給 LLM 下一輪

**核心結論**：ReAct loop 是 token 放大器，prompt cache + dynamic tool + result truncation 才能根治。Compaction 對單一大 turn 救不了。

---

## 1. Scope（5 items）

### A. Anthropic prompt `cache_control` on V2 chat 路徑（最高優先）

**設計：**
- `agent_helpers_native/llm_client.py` 的 `BaseLLMClient.create()` 介面擴充：`system` 接受 `str` *或* `list[dict]`（Anthropic ContentBlock 格式）
- `AnthropicLLMClient`：偵測 list → 直傳；list 內含 `cache_control: {"type":"ephemeral"}` 自然生效
- `OllamaLLMClient`：list → flatten 成 string，丟掉 `cache_control` field（OpenRouter / Ollama 沒這 feature）
- `tools` 同理 — 最後一個 tool dict 加 `cache_control`，cache 整個 tool list

**呼叫點調整：**
- [llm_call.py:176](python_ai_sidecar/agent_orchestrator_v2/nodes/llm_call.py#L176) 把 `system=system_text`（plain string）改成 cacheable structure
- 切分點：`[{type:text, text:CATALOG, cache_control:ephemeral}, {type:text, text:DYNAMIC_BLOCK}]` — catalog/role 兩段都靜態，cache 命中；dynamic 是 user 訊息 + `<current_state>`，每次不同放後面

**預期效果：**
- 第 1 個 iteration cost 不變（cache miss）
- 後續 6-8 個 iteration 的 25k 靜態前綴變 cache hit → cost × 0.1
- 整體一個 ReAct loop 從 ~175k → ~50k tokens（−70%）

**Anthropic cache 限制：** 最多 4 個 breakpoints / 5min TTL。一輪 chat 跑完前 cache 不會過期。

### B. Pre-flight token budget assembler

**設計：**
- 新 module [`agent_orchestrator_v2/context_assembler.py`](python_ai_sidecar/agent_orchestrator_v2/context_assembler.py)
- 接收 priorities：`{system, tools, history, dynamic_state, user_msg}`
- 套 budget table：
  | 區塊 | Hard cap | Soft target | 超出策略 |
  |---|---|---|---|
  | system + tools | 30k | 25k | 不可動（cache 倚賴穩定）|
  | dynamic_state | 2k | 1k | 截斷 alarms list 到 5 筆 |
  | history | 100k | 50k | 觸發 §C 摘要 |
  | user_msg | 4k | 2k | warn + truncate（罕見）|
  | **total** | **150k** | **120k** | 200k window 留 50k 給 output |
- 在 `load_context_node` return 前呼叫 `assembler.assemble(...)`，回 final messages + system_blocks
- 超 hard cap → emit warning event，仍試圖 send（不要直接 fail）

### C. Token-based threshold + tiktoken / Anthropic counter

**設計：**
- 新 helper [`agent_helpers_native/token_counter.py`](python_ai_sidecar/agent_helpers_native/token_counter.py)
  - 預設用 `tiktoken.get_encoding("cl100k_base")` → 中文 1 token ≈ 1.3 char，誤差 ~5%（夠用）
  - 可選 strict mode：呼 Anthropic `POST /v1/messages/count_tokens`（精準但多一次 API call，cache 結果 5min）
- 改 `orchestrator.py` 三個常數：
  ```python
  RAW_WINDOW = 6           # 不變（保留行數）
  TOKEN_THRESHOLD = 50_000 # 改 token 單位，從 8000 chars 升到 50k tokens
  WINDOW_HARD_LIMIT = 150_000  # 超這個觸發強制摘要不問
  ```
- `_summarize_history` 觸發條件改成 `total_tokens > TOKEN_THRESHOLD` 而非 `total_chars`
- 同時保留 `len(full_history) > RAW_WINDOW` 作為次要觸發（短訊息但很多輪）

### D. Dynamic Tool RAG — intent → tool subset

**設計：**
- 在 [`intent_classifier_node`](python_ai_sidecar/agent_orchestrator_v2/nodes/intent_classifier.py) 額外輸出 `tool_groups: list[str]`：
  ```
  intent=clear_chart   → tool_groups=["chart_build", "search_skill"]
  intent=clear_rca     → tool_groups=["rca_analysis", "search_skill", "execute_skill"]
  intent=clear_status  → tool_groups=["read_only"]   ← 最小 set，5 個 tool
  intent=vague         → 不進 llm_call，N/A
  intent=clarified     → 看 intent_hint 推導
  ```
- 新 metadata：`agent_helpers/tool_dispatcher.py` 每個 tool 加 `groups: tuple[str, ...]`
- `llm_call._visible_tools(roles)` → `_visible_tools(roles, tool_groups)`：先角色過濾、再 group 過濾
- 預期：clear_status 場景 23 → 5 tools，省 ~4k input/iter

**Risk:** classifier 判錯 → 缺工具 → agent 卡住。Mitigation：每組額外帶 `search_published_skills` + `update_plan` + `finish` 當 escape hatch；若 LLM 回 "找不到合適工具" 重 routing 補 group。

### E. Tool result truncation safety net

**設計：**
- 在 [`tool_dispatcher.py`](python_ai_sidecar/agent_helpers/tool_dispatcher.py) `execute()` return 之前統一 wrap：
  ```python
  result_str = json.dumps(result, ensure_ascii=False)
  if token_count(result_str) > TOOL_RESULT_TOKEN_CAP:  # default 4000 tokens
      truncated = _truncate_smart(result, cap)
      return {**truncated, "_truncated": True,
              "_original_size_tokens": token_count(result_str)}
  ```
- `_truncate_smart()` 處理常見格式：
  - `dict` 含 `data: list` → 保留前 N 筆 + `_total_count`
  - `list[dict]` → 同上
  - 純字串 → head/tail 各保留 1500 tokens + `... [truncated K tokens] ...`
- LLM 看到 `_truncated: true` 知道結果不完整，可再呼工具 narrow 條件
- block_chart / block_process_history 等 pipeline-builder block 已有 `limit` param，這層是**最後防線**

### F.（額外）Anthropic 原生 token counter integration

**設計：**
- §C token_counter 加 `count_tokens_native(messages, system, tools)` 走 Anthropic API
- Glass Box orchestrator + V2 chat 在 budget check 時可選用（精準但 +500ms / +small $）
- Default 用 tiktoken，dev 環境可開 `STRICT_TOKEN_COUNTER=1` 對照誤差

---

## 2. Step-by-Step Execution Plan

| Order | Item | Effort | Dep |
|---|---|---|---|
| 1 | (A) prompt cache | 0.5 day | none |
| 2 | (C) token counter helper + threshold update | 0.5 day | none |
| 3 | (E) tool result truncation | 0.5 day | (C) |
| 4 | (B) context assembler | 1 day | (C) |
| 5 | (D) dynamic tool RAG | 1 day | classifier output 已有 intent；只需加 group 對映 |

**Critical path 1.5 day**（A + C + E），剩下 (B)(D) 是 quality-of-life 加分。

---

## 3. Edge Cases & Risks

| Risk | 嚴重 | Mitigation |
|---|---|---|
| (A) cache_control 在非 Anthropic provider 噴錯 | 🔴 | OllamaLLMClient 偵測到 list system → flatten + 丟 cache_control field（已預設）|
| (A) cache breakpoint 放錯位置（dynamic block 在 cache 邊界內）→ cache 永不命中 | 🟡 | 一定要把 dynamic_state + user_msg 放 cache breakpoint **之後** |
| (B) assembler 邏輯複雜化 → debug 難 | 🟡 | budget 決策一律 emit `context_assembly` event 進 SSE log，前端 console 看得到 |
| (C) tiktoken 跟 Anthropic 真實 token 差 5-10% → budget 偶爾估錯 | 🟢 | budget 留 20% buffer 即可；strict mode 給 dev 用 |
| (D) classifier 誤判 → 缺 tool → agent 卡住 | 🟡 | escape hatch 永遠帶 `search_published_skills` + `update_plan` + `finish`；3 turn 內沒進展自動加回所有工具 |
| (E) truncation 砍到 LLM 真的需要的部分 → 答案不完整 | 🟡 | `_truncated: true` flag 顯示 / LLM 可重 query；保守起見 cap 設 4000 不要太緊 |
| (E) truncation logic 對 binary / large blob result 失效 | 🟢 | tool_dispatcher 已有 type narrow，binary 不會走過來 |

---

## 4. 預期 token 用量改善

「STEP_001 最近怎樣？」→ 「趨勢圖表」 case（Phase 1 後 ~191k）：

| Phase | tokens | 主要變化 |
|---|---|---|
| Phase 1（現況） | 191k | snapshot 注入 + intent gate |
| + (A) cache | 80-100k | outer loop iter 7-8 次，第 2 次起 cache 命中 |
| + (D) tool RAG | 70-90k | 5k tools schema 砍掉 4k |
| + (E) tool trunc | 60-80k | process_history 大 result 砍小 |
| + (B)(C) full assembler | 50-70k | history 摘要在合理 threshold 觸發 |

預期最終 **«191k → 60k 左右»** ，−65%（相對 Phase 1）/ **絕對值對比 baseline 162k → 60k = −63%**

---

## 5. Open Questions

1. cache breakpoint 放 2 個（system + tools）還是 3 個（+ static role addendum）？看 Anthropic 帳單實測再調
2. tool_groups 應該在 **每個 tool 裡 declare** 還是 **classifier_node 中央 mapping**？（推 declare in tool — 隨工具增減自然散落）
3. tiktoken 對 Sonnet 4 token 估計 — 中文場景誤差實測需要驗證；大誤差就改用 Anthropic native counter
4. Glass Box agent 要不要也吃 cache？目前已 hardcoded 用 cache_control，refactor 用統一 client 後要一起遷
5. (D) tool RAG 的 escape hatch — agent 三輪都答「沒工具」要怎麼自動 fallback 到全工具？目前想：classifier 在 retry 時不過濾，全送

---

請 review。確認沒問題回「開始開發」，我按 §2 順序動手（建議先做 1.5 day critical path A+C+E，看實測改善再決定 B+D 是否續做）。
