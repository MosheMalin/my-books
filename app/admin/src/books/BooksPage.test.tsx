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
    // …each naming the CUSTOMER that holds it, not only the collection.
    expect(within(panel).getByText('משפחת מלין')).toBeInTheDocument()
    expect(within(panel).getByText('משפחת כהן')).toBeInTheDocument()
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
    // Still two, though only one of them is in view…
    expect(screen.getByRole('button', { name: /2 הספריות|2 libraries/ }))
      .toBeInTheDocument()
    // …and the screen SAYS that is deliberate, for the library filter and not
    // only for the status one.
    expect(screen.getByText(/נשאר המספר האמיתי|stays the true one/))
      .toBeInTheDocument()
  })

  /** ⚠ A work held `manual` in one house and `auto` in another has no single
   *  status. Showing only the strongest would answer "anything unapproved out
   *  there?" with a confident no. */
  /**
   * ⚠⚠ **NO STATUS COLUMN** (owner, 2026-08-13): *"in 2 libraries it can be
   * different status. what to display? simply do not display."* The table used
   * to show the strongest claim across households plus a "mixed" badge —
   * `אבא` is exactly that case, held `auto` in one house and `manual` in
   * another — which answered "is anything unapproved out there?" with a
   * confident no. §5.1 is a property of one COPY in one library, and that is
   * the only place it is now shown.
   */
  it('shows no status for a work, because a work does not have one', async () => {
    bothServices()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    const table = screen.getByRole('table')
    expect(within(table).queryByRole('columnheader', { name: /סטטוס|Status/ }))
      .not.toBeInTheDocument()
    const row = screen.getByText('אבא').closest('tr')!
    for (const state of [/זוהה אוטומטית|^Auto$/, /^אושר$|^Approved$/,
                         /^ידני$|^Manual$/, /מעורב|mixed/]) {
      expect(within(row).queryByText(state)).not.toBeInTheDocument()
    }
  })

  /**
   * ⚠⚠ The library filter is grouped by CUSTOMER. A flat list of collection
   * names — `הבית`, `המשרד`, `ההורים` — makes an operator guess whose is
   * whose, and since P3.7b one account may own several. `optgroup` because the
   * grouping is real, not a label prefix.
   */
  it('groups the library filter by customer', async () => {
    bothServices()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    const picker = screen.getByLabelText(/^ספרייה$|^Library$/)
    const groups = [...picker.querySelectorAll('optgroup')]
    expect(groups.map((g) => g.getAttribute('label')))
      .toEqual(['משפחת מלין', 'משפחת כהן'])
    // …and acc-1's two collections sit under it, not loose in the list.
    expect([...groups[0]!.querySelectorAll('option')].map((o) => o.textContent))
      .toEqual(['הבית', 'המשרד'])
  })

  /** ⚠ The status FILTER survives the column, and means something the column
   *  could not: works with AT LEAST ONE copy in that state. Said out loud,
   *  since the rows no longer show a status to compare it against. */
  it('explains what the status filter selects, now that no row shows one', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    expect(screen.queryByText(/לפחות עותק אחד|at least one copy/)).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/סטטוס|Status/), 'auto')
    expect(await screen.findByText(/לפחות עותק אחד|at least one copy/))
      .toBeInTheDocument()
  })

  /**
   * ⚠ Changing the sort KEY resets the direction to that key's natural one.
   * Carrying A–Z's "ascending" onto "in most libraries" silently answers a
   * question nobody asked: "the rarest first".
   */
  it('resets the sort direction when the key changes, and sends both', async () => {
    const s = bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    expect(screen.getByRole('button', { name: /עולה|Ascending/ })).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/מיון|Sort/), 'libraries')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /יורד|Descending/ })).toBeInTheDocument()
    })
    // ⚠ …and it reaches the SERVER. The reset was pinned on the client and the
    // key was pinned on the server, with nothing gating the wire between them —
    // so dropping `sort` from the request left the whole ring green while "in
    // most libraries" quietly returned title order.
    await waitFor(() => {
      expect(s.calls.some((c) => c.url.includes('sort=libraries')
                              && c.url.includes('ascending=false'))).toBe(true)
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
