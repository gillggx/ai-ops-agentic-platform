-- V83 (2026-07-10): 標準 Skill wave 1 — the Coordinator's hardcoded prompt
-- knowledge moved into editable manuals (決策: agent 只看 Skill 目錄做事).
-- NOTE: Flyway is disabled in prod — apply manually via psql.

INSERT INTO agent_skills (name, when_to_use, body, updated_by) VALUES
(
  'process-info-mcp',
  '使用者要查 process 記錄／最後一次 process／單筆製程的 SPC/APC/DC/RECIPE 感測資料時',
  E'# process-info-mcp — 製程資料查詢\n\n'
  || E'## 工具\n'
  || E'- get_process_info：取 process events，每筆含 SPC+APC+DC+RECIPE 完整 nested 資料。參數看工具說明（那是唯一文件）。「EQP-07 最後一次 process」→ 帶 toolID 過濾、取最新一筆。\n'
  || E'- get_process_summary：OOC 統計／機台分佈的聚合視圖（毫秒級），不回 raw data。「OOC 率／哪台有問題／排名」先用這個，不要抓 raw 自己算。\n\n'
  || E'## 注意\n'
  || E'1. 模擬資料可能比較舊：預設時間窗查不到就放寬（例如 7d/30d），不要直接回「沒資料」。\n'
  || E'2. 回覆抓重點欄位（時間／lot／step／spc_status），不要把 nested JSON 原樣倒給使用者；多筆用表格。\n'
  || E'3. 這是「查」。使用者要畫圖分析 → pipeline-authoring；要定期自動查 → automation-setup。',
  'system'
),(
  'pipeline-authoring',
  '使用者要建新圖／分析圖表，或要修改、重新設計畫面上這張圖時',
  E'# pipeline-authoring — 建圖與改圖\n\n'
  || E'## 標準流程（建新圖）\n'
  || E'1. 呼叫 plan_pipeline → 對話裡會出「計畫卡」（P1..PN + 確認/修改/取消）。\n'
  || E'2. 使用者在卡上按確認 → 自動開始建（Live Canvas 逐節點顯示，會花幾十秒，系統會顯示 Planner/Builder/Director 進度）。\n'
  || E'3. 呼叫完只回一句「計畫在上面了，確認後就開始建」，**不要**用文字重列步驟、**不要**再呼叫 build_pipeline。\n'
  || E'4. 只有使用者明講「直接建／不用看計畫」才用 build_pipeline。\n\n'
  || E'## 改圖\n'
  || E'- 微調（拿掉區帶／加 tooltip／換機台／線改虛線）→ modify_current_chart。\n'
  || E'- 結構性重新設計 → 一樣會走計畫卡（以原圖為底），這是系統自動的。\n'
  || E'- 顏色（線色／背景）不是可改參數 → 請使用者用圖右上角的 STYLE 面板。\n\n'
  || E'## 建完之後\n'
  || E'- 圖會自動留在草稿暫存區；使用者要「存成正式 skill／啟用」→ activate_skill（確認卡）；要自動跑 → automation-setup。',
  'system'
),(
  'automation-setup',
  '使用者要把某張圖／某個 Domain Skill 設成自動跑：定時巡檢、事件觸發、定期檢查、告警',
  E'# automation-setup — 自動化設定\n\n'
  || E'## 流程\n'
  || E'1. 先確認對象：畫面上這張圖 → setup_automation（會出卡把它存成 Skill 並帶去設定頁）；既有 Domain Skill → 先 check_skill_ready_for_role 查資格。\n'
  || E'2. 角色規則（code 強制，講清楚不要硬闖）：Auto Patrol 需要 pipeline 含 alarm 判斷式（block_step_check verdict）——沒有會被擋（400）；Auto Check（datacheck）不需要 alarm；tool = 只手動跑。\n'
  || E'3. 想升 patrol 但沒 verdict → 建議使用者重編 pipeline 把結尾換成判斷式（走 pipeline-authoring 流程）。\n'
  || E'4. 排程／觸發條件都在設定頁由使用者填，不要在對話裡代填。',
  'system'
),(
  'knowledge-rules',
  '使用者問「我交代過你什麼」「有哪些 rules／知識」，或想新增、修改教過的規則時',
  E'# knowledge-rules — 使用者交代的規則\n\n'
  || E'## 查\n'
  || E'- list_agent_knowledge：目前生效的 directives（含使用者偏好）。回覆列出重點＋每條的用途，不要倒 raw JSON。\n\n'
  || E'## 增／改\n'
  || E'- 內部沒有直接寫入工具（設計如此：知識變更走人審）。使用者要新增或改 → 教他去 /agent-knowledge 頁自己加，或幫他整理好文字請他貼上。\n'
  || E'- 使用者在對話中說「記住以後都…」→ 覆述你理解的規則，請他到 /agent-knowledge 頁確認新增（給他連結）。',
  'system'
),(
  'supervisor-control',
  '使用者要看 Supervisor 的策展提案、代理健康狀態，或問「有什麼待我審核」時',
  E'# supervisor-control — Supervisor 監督\n\n'
  || E'## 查\n'
  || E'- list_supervisor_proposals：待人審的提案（prune/promote/merge/correct）。摘要每筆：類型、對象、理由。\n'
  || E'- list_agent_activity / get_agent_activity：agent 執行紀錄與成本。\n\n'
  || E'## 界線\n'
  || E'- 核准／駁回**永遠由人**在 /supervisor 頁做——你只能整理與建議，不能代按。使用者要處理 → 給 /supervisor 連結並講清楚建議與理由。',
  'system'
),(
  'domain-skill-management',
  '使用者要查、跑、啟用、停用、刪除或改名 Domain Skill（pipeline 那種）時',
  E'# domain-skill-management — Domain Skill 調配與維護\n\n'
  || E'## 查與跑\n'
  || E'- list_skills_v2 / get_skill_v2：清單與單筆（狀態、角色、自動化）。search_skills：關鍵字找。\n'
  || E'- invoke_skill(slug)：直接執行已啟用的 skill，結果卡進對話。草稿（draft）不能跑。\n\n'
  || E'## 管理（全部確認卡，使用者按了才生效）\n'
  || E'- 啟用：activate_skill（卡上可改名稱／描述）。\n'
  || E'- 停用／刪除／改名：manage_domain_skill(action=deactivate|delete|rename, slug, new_name?, new_description?)。delete 不可逆——先跟使用者確認，並提醒自動化會一併停。\n'
  || E'- 出卡後只回一句「確認卡在上面了」。\n\n'
  || E'## 建新的\n'
  || E'- 走 pipeline-authoring 建圖 → 啟用。不要在這裡手刻 pipeline JSON。',
  'system'
)
ON CONFLICT (name) DO NOTHING;
