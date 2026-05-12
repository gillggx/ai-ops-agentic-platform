-- V35 — block_groupby_agg: forbid comma-string for multi-column group_by;
--       require list of strings instead.
--
-- Background (2026-05-12):
--   Skill 48 builder run produced plan with `group_by: "lotID,step,chart_name"`
--   (single comma-separated string). Validator rejected it as a single
--   non-existent column name. LLM repair_plan loop hit MAX_PLAN_REPAIR=3
--   without ever switching to list form, because the description literally
--   said "用逗號分隔 string，不是 list" — wrong instruction, since the
--   executor `groupby_agg.py` does:
--     group_cols = group_by if isinstance(group_by, list) else [group_by]
--   So a comma-string becomes [\"a,b,c\"] (single-element list) → no match.
--
--   This migration syncs the corrected description into pb_blocks so
--   BlockDocsDrawer + Java catalog readers stay aligned with seed.py.
--   Sidecar executor patched in same commit to also accept comma-strings
--   (split on `,`) as a backward-compat safety net for old pipelines.

UPDATE pb_blocks
SET description = REPLACE(description,
'- ✅ 多維度：group_by=''toolID,step'' 逗號分隔',
'- ✅ 多維度：group_by=[''toolID'',''step''] (list) 或 group_by=''toolID'' (single col)'),
    updated_at = now()
WHERE name = 'block_groupby_agg'
  AND description LIKE '%group_by=''toolID,step'' 逗號分隔%';

UPDATE pb_blocks
SET description = REPLACE(description,
'group_by   (string, required) 分組欄位；逗號分隔多欄 (e.g. ''toolID,step'')',
'group_by   (string | list[string], required) 分組欄位
           ✅ 單欄 string:  ''toolID''
           ✅ 多欄 list:    [''toolID'',''step'',''chart_name'']  ← 推薦
           ⚠ 不要用逗號分隔字串 ''toolID,step''（會被當成單一欄名 ''toolID,step'' 找不到）'),
    updated_at = now()
WHERE name = 'block_groupby_agg'
  AND description LIKE '%group_by   (string, required) 分組欄位；逗號分隔多欄%';

UPDATE pb_blocks
SET description = REPLACE(description,
'⚠ 多 group_by 要用逗號分隔 string，不是 list',
'⚠ 多 group_by 要用 list of strings (e.g. [''toolID'',''step''])；逗號分隔 string 會被 reject'),
    updated_at = now()
WHERE name = 'block_groupby_agg'
  AND description LIKE '%多 group_by 要用逗號分隔 string，不是 list%';
