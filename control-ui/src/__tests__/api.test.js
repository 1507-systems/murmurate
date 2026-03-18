/**
 * Tests for the API client module.
 *
 * Mocks fetch globally to verify request construction (URLs, headers, bodies)
 * and error handling without hitting a real server.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  configure,
  getStatus,
  stopDaemon,
  getPersonas,
  getPersona,
  createPersona,
  deletePersona,
  getHistory,
  getStats,
  enablePlugin,
  disablePlugin,
  updateConfig,
} from '../api'

// Mock fetch globally
const mockFetch = vi.fn()
globalThis.fetch = mockFetch

function mockResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(data),
  }
}

beforeEach(() => {
  mockFetch.mockReset()
  // Reset to defaults — configure sets module-level state
  configure({ url: '/api', token: null })
})

describe('API client', () => {
  it('getStatus fetches /api/status', async () => {
    mockFetch.mockResolvedValue(mockResponse({ running: true, version: '0.1.0' }))
    const result = await getStatus()
    expect(result.running).toBe(true)
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/status',
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) })
    )
  })

  it('stopDaemon sends POST', async () => {
    mockFetch.mockResolvedValue(mockResponse({ message: 'ok' }))
    await stopDaemon()
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/daemon/stop',
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('getPersonas fetches persona list', async () => {
    const personas = [{ name: 'test', seeds: ['cooking'] }]
    mockFetch.mockResolvedValue(mockResponse(personas))
    const result = await getPersonas()
    expect(result).toEqual(personas)
  })

  it('getPersona fetches single persona', async () => {
    mockFetch.mockResolvedValue(mockResponse({ name: 'chef' }))
    const result = await getPersona('chef')
    expect(result.name).toBe('chef')
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/personas/chef',
      expect.anything()
    )
  })

  it('createPersona sends POST with body', async () => {
    mockFetch.mockResolvedValue(mockResponse({ name: 'new' }, 201))
    await createPersona('new', ['seed1', 'seed2'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toBe('/api/personas')
    expect(opts.method).toBe('POST')
    expect(JSON.parse(opts.body)).toEqual({ name: 'new', seeds: ['seed1', 'seed2'] })
  })

  it('deletePersona sends DELETE', async () => {
    mockFetch.mockResolvedValue(mockResponse({ message: 'deleted' }))
    await deletePersona('old')
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/personas/old',
      expect.objectContaining({ method: 'DELETE' })
    )
  })

  it('getHistory passes limit parameter', async () => {
    mockFetch.mockResolvedValue(mockResponse([]))
    await getHistory(100)
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/history?limit=100',
      expect.anything()
    )
  })

  it('getStats passes days parameter', async () => {
    mockFetch.mockResolvedValue(mockResponse({ total: 0 }))
    await getStats(30)
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/stats?days=30',
      expect.anything()
    )
  })

  it('enablePlugin sends POST', async () => {
    mockFetch.mockResolvedValue(mockResponse({ message: 'enabled' }))
    await enablePlugin('google')
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/plugins/google/enable',
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('disablePlugin sends POST', async () => {
    mockFetch.mockResolvedValue(mockResponse({ message: 'disabled' }))
    await disablePlugin('bing')
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/plugins/bing/disable',
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('updateConfig sends PUT with body', async () => {
    mockFetch.mockResolvedValue(mockResponse({ message: 'updated' }))
    await updateConfig({ scheduler: { burst_probability: 0.5 } })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toBe('/api/config')
    expect(opts.method).toBe('PUT')
  })

  it('configure sets custom base URL', async () => {
    configure({ url: 'http://192.168.1.100:7683/api' })
    mockFetch.mockResolvedValue(mockResponse({ running: true }))
    await getStatus()
    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.100:7683/api/status',
      expect.anything()
    )
  })

  it('configure adds auth token to headers', async () => {
    configure({ url: '/api', token: 'my-secret' })
    mockFetch.mockResolvedValue(mockResponse({ running: true }))
    await getStatus()
    const [, opts] = mockFetch.mock.calls[0]
    expect(opts.headers.Authorization).toBe('Bearer my-secret')
  })

  it('throws on HTTP error responses', async () => {
    mockFetch.mockResolvedValue(mockResponse({ error: 'Not found' }, 404))
    await expect(getPersona('nonexistent')).rejects.toThrow('Not found')
  })

  it('encodes persona names in URL', async () => {
    mockFetch.mockResolvedValue(mockResponse({ name: 'my persona' }))
    await getPersona('my persona')
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/personas/my%20persona',
      expect.anything()
    )
  })
})
