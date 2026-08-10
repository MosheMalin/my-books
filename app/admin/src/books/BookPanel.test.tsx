/**
 * The three moderation doors, the rules each must keep, and the one case that
 * closes all of them.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BookPanel } from './BookPanel'
import { I18nProvider } from '../lib/i18n'
import { fakeServer, makeBook, makeStaffBook, type FakeServer } from '../test/harness'
import type { StaffBook } from '../api/staff'

let s: FakeServer

function mount(over: Partial<StaffBook> = {}, writable = true) {
  const onChanged = vi.fn()
  const result = render(
    <I18nProvider>
      <BookPanel book={makeStaffBook(over)} libraryLabel="הבית" writable={writable}
                 onClose={() => {}} onChanged={onChanged} />
    </I18nProvider>,
  )
  return { ...result, onChanged }
}

beforeEach(() => {
  vi.unstubAllGlobals()
  s = fakeServer({
    'POST /api/v1/books': (req) => makeBook({ id: 'b1', ...(req.body as object ?? {}) }),
    'PATCH /api/v1/books': (req) => makeBook({ id: 'b1', ...(req.body as object ?? {}) }),
    'DELETE /api/v1/books': () => new Response(null, { status: 204 }),
  })
})

describe('BookPanel', () => {
  /**
   * ⚠⚠ Reading is cross-tenant; writing is not. The row came from the staff
   * service, which spans every tenant; the actions go through the product
   * API, which resolves the operator's own membership and 404s otherwise. A
   * panel that showed the buttons anyway would be showing clicks that fail.
   */
  it('shows no action at all for a library the operator is not in', () => {
    mount({ status: 'auto' }, false)
    expect(screen.queryByRole('button', { name: /אישור|Approve/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /עריכת כותרת|Edit title/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /מחיקה|Delete/ })).not.toBeInTheDocument()
    expect(screen.getByText(/אינכם חברים|not a member/)).toBeInTheDocument()
  })

  /**
   * ⚠ §5.1's ladder: a confirmed finding is created APPROVED, and a hand-typed
   * book is `manual`, which OUTRANKS it. So *approve* is only ever meaningful
   * on the `auto` rung — offering it elsewhere invites an operator to
   * "confirm" what a human already vouched for.
   */
  it('offers approve only for an auto record', () => {
    const { unmount } = mount({ status: 'auto' })
    expect(screen.getByRole('button', { name: /אישור|Approve/ })).toBeInTheDocument()
    unmount()

    mount({ status: 'approved' })
    expect(screen.queryByRole('button', { name: /^אישור$|^Approve$/ })).not.toBeInTheDocument()
  })

  it('does not offer approve for a hand-typed book', () => {
    mount({ status: 'manual' })
    expect(screen.queryByRole('button', { name: /^אישור$|^Approve$/ })).not.toBeInTheDocument()
  })

  /** ⚠ The write must be addressed to the book's OWN library, never to "the
   *  current" one — in a cross-tenant list two adjacent rows belong to
   *  different tenants and a book id alone cannot address one. */
  it('writes through the library the book belongs to', async () => {
    const user = userEvent.setup()
    const { onChanged } = mount({ status: 'auto', library_id: 'lib-9' })
    await user.click(screen.getByRole('button', { name: /אישור|Approve/ }))

    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(s.calls.find((c) => c.url.includes('/approve'))?.library).toBe('lib-9')
  })

  /**
   * ⚠ Deleting is not a soft hide: it removes every copy AND records a
   * standing rejection at each (shelf, depth) the book stood at, so the next
   * read of that shelf does not put it back (§5.6). A one-click version of
   * that on a dense table row is a misclick a read cannot undo.
   */
  it('asks before deleting, and only then calls the server', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(screen.getByRole('button', { name: /מחיקה מהספרייה|Delete from library/ }))

    expect(s.calls.filter((c) => c.method === 'DELETE')).toHaveLength(0)
    expect(screen.getByText(/דחייה|rejection/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^מחיקה$|^Delete$/ }))
    await waitFor(() => {
      expect(s.calls.filter((c) => c.method === 'DELETE')).toHaveLength(1)
    })
  })

  it('reports a deletion as a removal, not as an edit', async () => {
    const user = userEvent.setup()
    const { onChanged } = mount()
    await user.click(screen.getByRole('button', { name: /מחיקה מהספרייה|Delete from library/ }))
    await user.click(screen.getByRole('button', { name: /^מחיקה$|^Delete$/ }))

    // `null` is what tells the list to drop the row; handing the book back
    // would leave a deleted record on screen until the next full fetch.
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith('b1', null))
  })

  /**
   * ⚠ The focus/Escape effect must NOT depend on `onClose` — it is a fresh
   * closure every parent render, so a depending effect re-runs on every commit
   * and pulls focus back to the close button mid-typing. (It also, less
   * obviously, once broke a state reset that lived here — see the panel's
   * module note.)
   */
  it('does not steal focus back while a title is being typed', async () => {
    const user = userEvent.setup()
    mount({ title: 'ראשון' })
    await user.click(screen.getByRole('button', { name: /עריכת כותרת|Edit title/ }))

    const input = screen.getByLabelText(/^כותרת$|^Title$/)
    await user.clear(input)
    await user.type(input, 'שלושה')

    expect(input).toHaveFocus()
    expect(input).toHaveValue('שלושה')
  })

  it('keeps the form open when a save is refused, so nothing is retyped', async () => {
    const user = userEvent.setup()
    s.route('PATCH /api/v1/books', () =>
      new Response(JSON.stringify({ detail: 'כבר יש ספר כזה' }), { status: 409 }))

    mount({ title: 'ראשון' })
    await user.click(screen.getByRole('button', { name: /עריכת כותרת|Edit title/ }))
    await user.clear(screen.getByLabelText(/^כותרת$|^Title$/))
    await user.type(screen.getByLabelText(/^כותרת$|^Title$/), 'חדש')
    await user.click(screen.getByRole('button', { name: /שמירה|Save/ }))

    // The server's own sentence is shown — an operator diagnosing a 409 needs
    // to read it — and the typed value survives.
    expect(await screen.findByText('כבר יש ספר כזה')).toBeInTheDocument()
    expect(screen.getByLabelText(/^כותרת$|^Title$/)).toHaveValue('חדש')
  })
})
