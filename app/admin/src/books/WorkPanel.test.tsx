/**
 * The work drawer: no library at the top, every household below — each naming
 * the CUSTOMER that holds it — and nothing at all to press.
 *
 * ⚠⚠ Eight of this file's tests were about moderation: approve only on the
 * `auto` rung, the delete confirmation, the write addressed to the copy's own
 * library, the edit form surviving a 409, the focus effect not stealing the
 * caret mid-typing. The owner removed the capability on 2026-08-13 — *"this is
 * not mine to do so"* — so they are gone with it, replaced by tests that the
 * doors are SHUT and that the client cannot even reach for them. Deleting a
 * test whose subject no longer exists is right; keeping it green against a
 * feature nobody has is how a suite starts describing a product that is not
 * there.
 */
import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkPanel } from './WorkPanel'
import { makeStaffWork, renderApp } from '../test/harness'
import { bothServices } from '../test/servers'
import type { FakeServer } from '../test/harness'
import type { StaffWork } from '../api/staff'

let s: FakeServer

/** The household card a library's name sits in. `closest` on a class selector
 *  is typed `Element`, which `within()` will not take. */
const card = (library: string): HTMLElement =>
  screen.getByText(library).closest('.card') as HTMLElement

/** Mount the panel the way the page does — KEYED on the work — so a rerender
 *  with a different work remounts it. */
function renderWork(work: StaffWork) {
  const result = renderApp(
    <WorkPanel key={work.key} work={work} onClose={() => {}} />)
  return {
    rerender: (next: StaffWork) => result.rerender(
      <WorkPanel key={next.key} work={next} onClose={() => {}} />),
  }
}

function mount(over: Partial<StaffWork> = {}) {
  const work = makeStaffWork({
    key: 'אבא|א', title: 'אבא', author: 'א', libraries: 2, copies: 3,
    mixed: true, status: 'manual', ...over,
  })
  renderApp(<WorkPanel work={work} onClose={() => {}} />)
}

beforeEach(() => {
  vi.unstubAllGlobals()
  s = bothServices()
})

describe('WorkPanel', () => {
  /**
   * ⚠⚠ The owner's instruction for this panel: *"no library no shelf. maybe
   * number of libraries and first found"*. A work does not HAVE a library —
   * the households are a list below, not a property above.
   */
  it('describes the work by spread and first-found, not by a library', async () => {
    mount()
    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByText(/^ספריות$|^Libraries$/)).toBeInTheDocument()
    expect(within(panel).getByText(/נמצא לראשונה|First found/)).toBeInTheDocument()
    expect(within(panel).queryByText(/^מדף$|^Shelf$/)).not.toBeInTheDocument()
  })

  /**
   * ⚠⚠ **No status on the aggregate** (owner, 2026-08-13): *"in 2 libraries it
   * can be different status. what to display? simply do not display."* The
   * summary showed the strongest claim across households plus a "mixed" badge
   * — the same fiction the list's status column was, one level in. The
   * per-household cards still show it, because there it is one copy in one
   * library and therefore true.
   */
  it('shows no status for the work, only for each household copy', async () => {
    mount()
    await screen.findByText('הבית')
    const panel = screen.getByRole('dialog')

    // The summary block is the run of `.kv` rows above the household list.
    const summaryKeys = [...panel.querySelectorAll('.kv .k')].map((k) => k.textContent)
    expect(summaryKeys).not.toContain('סטטוס')
    expect(summaryKeys).not.toContain('Status')
    expect(within(panel).queryByText(/סטטוס מעורב|mixed/)).not.toBeInTheDocument()

    // …but the copy in one library has one, and shows it.
    expect(within(card('הבית'))
      .getByText(/זוהה אוטומטית|^Auto$|^אושר$|^Approved$|^ידני$|^Manual$/))
      .toBeInTheDocument()
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
   * ⚠⚠ **Which CUSTOMER holds each copy**, not just which collection. `הבית`
   * and `המשרד` are both `משפחת מלין`'s, and a cross-tenant list that names
   * only the collection leaves the operator guessing whose shelf they are
   * looking at.
   */
  it('names the customer behind each household copy', async () => {
    mount()
    await screen.findByText('הבית')
    expect(within(card('הבית')).getByText('משפחת מלין')).toBeInTheDocument()
    expect(within(card('ההורים')).getByText('משפחת כהן')).toBeInTheDocument()
  })

  /**
   * ⚠⚠ **THE PANEL MODERATES NOTHING** (owner, 2026-08-13): *"I should not be
   * able to approve it or remove it or edit it. this is not mine to do so."*
   * It used to offer all three on any copy in a library the operator belonged
   * to — and `lib-1` IS one of those, so this fixture is the case that used to
   * show the buttons.
   */
  it('offers no approve, edit or delete on any household copy', async () => {
    mount()
    await screen.findByText('הבית')
    const panel = screen.getByRole('dialog')

    for (const name of [/אישור|Approve/, /עריכת כותרת|Edit title/,
                        /מחיקה|Delete/, /שמירה|Save/]) {
      expect(within(panel).queryByRole('button', { name })).not.toBeInTheDocument()
    }
    // The ONLY button in the whole drawer is close.
    const buttons = within(panel).getAllByRole('button')
    expect(buttons).toHaveLength(1)
    expect(buttons[0]!.textContent).toMatch(/סגירה|Close/)
  })

  /** ⚠ Absent, and SAID to be absent. An operator who used to approve from
   *  here must learn the capability moved, not wonder whether it failed to
   *  render. */
  it('says where moderation went instead of leaving a silent gap', async () => {
    mount()
    await screen.findByText('הבית')
    expect(screen.getByText(/הקונסולה מדווחת ואינה עורכת|console reports, it does not edit/))
      .toBeInTheDocument()
  })

  /** ⚠ Structural, not cosmetic: with the client's book-write functions
   *  deleted there is no code path that could reach them. Nothing the panel
   *  does may produce a mutating product request. */
  it('never issues a mutating request to the product API', async () => {
    mount()
    await screen.findByText('הבית')
    const mutations = s.calls.filter((c) => c.method !== 'GET')
    expect(mutations).toEqual([])
  })

  /**
   * ⚠⚠ Choosing a different work must abandon whatever the open one loaded, or
   * the panel shows one work's households under another's title. The reset is
   * the CALLER's `key` on this component; an effect version was tried in the
   * retired `BookPanel` and was silently defeated by effect ordering.
   *
   * The ring could not catch this until the fake learned to be slow — see
   * `harness.tsx`. With an instant fetch there is no window in which the stale
   * data is on screen.
   */
  it('drops the previous household list the moment the work changes', async () => {
    let release: (() => void) | undefined
    s.route('GET /api/staff/v1/works/instances', async (req) => {
      const key = new URL(req.url, 'http://x').searchParams.get('key')
      if (key === 'בבא|ב') await new Promise<void>((r) => { release = r })
      return key === 'אבא|א'
        ? [{ id: 'b1', library_id: 'lib-1', title: 'אבא', author: 'א',
             status: 'auto', copy_count: 1, shelf_count: 0, added_at: null }]
        : []
    })

    const { rerender } = renderWork(makeStaffWork({ key: 'אבא|א', title: 'אבא' }))
    await screen.findByText('הבית')

    rerender(makeStaffWork({ key: 'בבא|ב', title: 'בבא' }))
    // The previous work's household must be gone the moment the key changes —
    // not when the new fetch lands.
    expect(screen.queryByText('הבית')).not.toBeInTheDocument()
    release?.()
  })
})
