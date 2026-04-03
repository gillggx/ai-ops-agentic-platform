import { useNavigate, useLocation } from 'react-router-dom'
import { LogOut, User } from 'lucide-react'
import { useAuth } from '../hooks/useAuth'

const PAGE_TITLES = {
  '/diagnosis': { title: '診斷工作站', sub: 'Diagnosis Console' },
  '/skills':    { title: '技能與事件庫', sub: 'Skill & Event Registry' },
  '/settings':  { title: '系統與環境變數', sub: 'System Variables' },
}

export default function Header() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const page = PAGE_TITLES[pathname] ?? { title: '控制台', sub: 'Admin Console' }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 flex-shrink-0">
      <div>
        <h1 className="text-lg font-semibold text-slate-800">{page.title}</h1>
        <p className="text-xs text-slate-400 leading-none">{page.sub}</p>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-50 rounded-lg border border-slate-200">
          <div className="w-6 h-6 rounded-full bg-indigo-100 flex items-center justify-center">
            <User size={13} className="text-indigo-600" />
          </div>
          <span className="text-sm text-slate-700 font-medium">admin</span>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-slate-500 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
        >
          <LogOut size={15} />
          <span>登出</span>
        </button>
      </div>
    </header>
  )
}
