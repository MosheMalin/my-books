/**
 * The work drawer: no library at the top, every household below, and the three
 * moderation doors — open only where the operator is a member.
 */
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import { userEvent } from '@booksnap/ui/testing/user'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkPanel } from './WorkPanel'
import { makeBook, makeStaffWork, renderApp } from '../test/harness'
import { bothServices } from '../test/servers'
import type { FakeServer } from '../test/harness'
import type { StaffWork } from '../api/staff'

let s: FakeServer

/** The household card a library's name sits in. `closest` on a class selector
 *  is typed `Element`, which `within()` will not take. */
const card = (library: string): HTMLElement =>
  screen.getByText(library).closest('.card') as HTMLElement

function mount(over: Partial<StaffWork> = {}) {
  const onChanged = vi.fn()
  const work = makeStaffWork({
    key: 'אבא|א', title: 'אבא', author: 'א', libraries: 2, copies: 3,
    mixed: true, status: 'manual', ...over,
  })
  renderApp(<WorkPanel work={work} onClose={() => {}} onChanged={onChanged} />)
  return { onChanged }
}

beforeEach(() => {
  vi.unstubAllGlobals()
  s = bothServices()
  s.route('PATCH /api/v1/books', (req) =>
    makeBook({ id: 'b1', ...(req.body as object ?? {}) }))
  s.route('POST /api/v1/books', () => makeBook({ id: 'b1', status: 'approved' }))
  s.route('DELETE /api/v1/books', () => new Response(null, { status: 204 }))
})

