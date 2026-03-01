/**
 * Phase 6 — AI Skill Builder Copilot
 *
 * A wide right-side drawer with three sections:
 *   A. Event Trigger & AI PE Suggestions  (/suggest-logic)
 *   B. MCP Tool Binding & Auto-Mapping    (/auto-map)
 *   C. Diagnostic Logic & Semantic Guard  (/validate-logic)
 */

import { useState, useEffect, useCallback } from 'react'
import { X, Zap, ArrowRight, CheckCircle, AlertTriangle, Plus } from 'lucide-react'
import * as builderApi from '../services/builderApi'

// ---------------------------------------------------------------------------
// Event catalogue (SPC OOC events the system understands)
// ---------------------------------------------------------------------------

const EVENTS = [
  {
    value: 'SPC_OOC_Etch_CD',
    label: 'SPC_OOC_Etch_CD — 蝕刻線寬 (CD) SPC 管制外',
    schema: {
      event_type: 'SPC_OOC_Etch_CD',
      description: '蝕刻製程 Critical Dimension SPC 超出管制界限事件',
      attributes: {
        lot_id:                { type: 'string',  description: '批號，例如 "LOT03B"' },
        eqp_id:                { type: 'string',  description: '機台 ID，例如 "EAP01"' },
        chamber_id:            { type: 'string',  description: '腔體 ID，例如 "ChamberA"' },
        recipe_name:           { type: 'string',  description: '製程配方名稱，例如 "ETCH_POLY_V2"' },
        rule_violated:         { type: 'string',  description: '違反的 SPC 規則，例如 "Nelson Rule 1"' },
        consecutive_ooc_count: { type: 'integer', description: '連續 OOC 次數' },
        control_limit_type:    { type: 'string',  enum: ['1-sigma', '2-sigma', '3-sigma'], description: '管制極限類型' },
      },
    },
  },
]

// ---------------------------------------------------------------------------
// MCP tool catalogue (input & output schemas for each tool)
// ---------------------------------------------------------------------------

const MCP_TOOLS = [
  {
    name: 'mcp_check_recipe_offset',
    label: '配方偏移檢查 (Recipe Offset)',
    inputSchema: {
      type: 'object',
      properties: {
        recipe_name: { type: 'string', description: '配方名稱' },
        eqp_id:      { type: 'string', description: '機台 ID' },
      },
      required: ['recipe_name', 'eqp_id'],
    },
    outputSchema: {
      type: 'object',
      properties: {
        recipe_name:            { type: 'string'  },
        eqp_id:                 { type: 'string'  },
        has_human_modification: { type: 'boolean' },
        offset_details:         { type: 'object'  },
        modified_by:            { type: 'string'  },
        modified_at:            { type: 'string'  },
      },
    },
  },
  {
    name: 'mcp_check_equipment_constants',
    label: '設備常數健康檢查 (Equipment Constants)',
    inputSchema: {
      type: 'object',
      properties: {
        eqp_id:     { type: 'string', description: '機台 ID' },
        chamber_id: { type: 'string', description: '腔體 ID（可選）' },
      },
      required: ['eqp_id'],
    },
    outputSchema: {
      type: 'object',
      properties: {
        eqp_id:              { type: 'string' },
        chamber_id:          { type: 'string' },
        hardware_aging_risk: { type: 'string', enum: ['LOW', 'MEDIUM', 'HIGH'] },
        constants_summary:   { type: 'object' },
        last_pm_date:        { type: 'string' },
      },
    },
  },
  {
    name: 'mcp_check_apc_params',
    label: 'APC 參數飽和檢查 (APC Saturation)',
    inputSchema: {
      type: 'object',
      properties: {
        eqp_id:      { type: 'string', description: '機台 ID' },
        chamber_id:  { type: 'string', description: '腔體 ID（可選）' },
        recipe_name: { type: 'string', description: '配方名稱（可選）' },
      },
      required: ['eqp_id'],
    },
    outputSchema: {
      type: 'object',
      properties: {
        eqp_id:             { type: 'string'  },
        saturation_flag:    { type: 'boolean' },
        saturation_ratio:   { type: 'number'  },
        affected_params:    { type: 'array'   },
        recommended_action: { type: 'string'  },
      },
    },
  },
]

// ---------------------------------------------------------------------------
// Small reusable components
// ---------------------------------------------------------------------------

function Skeleton({ className = '' }) {
  return <div className={`animate-pulse bg-slate-200 rounded ${className}`} />
}

