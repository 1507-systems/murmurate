/**
 * App — Root component for the Murmurate Control UI.
 *
 * Simple client-side routing via state (no router library needed for this
 * small number of pages). The Layout component provides the sidebar shell.
 */

import { useEffect, useState } from 'react'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Personas from './pages/Personas'
import History from './pages/History'
import Plugins from './pages/Plugins'
import Config from './pages/Config'
import { configure } from './api'

const PAGES = {
  dashboard: Dashboard,
  personas: Personas,
  history: History,
  plugins: Plugins,
  config: Config,
}

// sessionStorage key the auth token is cached under once received — see
// _bootstrapAuthToken below.
const TOKEN_STORAGE_KEY = 'murmurate_api_token'

/**
 * Pick up the API bearer token the daemon now always requires.
 *
 * The control UI is a static SPA with no filesystem access, so it can't
 * read the token file (~/.config/murmurate/api_token) directly. Instead,
 * whatever opens the dashboard — the menu bar app's "Open Dashboard" link —
 * hands the token off via a `?token=` URL parameter (the same pattern
 * Jupyter uses for its notebook server). We stash it in sessionStorage so a
 * plain page reload doesn't lose auth, then strip it from the URL so it
 * doesn't linger in browser history.
 */
function _bootstrapAuthToken() {
  const params = new URLSearchParams(window.location.search)
  const urlToken = params.get('token')

  if (urlToken) {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, urlToken)
    configure({ token: urlToken })

    params.delete('token')
    const query = params.toString()
    const cleanedUrl =
      window.location.pathname + (query ? `?${query}` : '') + window.location.hash
    window.history.replaceState({}, '', cleanedUrl)
    return
  }

  const storedToken = sessionStorage.getItem(TOKEN_STORAGE_KEY)
  if (storedToken) {
    configure({ token: storedToken })
  }
  // Neither present: requests will 401 until the dashboard is reopened via
  // a link that includes the token (or the dev proxy injects it — see
  // vite.config.js, which never needs this browser-side handoff at all).
}

export default function App() {
  const [activePage, setActivePage] = useState('dashboard')
  const PageComponent = PAGES[activePage] || Dashboard

  useEffect(() => {
    _bootstrapAuthToken()
  }, [])

  return (
    <Layout activePage={activePage} onNavigate={setActivePage}>
      <PageComponent />
    </Layout>
  )
}
