import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Send, Square, RefreshCw, FileText, Zap, Cpu, Database, HelpCircle, AlertTriangle, ChevronRight } from 'lucide-react'
import { useSSE } from '../hooks/useSSE'
import { URGENCY_CONFIG } from '../data/mockData'
import JsonViewer from '../components/ui/JsonViewer'

// ------- Left Panel: Report Tabs -------

function EventObjectCard({ eventObj }) {
  if (!eventObj) return (
    <div className="flex flex-col items-center justify-center h-40 text-slate-300">
      <Zap size={32} className="mb-2 opacity-40" />
      <p className="text-sm">等待事件分類…</p>
    </div>
  )

  const cfg = URGENCY_CONFIG[eventObj.urgency] ?? URGENCY_CONFIG.low

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between p-4 bg-slate-50 rounded-xl border border-slate-200">
        <div>
          <div className="text-xs text-slate-400 mb-1">事件類型</div>
          <div className="text-lg font-bold text-slate-800">{eventObj.event_type}</div>
        </div>
        <span className={`badge ${cfg.className} flex items-center gap-1.5 text-sm px-3 py-1.5`}>
          <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
          {cfg.label}
        </span>
      </div>

      {eventObj.recommended_skills?.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">建議工具鏈</div>
          <div className="flex flex-wrap gap-2">
            {eventObj.recommended_skills.map((s, i) => (
              <div key={s} className="flex items-center gap-1">
                <span className="badge badge-indigo text-xs font-mono">
                  {i + 1}. {s}
                </span>
                {i < eventObj.recommended_skills.length - 1 && (
                  <ChevronRight size={12} className="text-slate-300" />
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {eventObj.analysis_hints && (
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">分析提示</div>
          <p className="text-sm text-slate-600 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
            {eventObj.analysis_hints}
          </p>
        </div>
      )}
    </div>
  )
}

function ToolCallCard({ toolCall }) {
  const iconMap = {
    mcp_event_triage:              <Zap size={14} className="text-rose-500" />,
    mcp_check_recipe_offset:       <Database size={14} className="text-indigo-500" />,
    mcp_check_equipment_constants: <Cpu size={14} className="text-purple-500" />,
    mcp_check_apc_params:          <Zap size={14} className="text-amber-500" />,
    ask_user_recent_changes:       <HelpCircle size={14} className="text-teal-500" />,
  }
  const icon = iconMap[toolCall.name] ?? <Zap size={14} className="text-slate-400" />

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 bg-slate-50 border-b border-slate-200">
        <div className="w-6 h-6 rounded-md bg-white border border-slate-200 flex items-center justify-center">
          {icon}
        </div>
        <code className="text-sm font-semibold text-slate-700">{toolCall.name}</code>
        {toolCall.result
          ? <span className="ml-auto badge badge-emerald text-xs">✓ 完成</span>
          : <span className="ml-auto badge badge-amber text-xs animate-pulse">執行中…</span>
        }
      </div>
      <div className="p-4 space-y-3">
        <JsonViewer data={toolCall.input} label="Input" />
        {toolCall.result && (
          <JsonViewer data={toolCall.result} label="Result" />
        )}
      </div>
    </div>
  )
}

function FinalReport({ report, isStreaming }) {
  if (!report && !isStreaming) return (
    <div className="flex flex-col items-center justify-center h-40 text-slate-300">
      <FileText size={32} className="mb-2 opacity-40" />
      <p className="text-sm">診斷完成後將顯示報告</p>
    </div>
  )

  return (
    <div className={`prose-report ${isStreaming && !report ? 'typing-cursor' : ''}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {report || ''}
      </ReactMarkdown>
      {isStreaming && report && (
        <span className="inline-block w-0.5 h-4 bg-indigo-500 animate-pulse ml-0.5 align-middle" />
      )}
    </div>
  )
}

const LEFT_TABS = [
  { id: 'report',  label: '診斷報告',   icon: FileText },
  { id: 'event',   label: '事件分類',   icon: Zap },
  { id: 'tools',   label: '工具呼叫',   icon: Cpu },
]

// ------- Right Panel: Chat -------

function ChatBubble({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? 'bg-indigo-600 text-white rounded-br-sm'
            : 'bg-white border border-slate-200 text-slate-700 rounded-bl-sm shadow-sm'
        }`}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
          p: ({ children }) => <span>{children}</span>,
          code: ({ children }) => (
            <code className={`font-mono text-xs px-1 py-0.5 rounded ${isUser ? 'bg-indigo-500' : 'bg-slate-100'}`}>
              {children}
            </code>
          ),
        }}>
          {msg.content}
        </ReactMarkdown>
      </div>
    </div>
  )
}

// Quick scenario for the boss demo
const QUICK_TEST_MSG = 'TETCH01 PM2 發生 SPC OOC，CD 量測值連續 3 點超出 3-sigma 管制界限，請進行蝕刻製程排障診斷。'

const SUGGESTIONS = [
  'TETCH01 PM2 發生 SPC OOC，CD 超出 3-sigma，請診斷',
  '機台 EAP01 配方 ETCH_POLY_V2 參數偏移，懷疑人為修改',
  'Lot 03B 線寬異常，APC 補償可能已飽和',
  '機台保養後 CD 漂移，需確認 PM 品質與硬體常數',
]

// ------- Main DiagnosisPage -------

export default function DiagnosisPage() {
  const [activeTab, setActiveTab] = useState('report')
  const [input, setInput] = useState('')
  const chatEndRef = useRef(null)
  const textareaRef = useRef(null)

  const {
    isStreaming,
    eventObject,
    toolCalls,
    report,
    chatMessages,
    error,
    sendMessage,
    stop,
    setChatMessages,
  } = useSSE()

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  // Auto-switch to Tools tab when first tool_call arrives (shows live execution)
  useEffect(() => {
    if (toolCalls.length > 0) setActiveTab('tools')
  }, [toolCalls.length])

  // Auto-switch to Event tab when mcp_event_triage result lands
  useEffect(() => {
    if (eventObject) setActiveTab('event')
  }, [eventObject])

  // Auto-switch to Report tab when final report arrives
  useEffect(() => {
    if (report) setActiveTab('report')
  }, [!!report])

  const handleSend = () => {
    const msg = input.trim()
    if (!msg || isStreaming) return
    setInput('')
    sendMessage(msg)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleReset = () => {
    if (isStreaming) stop()
    setChatMessages([])
    setInput('')
    setActiveTab('report')
  }

  const handleQuickTest = () => {
    if (isStreaming) return
    sendMessage(QUICK_TEST_MSG)
  }

  const toolBadge = toolCalls.length > 0
    ? <span className="ml-1.5 inline-flex items-center justify-center w-4 h-4 text-xs bg-indigo-100 text-indigo-600 rounded-full font-bold">{toolCalls.length}</span>
    : null

  return (
    <div className="flex h-full gap-0">
      {/* ============ LEFT: Report Panel (65%) ============ */}
      <div className="flex flex-col" style={{ width: '65%' }}>
        {/* Tab Bar */}
        <div className="flex items-center gap-1 px-6 pt-5 pb-0 bg-white border-b border-slate-200">
          {LEFT_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === id
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}
            >
              <Icon size={15} />
              {label}
              {id === 'tools' && toolBadge}
            </button>
          ))}

          <div className="ml-auto mb-1">
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
            >
              <RefreshCw size={13} />
              重置
            </button>
          </div>
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {error && (
            <div className="mb-4 px-4 py-3 bg-rose-50 border border-rose-200 rounded-xl text-sm text-rose-700 flex items-start gap-2">
              <AlertTriangle size={15} className="flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {activeTab === 'report' && (
            <FinalReport report={report} isStreaming={isStreaming} />
          )}
          {activeTab === 'event' && (
            <EventObjectCard eventObj={eventObject} />
          )}
          {activeTab === 'tools' && (
            <div className="space-y-4">
              {toolCalls.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-40 text-slate-300">
                  <Cpu size={32} className="mb-2 opacity-40" />
                  <p className="text-sm">尚無工具呼叫記錄</p>
                </div>
              ) : (
                toolCalls.map((tc, i) => <ToolCallCard key={`${tc.name}-${i}`} toolCall={tc} />)
              )}
            </div>
          )}
        </div>
      </div>

      {/* Divider */}
      <div className="w-px bg-slate-200 flex-shrink-0" />

      {/* ============ RIGHT: Chat Panel (35%) ============ */}
      <div className="flex flex-col flex-1 min-w-0 bg-slate-50">
        {/* Chat Header */}
        <div className="px-5 py-3.5 bg-white border-b border-slate-200 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isStreaming ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300'}`} />
            <span className="text-sm font-medium text-slate-700">
              {isStreaming ? 'Agent 執行中…' : 'AI 診斷對話'}
            </span>
          </div>
          {isStreaming && (
            <button
              onClick={stop}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-rose-500 hover:bg-rose-50 rounded-lg transition-colors"
            >
              <Square size={11} fill="currentColor" />
              停止
            </button>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {chatMessages.length === 0 && (
            <div className="pt-4">
              <p className="text-xs text-slate-400 text-center mb-4">輸入症狀開始 AI 診斷</p>
              <div className="space-y-2">
                {SUGGESTIONS.map(s => (
                  <button
                    key={s}
                    onClick={() => sendMessage(s)}
                    disabled={isStreaming}
                    className="w-full text-left text-xs text-slate-600 bg-white border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50 rounded-xl px-4 py-3 transition-colors disabled:opacity-40"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {chatMessages.map((msg, i) => (
            <ChatBubble key={i} msg={msg} />
          ))}
          <div ref={chatEndRef} />
        </div>

        {/* Quick Test Button */}
        <div className="px-4 pt-3 pb-0 bg-white border-t border-slate-100">
          <button
            onClick={handleQuickTest}
            disabled={isStreaming}
            className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-xs font-semibold
                       bg-amber-50 border border-amber-300 text-amber-800 hover:bg-amber-100
                       disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ⚡ 模擬觸發：TETCH01 PM2 發生 SPC OOC
          </button>
        </div>

        {/* Input */}
        <div className="p-4 bg-white flex-shrink-0">
          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              rows={2}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="描述蝕刻製程症狀… (Enter 送出，Shift+Enter 換行)"
              disabled={isStreaming}
              className="input-field resize-none flex-1 text-sm py-2.5 leading-relaxed disabled:opacity-50"
            />
            <button
              onClick={isStreaming ? stop : handleSend}
              disabled={!isStreaming && !input.trim()}
              className={`flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center transition-colors disabled:opacity-40 ${
                isStreaming
                  ? 'bg-rose-500 hover:bg-rose-600 text-white'
                  : 'bg-indigo-600 hover:bg-indigo-700 text-white disabled:bg-slate-200 disabled:text-slate-400'
              }`}
            >
              {isStreaming
                ? <Square size={14} fill="currentColor" />
                : <Send size={15} />
              }
            </button>
          </div>
          <p className="text-xs text-slate-400 mt-1.5">Enter 送出 · Shift+Enter 換行</p>
        </div>
      </div>
    </div>
  )
}
