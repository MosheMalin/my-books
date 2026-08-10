/**
 * The one data-fetching primitive in this app.
 *
 * ⚠ **The request-id guard is the load-bearing part**, and it is here for the
 * reason `app/web/src/lib/books.tsx` records: a response whose query has been
 * superseded must be DROPPED. Without it, a slow first page lands after the
 * user has typed a filter and repaints rows they already filtered away — and
 * in THIS app the same race across a library switch would show one library's
 * books under another's name, which is the worst bug a tenant-aware screen
 * can have.
 *
 * Deliberately not a query library: this console has a handful of independent
 * reads and no cache to invalidate. Revisit when two screens need to share
 * one record map, the same threshold `app/web` set for itself.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

export interface AsyncState<T> {
  data: T | undefined
  loading: boolean
  /** The error message, already unwrapped from the server's `detail`. */
  error: string | undefined
  /** Re-run the same request. Used by a Retry button and after a write. */
  reload: () => void
}

/**
 * Run `fn` whenever `deps` change, keeping only the newest answer.
 *
 * `fn` receives an `AbortSignal`: an in-flight request whose result is about
 * to be discarded is also cancelled, so a fast typist does not leave a dozen
 * fan-out requests running against the server.
 */
export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
): AsyncState<T> {
  const [data, setData] = useState<T | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>(undefined)
  const [nonce, setNonce] = useState(0)

  // The newest request wins. A plain counter is enough — this is one
  // component's own sequence, never shared.
  const seq = useRef(0)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    const id = ++seq.current
    const ctrl = new AbortController()
    setLoading(true)
    setError(undefined)
    fnRef.current(ctrl.signal).then(
      (result) => {
        if (id !== seq.current) return
        setData(result)
        setLoading(false)
      },
      (err: unknown) => {
        if (id !== seq.current) return
        // An abort is not a failure — it is this hook doing its job.
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      },
    )
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, loading, error, reload }
}
