# Spec：Chat/Coordinator 改成對話為主的 MCP-client agent loop

Status: 對齊完成（2026-07-09），待「開始開發」。Builder（Planner & Builder）不動。

---

## 第一層：對齊稿

### 目標
把操作對話（Coordinator/chat 層）從「rigid 分類器 + graph 派工」改成 **cowork /
Claude Code 式的對話 agent**：會自然講話（回答「你能做什麼」、閒聊、解釋），
需要動作時**自己選工具**（建圖 / 改圖 / 跑 skill / 查現況 / 設自動化）。
工具用**標準 MCP**（跟 cowork 同一套）。建置引擎 **Planner & Builder 原封不動**，
被包成一個高階工具 `build_pipeline`。

### Key Features（誰得到什麼 · before → after · 驗收）
| # | Feature | before → after | 驗收 |
|---|---|---|---|
| 1 | 會自然對話 | 「你能做什麼」→ 逼選卡 ／ after：人話列能力 | 問「你可以幫我做什麼」→ 自然能力說明，無逼選卡 |
| 2 | 接得住閒聊/後設 | 「你不能聊天」→ 答非所問 ／ after：自然回應 | 問「你不能聊天嗎」「你是誰」→ 自然回答 |
| 3 | 需要動作才用工具（自選） | 每句先分類再派工 ／ after：判斷要建圖才呼叫建圖工具… | 「畫 xbar」→ 建圖；「拿掉區帶」→ 改圖；「最差機台」→ 跑排名 skill |
| 4 | 建置品質不變 | 一樣 | 建圖結果與現在一致（背後同一個 Planner&Builder） |

### 不做的事
- 不動 Builder：Planner / Builder / 建置 graph / G2 / M2 / build_postmortem 全留。
- 不動 pipeline 執行、skills、自動化後端邏輯。
- 不做跨 session 長期記憶。
- 工具呼叫有上限、可觀測，不放它亂探索。

### 已拍板的裁決
1. 範圍 = **Coordinator/chat 層**（Builder 不動）。
2. 工具機制 = **標準 MCP**；chat agent 當 **aiops MCP server 的 client**（localhost HTTP，可接受一個 hop 換單一來源 + 內外一致）。
3. 唯一新增 = 高階 `build_pipeline` MCP 工具包住不動的 Planner & Builder。
4. 分兩步：Step 1 先做「會對話」；Step 2 再接重工具。
5. 旗標灰度上線、可回退。

---

## 第二層：實作設計

### 架構
```
內部 chat agent（Anthropic tool-use loop，仿現有 agent_builder 的 loop 形狀）
  └─ 當 MCP client 連 aiops MCP server（:8060，cowork 用的同一個）
     → 拿 28 工具 + 每個 how-to docstring + server INSTRUCTIONS（單一來源）
  system prompt = 人設 + 能力清單 + 工作流指引 + gotchas（原則式，不列 case）
  loop: 讀完整對話 → 回話 OR 呼叫 MCP 工具 → 看結果 → 繼續
  （不需要動作時，直接自然回話，不呼叫工具）
```

### 工具（全部走 MCP，單一來源）
| 工具 | 包什麼 | 新增? |
|---|---|---|
| `build_pipeline(instruction)` | **現有 Planner & Builder graph（不改）** | **是（唯一新增）** |
| `modify_current_chart(instruction)` | 現有 run_modify（modify-mode delta） | 既有/接上 |
| `search_skills` / `invoke_skill` | 動態涵蓋所有 published skills | 既有 |
| `call_mcp` / `list_mcps` | 動態涵蓋所有 system MCPs | 既有 |
| `get_current_status` | alarms / 機台現況 snapshot | 既有 |
| `search_knowledge` | RAG | 既有 |
| `setup_automation` | 交接 /skills/[slug]/automate | 既有 |

### 擴充機制（標準 MCP + 已有動態）
1. 加工具：MCP server `@mcp.tool()` + docstring（用法）→ 內外立刻可用。
2. 零加：新 skill / MCP → search_skills / invoke_skill / call_mcp 自動涵蓋。
3. 未來：DB 宣告（比照 V54 mcp_auto），admin 免程式。

### 拿掉什麼（chat 層）
- `intent_classifier`（4-bucket）+ 「不合就丟 clarify 卡」fallback。
- `intent_completeness` 的 design-intent 逼選卡。
- `coordinator_triage` 前置分類（其後端函式 run_modify 保留，改由 `modify_current_chart` 工具呼叫）。

### 可靠性（沒有前置 graph 了，怎麼守）
1. 重工具內部仍是 graph（build_pipeline 裡是原封不動的 Builder，含 G2/M2/postmortem）。
2. 工具參數確定性驗證：錯的回明確錯誤讓模型自我修正。
3. loop 工具呼叫上限（防亂跑燒錢）。
4. 每個工具呼叫記 Agent Activity（EpisodeRecorder）—— 你看得到它選了什麼、為什麼。
5. 旗標 `CHAT_AGENT_LOOP_ENABLED`，一秒回退舊流程。

### 分兩步
- **Step 1（先做，review 對話品質）**：agent loop + 人設 + MCP client 連上 + **唯讀工具**（get_current_status / search_skills / invoke_skill / search_knowledge）。能自然對話、能查、能跑現成 skill。**不接** build_pipeline / modify。
- **Step 2**：MCP server 加 `build_pipeline` 高階工具（包 Builder）+ 接 modify_current_chart + setup_automation。

### 驗收清單總表
| 驗收 | 操作 | 預期 |
|---|---|---|
| F1 | 「你可以幫我做什麼」 | 自然能力說明，無逼選卡 |
| F2 | 「你不能聊天嗎」 | 自然回應 |
| F3 | 「畫 EQP-01 xbar」/「拿掉區帶」/「最差機台」 | 分別呼叫 build_pipeline / modify / 排名 skill，結果與現在一致 |
| F4 | Agent Activity | 看得到每次選了哪個 MCP 工具 |

### 風險
- 模型自由度↑ → 偶爾選錯工具：靠參數驗證 + loop 上限 + 可觀測 + 旗標回退。
- MCP client 連線/認證：sidecar → :8060 需帶內部 token（既有機制）。
- build_pipeline 把 chat instruction 乾淨轉給 Builder：複用現有 chat→build 那條路。
