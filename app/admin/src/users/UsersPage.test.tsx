import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { UsersPage } from './UsersPage'
import { AccessPage } from '../access/AccessPage'
import { renderApp } from '../test/harness'
import { bothServices } from '../test/servers'

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('UsersPage', () => {
  /**
   * ⚠⚠ The screen that has no equivalent in `/api/v1` and could not have one:
   * the product API answers "which libraries may **I** name", never "who is in
   * the system". Its existence is the clearest demonstration of why a system
   * administrator is a separate service rather than a bigger role.
   */
  it('lists every account, not only the operator\'s own', async () => {
    bothServices()
    renderApp(<UsersPage />)

    expect(await screen.findByText('משה')).toBeInTheDocument()
    expect(screen.getByText('שכן')).toBeInTheDocument()
  })

  it('shows each account\'s memberships with the role held in each', async () => {
    bothServices()
    renderApp(<UsersPage />)

    const row = (await screen.findByText('שכן')).closest('tr') as HTMLElement
    expect(within(row).getByText('admin')).toBeInTheDocument()
    expect(within(row).getByText('viewer')).toBeInTheDocument()
    expect(within(row).getByText('ההורים')).toBeInTheDocument()
  })

  /**
   * ⚠⚠ Member management is SKIPPED because no endpoint exists in either
   * service — and skipped means ABSENT, not disabled. This test is how "we
   * chose not to fake it" stays true: a dead invite button added later fails
   * here, and whoever adds a live one has to delete this test, which is where
   * the reason is written down.
   */
  it('has no invite, remove or role-editing control', async () => {
    bothServices()
    renderApp(<UsersPage />)
    await screen.findByText('משה')

    expect(screen.queryByRole('button', { name: /הזמנ|invite/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /הסר|remove/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  /**
   * ⚠ Identity and membership, deliberately NOT activity. "Statistics about
   * the users" is a fair thing to want; a per-person feed of what someone has
   * been photographing and reading in their own home is a different and much
   * larger power, and this product has no login, audit trail or consent story
   * to justify it. Aggregate figures live on the library rows instead.
   */
  it('reports no per-person reading or capture activity', async () => {
    bothServices()
    renderApp(<UsersPage />)
    await screen.findByText('משה')

    const row = (screen.getByText('משה')).closest('tr') as HTMLElement
    expect(within(row).queryByText(/קריאות|reads/i)).not.toBeInTheDocument()
    expect(within(row).queryByText(/תצלומים|photos/i)).not.toBeInTheDocument()
  })

  it('names the two admin jobs so they are not confused', async () => {
    bothServices()
    renderApp(<UsersPage />)
    expect(await screen.findByText(/מנהל המערכת|SYSTEM admin/)).toBeInTheDocument()
  })
})

describe('AccessPage', () => {
  it('separates the system admin from the account admin', async () => {
    bothServices()
    renderApp(<AccessPage />)
    expect(await screen.findByText(/מנהל המערכת|SYSTEM admin/)).toBeInTheDocument()
  })

  it('lists only the operator\'s own memberships, which is what they may write to',
     async () => {
    bothServices()
    renderApp(<AccessPage />)

    // `mine` is lib-1 alone in the default world, even though the operator can
    // SEE both libraries. Conflating the two is what would produce buttons
    // that 404.
    const table = await screen.findByRole('table')
    expect(within(table).getByText('הבית')).toBeInTheDocument()
    expect(within(table).queryByText('ההורים')).not.toBeInTheDocument()
  })

  it('names the gaps that still need backend work', async () => {
    bothServices()
    renderApp(<AccessPage />)
    // P4.1 is named by more than one gap — the login blocks both the invite
    // and the account being able to sign in at all.
    expect((await screen.findAllByText(/P4\.1/)).length).toBeGreaterThan(0)
    expect((await screen.findAllByText(/P3\.2/)).length).toBeGreaterThan(0)
  })
})
