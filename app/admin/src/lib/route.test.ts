import { describe, expect, it } from 'vitest'

import { href, parseHash } from './route'

describe('parseHash', () => {
  it('defaults to the dashboard, including for an empty or unknown hash', () => {
    expect(parseHash('')).toEqual({ name: 'dashboard' })
    expect(parseHash('#/')).toEqual({ name: 'dashboard' })
    expect(parseHash('#/nonsense')).toEqual({ name: 'dashboard' })
  })

  it('reads the account list and one account', () => {
    expect(parseHash('#/accounts')).toEqual({ name: 'accounts' })
    expect(parseHash('#/accounts/lib-1')).toEqual({ name: 'account', id: 'lib-1' })
  })

  /**
   * ⚠⚠ The retired spellings still land somewhere sensible. Revision 4 merged
   * the Libraries and Users tabs — two names for one entity — and a bookmark
   * that answered with the dashboard would teach the operator that their link
   * ROTTED rather than moved.
   */
  it('lands the retired library and user routes on the accounts screen', () => {
    expect(parseHash('#/libraries')).toEqual({ name: 'accounts' })
    expect(parseHash('#/libraries/lib-1')).toEqual({ name: 'account', id: 'lib-1' })
    expect(parseHash('#/users')).toEqual({ name: 'accounts' })
  })

  /**
   * ⚠ A library id is opaque — whatever the id generator emits — so it is
   * decoded, not pattern-matched. An id containing a `%` or a slash would
   * otherwise open the wrong library, or none.
   */
  it('decodes an account id', () => {
    expect(parseHash(`#/accounts/${encodeURIComponent('lib/one')}`))
      .toEqual({ name: 'account', id: 'lib/one' })
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

  /** The images screen narrows the same way the books screen does, and for
   *  the same reason — a shared link must land on the same view. */
  it('carries the images screen narrowing', () => {
    expect(parseHash('#/images')).toEqual({ name: 'images', libraryId: undefined })
    expect(parseHash('#/images?library=lib-2'))
      .toEqual({ name: 'images', libraryId: 'lib-2' })
  })

  it('round-trips every route through href', () => {
    for (const route of [
      { name: 'dashboard' },
      { name: 'accounts' },
      { name: 'account', id: 'lib/one' },
      { name: 'books', libraryId: undefined },
      { name: 'books', libraryId: 'lib-2' },
      { name: 'images', libraryId: undefined },
      { name: 'images', libraryId: 'lib-2' },
      { name: 'access' },
    ] as const) {
      expect(parseHash(href(route))).toEqual(route)
    }
  })
})
