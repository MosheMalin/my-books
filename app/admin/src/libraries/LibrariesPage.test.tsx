import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { LibrariesPage } from './LibrariesPage'
import { makeLibrary, renderApp } from '../test/harness'
import { bothServices } from '../test/servers'

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('LibrariesPage', () => {
  it('lists every library in the system, not only the operator\'s own', async () => {
    bothServices()
    renderApp(<LibrariesPage />)

    expect(await screen.findByRole('link', { name: 'הבית' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ההורים' })).toBeInTheDocument()
  })

  /**
   * ⚠⚠ The console's central asymmetry. The list spans every tenant; *rename*
   * and the exports go through the product API, which resolves the operator's
   * own membership and 404s for anything else. A row outside `mine` therefore
   * gets no controls and says why — offering them would be offering a click
   * that fails.
   */
  it('offers rename and export only where the operator is a member', async () => {
    bothServices()
    renderApp(<LibrariesPage />)

    const own = (await screen.findByRole('link', { name: 'הבית' }))
      .closest('tr') as HTMLElement
    expect(within(own).getByRole('button', { name: /שינוי שם|Rename/ }))
      .toBeInTheDocument()
    expect(within(own).getByRole('link', { name: 'CSV' })).toBeInTheDocument()

    const other = (screen.getByRole('link', { name: 'ההורים' }))
      .closest('tr') as HTMLElement
    expect(within(other).queryByRole('button', { name: /שינוי שם|Rename/ }))
      .not.toBeInTheDocument()
    expect(within(other).queryByRole('link', { name: 'CSV' })).not.toBeInTheDocument()
    expect(within(other).getByText(/אינכם חברים|not a member/)).toBeInTheDocument()
  })

  /**
   * ⚠⚠ An export is a download, so the BROWSER issues the request — and a
   * browser-issued request cannot carry `X-Booksnap-Library`. The reference
   * has to be in the query string or the file comes back from whichever
   * library the caller defaults to. This shipped broken in the product for an
   * afternoon; it is the one URL-building rule worth its own test.
   */
  it('puts the library in the query string of every export link', async () => {
    bothServices()
    renderApp(<LibrariesPage />)
    await screen.findByRole('link', { name: 'הבית' })

    for (const name of ['CSV', 'JSON']) {
      expect(screen.getByRole('link', { name })).toHaveAttribute(
        'href', expect.stringContaining('library=lib-1') as unknown as string,
      )
    }
  })

  it('creates a library and refreshes the system list', async () => {
    const s = bothServices()
    const user = userEvent.setup()
    renderApp(<LibrariesPage />)
    await screen.findByRole('link', { name: 'הבית' })

    s.route('POST /api/v1/libraries', (req) =>
      makeLibrary({ id: 'lib-new', label: (req.body as { label: string }).label }))

    await user.click(screen.getByRole('button', { name: /ספרייה חדשה|New library/ }))
    await user.type(screen.getByLabelText(/שם הספרייה|Library name/), 'חדשה')
    await user.click(screen.getByRole('button', { name: /^יצירה$|^Create$/ }))

    await vi.waitFor(() => {
      expect(s.calls.filter((c) => c.method === 'POST'
                                && c.url === '/api/v1/libraries')).toHaveLength(1)
    })
  })

  /**
   * ⚠ Stated on the form, because it is the one thing about it that is NOT
   * obvious on a system console: `POST /api/v1/libraries` creates the library
   * under the CALLER's account. There is no route that creates one for
   * somebody else, and an operator who assumed otherwise would quietly
   * accumulate libraries in their own name.
   */
  it('says that a new library lands under the operator\'s own account', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<LibrariesPage />)
    await screen.findByRole('link', { name: 'הבית' })

    await user.click(screen.getByRole('button', { name: /ספרייה חדשה|New library/ }))
    expect(screen.getByText(/תחת החשבון שלכם|under YOUR account/)).toBeInTheDocument()
  })

  /**
   * ⚠ A refusal must not clear the form. A form that emptied itself would
   * make the operator retype what they had, which reads as the app losing
   * their input rather than the server declining it.
   */
  it('keeps the form and its text when creation is refused', async () => {
    const s = bothServices()
    const user = userEvent.setup()
    s.route('POST /api/v1/libraries', () =>
      new Response(JSON.stringify({ detail: 'a library must have a name' }),
                   { status: 400 }))

    renderApp(<LibrariesPage />)
    await screen.findByRole('link', { name: 'הבית' })
    await user.click(screen.getByRole('button', { name: /ספרייה חדשה|New library/ }))
    await user.type(screen.getByLabelText(/שם הספרייה|Library name/), 'שם')
    await user.click(screen.getByRole('button', { name: /^יצירה$|^Create$/ }))

    expect(await screen.findByText(/must have a name/)).toBeInTheDocument()
    expect(screen.getByLabelText(/שם הספרייה|Library name/)).toHaveValue('שם')
  })

  /**
   * ⚠ No delete, in either service, and the screen SAYS so. It would mean a
   * cascade across six aggregates plus a blob purge (P3.2/P3.5). A disabled
   * control would read as a bug; a sentence reads as a product that has not
   * grown that far.
   */
  it('offers no way to delete a library', async () => {
    bothServices()
    renderApp(<LibrariesPage />)
    await screen.findByRole('link', { name: 'הבית' })

    expect(screen.queryByRole('button', { name: /^מחיק|^Delete/ })).not.toBeInTheDocument()
    expect(screen.getByText(/אין מחיקת ספרייה|No library deletion/)).toBeInTheDocument()
  })
})
