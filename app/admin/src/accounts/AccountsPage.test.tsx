/**
 * The accounts screen — the console's customer list, and the two tabs it
 * replaced.
 */
import { screen, waitFor, within } from '@testing-library/react'
import { userEvent } from '@booksnap/ui/testing/user'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AccountsPage } from './AccountsPage'
import { makeAccount, makeLibrary, makeStaffLibrary, renderApp } from '../test/harness'
import { bothServices, DEFAULT_WORLD } from '../test/servers'

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('AccountsPage', () => {
  /**
   * ⚠⚠ The owner's list for a row: *"when it was created, who are the admins,
   * how many users, how many books, images storage"*. A person has no admins
   * and no users — that list describes a CUSTOMER, which is why the console's
   * "account" is the tenant.
   */
  it('reports each customer by admins, users, books and storage', async () => {
    bothServices()
    renderApp(<AccountsPage openId={undefined} />)

    const table = await screen.findByRole('table')
    const row = within(table).getByText('הבית').closest('tr')!
    // acc-1 admins lib-1; acc-2 is a viewer there.
    expect(within(row).getByText('משה')).toBeInTheDocument()
    expect(within(row).queryByText('שכן')).not.toBeInTheDocument()
    // users, books, images, storage — in that order, by column rather than by
    // value, since two of the figures legitimately read the same number.
    const cells = within(row).getAllByRole('cell').map((c) => c.textContent)
    expect(cells[2]).toBe('2')      // users
    expect(cells[3]).toBe('2')      // books
    expect(cells[4]).toBe('3')      // images
    expect(cells[5]).toMatch(/\d+ (B|KB|MB)/)  // storage, from the blob tree
  })

  it('lists every account in the system, not only the operator\'s own', async () => {
    bothServices()
    renderApp(<AccountsPage openId={undefined} />)

    expect(await screen.findByText('הבית')).toBeInTheDocument()
    expect(screen.getByText('ההורים')).toBeInTheDocument()
  })

  /** ⚠ Reading spans every tenant; writing does not. A row outside `mine`
   *  shows its numbers and says it is read-only rather than offering a button
   *  that would 404 on click. */
  it('offers rename and export only where the operator is a member', async () => {
    bothServices()
    renderApp(<AccountsPage openId={undefined} />)
    await screen.findByText('הבית')

    const mine = screen.getByText('הבית').closest('tr')!
    const theirs = screen.getByText('ההורים').closest('tr')!
    expect(within(mine).getByRole('button', { name: /שינוי שם|Rename/ }))
      .toBeInTheDocument()
    expect(within(theirs).queryByRole('button', { name: /שינוי שם|Rename/ }))
      .not.toBeInTheDocument()
    expect(within(theirs).getByText(/אינכם חברים|not a member/)).toBeInTheDocument()
  })

  /**
   * ⚠⚠ A person with no membership would otherwise be invisible: the Users tab
   * was the only screen that listed people directly, and a tenant-shaped list
   * cannot show somebody who belongs to no tenant. The mirror of the
   * orphan-library warning.
   */
  it('names the people who belong to no account at all', async () => {
    bothServices({
      accounts: [...DEFAULT_WORLD.accounts,
                 makeAccount({ id: 'acc-3', display_name: 'נשכח',
                               memberships: [] })],
    })
    renderApp(<AccountsPage openId={undefined} />)

    expect(await screen.findByText(/ללא שיוך|Unaffiliated/)).toBeInTheDocument()
    expect(screen.getByText('נשכח')).toBeInTheDocument()
  })

  it('says nothing about unaffiliated people when there are none', async () => {
    bothServices()
    renderApp(<AccountsPage openId={undefined} />)
    await screen.findByText('הבית')
    expect(screen.queryByText(/ללא שיוך|Unaffiliated/)).not.toBeInTheDocument()
  })

  /** ⚠ `new_library` mints an admin membership in the same call precisely so
   *  this cannot happen — a customer nobody can administer is the anomaly only
   *  a system console can surface. */
  it('flags an account with no administrator', async () => {
    bothServices({
      libraries: [makeStaffLibrary({ id: 'lib-9', label: 'יתומה', members: 0 })],
      accounts: [],
    })
    renderApp(<AccountsPage openId={undefined} />)

    expect(await screen.findByText(/אין מנהל|no admin/)).toBeInTheDocument()
  })

  it('creates an account and refreshes the system list', async () => {
    const s = bothServices()
    s.route('POST /api/v1/libraries', () => makeLibrary({ id: 'lib-3' }))
    const user = userEvent.setup()
    renderApp(<AccountsPage openId={undefined} />)
    await screen.findByText('הבית')

    await user.click(screen.getByRole('button', { name: /ספרייה חדשה|New library/ }))
    await user.type(screen.getByLabelText(/שם הספרייה|Library name/), 'חדשה')
    await user.click(screen.getByRole('button', { name: /^יצירה$|^Create$/ }))

    await waitFor(() => {
      expect(s.calls.filter((c) => c.method === 'POST')).toHaveLength(1)
      // The system list is refetched, not patched: the new row's figures come
      // from the staff service, which is the only thing that knows them.
      expect(s.calls.filter((c) => c.url === '/api/staff/v1/libraries').length)
        .toBeGreaterThan(1)
    })
  })

  it('offers no way to delete an account', async () => {
    bothServices()
    renderApp(<AccountsPage openId={undefined} />)
    await screen.findByText('הבית')

    expect(screen.queryByRole('button', { name: /מחיקה|Delete/ }))
      .not.toBeInTheDocument()
    expect(screen.getByText(/אין מחיקת ספרייה|No library delete/i))
      .toBeInTheDocument()
  })

  /**
   * ⚠ The drawer's three sections are the owner's own shape: *"users section,
   * books section, images section"*.
   */
  it('opens one account in a drawer with users, books and images', async () => {
    bothServices()
    renderApp(<AccountsPage openId="lib-1" />)

    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByRole('heading', { name: /משתמשים|Users/ }))
      .toBeInTheDocument()
    expect(within(panel).getByRole('heading', { name: /^ספרים$|^Books$/ }))
      .toBeInTheDocument()
    expect(within(panel).getByRole('heading', { name: /^תמונות$|^Images$/ }))
      .toBeInTheDocument()
    // The list is still behind it — that is what makes it a drawer.
    expect(screen.getByText('ההורים')).toBeInTheDocument()
  })

  /** ⚠ The console renamed the tenant and the storage did not. Showing the
   *  library id, labelled, is what keeps that a naming choice rather than a
   *  lie. */
  it('shows the library id behind the account, named as such', async () => {
    bothServices()
    renderApp(<AccountsPage openId="lib-1" />)

    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByText(/מזהה ספרייה|Library id/)).toBeInTheDocument()
    expect(within(panel).getByText('lib-1')).toBeInTheDocument()
  })

  /**
   * ⚠ Reported, not profiled. The drawer shows identity, role and join date —
   * never a per-person feed of what somebody has been photographing at home.
   * And there is no invite/remove/re-role control, because there is no route
   * for one in either service.
   */
  it('reports membership without offering to change it, and without activity',
     async () => {
    bothServices()
    renderApp(<AccountsPage openId="lib-1" />)
    const panel = await screen.findByRole('dialog')

    expect(within(panel).getByText('acc-2')).toBeInTheDocument()
    expect(within(panel).getByText('viewer')).toBeInTheDocument()
    for (const name of [/הזמנה|Invite/, /הסרה|Remove/, /שינוי תפקיד|Change role/]) {
      expect(within(panel).queryByRole('button', { name })).not.toBeInTheDocument()
    }
    expect(within(panel).getByText(/מחכים להתחברות|wait on the login/))
      .toBeInTheDocument()
  })
})
