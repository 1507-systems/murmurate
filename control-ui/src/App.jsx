/**
 * App — Root component for the Murmurate Control UI.
 *
 * Simple client-side routing via state (no router library needed for this
 * small number of pages). The Layout component provides the sidebar shell.
 */

import { useState } from 'react'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Personas from './pages/Personas'
import History from './pages/History'
import Plugins from './pages/Plugins'
import Config from './pages/Config'

const PAGES = {
  dashboard: Dashboard,
  personas: Personas,
  history: History,
  plugins: Plugins,
  config: Config,
}

export default function App() {
  const [activePage, setActivePage] = useState('dashboard')
  const PageComponent = PAGES[activePage] || Dashboard

  return (
    <Layout activePage={activePage} onNavigate={setActivePage}>
      <PageComponent />
    </Layout>
  )
}
