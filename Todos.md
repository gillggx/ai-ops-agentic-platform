# Todos

## Memory v2 Spec — semantic-driven memory management

**Status**: 想法成型，spec 待寫
**Trigger**: 2026-05-21 session — 體認到 prompt 跟 agent flow 的可調空間已耗盡（CLAUDE.md §0「禁止 case-specific prompt rule」+ feedback_flow_in_graph_not_prompt），剩下唯一高槓桿就是 memory 系統升級。
**Why now**: EQP-08 case 顯示 agent 選錯 chart type（bar 而非 line/xbar 畫 SPC value vs limits），原因是缺一條 chart-selection knowledge；廣義來說 builder 蓋 N 次 SPC pipeline 後選 chart 的能力跟第一次完全一樣，因為 builder 端只讀不寫 memory。

### 現況盤點

| Memory 表 | 內容 | 誰讀 | 誰寫 |
|---|---|---|---|
| `agent_knowledge` | 手寫 first-principle（SPC/APC/FDC level、視覺化必須含 chart block） | chat + builder plan_node（priority=high always-on + RAG cosine） | 只能人工 seed（V32/V36/V44 Flyway migrations） |
| `agent_experience_memories` | LLM 自動抽出 (intent → action) pair + confidence/use/success/fail counters | chat `load_context`（RAG by query） | chat `memory_lifecycle_node` 每次成功對話後自動寫 |
| `agent_memories` | legacy keyword-based | chat fallback | 廢棄 |

**Gap**：builder 側完全沒有「自動寫」的路徑 — `plan_node` 只讀 `agent_knowledge`，build success 後不抽 lesson 寫回。

### 4 個必須先答的設計問題

1. **抽取觸發點**：(a) build success / judge accept 後 / (b) user 在 trace UI 主動標好壞 / (c) Skill 綁定 N 次無 error 後升級 confidence / (d) 三者組合分 tier？
2. **語意 unit schema**：raw plan JSON 會 over-fit instruction wording；free text 會跟 prompt 一樣失控。傾向結構化 triple `(intent_signature, block_chain_pattern, why)`，e.g. `(intent="SPC value vs limits trend", pattern="long_form → line_chart{y=[value,ucl,lcl]}", why="value 跟 limits 同單位連續量")`。schema 設計就是整個系統天花板。
3. **Retrieval 適用判斷**：純 cosine 太脆（中/英/同義詞 miss）；建議 hybrid: cosine 第一關 → metadata gate（intent_type, data_subject, output_kind）第二關。需要先有 intent classifier 把 instruction 拆 facet。
4. **Conflict / staleness**：Memory A 說「用 line_chart」、Memory B 說「用 xbar_r」誰贏？block schema 改了 → 舊 memory stale 怎麼自動偵測？chat 側已有 confidence_score + use_count + fail_count，builder 要不要照搬？

### Next step

寫單頁 Spec（30-60 分鐘），對 4 個問題各給明確答案 + schema 草案 + 「EQP-08 走過去會怎樣」worked example。Spec 確定後再分 phase 實作。

**Do NOT**: 一邊寫 V45 chart-selection knowledge 一邊做 builder reflection node — 那會做出「能跑但語意還是平的」memory。Spec 先。
