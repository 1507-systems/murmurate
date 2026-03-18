/**
 * History — View recent browsing session history with filtering.
 *
 * Shows a sortable table of recent sessions with status, persona, plugin,
 * transport type, and timing information. Auto-refreshes every 10 seconds.
 */

import { useState } from 'react'
import { usePolling } from '../hooks/useApi'
import { getHistory } from '../api'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import Button from '../components/Button'

export default function History() {
  const [limit, setLimit] = useState(50)
  const { data: sessions, loading } = usePolling(() => getHistory(limit), 10000, [limit])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-white">Session History</h1>
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
