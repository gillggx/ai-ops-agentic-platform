-- V34 — Clarify block_join '_r' suffix rule + spc_long_form pipeline (E)
--       explicit join output schema.
--
-- Background (2026-05-11):
--   Test pipeline 'top-N via join' failed at runtime because LLM read
--   block_join's '右表非 key 同名欄自動加 _r 後綴' as 'all non-key right
--   columns get _r'. Real rule (pandas suffixes=("", "_r")): only
--   collision-resolved columns get _r. The right table's unique columns
--   keep their names. So n7 block_compute(expression={column:
--   'is_ooc_count_r'}) threw 'Column is_ooc_count_r not in input' —
--   the actual column was just 'is_ooc_count'.
--
-- This migration syncs description text into pb_blocks so BlockDocsDrawer
-- + Java catalog readers stay aligned with the sidecar seed.py update.

-- ── block_join: replace ambiguous _r rule with explicit examples ──────
UPDATE pb_blocks
SET description = REPLACE(description,
'== Output ==
port: data (dataframe) — 合併後的 df；右表非 key 同名欄自動加 ''_r'' 後綴

== ⚠ Common mistakes ==
⚠ key 兩邊必須同名；不同名要先 rename
⚠ 多欄 key 用英文逗號分隔（無空白 or 有空白都可），不是 list
⚠ inner join 條件不符會得空 df — 檢查 key 值分佈
⚠ 右表欄位會多出 ''_r'' 後綴；下游要用要注意名稱',
'== Output ==
port: data (dataframe) — left 全部欄位 + right 獨有欄位

== ⚠ 欄位命名規則（最常踩的雷）==
`_r` 後綴**只**加在『左右兩邊都有同名欄位』的衝突情況；右表獨有欄位**保留原名**。
  範例 1：left=[id, name, age], right=[id, score]
         join on id  → output=[id, name, age, score]   （score 沒衝突，無 suffix）
  範例 2：left=[id, name, age], right=[id, name, score]
         join on id  → output=[id, name, age, name_r, score]   （name 衝突，右邊變 name_r）
  範例 3（top-N-via-join 場景）：
         left=[..., chart_name, value, is_ooc],
         right=[chart_name, is_ooc_count]   （right 從 groupby+sort+limit=1 來）
         join on chart_name → output=[..., value, is_ooc, is_ooc_count]
         **是 is_ooc_count，不是 is_ooc_count_r**（沒衝突）

== ⚠ Common mistakes ==
⚠ key 兩邊必須同名；不同名要先 rename
⚠ 多欄 key 用英文逗號分隔（無空白 or 有空白都可），不是 list
⚠ inner join 條件不符會得空 df — 檢查 key 值分佈
⚠ **不要假設右表所有欄位都加 _r**；只有跟左表衝突的才會。下游 block_compute / block_step_check 引用欄位時請對照上面範例。'),
    updated_at = now()
WHERE name = 'block_join'
  AND description LIKE '%右表非 key 同名欄自動加 ''_r'' 後綴%';

-- ── block_spc_long_form: update pipeline (E) to show join output schema ──
UPDATE pb_blocks
SET description = REPLACE(description,
'    Branch B（用 A 過濾原 long-form）：
      block_join(left=n2, right=A, key=''chart_name'', how=''inner'')
         → 只剩最差 chart 的所有 rows
      → line_chart(x=''eventTime'', y=''value'',
                   ucl_column=''ucl'', lcl_column=''lcl'',
                   highlight_column=''is_ooc'')
    ⚠ 不要在 chart 上 facet — 我們已經 join 只剩一張 chart 了。
    ⚠ Branch A 跟 B 都從 **同一個 n2** fan-out，**不要重做 spc_long_form**。',
'    Branch B（用 A 過濾原 long-form）：
      block_join(left=n2, right=A, key=''chart_name'', how=''inner'')
         → output 欄位 = left 全 + 右獨有 = [..., chart_name, value, ucl, lcl, is_ooc, **is_ooc_count**]
         → **不是** is_ooc_count_r — is_ooc_count 只在右表有，無衝突 → 保留原名
      → line_chart(x=''eventTime'', y=''value'',
                   ucl_column=''ucl'', lcl_column=''lcl'',
                   highlight_column=''is_ooc'')
      → step_check(column=''is_ooc_count'', aggregate=''max'', operator=''>'', threshold=0)
    ⚠ 不要在 chart 上 facet — 我們已經 join 只剩一張 chart 了。
    ⚠ Branch A 跟 B 都從 **同一個 n2** fan-out，**不要重做 spc_long_form**。
    ⚠ join 後可以直接 step_check on is_ooc_count，**不需要** block_compute 來 rename。'),
    updated_at = now()
WHERE name = 'block_spc_long_form'
  AND description NOT LIKE '%output 欄位 = left 全 + 右獨有%';
