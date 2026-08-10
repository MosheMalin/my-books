/**
 * A hash router, because that is what `#/book/<id>` in UI_PLAN §5 asks for and
 * because a hash route needs no server rewrite rule — FastAPI serves one
 * index.html and the client does the rest.
 *
 * Four routes today:
 *   #/library            the Books tab
 *   #/book/<id>          the book surface, promoted to a full page
 *   #/capture            the Capture tab (P2.7)
 *   #/map/<shelfId>       the shelf-detail screen (P2.8)
 *
 * `#/map/<shelfId>` is UI_PLAN §3's OWN deep-link shape ("`#/map/<shelfId>`
 * deep-links straight to level 3 with the right place, case and elevation
 * already open"), reused here even though the Map tab's levels 1/2 do not
 * exist yet (pillar 6) — the shelf detail this route opens IS "level 3", so
 * when the map arrives it gains levels 1-2 as a way IN to this same screen
 * rather than a second shelf-detail surface. Reachable today from the
 * Capture tab's *"open the shelf →"* chip and by direct URL, same as
 * `#/book/<id>` before the Books tab existed to link to it.
 *
 * The book DRAWER is deliberately not a route. It is an overlay on top of an
 * untouched list (§5), so putting it in the URL would make Back close it
 * instead of leaving the tab — and would lose the list's scroll position on
 * every open. ⤢ promotes the drawer to the route; that transition is the
 * deep-linkable one.
 */
import { useCallback } from 'react'

// The `hashchange` subscription itself is shared (`@booksnap/ui`); the ROUTE
// TABLE below is not, and deliberately: a union of both apps' routes would let
// one link to a screen it does not have.
import { backOr, navigateHash, useHash } from '@booksnap/ui'

export type Route =
  | { name: 'library' }
  | { name: 'book'; id: string }
  | { name: 'capture' }
  | { name: 'shelf'; id: string }

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#\/?/, '').split('?')[0] ?? ''
  const [head, arg] = path.split('/')
  if (head === 'book' && arg) return { name: 'book', id: decodeURIComponent(arg) }
  if (head === 'capture') return { name: 'capture' }
  if (head === 'map' && arg) return { name: 'shelf', id: decodeURIComponent(arg) }
  return { name: 'library' }
}

export function bookHash(id: string): string {
  return `#/book/${encodeURIComponent(id)}`
}

export function shelfHash(id: string): string {
  return `#/map/${encodeURIComponent(id)}`
}

export const LIBRARY_HASH = '#/library'
export const CAPTURE_HASH = '#/capture'

export function useRoute(): {
  route: Route
  navigate: (hash: string) => void
  back: () => void
} {
  const hash = useHash()
  const navigate = useCallback((next: string) => navigateHash(next), [])
  // history.back() rather than navigating to #/library, so returning from a
  // book restores the list's scroll position instead of jumping to the top.
  // Falls back for a deep link opened directly, where there is nothing to go
  // back to.
  const back = useCallback(() => backOr(LIBRARY_HASH), [])

  return { route: parseHash(hash || LIBRARY_HASH), navigate, back }
}
