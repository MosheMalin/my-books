/**
 * A hash router, because that is what `#/book/<id>` in UI_PLAN §5 asks for and
 * because a hash route needs no server rewrite rule — FastAPI serves one
 * index.html and the client does the rest.
 *
 * Three routes today:
 *   #/library            the Books tab
 *   #/book/<id>          the book surface, promoted to a full page
 *   #/capture            the Capture tab (P2.7)
 *
 * The book DRAWER is deliberately not a route. It is an overlay on top of an
 * untouched list (§5), so putting it in the URL would make Back close it
 * instead of leaving the tab — and would lose the list's scroll position on
 * every open. ⤢ promotes the drawer to the route; that transition is the
 * deep-linkable one.
 */
import { useCallback, useEffect, useState } from 'react'

export type Route =
  | { name: 'library' }
  | { name: 'book'; id: string }
  | { name: 'capture' }

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#\/?/, '').split('?')[0] ?? ''
  const [head, arg] = path.split('/')
  if (head === 'book' && arg) return { name: 'book', id: decodeURIComponent(arg) }
  if (head === 'capture') return { name: 'capture' }
  return { name: 'library' }
}

export function bookHash(id: string): string {
  return `#/book/${encodeURIComponent(id)}`
}

export const LIBRARY_HASH = '#/library'
export const CAPTURE_HASH = '#/capture'

export function useRoute(): {
  route: Route
  navigate: (hash: string) => void
  back: () => void
} {
  const [hash, setHash] = useState(() => globalThis.location?.hash || LIBRARY_HASH)

  useEffect(() => {
    const onChange = () => setHash(globalThis.location.hash || LIBRARY_HASH)
    globalThis.addEventListener('hashchange', onChange)
    return () => globalThis.removeEventListener('hashchange', onChange)
  }, [])

  const navigate = useCallback((next: string) => {
    if (globalThis.location.hash === next) return
    globalThis.location.hash = next
  }, [])

  // history.back() rather than navigating to #/library, so returning from a
  // book restores the list's scroll position instead of jumping to the top.
  // Falls back for a deep link opened directly, where there is nothing to go
  // back to.
  const back = useCallback(() => {
    if (globalThis.history.length > 1) globalThis.history.back()
    else globalThis.location.hash = LIBRARY_HASH
  }, [])

  return { route: parseHash(hash), navigate, back }
}
