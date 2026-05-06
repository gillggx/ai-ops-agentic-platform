-- 2026-05-06: publish 5 list-type Skills so chat agent can answer simple
-- "目前有哪些 X" questions in one shot. Each skill wraps a single MCP via
-- a 2-node pipeline (block_mcp_call → block_data_view). search_published_skills
-- is the chat LLM's only direct call surface; without these, list-type
-- queries fall through to build_pipeline_live and burn 40+ Glass Box turns.
--
-- Idempotent guard: each skill block is wrapped in DO IF NOT EXISTS keyed
-- on slug. Re-running on a DB that already has the rows is a no-op.

-- ── Skill 1: list-apcs ────────────────────────────────────────────────
DO $skill$
DECLARE pipe_id INTEGER;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pb_published_skills WHERE slug = 'list-apcs') THEN
    INSERT INTO pb_pipelines (name, description, status, pipeline_kind, version, pipeline_json, usage_stats)
    VALUES (
      'List APCs', '列出系統所有 APC config object', 'active', 'auto_check', '1.0.0',
      $json$ {"name":"List APCs","version":"1.0","nodes":[{"id":"n1","block_id":"block_mcp_call","block_version":"1.0.0","params":{"mcp_name":"list_apcs"},"position":{"x":100,"y":200},"display_label":"呼叫 list_apcs MCP"},{"id":"n2","block_id":"block_data_view","block_version":"1.0.0","params":{"title":"APC 清單","max_rows":50},"position":{"x":380,"y":200},"display_label":"顯示 APC 清單"}],"edges":[{"id":"e1","from":{"node":"n1","port":"data"},"to":{"node":"n2","port":"data"}}],"inputs":[],"metadata":{}} $json$,
      '{"invoke_count":0,"last_invoked_at":null,"last_triggered_at":null}'
    ) RETURNING id INTO pipe_id;

    INSERT INTO pb_published_skills (pipeline_id, pipeline_version, slug, name, use_case, when_to_use, inputs_schema, outputs_schema, tags, status)
    VALUES (
      pipe_id, '1.0.0', 'list-apcs', '列出系統所有 APC',
      '回答「系統有哪些 APC」「APC 名單」這類 directory 查詢。從 object_snapshots 拉 distinct apcID 並回傳。',
      '當使用者問「目前有哪些 APC」「列出 APCs」「APC 清單」「系統有幾個 APC」時用本 skill。input 為空 — 不需要任何參數。',
      '[]',
      '[{"port":"data_view","type":"table","description":"APC 清單表格，欄位 apcID"}]',
      'list,inventory,apc,directory', 'active'
    );
  END IF;
END $skill$;

-- ── Skill 2: list-tools ───────────────────────────────────────────────
DO $skill$
DECLARE pipe_id INTEGER;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pb_published_skills WHERE slug = 'list-tools') THEN
    INSERT INTO pb_pipelines (name, description, status, pipeline_kind, version, pipeline_json, usage_stats)
    VALUES (
      'List Tools', '列出全廠機台與目前狀態', 'active', 'auto_check', '1.0.0',
      $json$ {"name":"List Tools","version":"1.0","nodes":[{"id":"n1","block_id":"block_mcp_call","block_version":"1.0.0","params":{"mcp_name":"list_tools"},"position":{"x":100,"y":200},"display_label":"呼叫 list_tools MCP"},{"id":"n2","block_id":"block_data_view","block_version":"1.0.0","params":{"title":"機台清單","max_rows":50},"position":{"x":380,"y":200},"display_label":"顯示機台清單"}],"edges":[{"id":"e1","from":{"node":"n1","port":"data"},"to":{"node":"n2","port":"data"}}],"inputs":[],"metadata":{}} $json$,
      '{"invoke_count":0,"last_invoked_at":null,"last_triggered_at":null}'
    ) RETURNING id INTO pipe_id;

    INSERT INTO pb_published_skills (pipeline_id, pipeline_version, slug, name, use_case, when_to_use, inputs_schema, outputs_schema, tags, status)
    VALUES (
      pipe_id, '1.0.0', 'list-tools', '列出所有機台與狀態',
      '回答「有哪些機台」「機台狀態」這類 directory 查詢。回傳每台機台的 tool_id + 目前 status (Idle / Busy / Maintenance)。',
      '當使用者問「有哪些機台」「機台清單」「目前所有 EQP」「哪台在跑」時用本 skill。input 為空 — 不需要任何參數。',
      '[]',
      '[{"port":"data_view","type":"table","description":"機台表格，欄位 tool_id / status"}]',
      'list,inventory,tool,equipment,directory', 'active'
    );
  END IF;
END $skill$;

