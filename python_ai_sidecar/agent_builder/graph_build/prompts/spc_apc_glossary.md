# SPC / APC Pipeline Domain Knowledge

Verifier 用這份對照「實際資料」vs「user 任務」找 gap。

## block_process_history 的 output 結構

DataFrame，每 row 一筆 process event：

```
eventTime:    ISO timestamp
toolID:       機台 ID (e.g. EQP-01, EQP-02)
lotID:        批號
step:         製程站點 (e.g. STEP_001, STEP_002)
spc_status:   'PASS' | 'OOC'  (整 process 的整體狀態，不是個別 chart 的)
spc_charts:   list[dict] — nested SPC chart 量測，每筆內含 chart_name, value, ucl, lcl, ooc_flag
fdc_classification: (optional) FDC 分類結果
recipe:       (optional) recipe 名稱
apc:          (optional) APC nested dict
```

## spc_charts nested 結構

```
spc_charts = [
  {chart_name: 'xbar_chart', value: 1.23, ucl: 1.5, lcl: 1.0, ooc_flag: False},
  {chart_name: 'r_chart',    value: 0.5,  ucl: 0.8, lcl: 0.2, ooc_flag: False},
  {chart_name: 's_chart',    value: 0.3,  ucl: 0.5, lcl: 0.1, ooc_flag: False},
  ...
]
```

每筆 process event 通常含 12 種 chart 量測。

## 常見 chart_name enum (SPC)

`xbar_chart`, `r_chart`, `s_chart`, `cpk_chart`, `cpu_chart`, `cpl_chart`,
`imr_chart`, `p_chart`, `c_chart`, `np_chart`, `u_chart`, `mr_chart`

## 標準 SPC chart pipeline

```
process_history → unnest(spc_charts) → filter(chart_name='X') → block_xxx_chart
```

四步缺一不可（除非用 composite block_spc_panel = 1-block 內含全部 4 步）。

**unnest 之後若不 filter** → DataFrame 含**所有 chart kind 混在一起** (rows = raw × 12)。
喂下游單一 chart block 會畫出混雜資料，不是 user 要的單一 chart。
**user 點名單一 chart_name → 必須有 filter step**。

## APC 對應結構

`apc` 是 nested dict，key 是 parameter 名稱，value 是該 param 的時序量測。
標準 pipeline: `process_history → unnest(apc) 或 pluck_nested → filter → chart`。

## OOC / OOS / 管制相關名詞

- **OOC** (Out Of Control): 量測值超出管制界線，spc_status='OOC' 或 ooc_flag=True
- **OOS** (Out Of Spec): 量測值超出規格 (USL/LSL)，比 OOC 嚴重
- **UCL/LCL**: Upper/Lower Control Limit (管制上下限)
- **USL/LSL**: Upper/Lower Spec Limit (規格上下限)
- **Cpk/Cp**: 製程能力指標
- **EWMA/CUSUM**: 漂移偵測演算法

## 名稱慣例

- `step`: `STEP_001`, `STEP_002` (大寫 STEP + 底線 + 3 位數字)
- `toolID`: `EQP-XX` (大寫 EQP + 連字號 + 2 位數字)
- `lotID`: 字串格式視場域而定

## Composite block 速查

| Block | Internal coverage | 何時用 |
|---|---|---|
| `block_spc_panel` | raw_data + transform + verdict + chart (SPC) | user 點名單一 SPC chart 趨勢 |
| `block_apc_panel` | raw_data + transform + chart (APC) | user 點名單一 APC param 趨勢 |
| 1-block 走完 raw → chart，不需要 unnest/filter 拼裝 |
