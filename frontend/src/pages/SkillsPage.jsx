import { useState } from 'react'
import { GitBranch, Wrench, ChevronRight, Activity, Clock, Zap, AlertCircle, Plus } from 'lucide-react'
import Drawer from '../components/ui/Drawer'
import SkillBuilderDrawer from '../components/SkillBuilderDrawer'
import JsonViewer from '../components/ui/JsonViewer'
import { MOCK_SKILLS, URGENCY_CONFIG } from '../data/mockData'

const TABS = [
  { id: 'triage',  label: '事件分診庫',    sub: 'Event Triage',       icon: GitBranch },
  { id: 'action',  label: '診斷工具庫',    sub: 'Diagnostic Actions',  icon: Wrench },
]

function UrgencyBadge({ urgency }) {
  const cfg = URGENCY_CONFIG[urgency] ?? URGENCY_CONFIG.low
  return (
    <span className={`badge ${cfg.className} inline-flex items-center gap-1 text-xs`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

function SkillRow({ skill, onClick }) {
  return (
    <div
      className="flex items-center justify-between p-4 hover:bg-slate-50 cursor-pointer border-b border-slate-100 last:border-0 group transition-colors"
      onClick={() => onClick(skill)}
    >
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0">
          <Zap size={16} className="text-indigo-500" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-slate-800 font-mono">{skill.name}</span>
            <span className={`badge text-xs ${skill.status === 'active' ? 'badge-emerald' : 'badge-slate'}`}>
              {skill.status === 'active' ? '✓ Active' : 'Inactive'}
            </span>
          </div>
          <p className="text-xs text-slate-500 truncate mt-0.5 max-w-[480px]">{skill.description}</p>
        </div>
      </div>

      <div className="flex items-center gap-5 flex-shrink-0 ml-4">
        <div className="text-right hidden sm:block">
          <div className="flex items-center gap-1 text-xs text-slate-500">
            <Activity size={11} />
            <span className="font-medium text-slate-700">{skill.invocations}</span>
            <span>次</span>
          </div>
          <div className="flex items-center gap-1 text-xs text-slate-500 mt-0.5">
            <Clock size={11} />
            <span className="font-medium text-slate-700">{skill.avgMs}</span>
            <span>ms</span>
          </div>
        </div>
        <ChevronRight size={16} className="text-slate-300 group-hover:text-indigo-400 transition-colors" />
      </div>
    </div>
  )
}

function TriageRuleCard({ rule }) {
  return (
    <div className="border border-slate-200 rounded-xl p-4 bg-slate-50">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-slate-700">{rule.event_type}</span>
        <UrgencyBadge urgency={rule.urgency} />
      </div>

      <div className="mb-3">
        <div className="text-xs text-slate-400 mb-1.5">觸發關鍵字</div>
        <div className="flex flex-wrap gap-1.5">
          {rule.keywords.map(kw => (
            <code key={kw} className="text-xs bg-white border border-slate-200 rounded px-1.5 py-0.5 text-indigo-600">
              {kw}
            </code>
          ))}
        </div>
      </div>

      <div>
        <div className="text-xs text-slate-400 mb-1.5">後續工具鏈</div>
        <div className="flex flex-wrap gap-1.5">
          {rule.skills.map((s, i) => (
            <div key={s} className="flex items-center gap-1">
              <span className="text-xs bg-indigo-50 border border-indigo-200 rounded px-1.5 py-0.5 text-indigo-700 font-mono">
                {i + 1}. {s}
              </span>
              {i < rule.skills.length - 1 && (
                <ChevronRight size={10} className="text-slate-300" />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function SkillsPage() {
  const [activeTab, setActiveTab] = useState('triage')
  const [selectedSkill, setSelectedSkill] = useState(null)
  const [builderOpen, setBuilderOpen] = useState(false)

  const filtered = MOCK_SKILLS.filter(s => s.type === activeTab)

  return (
    <div className="p-6 h-full">
      {/* Tab Bar + New Skill button */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex gap-1 p-1 bg-slate-100 rounded-xl w-fit">
          {TABS.map(({ id, label, sub, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
                activeTab === id
                  ? 'bg-white text-indigo-600 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              <Icon size={16} />
              <span>{label}</span>
              <span className="text-xs text-slate-400 hidden sm:inline">/ {sub}</span>
            </button>
          ))}
        </div>

        <button
          onClick={() => setBuilderOpen(true)}
          className="btn-primary"
        >
          <Plus size={16} />
          新增技能
        </button>
      </div>

      {/* Skill List */}
      <div className="card overflow-hidden">
        {/* List header */}
        <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            {activeTab === 'triage' ? '分診技能' : '診斷技能'} — {filtered.length} 個
          </span>
          <span className="text-xs text-slate-400">點擊任意行查看 Schema 詳情</span>
        </div>

        {filtered.length === 0 ? (
          <div className="flex flex-col items-center py-16 text-slate-400">
            <AlertCircle size={32} className="mb-3 opacity-40" />
            <p className="text-sm">尚無技能</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {filtered.map(skill => (
              <SkillRow key={skill.id} skill={skill} onClick={setSelectedSkill} />
            ))}
          </div>
        )}
      </div>

      {/* Skill Builder Drawer (wide, AI-powered) */}
      <SkillBuilderDrawer open={builderOpen} onClose={() => setBuilderOpen(false)} />

      {/* Skill detail Drawer */}
      <Drawer
        open={!!selectedSkill}
        onClose={() => setSelectedSkill(null)}
        title={selectedSkill?.displayName ?? ''}
      >
        {selectedSkill && (
          <div className="space-y-6">
            {/* Meta */}
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0">
                <Zap size={18} className="text-indigo-500" />
              </div>
              <div>
                <code className="text-sm font-semibold text-slate-800">{selectedSkill.name}</code>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`badge text-xs ${selectedSkill.status === 'active' ? 'badge-emerald' : 'badge-slate'}`}>
                    {selectedSkill.status}
                  </span>
                  <span className="badge badge-indigo text-xs">{selectedSkill.type}</span>
                </div>
              </div>
            </div>

            {/* Description */}
            <div>
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">描述</div>
              <p className="text-sm text-slate-600 leading-relaxed">{selectedSkill.description}</p>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-slate-50 rounded-xl p-3 text-center">
                <div className="text-xl font-bold text-indigo-600">{selectedSkill.invocations}</div>
                <div className="text-xs text-slate-500 mt-0.5">呼叫次數</div>
              </div>
              <div className="bg-slate-50 rounded-xl p-3 text-center">
                <div className="text-xl font-bold text-indigo-600">{selectedSkill.avgMs}ms</div>
                <div className="text-xs text-slate-500 mt-0.5">平均延遲</div>
              </div>
            </div>

            {/* Triage Rules */}
            {selectedSkill.triageRules && (
              <div>
                <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                  分診規則 ({selectedSkill.triageRules.length} 條)
                </div>
                <div className="space-y-3">
                  {selectedSkill.triageRules.map(rule => (
                    <TriageRuleCard key={rule.event_type} rule={rule} />
                  ))}
                </div>
              </div>
            )}

            {/* JSON Schema */}
            {selectedSkill.schema && (
              <JsonViewer data={selectedSkill.schema} label="Input Schema (JSON Schema)" />
            )}
          </div>
        )}
      </Drawer>
    </div>
  )
}
