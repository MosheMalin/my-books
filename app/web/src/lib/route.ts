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
  | { name: 'plan'; focus: string | null }
  | { name: 'login'; token: string | null }
  | { name: 'invite'; token: string | null }

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#\/?/, '').split('?')[0] ?? ''
  const [head, arg] = path.split('/')
  if (head === 'book' && arg) return { name: 'book', id: decodeURIComponent(arg) }
  if (head === 'capture') return { name: 'capture' }
  // ⚠ Before the `map/<id>` line below, which is the SHELF detail screen and
  // has carried that prefix since P2.8. `#/plan` is the drawing; a bare
  // `#/map` would read as the same thing as `#/map/<shelf>` and is not.
  //
  // `#/plan/<shelfId>` opens the drawing POINTING AT that shelf — the storey
  // it stands on, its bookcase selected, its cell selected. UI_PLAN §3 asks
  // for the drill in one direction (`#/map/<shelfId>` "deep-links straight to
  // level 3 with the right place, case and elevation already open"); this is
  // the same journey the other way, and it is the one an address needs.
  // On the owner's library every bookcase is unnamed, so *סלון · כוננית
  // ללא שם · עמודה 2* cannot discriminate between two cases in one
  // room, and pointing at it on the drawing is the only thing that can.
  if (head === 'plan')
    return { name: 'plan', focus: arg ? decodeURIComponent(arg) : null }
  if (head === 'map' && arg) return { name: 'shelf', id: decodeURIComponent(arg) }
  if (head === 'login' || head === 'invite') {
    // The two routes that read their query: an emailed sign-in link and a
    // shared invite link both land carrying a token, and the general rule
    // of stripping `?` is exactly what would eat it.
    const query = hash.split('?')[1] ?? ''
    return { name: head, token: new URLSearchParams(query).get('token') }
  }
  return { name: 'library' }
}

export function bookHash(id: string): string {
  return `#/book/${encodeURIComponent(id)}`
}

export function shelfHash(id: string): string {
  return `#/map/${encodeURIComponent(id)}`
}

/** The drawing, optionally pointing at one shelf. */
export function planHash(shelfId?: string): string {
  return shelfId ? `#/plan/${encodeURIComponent(shelfId)}` : PLAN_HASH
}

export const LIBRARY_HASH = '#/library'
export const CAPTURE_HASH = '#/capture'
export const PLAN_HASH = '#/plan'

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
