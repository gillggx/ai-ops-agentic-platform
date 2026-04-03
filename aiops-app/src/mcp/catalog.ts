/**
 * AIOps MCP Catalog
 *
 * 定義 AIOps 暴露給 Agent 的所有 MCP。
 * - Data MCP: Agent 呼叫後拿到資料繼續推理
 * - Handoff MCP: Agent 呼叫後 AIOps 接管 UI 互動
 */

export interface MCPDefinition {
  name: string;
  description: string;
  is_handoff: boolean;
  parameters: Record<string, ParameterSchema>;
  /** 一到兩句話說明「何時」、「如何」呼叫此 MCP 的具體範例 */
  usage_example: string;
  /** 描述回傳資料的結構，讓 Agent 知道拿到什麼後可以做什麼 */
  output_description: string;
}

export interface ParameterSchema {
  type: string;
  description: string;
  required: boolean;
  enum?: string[];
}

// ---------------------------------------------------------------------------
// Data MCPs
// ---------------------------------------------------------------------------

export const DATA_MCPS: MCPDefinition[] = [
  {
    name: "get_dc_timeseries",
    description: `【DC 製程參數時間序列】取得特定機台 × 站點的 Data Collection 量測值時間序列，專為 SPC 趨勢分析設計。

每個資料點 = 一次 ProcessEnd（一批貨跑完這個站），時間由舊到新排序。

回傳欄位說明：
- equipment_id: 機台代碼（EQP-01 ~ EQP-10）
- parameter: 量測參數名稱（如 Temperature、Pressure、RF Power）
- data: [{timestamp, value, lot_id, is_ooc}] — 時間序列資料點，is_ooc 標記是否超出管制限
- ucl / lcl / mean: 基於同窗口計算的 3-sigma 管制界限與均值

典型使用情境：
① 畫 SPC 趨勢圖：用 data[].value + ucl/lcl 畫折線圖，is_ooc=true 的點標紅
② 偵測連續 OOC：掃描 is_ooc=true 的連續序列，>= 3 點連續 OOC 即警示
③ 參數偏移診斷：比較最近幾點 value 是否持續朝 UCL 或 LCL 偏移（趨勢 Run）
④ 多參數根因對比：同時比較 Temperature、Pressure、RF Power 走勢，找出最先異常的參數

⚠️ 必填：equipment_id（機台）、parameter（參數名稱）、start / end（時間窗口）
⚠️ 時間格式為 ISO 8601，例如 "2025-01-15T08:00:00Z"
⚠️ 與 get_spc_data 的差別：此工具只回傳單一參數的原始時序值；get_spc_data 回傳完整 SPC 報告（含多圖分析和 OOC 摘要）`,
    is_handoff: false,
    parameters: {
      equipment_id: { type: "string", description: "機台 ID，例如 EQP-01、EQP-05", required: true },
      parameter:    { type: "string", description: "量測參數名稱，例如 Temperature（溫度）、Pressure（壓力）、RF Power（射頻功率）、Bias Voltage", required: true },
      start:        { type: "string", description: "查詢時間窗口起始（ISO 8601），例如 2025-01-15T00:00:00Z", required: true },
      end:          { type: "string", description: "查詢時間窗口結束（ISO 8601），例如 2025-01-15T23:59:59Z", required: true },
    },
    usage_example: "SPC OOC 後診斷根因：呼叫 get_dc_timeseries(equipment_id='EQP-03', parameter='Temperature', start='...', end='...') 取得溫度時序，掃描 is_ooc=true 的資料點，判斷是單點突波還是持續漂移。",
    output_description: "回傳 { equipment_id, parameter, data: [{timestamp, value, lot_id, is_ooc}], ucl, lcl, mean }。data 陣列按時間升序排列，每點對應一批貨的量測值。",
  },
  {
    name: "get_event_log",
    description: `【設備事件記錄】取得指定機台在時間窗口內的所有設備事件，包含 PM、Alarm、Downtime、Hold、Recipe 變更等。

回傳欄位說明：
- event_id: 事件唯一識別碼
- equipment_id: 機台代碼
- event_type: 事件類型 — "PM"（預防保養）、"ALARM"（警報）、"DOWN"（停機）、"HOLD"（批次保留）、"RESUME"（恢復）
- severity: 嚴重程度 — "critical"（緊急停機）、"warning"（警告）、"info"（一般紀錄）
- description: 事件描述文字，包含故障代碼或操作說明
- timestamp: 事件發生時間（ISO 8601）
- resolved_at: 問題解決時間；null 表示尚未解決（機台仍在 Hold 或 Down 狀態）

典型使用情境：
① 「機台最近停機幾次？」→ 過濾 event_type='DOWN'，統計 count 與 resolved_at 差值計算停機時長
② 「OOC 前機台有沒有做過 PM？」→ 查詢 OOC 時間附近的 PM 事件，判斷是否為 PM 後漂移
③ 「哪些警報最常發生？」→ 按 description 分組統計頻率，找出高頻故障模式
④ 根因分析：結合 DC 時序，找出 Alarm 發生與 SPC OOC 的時間相關性

⚠️ 必填：equipment_id、start、end（時間窗口）
⚠️ resolved_at=null 代表此時此刻事件仍然持續（例如機台仍在 Hold 中）`,
    is_handoff: false,
    parameters: {
      equipment_id: { type: "string", description: "機台 ID，例如 EQP-01", required: true },
      start:        { type: "string", description: "查詢起始時間（ISO 8601）", required: true },
      end:          { type: "string", description: "查詢結束時間（ISO 8601）", required: true },
    },
    usage_example: "查詢 EQP-05 在 OOC 前後 48 小時內是否有 PM 或 Alarm：呼叫 get_event_log(equipment_id='EQP-05', start='...', end='...')，過濾 event_type IN ['PM','ALARM']，確認時間序列關係。",
    output_description: "回傳 [{ event_id, equipment_id, event_type, severity, description, timestamp, resolved_at }]。resolved_at=null 表示事件仍在持續中。",
  },
  {
    name: "get_tools_status",
    description: `【所有機台即時狀態總覽】一次取得廠內全部機台（EQP-01 ~ EQP-10）的當前運作狀態，無需任何參數。

回傳欄位說明（每台機台）：
- equipment_id: 機台代碼
- name: 機台名稱（如 Etch Tool 01、CVD Tool 01）
- status: 當前狀態 — "running"（有批次在加工）、"idle"（閒置待機）、"alarm"（警報中）、"maintenance"（保養中）、"down"（停機）
- current_lot: 若 running，顯示當前加工的批次 ID；其餘狀態為 null
- last_activity: 最後一次活動的時間戳（ISO 8601）

典型使用情境：
① 「現在哪些機台是閒置的？」→ 直接呼叫，過濾 status="idle"
② 「有沒有機台在警報狀態？」→ 過濾 status="alarm" 或 "down"
③ 廠況健康度快速掃描 → 統計各狀態機台數量，做出廠況摘要
④ 作為分析起點：先掌握整體廠況，再針對異常機台進行深入查詢

⚠️ 此 MCP 不需要任何參數，直接呼叫即可取得全廠機台狀態
⚠️ 若需要特定機台的詳細製程歷史，請接著用 equipment_id 呼叫 get_dc_timeseries 或 get_event_log`,
    is_handoff: false,
    parameters: {},
    usage_example: "作為分析第一步：呼叫 get_tools_status() 取得廠況快照，找出 status='alarm' 或 'down' 的機台，再針對這些機台呼叫 get_event_log 深入分析。",
    output_description: "回傳 [{ equipment_id, name, status, current_lot, last_activity }]，共 10 台機台的即時狀態陣列。",
  },
  {
    name: "get_lot_trace",
    description: `【批次流轉軌跡】取得指定 Lot（批次/晶圓批）在各機台間的完整流轉記錄，追蹤從投入到完成的全程加工路徑。

回傳欄位說明：
- lot_id: 批次識別碼
- status: 批次當前狀態 — "Processing"（加工中）、"Waiting"（等待中）、"Finished"（完成）、"Hold"（保留）
- current_step: 目前所在的製程站點編號
- route: [{step, equipment_id, start_time, end_time, spc_status, cycle_time_min}] — 每站的加工記錄
  - step: 站點代碼（如 STEP_001、STEP_007）
  - equipment_id: 使用的機台
  - spc_status: 該站 SPC 結果 — "PASS"、"OOC"、"N/A"
  - cycle_time_min: 該站實際加工時間（分鐘）
- ooc_steps: 發生 SPC OOC 的站點清單（快速鎖定問題站）
- total_cycle_time_hrs: 累計加工時間（小時）

典型使用情境：
① 「Lot-0007 在哪個站發生 OOC？」→ 直接查看 ooc_steps 欄位
② 追蹤批次當前位置：查看 status 和 current_step
③ 良率分析：找出多個 Lot 共同 OOC 的站點，判斷是系統性問題
④ 週期時間分析：比較 route 中各站 cycle_time_min，找出瓶頸站

⚠️ 必填：lot_id（格式為 LOT-XXXX，例如 LOT-0007）`,
    is_handoff: false,
    parameters: {
      lot_id: { type: "string", description: "批次 ID，格式為 LOT-XXXX，例如 LOT-0007", required: true },
    },
    usage_example: "追蹤問題批次：呼叫 get_lot_trace(lot_id='LOT-0007')，讀取 ooc_steps 找出 OOC 站點，再對那些站點的機台呼叫 get_dc_timeseries 或 get_spc_data 深入分析。",
    output_description: "回傳 { lot_id, status, current_step, route: [{step, equipment_id, spc_status, cycle_time_min, ...}], ooc_steps: [...], total_cycle_time_hrs }。",
  },
  {
    name: "get_spc_data",
    description: `【SPC 統計製程控制完整報告】取得指定機台 × 參數的統計製程控制分析，包含管制圖資料、UCL/LCL 管制界限、OOC 批次清單與趨勢摘要。

回傳欄位說明：
- equipment_id / parameter: 查詢的機台與參數
- charts: [{timestamp, lot_id, value, ucl, lcl, is_ooc}] — 管制圖完整資料點
- ucl / lcl / mean / std_dev: 整體管制界限統計值
- ooc_events: [{lot_id, timestamp, value, deviation_pct}] — 所有 OOC 事件清單，含偏差百分比
- consecutive_ooc: 最長連續 OOC 序列長度（>= 3 通常為系統性偏移警示）
- trend: "STABLE"（穩定）、"DRIFTING_UP"（持續上漂）、"DRIFTING_DOWN"（持續下漂）、"OSCILLATING"（震盪）
- summary: 一句可直接引用的 SPC 狀況摘要

典型使用情境：
① 完整 SPC 報告：一次取得管制圖 + OOC 事件 + 趨勢判斷
② 「最近 OOC 了幾次？」→ 查看 ooc_events 數量
③ 連續 OOC 警示：consecutive_ooc >= 3 表示製程可能已失控，需立即介入
④ 趨勢判斷：trend="DRIFTING_UP" 代表參數持續向上漂移，即使尚未 OOC 也需要注意

⚠️ 必填：equipment_id、parameter、start、end
⚠️ 與 get_dc_timeseries 差別：此工具提供完整 SPC 分析報告（趨勢判斷、OOC 摘要）；get_dc_timeseries 只提供原始時序值，適合自行作圖
⚠️ 建議時間窗口至少涵蓋 30 個批次以上，以確保管制界限統計的可靠性`,
    is_handoff: false,
    parameters: {
      equipment_id: { type: "string", description: "機台 ID，例如 EQP-01", required: true },
      parameter:    { type: "string", description: "量測參數名稱，例如 Temperature、Pressure、RF Power", required: true },
      start:        { type: "string", description: "查詢起始時間（ISO 8601）", required: true },
      end:          { type: "string", description: "查詢結束時間（ISO 8601）", required: true },
    },
    usage_example: "評估機台整體 SPC 狀況：呼叫 get_spc_data(equipment_id='EQP-03', parameter='Temperature', start='...', end='...')，讀取 trend 與 consecutive_ooc，判斷製程是否已失控並直接引用 summary 回覆使用者。",
    output_description: "回傳 { equipment_id, parameter, charts: [...], ucl, lcl, mean, std_dev, ooc_events: [...], consecutive_ooc, trend, summary }。summary 欄位可直接作為回覆文字。",
  },
  {
    name: "get_step_dc_timeseries",
    description: `【站點級 DC 時序】以製程站點（Step）為主鍵，取得所有通過該站的批次之 DC 量測值時間序列。適合站點維度的 SPC 分析，不受限於特定機台。

回傳欄位說明：
- step: 製程站點代碼（大寫，例如 STEP_007）
- parameter: 查詢的感測器顯示名稱（例如 Chamber Press）
- sensor_key: 實際使用的感測器代碼（例如 sensor_01）
- data: [{eventTime, lotID, toolID, value, is_ooc}] — 依時間升序排列的量測點，每點對應一批貨
- ucl / lcl / mean / std_dev: 由全部批次計算的 3-sigma 管制界限
- ooc_count / total_points: OOC 筆數與總筆數
- pass_rate: 良率百分比
- ooc_timestamps: OOC 事件的時間戳清單（最多 10 筆）

典型使用情境：
① 「STEP_007 這個站的腔壓有沒有跑掉？」→ step='STEP_007', parameter='Chamber Press'
② 站點跨機台趨勢分析：同一站點的資料混合多台機台，能看出是否有特定機台造成偏差
③ 新製程站點的基線建立：比較早期批次與近期批次的 UCL/LCL 變化

⚠️ 必填：step（站點代碼）、parameter（感測器顯示名稱，見下方清單）
⚠️ parameter 可用值：Chamber Press, Foreline Press, Load Lock Press, Transfer Press, ESC Zone1 Temp, ESC Zone2 Temp, ESC Zone3 Temp, Chuck Temp, Wall Temp, Ceiling Temp, Source Power HF, Source Refl HF, Bias Power LF, Bias Voltage, Bias Current, CF4 Flow, O2 Flow, Ar Flow, N2 Flow, Total Flow
⚠️ 與 get_dc_timeseries 差別：此工具以站點為主鍵（跨機台），get_dc_timeseries 以機台為主鍵（跨站點）`,
    is_handoff: false,
    parameters: {
      step:      { type: "string", description: "製程站點代碼，例如 STEP_007、STEP_001（不分大小寫）", required: true },
      parameter: { type: "string", description: "感測器顯示名稱，例如 Chamber Press、ESC Zone1 Temp、Source Power HF", required: true },
      limit:     { type: "number", description: "最多回傳幾筆（預設 100，最大 500）", required: false },
      start:     { type: "string", description: "查詢起始時間（ISO 8601），例如 2025-01-01T00:00:00Z", required: false },
      end:       { type: "string", description: "查詢結束時間（ISO 8601）", required: false },
    },
    usage_example: "分析 STEP_007 腔壓趨勢：呼叫 get_step_dc_timeseries(step='STEP_007', parameter='Chamber Press', limit=100)，掃描 is_ooc=true 的批次，並比對 toolID 找出是否集中在某台機台。",
    output_description: "回傳 { step, parameter, sensor_key, total_points, ooc_count, pass_rate, ucl, lcl, mean, std_dev, ooc_timestamps, sample_data: [{eventTime, lotID, toolID, value, is_ooc}] }。sample_data 提供前 3 + 後 3 筆供預覽，完整資料在 data 陣列。",
  },
  {
    name: "get_step_spc_chart",
    description: `【站點級 SPC 管制圖】以製程站點（Step）為主鍵，取得特定 SPC 管制圖（xbar_chart / r_chart / s_chart / p_chart / c_chart）的完整時序資料，含趨勢判斷與連續 OOC 分析。

回傳欄位說明：
- step: 製程站點代碼
- chart_name: 使用的管制圖類型
- data: [{eventTime, lotID, toolID, value, ucl, lcl, is_ooc}] — 每點對應一批貨的管制圖量測值
- total_points / ooc_count / pass_rate: 總點數、OOC 數、良率
- consecutive_ooc: 最大連續 OOC 序列長度（>= 3 為系統性失控警示）
- trend: "STABLE" | "DRIFTING_UP" | "DRIFTING_DOWN" | "OSCILLATING"
- ooc_timestamps: OOC 事件時間戳清單（最多 10 筆）

管制圖類型說明：
- xbar_chart: 均值管制圖（最常用，監控製程均值漂移）
- r_chart: 全距管制圖（監控批次內變異）
- s_chart: 標準差管制圖（比 r_chart 更精確的變異管制）
- p_chart: 不良率管制圖（適合 Pass/Fail 類型的良率監控）
- c_chart: 缺陷數管制圖（監控每批次的缺陷發生數）

典型使用情境：
① 「STEP_007 的 xbar 有沒有漂移？」→ step='STEP_007', chart_name='xbar_chart'
② 連續 OOC 警示：consecutive_ooc >= 3 代表製程可能已系統性失控
③ 趨勢判斷：trend='DRIFTING_UP' 即使未 OOC 也預示問題將發生
④ 跨機台 SPC 比較：同站點的資料混合所有機台，能判斷是製程站點問題還是特定機台問題

⚠️ 必填：step（站點代碼）、chart_name（管制圖類型）
⚠️ chart_name 只能是：xbar_chart、r_chart、s_chart、p_chart、c_chart`,
    is_handoff: false,
    parameters: {
      step:       { type: "string", description: "製程站點代碼，例如 STEP_007（不分大小寫）", required: true },
      chart_name: { type: "string", description: "SPC 管制圖類型", required: true, enum: ["xbar_chart", "r_chart", "s_chart", "p_chart", "c_chart"] },
      limit:      { type: "number", description: "最多回傳幾筆（預設 100，最大 500）", required: false },
      start:      { type: "string", description: "查詢起始時間（ISO 8601）", required: false },
      end:        { type: "string", description: "查詢結束時間（ISO 8601）", required: false },
    },
    usage_example: "診斷 STEP_007 製程失控：呼叫 get_step_spc_chart(step='STEP_007', chart_name='xbar_chart', limit=100)，讀取 trend 和 consecutive_ooc，若 consecutive_ooc >= 3 或 trend != 'STABLE' 則升級為緊急警示。",
    output_description: "回傳 { step, chart_name, total_points, ooc_count, pass_rate, consecutive_ooc, trend, ooc_timestamps, sample_data: [{eventTime, lotID, toolID, value, ucl, lcl, is_ooc}] }。",
  },
  {
    name: "list_object_schema",
    description: `【Object 參數目錄】查詢特定製程物件（APC / EC / FDC / SPC / RECIPE / DC）所有可查詢的 parameter 清單及其 metadata，包含推斷資料型別、覆蓋率、值域範圍、可過濾的屬性欄位。

用途：在呼叫 query_object_parameter 之前，先用此工具確認可查詢的 parameter key 和可用的 conditions 欄位。

回傳欄位說明：
- object_name: 物件類型名稱
- parameters: [{key, inferred_type, coverage_pct, sample_range}] — 可查詢的數值型 parameter
- filterable_fields: [{key, inferred_type, enum_sample}] — 可作為 conditions 的屬性欄位
- fixed_axes: ["lotID", "toolID", "step"] — 永遠可用的過濾軸

各物件的典型 parameters：
- APC: parameters.param_01（R2R Bias）~ parameters.param_20（Response Factor）
- EC: pm_count, wafers_since_pm, chamber_age_hrs, component_health.rf_match, component_health.esc
- FDC: confidence（0.0~1.0 故障信心度）
- SPC: charts.xbar_chart.value, charts.r_chart.value, charts.s_chart.value 等

⚠️ 此工具不需要 step，只需要 object_name
⚠️ 若不確定有哪些 parameters，先呼叫此工具再呼叫 query_object_parameter`,
    is_handoff: false,
    parameters: {
      object_name: { type: "string", description: "物件類型：APC | EC | FDC | SPC | RECIPE | DC", required: true },
    },
    usage_example: "準備查詢 APC 參數前：呼叫 list_object_schema(object_name='APC') 取得所有可查詢 parameter key（如 parameters.param_01）和可過濾屬性（如 mode、objectID），再決定要查哪個 parameter。",
    output_description: "回傳 { object_name, parameters: [{key, inferred_type, coverage_pct, sample_range}], filterable_fields: [{key, enum_sample}], fixed_axes }。",
  },
  {
    name: "query_object_parameter",
    description: `【Object 參數時序查詢】以製程物件類型（APC/EC/FDC/SPC/RECIPE/DC）+ 站點（step）為主鍵，查詢某個 parameter 在指定時間段內的完整時序，支援多屬性條件過濾。

這是 Object-centric 的查詢入口，與 get_step_dc_timeseries（sensor 層）互補：
- get_step_dc_timeseries → DC 物件的 sensor 值時序（固定格式）
- query_object_parameter → 任何物件的任意 parameter 時序（動態 schema）

回傳欄位說明：
- object_name / parameter / step: 查詢鍵
- filter_applied: 實際套用的 MongoDB filter（含 conditions 轉換後的結果）
- stats: { mean, ucl, lcl, std_dev, ooc_count, pass_rate } — 3-sigma 管制統計
- data: [{eventTime, lotID, toolID, value, is_ooc, context?}] — 完整時序

conditions 使用方式：
- 精確比對：{"model_version": "v2.1"}
- IN 列表：{"model_version": ["v2.0", "v2.1"]}
- 數值範圍：{"confidence": {"gte": 0.8}}
- 複合：{"fault_class": "Fault", "model_version": ["v2.0", "v2.1"]}

典型使用情境：
① APC model drift：query_object_parameter(object_name='APC', parameter='parameters.param_01', step='STEP_007') 看 R2R Bias 是否漂移
② EC 健康度趨勢：parameter='component_health.rf_match', conditions={"seasoning_status": "Aging"}
③ FDC 高信心故障篩選：parameter='confidence', conditions={"fault_class": "Fault", "confidence": {"gte": 0.85}}
④ 跨 model 版本比較：conditions={"objectID": "APC-007", "mode": "Run-to-Run"}

⚠️ 必填：object_name, parameter, step
⚠️ parameter key 必須先用 list_object_schema 確認（例如 APC 的是 'parameters.param_01'，不是 'param_01'）
⚠️ conditions 的 key 也必須在 list_object_schema 回傳的 filterable_fields 清單內`,
    is_handoff: false,
    parameters: {
      object_name: { type: "string", description: "物件類型：APC | EC | FDC | SPC | RECIPE | DC", required: true },
      parameter:   { type: "string", description: "parameter key（dot-notation），例如 parameters.param_01、component_health.rf_match、confidence", required: true },
      step:        { type: "string", description: "製程站點，例如 STEP_007（不分大小寫）", required: true },
      start:       { type: "string", description: "查詢起始時間（ISO 8601）", required: false },
      end:         { type: "string", description: "查詢結束時間（ISO 8601）", required: false },
      conditions:  { type: "object", description: "額外過濾條件 JSON，key 為 filterable_fields 中的欄位，value 為 scalar / list / {gte/lte/gt/lt: val}", required: false },
      limit:       { type: "number", description: "最多回傳幾筆（預設 200，最大 500）", required: false },
    },
    usage_example: "診斷 APC Run-to-Run Bias 異常：呼叫 query_object_parameter(object_name='APC', parameter='parameters.param_01', step='STEP_007', conditions={'mode': 'Run-to-Run'}, limit=100)，掃描 is_ooc=true 的批次，確認是否持續偏移。",
    output_description: "回傳 { object_name, parameter, step, filter_applied, total_points, stats: {mean, ucl, lcl, std_dev, ooc_count, pass_rate}, data: [{eventTime, lotID, toolID, value, is_ooc, context?}] }。",
  },
];

