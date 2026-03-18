/**
 * Plugins — View and manage site plugins.
 *
 * Displays all registered plugins with their transport preferences, rate
 * limits, and enabled/disabled status. Allows toggling plugins on/off.
 */

import { useApi } from '../hooks/useApi'
import { getPlugins, enablePlugin, disablePlugin } from '../api'
import Card from '../components/Card'
import Button from '../components/Button'
import StatusBadge from '../components/StatusBadge'

export default function Plugins() {
  const { data: plugins, loading, refresh } = useApi(getPlugins)

  async function handleToggle(name, currentlyEnabled) {
    try {
      if (currentlyEnabled) {
        await disablePlugin(name)
      } else {
        await enablePlugin(name)
      }
      refresh()
    } catch {
      // Will show on next refresh
    }
  }

  return (
    <div>
      <h1 className="text-xl font-semibold text-white mb-6">Plugins</h1>

      <Card>
        {loading && !plugins && (
          <p className="text-[#8888a0] text-sm">Loading plugins...</p>
        )}
        {plugins && plugins.length === 0 && (
          <p className="text-[#8888a0] text-sm">No plugins registered.</p>
        )}
        {plugins && plugins.length > 0 && (
          <div className="space-y-3">
            {plugins.map(p => (
              <div
                key={p.name}
                className="flex items-center justify-between p-3 bg-[#0f0f13] rounded-lg"
              >
                <div className="flex items-center gap-4">
                  <div>
                    <span className="text-sm font-medium text-[#e0e0e8]">{p.name}</span>
                    <div className="flex gap-3 mt-1 text-xs text-[#8888a0]">
                      <span>Transport: {p.preferred_transport}</span>
                      <span>Rate: {p.rate_limit_rpm} RPM</span>
                      {p.domains && (
                        <span>Domains: {p.domains.slice(0, 3).join(', ')}</span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  {p.consecutive_failures > 0 && (
                    <span className="text-xs text-[#f59e0b]">
                      {p.consecutive_failures} failures
                    </span>
                  )}
                  <StatusBadge status={p.enabled ? 'enabled' : 'disabled'} />
                  <Button
                    variant={p.enabled ? 'danger' : 'primary'}
                    size="sm"
                    onClick={() => handleToggle(p.name, p.enabled)}
                  >
                    {p.enabled ? 'Disable' : 'Enable'}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
