---
name: block_step_check
description: Aggregate (count/sum/mean/max/min/last/exists) upstream DataFrame to a scalar and compare with threshold/baseline. Skill terminal block. 不 filter, 不 group — upstream 必須已 filter 到目標 row set, 此 block 對整個 DataFrame 套 aggregate.
---

# block_step_check

Phase 11 Skill terminal block. 把 upstream rows aggregate 成一個 scalar
值, 跟 threshold (或 baseline drift) 比較, 輸出 `{pass, value, threshold,
note, evidence_rows}` 給 SkillRunner 或下游 block_alert 讀。

## When to invoke

- Skill step 結尾的 pass/fail check (Skill mode 強制 pipeline 以這個 block 收尾)
- Diagnostic Rule 中需要「對 row set 算個數值 + 判 threshold + 觸發告警」
- 量化比較類意圖 — count / sum / mean / max / min / last / exists

不適用情境:
- 想 filter row 子集 → 改用 `block_filter` (本 block 不 filter)
- 想 group by 後對每組 aggregate → 改用 `block_groupby_agg`
- 想 triggered (bool) + evidence (table) 雙 port → 改用 `block_threshold`
- 想出 chart → 改用 chart 系列 block

## Inputs

### port: `data`
- type: dataframe
- required: yes
- 期望狀態: 已 filter 到目標 row set 的長表。本 block 對整個 DataFrame
  套 aggregate, 不做 row 篩選。
- 必要欄位: `aggregate ∈ {sum, mean, max, min, last}` 時, `column` param
  指定的欄位必須存在於上游 dataframe。`count / exists` 不依賴特定欄位。
- 不接受: 空 dataframe (0 row, 由上游保證), nested list/dict column。

upstream sample:
```json
[
  {"eventTime": "2026-05-19T10:00", "toolID": "EQP-01", "spc_status": "OOC"},
  {"eventTime": "2026-05-19T10:05", "toolID": "EQP-01", "spc_status": "OOC"},
  {"eventTime": "2026-05-19T10:10", "toolID": "EQP-01", "spc_status": "OOC"}
]
```

## Outputs

### port: `check`
- type: dataframe (1 row)
- columns: `pass` (bool), `value` (any), `threshold` (any), `operator`
  (string), `aggregate` (string), `column` (string|null), `note` (string),
  `evidence_rows` (int)
- 下游 hint:
  - `block_alert`: 讀 `pass` 觸發告警
  - `block_data_view`: 顯示整 row 給人看
  - 不接 chart blocks (此 block 是 verdict 非 trend)

output sample:
```json
{"pass": true, "value": 3, "threshold": 3, "operator": ">=",
 "aggregate": "count", "column": "spc_status",
 "note": "count(spc_status)=3 >= 3", "evidence_rows": 3}
```

## Parameters

| name | type | required | default | enum | 用途 |
|---|---|---|---|---|---|
| `aggregate` | string | no | `count` | count/sum/mean/max/min/last/exists | 對 row set 做哪種 aggregate |
| `column` | string | 非 count/exists 時必填 | - | - | 被 aggregate 的欄位 |
| `operator` | string | no | `>=` | `>=`/`>`/`=`/`==`/`<`/`<=`/`changed`/`drift` | 比較運算子 (`==` 是 `=` 的 alias) |
| `threshold` | number | 數值比較必填 | - | - | 比較目標值 |
| `baseline` | any | `operator=changed/drift` 時必填 | - | - | 變動偵測基準 |

常見錯誤:
- `op` 而非 `operator` → validation_error
- `agg_func` 而非 `aggregate` → validation_error
- `column` 拼錯 → COLUMN_NOT_FOUND
- `sum` 沒給 `column` → validation_error
- `operator='drift'` 沒給 `baseline` → validation_error

## Examples

### Standard OOC threshold pattern (Diagnostic Rule mode)
```
block_process_history(tool_id='EQP-01', limit=5)
  → block_filter(column='spc_status', operator='==', value='OOC')
  → block_step_check(aggregate='count', operator='>=', threshold=3)
  → block_alert(severity='HIGH', title='OOC threshold breach')
```
意圖: 撈 5 筆 EQP-01 process → 篩 OOC → 算數量 → 若 ≥3 觸發告警。
注意: `block_filter` 是必要前置, 此 block 不會自己過濾。

### Drift detection on APC parameter (Skill mode terminal)
```
block_process_history(tool_id='EQP-08', step='STEP_001', time_range='7d')
  → block_apc_long_form(param='etch_time_offset')
  → block_step_check(aggregate='mean', column='value',
                     operator='drift', baseline=0, threshold=1.0)
```
意圖: 過去 7 天 etch_time_offset 平均, 若偏離 baseline 0 > 1σ 則 fail。
注意: Skill mode 此 block 為 pipeline terminal, 不接 block_alert
(SkillRunner 自動處理告警)。
