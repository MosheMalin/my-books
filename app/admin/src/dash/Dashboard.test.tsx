import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Dashboard } from './Dashboard'
import { renderApp } from '../test/harness'
import { bothServices, DEFAULT_WORLD } from '../test/servers'
import { makeOverview } from '../test/harness'

/** The number on one stat card. Scoped, because several cards legitimately
 *  show the same figure and the column headers repeat their labels. */
const statValue = (label: RegExp): string => {
  const stats = document.querySelector('.stats') as HTMLElement
  const card = within(stats).getByText(label).closest('.stat') as HTMLElement
  return within(card).getByText(/\d/).textContent ?? ''
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('Dashboard', () => {
  /**
   * ⚠⚠ The change that makes this a SYSTEM console rather than an account
   * one. The figures come from a cross-tenant service in one request; the
   * earlier version added up only the libraries the operator belonged to and
   * called the result "the system", which was true for exactly one account.
   */
  it('reports system totals from the staff service, not a per-library fan-out', async () => {
    const s = bothServices()
    renderApp(<Dashboard />)

    await screen.findByText(/סקירת המערכת|System overview/)
    expect(statValue(/^ספרים$|^Books$/)).toBe('4')
    expect(statValue(/^חשבונות$|^Accounts$/)).toBe('2')

    // Not one books request per library — the shape it replaced.
    expect(s.calls.filter((c) => c.url.startsWith('/api/v1/books'))).toHaveLength(0)
    expect(s.calls.filter((c) => c.url.startsWith('/api/staff/v1/overview')))
      .toHaveLength(1)
  })

  /**
   * ⚠⚠ **The tile read `overview.libraries` until P3.7e.** It was a count of
   * COLLECTIONS under a heading saying "accounts", which was true only while a
   * library WAS the tenant; P3.7b made the Account its own record, and the
   * owner's real database — one customer, two libraries — is precisely the
   * case that makes the two numbers differ.
   *
   * ⚠ The fixture keeps accounts (2), people (4) and libraries (3) PAIRWISE
   * unequal. The first version had accounts and people BOTH at 2, and a
   * review measured what that hid: swapping the tile to `overview.users`
   * passed the entire ring. A comment claiming the numbers are all different
   * is not the same as their being all different.
   */
  it('counts customers, people and collections as three different numbers', async () => {
    bothServices()
    renderApp(<Dashboard />)
    await screen.findByText(/סקירת המערכת|System overview/)

    expect(statValue(/^חשבונות$|^Accounts$/)).toBe('2')
    expect(statValue(/^אנשים$|^People$/)).toBe('4')
    expect(statValue(/^ספריות$|^Libraries$/)).toBe('3')
  })

  it('counts accounts and memberships, which no product route can answer', async () => {
    bothServices()
    renderApp(<Dashboard />)
    await screen.findByText(/סקירת המערכת|System overview/)

    for (const label of [/חשבונות|Accounts/, /חברויות|Memberships/]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  /**
   * ⚠ §5.1's ladder is `auto < approved < manual`, and `manual` OUTRANKS
   * approved — a hand-typed book is vouched for by the act of typing it. So
   * "awaiting approval" is the `auto` count and NOTHING else.
   */
  it('counts only auto records as awaiting approval', async () => {
    bothServices({
      overview: makeOverview({ books: 10, auto: 2, approved: 5, manual: 3 }),
    })
    renderApp(<Dashboard />)

    await screen.findByText(/סקירת המערכת|System overview/)
    expect(statValue(/ממתינים לאישור|Awaiting approval/)).toBe('2')
  })

  /**
   * ⚠⚠ Rows by CUSTOMER, which is what the "by account" heading always
   * claimed and what the table only started doing at P3.7e. `משפחת מלין` owns
   * two collections whose books sum to three; listing libraries would show it
   * as two separate rows of two and one — two customers where there is one.
   */
  it('rows by customer, with the collections each one keeps', async () => {
    bothServices()
    renderApp(<Dashboard />)

    const home = await screen.findByRole('link', { name: 'משפחת מלין' })
    const cells = within(home.closest('tr') as HTMLElement)
      .getAllByRole('cell').map((c) => c.textContent)
    // account, users, libraries, books, unapproved…
    expect(cells.slice(1, 5)).toEqual(['2', '2', '3', '1'])
    expect(screen.getByRole('link', { name: 'משפחת כהן' })).toBeInTheDocument()
    // The libraries themselves are a level down, in the drawer — not rows here.
    expect(screen.queryByRole('link', { name: 'הבית' })).not.toBeInTheDocument()
  })

  /**
   * ⚠ A library whose OWNING ACCOUNT has no member is one nobody can see or
   * administer — `new_account` mints an admin membership in the same call
   * precisely so this cannot happen, and `NoAdminLeft` keeps it so. A system
   * console is the only place it is visible at all, so it must not be a silent
   * zero in a column.
   */
  it('warns when a library\'s owning account has no members', async () => {
    bothServices({
      overview: makeOverview({ ...DEFAULT_WORLD.overview,
                               orphan_libraries: ['lib-lost'] }),
    })
    renderApp(<Dashboard />)
    expect(await screen.findByText(/אין אף חבר|no member at all/))
      .toBeInTheDocument()
  })

  /**
   * ⚠⚠ The product's "no login until pillar 4" trade does NOT extend to a
   * cross-tenant surface. A staff service running with no token means anyone
   * on the LAN reads every household's data, and an operator must be told
   * that rather than discover it.
   */
  it('warns loudly when the staff service has no token configured', async () => {
    bothServices({ overview: makeOverview({ authenticated: false }) })
    renderApp(<Dashboard />)
    expect(await screen.findByText(/BOOKSNAP_STAFF_TOKEN/)).toBeInTheDocument()
  })

  it('says nothing about the token when one is configured', async () => {
    bothServices()
    renderApp(<Dashboard />)
    await screen.findByText(/סקירת המערכת|System overview/)
    expect(screen.queryByText(/BOOKSNAP_STAFF_TOKEN/)).not.toBeInTheDocument()
  })
})