describe('WorkPanel', () => {
  /**
   * ⚠⚠ The owner's instruction for this panel: *"no library no shelf. maybe
   * number of libraries and first found"*. A work does not HAVE a library —
   * the households are a list below, not a property above.
   */
  it('describes the work by spread and first-found, not by a library', async () => {
    mount()
    // The summary block, before the per-household list.
    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByText(/^ספריות$|^Libraries$/)).toBeInTheDocument()
    expect(within(panel).getByText(/נמצא לראשונה|First found/)).toBeInTheDocument()
    expect(within(panel).queryByText(/^מדף$|^Shelf$/)).not.toBeInTheDocument()
  })

  it('lists every household that holds it, with that household\'s own spelling',
     async () => {
    mount()
    expect(await screen.findByText('הבית')).toBeInTheDocument()
    expect(screen.getByText('ההורים')).toBeInTheDocument()
    // lib-2 stores it as 'אבא!' — shown, because otherwise an operator cannot
    // tell why two rows normalize to one work.
    expect(screen.getByText(/אבא!/)).toBeInTheDocument()
  })

  /**
   * ⚠⚠ Reading is cross-tenant; writing is not. The instances came from the
   * staff service, which spans every tenant; the actions go through the
   * product API, which resolves the operator's own membership and 404s
   * otherwise. lib-2 is not in `mine`, so its row offers nothing.
   */
  it('offers moderation only on the households the operator belongs to', async () => {
    mount()
    await screen.findByText('הבית')

    const mine = card('הבית')
    const theirs = card('ההורים')

    expect(within(mine).getByRole('button', { name: /עריכת כותרת|Edit title/ }))
      .toBeInTheDocument()
    expect(within(theirs).queryByRole('button', { name: /עריכת כותרת|Edit title/ }))
      .not.toBeInTheDocument()
    expect(within(theirs).getByText(/אינכם חברים|not a member/)).toBeInTheDocument()
  })

  /** ⚠ There is no "approve everywhere". The aggregate is a reading device;
   *  every write is per household. A fan-out whose failure mode is "three
   *  succeeded, two 404'd" has no honest way to be reported. */
  it('offers no action on the work as a whole', async () => {
    mount()
    const panel = await screen.findByRole('dialog')
    await screen.findByText('הבית')

    // Every action button lives inside a household card.
    for (const button of within(panel).getAllByRole('button')) {
      if (/סגירה|Close/.test(button.textContent ?? '')) continue
      expect(button.closest('.card')).not.toBeNull()
    }
  })

  /** ⚠ The write is addressed to the household's OWN library, never to "the
   *  current" one — in a cross-tenant list two adjacent rows belong to
   *  different tenants and a book id alone cannot address one. */
  it('writes through the library the copy belongs to', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('הבית')

    const mine = card('הבית')
    await user.click(within(mine).getByRole('button', { name: /אישור|Approve/ }))
    await waitFor(() => {
      expect(s.calls.find((c) => c.url.includes('/approve'))?.library).toBe('lib-1')
    })
  })

  /**
   * ⚠ §5.1's ladder: a confirmed finding is created APPROVED and a hand-typed
   * book is `manual`, which OUTRANKS it. So *approve* is only ever meaningful
   * on the `auto` rung.
   */
  it('offers approve only for an auto copy', async () => {
    // The default world holds it `auto` in lib-1 — the house the operator can
    // write to — so the button is there.
    mount()
    await screen.findByText('הבית')
    expect(within(card('הבית')).getByRole('button', { name: /אישור|Approve/ }))
      .toBeInTheDocument()

    // Now the same house has vouched for it. `manual` OUTRANKS `approved`
    // (§5.1), so "approve" would invite confirming what a human already typed.
    cleanup()
    s.route('GET /api/staff/v1/works/instances', () => [
      { id: 'b1', library_id: 'lib-1', title: 'אבא', author: 'א',
        status: 'manual', copy_count: 1, shelf_count: 0, added_at: null },
    ])
    mount()
    await screen.findByText('הבית')
    expect(within(card('הבית')).queryByRole('button', { name: /^אישור$|^Approve$/ }))
      .not.toBeInTheDocument()
    // …and the other two doors are still open.
    expect(within(card('הבית')).getByRole('button', { name: /עריכת כותרת|Edit title/ }))
      .toBeInTheDocument()
  })

  /**
   * ⚠ Deleting is not a soft hide: it removes every copy AND records a
   * standing rejection at each (shelf, depth) the book stood at, so the next
   * read of that shelf does not put it back (§5.6).
   */
  it('asks before deleting, and only then calls the server', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('הבית')
    const mine = card('הבית')

    await user.click(within(mine).getByRole('button', { name: /מחיקה מהספרייה|Delete from library/ }))
    expect(s.calls.filter((c) => c.method === 'DELETE')).toHaveLength(0)
    expect(within(mine).getByText(/דחייה|rejection/)).toBeInTheDocument()

    await user.click(within(mine).getByRole('button', { name: /^מחיקה$|^Delete$/ }))
    await waitFor(() => {
      expect(s.calls.filter((c) => c.method === 'DELETE')).toHaveLength(1)
    })
  })

  /**
   * ⚠ A delete can drop a library from the spread, so the AGGREGATE behind the
   * panel is stale the moment a write lands. A row still reading "in 2
   * libraries" would be a lie the operator caused themselves.
   */
  it('tells the list to refetch after a write', async () => {
    const user = userEvent.setup()
    const { onChanged } = mount()
    await screen.findByText('הבית')

    const mine = card('הבית')
    await user.click(within(mine).getByRole('button', { name: /אישור|Approve/ }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  /** ⚠ The focus/Escape effect must NOT depend on `onClose` — it is a fresh
   *  closure every parent render, so a depending effect re-runs on every
   *  commit and pulls focus back to the close button mid-typing. */
  it('does not steal focus back while a title is being typed', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('הבית')

    const mine = card('הבית')
    await user.click(within(mine).getByRole('button', { name: /עריכת כותרת|Edit title/ }))
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

    mount()
    await screen.findByText('הבית')
    const mine = card('הבית')

    await user.click(within(mine).getByRole('button', { name: /עריכת כותרת|Edit title/ }))
    await user.clear(screen.getByLabelText(/^כותרת$|^Title$/))
    await user.type(screen.getByLabelText(/^כותרת$|^Title$/), 'חדש')
    await user.click(within(mine).getByRole('button', { name: /שמירה|Save/ }))

    expect(await screen.findByText('כבר יש ספר כזה')).toBeInTheDocument()
    expect(screen.getByLabelText(/^כותרת$|^Title$/)).toHaveValue('חדש')
  })
})
