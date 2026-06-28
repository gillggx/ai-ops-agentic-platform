-- V66 — skills_v2: Skill = 1 pipeline + optional automation wrapper.
--
-- New cleaner model (replacing the multi-step skill_documents shape):
--   - Skill is just: identity + NL prose + 1 pipeline binding + io contracts
--   - Automation is OPTIONAL fields ON THE SAME ROW (trigger / gate / outcome)
--   - role is derived: NULL automation → 'tool'; has_alarm + automation → 'patrol';
--     no has_alarm + automation → 'datacheck'
--
-- One-row-per-skill keeps the API simple — no JOIN to fetch a skill's
-- automation. Migrations to a separate skill_automations table can happen
-- if multi-automation per skill becomes a real need.
--
-- Coexists with the legacy skill_documents table for now (still drives
-- patrol-activity / scheduler in this branch); migration of existing skill
-- data to skills_v2 is deferred (and possibly never — the v2 model isn't
-- back-compat with the multi-step shape anyway).
--
-- Flyway disabled in prod — apply via:
--   psql -h localhost -U aiops aiops_db -f V66__skills_v2.sql

CREATE TABLE IF NOT EXISTS skills_v2 (
  id              BIGSERIAL PRIMARY KEY,
  slug            TEXT UNIQUE NOT NULL,
  name            TEXT NOT NULL,
  sub             TEXT NOT NULL DEFAULT '',                  -- one-line description
  nl              TEXT NOT NULL DEFAULT '',                  -- author's natural language
  pipeline_id     BIGINT REFERENCES pb_pipelines(id) ON DELETE SET NULL,
  pipeline_nodes  TEXT NOT NULL DEFAULT '[]',                -- compiled nodes (JSON of PipelineNode[])
  has_alarm       BOOLEAN NOT NULL DEFAULT FALSE,            -- derived from any node.isVerdict
  in_type         TEXT NOT NULL DEFAULT '',                  -- contract input (e.g. 'Event (OOC)')
  out_type        TEXT NOT NULL DEFAULT '',                  -- contract output

  -- Automation block (NULL when role='tool')
  role                TEXT NOT NULL DEFAULT 'tool'
                       CHECK (role IN ('tool', 'patrol', 'datacheck')),
  trigger_config      TEXT,                                  -- JSON: {kind, schedule?, target?, source?}
  alarm_gate          TEXT,                                  -- patrol only
  outcome             TEXT,                                  -- patrol-only options, datacheck=NULL or 'data only'

  status              TEXT NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'active', 'retired')),
  test_cases          TEXT NOT NULL DEFAULT '[]',
  created_by          BIGINT,
  created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_skills_v2_role         ON skills_v2(role);
CREATE INDEX IF NOT EXISTS ix_skills_v2_pipeline_id  ON skills_v2(pipeline_id);
CREATE INDEX IF NOT EXISTS ix_skills_v2_status_role  ON skills_v2(status, role);

COMMENT ON TABLE  skills_v2 IS
  'Skills v2 — 1 skill = 1 pipeline + optional automation. Replaces skill_documents multi-step model.';
COMMENT ON COLUMN skills_v2.has_alarm IS
  'Derived from pipeline_nodes: TRUE iff any node has isVerdict=true. Stored for fast filter; recalculated on every save.';
COMMENT ON COLUMN skills_v2.role IS
  'Derived view: tool = no automation; patrol = automated + has_alarm; datacheck = automated + !has_alarm.';

-- Seed 6 skills from the design spec §2.3 so the UI has data to click
-- through immediately. Slug used as a deduplication key via ON CONFLICT.

INSERT INTO skills_v2 (slug, name, sub, nl, pipeline_nodes, has_alarm, in_type, out_type,
                       role, trigger_config, alarm_gate, outcome, status) VALUES
('p-ooc52', 'OOC 5取2 全廠巡檢',
 '排程巡所有機台，最近 5 筆 SPC 中 ≥2 筆 OOC 就 emit Event + ALARM。',
 '每小時掃所有機台，看最近 5 筆 SPC 紀錄是否有 2 筆以上 OOC。達標就 emit Event 並 raise alarm。',
 '[{"k":"IN","t":"排程 every 1h · all tools","s":"觸發點"},'
 || '{"k":"S1","t":"take last 5/tool","s":"視窗"},'
 || '{"k":"S2","t":"count(spc_status==OOC)","s":"OOC 次數"},'
 || '{"k":"⚑","t":"count ≥ 2 ⇒ emit Event+ALARM","s":"判斷式 · 5取2 達標","isVerdict":true}]',
 TRUE, 'SPC stream', 'Event + Alarm',
 'patrol',
 '{"kind":"schedule","schedule":"每 1 小時","target":"所有機台"}',
 '5 取 2 達標 → alarm',
 'raise alarm · 可被下游接',
 'active'),

