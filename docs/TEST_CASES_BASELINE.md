# Copilot Baseline Test Cases

**Date:** 2026-04-13
**Purpose:** Validate LLM routing + chart rendering behavior after prompt changes.
**How to run:** POST to `/api/v1/agent/chat/stream` with each prompt, check SSE events.

---

## Verification Fields

From SSE events, check:
- `tool_start` → which tool was chosen
- `tool_done.render_card.contract` → YES = Investigate Mode, NO = text only
- `tool_done.render_card.contract.charts` → number of chart DSL produced
- `tool_done.render_card.contract.visualization` → number of viz items
- `synthesis.contract` → final contract delivered to frontend
- `synthesis.text` → LLM text response (no hallucinated "已渲染" when no chart)

---

## Test Cases

### Category A: Should produce chart (Investigate Mode)

| # | Prompt | Expected Tool | Expected Behavior | 2026-04-13 Result |
|---|--------|--------------|-------------------|-------------------|
| A1 | EQP-01 的 APC etch_time_offset 趨勢 | execute_skill(#39) | contract=YES, chart(line) | ✅ skill#39, contract=YES viz=1 |
| A2 | STEP_001 的 xbar_chart trend chart | execute_analysis | contract=YES, chart(spc) | ✅ analysis, contract=YES charts=1 viz=1 |
| A3 | EQP-03 的 DC chamber_pressure 趨勢 | execute_analysis | contract=YES, chart(line) | ✅ analysis, contract=YES charts=1 viz=1 |
| A4 | EQP-05 列出 OOC 站點和 SPC charts | skill or analysis | contract=YES, chart(spc) + text | ✅ mcp+skill(#22), contract=YES viz=5 |
| A5 | 比較 EQP-01 和 EQP-02 的 SPC xbar | execute_analysis | contract=YES, chart(multi_line) | ❌ skill#43 fail → mcp×2 → analysis, charts=0 viz=0 |
| A6 | EQP-04 STEP_002 的 APC 三參數疊加趨勢 | execute_skill(#40) | contract=YES, chart(multi_line) | ✅ skill(#40), contract=YES viz=1 |
| A7 | EQP-06 近 7 天的 SPC 5 chart 全圖 | skill(#22~36) or analysis | contract=YES, 5 spc charts | ❌ mcp → analysis, contract=YES but charts=0 viz=0 |
| A8 | STEP_003 各機台的 OOC 率比較 | execute_analysis | contract=YES, chart(bar) | ⚠️ LLM 反問時間範圍，沒執行 |

### Category B: Should produce text only (no Investigate Mode)

| # | Prompt | Expected Tool | Expected Behavior | 2026-04-13 Result |
|---|--------|--------------|-------------------|-------------------|
| B1 | 我想看 EQP-02 今天的製程資訊 | execute_mcp(get_process_info) | contract=NO, text with OOC stats | ✅ contract=NO, text has OOC breakdown |
| B2 | 目前有哪些機台 | execute_mcp(list_tools) | contract=NO, text list | ✅ contract=NO, lists 10 tools |
| B3 | 全廠 OOC 率是多少 | execute_mcp(get_process_summary) | contract=NO, text with rate | ⚠️ LLM 反問時間範圍，沒直接回答 |
| B4 | EQP-08 的 FDC 狀態 | execute_mcp(get_process_info) | contract=NO, text with classification | ✅ mcp×2, contract=NO, text shows NORMAL + 96% confidence |
| B5 | LOT-0001 經過了哪些機台 | execute_mcp(get_process_info) | contract=NO, text list | ✅ mcp, contract=NO, text lists EQP-01 STEP_004 + 14 events |

### Category C: Should produce judgment/analysis (Investigate Mode)

| # | Prompt | Expected Tool | Expected Behavior | 2026-04-13 Result |
|---|--------|--------------|-------------------|-------------------|
| C1 | EQP-01 最近有沒有 OOC | execute_analysis | contract=YES, condition_met判斷 | ⚠️ LLM 反問時間範圍，沒直接執行 |
| C2 | EQP-07 的 Recipe 參數有沒有變動 | execute_analysis | contract=YES, table or text | ⚠️ mcp+skill(#24), contract=NO — 只列了最新 Recipe 參數，沒比較歷史變動 |

---

## Known Issues (2026-04-13)

### Issue 1: LLM 反問時間範圍 (TC B3, C1)
**Symptom:** 用戶問「全廠 OOC 率」或「最近有沒有 OOC」，LLM 反問時間範圍而不直接回答。
**Root cause:** context_loader 模糊問題規則要求「最近」沒給天數時必須問。但 get_process_summary 預設就是 24h。
**Impact:** 多一輪對話，體驗差。
**Fix:** get_process_summary 沒帶 since 時預設 24h，LLM 不該再問。

### Issue 2: Multi-tool comparison charts=0 (TC A5)
**Symptom:** skill#43 fail → fallback mcp → analysis → contract=YES but charts=0。
**Root cause:** execute_analysis auto mode 生成的 code 可能沒正確宣告 output_schema type。
**Impact:** 用戶看到空的 Investigate Mode。
**Fix:** 需檢查 execute_analysis auto mode 對 multi_line_chart output_schema 的生成品質。

### Issue 3: LLM 幻覺 "圖表已渲染"
**Symptom:** execute_mcp 路徑沒有 chart，但 LLM 在 synthesis 說「圖表已自動渲染」。
**Root cause:** system prompt 歷史殘留 + LLM 慣性。
**Impact:** 用戶困惑。
**Fix:** execute_mcp 不再注入 "CHART RENDERED" notice（已修正），但 system prompt 可能仍有殘留描述。

### Issue 4: execute_analysis auto mode 生成 charts=0 (TC A5, A7)
**Symptom:** execute_analysis 走 auto mode，contract=YES 但 charts=0 viz=0。用戶看到空的 Investigate Mode。
**Root cause:** auto mode 後端 LLM 生成的 code 沒正確宣告 output_schema chart type，或 chart_middleware 無法從產出的 outputs 格式建圖。
**Impact:** 明確要求圖表的 case 沒有圖。
**Fix:** 檢查 diagnostic_rule_service.generate_steps_stream 對 chart type output_schema 的生成品質。可能需要在 auto mode prompt 裡加入 chart_middleware 支援的 type 清單和範例。

### Issue 5: 判斷型問題沒走 execute_analysis (TC C2)
**Symptom:** 「Recipe 參數有沒有變動」→ LLM 只拿最新一筆 Recipe 列表，沒有做歷史比較。
**Root cause:** LLM 選了 execute_mcp + execute_skill(#24 最新 Recipe 列表)，而不是用 execute_analysis 做多筆比對。
**Impact:** 回答不完整 — 列了參數但沒回答「有沒有變動」。
**Fix:** execute_analysis description 已改為 data pipeline 思維，但 LLM 仍偏好用現有 skill。可能需要在 skill#24 description 加註「此 skill 只看最新一筆，不做歷史比較」。

---

## How to Run

```bash
# Single test
curl -sN -X POST "http://localhost:8001/api/v1/agent/chat/stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "YOUR PROMPT", "session_id": "test-xxx"}' | grep "^data:"

# Check key events
... | python3 -c "
import sys, json
for line in sys.stdin:
    if not line.startswith('data: '): continue
    ev = json.loads(line[6:])
    t = ev.get('type','')
    if t == 'tool_start':
        print(f'TOOL: {ev.get(\"tool\")} {json.dumps(ev.get(\"input\",{}))[:100]}')
    elif t == 'tool_done':
        c = ev.get('render_card',{}).get('contract')
        print(f'DONE: contract={bool(c)} charts={len(c.get(\"charts\",[]))} viz={len(c.get(\"visualization\",[]))}' if c else 'DONE: contract=NO')
    elif t == 'synthesis':
        c = ev.get('contract')
        print(f'SYNTH: contract={bool(c)} charts={len(c.get(\"charts\",[]))} viz={len(c.get(\"visualization\",[]))}' if c else 'SYNTH: contract=NO')
"
```

---

*Baseline established 2026-04-13. Update after each prompt/routing change.*
