/**
 * useApi — React hook for data fetching with loading/error states.
 *
 * Provides a simple pattern for components to fetch data from the API with
 * automatic refresh support. Returns { data, loading, error, refresh }.
 */

import { useState, useEffect, useCallback } from 'react'

export function useApi(fetchFn, deps = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchFn()
      setData(result)
    } catch (err) {
      setError(err.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
    // fetchFn is intentionally excluded — callers should pass a stable reference
    // or wrap in useCallback. Including it here would cause infinite loops when
    // the caller passes an inline arrow function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    refresh()
  }, [refresh])

  return { data, loading, error, refresh }
}

/**
 * usePolling — Like useApi but auto-refreshes on an interval.
 * Good for status and history views that should stay up to date.
 */
export function usePolling(fetchFn, intervalMs = 5000, deps = []) {
  const result = useApi(fetchFn, deps)

  useEffect(() => {
    const timer = setInterval(result.refresh, intervalMs)
    return () => clearInterval(timer)
  }, [result.refresh, intervalMs])

  return result
}
