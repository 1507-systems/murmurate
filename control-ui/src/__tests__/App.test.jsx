/**
 * Tests for the main App component and navigation.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from '../App'
import { configure } from '../api'

// Mock the API so components don't make real fetch calls
vi.mock('../api', () => ({
  getStatus: vi.fn().mockResolvedValue({ running: false, version: '0.1.0' }),
  getStats: vi.fn().mockResolvedValue({ total: 0, completed: 0, failed: 0, plugins: {}, transports: {}, daily: {} }),
  getPersonas: vi.fn().mockResolvedValue([]),
  getHistory: vi.fn().mockResolvedValue([]),
  getPlugins: vi.fn().mockResolvedValue([]),
  getConfig: vi.fn().mockResolvedValue({
    config_version: 1,
    scheduler: {},
    transport: {},
    rate_limit: {},
    persona: {},
    plugin: {},
  }),
  stopDaemon: vi.fn(),
  configure: vi.fn(),
  getToken: vi.fn().mockReturnValue(null),
}))

beforeEach(() => {
  configure.mockClear()
  sessionStorage.clear()
  window.history.replaceState({}, '', '/')
})

describe('App', () => {
  it('renders the layout with sidebar', async () => {
    render(<App />)
    // Sidebar title
    expect(screen.getByText('Murmurate')).toBeInTheDocument()
    expect(screen.getByText('Control UI')).toBeInTheDocument()
  })

  it('shows Dashboard by default', async () => {
    render(<App />)
    // "Dashboard" appears in both the nav and the page heading
    const dashboards = screen.getAllByText('Dashboard')
    expect(dashboards.length).toBeGreaterThanOrEqual(2)
  })

  it('navigates to Personas page', async () => {
    render(<App />)
    fireEvent.click(screen.getByText('Personas'))
    await waitFor(() => {
      expect(screen.getByText('Create Persona')).toBeInTheDocument()
    })
  })

  it('navigates to History page', async () => {
    render(<App />)
    fireEvent.click(screen.getByText('History'))
    await waitFor(() => {
      expect(screen.getByText('Session History')).toBeInTheDocument()
    })
  })

  it('navigates to Plugins page', async () => {
    render(<App />)
    fireEvent.click(screen.getByText('Plugins'))
    await waitFor(() => {
      // The heading "Plugins" exists both in nav and page
      const headings = screen.getAllByText('Plugins')
      expect(headings.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('navigates to Config page', async () => {
    render(<App />)
    fireEvent.click(screen.getByText('Config'))
    await waitFor(() => {
      expect(screen.getByText('Configuration')).toBeInTheDocument()
    })
  })

  it('shows daemon status in sidebar', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Daemon stopped')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Auth token bootstrap
//
// The API now always requires a bearer token (see the daemon's
// murmurate.api.auth module). The control UI is a static SPA with no
// filesystem access, so the token is handed off via a `?token=` URL
// parameter (set by the menu bar app's "Open Dashboard" link) and cached in
// sessionStorage so a plain reload doesn't lose auth.
// ---------------------------------------------------------------------------

describe('App auth token bootstrap', () => {
  it('configures the API client from a ?token= URL parameter', async () => {
    window.history.pushState({}, '', '/?token=url-handoff-token')
    render(<App />)
    await waitFor(() => {
      expect(configure).toHaveBeenCalledWith({ token: 'url-handoff-token' })
    })
  })

  it('strips the token from the URL after reading it', async () => {
    window.history.pushState({}, '', '/?token=url-handoff-token&page=dashboard')
    render(<App />)
    await waitFor(() => {
      expect(window.location.search).not.toContain('token=')
    })
    // Unrelated query params are preserved.
    expect(window.location.search).toContain('page=dashboard')
  })

  it('caches the URL token in sessionStorage', async () => {
    window.history.pushState({}, '', '/?token=url-handoff-token')
    render(<App />)
    await waitFor(() => {
      expect(sessionStorage.getItem('murmurate_api_token')).toBe('url-handoff-token')
    })
  })

  it('falls back to a sessionStorage token when the URL has none', async () => {
    sessionStorage.setItem('murmurate_api_token', 'stored-token')
    render(<App />)
    await waitFor(() => {
      expect(configure).toHaveBeenCalledWith({ token: 'stored-token' })
    })
  })

  it('does not call configure when neither URL nor sessionStorage has a token', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Murmurate')).toBeInTheDocument()
    })
    expect(configure).not.toHaveBeenCalled()
  })

  it('prefers the URL token over a stale sessionStorage value', async () => {
    sessionStorage.setItem('murmurate_api_token', 'stale-token')
    window.history.pushState({}, '', '/?token=fresh-token')
    render(<App />)
    await waitFor(() => {
      expect(configure).toHaveBeenCalledWith({ token: 'fresh-token' })
    })
    expect(sessionStorage.getItem('murmurate_api_token')).toBe('fresh-token')
  })
})
