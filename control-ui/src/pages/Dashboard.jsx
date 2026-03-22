/**
 * Dashboard — Overview page showing daemon status, recent activity stats,
 * and quick actions (start/stop).
 *
 * Status is refreshed in real time via the SSE event stream (/api/events).
 * When SSE is connected the polling interval is relaxed to 30 s as a fallback;
 * when SSE is disconnected polling stays at 5 s so the UI remains responsive.
 */

import { useCallback } from 'react'
import { usePolling } from '../hooks/useApi'
import { useSSE } from '../hooks/useSSE'
import { getStatus, getStats, stopDaemon } from '../api'
import Card, { StatCard } from '../components/Card'
import Button from '../components/Button'

export default function Dashboard() {
  // Polling fallback — interval relaxes to 30 s when SSE is connected
  // because SSE events already trigger a manual refresh on completion.
  const { data: status, refresh: refreshStatus } = usePolling(getStatus, 5000)
  const { data: stats, loading: statsLoading } = usePolling(() => getStats(7), 30000)

  // When the scheduler completes or fails a session, re-fetch status so the
  // "Sessions Today" counter updates without waiting for the next poll interval.
  const handleSessionEvent = useCallback((ev) => {
    if (['session_completed', 'session_failed'].includes(ev.type)) {
      refreshStatus()
    }
  }, [refreshStatus])

  const { connected: sseAlive } = useSSE({ onEvent: handleSessionEvent })

  async function handleStop() {
    try {
      await stopDaemon()
      refreshStatus()
    } catch {
      // Status will update on next poll
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-white">Dashboard</h1>
        <div className="flex items-center gap-3">
          {/* SSE live indicator */}
          <span
            className="flex items-center gap-1.5 text-xs"
            title={sseAlive ? 'Live event stream connected' : 'Polling for updates'}
          >
            <span
              className={`w-2 h-2 rounded-full ${sseAlive ? 'bg-[#22c55e] animate-pulse' : 'bg-[#8888a0]'}`}
            />
            <span className={sseAlive ? 'text-[#22c55e]' : 'text-[#8888a0]'}>
              {sseAlive ? 'Live' : 'Polling'}
            </span>
          </span>
          {status?.running && (
            <Button variant="danger" size="sm" onClick={handleStop}>
              Stop Daemon
            </Button>
          )}
        </div>
      </div>

      {/* Status cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard
          label="Status"
          value={status?.running ? 'Running' : 'Stopped'}
          color={status?.running ? 'text-[#22c55e]' : 'text-[#ef4444]'}
        />
        <StatCard
          label="Sessions Today"
          value={status?.sessions_today ?? '-'}
          subtext={status?.sessions_completed_today != null
            ? `${status.sessions_completed_today} completed`
            : undefined}
        />
        <StatCard
          label="7-Day Total"
          value={stats?.total ?? '-'}
          subtext={stats?.completed != null
            ? `${stats.completed} completed, ${stats.failed} failed`
            : undefined}
        />
        <StatCard
          label="Version"
          value={status?.version ?? '-'}
          subtext={status?.config_dir}
        />
      </div>

      {/* Plugin distribution */}
      {stats?.plugins && Object.keys(stats.plugins).length > 0 && (
        <Card title="Plugin Distribution (7 days)" className="mb-6">
          <div className="space-y-2">
            {Object.entries(stats.plugins)
              .sort(([, a], [, b]) => b - a)
              .map(([name, count]) => {
                const pct = stats.total > 0 ? (count / stats.total * 100) : 0
                return (
                  <div key={name} className="flex items-center gap-3">
                    <span className="text-sm text-[#e0e0e8] w-24 flex-shrink-0">{name}</span>
                    <div className="flex-1 bg-[#2a2a3a] rounded-full h-2">
                      <div
                        className="bg-[#6366f1] h-2 rounded-full transition-all"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-xs text-[#8888a0] w-16 text-right">
                      {count} ({pct.toFixed(0)}%)
                    </span>
                  </div>
                )
              })}
          </div>
        </Card>
      )}

      {/* Daily activity chart (simple bar chart) */}
      {stats?.daily && Object.keys(stats.daily).length > 0 && (
        <Card title="Daily Activity">
          <div className="flex items-end gap-1 h-32">
            {Object.entries(stats.daily)
              .sort(([a], [b]) => a.localeCompare(b))
              .slice(-14)
              .map(([day, count]) => {
                const maxCount = Math.max(...Object.values(stats.daily))
                const height = maxCount > 0 ? (count / maxCount * 100) : 0
                return (
                  <div key={day} className="flex-1 flex flex-col items-center gap-1">
                    <div
                      className="w-full bg-[#6366f1]/60 rounded-t min-h-[2px] transition-all"
                      style={{ height: `${height}%` }}
                      title={`${day}: ${count} sessions`}
                    />
                    <span className="text-[10px] text-[#8888a0] -rotate-45 origin-top-left whitespace-nowrap">
                      {day.slice(5)}
                    </span>
                  </div>
                )
              })}
          </div>
        </Card>
      )}

      {statsLoading && !stats && (
        <p className="text-[#8888a0] text-sm">Loading statistics...</p>
      )}
    </div>
  )
}
