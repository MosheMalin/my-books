/**
 * Hash routing, hand-rolled — the same call `app/web/src/lib/route.ts` makes,
 * and for the same reason: four screens do not earn a router dependency, and
 * a hash route needs no server rewrite rule, which matters for an app served
 * by `vite preview` with nothing in front of it.
 *
 * Routes:
 *   #/                      the dashboard
 *   #/accounts              every account (tenant) in the system
 *   #/accounts/<id>         …with one open in a drawer over the list
 *   #/books                 every book in the system
 *   #/books?library=<id>    …narrowed to one (a deep link from a library row)
 *   #/access                the staff credential, the two admin jobs, the gaps
 *
 * ⚠ `#/libraries`, `#/libraries/<id>` and `#/users` are RETIRED and still
 * parse, landing on the accounts screen. Revision 4 merged those two tabs into
 * one — they were two names for one entity — and a console that answered a
 * bookmark with the dashboard would teach the operator that their link rotted
 * rather than moved.
 */
// The `hashchange` subscription is shared (`@booksnap/ui`); the ROUTE TABLE
// below is deliberately not — a union of both apps' routes would let one link
// to a screen it does not have.
import { navigateHash, useHash } from '@booksnap/ui'

export type Route =
  | { name: 'dashboard' }
  | { name: 'accounts' }
  | { name: 'account'; id: string }
  | { name: 'books'; libraryId: string | undefined }
  | { name: 'images'; libraryId: string | undefined }
  | { name: 'access' }

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '')
  const [path = '', queryString = ''] = raw.split('?')
  const query = new URLSearchParams(queryString)
  const parts = path.split('/').filter(Boolean)

  // `libraries` is the retired spelling of `accounts` — see the module note.
  if (parts[0] === 'accounts' || parts[0] === 'libraries') {
    // An id is opaque and may contain anything the generator emits, so it is
    // decoded rather than pattern-matched.
    return parts[1]
      ? { name: 'account', id: decodeURIComponent(parts[1]) }
      : { name: 'accounts' }
  }
  // …and `users` is the retired tab whose contents are now a section inside
  // an account. It lands on the list rather than on the dashboard.
  if (parts[0] === 'users') return { name: 'accounts' }
  if (parts[0] === 'books') {
    return { name: 'books', libraryId: query.get('library') ?? undefined }
  }
  if (parts[0] === 'images') {
    return { name: 'images', libraryId: query.get('library') ?? undefined }
  }
  if (parts[0] === 'access') return { name: 'access' }
  return { name: 'dashboard' }
}

export const href = (route: Route): string => {
  switch (route.name) {
    case 'dashboard': return '#/'
    case 'accounts': return '#/accounts'
    case 'account': return `#/accounts/${encodeURIComponent(route.id)}`
    case 'books':
      return route.libraryId
        ? `#/books?library=${encodeURIComponent(route.libraryId)}`
        : '#/books'
    case 'images':
      return route.libraryId
        ? `#/images?library=${encodeURIComponent(route.libraryId)}`
        : '#/images'
    case 'access': return '#/access'
  }
}

export function navigate(route: Route): void {
  navigateHash(href(route))
}

export function useRoute(): Route {
  return parseHash(useHash())
}
