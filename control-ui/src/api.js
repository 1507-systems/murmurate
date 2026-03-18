/**
 * api.js — HTTP client for the Murmurate REST API.
 *
 * All API calls go through this module so connection settings (base URL, auth
 * token) are configured in one place. During development, Vite proxies /api
 * requests to the daemon; in production the UI is served by the daemon itself.
 */

const DEFAULT_BASE_URL = '/api'

let baseUrl = DEFAULT_BASE_URL
let authToken = null

/**
 * Configure the API client. Call this at startup if connecting to a remote
 * Murmurate instance (different host/port than where the UI is served).
 */
export function configure({ url, token }) {
  if (url) baseUrl = url.replace(/\/$/, '')
  if (token) authToken = token
}

/**
 * Internal fetch wrapper that adds auth headers and handles errors.
 */
async function request(path, options = {}) {
  const url = `${baseUrl}${path}`
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  }

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`
  }

  const response = await fetch(url, { ...options, headers })

  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }))
    const error = new Error(body.error || `HTTP ${response.status}`)
    error.status = response.status
    error.body = body
    throw error
  }

  return response.json()
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

export async function getStatus() {
  return request('/status')
}

export async function stopDaemon() {
  return request('/daemon/stop', { method: 'POST' })
}

// ---------------------------------------------------------------------------
// Personas
// ---------------------------------------------------------------------------

export async function getPersonas() {
  return request('/personas')
}

export async function getPersona(name) {
  return request(`/personas/${encodeURIComponent(name)}`)
}

export async function createPersona(name, seeds = []) {
  return request('/personas', {
    method: 'POST',
    body: JSON.stringify({ name, seeds }),
  })
}

export async function updatePersona(name, data) {
  return request(`/personas/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deletePersona(name) {
  return request(`/personas/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
}

// ---------------------------------------------------------------------------
// History & Stats
// ---------------------------------------------------------------------------

export async function getHistory(limit = 50) {
  return request(`/history?limit=${limit}`)
}

export async function getStats(days = 7) {
  return request(`/stats?days=${days}`)
}

// ---------------------------------------------------------------------------
// Plugins
// ---------------------------------------------------------------------------

export async function getPlugins() {
  return request('/plugins')
}

export async function getPlugin(name) {
  return request(`/plugins/${encodeURIComponent(name)}`)
}

export async function enablePlugin(name) {
  return request(`/plugins/${encodeURIComponent(name)}/enable`, { method: 'POST' })
}

export async function disablePlugin(name) {
  return request(`/plugins/${encodeURIComponent(name)}/disable`, { method: 'POST' })
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export async function getConfig() {
  return request('/config')
}

export async function updateConfig(data) {
  return request('/config', {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}
