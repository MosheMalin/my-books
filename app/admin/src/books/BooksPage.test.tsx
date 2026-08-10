/**
 * The cross-tenant book list, and the read/write asymmetry only a rendered
 * screen can catch.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BooksPage } from './BooksPage'
import { renderApp } from '../test/harness'
import { bothServices } from '../test/servers'

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('BooksPage', () => {
  /**
   * ⚠⚠ One request, spanning every tenant. This replaced a per-library
   * fan-out whose results were merged and re-sorted in the browser with
   * `localeCompare` — which is not the server's normalized key, so the merged
   * order differed from a single library's and the screen had to apologise
   * for it. Ordering and Hebrew ranking now happen once, server-side.
   */
  it('lists every tenant\'s books from one staff request', async () => {
    const s = bothServices()
    renderApp(<BooksPage initialLibraryId={undefined} />)

    expect(await screen.findByText('אבא')).toBeInTheDocument()
    expect(screen.getByText('גגא')).toBeInTheDocument()

    expect(s.calls.filter((c) => c.url.startsWith('/api/staff/v1/books')))
      .toHaveLength(1)
    expect(s.calls.filter((c) => c.url.startsWith('/api/v1/books'))).toHaveLength(0)
  })

  it('labels each row with the library it came from', async () => {
    bothServices()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    // Scoped to the table — the picker above it names every library too — and
    // `getAllByText`, because lib-1 legitimately owns two of the three rows.
    const table = screen.getByRole('table')
    expect(within(table).getAllByText('הבית')).toHaveLength(2)
    expect(within(table).getAllByText('ההורים')).toHaveLength(1)
  })

  it('narrows to one library through the server, not the browser', async () => {
    const s = bothServices()
    renderApp(<BooksPage initialLibraryId="lib-2" />)

    expect(await screen.findByText('גגא')).toBeInTheDocument()
    expect(screen.queryByText('אבא')).not.toBeInTheDocument()
    expect(s.calls.some((c) => c.url.includes('library_id=lib-2'))).toBe(true)
  })

  /**
   * ⚠ Changing the sort KEY resets the direction to that key's natural one.
   * Carrying A–Z's "ascending" onto a date key silently answers a question
   * nobody asked: "recently added, oldest first".
   */
  it('resets the sort direction when the key changes', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    expect(screen.getByRole('button', { name: /עולה|Ascending/ })).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/מיון|Sort/), 'recently_added')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /יורד|Descending/ })).toBeInTheDocument()
    })
  })

  /**
   * ⚠ While searching, the server ranks by RELEVANCE (P1.5's measured Hebrew
   * search) and ignores `sort`. A live sort control would promise an ordering
   * nobody applies, so it is inert and the screen says why.
   */
  it('sends the query to the server and marks the sort inert', async () => {
    const s = bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)
    await screen.findByText('אבא')

    await user.type(screen.getByLabelText(/חיפוש|Search/), 'מנהרה')
    await waitFor(() => {
      expect(s.calls.some((c) => c.url.includes('/api/staff/v1/books')
                              && c.url.includes(encodeURIComponent('מנהרה')))).toBe(true)
    })
    expect(screen.getByLabelText(/מיון|Sort/)).toBeDisabled()
    expect(screen.getByText(/רלוונטיות|relevance/)).toBeInTheDocument()
  })

  /**
   * ⚠⚠ The console's central asymmetry, made visible. Reading spans every
   * tenant; writing goes through the product API, which resolves the
   * operator's own membership and 404s for anything else. A book in a library
   * they do not belong to must therefore show no action buttons — offering
   * one would be offering a click that fails.
   */
  it('offers no moderation on a book outside the operator\'s own libraries', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)

    // lib-2 is NOT in `mine` in the default world.
    await user.click(await screen.findByText('גגא'))
    const panel = await screen.findByRole('dialog')

    expect(within(panel).queryByRole('button', { name: /עריכת כותרת|Edit title/ }))
      .not.toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: /מחיקה|Delete/ }))
      .not.toBeInTheDocument()
    // …and says why, rather than leaving a panel that looks broken.
    expect(within(panel).getByText(/אינכם חברים|not a member/)).toBeInTheDocument()
  })

  it('offers moderation on a book in a library the operator administers', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)

    await user.click(await screen.findByText('אבא'))
    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByRole('button', { name: /עריכת כותרת|Edit title/ }))
      .toBeInTheDocument()
  })

  /**
   * ⚠⚠ Choosing a different row must abandon whatever was half-typed, or the
   * next Save renames the wrong book — across tenants, at that. The panel is
   * keyed on the book for exactly this; an effect that copied props into state
   * was tried first and was silently defeated by effect ordering (see
   * `BookPanel`'s note).
   */
  it('abandons a half-typed edit when another book is selected', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId="lib-1" />)
    await screen.findByText('אבא')

    await user.click(screen.getByText('אבא'))
    await user.click(await screen.findByRole('button', { name: /עריכת כותרת|Edit title/ }))
    await user.clear(screen.getByLabelText(/^כותרת$|^Title$/))
    await user.type(screen.getByLabelText(/^כותרת$|^Title$/), 'חצי')

    await user.click(screen.getByText('בבא'))

    const panel = await screen.findByRole('dialog')
    expect(screen.queryByLabelText(/^כותרת$|^Title$/)).not.toBeInTheDocument()
    expect(within(panel).getByText('בבא')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('חצי')).not.toBeInTheDocument()
  })

  /** A ranked search stops at the server's scan cap; pages past it are
   *  unreachable, so the operator is told rather than shown a short list that
   *  reads as "that is all there is". */
  it('reports a truncated search', async () => {
    const s = bothServices()
    s.route('GET /api/staff/v1/books', () =>
      ({ items: [], total: 99999, offset: 0, limit: 25, truncated: true }))
    const user = userEvent.setup()
    renderApp(<BooksPage initialLibraryId={undefined} />)

    await user.type(await screen.findByLabelText(/חיפוש|Search/), 'א')
    expect(await screen.findByText(/מגבלת הסריקה|scan cap/)).toBeInTheDocument()
  })
})