('p-diag', 'OOC 多維診斷',
 '收到 OOC 事件後，從 Tool/Lot/APC/Step 多角度檢查並回傳 Findings。',
 '事件發生時要從 5 個角度檢查（Tool / Lot / APC / Recipe / Step）。任一維度超門檻就 raise alarm。',
 '[{"k":"IN","t":"Event{tool,lot,ts,severity}","s":"事件輸入"},'
 || '{"k":"A1","t":"Tool ≥ 10","s":"機台維度"},'
 || '{"k":"A2","t":"Lot ≥ 2","s":"批次維度"},'
 || '{"k":"A3","t":"APC ≥ 2","s":"APC 維度"},'
 || '{"k":"A5","t":"Step ≥ 2","s":"站點維度"},'
 || '{"k":"⚑","t":"any(findings) ⇒ ALARM","s":"判斷式 · 任一達標","isVerdict":true}]',
 TRUE, 'Event (OOC)', 'Findings + Alarm',
 'patrol',
 '{"kind":"event","source":"p-ooc52"}',
 '任一符合 → alarm',
 'raise alarm · 可被下游接',
 'active'),

('d-rollup', 'OOC 次數彙整看板',
 '每日 08:00 彙整過去 48h OOC 次數依 Tool/Lot/Recipe 排序產 Report。',
 '每天早上 8 點，把過去 48 小時的 OOC 紀錄依 Tool / Lot / Recipe 彙整排序，產出 JSON Report。',
 '[{"k":"IN","t":"window 48h","s":"時間窗"},'
 || '{"k":"S1","t":"fetch OOC records","s":"取資料"},'
 || '{"k":"S2","t":"group by Tool / Lot / Recipe","s":"分組"},'
 || '{"k":"S3","t":"sort desc","s":"降冪"},'
 || '{"k":"S4","t":"format → Report JSON","s":"輸出"}]',
 FALSE, 'window 48h', 'Report (JSON)',
 'datacheck',
 '{"kind":"schedule","schedule":"每日 08:00","target":"所有機台"}',
 NULL,
 'data only',
 'active'),

('t-apc', 'APC 補償飽和檢查',
 '查 APC 參數是否接近飽和；目前只是工具，未綁 trigger。',
 '檢查 APC 補償參數是否接近飽和上限。若是則回傳 Finding 並標記異常。',
 '[{"k":"IN","t":"APC params","s":"參數輸入"},'
 || '{"k":"S1","t":"compare to limits","s":"門檻比較"},'
 || '{"k":"⚑","t":"saturated ⇒ Finding","s":"判斷式 · 含 alarm","isVerdict":true}]',
 TRUE, 'APC params', 'Finding + bool',
 'tool', NULL, NULL, NULL,
 'active'),

('d-recipe', 'Recipe × SPC 相關性熱圖',
 'OOC 事件觸發後計算 Recipe 與 SPC 變化的相關性熱圖。',
 '當 OOC 多維診斷產生 alarm 時，計算 Recipe 與 SPC 各參數的相關性矩陣並產熱圖。',
 '[{"k":"IN","t":"Event from p-diag","s":"事件輸入"},'
 || '{"k":"S1","t":"fetch Recipe × SPC","s":"取兩維資料"},'
 || '{"k":"S2","t":"compute correlation","s":"計算相關性"},'
 || '{"k":"S3","t":"format → Heatmap data","s":"輸出"}]',
 FALSE, 'Event (Findings)', 'Heatmap data',
 'datacheck',
 '{"kind":"event","source":"p-diag"}',
 NULL,
 'data only',
 'active'),

('t-trend', '機台 OOC 趨勢摘要',
 '依 tool_id 給出該機台過去 OOC 趨勢摘要；目前只是工具。',
 '輸入一個 tool_id，回傳該機台最近 7 天的 OOC 趨勢摘要（次數 / 高峰時段 / 主要違反項目）。',
 '[{"k":"IN","t":"tool_id","s":"參數"},'
 || '{"k":"S1","t":"fetch last 7d events","s":"取資料"},'
 || '{"k":"S2","t":"summarize peaks","s":"摘要計算"},'
 || '{"k":"S3","t":"format → text summary","s":"輸出"}]',
 FALSE, 'tool_id', 'summary',
 'tool', NULL, NULL, NULL,
 'active')

ON CONFLICT (slug) DO NOTHING;