-- ── Skill 3: list-active-lots ─────────────────────────────────────────
DO $skill$
DECLARE pipe_id INTEGER;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pb_published_skills WHERE slug = 'list-active-lots') THEN
    INSERT INTO pb_pipelines (name, description, status, pipeline_kind, version, pipeline_json, usage_stats)
    VALUES (
      'List Active Lots', '列出目前 in-flight 的 lot（Waiting + Processing）', 'active', 'auto_check', '1.0.0',
      $json$ {"name":"List Active Lots","version":"1.0","nodes":[{"id":"n1","block_id":"block_mcp_call","block_version":"1.0.0","params":{"mcp_name":"list_active_lots"},"position":{"x":100,"y":200},"display_label":"呼叫 list_active_lots MCP"},{"id":"n2","block_id":"block_data_view","block_version":"1.0.0","params":{"title":"在跑的 Lot","max_rows":50},"position":{"x":380,"y":200},"display_label":"顯示 active lot 清單"}],"edges":[{"id":"e1","from":{"node":"n1","port":"data"},"to":{"node":"n2","port":"data"}}],"inputs":[],"metadata":{}} $json$,
      '{"invoke_count":0,"last_invoked_at":null,"last_triggered_at":null}'
    ) RETURNING id INTO pipe_id;

    INSERT INTO pb_published_skills (pipeline_id, pipeline_version, slug, name, use_case, when_to_use, inputs_schema, outputs_schema, tags, status)
    VALUES (
      pipe_id, '1.0.0', 'list-active-lots', '列出目前還在跑的 Lot',
      '回答「現在有哪些 lot」「卡在哪一站」這類即時 inventory 查詢。Waiting + Processing 狀態都列入；Finished 不會出現。',
      '當使用者問「現在有哪些 lot」「在跑的 lot」「lot 走到哪了」「active lot」時用本 skill。input 為空 — 不需要任何參數。',
      '[]',
      '[{"port":"data_view","type":"table","description":"Lot 表格，欄位 lot_id / current_step / status / cycle"}]',
      'list,inventory,lot,active,in-flight,directory', 'active'
    );
  END IF;
END $skill$;

-- ── Skill 4: list-steps ───────────────────────────────────────────────
DO $skill$
DECLARE pipe_id INTEGER;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pb_published_skills WHERE slug = 'list-steps') THEN
    INSERT INTO pb_pipelines (name, description, status, pipeline_kind, version, pipeline_json, usage_stats)
    VALUES (
      'List Steps', '列出系統定義的所有 process step', 'active', 'auto_check', '1.0.0',
      $json$ {"name":"List Steps","version":"1.0","nodes":[{"id":"n1","block_id":"block_mcp_call","block_version":"1.0.0","params":{"mcp_name":"list_steps"},"position":{"x":100,"y":200},"display_label":"呼叫 list_steps MCP"},{"id":"n2","block_id":"block_data_view","block_version":"1.0.0","params":{"title":"Step 清單","max_rows":50},"position":{"x":380,"y":200},"display_label":"顯示 step 清單"}],"edges":[{"id":"e1","from":{"node":"n1","port":"data"},"to":{"node":"n2","port":"data"}}],"inputs":[],"metadata":{}} $json$,
      '{"invoke_count":0,"last_invoked_at":null,"last_triggered_at":null}'
    ) RETURNING id INTO pipe_id;

    INSERT INTO pb_published_skills (pipeline_id, pipeline_version, slug, name, use_case, when_to_use, inputs_schema, outputs_schema, tags, status)
    VALUES (
      pipe_id, '1.0.0', 'list-steps', '列出所有 process step',
      '回答「系統有哪些 step」「總共幾站」這類 directory 查詢。回傳 STEP_001 ~ STEP_NNN 完整清單。',
      '當使用者問「有哪些 step」「總共幾站」「站點清單」「process steps」時用本 skill。input 為空 — 不需要任何參數。',
      '[]',
      '[{"port":"data_view","type":"table","description":"Step 表格，欄位 name / description"}]',
      'list,inventory,step,process,directory', 'active'
    );
  END IF;
END $skill$;

-- ── Skill 5: list-spcs ────────────────────────────────────────────────
DO $skill$
DECLARE pipe_id INTEGER;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pb_published_skills WHERE slug = 'list-spcs') THEN
    INSERT INTO pb_pipelines (name, description, status, pipeline_kind, version, pipeline_json, usage_stats)
    VALUES (
      'List SPC Charts', '列出系統支援的 SPC chart 種類', 'active', 'auto_check', '1.0.0',
      $json$ {"name":"List SPC Charts","version":"1.0","nodes":[{"id":"n1","block_id":"block_mcp_call","block_version":"1.0.0","params":{"mcp_name":"list_spcs"},"position":{"x":100,"y":200},"display_label":"呼叫 list_spcs MCP"},{"id":"n2","block_id":"block_data_view","block_version":"1.0.0","params":{"title":"SPC Chart 種類","max_rows":50},"position":{"x":380,"y":200},"display_label":"顯示 SPC chart 種類"}],"edges":[{"id":"e1","from":{"node":"n1","port":"data"},"to":{"node":"n2","port":"data"}}],"inputs":[],"metadata":{}} $json$,
      '{"invoke_count":0,"last_invoked_at":null,"last_triggered_at":null}'
    ) RETURNING id INTO pipe_id;

    INSERT INTO pb_published_skills (pipeline_id, pipeline_version, slug, name, use_case, when_to_use, inputs_schema, outputs_schema, tags, status)
    VALUES (
      pipe_id, '1.0.0', 'list-spcs', '列出 SPC chart 種類',
      '回答「SPC 有哪些 chart」這類 directory 查詢。回傳系統支援的 5 種 chart：xbar / r / s / p / c。',
      '當使用者問「SPC 有哪些 chart」「除了 xbar 還有什麼可看」「SPC chart 種類」時用本 skill。input 為空 — 不需要任何參數。',
      '[]',
      '[{"port":"data_view","type":"table","description":"SPC chart 表格，欄位 chart / description"}]',
      'list,inventory,spc,chart,directory', 'active'
    );
  END IF;
END $skill$;
