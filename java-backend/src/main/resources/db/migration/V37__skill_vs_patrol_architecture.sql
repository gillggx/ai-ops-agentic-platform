-- V37 — Skill vs Patrol pipeline architecture clarification.
--
-- Background (2026-05-12):
--   User reported repeated build failures on the instruction
--   「檢查機台最後一次OOC 時，是否有多張SPC 也OOC (>2)，並且顯示該SPC charts」.
--   plan_unfixable across 4 attempts because LLM kept wiring
--   block_step_check → block_alert with a hallucinated `triggered` port.
--   Root cause: LLM conflates two architectures.
--
--   Skill step pipeline: terminates in block_step_check, SkillRunner reads
--     check.pass and fires the alarm itself (no block_alert in pipeline).
--   Auto-Patrol pipeline: terminates in block_alert downstream of a Logic
--     Node (block_threshold / block_consecutive_rule / block_weco_rules /
--     block_any_trigger / ...). No block_step_check.
--
--   block_step_check has output port `check` (dataframe), no `triggered`
--   bool port. LLM was inventing the port.
--
--   Three reinforcements:
--   1. Update block_alert description in pb_blocks (sync with seed.py)
--      to call out "not for skill_step_mode" explicitly.
--   2. Update block_step_check description: TERMINAL block, no downstream.
--   3. New agent_knowledge entry codifies the architectural distinction
--      so plan_node retrieves it as context (no prompt hardcoding).

-- 1) block_alert — append skill_step_mode warning if not already there
UPDATE pb_blocks
SET description = REPLACE(description,
'== When to use ==',
'⚠ **不適用於 skill_step_mode pipelines**（即 Skill 的 step pipeline）：
  - Skill 架構下，pipeline 結尾**只放 `block_step_check`**，由 SkillRunner
    讀取 step_check.check.pass 後決定是否觸發 alarm（這是 SkillRunner 的工作）。
  - 如果 plan 同時包含 block_alert + block_step_check，是錯誤架構。
  - block_step_check 沒有 `triggered` port；不要嘗試把它接到 block_alert。
  - 真正會用 block_alert 的是 auto_patrol pipelines（沒 step_check 結尾）。

== When to use =='),
    updated_at = now()
WHERE name = 'block_alert'
  AND description NOT LIKE '%不適用於 skill_step_mode pipelines%';

-- 2) block_step_check — append terminal-block warning if not already there
UPDATE pb_blocks
SET description = REPLACE(description,
'**Every Skill step''s pipeline MUST end with this block.**',
'**Every Skill step''s pipeline MUST end with this block.**

⚠ **TERMINAL block — 不要接任何下游 block (especially block_alert)**
  - Output port: `check` (dataframe, NOT ''triggered'' / ''result'' / ''pass''). 沒有 bool port。
  - SkillRunner 從 check.pass 讀結果 + 自動發 alarm. **pipeline 不該再加 block_alert**.
  - 想顯示 chart / data_view 當 side branch OK (從上游 fan-out)，但不要接到 step_check 下游.'),
    updated_at = now()
WHERE name = 'block_step_check'
  AND description NOT LIKE '%TERMINAL block — 不要接任何下游 block%';

-- 3) agent_knowledge — Skill vs Patrol architectural rule
INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       'Skill step pipeline vs Auto-Patrol pipeline 架構差異',
       'AIOps 平台有兩種「會發告警的 pipeline」，**結構截然不同**：

(A) Skill step pipeline (skill_step_mode=true)：
  - **必須**終端 `block_step_check`，輸出 port=`check` (dataframe 1 row with pass:bool)
  - **不可以**加 `block_alert` — SkillRunner 讀 step_check.check.pass 後**自動**發 alarm
  - 上游可以有 chart / data_view 當 side branches，但**它們不能接到 step_check 下游**
  - 典型流程：source → filter → aggregate → block_step_check

(B) Auto-Patrol pipeline (kind=auto_patrol, 非 skill)：
  - 終端 `block_alert`，輸入 port=`triggered` (bool) + `evidence` (dataframe)
  - 上游必須是 Logic Node：`block_threshold` / `block_consecutive_rule` / `block_weco_rules` / `block_any_trigger` / `block_cpk` / `block_correlation` / `block_hypothesis_test` / `block_linear_regression`
  - **不可以**有 `block_step_check`
  - 典型流程：source → filter → block_threshold → block_alert

常見錯誤：把兩種架構混在一起（block_step_check + block_alert 並存，或試圖從 step_check 連到 alert）。block_step_check 的 output port 叫 `check` (dataframe)，**不是** `triggered`。

LLM 看到 user 講「觸發 alarm」就反射性加 block_alert — 在 skill_step_mode 下這是錯的，validate_plan 會擋下。',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (
    SELECT 1 FROM agent_knowledge
    WHERE title = 'Skill step pipeline vs Auto-Patrol pipeline 架構差異'
);