// ---------------------------------------------------------------------------
// Handoff MCPs
// ---------------------------------------------------------------------------

export const HANDOFF_MCPS: MCPDefinition[] = [
  {
    name: "open_lot_trace",
    description: `【開啟批次流轉追蹤面板】在 AIOps UI 中開啟 Lot Trace 視覺化面板，讓使用者可以互動式地追蹤批次的完整流轉路徑與各站狀態。呼叫此工具後，AIOps 系統接管 UI 互動，Agent 停止進一步的文字分析。

適用場景：
- 使用者想「看」批次的流轉路徑，而非只是讀取文字摘要
- 需要視覺化呈現多站 OOC 的分布狀況
- 使用者想在 UI 上點擊個別站點查看詳細資料

⚠️ 這是 UI 導向工具（Handoff）：呼叫後頁面會跳轉至 Lot Trace 面板，適合在分析末尾引導使用者進行互動式探索`,
    is_handoff: true,
    parameters: {
      equipment_id: { type: "string", description: "機台 ID（選填）：預先過濾顯示特定機台相關批次", required: false },
      lot_id:       { type: "string", description: "Lot ID（選填）：直接定位到特定批次，例如 LOT-0007", required: false },
    },
    usage_example: "當使用者說「我想看 LOT-0007 的流程圖」→ 呼叫 open_lot_trace(lot_id='LOT-0007')，UI 自動切換到 Lot Trace 面板並定位到該批次。",
    output_description: "不回傳資料。呼叫後 UI 跳轉到 Lot Trace 面板，Agent 應停止後續文字分析，改為描述「已開啟視覺化面板」。",
  },
  {
    name: "open_drill_down",
    description: `【開啟設備詳細下鑽面板】在 AIOps UI 中開啟指定設備的詳細分析面板，含即時狀態、DC 時序圖、SPC 管制圖、設備常數比對等完整視圖。呼叫後 AIOps 接管 UI，使用者可以在面板上互動探索。

適用場景：
- 使用者想深入查看某台機台的完整運作狀況
- 分析過程中發現某台機台可疑，引導使用者進行視覺化確認
- 使用者說「讓我看看 EQP-04 的詳細情況」

包含的面板內容：
- 機台即時狀態與當前批次
- 最近 DC 參數趨勢圖（Temperature、Pressure、RF Power 等）
- SPC 管制圖（帶 UCL/LCL 標記）
- Equipment Constants 偏差分析
- 最近設備事件記錄（Alarm、PM、Downtime）

⚠️ 這是 UI 導向工具（Handoff）：呼叫後頁面跳轉至設備詳情頁，equipment_id 為必填`,
    is_handoff: true,
    parameters: {
      equipment_id: { type: "string", description: "目標機台 ID，格式 EQP-XX，例如 EQP-04", required: true },
    },
    usage_example: "當使用者說「讓我看 EQP-03 的詳細狀況」或分析後發現 EQP-03 最可疑 → 呼叫 open_drill_down(equipment_id='EQP-03')，UI 跳轉到該機台詳情頁。",
    output_description: "不回傳資料。呼叫後 UI 跳轉到設備詳情頁，Agent 應說明「已開啟 EQP-XX 的詳細面板」並停止進一步分析。",
  },
  {
    name: "open_topology",
    description: `【開啟廠區製程拓撲視圖】在 AIOps UI 中開啟廠區製程拓撲圖（Topology View），以節點圖方式呈現 LOT、TOOL、RECIPE、APC、DC、SPC、EC、FDC、OCAP 九類製程物件之間的關聯關係。呼叫後 AIOps 接管 UI 互動。

拓撲圖展示的關係：
- TOOL-bound（設備端）：RECIPE（配方）、EC（設備健康狀態）、FDC（故障偵測）
- LOT-bound（批次端）：APC（補償控制）、DC（量測資料）、SPC（統計管制）、OCAP（異常處置計畫）
- 主幹線：TOOL ↔ LOT（設備與批次的加工關係）

節點顏色語意：
- SPC 節點：PASS=綠色，OOC=紅色
- FDC 節點：Normal=綠色，Warning=黃色，Fault=紅色
- OCAP 節點：P1=紅色（緊急），P2=黃色（警告），未觸發=灰色（半透明）

適用場景：
- 使用者想全面了解某批次/機台的製程物件關聯
- 解釋 OOC 根因時，展示 FDC 偵測到的故障與 OCAP 建議行動的關聯
- 引導使用者進行多維度的製程狀態探索

⚠️ 這是 UI 導向工具（Handoff）：無需參數，直接開啟拓撲視圖`,
    is_handoff: true,
    parameters: {},
    usage_example: "當使用者說「讓我看製程整體關係」或需要解釋多物件之間的依賴關係時 → 呼叫 open_topology()，UI 切換到拓撲圖，使用者可點擊各節點探索。",
    output_description: "不回傳資料。呼叫後 UI 切換至拓撲視圖，Agent 說明「已開啟製程拓撲視圖」並停止進一步分析。",
  },
];

