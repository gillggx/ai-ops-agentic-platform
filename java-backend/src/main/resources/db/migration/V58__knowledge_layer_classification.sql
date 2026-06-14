-- V58: classify agent_knowledge by the agent LAYER that consumes it
-- (planning vs execution) + mark the irreducible "always-on" core.
--
-- Why (spc-ooc, 2026-06-14): id 36 ("全廠聚合 → list_objects + mcp_foreach")
-- is BLOCK-CHOICE knowledge. It was read only by goal_plan (plan layer), but
-- the plan is block-agnostic by design (it emits intent, not blocks), so the
-- advice was flattened away; and phase_loop (the layer that actually PICKS the
-- source block) injected NO knowledge at all. Result: the agent picked
-- block_process_history, hit 3 verifier rejections, and burned ~9 extra rounds
-- rediscovering what id 36 already stated. The knowledge was structurally
-- stranded: read where blocks aren't chosen, absent where they are.
--
-- Fix is delivery, not content: tag each entry with which layer needs it so
-- plan and execute can retrieve different slices, and shrink the always-on
-- full dump (all 19 high bodies into every plan prompt) down to a small core
-- + RAG.
--
--   applies_to : 'plan' | 'execute' | 'both'  — which agent layer consumes it
--   always_on  : true  -> bypass RAG, inject unconditionally (only the few
--                         first-principle rules that MUST land regardless of
--                         multilingual recall). Everything else -> RAG-only.
--
-- Retrieval after this migration (gated by feature flags, default OFF):
--   goal_plan       : always_on(plan|both) + RAG top-k filtered applies_to ∈ {plan, both}
--   phase_loop pick : RAG top-2 filtered applies_to ∈ {execute, both}, query = phase.goal
--                     (no always-on dump at execute — keep the pick prompt lean)
--
-- Flyway is DISABLED in prod — apply this manually with psql on EC2.
-- The id lists below are PROD-CURRENT ids (2026-06-14). On a fresh re-seed the
-- ids may differ; re-derive from titles if so.

ALTER TABLE agent_knowledge
    ADD COLUMN IF NOT EXISTS applies_to varchar(10) NOT NULL DEFAULT 'both';
ALTER TABLE agent_knowledge
    ADD COLUMN IF NOT EXISTS always_on  boolean     NOT NULL DEFAULT false;

-- ── always-on core: irreducible first principles (must always reach planner) ──
-- 25 SPC=station-level · 26 APC=recipe-level · 27 FDC=tool+chamber ·
-- 31 視覺化必含 chart block
UPDATE agent_knowledge SET applies_to='plan', always_on=true
 WHERE id IN (25, 26, 27, 31);

-- ── plan-only: shape intent / phase decomposition / scope gating ──
--  7 FDC 三級 · 9 連續 N 點 OOC 告警 · 28 recipe drift · 29 Skill vs Patrol ·
-- 32 alarm 不在 scope · 33 intent=BUILD · 2 OCAP · 8 chamber aging ·
-- 12 跨 metric 優先序 · 1 PI-run · 11 MTBF/MTTR
UPDATE agent_knowledge SET applies_to='plan', always_on=false
 WHERE id IN (7, 9, 28, 29, 32, 33, 2, 8, 12, 1, 11);

-- ── execute-only: guide block / param choice at commit_pick / construct ──
-- 30 資料是 object(table 是視圖) · 35 看 trend 別砍 history ·
-- 38 參數分佈用 flat-mode 別 unnest · 10 ID 命名格式
UPDATE agent_knowledge SET applies_to='execute', always_on=false
 WHERE id IN (30, 35, 38, 10);

-- ── both: plan-shape AND block-choice facets (e.g. fan-out family) ──
--  3 Cpk 門檻 · 4 WECO 8 rule · 5 spc_status · 36 全廠 list_objects+foreach ·
-- 37 multi-tool named path · 39 多 entity filter('in') · 6 APC run-to-run
UPDATE agent_knowledge SET applies_to='both', always_on=false
 WHERE id IN (3, 4, 5, 36, 37, 39, 6);
