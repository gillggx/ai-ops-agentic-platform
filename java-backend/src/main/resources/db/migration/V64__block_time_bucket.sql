-- V64 — block_time_bucket: truncate a timestamp column into groupable time
-- buckets (15min / 30min / 1h / 4h / 1d). Unblocks "event count by hour" type
-- analyses — process_history.eventTime is a millisecond-unique ISO string, so a
-- raw groupby makes one bucket per row. Backed by TimeBucketBlockExecutor in
-- sidecar pipeline_builder/blocks/time_bucket.py (seed.py + BUILTIN_EXECUTORS +
-- SIDECAR_NATIVE_BLOCKS already updated — this is the catalog row the LLM sees).

DELETE FROM pb_blocks WHERE name = 'block_time_bucket';
INSERT INTO pb_blocks (
  name, category, version, status, description,
  input_schema, output_schema, param_schema,
  implementation, examples, output_columns_hint, is_custom
) VALUES (
  'block_time_bucket',
  'transform',
  '1.0.0',
  'production',
  $$== What ==
把時間欄截斷成等距時間桶（15min/30min/1h/4h/1d），輸出一個可直接 groupby 的桶欄。
解決「eventTime 是毫秒級唯一 ISO 字串、直接 group 會每筆一桶」的問題。

== When to use ==
- ✅ 「過去 N 天 OOC 次數 by hour」→ time_bucket(eventTime,1h) → groupby_agg(group_by=time_bucket, count) → bar_chart
- ✅ 任何「事件 / 良率隨時間」的逐時、逐日趨勢或統計
- ❌ 已是離散分組鍵（tool / step / recipe）→ 直接 groupby，不用本 block
- ❌ 想要連續時間軸補零 → 本 block 不補零（空桶不出現），補零另議

== Params ==
column        (string, required) 時間欄，ISO 字串或 datetime，例 eventTime
interval      (enum 15min|30min|1h|4h|1d, default 1h) 桶粒度
output_column (string, default time_bucket) 輸出欄名
tz            (string, default UTC) 時區，影響小時對齊，例 Asia/Taipei
label         (enum start|center, default start) 桶標籤取桶起點或中心

== Output ==
port: data (dataframe) — 原欄位 + output_column（截斷後時間字串，例 2026-06-26T05:00）。
下游接 block_groupby_agg(group_by=output_column, agg_func='count') → block_bar_chart / block_line_chart。$$,
  $$[{"port": "data", "type": "dataframe", "required": true}]$$,
  $$[{"port": "data", "type": "dataframe"}]$$,
  $${
    "type": "object",
    "required": ["column"],
    "properties": {
      "column":        {"type": "string", "title": "時間欄（ISO 字串或 datetime），例 eventTime"},
      "interval":      {"type": "string", "enum": ["15min", "30min", "1h", "4h", "1d"], "default": "1h", "title": "桶粒度"},
      "output_column": {"type": "string", "default": "time_bucket", "title": "輸出桶欄名"},
      "tz":            {"type": "string", "default": "UTC", "title": "時區，影響小時對齊，例 Asia/Taipei"},
      "label":         {"type": "string", "enum": ["start", "center"], "default": "start", "title": "桶標籤取桶起點或中心"}
    }
  }$$,
  $${"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.time_bucket:TimeBucketBlockExecutor"}$$,
  $$[
    {"label": "OOC 次數 by hour（截到小時桶後 groupby count → bar chart）",
     "params": {"column": "eventTime", "interval": "1h", "tz": "Asia/Taipei"}}
  ]$$,
  '[]',
  false
);
