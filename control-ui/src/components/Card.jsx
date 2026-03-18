/**
 * Card — Reusable container component with consistent dark-theme styling.
 */

export default function Card({ title, children, className = '', actions }) {
  return (
    <div className={`bg-[#1a1a24] border border-[#2a2a3a] rounded-lg ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#2a2a3a]">
          {title && <h2 className="text-sm font-medium text-white">{title}</h2>}
          {actions && <div className="flex gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-5">{children}</div>
    </div>
  )
}

/**
 * StatCard — Small card for displaying a single metric.
 */
export function StatCard({ label, value, subtext, color = 'text-white' }) {
  return (
    <div className="bg-[#1a1a24] border border-[#2a2a3a] rounded-lg p-4">
      <p className="text-xs text-[#8888a0] uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-semibold mt-1 ${color}`}>{value}</p>
      {subtext && <p className="text-xs text-[#8888a0] mt-0.5">{subtext}</p>}
    </div>
  )
}
