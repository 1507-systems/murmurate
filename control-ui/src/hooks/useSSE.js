/**
 * useSSE — React hook for consuming the Murmurate SSE event stream.
 *
 * Opens a persistent EventSource connection to GET /api/events and
 * delivers structured JSON events to the caller. The connection
 * automatically reconnects on drop (browser EventSource behaviour).
 *
 * Usage:
 *   const { connected, lastEvent } = useSSE()
 *
 *   // With a handler for a specific event type:
 *   useSSE({ onEvent: (ev) => {
 *     if (ev.type === 'session_completed') setCount(c => c + 1)
 *   }})
 *
 * Event types pushed by the server:
 *   - connected          Initial confirmation that the stream is live.
 *   - session_started    A new session has been dispatched.
 *   - session_completed  A session finished successfully.
 *   - session_failed     A session encountered an error.
 *
 * The hook falls back silently when EventSource is unavailable (very old
 * browsers or test environments) — components using it continue to work
 * via their existing polling hooks.
 */

import { useState, useEffect, useRef, useCallback } from 'react'

const SSE_PATH = '/api/events'

/**
 * @param {object}   [options]
 * @param {function} [options.onEvent]   Called with the parsed event object on every message.
 * @param {boolean}  [options.enabled]   Set to false to disable the connection (default: true).
 * @returns {{ connected: boolean, lastEvent: object|null, eventCount: number }}
 */
export function useSSE({ onEvent, enabled = true } = {}) {
  const [connected, setConnected] = useState(false)
  const [lastEvent, setLastEvent] = useState(null)
  const [eventCount, setEventCount] = useState(0)

  // Keep a stable ref to the onEvent callback so the effect does not
  // re-run (and re-connect) every render when the caller passes an inline fn.
  const onEventRef = useRef(onEvent)
  useEffect(() => { onEventRef.current = onEvent }, [onEvent])

  useEffect(() => {
    if (!enabled) return
    if (typeof EventSource === 'undefined') return  // SSR / old browsers

    const es = new EventSource(SSE_PATH)

    es.onopen = () => setConnected(true)

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        setLastEvent(event)
        setEventCount(n => n + 1)
        if (onEventRef.current) onEventRef.current(event)
      } catch {
        // Ignore unparseable frames (e.g. heartbeat comments never reach here
        // because SSE comments start with ":" not "data:")
      }
    }

    es.onerror = () => {
      // The browser will automatically reconnect; we just mark as disconnected
      // until the next onopen fires.
      setConnected(false)
    }

    return () => {
      es.close()
      setConnected(false)
    }
  }, [enabled])

  return { connected, lastEvent, eventCount }
}

/**
 * useSessionEvents — Convenience hook that accumulates live session events
 * into a running list, bounded to the most recent `maxEvents` items.
 *
 * Designed for the History page: new sessions appear instantly without
 * waiting for the next poll interval.
 *
 * @param {number} [maxEvents=200]  Maximum number of live events to keep.
 * @returns {{ events: object[], connected: boolean, clearEvents: function }}
 */
export function useSessionEvents(maxEvents = 200) {
  const [events, setEvents] = useState([])

  const handleEvent = useCallback((ev) => {
    // Only accumulate session lifecycle events, not the internal "connected" ping
    if (!['session_started', 'session_completed', 'session_failed'].includes(ev.type)) return
    setEvents(prev => {
      const next = [ev, ...prev]
      return next.length > maxEvents ? next.slice(0, maxEvents) : next
    })
  }, [maxEvents])

  const { connected } = useSSE({ onEvent: handleEvent })

  const clearEvents = useCallback(() => setEvents([]), [])

  return { events, connected, clearEvents }
}
