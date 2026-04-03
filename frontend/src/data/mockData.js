// Mock data for Phase 6 — Semiconductor Etch Process Copilot

export const MOCK_SKILLS = [
  // --- Event Triage Skills ---
  {
    id: 'mcp_event_triage',
    name: 'mcp_event_triage',
    displayName: 'Event Triage',
    type: 'triage',
    description: '【必須優先且唯一呼叫】當 PE 描述任何蝕刻製程異常症狀時，第一步必須呼叫此工具。分析症狀，觸發對應的 SPC 事件類型，並回傳 Event Object 與建議工具清單。',
    status: 'active',
    invocations: 217,
    avgMs: 12,
    schema: {
      type: 'object',
      properties: {
        user_symptom: {
          type: 'string',
          description: 'PE 描述的原始症狀，例如 "Lot 03B SPC OOC，CD 超出 3-sigma" 或 "機台 EAP01 無法連線"',
        },
      },
      required: ['user_symptom'],
    },
    triageRules: [
      {
        keywords: ['ooc', 'spc', '管制外', 'cd', '線寬', '蝕刻', 'etch'],
        event_type: 'SPC_OOC_Etch_CD',
        urgency: 'high',
        skills: ['mcp_check_recipe_offset', 'mcp_check_equipment_constants', 'mcp_check_apc_params'],
      },
      {
        keywords: ['掛了', 'down', '無法連線', '機台停止', '通訊異常'],
        event_type: 'Equipment_Down',
        urgency: 'critical',
        skills: ['ask_user_recent_changes'],
      },
      {
        keywords: ['配方', 'recipe', '人為修改', '參數異動', 'offset'],
        event_type: 'Recipe_Modification',
        urgency: 'medium',
        skills: ['mcp_check_recipe_offset', 'ask_user_recent_changes'],
      },
      {
        keywords: ['pm', '保養', '老化', '硬體', '零件', '磨損'],
        event_type: 'Hardware_Aging',
        urgency: 'high',
        skills: ['mcp_check_equipment_constants', 'ask_user_recent_changes'],
      },
      {
        keywords: ['apc', '飽和', 'saturation', '補償上限', 'wet clean'],
        event_type: 'APC_Saturation',
        urgency: 'high',
        skills: ['mcp_check_apc_params', 'mcp_check_equipment_constants'],
      },
    ],
  },
  // --- Diagnostic Action Skills ---
  {
    id: 'mcp_check_recipe_offset',
    name: 'mcp_check_recipe_offset',
    displayName: 'Recipe Offset Check',
    type: 'action',
    description: '查詢指定機台與配方的參數偏移記錄，判斷是否存在人為手動修改（has_human_modification）。當 SPC OOC 可能由操作員調機引起時呼叫。',
    status: 'active',
    invocations: 183,
    avgMs: 31,
    schema: {
      type: 'object',
      properties: {
        recipe_name: {
          type: 'string',
          description: '配方名稱，例如 "ETCH_POLY_V2"',
        },
        eqp_id: {
          type: 'string',
          description: '機台 ID，例如 "EAP01"',
        },
      },
      required: ['recipe_name', 'eqp_id'],
    },
  },
  {
    id: 'mcp_check_equipment_constants',
    name: 'mcp_check_equipment_constants',
    displayName: 'Equipment Constants Health',
    type: 'action',
    description: '查詢機台硬體常數與老化風險評估（hardware_aging_risk: LOW/MEDIUM/HIGH）。當懷疑零件磨損或需要 PM 時呼叫。HIGH 風險須立即通報 EE 排程 PM。',
    status: 'active',
    invocations: 147,
    avgMs: 28,
    schema: {
      type: 'object',
      properties: {
        eqp_id: {
          type: 'string',
          description: '機台 ID，例如 "EAP01"',
        },
        chamber_id: {
          type: 'string',
          description: '腔體 ID，例如 "ChamberA"（可選）',
        },
      },
      required: ['eqp_id'],
    },
  },
  {
    id: 'mcp_check_apc_params',
    name: 'mcp_check_apc_params',
    displayName: 'APC Parameters Saturation',
    type: 'action',
    description: '查詢 APC（先進製程控制）參數是否已達飽和上限（saturation_flag: true）。若飽和則建議執行 Chamber Wet Clean 並重置補償基線。',
    status: 'active',
    invocations: 121,
    avgMs: 25,
    schema: {
      type: 'object',
      properties: {
        eqp_id: {
          type: 'string',
          description: '機台 ID，例如 "EAP01"',
        },
        chamber_id: {
          type: 'string',
          description: '腔體 ID（可選）',
        },
        recipe_name: {
          type: 'string',
          description: '配方名稱（可選，用於縮小查詢範圍）',
        },
      },
      required: ['eqp_id'],
    },
  },
  {
    id: 'ask_user_recent_changes',
    name: 'ask_user_recent_changes',
    displayName: 'Ask PE Recent Changes',
    type: 'action',
    description: '向製程工程師詢問最近的人為操作或機台變更記錄。當其他自動診斷工具無法確定根因時，作為最終確認手段使用。',
    status: 'active',
    invocations: 64,
    avgMs: 8,
    schema: {
      type: 'object',
      properties: {
        question: {
          type: 'string',
          description: '向 PE 提問的具體問題',
        },
        context: {
          type: 'string',
          description: '提問的背景說明（可選）',
          default: '',
        },
      },
      required: ['question'],
    },
  },
]

