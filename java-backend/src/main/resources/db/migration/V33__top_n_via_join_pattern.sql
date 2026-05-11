-- V33 — Sync block description updates for the "filter-to-top-N-group via join" pattern
--
-- Background (2026-05-11):
--   User test prompt: 「檢查機台過去 2 天，表現最差的 SPC chart (ooc 最多的)，
--   並且秀它的 trend chart」 — LLM produced a 9-node pipeline that:
--     1. used time_range=24h instead of 48h (param enum was locked to [1h,24h,7d,30d])
--     2. used deprecated block_chart instead of block_line_chart
--     3. faceted ALL SPC chart trends instead of joining-to-the-worst-one
--
-- Code fixes (sidecar):
--   - plan.py _format_catalog: filters out status=deprecated
--   - seed.py block_process_history.time_range: enum → pattern Nh/Nd
--
-- This SQL migration syncs the description changes into pb_blocks so the
-- BlockDocsDrawer + Java catalog readers stay aligned. (param_schema in
-- pb_blocks doesn't drive sidecar's planner — SeedlessBlockRegistry reads
-- seed.py directly at runtime — so we only sync description text here.)

-- ── block_join: add canonical "filter to top-N group via join" use case ─
UPDATE pb_blocks
SET description = REPLACE(description,
'- ✅ 「Alert records 帶 tool metadata」→ alert df left-join tool df
- ❌ 縱向疊加（rows concat）兩張結構相同的 df → 用 block_union',
'- ✅ 「Alert records 帶 tool metadata」→ alert df left-join tool df
- ✅ **「filter 到 top-N group」** → groupby_agg + sort limit=1 取出 top group 的 key value，
       再 inner-join 回原 df，自動只留該 group 的 rows。
       e.g. 「秀『最差 SPC chart』的 trend」：
         A = spc_long_form → filter is_ooc → groupby chart_name count → sort desc limit=1
         B = spc_long_form (full)
         block_join(left=B, right=A, key=''chart_name'', how=''inner'')
       → 只留最差那張 chart 的 rows，下游 line_chart 即可。
- ❌ 縱向疊加（rows concat）兩張結構相同的 df → 用 block_union'),
    updated_at = now()
WHERE name = 'block_join'
  AND description NOT LIKE '%filter 到 top-N group%';

-- ── block_spc_long_form: add canonical pipeline (E) + fan-out tip ──────
UPDATE pb_blocks
SET description = REPLACE(description,
'    ⚠ 不要用 series_field=''chart_name'' — 那會把 5 張合併成 1 張多色線。

== Errors ==',
'    ⚠ 不要用 series_field=''chart_name'' — 那會把 5 張合併成 1 張多色線。

(E) 找出「**最差**那張 SPC chart」並秀**只那張**的 trend:
    n1 process_history(...) → n2 spc_long_form
    Branch A（找最差 chart_name）：
      n2 → filter(is_ooc=true)
         → groupby_agg(group_by=''chart_name'', agg_column=''is_ooc'', agg_func=''count'')
         → sort(columns=[{column:''is_ooc_count'', order:''desc''}], limit=1)
         → 輸出 1-row {chart_name=''X'', is_ooc_count=Y}
    Branch B（用 A 過濾原 long-form）：
      block_join(left=n2, right=A, key=''chart_name'', how=''inner'')
         → 只剩最差 chart 的所有 rows
      → line_chart(x=''eventTime'', y=''value'',
                   ucl_column=''ucl'', lcl_column=''lcl'',
                   highlight_column=''is_ooc'')
    ⚠ 不要在 chart 上 facet — 我們已經 join 只剩一張 chart 了。
    ⚠ Branch A 跟 B 都從 **同一個 n2** fan-out，**不要重做 spc_long_form**。

== Fan-out 提醒 ==
下游分多 branch 時（A/B/...）都從**同個 spc_long_form node** fan-out edge，
**不要**每個 branch 各做一次 spc_long_form — 多此一舉 + 浪費 CPU。

== Errors =='),
    updated_at = now()
WHERE name = 'block_spc_long_form'
  AND description NOT LIKE '%(E) 找出「**最差**那張 SPC chart」%';

-- ── block_process_history: update time_range param description ─────────
UPDATE pb_blocks
SET description = REPLACE(description,
'time_range  (string, 預設 24h) 1h / 24h / 7d / 30d',
'time_range  (string, 預設 24h) **Nh / Nd 任意組合**，e.g. 1h / 24h / 48h / 72h / 7d / 30d。
              使用者說「過去 N 天」→ time_range=''{N*24}h''（e.g. 2 天 → ''48h''）。'),
    updated_at = now()
WHERE name = 'block_process_history'
  AND description LIKE '%time_range  (string, 預設 24h) 1h / 24h / 7d / 30d%';
