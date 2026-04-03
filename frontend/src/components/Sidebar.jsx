import { NavLink } from 'react-router-dom'
import { Monitor, Wrench, Settings, Zap } from 'lucide-react'

const NAV_ITEMS = [
  { to: '/diagnosis', icon: Monitor,  label: '診斷工作站',      sub: 'Diagnosis Console' },
  { to: '/skills',    icon: Wrench,   label: '技能與事件庫',    sub: 'Skill & Event Registry' },
  { to: '/settings',  icon: Settings, label: '系統與環境變數',  sub: 'System Variables' },
]

export default function Sidebar() {
  return (
    <aside className="w-64 flex-shrink-0 bg-slate-900 text-white flex flex-col h-full">
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-slate-700">
        <div className="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center">
          <Zap size={16} className="text-white" />
        </div>
        <div>
          <div className="text-sm font-semibold leading-tight">AI 診斷引擎</div>
          <div className="text-xs text-slate-400 leading-tight">Admin Console v5</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map(({ to, icon: Icon, label, sub }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? 'active' : ''}`
            }
          >
            <Icon size={18} className="flex-shrink-0" />
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">{label}</div>
              <div className="text-xs text-slate-400 truncate leading-none mt-0.5">{sub}</div>
            </div>
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-slate-700">
        <div className="text-xs text-slate-500">Phase 5 · Agentic Platform</div>
      </div>
    </aside>
  )
}
