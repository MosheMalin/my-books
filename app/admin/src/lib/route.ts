/**
 * Hash routing, hand-rolled — the same call `app/web/src/lib/route.ts` makes,
 * and for the same reason: four screens do not earn a router dependency, and
 * a hash route needs no server rewrite rule, which matters for an app served
 * by `vite preview` with nothing in front of it.
 *
 * Routes:
 *   #/                      the dashboard
 *   #/libraries             every library this account belongs to
 *   #/libraries/<id>        one library: shelves, reads, open questions
 *   #/books                 every book in the system
 *   #/books?library=<id>    …narrowed to one (a deep link from a library row)
 *   #/users                 every account in the system, and what it may reach
 *   #/access                the staff credential, the two admin jobs, the gaps
 */
// The `hashchange` subscription is shared (`@booksnap/ui`); the ROUTE TABLE
// below is deliberately not — a union of both apps' routes would let one link
// to a screen it does not have.
import { navigateHash, useHash } from '@booksnap/ui'

export type Route =
  | { name: 'dashboard' }
  | { name: 'libraries' }
  | { name: 'library'; id: string }
  | { name: 'books'; libraryId: string | undefined }
  | { name: 'images'; libraryId: string | undefined }
  | { name: 'users' }
  | { name: 'access' }

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '')
  const [path = '', queryString = ''] = raw.split('?')
  const query = new URLSearchParams(queryString)
  const parts = path.split('/').filter(Boolean)

  if (parts[0] === 'libraries') {
    // A library id is opaque and may contain anything the id generator emits,
    // so it is decoded rather than pattern-matched.
    return parts[1]
      ? { name: 'library', id: decodeURIComponent(parts[1]) }
      : { name: 'libraries' }
  }
  if (parts[0] === 'books') {
    return { name: 'books', libraryId: query.get('library') ?? undefined }
  }
  if (parts[0] === 'images') {
    return { name: 'images', libraryId: query.get('library') ?? undefined }
  }
  if (parts[0] === 'users') return { name: 'users' }
  if (parts[0] === 'access') return { name: 'access' }
  return { name: 'dashboard' }
}

export const href = (route: Route): string => {
  switch (route.name) {
    case 'dashboard': return '#/'
    case 'libraries': return '#/libraries'
    case 'library': return `#/libraries/${encodeURIComponent(route.id)}`
    case 'books':
      return route.libraryId
        ? `#/books?library=${encodeURIComponent(route.libraryId)}`
        : '#/books'
    case 'images':
      return route.libraryId
        ? `#/images?library=${encodeURIComponent(route.libraryId)}`
        : '#/images'
    case 'users': return '#/users'
    case 'access': return '#/access'
  }
}

export function navigate(route: Route): void {
  navigateHash(href(route))
}

export function useRoute(): Route {
  return parseHash(useHash())
}
