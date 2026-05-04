-- 2026-05-04: append "Choosing the right column" guidance to blocks whose
-- params reference upstream column names. Prevents Glass Box's recurring
-- failure mode where it picks `'count'` for sort.column on a groupby_agg
-- upstream that actually emits `<agg_column>_<agg_func>` (e.g.
-- `spc_status_count`). Companion to the runtime COLUMN_NOT_IN_UPSTREAM
-- check in tools.py and the Glass Box prompt rule.
--
-- Idempotent: only appends if the marker isn't already present.

UPDATE pb_blocks
SET description = description || E'\n\n== Choosing the right column ==\n'
  || E'⚠ **columns[].column 必須是上游真正輸出的欄位名**。寫錯就 auto-run\n'
  || E'失敗。最常踩的雷：上游是 block_groupby_agg 時。\n'
  || E'  - 上游 groupby_agg(agg_column=''spc_status'', agg_func=''count'')\n'
  || E'    → output column 是 `spc_status_count`（NOT ''count''）\n'
  || E'  - 上游 count_rows → column = ''count''（這個才是 ''count''）\n'
  || E'  - 上游 cpk → ''cpk'' / ''cpu'' / ''cpl'' / ''mean'' / ''std'' / ...\n'
  || E'  - 上游 source / filter / sort（pass-through）→ 用源頭 column\n'
  || E'  - 不確定 → 先 run_preview 上游 node，看 columns 列表\n'
  || E'set_param 會在你寫錯時丟 COLUMN_NOT_IN_UPSTREAM；hint 列出真實 columns。'
WHERE name = 'block_sort'
  AND description NOT LIKE '%Choosing the right column%';

UPDATE pb_blocks
SET description = description || E'\n\n== Choosing the right column ==\n'
  || E'⚠ **column 必須是上游真正輸出的欄位名**。常見雷區：\n'
  || E'  - 上游是 groupby_agg → 用 `<agg_column>_<agg_func>`（e.g. spc_status_count）\n'
  || E'  - 上游是 count_rows → ''count''\n'
  || E'  - 其它（source / pass-through transform）→ 用源頭欄位\n'
  || E'  - 不確定 → 先 run_preview 上游 看 columns。\n'
  || E'set_param 寫錯會丟 COLUMN_NOT_IN_UPSTREAM；hint 會列真實 columns。'
WHERE name = 'block_filter'
  AND description NOT LIKE '%Choosing the right column%';

UPDATE pb_blocks
SET description = description || E'\n\n== Choosing the right column ==\n'
  || E'⚠ **column 必須在上游真正輸出**（同 sort/filter 的雷區）：\n'
  || E'  - 上游 groupby_agg → `<agg_column>_<agg_func>`（**不是** ''count'' / ''mean''）\n'
  || E'  - 上游 count_rows → ''count''\n'
  || E'  - 上游 cpk → ''cpk'' / ''cpu'' / ''cpl'' 等\n'
  || E'  - 不確定 → 先 run_preview 上游。'
WHERE name = 'block_threshold'
  AND description NOT LIKE '%Choosing the right column%';

-- block_groupby_agg: amend its existing "Common mistakes" warning with the
-- downstream-binding hint so the LLM sees the rule from BOTH ends.
UPDATE pb_blocks
SET description = REPLACE(
  description,
  E'⚠ 輸出欄位名是 <agg_column>_<agg_func>（e.g. value_mean），不是 ''agg'' 或 <agg_column>',
  E'⚠ 輸出欄位名是 <agg_column>_<agg_func>（e.g. value_mean），不是 ''agg'' 或 <agg_column>\n'
  || E'  下游 sort/filter/threshold/chart 引用這個欄位時，記得**完整名**：\n'
  || E'  agg_column=''spc_status'' + agg_func=''count'' → 下游 column=''spc_status_count''\n'
  || E'  （**寫 ''count'' 會被 set_param 拒絕**，COLUMN_NOT_IN_UPSTREAM）'
)
WHERE name = 'block_groupby_agg'
  AND description NOT LIKE '%COLUMN_NOT_IN_UPSTREAM%';
