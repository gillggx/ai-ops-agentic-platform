"""agents/ — the platform's agent packages (Wave 2, 2026-07-10).

Each subpackage is the ONE public boundary for that agent. Cross-agent code
must import from here, never from the implementation modules directly — the
implementations will migrate physically under these packages over time, and
these facades are what keeps that migration a no-op for callers.

    coordinator  對話代理（chat loop、工具面、確認卡契約）
    planner      規劃（goal_plan、計畫卡、dry-run plan）
    builder      建構（graph build 執行、resume、Live Canvas 事件）
    supervisor   監督（知識/規則策展提案；核准永遠由人）

Boundary rules (enforced by review, described per-package README):
  - Coordinator never gets pipeline-construction primitives (Planner/Builder 職權).
  - All DB writes from any agent go through user-confirmed cards / handoffs.
  - Knowledge of「怎麼做事」lives in 標準 Skills (agent_skills DB), not prompts.
"""
