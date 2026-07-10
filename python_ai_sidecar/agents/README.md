# agents/ — 平台 Agent 套件邊界（Wave 2, 2026-07-10）

一個子套件 = 一個 agent 的**唯一公開介面**。跨 agent 的程式只准 import 這裡，
不准直接 import 實作模組 —— 實作檔案會逐步物理搬進來，facade 保證搬移對呼叫端零影響。

| 套件 | 職責 | 實作位置（暫） | 公開介面 |
|---|---|---|---|
| `coordinator` | 對話代理：chat tool-use loop、能力面（granted 工具 + 標準 Skill 目錄）、確認卡契約 | `agent_orchestrator_v2/chat_agent_loop.py` | `run_chat_agent`, `is_chat_agent_loop_enabled` |
| `planner` | 規劃：goal_plan、計畫卡（goal_plan_confirm_gate 暫停） | `agent_builder/graph_build/nodes/goal_plan.py` | `stream_graph_build`（到 confirm gate） |
| `builder` | 建構：v30 ReAct loop、finalize（含自動命名）、pb_glass_* 事件 | `agent_builder/graph_build/` | `stream_graph_build`, `resume_graph_v30`, `wrap_build_event_for_chat` |
| `supervisor` | 策展提案（prune/promote/merge/correct）；核准永遠由人 | `supervisor_curation/` | `proposer` |

## 邊界鐵律
1. Coordinator 永遠拿不到 pipeline 建構原語（add_node/validate/save…）—— 那是 Planner & Builder 的職權。
2. 任何 agent 的 DB 寫入都走「使用者確認卡 / handoff」，瀏覽器以使用者 JWT 執行；角色閘門（patrol verdict、resolve=ADMIN/PE）在 code 強制。
3. 「怎麼做事」的知識放標準 Skill（`agent_skills` 表，/admin/agent-skills 可編），不放 prompt；prompt 只留人設 + 少數硬規則（核心路由）。
4. 工具的參數/回傳文件 = 工具 description（DB / dispatch 表），單一來源。
