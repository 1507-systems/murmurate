/**
 * Config — View and edit the Murmurate configuration.
 *
 * Displays the current config as structured form fields grouped by section
 * (scheduler, transport, rate limits, etc.). Changes are saved to config.toml
 * on the daemon side and trigger a hot-reload.
 */

import { useState, useEffect } from 'react'
import { useApi } from '../hooks/useApi'
import { getConfig, updateConfig } from '../api'
import Card from '../components/Card'
import Button from '../components/Button'

export default function Config() {
  const { data: config, loading, refresh } = useApi(getConfig)
  const [editConfig, setEditConfig] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState(null)

  // Sync fetched config into the edit state
  useEffect(() => {
    if (config) setEditConfig(structuredClone(config))
  }, [config])

  function updateField(section, key, value) {
    setEditConfig(prev => ({
      ...prev,
      [section]: { ...prev[section], [key]: value },
    }))
  }

  async function handleSave() {
    setSaving(true)
    setSaveMsg(null)
    try {
      await updateConfig(editConfig)
      setSaveMsg('Configuration saved and reloaded.')
      refresh()
    } catch (err) {
      setSaveMsg(`Error: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  if (loading && !config) {
    return (
      <div>
        <h1 className="text-xl font-semibold text-white mb-6">Configuration</h1>
        <p className="text-[#8888a0] text-sm">Loading configuration...</p>
      </div>
    )
  }

  if (!editConfig) return null

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-white">Configuration</h1>
        <div className="flex items-center gap-3">
          {saveMsg && (
            <span className={`text-xs ${saveMsg.startsWith('Error') ? 'text-[#ef4444]' : 'text-[#22c55e]'}`}>
              {saveMsg}
            </span>
          )}
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Changes'}
          </Button>
        </div>
      </div>

      {/* Scheduler */}
      <Card title="Scheduler" className="mb-4">
        <div className="grid grid-cols-2 gap-4">
          <ConfigField
            label="Sessions per hour (min)"
            value={editConfig.scheduler?.sessions_per_hour_min}
            type="number"
            onChange={v => updateField('scheduler', 'sessions_per_hour_min', parseInt(v, 10))}
          />
          <ConfigField
            label="Sessions per hour (max)"
            value={editConfig.scheduler?.sessions_per_hour_max}
            type="number"
            onChange={v => updateField('scheduler', 'sessions_per_hour_max', parseInt(v, 10))}
          />
          <ConfigField
            label="Active hours start"
            value={editConfig.scheduler?.active_hours_start}
            onChange={v => updateField('scheduler', 'active_hours_start', v)}
          />
          <ConfigField
            label="Active hours end"
            value={editConfig.scheduler?.active_hours_end}
            onChange={v => updateField('scheduler', 'active_hours_end', v)}
          />
          <ConfigField
            label="Quiet hours start"
            value={editConfig.scheduler?.quiet_hours_start}
            onChange={v => updateField('scheduler', 'quiet_hours_start', v)}
          />
          <ConfigField
            label="Quiet hours end"
            value={editConfig.scheduler?.quiet_hours_end}
            onChange={v => updateField('scheduler', 'quiet_hours_end', v)}
          />
          <ConfigField
            label="Burst probability"
            value={editConfig.scheduler?.burst_probability}
            type="number"
            step="0.05"
            onChange={v => updateField('scheduler', 'burst_probability', parseFloat(v))}
          />
          <ConfigField
            label="Timezone"
            value={editConfig.scheduler?.active_hours_timezone}
            onChange={v => updateField('scheduler', 'active_hours_timezone', v)}
          />
        </div>
      </Card>

      {/* Transport */}
      <Card title="Transport" className="mb-4">
        <div className="grid grid-cols-2 gap-4">
          <ConfigField
            label="Browser ratio"
            value={editConfig.transport?.browser_ratio}
            type="number"
            step="0.1"
            onChange={v => updateField('transport', 'browser_ratio', parseFloat(v))}
          />
          <ConfigField
            label="Browser pool size"
            value={editConfig.transport?.browser_pool_size}
            type="number"
            onChange={v => updateField('transport', 'browser_pool_size', parseInt(v, 10))}
          />
          <ConfigField
            label="Headless"
            value={editConfig.transport?.headless}
            type="checkbox"
            onChange={v => updateField('transport', 'headless', v)}
          />
          <ConfigField
            label="Mouse jitter"
            value={editConfig.transport?.mouse_jitter}
            type="checkbox"
            onChange={v => updateField('transport', 'mouse_jitter', v)}
          />
        </div>
      </Card>

      {/* Rate limits */}
      <Card title="Rate Limits" className="mb-4">
        <div className="grid grid-cols-2 gap-4">
          <ConfigField
            label="Global bandwidth (Mbps)"
            value={editConfig.rate_limit?.global_bandwidth_mbps}
            type="number"
            onChange={v => updateField('rate_limit', 'global_bandwidth_mbps', parseInt(v, 10))}
          />
          <ConfigField
            label="Default per-domain RPM"
            value={editConfig.rate_limit?.default_per_domain_rpm}
            type="number"
            onChange={v => updateField('rate_limit', 'default_per_domain_rpm', parseInt(v, 10))}
          />
        </div>
      </Card>

      {/* Persona settings */}
      <Card title="Persona Settings">
        <div className="grid grid-cols-2 gap-4">
          <ConfigField
            label="Auto-generate count"
            value={editConfig.persona?.auto_generate_count}
            type="number"
            onChange={v => updateField('persona', 'auto_generate_count', parseInt(v, 10))}
          />
          <ConfigField
            label="Drift rate"
            value={editConfig.persona?.drift_rate}
            type="number"
            step="0.05"
            onChange={v => updateField('persona', 'drift_rate', parseFloat(v))}
          />
          <ConfigField
            label="Max tree depth"
            value={editConfig.persona?.max_tree_depth}
            type="number"
            onChange={v => updateField('persona', 'max_tree_depth', parseInt(v, 10))}
          />
        </div>
      </Card>
    </div>
  )
}

function ConfigField({ label, value, type = 'text', step, onChange }) {
  if (type === 'checkbox') {
    return (
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={!!value}
          onChange={e => onChange(e.target.checked)}
          className="rounded border-[#2a2a3a] bg-[#0f0f13] text-[#6366f1] focus:ring-[#6366f1]"
        />
        <span className="text-sm text-[#e0e0e8]">{label}</span>
      </label>
    )
  }

  return (
    <div>
      <label className="block text-xs text-[#8888a0] uppercase tracking-wider mb-1">
        {label}
      </label>
      <input
        type={type}
        value={value ?? ''}
        step={step}
        onChange={e => onChange(e.target.value)}
        className="w-full bg-[#0f0f13] border border-[#2a2a3a] rounded px-3 py-2 text-sm text-[#e0e0e8] focus:outline-none focus:border-[#6366f1]"
      />
    </div>
  )
}
