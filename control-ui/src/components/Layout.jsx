/**
 * Layout — App shell with sidebar navigation and main content area.
 *
 * The sidebar shows the Murmurate logo and navigation links for each section.
 * The main area renders the active page. Daemon status is shown in the sidebar
 * footer so it's always visible.
 */

import { usePolling } from '../hooks/useApi'
import { getStatus } from '../api'

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard', icon: '◉' },
  { key: 'personas', label: 'Personas', icon: '◎' },
  { key: 'history', label: 'History', icon: '◷' },
  { key: 'plugins', label: 'Plugins', icon: '◫' },
  { key: 'config', label: 'Config', icon: '◈' },
]

export default function Layout({ activePage, onNavigate, children }) {
  const { data: status } = usePolling(getStatus, 5000)

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 border-r border-[#2a2a3a] bg-[#12121a] flex flex-col">
        {/* Logo / Title */}
        <div className="p-5 border-b border-[#2a2a3a]">
          <h1 className="text-lg font-semibold text-white tracking-tight">
            Murmurate
          </h1>
          <p className="text-xs text-[#8888a0] mt-0.5">Control UI</p>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-3">
          {NAV_ITEMS.map(item => (
            <button
              key={item.key}
              onClick={() => onNavigate(item.key)}
              className={`w-full text-left px-5 py-2.5 text-sm flex items-center gap-3 transition-colors ${
                activePage === item.key
                  ? 'bg-[#6366f1]/10 text-[#818cf8] border-r-2 border-[#6366f1]'
                  : 'text-[#8888a0] hover:text-[#e0e0e8] hover:bg-[#1a1a24]'
              }`}
            >
              <span className="text-base">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        {/* Status footer */}
        <div className="p-4 border-t border-[#2a2a3a]">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${
              status?.running ? 'bg-[#22c55e]' : 'bg-[#ef4444]'
            }`} />
            <span className="text-xs text-[#8888a0]">
              {status?.running ? 'Daemon running' : 'Daemon stopped'}
            </span>
          </div>
          {status?.sessions_today != null && (
            <p className="text-xs text-[#8888a0] mt-1">
              {status.sessions_today} sessions today
            </p>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-5xl mx-auto p-6">
          {children}
        </div>
      </main>
    </div>
  )
}
