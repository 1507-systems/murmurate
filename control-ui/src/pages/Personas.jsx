/**
 * Personas — Manage personas: list, create, view details, delete.
 *
 * Shows a table of all personas with their seeds, session counts, and topic
 * tree size. A modal form allows creating new personas with custom or random
 * seeds.
 */

import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { getPersonas, getPersona, createPersona, deletePersona } from '../api'
import Card from '../components/Card'
import Button from '../components/Button'
import Modal from '../components/Modal'

export default function Personas() {
  const { data: personas, loading, refresh } = useApi(getPersonas)
  const [showCreate, setShowCreate] = useState(false)
  const [selectedPersona, setSelectedPersona] = useState(null)
  const [detail, setDetail] = useState(null)

  async function handleViewDetail(name) {
    setSelectedPersona(name)
    try {
      const data = await getPersona(name)
      setDetail(data)
    } catch {
      setDetail(null)
    }
  }

  async function handleDelete(name) {
    if (!confirm(`Delete persona "${name}"?`)) return
    try {
      await deletePersona(name)
      refresh()
      if (selectedPersona === name) {
        setSelectedPersona(null)
        setDetail(null)
      }
    } catch {
      // Will show on next refresh
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-white">Personas</h1>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          Create Persona
        </Button>
      </div>

      {/* Persona list */}
      <Card className="mb-6">
        {loading && !personas && (
          <p className="text-[#8888a0] text-sm">Loading personas...</p>
        )}
        {personas && personas.length === 0 && (
          <p className="text-[#8888a0] text-sm">
            No personas found. Create one to get started.
          </p>
        )}
        {personas && personas.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[#8888a0] text-xs uppercase tracking-wider">
                <th className="pb-3">Name</th>
                <th className="pb-3">Seeds</th>
                <th className="pb-3 text-right">Sessions</th>
                <th className="pb-3 text-right">Topics</th>
                <th className="pb-3 text-right">Expertise</th>
                <th className="pb-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2a3a]">
              {personas.map(p => (
                <tr key={p.name} className="hover:bg-[#22222f]">
                  <td className="py-2.5">
                    <button
                      onClick={() => handleViewDetail(p.name)}
                      className="text-[#818cf8] hover:underline"
                    >
                      {p.name}
                    </button>
                  </td>
                  <td className="py-2.5 text-[#8888a0]">
                    {p.seeds.slice(0, 3).join(', ')}
                    {p.seeds.length > 3 && ` +${p.seeds.length - 3}`}
                  </td>
                  <td className="py-2.5 text-right">{p.total_sessions}</td>
                  <td className="py-2.5 text-right">{p.topic_count}</td>
                  <td className="py-2.5 text-right">
                    {(p.expertise_level * 100).toFixed(0)}%
                  </td>
                  <td className="py-2.5 text-right">
                    <Button variant="danger" size="sm" onClick={() => handleDelete(p.name)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Persona detail panel */}
      {detail && (
        <Card title={`Persona: ${detail.name}`} className="mb-6">
          <div className="grid grid-cols-2 gap-4 text-sm mb-4">
            <div>
              <span className="text-[#8888a0]">Created:</span>{' '}
              {detail.created_at?.slice(0, 19).replace('T', ' ')}
            </div>
            <div>
              <span className="text-[#8888a0]">Sessions:</span>{' '}
              {detail.total_sessions}
            </div>
            <div>
              <span className="text-[#8888a0]">Expertise:</span>{' '}
              {(detail.expertise_level * 100).toFixed(1)}%
            </div>
            <div>
              <span className="text-[#8888a0]">Platform:</span>{' '}
              {detail.fingerprint?.platform}
            </div>
          </div>

          {/* Topic tree (simplified view) */}
          <h3 className="text-xs text-[#8888a0] uppercase tracking-wider mb-2">Topic Tree</h3>
          <div className="bg-[#0f0f13] rounded p-3 max-h-64 overflow-auto">
            {detail.topic_tree?.map((node, i) => (
              <TopicNode key={i} node={node} depth={0} />
            ))}
          </div>
        </Card>
      )}

      {/* Create persona modal */}
      <CreatePersonaModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => {
          setShowCreate(false)
          refresh()
        }}
      />
    </div>
  )
}

function TopicNode({ node, depth }) {
  const indent = depth * 16
  return (
    <>
      <div className="flex items-center gap-2 py-0.5" style={{ paddingLeft: indent }}>
        <span className="text-[#6366f1] text-xs">
          {node.children?.length > 0 ? '▸' : '·'}
        </span>
        <span className="text-sm text-[#e0e0e8]">{node.topic}</span>
        <span className="text-xs text-[#8888a0]">
          ({node.query_count} queries)
        </span>
      </div>
      {node.children?.map((child, i) => (
        <TopicNode key={i} node={child} depth={depth + 1} />
      ))}
    </>
  )
}

function CreatePersonaModal({ open, onClose, onCreated }) {
  const [name, setName] = useState('')
  const [seedsText, setSeedsText] = useState('')
  const [error, setError] = useState(null)
  const [creating, setCreating] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setCreating(true)

    const seeds = seedsText
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)

    try {
      await createPersona(name.trim(), seeds)
      setName('')
      setSeedsText('')
      onCreated()
    } catch (err) {
      setError(err.message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Create Persona">
      <form onSubmit={handleSubmit}>
        <div className="mb-4">
          <label className="block text-xs text-[#8888a0] uppercase tracking-wider mb-1">
            Name
          </label>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="e.g., woodworker"
            className="w-full bg-[#0f0f13] border border-[#2a2a3a] rounded px-3 py-2 text-sm text-[#e0e0e8] placeholder-[#8888a0]/50 focus:outline-none focus:border-[#6366f1]"
            required
          />
        </div>
        <div className="mb-4">
          <label className="block text-xs text-[#8888a0] uppercase tracking-wider mb-1">
            Seeds (comma-separated, leave empty for random)
          </label>
          <input
            type="text"
            value={seedsText}
            onChange={e => setSeedsText(e.target.value)}
            placeholder="e.g., woodworking, hand tools, joinery"
            className="w-full bg-[#0f0f13] border border-[#2a2a3a] rounded px-3 py-2 text-sm text-[#e0e0e8] placeholder-[#8888a0]/50 focus:outline-none focus:border-[#6366f1]"
          />
        </div>
        {error && (
          <p className="text-[#ef4444] text-sm mb-3">{error}</p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button type="submit" disabled={creating || !name.trim()}>
            {creating ? 'Creating...' : 'Create'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
