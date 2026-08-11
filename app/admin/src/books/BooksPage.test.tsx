/**
 * The cross-tenant book CATALOGUE — one row per work — and the read/write
 * asymmetry only a rendered screen can catch.
 */
import { screen, waitFor, within } from '@testing-library/react'
import { userEvent } from '@booksnap/ui/testing/user'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BooksPage } from './BooksPage'
import { renderApp } from '../test/harness'
import { bothServices } from '../test/servers'

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('BooksPage', () => {
  /**
   * ⚠⚠ One row per WORK, from one request. The screen used to list
   * `(library, book)` pairs, which made a system-wide book list a
   * concatenation of household lists — it answered "whose is it", a question
   * an operator never asks.
   */
  it('lists one row per book across every tenant, with no library column', async () => {
    const s = bothServices()
    renderApp(<BooksPage initialLibraryId={undefined} />)

    expect(await screen.findByText('אבא')).toBeInTheDocument()
    const table = screen.getByRole('table')
    // The two households that hold 'אבא' are ONE row here…
    expect(within(table).getAllByText('אבא')).toHaveLength(1)
    // …and neither library's name appears in the table at all.
    expect(within(table).queryByText('הבית')).not.toBeInTheDocument()
    expect(within(table).queryByText('ההורים')).not.toBeInTheDocument()

    expect(s.calls.filter((c) => c.url.startsWith('/api/staff/v1/works')))
      .toHaveLength(1)
    expect(s.calls.filter((c) => c.url.startsWith('/api/v1/books'))).toHaveLength(0)
  })

  /** The owner's own sketch: the spread is a number, and the number is the
   *  link that opens the list behind it. */
  it('shows how many libraries hold a work, as a control that opens the list', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    await user.click(screen.getByRole('button', { name: /2 הספריות|2 libraries/ }))
    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByText('הבית')).toBeInTheDocument()
    expect(within(panel).getByText('ההורים')).toBeInTheDocument()
  })

  /**
   * ⚠⚠ A filter SELECTS works; it must not change what one reports. If
   * narrowing to lib-2 made 'אבא' read "in 1 library", the console's central
   * column would be a number that changes meaning when you filter.
   */
  it('keeps a work\'s spread honest while the list is narrowed to one library', async () => {
    const s = bothServices()
    renderApp(<BooksPage initialLibraryId="lib-2" />)

    await screen.findByText('אבא')
    expect(screen.queryByText('בבא')).not.toBeInTheDocument()
    expect(s.calls.some((c) => c.url.includes('library_id=lib-2'))).toBe(true)
    // Still two, though only one of them is in view.
    expect(screen.getByRole('button', { name: /2 הספריות|2 libraries/ }))
      .toBeInTheDocument()
  })

  /** ⚠ A work held `manual` in one house and `auto` in another has no single
   *  status. Showing only the strongest would answer "anything unapproved out
   *  there?" with a confident no. */
  it('says so when the households disagree about status', async () => {
    bothServices()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    const row = screen.getByText('אבא').closest('tr')!
    expect(within(row).getByText(/מעורב|mixed/)).toBeInTheDocument()
    expect(within(screen.getByText('בבא').closest('tr')!)
      .queryByText(/מעורב|mixed/)).not.toBeInTheDocument()
  })

  /**
   * ⚠ Changing the sort KEY resets the direction to that key's natural one.
   * Carrying A–Z's "ascending" onto "in most libraries" silently answers a
   * question nobody asked: "the rarest first".
   */
  it('resets the sort direction when the key changes', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    expect(screen.getByRole('button', { name: /עולה|Ascending/ })).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/מיון|Sort/), 'libraries')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /יורד|Descending/ })).toBeInTheDocument()
    })
  })

  /**
   * ⚠ While searching, the server ranks by RELEVANCE (P1.5's measured Hebrew
   * search) and ignores `sort`. A live sort control would promise an ordering
   * nobody applies, so it is inert and the box READS the ordering in force —
   * not a key the server is discarding. (A first version asserted only that
   * the word "relevance" appeared SOMEWHERE, which matched the sentence below
   * the row and was green while the box still said "title".)
   */
  it('sends the query to the server and marks the sort inert', async () => {
    const s = bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    await user.type(screen.getByLabelText(/חיפוש|Search/), 'מנהרה')
    await waitFor(() => {
      expect(s.calls.some((c) => c.url.startsWith('/api/staff/v1/works')
                              && c.url.includes(encodeURIComponent('מנהרה')))).toBe(true)
    })
    const sort = screen.getByLabelText(/מיון|Sort/)
    expect(sort).toBeDisabled()
    expect(sort).toHaveValue('relevance')
  })

  /** A ranked search stops at the server's scan cap; pages past it are
   *  unreachable, so the operator is told rather than shown a short list that
   *  reads as "that is all there is". */
  it('reports a truncated search', async () => {
    const s = bothServices()
    s.route('GET /api/staff/v1/works', () =>
      ({ items: [], total: 99999, offset: 0, limit: 25, truncated: true }))
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)

    await user.type(await screen.findByLabelText(/חיפוש|Search/), 'א')
    expect(await screen.findByText(/מגבלת הסריקה|scan cap/)).toBeInTheDocument()
  })
})
