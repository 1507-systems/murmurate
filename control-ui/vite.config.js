import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// The daemon now always requires a bearer token (see
// murmurate.api.auth.get_or_create_api_token) and enforces a strict
// same-origin check (murmurate.api.middleware.origin_middleware). Neither
// is something the *browser* can satisfy when talking through this dev
// proxy: the token file lives outside the browser sandbox, and the
// browser's Origin header (http://localhost:5173) legitimately differs
// from the daemon's own origin. Vite's proxy runs in Node, though, so it
// can read the token off disk and rewrite the Origin header itself, making
// the proxied dev flow look — from the daemon's point of view — exactly
// like the production same-origin deployment. The browser-side app never
// needs to know the token in dev mode at all.
const PROXY_TARGET = 'http://127.0.0.1:7683'

/**
 * Read the daemon's auto-generated API token from its config directory.
 *
 * Re-read on every proxied request (rather than cached at server startup)
 * so a token rotated by deleting the file and restarting the daemon is
 * picked up without also restarting `vite dev`.
 */
function readApiToken() {
  const configDir =
    process.env.MURMURATE_CONFIG || path.join(os.homedir(), '.config', 'murmurate')
  try {
    return fs.readFileSync(path.join(configDir, 'api_token'), 'utf-8').trim() || null
  } catch {
    // Daemon hasn't run yet, or MURMURATE_CONFIG points elsewhere — proxied
    // requests will 401 until `murmurate start --api` / `murmurate api` has
    // run at least once to generate the token file.
    return null
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Proxy API requests to the Murmurate daemon during development
    proxy: {
      '/api': {
        target: PROXY_TARGET,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            const token = readApiToken()
            if (token) {
              proxyReq.setHeader('Authorization', `Bearer ${token}`)
            }
            // See PROXY_TARGET comment above — presenting the daemon's own
            // origin here (instead of the browser's localhost:5173) is
            // safe: the browser's cross-origin request already terminated
            // at this trusted, same-machine Node process.
            proxyReq.setHeader('Origin', PROXY_TARGET)
          })
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.js',
  },
})
