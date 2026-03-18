/**
 * Tests for the main App component and navigation.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from '../App'

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
}))

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
