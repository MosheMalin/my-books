/**
 * Merging two shelf identities into one, from the panel (P6.4d, §3.11).
 *
 * The sentences this file holds in place, each mutation-checked:
 *
 *   - **the preview comes between the pick and the ✓** (§3.14). A merge moves
 *     a population of copies and looks like success either way, because the
 *     map gets fuller — so the owner sees what moves before saying yes;
 *   - **the strip order is DECLARED** (§3.12). Neither radio is pre-selected
 *     and the button stays disabled until one is, because a default here
 *     would be the system detecting it on their behalf;
 *   - **a refusal is the server's own sentence**, not ours, and it arrives
 *     with a 200 rather than a status the client has to interpret;
 *   - **a preview that failed is not a merge that moves nothing** — the same
 *     third state the shelf picker needed, for the same measured reason.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { I18nProvider } from '../lib/i18n'
import { Inspector, type Actions } from './ui/Inspector'
import type { Selection } from './ui/types'
import type { MergePreview, OffMapShelf } from './useMapSync'
import { emptyPlan, newBookcase } from './core/model'
import type { Plan, Section } from './core/model'
import { mapText } from './text'

const HE = mapText('he')

const OFF: OffMapShelf[] = [
  { id: 'ph-1', label: 'ספרי בישול', capture_count: 2, book_count: 22 },
]

const MOVES: MergePreview = {
  absorbed_id: 'ph-1', survivor_id: 'sh-1', refused: null, already: false,
  depth: 2, books: 22, copies: [{ depth: 1, count: 22 }],
  photos: [{ depth: 1, count: 2 }], clashes: [],
  answers_moved: 3, identities_moved: 0,
}

const section = (id: string): Section => ({
  id, columnLevels: [1], gaps: [], defaultLevels: 1, defaultDepth: 1,
  // ⚠ `photos: 3`, and it was 0. The flagship *declared, never detected*
  // test lives on this cell, and with the survivor holding no photographs
  // both orderings produce a byte-identical strip — so the one test pinning
  // §5.7 was pinning a question with a single answer.
  shelves: [{ col: 0, level: 0, depth: 1, photos: 3, books: 0,
              id: 'sh-1', label: 'המדף העליון' }],
})

const plan = (): Plan => ({
  ...emptyPlan(),
  rooms: [{ id: 'r1', name: 'סלון', rect: { x: 0, y: 0, w: 10, h: 8 },
            floorId: 'f1' }],
  cases: [{
    ...newBookcase('c1', 'ארון', { x: 1, y: 0, w: 4, h: 1 }, 'S', 'r1', 'f1', 1),
    sections: [section('s1')],
  }],
})

const actions = (over: Partial<Actions> = {}): Actions => ({
  renameRoom: vi.fn(), resizeRoom: vi.fn(), renameCase: vi.fn(),
  resizeCase: vi.fn(), setCaseRoom: vi.fn(), turnCase: vi.fn(),
  setGaps: vi.fn(), setColumnCount: vi.fn(), setColumnLevels: vi.fn(),
  setDefaultLevels: vi.fn(), applyDefaultLevels: vi.fn(),
  setDefaultDepth: vi.fn(), applyDefaultDepth: vi.fn(), setShelfDepth: vi.fn(),
  addSection: vi.fn(), removeSection: vi.fn(), moveSection: vi.fn(),
  deleteSelection: vi.fn(),
  copySelection: vi.fn(), paste: vi.fn(), select: vi.fn(),
  shelvesOffTheMap: vi.fn(async () => OFF),
  bindShelf: vi.fn(), unbindShelf: vi.fn(),
  previewMerge: vi.fn(async () => MOVES), mergeShelf: vi.fn(),
  shelfOverview: vi.fn(async () => ({
                     shelf: { id: 'sh', label: '', depth_count: 1,
                              virtual: false, created_at: null,
                              capture_count: 0, book_count: 0, address: null,
                              formerly: [] },
                     depths: [], last_read_at: null,
                   })),
  ...over,
})

const unnamedPlan = (): Plan => ({
  ...plan(),
  cases: [{
    ...newBookcase('c1', 'ארון', { x: 1, y: 0, w: 4, h: 1 }, 'S', 'r1', 'f1', 1),
    sections: [{
      ...section('s1'),
      shelves: [{ col: 0, level: 0, depth: 1, photos: 3, books: 0,
                  id: 'sh-1', label: '' }],
    }],
  }],
})

const emptyStripPlan = (): Plan => ({
  ...plan(),
  cases: [{
    ...newBookcase('c1', 'ארון', { x: 1, y: 0, w: 4, h: 1 }, 'S', 'r1', 'f1', 1),
    sections: [{
      ...section('s1'),
      shelves: [{ col: 0, level: 0, depth: 1, photos: 0, books: 0,
                  id: 'sh-1', label: 'המדף העליון' }],
    }],
  }],
})

const CELL: Selection = {
  rooms: [], cases: ['c1'],
  cells: [{ caseId: 'c1', sectionId: 's1', col: 0, level: 0 }],
}

const show = (acts: Actions) =>
  render(
    <I18nProvider>
      <Inspector doc={{ plan: plan(), seq: 0 }} floorId="f1" selection={CELL}
                 actions={acts} renaming={null} onRenamed={() => {}} />
    </I18nProvider>,
  )

const openPicker = async (acts: Actions) => {
  const user = userEvent.setup()
  show(acts)
  await user.click(screen.getByRole('button', { name: HE.merge_a_shelf_here }))
  return user
}

describe('the panel offers a merge, and shows what it would cost', () => {
  it('is a separate control from the bind — never one button (§3.14)', () => {
    // ⚠ The empty-cell picker says *put a shelf here* and moves nothing; this
    // says *merge another shelf into this one* and moves a population of
    // copies. A UI that names them alike is how the dangerous one gets
    // pressed by accident, which is the whole of §3.14.
    show(actions())
    expect(screen.getByRole('button', { name: HE.merge_a_shelf_here }))
      .toBeInTheDocument()
    expect(screen.queryByRole('button', { name: HE.put_a_shelf_here }))
      .toBeNull()
  })

  it('shows what would move before it will let anything be merged', async () => {
    const acts = actions()
    const user = await openPicker(acts)
    await user.click(await screen.findByRole('button',
      { name: HE.merge_pick_option(1, 'ספרי בישול', 22, 2) }))

    expect(await screen.findByText(
      HE.merge_would_move('ספרי בישול', 'המדף העליון'))).toBeInTheDocument()
    expect(screen.getByText(HE.merge_books(22))).toBeInTheDocument()
    expect(screen.getByText(HE.merge_photos(2))).toBeInTheDocument()
    expect(screen.getByText(HE.merge_answers(3))).toBeInTheDocument()
    expect(screen.getByText(HE.merge_depth_after(2))).toBeInTheDocument()
    expect(acts.mergeShelf).not.toHaveBeenCalled()
  })

  it('says why a merge has nothing to offer, not where shelves are', async () => {
    // ⚠ It reused the bind's *"every shelf is already on the map"* — a
    // statement about PLACEMENT under a question about IDENTITY, which never
    // says the actual reason: only a shelf standing nowhere can be merged in.
    const acts = actions({ shelvesOffTheMap: vi.fn(async () => []) })
    await openPicker(acts)
    expect(await screen.findByText(HE.merge_none_off_the_map))
      .toBeInTheDocument()
    expect(screen.queryByText(HE.no_shelves_off_the_map)).toBeNull()
  })

  it('announces an empty shelf the same way the row shows it', async () => {
    // ⚠ The row read *ריק* while its accessible name said *0 ספרים · 0
    // תמונות* — two descriptions of one shelf, which is the bug the bind
    // sibling's own branch was written for. Three taps to reach: unbind an
    // empty shelf, then open the merge picker.
    const acts = actions({
      shelvesOffTheMap: vi.fn(async () => [
        { id: 'a', label: 'ריקה', capture_count: 0, book_count: 0 },
      ]),
    })
    await openPicker(acts)
    const row = await screen.findByRole('button',
      { name: HE.merge_pick_option(1, 'ריקה', 0, 0) })
    expect(row.getAttribute('aria-label')).toContain(HE.shelf_holds_nothing)
    expect(row.getAttribute('aria-label')).not.toMatch(/0/)
  })

  it('will not merge until the strip order is DECLARED (§3.12)', async () => {
    // §5.7's rule is *declared, never detected*, and which half of the merged
    // shelf is on the left is a physical claim about wood that no photograph
    // carries. A pre-selected radio is the system answering it every time.
    const acts = actions()
    const user = await openPicker(acts)
    await user.click(await screen.findByRole('button',
      { name: HE.merge_pick_option(1, 'ספרי בישול', 22, 2) }))

    const go = await screen.findByRole('button', { name: HE.merge_confirm })
    expect(go).toBeDisabled()
    for (const radio of screen.getAllByRole('radio')) {
      expect(radio).not.toBeChecked()
    }

    await user.click(screen.getByRole('radio',
      { name: HE.merge_strip_absorbed_first('ספרי בישול') }))
    expect(go).toBeEnabled()
    await user.click(go)
    expect(acts.mergeShelf).toHaveBeenCalledWith(
      'ph-1', 'sh-1', 'absorbed_first', 'ספרי בישול')
  })

  it('asks nothing about order when there are no photographs to order', async () => {
    // A required answer to a question about nothing is a dead end: with no
    // photographs on either side there is no left and no right, and the radio
    // would block a merge that has no order to declare.
    const acts = actions({
      previewMerge: vi.fn(async () => ({ ...MOVES, photos: [], books: 0 })),
      shelvesOffTheMap: vi.fn(async () => [
        { id: 'ph-1', label: 'ספרי בישול', capture_count: 0, book_count: 0 },
      ]),
    })
    const user = await openPicker(acts)
    await user.click(await screen.findByRole('button',
      { name: HE.merge_pick_option(1, 'ספרי בישול', 0, 0) }))

    expect(await screen.findByText(HE.merge_moves_nothing)).toBeInTheDocument()
    expect(screen.queryAllByRole('radio')).toEqual([])
    const go = screen.getByRole('button', { name: HE.merge_confirm })
    expect(go).toBeEnabled()
    await user.click(go)
    expect(acts.mergeShelf).toHaveBeenCalledWith(
      'ph-1', 'sh-1', 'survivor_first', 'ספרי בישול')
  })

  it('asks nothing about order when only ONE side has photographs', async () => {
    // Both orderings produce a byte-identical strip when the survivor holds
    // nothing — measured in the domain. A required answer to that is a
    // required answer to nothing, and it is what the client used to demand,
    // because it counted the absorbed shelf's photographs alone.
    const acts = actions()
    const user = userEvent.setup()
    render(
      <I18nProvider>
        <Inspector doc={{ plan: emptyStripPlan(), seq: 0 }} floorId="f1"
                   selection={CELL} actions={acts} renaming={null}
                   onRenamed={() => {}} />
      </I18nProvider>,
    )
    await user.click(screen.getByRole('button',
      { name: HE.merge_a_shelf_here }))
    await user.click(await screen.findByRole('button',
      { name: HE.merge_pick_option(1, 'ספרי בישול', 22, 2) }))

    await screen.findByText(HE.merge_books(22))
    expect(screen.queryAllByRole('radio')).toEqual([])
    expect(screen.getByRole('button', { name: HE.merge_confirm }))
      .toBeEnabled()
  })

  it("says a refusal in the READER's language, and offers no ✓", async () => {
    // ⚠ Six reasons, six different next actions — and `MergeRefused` carries
    // a stable code beside the sentence *so a client can translate it*, in
    // its own words. This client translated none of them, so a household
    // member met four lines of English and a 32-character hex id. Measured in
    // a real browser on the owner's library.
    const acts = actions({
      previewMerge: vi.fn(async () => ({
        ...MOVES,
        refused: { reason: 'read_running',
                   say: 'a read of 83e6eaf0d861 is still running' },
      })),
    })
    const user = await openPicker(acts)
    await user.click(await screen.findByRole('button',
      { name: HE.merge_pick_option(1, 'ספרי בישול', 22, 2) }))

    expect(await screen.findByText(
      new RegExp(HE.merge_reason('read_running')))).toBeInTheDocument()
    expect(screen.queryByText(/83e6eaf0d861/)).toBeNull()
    expect(screen.queryByRole('button', { name: HE.merge_confirm })).toBeNull()
    // Transient by nature, so the way forward is to ask again.
    expect(screen.getByRole('button', { name: HE.shelf_list_retry }))
      .toBeInTheDocument()
  })

  it("falls back to the server's sentence for a code it does not know", async () => {
    // A table that answers '' for an unknown code and a caller that prints
    // nothing would leave *Cannot merge:* with no reason at all — which is
    // the refusal §3.15 explicitly does not want.
    const acts = actions({
      previewMerge: vi.fn(async () => ({
        ...MOVES,
        refused: { reason: 'a_reason_from_the_future', say: 'because of X' },
      })),
    })
    const user = await openPicker(acts)
    await user.click(await screen.findByRole('button',
      { name: HE.merge_pick_option(1, 'ספרי בישול', 22, 2) }))

    expect(await screen.findByText(/because of X/)).toBeInTheDocument()
  })

  it('says WHY the ✓ is disabled, beside the ✓', async () => {
    // ⚠ Measured: with the radio fieldset on screen the auto-scroll landed
    // past the question, so what the owner saw in a 251px panel was a greyed
    // destructive button, no question, and no account of what would move.
    const acts = actions()
    const user = await openPicker(acts)
    await user.click(await screen.findByRole('button',
      { name: HE.merge_pick_option(1, 'ספרי בישול', 22, 2) }))

    const go = await screen.findByRole('button', { name: HE.merge_confirm })
    expect(go).toBeDisabled()
    expect(screen.getByText(HE.merge_pick_order)).toBeInTheDocument()
    expect(go.getAttribute('aria-describedby')).toBeTruthy()

    await user.click(screen.getByRole('radio',
      { name: HE.merge_strip_absorbed_first('ספרי בישול') }))
    expect(screen.queryByText(HE.merge_pick_order)).toBeNull()
    expect(go.getAttribute('aria-describedby')).toBeNull()
  })

  it('says a preview could not be READ rather than showing an empty one', async () => {
    // ⚠ The same third state the shelf picker needed. A failure landing as
    // "moves nothing" is a confident false statement in front of the one
    // gesture in this pillar that can lose books — measured once already, as
    // *"every shelf is already on the map"* beside forty that were not.
    const acts = actions({
      previewMerge: vi.fn(async () => { throw new Error('down') }),
    })
    const user = await openPicker(acts)
    await user.click(await screen.findByRole('button',
      { name: HE.merge_pick_option(1, 'ספרי בישול', 22, 2) }))

    expect(await screen.findByText(HE.merge_read_failed)).toBeInTheDocument()
    expect(screen.queryByText(HE.merge_moves_nothing)).toBeNull()
    expect(screen.queryByRole('button', { name: HE.merge_confirm })).toBeNull()
  })

  it('names every option, because most of these shelves have no name', async () => {
    // Two unnamed shelves holding nothing announce the identical sentence
    // otherwise — the collision CLAUDE.md keeps a line about, and unnamed is
    // the COMMON case here: these are the photo-born half of the population.
    const acts = actions({
      shelvesOffTheMap: vi.fn(async () => [
        { id: 'a', label: '', capture_count: 0, book_count: 0 },
        { id: 'b', label: '', capture_count: 0, book_count: 0 },
      ]),
    })
    await openPicker(acts)
    const names = (await screen.findAllByRole('button'))
      .map((b) => b.getAttribute('aria-label') || b.textContent)
      .filter((n) => n && n.includes(HE.shelf_unnamed))
    expect(new Set(names).size).toBe(names.length)
    expect(names.length).toBe(2)
  })

  it('survives the selection going from no cell to a cell', async () => {
    // ⚠⚠ The transition NOTHING tested, and it is the ordinary one: select a
    // bookcase, then tap a cell. `ShelfPanel` returns early when no cell is
    // chosen, so a hook called below that return is a CONDITIONAL hook — and
    // React answers with *"a change in the order of Hooks called by
    // ShelfPanel"*, then *"Should have a queue"*, then *"Internal React
    // error"*. Measured in a real browser on the owner's own library while
    // the whole ring was green, because every other test in this file MOUNTS
    // the panel already pointing at a cell.
    const noises: unknown[] = []
    const spy = vi.spyOn(console, 'error')
      .mockImplementation((...a) => { noises.push(a[0]) })
    try {
      const acts = actions()
      const caseOnly: Selection = { rooms: [], cases: ['c1'], cells: [] }
      const view = (selection: Selection) => (
        <I18nProvider>
          <Inspector doc={{ plan: plan(), seq: 0 }} floorId="f1"
                     selection={selection} actions={acts} renaming={null}
                     onRenamed={() => {}} />
        </I18nProvider>
      )
      const { rerender } = render(view(caseOnly))
      // ⚠ Re-wrapped, not `rerender(<Inspector …/>)`: a bare one throws
      // "useI18n outside <I18nProvider>", which reads as a screen bug.
      rerender(view(CELL))

      expect(screen.getByRole('button', { name: HE.merge_a_shelf_here }))
        .toBeInTheDocument()
      expect(noises.filter((n) => typeof n === 'string'
        && /order of Hooks|Should have a queue|Internal React error/.test(n)))
        .toEqual([])
    } finally {
      spy.mockRestore()
    }
  })

  it('tells the two radios apart when NEITHER shelf has a name', async () => {
    // ⚠ Measured on the owner's own library, which is the only reason this
    // case exists: both shelves were unnamed, both radios fell back to
    // *מדף ללא שם*, and the control that decides an ordering §5.7 says
    // nothing can detect announced ONE accessible name twice. The fixture
    // above hid it by naming both shelves — which is not the state a
    // household is in, since the photo-born half of the population is
    // unnamed by default.
    const acts = actions({
      shelvesOffTheMap: vi.fn(async () => [
        { id: 'ph-1', label: '', capture_count: 2, book_count: 22 },
      ]),
    })
    const user = userEvent.setup()
    render(
      <I18nProvider>
        <Inspector doc={{ plan: unnamedPlan(), seq: 0 }} floorId="f1"
                   selection={CELL} actions={acts} renaming={null}
                   onRenamed={() => {}} />
      </I18nProvider>,
    )
    await user.click(screen.getByRole('button',
      { name: HE.merge_a_shelf_here }))
    await user.click(await screen.findByRole('button',
      { name: HE.merge_pick_option(1, HE.shelf_unnamed, 22, 2) }))

    const named = (await screen.findAllByRole('radio'))
      .map((r) => r.getAttribute('aria-label')
        || (r as HTMLInputElement).labels?.[0]?.textContent)
    expect(new Set(named).size, `two radios announcing ${named[0]}`).toBe(2)
  })

  it('brings the ✓ into view, because the panel is 251px tall', async () => {
    // ⚠ Measured: with the account of what would move rendered, the confirm
    // sat at y=978 inside a `.map-side` whose window ends around y=812 — off
    // screen, reachable only by scrolling a panel nothing says is scrollable.
    // What is out of sight is the confirmation of the one gesture in this
    // pillar that moves books.
    const into = vi.fn()
    ;(Element.prototype as unknown as { scrollIntoView: unknown })
      .scrollIntoView = into
    const frames: FrameRequestCallback[] = []
    const raf = vi.spyOn(window, 'requestAnimationFrame')
      .mockImplementation((cb) => { frames.push(cb); return 0 })
    try {
      const acts = actions()
      const user = await openPicker(acts)
      // ⚠ CLEARED here, and a mutation is why: `useCellInView` one fold up
      // scrolls the whole panel into view when a cell is selected, so a bare
      // "was it called" is satisfied by that call and the assertion below
      // survived deleting the line it is about.
      into.mockClear()
      await user.click(await screen.findByRole('button',
        { name: HE.merge_pick_option(1, 'ספרי בישול', 22, 2) }))
      await screen.findByRole('button', { name: HE.merge_confirm })
      expect(into, 'nothing was scrolled after the preview arrived')
        .not.toHaveBeenCalled()
      frames.forEach((cb) => cb(0))
      expect(into).toHaveBeenCalled()
    } finally {
      raf.mockRestore()
      delete (Element.prototype as unknown as { scrollIntoView?: unknown })
        .scrollIntoView
    }
  })
})