function SectionLabel({ letter, color, children }) {
  const colors = {
    indigo: 'bg-indigo-600',
    purple: 'bg-purple-600',
    emerald: 'bg-emerald-600',
  }
  return (
    <div className="flex items-center gap-2">
      <span className={`w-6 h-6 rounded-full ${colors[color]} text-white text-xs font-bold flex items-center justify-center flex-shrink-0`}>
        {letter}
      </span>
      <h3 className="text-sm font-semibold text-slate-700">{children}</h3>
    </div>
  )
}

function ConfidenceBadge({ confidence }) {
  const map = {
    HIGH:   'bg-emerald-100 text-emerald-700',
    MEDIUM: 'bg-amber-100 text-amber-700',
    LOW:    'bg-slate-100 text-slate-500',
  }
  return (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded flex-shrink-0 ${map[confidence] ?? map.LOW}`}>
      {confidence}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main drawer component
// ---------------------------------------------------------------------------

export default function SkillBuilderDrawer({ open, onClose }) {
  // Section A
  const [selectedEvent, setSelectedEvent] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [suggestLoading, setSuggestLoading] = useState(false)

  // Section B
  const [selectedTools, setSelectedTools] = useState([])
  const [mappings, setMappings] = useState([])   // { event_field, tool_param, confidence, reasoning, toolName }
  const [mapLoading, setMapLoading] = useState(false)

  // Section C
  const [diagnosticLogic, setDiagnosticLogic] = useState('')
  const [validation, setValidation] = useState(null)
  const [validating, setValidating] = useState(false)

  // Toast notification
  const [toast, setToast] = useState(null) // { type: 'success'|'error', message }

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    if (open) document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  // Reset all state when drawer closes
  useEffect(() => {
    if (!open) {
      setSelectedEvent('')
      setSuggestions([])
      setSelectedTools([])
      setMappings([])
      setDiagnosticLogic('')
      setValidation(null)
      setToast(null)
    }
  }, [open])

  // ── Section A: Event selection → call /suggest-logic ──────────────────────

  const handleEventChange = useCallback(async (eventValue) => {
    setSelectedEvent(eventValue)
    setSuggestions([])
    if (!eventValue) return

    const event = EVENTS.find(e => e.value === eventValue)
    if (!event) return

    setSuggestLoading(true)
    try {
      const data = await builderApi.suggestLogic(event.schema, `Event: ${eventValue}`)
      setSuggestions(data.suggestions ?? [])
    } catch (err) {
      console.error('suggest-logic failed:', err)
      setSuggestions(['（AI 建議載入失敗，請確認後端服務正常）'])
    } finally {
      setSuggestLoading(false)
    }
  }, [])

  // ── Section B: Tool checkbox toggle → call /auto-map for new tool ─────────

  const handleToolToggle = useCallback(async (toolName) => {
    const isAdding = !selectedTools.includes(toolName)

    if (!isAdding) {
      setSelectedTools(prev => prev.filter(t => t !== toolName))
      setMappings(prev => prev.filter(m => m.toolName !== toolName))
      return
    }

    setSelectedTools(prev => [...prev, toolName])

    if (!selectedEvent) return

    const event = EVENTS.find(e => e.value === selectedEvent)
    const tool = MCP_TOOLS.find(t => t.name === toolName)
    if (!event || !tool) return

    setMapLoading(true)
    try {
      const data = await builderApi.autoMap(event.schema, tool.inputSchema)
      const newMappings = (data.mappings ?? []).map(m => ({ ...m, toolName }))
      setMappings(prev => [...prev.filter(m => m.toolName !== toolName), ...newMappings])
    } catch (err) {
      console.error('auto-map failed:', err)
    } finally {
      setMapLoading(false)
    }
  }, [selectedEvent, selectedTools])

  // ── Section C: Validate diagnostic logic ─────────────────────────────────

  const handleValidate = useCallback(async () => {
    if (!diagnosticLogic.trim() || selectedTools.length === 0) return

    // Build a merged output schema from all selected tools
    const combinedProperties = {}
    selectedTools.forEach(name => {
      const tool = MCP_TOOLS.find(t => t.name === name)
      if (tool) Object.assign(combinedProperties, tool.outputSchema.properties ?? {})
    })
    const combinedSchema = { type: 'object', properties: combinedProperties }

    setValidating(true)
    setValidation(null)
    try {
      const data = await builderApi.validateLogic(diagnosticLogic, combinedSchema)
      setValidation(data)
      if (data.is_valid) {
        setToast({ type: 'success', message: '✅ 邏輯完美，所需數據工具皆已齊備。' })
        setTimeout(() => setToast(null), 4000)
      }
    } catch (err) {
      console.error('validate-logic failed:', err)
    } finally {
      setValidating(false)
    }
  }, [diagnosticLogic, selectedTools])

  // Apply a suggestion directly into the textarea
  const applySuggestion = (suggestion) => {
    setDiagnosticLogic(suggestion)
    setValidation(null)
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 bg-black/30 z-40 transition-opacity duration-200 ${
          open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
        onClick={onClose}
      />

      {/* Wide drawer panel — 60vw */}
      <div
        className={`fixed right-0 top-0 h-full w-[60vw] max-w-full bg-white shadow-2xl z-50 flex flex-col
          transform transition-transform duration-300 ease-out
          ${open ? 'translate-x-0' : 'translate-x-full'}`}
      >
        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-indigo-900/20 flex-shrink-0 bg-gradient-to-r from-indigo-600 to-purple-600">
          <div className="flex items-center gap-2.5">
            <Zap size={18} className="text-yellow-300" />
            <div>
              <h2 className="text-sm font-bold text-white leading-tight">新增技能 — AI Skill Builder Copilot</h2>
              <p className="text-xs text-indigo-200">由 AI 輔助完成，No-Code 極致體驗</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-white/20 text-white/70 hover:text-white transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* ── Scrollable content ──────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">

          {/* ═══════════════════════════════════════════════════════════════
              Section A: Event & AI Suggestions
          ═══════════════════════════════════════════════════════════════ */}
          <div className="space-y-4">
            <SectionLabel letter="A" color="indigo">事件觸發與 AI 診斷建議</SectionLabel>

            {/* Event selector */}
            <div>
              <label className="text-xs font-medium text-slate-500 mb-1.5 block">觸發事件 (Trigger Event)</label>
              <select
                value={selectedEvent}
                onChange={e => handleEventChange(e.target.value)}
                className="input-field"
              >
                <option value="">— 選擇觸發事件 —</option>
                {EVENTS.map(e => (
                  <option key={e.value} value={e.value}>{e.label}</option>
                ))}
              </select>
            </div>

            {/* AI Suggestions panel (appears after event is selected) */}
            {(selectedEvent || suggestLoading) && (
              <div className="rounded-xl border-2 border-indigo-200 bg-gradient-to-br from-indigo-50 to-purple-50 p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Zap size={14} className="text-indigo-500" />
                  <span className="text-sm font-semibold text-indigo-700">💡 AI 資深 PE 診斷建議</span>
                  {suggestLoading && (
                    <span className="text-xs text-indigo-400 animate-pulse ml-auto">AI 分析中...</span>
                  )}
                </div>

                {suggestLoading ? (
                  <div className="space-y-2.5">
                    {[1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-10 w-full" />)}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {suggestions.map((s, i) => (
                      <div key={i} className="flex items-start gap-2.5 bg-white rounded-lg p-3 border border-indigo-100 shadow-sm">
                        <span className="text-xs text-indigo-300 font-mono mt-0.5 flex-shrink-0 w-4">{i + 1}.</span>
                        <p className="text-xs text-slate-700 flex-1 leading-relaxed">{s}</p>
                        <button
                          onClick={() => applySuggestion(s)}
                          className="flex-shrink-0 text-xs bg-indigo-100 hover:bg-indigo-200 text-indigo-700 font-medium px-2.5 py-1 rounded-md transition-colors"
                        >
                          套用
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="border-t border-slate-200" />

          {/* ═══════════════════════════════════════════════════════════════
              Section B: Tools & Auto-Mapping
          ═══════════════════════════════════════════════════════════════ */}
          <div className="space-y-4">
            <SectionLabel letter="B" color="purple">工具綁定與 AI 自動映射</SectionLabel>

            {/* Tool checkboxes */}
            <div>
              <label className="text-xs font-medium text-slate-500 mb-2 block">選擇 MCP 診斷工具</label>
              <div className="space-y-2">
                {MCP_TOOLS.map(tool => (
                  <label
                    key={tool.name}
                    className="flex items-center gap-3 p-3 border border-slate-200 rounded-lg hover:bg-slate-50 cursor-pointer transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={selectedTools.includes(tool.name)}
                      onChange={() => handleToolToggle(tool.name)}
                      className="w-4 h-4 accent-purple-600 flex-shrink-0"
                    />
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-700 font-mono">{tool.name}</div>
                      <div className="text-xs text-slate-400 mt-0.5">{tool.label}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {/* Mapping visualization panel */}
            {(mapLoading || mappings.length > 0) && (
              <div className="rounded-xl border-2 border-purple-200 bg-gradient-to-br from-purple-50 to-indigo-50 p-4">
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-sm font-semibold text-purple-700">✨ AI 自動欄位映射</span>
                  {mapLoading && (
                    <span className="text-xs text-purple-400 animate-pulse ml-auto">AI 對應中...</span>
                  )}
                </div>

                {mapLoading ? (
                  <div className="space-y-2.5">
                    {[1, 2, 3].map(i => <Skeleton key={i} className="h-10 w-full" />)}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {mappings.map((m, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 bg-white rounded-lg p-2.5 border border-purple-100 shadow-sm text-xs flex-wrap"
                      >
                        <code className="bg-indigo-50 border border-indigo-200 px-2 py-1 rounded text-indigo-700 font-mono flex-shrink-0">
                          [Event] {m.event_field}
                        </code>
                        <ArrowRight size={12} className="text-purple-400 flex-shrink-0" />
                        <span className="text-purple-400 text-[11px] flex-shrink-0">✨ AI 自動對應</span>
                        <ArrowRight size={12} className="text-purple-400 flex-shrink-0" />
                        <code className="bg-purple-50 border border-purple-200 px-2 py-1 rounded text-purple-700 font-mono flex-shrink-0">
                          [Tool] {m.tool_param}
                        </code>
                        <div className="ml-auto flex items-center gap-1.5 flex-shrink-0">
                          <ConfidenceBadge confidence={m.confidence} />
                          <button className="text-[10px] text-slate-400 hover:text-indigo-600 border border-slate-200 hover:border-indigo-300 px-1.5 py-0.5 rounded transition-colors">
                            編輯
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="border-t border-slate-200" />

          {/* ═══════════════════════════════════════════════════════════════
              Section C: Diagnostic Logic & Validation
          ═══════════════════════════════════════════════════════════════ */}
          <div className="space-y-4">
            <SectionLabel letter="C" color="emerald">診斷大腦與語意防呆</SectionLabel>

            <div>
              <label className="text-xs font-medium text-slate-500 mb-1.5 block">診斷邏輯 Prompt</label>
              <textarea
                value={diagnosticLogic}
                onChange={e => { setDiagnosticLogic(e.target.value); setValidation(null) }}
                placeholder="在此輸入診斷邏輯，或點擊上方建議的 [套用] 按鈕自動填入..."
                rows={6}
                className="input-field font-mono text-xs resize-none"
              />
              <div className="flex justify-end mt-2">
                <button
                  onClick={handleValidate}
                  disabled={!diagnosticLogic.trim() || selectedTools.length === 0 || validating}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                             bg-indigo-600 hover:bg-indigo-700 text-white
                             disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {validating ? (
                    <span className="animate-pulse">驗證中...</span>
                  ) : (
                    <><Zap size={12} /> ✨ 驗證邏輯</>
                  )}
                </button>
              </div>
            </div>

            {/* Validation success indicator */}
            {validation?.is_valid && (
              <div className="flex items-center gap-2 rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-3">
                <CheckCircle size={16} className="text-emerald-500 flex-shrink-0" />
                <p className="text-sm text-emerald-700 font-medium">邏輯完美，所需數據工具皆已齊備。</p>
              </div>
            )}

            {/* Validation warning */}
            {validation && !validation.is_valid && (
              <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <AlertTriangle size={16} className="text-amber-500 flex-shrink-0" />
                  <span className="text-sm font-semibold text-amber-700">⚠️ 語意防呆警告</span>
                </div>
                <div className="space-y-1.5 mb-3">
                  {(validation.issues ?? []).map((issue, i) => (
                    <p key={i} className="text-xs text-amber-700 leading-relaxed">• {issue}</p>
                  ))}
                </div>
                {(validation.suggestions ?? []).length > 0 && (
                  <div className="pt-3 border-t border-amber-200">
                    <p className="text-xs font-semibold text-amber-600 mb-1.5">建議修正：</p>
                    {validation.suggestions.map((s, i) => (
                      <p key={i} className="text-xs text-amber-600 leading-relaxed">→ {s}</p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Bottom spacer */}
          <div className="h-2" />
        </div>

        {/* ── Footer ──────────────────────────────────────────────────────── */}
        <div className="px-6 py-4 border-t border-slate-200 flex items-center justify-between flex-shrink-0 bg-slate-50">
          <button onClick={onClose} className="btn-secondary text-sm">
            取消
          </button>
          <button
            disabled={!selectedEvent || !diagnosticLogic.trim()}
            className="btn-primary text-sm disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Plus size={15} />
            建立技能
          </button>
        </div>
      </div>

      {/* ── Toast notification ─────────────────────────────────────────────── */}
      {toast && (
        <div
          className={`fixed bottom-8 right-8 z-[60] flex items-center gap-2 px-4 py-3 rounded-xl shadow-xl text-sm font-medium transition-all animate-fade-in ${
            toast.type === 'success' ? 'bg-emerald-600 text-white' : 'bg-rose-600 text-white'
          }`}
        >
          {toast.type === 'success' ? <CheckCircle size={16} /> : <AlertTriangle size={16} />}
          {toast.message}
        </div>
      )}
    </>
  )
}
