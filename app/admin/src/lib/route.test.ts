import { describe, expect, it } from 'vitest'

import { href, parseHash } from './route'

describe('parseHash', () => {
  it('defaults to the dashboard, including for an empty or unknown hash', () => {
    expect(parseHash('')).toEqual({ name: 'dashboard' })
    expect(parseHash('#/')).toEqual({ name: 'dashboard' })
    expect(parseHash('#/nonsense')).toEqual({ name: 'dashboard' })
  })

  it('reads the library list and one library', () => {
    expect(parseHash('#/libraries')).toEqual({ name: 'libraries' })
    expect(parseHash('#/libraries/lib-1')).toEqual({ name: 'library', id: 'lib-1' })
  })

  /**
   * ⚠ A library id is opaque — whatever the id generator emits — so it is
   * decoded, not pattern-matched. An id containing a `%` or a slash would
   * otherwise open the wrong library, or none.
   */
  it('decodes a library id', () => {
    expect(parseHash(`#/libraries/${encodeURIComponent('lib/one')}`))
      .toEqual({ name: 'library', id: 'lib/one' })
  })

  /**
   * ⚠ The books screen carries its narrowing in the ROUTE, so a reload or a
   * shared link lands on the same view. Without it, picking a library and
   * refreshing silently widens back to every library — and the rows would
   * then be a different set under the same heading.
   */
  it('carries the books screen narrowing', () => {
    expect(parseHash('#/books')).toEqual({ name: 'books', libraryId: undefined })
    expect(parseHash('#/books?library=lib-2'))
      .toEqual({ name: 'books', libraryId: 'lib-2' })
  })

  it('reads the users screen', () => {
    expect(parseHash('#/users')).toEqual({ name: 'users' })
  })

  it('round-trips every route through href', () => {
    for (const route of [
      { name: 'dashboard' },
      { name: 'libraries' },
      { name: 'library', id: 'lib/one' },
      { name: 'books', libraryId: undefined },
      { name: 'books', libraryId: 'lib-2' },
      { name: 'users' },
      { name: 'access' },
    ] as const) {
      expect(parseHash(href(route))).toEqual(route)
    }
  })
})