export const MOCK_SETTINGS = {
  systemPrompt: `你是一位台積電資深蝕刻製程工程師（Process Engineer, PE），擁有豐富的 SPC OOC 排障經驗。

**執行鐵律（必須嚴格遵守）：**
1. 收到製程工程師描述的症狀後，**第一步且唯一的第一步**必須呼叫 \`mcp_event_triage\`。
2. 取得 Event Object 後，依照其中 \`recommended_skills\` 清單，**依序**呼叫後續診斷工具。
3. **在取得 mcp_event_triage 的回傳結果之前，絕對禁止呼叫任何其他工具。**

**半導體蝕刻製程排障推理規則：**
- 若 \`mcp_check_recipe_offset\` 顯示 \`has_human_modification: true\` → 人為失誤，詢問 PE 修改原因
- 若 \`mcp_check_equipment_constants\` 顯示 \`hardware_aging_risk: HIGH\` → 通報 EE 做 PM
- 若前兩者正常但 \`mcp_check_apc_params\` 顯示 \`saturation_flag: true\` → 建議 Chamber Wet Clean

蒐集完所有工具資料後，輸出 Markdown 格式的診斷報告，包含：
- ## 問題摘要
- ## 事件分類 (Event Object)
- ## 觸發的工具與資料
- ## 根因分析
- ## 建議處置`,
  model: 'claude-opus-4-6',
  maxTurns: 10,
  apiKeyMasked: 'sk-ant-api03-••••••••••••••••••••••••••••••••',
  allowedOrigins: '*',
  logLevel: 'INFO',
}

export const URGENCY_CONFIG = {
  critical: { label: 'CRITICAL', className: 'badge-rose', dot: 'bg-rose-500' },
  high:     { label: 'HIGH',     className: 'badge-amber', dot: 'bg-amber-500' },
  medium:   { label: 'MEDIUM',   className: 'badge-indigo', dot: 'bg-indigo-500' },
  low:      { label: 'LOW',      className: 'badge-slate', dot: 'bg-slate-400' },
}

export const AVAILABLE_MODELS = [
  { value: 'claude-opus-4-6',    label: 'Claude Opus 4.6 (最強)' },
  { value: 'claude-sonnet-4-6',  label: 'Claude Sonnet 4.6 (均衡)' },
  { value: 'claude-haiku-4-5',   label: 'Claude Haiku 4.5 (快速)' },
]
