import { useState } from 'react'
import { Save, Eye, EyeOff, CheckCircle2, RotateCcw } from 'lucide-react'
import { MOCK_SETTINGS, AVAILABLE_MODELS } from '../data/mockData'

export default function SettingsPage() {
  const [settings, setSettings] = useState({ ...MOCK_SETTINGS })
  const [showKey, setShowKey] = useState(false)
  const [saved, setSaved] = useState(false)

  const update = (key, value) => setSettings(prev => ({ ...prev, [key]: value }))

  const handleSave = () => {
    // Mock save — in real integration would PUT /api/v1/settings
    setSaved(true)
    setTimeout(() => setSaved(false), 2500)
  }

  const handleReset = () => setSettings({ ...MOCK_SETTINGS })

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      {/* Section: System Prompt */}
      <div className="card p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-800">全局提示詞</h2>
            <p className="text-sm text-slate-500 mt-0.5">定義 AI Agent 的核心行為規則與約束</p>
          </div>
          <span className="badge badge-indigo text-xs">Global Prompt</span>
        </div>
        <textarea
          rows={14}
          value={settings.systemPrompt}
          onChange={e => update('systemPrompt', e.target.value)}
          className="input-field resize-none font-mono text-xs leading-5"
          spellCheck={false}
        />
        <div className="mt-2 flex justify-end">
          <span className="text-xs text-slate-400">{settings.systemPrompt.length} 字元</span>
        </div>
      </div>

      {/* Section: Model Routing */}
      <div className="card p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-800">模型設定</h2>
            <p className="text-sm text-slate-500 mt-0.5">選擇 LLM 模型與最大回合數</p>
          </div>
          <span className="badge badge-purple text-xs">Model Routing</span>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">LLM 模型</label>
            <select
              value={settings.model}
              onChange={e => update('model', e.target.value)}
              className="input-field"
            >
              {AVAILABLE_MODELS.map(m => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">最大回合數 (Max Turns)</label>
            <input
              type="number"
              min={1}
              max={50}
              value={settings.maxTurns}
              onChange={e => update('maxTurns', Number(e.target.value))}
              className="input-field"
            />
          </div>
        </div>
      </div>

      {/* Section: Secrets */}
      <div className="card p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-800">金鑰管理</h2>
            <p className="text-sm text-slate-500 mt-0.5">API Key 與安全憑證管理</p>
          </div>
          <span className="badge badge-rose text-xs">Secrets</span>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1.5">Anthropic API Key</label>
          <div className="relative">
            <input
              type={showKey ? 'text' : 'password'}
              value={settings.apiKeyMasked}
              onChange={e => update('apiKeyMasked', e.target.value)}
              className="input-field pr-10 font-mono text-sm"
              placeholder="sk-ant-api03-..."
            />
            <button
              type="button"
              onClick={() => setShowKey(v => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <p className="text-xs text-slate-400 mt-1.5">⚠️ API Key 僅供本地 mock 展示，不會傳送至後端。</p>
        </div>
      </div>

      {/* Section: API Access */}
      <div className="card p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-800">存取設定</h2>
            <p className="text-sm text-slate-500 mt-0.5">CORS 與日誌等級設定</p>
          </div>
          <span className="badge badge-slate text-xs">Access Control</span>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">允許來源 (CORS)</label>
            <input
              type="text"
              value={settings.allowedOrigins}
              onChange={e => update('allowedOrigins', e.target.value)}
              className="input-field"
              placeholder="* 或指定網域"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">日誌等級</label>
            <select
              value={settings.logLevel}
              onChange={e => update('logLevel', e.target.value)}
              className="input-field"
            >
              {['DEBUG', 'INFO', 'WARNING', 'ERROR'].map(l => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex items-center gap-3 justify-end pb-6">
        <button onClick={handleReset} className="btn-secondary flex items-center gap-1.5">
          <RotateCcw size={15} />
          還原預設
        </button>
        <button onClick={handleSave} className="btn-primary flex items-center gap-1.5">
          {saved ? (
            <>
              <CheckCircle2 size={15} />
              已儲存
            </>
          ) : (
            <>
              <Save size={15} />
              儲存設定
            </>
          )}
        </button>
      </div>
    </div>
  )
}
