-- V6 — Two purpose-built reshape blocks for SPC / APC patrol pipelines
-- plus a description nudge on block_consecutive_rule pointing the LLM at them.
--
-- Why: process_history returns wide-format rows (`spc_<chart>_<field>` /
-- `apc_<param>`). Asking the agent to compose generic block_unpivot to flip
-- this into long form routinely fails — the LLM picks ad-hoc names like
-- `chart_type` for the variable column, which then breaks downstream
-- group_by. These two blocks bake in the canonical reshape and fix the
-- output column names (`chart_name`, `param_name`).

-- ─── 1. INSERT block_spc_long_form ────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_spc_long_form', '1.0.0', 'transform', 'production',
$desc$== What ==
Process-History wide → SPC long format reshape (purpose-built).

把 process_history 直出的 `spc_<chart>_value` / `_ucl` / `_lcl` / `_is_ooc`
寬欄位攤平成長表，downstream 用 `group_by=chart_name` 一次掃所有 chart。

== When to use ==
- ✅ 「站點所有 SPC charts 任一連 N 次 OOC 就告警」→ 經典組合
- ✅ 「對每張 chart 各跑一次 regression / cpk」→ groupby chart_name
- ✅ 「列出哪些 chart 最近偏離最多」→ groupby chart_name + agg
- ❌ 只處理 1 張特定 chart → 直接 filter 那張的欄位即可，不用 reshape
- ❌ APC 參數 → 用 block_apc_long_form

== Inputs ==
data (dataframe) — 通常來自 block_process_history（不帶 object_name 或
                   object_name='SPC'），需含 spc_<chart>_<field> 欄位。

== Params ==
（無；零參數）

== Output ==
port: data (dataframe, long format)
columns:
  eventTime, toolID, lotID, step, spc_status, fdc_classification  ← passthrough id 欄
  chart_name (string)   ← chart 名稱（X1, X2, R, Xbar, ...）
  value      (number)
  ucl        (number, nullable)
  lcl        (number, nullable)
  is_ooc     (bool)

⚠ 輸出欄位**固定叫 `chart_name`**，**不是** `chart_type` / `chart` / `metric`。
   下游 group_by 請寫 `chart_name`，否則 COLUMN_NOT_FOUND。

== 經典 pipeline ==
process_history(step=$step)
  → spc_long_form
  → consecutive_rule(flag_column=is_ooc, count=2,
                     sort_by=eventTime, group_by=chart_name)
  → alert(severity=HIGH, title="連 2 次 OOC")

== Errors ==
- INVALID_INPUT    : data 不是 DataFrame
- NO_SPC_COLUMNS   : 上游沒 spc_*_<field> 欄位（檢查 process_history params）
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "data", "type": "dataframe"}]',
  '{"type": "object", "properties": {}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.spc_long_form:SpcLongFormBlockExecutor"}',
  '[]',
  '["chart_name", "value", "ucl", "lcl", "is_ooc"]',
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  output_columns_hint = EXCLUDED.output_columns_hint,
  status = EXCLUDED.status,
  category = EXCLUDED.category,
  updated_at = now();

-- ─── 2. INSERT block_apc_long_form ────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_apc_long_form', '1.0.0', 'transform', 'production',
$desc$== What ==
Process-History wide → APC long format reshape (purpose-built).

把 process_history 直出的 `apc_<param>` 寬欄位攤平成長表，downstream
用 `group_by=param_name` 一次處理所有 APC 參數。

== When to use ==
- ✅ 「任一 APC 參數連 N 次超過 X」→ apc_long_form → threshold → consecutive_rule
- ✅ 「對每個 APC 參數做 boxplot / histogram」→ groupby param_name
- ✅ 「找出最常偏離 nominal 的 top-K 參數」→ groupby + count
- ❌ 只看 1 個指定參數 → 直接用該欄位即可
- ❌ SPC chart → 用 block_spc_long_form

== Inputs ==
data (dataframe) — 通常來自 block_process_history（含 apc_<param> 欄位）

== Params ==
（無；零參數）

== Output ==
port: data (dataframe, long format)
columns:
  eventTime, toolID, lotID, step, spc_status, fdc_classification, apc_id  ← id 欄
  param_name (string)   ← 已剝掉 'apc_' 前綴（Pressure / Temperature / Flow ...）
  value      (number)

⚠ 輸出欄位**固定叫 `param_name`**，**不是** `parameter` / `metric` / `apc_param`。
   下游 group_by 請寫 `param_name`，否則 COLUMN_NOT_FOUND。

== 經典 pipeline ==
process_history(step=$step)
  → apc_long_form
  → threshold(value_column=value, op='>', threshold=100)  ← 產生 triggered_row 旗標
  → consecutive_rule(flag_column=triggered_row, count=3,
                     sort_by=eventTime, group_by=param_name)
  → alert(severity=HIGH, title="APC 連 3 次超標")

== Errors ==
- INVALID_INPUT    : data 不是 DataFrame
- NO_APC_COLUMNS   : 上游沒 apc_<param> 欄位
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "data", "type": "dataframe"}]',
  '{"type": "object", "properties": {}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.apc_long_form:ApcLongFormBlockExecutor"}',
  '[]',
  '["param_name", "value"]',
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  output_columns_hint = EXCLUDED.output_columns_hint,
  status = EXCLUDED.status,
  category = EXCLUDED.category,
  updated_at = now();

-- ─── 3. UPDATE block_consecutive_rule.description — point at long-form ──
-- Append a "multi-metric" usage hint so when the LLM sees consecutive_rule
-- it remembers the SPC/APC long-form pattern instead of trying to use
-- raw spc_<chart>_is_ooc directly.
UPDATE pb_blocks
SET description = description || E'\n== Multi-metric pattern (PR-V6) ==\n'
                || E'若要「站點所有 SPC chart 任一連 N 次 OOC」或「任一 APC 參數連 N 次超標」：\n'
                || E'先用 block_spc_long_form / block_apc_long_form 把 wide → long，\n'
                || E'再以 group_by=chart_name 或 group_by=param_name 跑本 block。\n'
                || E'單一 flag_column 一次掃所有 metrics — 不用為每個 chart 拼一次 pipeline。\n',
    updated_at = now()
WHERE name = 'block_consecutive_rule'
  AND description NOT LIKE '%Multi-metric pattern (PR-V6)%';
