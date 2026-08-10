/**
 * The one data-fetching primitive.
 *
 * ⚠ **The request-id guard is the load-bearing part.** A response whose query
 * has been superseded must be DROPPED — without it a slow first page lands
 * after the user has typed a filter and repaints rows they already filtered
 * away. In a tenant-aware screen the same race across a library switch shows
 * one library's books under another's name, which is the worst bug either of
 * these apps can have. `app/web/src/lib/books.tsx` carries its own copy of
 * this guard inside the books store (it also owns a record map and paging, so
 * it is more than this hook can be); the console had this one; the rule is now
 * written down once even though it is enforced in two places.
 *
 * Deliberately not a query library. Between them these apps have a handful of
 * independent reads and one cache; a library would mostly be API surface.
 * Revisit when a second screen needs to share one record map — the threshold
 * `app/web` already set for itself.
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