// ---------------------------------------------------------------------------
// AIOps Automation MCPs (Agent → AIOps Platform)
// ---------------------------------------------------------------------------

export const AIOPS_MCPS: MCPDefinition[] = [
  {
    name: "register_cron_job",
    description: "【AIOps 排程】為指定 Skill 建立 Cron Job，讓 AIOps 平台依排程自動執行診斷腳本。",
    is_handoff: false,
    parameters: {
      skill_id:  { type: "integer", description: "目標 Skill 的 ID", required: true },
      schedule:  { type: "string",  description: "Cron 表達式，例如 '0 8 * * *'（每天早上 8 點）", required: true },
      timezone:  { type: "string",  description: "時區，預設 'Asia/Taipei'", required: false },
      label:     { type: "string",  description: "排程標籤，方便識別", required: false },
    },
    usage_example: "使用者說「讓這個 Skill 每天早上 8 點自動跑」→ 呼叫 register_cron_job(skill_id=X, schedule='0 8 * * *')。",
    output_description: "回傳 CronJob 物件，含 id、next_run_at、status(active)。",
  },
  {
    name: "list_cron_jobs",
    description: "【AIOps 排程】列出所有（或指定 Skill 的）Cron Jobs，含 schedule、last_run_at、next_run_at。",
    is_handoff: false,
    parameters: {
      skill_id: { type: "integer", description: "篩選特定 Skill 的排程（選填）", required: false },
    },
    usage_example: "使用者說「目前有哪些排程？」→ 呼叫 list_cron_jobs() 取得清單。",
    output_description: "回傳 CronJob 陣列，每筆含 id, skill_id, schedule, timezone, label, status, last_run_at, next_run_at。",
  },
  {
    name: "delete_cron_job",
    description: "【AIOps 排程】刪除（軟刪除）指定 Cron Job，停止後續排程觸發。",
    is_handoff: false,
    parameters: {
      job_id: { type: "integer", description: "要刪除的 CronJob ID", required: true },
    },
    usage_example: "使用者說「停止排程 ID 3」→ 呼叫 delete_cron_job(job_id=3)。",
    output_description: "回傳 { deleted: true, job_id }。",
  },
  {
    name: "list_pending_scripts",
    description: "【Script Registry】列出所有待人工審核的 draft 版本腳本。用於提醒使用者有 Script 等待核准。",
    is_handoff: false,
    parameters: {},
    usage_example: "使用者說「有沒有腳本在等待核准？」→ 呼叫 list_pending_scripts()。",
    output_description: "回傳 ScriptVersion 陣列，每筆含 id, skill_id, version, status(draft), change_note, generated_at。",
  },
  {
    name: "approve_script",
    description: "【Script Registry】核准指定 ScriptVersion（draft → active），使其成為 Skill 的執行腳本。需要人工確認。",
    is_handoff: false,
    parameters: {
      version_id: { type: "integer", description: "要核准的 ScriptVersion ID", required: true },
    },
    usage_example: "使用者說「核准腳本版本 ID 5」→ 呼叫 approve_script(version_id=5)。",
    output_description: "回傳 ScriptVersion 物件，status 變更為 active，含 approved_at、reviewed_by。",
  },
  {
    name: "rollback_script",
    description: "【Script Registry】將 Skill 的執行腳本回滾到指定歷史版本。",
    is_handoff: false,
    parameters: {
      skill_id:       { type: "integer", description: "目標 Skill ID", required: true },
      target_version: { type: "integer", description: "要還原到的版本號", required: true },
    },
    usage_example: "使用者說「把 Skill 2 回滾到版本 3」→ 呼叫 rollback_script(skill_id=2, target_version=3)。",
    output_description: "回傳重新 active 的 ScriptVersion 物件。",
  },
  {
    name: "test_run_skill",
    description: "【Script Registry】用測試 EventContext 在沙盒執行指定 Skill 的腳本版本，不產生任何副作用。用於驗證腳本邏輯。",
    is_handoff: false,
    parameters: {
      skill_id:      { type: "integer", description: "目標 Skill ID", required: true },
      event_type:    { type: "string",  description: "測試事件類型，例如 'manual' | 'cron' | 'spc_ooc'", required: true },
      event_time:    { type: "string",  description: "ISO 8601 時間戳記，選填（預設現在）", required: false },
      payload:       { type: "object",  description: "測試 payload（JSON），選填", required: false },
      version:       { type: "integer", description: "測試特定版本號，選填（預設最新 draft 或 active）", required: false },
    },
    usage_example: "使用者說「幫我測試一下這個 Skill 的腳本」→ 呼叫 test_run_skill(skill_id=X, event_type='manual')。",
    output_description: "回傳 { status: success|error|timeout, diag_status, diagnosis_message, problem_object, duration_ms }。",
  },
  {
    name: "dispatch_action",
    description: "【Action Dispatcher】觸發自動化動作（通知工程師 / Hold 機台 / 建立 OCAP 等）。Critical 動作會回傳 requires_confirm=true，需使用者確認。",
    is_handoff: false,
    parameters: {
      action_type:  { type: "string",  description: "動作類型：hold_equipment | notify_engineer | escalate | create_ocap | monitor", required: true, enum: ["hold_equipment", "notify_engineer", "escalate", "create_ocap", "monitor"] },
      target_id:    { type: "string",  description: "目標 ID（機台代碼 / Lot ID / 工程師帳號等）", required: true },
      severity:     { type: "string",  description: "嚴重性：critical | high | warning | info", required: false, enum: ["critical", "high", "warning", "info"] },
      message:      { type: "string",  description: "給工程師的說明訊息", required: false },
      evidence:     { type: "object",  description: "輔助證據（JSON），例如 { spc_ooc_count: 3 }", required: false },
      auto_execute: { type: "boolean", description: "是否跳過確認（僅適用於非 critical 動作）", required: false },
    },
    usage_example: "診斷發現 TETCH01 SPC OOC → 呼叫 dispatch_action(action_type='notify_engineer', target_id='TETCH01', severity='high', message='SPC OOC 3 筆')。",
    output_description: "回傳 { dispatched, action_type, target_id, message, requires_confirm }。requires_confirm=true 時需顯示確認對話框。",
  },
];

// ---------------------------------------------------------------------------
// Combined catalog (for injection into Agent)
// ---------------------------------------------------------------------------

export const MCP_CATALOG: MCPDefinition[] = [...DATA_MCPS, ...HANDOFF_MCPS, ...AIOPS_MCPS];
