/**
 * StatusBadge — Small colored badge for displaying session/plugin status.
 */

const STATUS_STYLES = {
  completed: 'bg-[#22c55e]/10 text-[#22c55e]',
  running: 'bg-[#6366f1]/10 text-[#818cf8]',
  failed: 'bg-[#ef4444]/10 text-[#ef4444]',
  cancelled: 'bg-[#f59e0b]/10 text-[#f59e0b]',
  enabled: 'bg-[#22c55e]/10 text-[#22c55e]',
  disabled: 'bg-[#ef4444]/10 text-[#ef4444]',
}

export default function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || 'bg-[#2a2a3a] text-[#8888a0]'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${style}`}>
      {status}
    </span>
  )
}
