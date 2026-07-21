/**
 * Tests for useSSE and useSessionEvents hooks.
 *
 * EventSource is not available in jsdom so we provide a mock that simulates
 * the browser's native EventSource interface.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSSE, useSessionEvents } from '../hooks/useSSE'
import { configure } from '../api'

// ---------------------------------------------------------------------------
// EventSource mock
// ---------------------------------------------------------------------------

class MockEventSource {
  constructor(url) {
    this.url = url
    this.readyState = 0  // CONNECTING
    this.onopen = null
    this.onmessage = null
    this.onerror = null
    MockEventSource.instances.push(this)
  }

  static instances = []

  static reset() {
    MockEventSource.instances = []
  }

  close() {
    this.readyState = 2  // CLOSED
  }

  // Test helper: simulate the server sending a JSON event
  simulateMessage(data) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) })
    }
  }

  // Test helper: simulate connection open
  simulateOpen() {
    this.readyState = 1  // OPEN
    if (this.onopen) this.onopen()
  }

  // Test helper: simulate an error (triggers reconnect in real browser)
  simulateError() {
    if (this.onerror) this.onerror(new Event('error'))
  }
}

beforeEach(() => {
  MockEventSource.reset()
  globalThis.EventSource = MockEventSource
  // useSSE.js reads the module-level auth token via api.js's getToken();
  // reset it so tests don't leak state into each other.
  configure({ token: null })
})

afterEach(() => {
  delete globalThis.EventSource
})

// ---------------------------------------------------------------------------
// useSSE
// ---------------------------------------------------------------------------

describe('useSSE', () => {
  it('starts as disconnected', () => {
    const { result } = renderHook(() => useSSE())
    expect(result.current.connected).toBe(false)
  })

  it('becomes connected when EventSource fires onopen', () => {
    const { result } = renderHook(() => useSSE())

    act(() => {
      const es = MockEventSource.instances[0]
      es.simulateOpen()
    })

    expect(result.current.connected).toBe(true)
  })

  it('lastEvent is null initially', () => {
    const { result } = renderHook(() => useSSE())
    expect(result.current.lastEvent).toBeNull()
  })

  it('delivers parsed event to lastEvent', () => {
    const { result } = renderHook(() => useSSE())

    act(() => {
      const es = MockEventSource.instances[0]
      es.simulateOpen()
      es.simulateMessage({ type: 'session_completed', session_id: 'abc', ts: 1000 })
    })

    expect(result.current.lastEvent).toMatchObject({
      type: 'session_completed',
      session_id: 'abc',
    })
  })

  it('increments eventCount on each message', () => {
    const { result } = renderHook(() => useSSE())

    act(() => {
      const es = MockEventSource.instances[0]
      es.simulateMessage({ type: 'ping', ts: 1 })
      es.simulateMessage({ type: 'pong', ts: 2 })
    })

    expect(result.current.eventCount).toBe(2)
  })

  it('calls onEvent callback with parsed event', () => {
    const onEvent = vi.fn()
    renderHook(() => useSSE({ onEvent }))

    act(() => {
      const es = MockEventSource.instances[0]
      es.simulateMessage({ type: 'session_started', persona_name: 'chef', ts: 1 })
    })

    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'session_started', persona_name: 'chef' })
    )
  })

  it('handles malformed JSON without throwing', () => {
    const { result } = renderHook(() => useSSE())

    act(() => {
      const es = MockEventSource.instances[0]
      if (es.onmessage) es.onmessage({ data: 'not json {{{' })
    })

    // Should not crash; lastEvent stays null
    expect(result.current.lastEvent).toBeNull()
  })

  it('sets connected to false on error', () => {
    const { result } = renderHook(() => useSSE())

    act(() => {
      const es = MockEventSource.instances[0]
      es.simulateOpen()
    })
    expect(result.current.connected).toBe(true)

    act(() => {
      const es = MockEventSource.instances[0]
      es.simulateError()
    })
    expect(result.current.connected).toBe(false)
  })

  it('does not create EventSource when enabled is false', () => {
    renderHook(() => useSSE({ enabled: false }))
    expect(MockEventSource.instances.length).toBe(0)
  })

  it('closes EventSource on unmount', () => {
    const { unmount } = renderHook(() => useSSE())
    const es = MockEventSource.instances[0]
    expect(es.readyState).not.toBe(2)
    unmount()
    expect(es.readyState).toBe(2)  // CLOSED
  })
})

// ---------------------------------------------------------------------------
// useSessionEvents
// ---------------------------------------------------------------------------

describe('useSessionEvents', () => {
  it('starts with empty events array', () => {
    const { result } = renderHook(() => useSessionEvents())
    expect(result.current.events).toEqual([])
  })

  it('accumulates session lifecycle events', () => {
    const { result } = renderHook(() => useSessionEvents())

    act(() => {
      const es = MockEventSource.instances[0]
      es.simulateMessage({ type: 'session_completed', persona_name: 'chef', ts: 1 })
      es.simulateMessage({ type: 'session_failed', persona_name: 'baker', ts: 2 })
      es.simulateMessage({ type: 'session_started', persona_name: 'gamer', ts: 3 })
    })

    expect(result.current.events.length).toBe(3)
  })

  it('ignores non-session events', () => {
    const { result } = renderHook(() => useSessionEvents())

    act(() => {
      const es = MockEventSource.instances[0]
      // "connected" is not a session lifecycle event
      es.simulateMessage({ type: 'connected', ts: 1 })
      es.simulateMessage({ type: 'heartbeat', ts: 2 })
    })

    expect(result.current.events.length).toBe(0)
  })

  it('newest events appear first', () => {
    const { result } = renderHook(() => useSessionEvents())

    act(() => {
      const es = MockEventSource.instances[0]
      es.simulateMessage({ type: 'session_completed', persona_name: 'first', ts: 100 })
      es.simulateMessage({ type: 'session_completed', persona_name: 'second', ts: 200 })
    })

    // Most recent (second) should be at index 0
    expect(result.current.events[0].persona_name).toBe('second')
    expect(result.current.events[1].persona_name).toBe('first')
  })

  it('respects maxEvents limit', () => {
    const { result } = renderHook(() => useSessionEvents(3))

    act(() => {
      const es = MockEventSource.instances[0]
      for (let i = 0; i < 10; i++) {
        es.simulateMessage({ type: 'session_completed', persona_name: `p${i}`, ts: i })
      }
    })

    expect(result.current.events.length).toBe(3)
  })

  it('clearEvents empties the list', () => {
    const { result } = renderHook(() => useSessionEvents())

    act(() => {
      const es = MockEventSource.instances[0]
      es.simulateMessage({ type: 'session_completed', persona_name: 'chef', ts: 1 })
    })
    expect(result.current.events.length).toBe(1)

    act(() => {
      result.current.clearEvents()
    })
    expect(result.current.events.length).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// Auth token query parameter
//
// EventSource cannot set an Authorization header, so useSSE appends the
// token api.js has configured (via App.jsx's URL/sessionStorage bootstrap,
// or nothing at all in dev mode where the Vite proxy injects it instead)
// as a `?token=` query parameter — the one case auth_middleware accepts it.
// ---------------------------------------------------------------------------

describe('useSSE auth token handling', () => {
  it('connects without a token query param when none is configured', () => {
    renderHook(() => useSSE())
    expect(MockEventSource.instances[0].url).toBe('/api/events')
  })

  it('appends the configured token as a query parameter', () => {
    configure({ token: 'stream-secret' })
    renderHook(() => useSSE())
    expect(MockEventSource.instances[0].url).toBe('/api/events?token=stream-secret')
  })

  it('URL-encodes special characters in the token', () => {
    configure({ token: 'a/b+c' })
    renderHook(() => useSSE())
    expect(MockEventSource.instances[0].url).toBe('/api/events?token=a%2Fb%2Bc')
  })
})
