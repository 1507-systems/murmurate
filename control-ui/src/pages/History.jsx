/**
 * History — View recent browsing session history with filtering.
 *
 * Shows a sortable table of recent sessions with status, persona, plugin,
 * transport type, and timing information.
 *
 * New sessions arrive instantly via the SSE stream (session_started /
 * session_completed / session_failed events). The polling fallback refreshes
 * every 30 s to catch anything missed while SSE was disconnected.
 */

import { useState } from 'react'
import { usePolling } from '../hooks/useApi'
import { useSessionEvents } from '../hooks/useSSE'
import { getHistory } from '../api'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import Button from '../components/Button'

export default function History() {
  const [limit, setLimit] = useState(50)
  // Polling fallback — relaxed to 30 s because SSE covers real-time updates.
  // After each SSE completion event the user can hit refresh manually; the
  // poll will pick up the persisted record within 30 s automatically.
  const { data: sessions, loading } = usePolling(() => getHistory(limit), 30000, [limit])

  // Live session events from SSE — these appear instantly before they are
  // persisted and returned by the polling fetch.
  const { events: liveEvents, connected: sseAlive, clearEvents } = useSessionEvents(50)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-white">Session History</h1>
          {/* SSE live indicator */}
          <span
            className="flex items-center gap-1.5 text-xs"
            title={sseAlive ? 'Live event stream connected — new sessions appear instantly' : 'Polling every 30 s'}
          >
            <span className={`w-2 h-2 rounded-full ${sseAlive ? 'bg-[#22c55e] animate-pulse' : 'bg-[#8888a0]'}`} />
            <span className={sseAlive ? 'text-[#22c55e]' : 'text-[#8888a0]'}>
              {sseAlive ? 'Live' : 'Polling'}
            </span>
          </span>
        </div>
        <div className="flex gap-2">
          {[50, 100, 500].map(n => (
            <Button
              key={n}
              variant={limit === n ? 'primary' : 'secondary'}
              size="sm"
              onClick={() => setLimit(n)}
            >
              Last {n}
            </Button>
          ))}
        </div>
      </div>

      {/* Live session events from SSE (appear before the DB poll catches up) */}
      {liveEvents.length > 0 && (
        <Card title="Live Events" className="mb-4">
          <div className="space-y-1">
            {liveEvents.map((ev, i) => (
              <div key={i} className="flex items-center gap-3 text-sm py-1">
                <StatusBadge status={
                  ev.type === 'session_completed' ? 'completed'
                  : ev.type === 'session_failed' ? 'failed'
                  : 'running'
                } />
                <span className="text-[#e0e0e8]">{ev.persona_name}</span>
                <span className="text-[#8888a0]">→</span>
                <span className="text-[#e0e0e8]">{ev.plugin_name}</span>
                {ev.type === 'session_failed' && ev.error && (
                  <span className="text-[#ef4444] text-xs truncate max-w-xs">{ev.error}</span>
                )}
                <span className="ml-auto text-xs text-[#8888a0]">
                  {new Date(ev.ts * 1000).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
          <button
            onClick={clearEvents}
            className="mt-2 text-xs text-[#8888a0] hover:text-[#e0e0e8]"
          >
            Clear live events
          </button>
        </Card>
      )}

      <Card>
        {loading && !sessions && (
          <p className="text-[#8888a0] text-sm">Loading history...</p>
        )}
        {sessions && sessions.length === 0 && (
          <p className="text-[#8888a0] text-sm">No sessions recorded yet.</p>
        )}
        {sessions && sessions.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[#8888a0] text-xs uppercase tracking-wider">
                  <th className="pb-3">Status</th>
                  <th className="pb-3">Persona</th>
                  <th className="pb-3">Plugin</th>
                  <th className="pb-3">Transport</th>
                  <th className="pb-3 text-right">Queries</th>
                  <th className="pb-3 text-right">Results</th>
                  <th className="pb-3 text-right">Duration</th>
                  <th className="pb-3">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2a2a3a]">
                {sessions.map(s => (
                  <tr key={s.id} className="hover:bg-[#22222f]">
                    <td className="py-2">
                      <StatusBadge status={s.status || 'unknown'} />
                    </td>
                    <td className="py-2">{s.persona_name}</td>
                    <td className="py-2">{s.plugin_name}</td>
                    <td className="py-2 text-[#8888a0]">{s.transport_type}</td>
                    <td className="py-2 text-right">{s.queries_executed ?? '-'}</td>
                    <td className="py-2 text-right">{s.results_browsed ?? '-'}</td>
                    <td className="py-2 text-right">
                      {s.duration_s != null ? `${s.duration_s.toFixed(1)}s` : '-'}
                    </td>
                    <td className="py-2 text-[#8888a0] text-xs">
                      {s.started_at?.slice(0, 19).replace('T', ' ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
