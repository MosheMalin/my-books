/**
 * The settings panel: what it edits, and what it only reports.
 *
 * The port brought the lab's shelf panel over whole, including a *Photos
 * attached* number input. In the lab that number was part of the document —
 * you typed it so a half-catalogued case looked half-catalogued. Here it is
 * `capture_count`, read off the shelf, with no op behind it: a review measured
 * the panel accepting an edit, the toolbar reporting *saved*, and the value
 * gone on the next load. A control that discards what it takes is worse than
 * one that is absent.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { I18nProvider } from '../../lib/i18n'
import { Inspector, type Actions } from './Inspector'
import type { Selection } from './types'
import type { MergePreview } from '../useMapSync'
import { emptyPlan, newBookcase, withGaps } from '../core/model'
import type { Plan, Section } from '../core/model'
import { mapText } from '../text'

const HE = mapText('he')

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  globalThis.localStorage.clear()
})

const section = (id: string): Section => ({
  id,
  columnLevels: [2, 2, 1], gaps: [],
  defaultLevels: 2,
  defaultDepth: 1,
  shelves: [
    // A shelf the SERVER put here, one it says holds nothing, and — since
    // P6.4c — a slot with no shelf in it at all. The third is what an unbind
    // leaves behind, and what the model calls `free`.
    { col: 0, level: 0, depth: 1, photos: 3, books: 0,
      id: 'sh-1', label: 'המדף העליון' },
    { col: 0, level: 1, depth: 2, photos: 0, books: 0, id: 'sh-2', label: '' },
    // ⚠ BOOKS and no photographs. Every cell in this fixture used to hold
    // zero of both, so the confirm's `shelf.books` half was unmeasured — a
    // review dropped it and the whole ring stayed green, which means a shelf
    // holding books could have left the map with no dialog at all.
    { col: 2, level: 0, depth: 1, photos: 0, books: 4, id: 'sh-books',
      label: 'ספרים בלבד' },
    { col: 1, level: 0, depth: 1, photos: 0, books: 0, free: true },
    // ⚠ Neither `id` nor `free`: the cell this SESSION drew, whose shelf the
    // push is about to mint. It must read as occupied, not as free.
    { col: 1, level: 1, depth: 1, photos: 0, books: 0 },
  ],
})

const plan = (): Plan => ({
  ...emptyPlan(),
  // ⚠ NO name: the fallback is what the panel gets wrong, so the fixture is
  // the state a freshly drawn room is in.
  rooms: [{ id: 'r1', name: '', rect: { x: 0, y: 0, w: 10, h: 8 }, floorId: 'f1' }],
  cases: [{
    ...newBookcase('c1', 'ארון', { x: 1, y: 0, w: 4, h: 1 }, 'S', 'r1', 'f1', 1),
    sections: [section('s1')],
  }],
})

const actions = (): Actions => ({
  renameRoom: vi.fn(), resizeRoom: vi.fn(), renameCase: vi.fn(),
  resizeCase: vi.fn(), setCaseRoom: vi.fn(), turnCase: vi.fn(), setGaps: vi.fn(),
  setColumnCount: vi.fn(), setColumnLevels: vi.fn(), setDefaultLevels: vi.fn(),
  applyDefaultLevels: vi.fn(), setDefaultDepth: vi.fn(), applyDefaultDepth: vi.fn(),
  moveSection: vi.fn(), attachPhoto: vi.fn(async () => {}),
  setShelfDepth: vi.fn(), addSection: vi.fn(), removeSection: vi.fn(),
  deleteSelection: vi.fn(), copySelection: vi.fn(), paste: vi.fn(), select: vi.fn(),
  shelvesOffTheMap: vi.fn(async () => []), bindShelf: vi.fn(),
  unbindShelf: vi.fn(),
  previewMerge: vi.fn(async () => NOTHING_MOVES), mergeShelf: vi.fn(),
  // P6.5c: the panel asks when this cell's shelf was last read.
  shelfOverview: vi.fn(async () => ({
                     shelf: { id: 'sh', label: '', depth_count: 1,
                              virtual: false, created_at: null,
                              capture_count: 0, book_count: 0, address: null,
                              formerly: [] },
                     depths: [], last_read_at: null,
                   })),
})

/** A preview that refuses nothing and moves nothing — the neutral default. */
const NOTHING_MOVES: MergePreview = {
  absorbed_id: 'a', survivor_id: 'b', refused: null, already: false,
  depth: 1, books: 0, copies: [], photos: [], clashes: [],
  answers_moved: 0, identities_moved: 0,
}

const onShelf: Selection = {
  rooms: [], cases: ['c1'],
  cells: [{ caseId: 'c1', sectionId: 's1', col: 0, level: 0 }],
}

const show = (selection: Selection) =>
  render(
    <I18nProvider>
      <Inspector
        doc={{ plan: plan(), seq: 0 }}
        floorId="f1"
        selection={selection}
        actions={actions()}
        renaming={null}
        onRenamed={() => {}}
      />
    </I18nProvider>,
  )

describe('the case panel on a phone', () => {
  it('opens with the elevation in reach, not under four fields', () => {
    // ⚠ The panel is 38% of a phone. A review measured the elevation grid
    // 351px below its top and the per-column controls 580px below — two
    // panel-heights of scrolling to reach the thing the bookcase was selected
    // FOR. The details fold's closed summary already says name · size ·
    // facing, so nothing is hidden that it does not state.
    vi.stubGlobal('matchMedia', (q: string) => ({
      matches: q.includes('640px'), media: q, addEventListener() {},
      removeEventListener() {}, addListener() {}, removeListener() {},
      onchange: null, dispatchEvent: () => false,
    }))
    show({ rooms: [], cases: ['c1'], cells: [] })
    const fold = screen.getByRole('button', { name: new RegExp(HE.case_details) })
    expect(fold).toHaveAttribute('aria-expanded', 'false')
    // The grid is still there — closing the fold is what puts it on screen.
    expect(screen.getByText(HE.col_head(1))).toBeInTheDocument()
  })

  it('calls an unnamed room what its own controls call it', () => {
    // ⚠ ' · ב' + 'ללא שם' is not Hebrew — the panel read "בללא שם" — and it
    // disagreed with the Select two rows above, which has always called this
    // room "חדר 10×8". One room, one name, in the same fold.
    show({ rooms: [], cases: ['c1'], cells: [] })
    // The Select offers the room by that name, and the note names it too —
    // which is the point: they used to disagree.
    const said = screen.getAllByText(new RegExp(HE.unnamed_room(10, 8)))
    expect(said.length).toBeGreaterThan(1)
    const note = said.find((el) => el.classList.contains('note'))
    expect(note, 'the case note never names the room').toBeDefined()
    expect(note!.textContent).not.toContain(`ב${HE.unnamed}`)
  })

  it('puts the bookcase’s own delete ABOVE the grid, not below it (P6.7b)', () => {
    // The owner, walking his own library: *"while editing cells/shelves,
    // clicking delete can only delete cells, not the entire bookcase."* It
    // could — the control was the LAST thing in the panel, below a
    // 38-cell grid and the shelf panel, past two other destructive buttons.
    // A control nobody can find is not a control.
    //
    // Asserted as document ORDER, because that is the claim. Anything else
    // (it exists, it is labelled, it calls the action) was already true on
    // the day the owner could not find it.
    show({ rooms: [], cases: ['c1'], cells: [] })
    const remove = screen.getByRole('button', { name: HE.delete_case })
    const grid = screen.getByText(HE.col_head(1))
    expect(remove.compareDocumentPosition(grid)
      & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('never offers a SECOND control by that name', () => {
    // Moving a destructive control is safe; duplicating one is the
    // accessible-name collision CLAUDE.md records, in the worst place to
    // earn it.
    show({ rooms: [], cases: ['c1'], cells: [] })
    expect(screen.getAllByRole('button', { name: HE.delete_case })).toHaveLength(1)
  })

  it('leaves the fold open on anything bigger', () => {
    show({ rooms: [], cases: ['c1'], cells: [] })
    expect(screen.getByRole('button', { name: new RegExp(HE.case_details) }))
      .toHaveAttribute('aria-expanded', 'true')
  })
})

describe('the shelf panel', () => {
  it('reports the photo count as a fact, with no way to type over it', () => {
    show(onShelf)
    expect(screen.getByText(HE.photos_attached)).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    // ⚠ The measured defect: a spinbutton that took an edit and threw it away.
    expect(screen.queryByRole('spinbutton', { name: HE.photos_attached }))
      .not.toBeInTheDocument()
    expect(screen.queryByRole('spinbutton', { name: /photos/i }))
      .not.toBeInTheDocument()
  })

  it('still edits the one thing it CAN save — this shelf\'s own depth', () => {
    show(onShelf)
    expect(screen.getByRole('spinbutton', { name: HE.shelf_depth }))
      .toHaveValue(1)
  })

  it('speaks Hebrew where the port left English', () => {
    show({ rooms: ['r1'], cases: [], cells: [] })
    expect(screen.getByRole('heading', { name: HE.room })).toBeInTheDocument()
    expect(screen.getByText(HE.cases_attached)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: HE.delete_room })).toBeInTheDocument()
  })
})

describe('the elevation, with cells switched off (P6.3.2b)', () => {
  const holed = (): Plan => {
    const p = plan()
    const sec = p.cases[0]!.sections[0]!
    p.cases[0]!.sections[0] = withGaps(sec, [{ col: 0, level: 0 }], true)
    return p
  }

  const emptyCase = (): Plan => {
    const p = plan()
    const sec = p.cases[0]!.sections[0]!
    p.cases[0]!.sections[0] = {
      ...sec,
      shelves: sec.shelves.map((sh) => ({ ...sh, depth: 1, photos: 0, books: 0 })),
    }
    return p
  }

  const showPlan = (selection: Selection, acts: Actions, custom = plan()) =>
    render(
      <I18nProvider>
        <Inspector
          doc={{ plan: custom, seq: 0 }}
          floorId="f1"
          selection={selection}
          actions={acts}
          renaming={null}
          onRenamed={() => {}}
        />
      </I18nProvider>,
    )

  it('draws a hole that says what tapping it DOES, and brings the shelf back', async () => {
    // The owner's second sentence: *"user should be able to click on a
    // 'missing' cell and make it a real shelf again."* The accessible name
    // names the action, because "gap" names a state and a state is not
    // something a button can be pressed to do.
    const acts = actions()
    showPlan({ rooms: [], cases: ['c1'], cells: [] }, acts, holed())

    const hole = screen.getByRole('button', { name: /החזרת מדף/ })
    await userEvent.click(hole)

    expect(acts.setGaps).toHaveBeenCalledWith('c1', 's1', [{ col: 0, level: 0 }], false)
    // …and it is NOT offered as a shelf: a hole holds nothing to select.
    expect(screen.queryByRole('button', { name: /^מדף, עמודה 1, גובה 1$/ })).toBeNull()
  })

  it('marks several cells with the modifier the plan already uses', async () => {
    // ⚠ The selection prop ALREADY holds a cell, and that is the whole point.
    // A review measured the first version of this test: with `cells: []`,
    // `markCell(sel, B, true)` and `markCell(sel, B, false)` both answer
    // `[B]`, so deleting the modifier from `Elevation.tsx` entirely left 305
    // tests green. Starting from a held cell makes ADD and REPLACE tell
    // themselves apart in one assertion.
    //
    // ⚠⚠ `userEvent.setup()`, not the direct API: the direct one builds a
    // fresh instance per call, so a held `{Control>}` never reaches a
    // separate `.click()` — the same review measured the received call
    // arriving with `ctrlKey: false`, i.e. the test exercising a plain click
    // under a comment that said Ctrl.
    const A = { caseId: 'c1', sectionId: 's1', col: 0, level: 0 }
    const acts = actions()
    showPlan({ rooms: [], cases: ['c1'], cells: [A] }, acts)
    const user = userEvent.setup()

    await user.keyboard('{Control>}')
    await user.click(screen.getByRole('button', { name: /מדף, עמודה 1, גובה 2/ }))
    await user.keyboard('{/Control}')
    expect(acts.select).toHaveBeenLastCalledWith(expect.objectContaining({
      cells: [A, { caseId: 'c1', sectionId: 's1', col: 0, level: 1 }],
    }))
  })

  it('replaces the marked set on a plain click', async () => {
    const A = { caseId: 'c1', sectionId: 's1', col: 0, level: 0 }
    const acts = actions()
    showPlan({ rooms: [], cases: ['c1'], cells: [A] }, acts)

    await userEvent.click(screen.getByRole('button', { name: /מדף, עמודה 1, גובה 2/ }))
    expect(acts.select).toHaveBeenLastCalledWith(expect.objectContaining({
      cells: [{ caseId: 'c1', sectionId: 's1', col: 0, level: 1 }],
    }))
  })

  it('offers "make space" only while cells are marked, and says how many', () => {
    // ABSENT, not disabled — the house rule. And it never mentions the
    // bookcase: deleting cells does not delete furniture.
    const acts = actions()
    const { unmount } = showPlan({ rooms: [], cases: ['c1'], cells: [] }, acts, emptyCase())
    expect(screen.queryByRole('button', { name: /השארת מקום/ })).toBeNull()
    unmount()

    showPlan({
      rooms: [], cases: ['c1'],
      cells: [
        { caseId: 'c1', sectionId: 's1', col: 0, level: 0 },
        { caseId: 'c1', sectionId: 's1', col: 0, level: 1 },
      ],
    }, acts, emptyCase())
    expect(screen.getByRole('button', { name: /השארת מקום \(2 תאים\)/ })).toBeTruthy()
  })

  it('switches off exactly the marked cells, with no confirm in the way', async () => {
    // No dialog: the cells are empty by construction (the server refuses
    // otherwise) and it is reversible by tapping the hole. A dialog in front
    // of a gesture that destroys nothing is what teaches people to click
    // through the ones that do.
    const acts = actions()
    showPlan({
      rooms: [], cases: ['c1'],
      cells: [
        { caseId: 'c1', sectionId: 's1', col: 0, level: 0 },
        { caseId: 'c1', sectionId: 's1', col: 0, level: 1 },
      ],
    }, acts, emptyCase())

    await userEvent.click(screen.getByRole('button', { name: /השארת מקום \(2 תאים\)/ }))
    expect(acts.setGaps).toHaveBeenCalledWith(
      'c1', 's1', [{ col: 0, level: 0 }, { col: 0, level: 1 }], true)
  })

  it('shows the depth panel for one marked cell and not for several', () => {
    // `onlyCell`, which is `only`'s rule one level down: a panel that edits
    // ONE shelf's depth cannot answer for a set.
    const acts = actions()
    const { unmount } = showPlan({
      rooms: [], cases: ['c1'],
      cells: [{ caseId: 'c1', sectionId: 's1', col: 0, level: 0 }],
    }, acts)
    expect(screen.queryByLabelText('עומק המדף הזה')).toBeTruthy()
    unmount()

    showPlan({
      rooms: [], cases: ['c1'],
      cells: [
        { caseId: 'c1', sectionId: 's1', col: 0, level: 0 },
        { caseId: 'c1', sectionId: 's1', col: 0, level: 1 },
      ],
    }, acts)
    expect(screen.queryByLabelText('עומק המדף הזה')).toBeNull()
  })
  it('says why in Hebrew instead of offering a delete the server would refuse', () => {
    // The 409 arrives in English, after the press. MapScreen's own rule is
    // that a refusal the screen could have stated belongs BEFORE it — the
    // same reason `limits.ts` mirrors the ceilings. The server refusal stays
    // as the backstop for what another tab did, and for a NAMED empty cell,
    // which the document cannot see at all.
    const acts = actions()
    const p = plan()
    // level 0 of the fixture holds 3 photographs.
    showPlan({
      rooms: [], cases: ['c1'],
      cells: [{ caseId: 'c1', sectionId: 's1', col: 0, level: 0 }],
    }, acts, p)

    expect(screen.queryByRole('button', { name: /השארת מקום/ })).toBeNull()
    // Named per CAUSE: this cell holds photographs, so the sentence says so
    // and names a remedy that exists — not "clear them first" of nothing.
    expect(screen.getByText(/יש צילום/)).toBeTruthy()
    expect(acts.setGaps).not.toHaveBeenCalled()
  })
  it('lets a FINGER mark a set, since a tap carries no modifier', async () => {
    // A UX review measured this: `onClick`'s ctrlKey/metaKey/shiftKey are all
    // false for a touch tap, and the tree had no long-press and no toggle —
    // so on a phone the marked set could never exceed one cell, and the whole
    // premise of the item ("a television is a rectangle of cells") was a
    // desktop feature that nothing on screen mentioned.
    //
    // The latch is absent until a cell is marked, states its own rule, and
    // makes plain taps accumulate. `userEvent.click` sends no modifiers, so
    // this test IS the touch path.
    const A = { caseId: 'c1', sectionId: 's1', col: 0, level: 0 }
    const acts = actions()
    showPlan({ rooms: [], cases: ['c1'], cells: [A] }, acts, emptyCase())

    const latch = screen.getByRole('button', { name: 'סימון תאים נוספים' })
    expect(latch.getAttribute('aria-pressed')).toBe('false')
    await userEvent.click(latch)
    expect(latch.getAttribute('aria-pressed')).toBe('true')

    await userEvent.click(screen.getByRole('button', { name: /מדף, עמודה 1, גובה 2/ }))
    expect(acts.select).toHaveBeenLastCalledWith(expect.objectContaining({
      cells: [A, { caseId: 'c1', sectionId: 's1', col: 0, level: 1 }],
    }))
  })

  it('explains a hole on SCREEN, not only in a tooltip a phone never shows', () => {
    const acts = actions()
    showPlan({ rooms: [], cases: ['c1'], cells: [] }, acts, holed())
    expect(screen.getByText(/לחיצה מחזירה מדף/)).toBeTruthy()
  })
})

describe('putting a shelf in a slot, and taking one out (P6.4c)', () => {
  const showWith = (selection: Selection, acts: Actions) =>
    render(
      <I18nProvider>
        <Inspector
          doc={{ plan: plan(), seq: 0 }}
          floorId="f1"
          selection={selection}
          actions={acts}
          renaming={null}
          onRenamed={() => {}}
        />
      </I18nProvider>,
    )

  const cell = (col: number, level: number): Selection => ({
    rooms: [], cases: ['c1'],
    cells: [{ caseId: 'c1', sectionId: 's1', col, level }],
  })

  it('offers nothing to edit on an empty slot but the way to fill it', () => {
    // ⚠ The depth box most of all. `PATCH .../shelves/{col}/{level}` answers
    // 404 for a slot with no shelf, and the toolbar would have said "saved" —
    // a control that discards what it takes, which this panel already has a
    // rule against one field down.
    showWith(cell(1, 0), actions())
    expect(screen.getByText(HE.cell_has_no_shelf)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: HE.put_a_shelf_here }))
      .toBeInTheDocument()
    expect(screen.queryByLabelText(HE.shelf_depth)).toBeNull()
    expect(screen.queryByRole('button', { name: HE.shelf_take_off_map }))
      .toBeNull()
  })

  it('treats a cell this session DREW as occupied, not as free', () => {
    // ⚠ The reason `free` is a field rather than `!id`. A cell the owner just
    // added has no shelf id either, and the push is about to mint one — so
    // offering *put a shelf here* would be offering a 409 for a slot that is
    // about to be taken.
    showWith(cell(1, 1), actions())
    expect(screen.queryByRole('button', { name: HE.put_a_shelf_here })).toBeNull()
    expect(screen.getByLabelText(HE.shelf_depth)).toBeInTheDocument()
  })

  it('lists the shelves that stand nowhere, and binds the one picked', async () => {
    const user = userEvent.setup()
    const acts = actions()
    acts.shelvesOffTheMap = vi.fn(async () => [
      { id: 'sh-photo', label: 'ליד החלון', capture_count: 2, book_count: 7 },
    ])
    showWith(cell(1, 0), acts)

    await user.click(screen.getByRole('button', { name: HE.put_a_shelf_here }))
    const option = await screen.findByRole('button', {
      name: HE.pick_shelf_option(1, 'ליד החלון', 7, 2),
    })
    await user.click(option)

    // 0-BASED here, 1-based on the wire — the hook does that shift, and it is
    // gated in `bind.test.tsx`. Handing it over already shifted is how a book
    // gets filed one cell up.
    expect(acts.bindShelf).toHaveBeenCalledWith(
      'sh-photo', 's1', 1, 0, 'ליד החלון')
  })

  it('gives two unnamed shelves two different names to press', async () => {
    // The collision CLAUDE.md records, and unnamed is the COMMON case here:
    // these are the photo-born half of the population, and a shelf is never
    // required to be named.
    const user = userEvent.setup()
    const acts = actions()
    acts.shelvesOffTheMap = vi.fn(async () => [
      { id: 'a', label: '', capture_count: 0, book_count: 0 },
      { id: 'b', label: '', capture_count: 0, book_count: 0 },
    ])
    showWith(cell(1, 0), acts)
    await user.click(screen.getByRole('button', { name: HE.put_a_shelf_here }))

    await screen.findByRole('button',
      { name: HE.pick_shelf_option(1, HE.shelf_unnamed, 0, 0) })
    const both = screen.getAllByRole('button', {
      name: new RegExp(HE.shelf_unnamed),
    })
    expect(both).toHaveLength(2)
    expect(both[0]!.getAttribute('aria-label'))
      .not.toBe(both[1]!.getAttribute('aria-label'))
  })

  it('says so when every shelf is already on the map', async () => {
    const user = userEvent.setup()
    const acts = actions()
    showWith(cell(1, 0), acts)
    await user.click(screen.getByRole('button', { name: HE.put_a_shelf_here }))
    expect(await screen.findByText(HE.no_shelves_off_the_map))
      .toBeInTheDocument()
  })

  it('takes an EMPTY shelf off the map without asking', async () => {
    // ⚠ The rule the section header already follows: a dialog in front of a
    // gesture that destroys nothing is what teaches people to click through
    // the ones that do (owner, drawing with it).
    const user = userEvent.setup()
    const acts = actions()
    const confirm = vi.fn(() => true)
    vi.stubGlobal('confirm', confirm)
    showWith(cell(0, 1), acts)

    await user.click(screen.getByRole('button', { name: HE.shelf_take_off_map }))
    expect(confirm).not.toHaveBeenCalled()
    expect(acts.unbindShelf).toHaveBeenCalledWith(
      'sh-2', 's1', 0, 1, HE.shelf_unnamed)
    vi.unstubAllGlobals()
  })

  it('asks before taking one that holds photographs, and says it is undoable', async () => {
    const user = userEvent.setup()
    const acts = actions()
    const confirm = vi.fn(() => false)
    vi.stubGlobal('confirm', confirm)
    showWith(cell(0, 0), acts)

    await user.click(screen.getByRole('button', { name: HE.shelf_take_off_map }))
    expect(confirm).toHaveBeenCalledWith(HE.shelf_take_off_map_confirm(0, 3))
    expect(acts.unbindShelf).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('names the shelf standing in the cell, which the grid cannot', () => {
    // A cell is 44 pixels wide. The panel is where "which shelf is this"
    // gets an answer — and it is the question the whole item is about.
    showWith(cell(0, 0), actions())
    expect(screen.getByText(HE.shelf_is_named('המדף העליון')))
      .toBeInTheDocument()
  })
})

describe('the predicates the P6.4c panel rides on', () => {
  const showWith = (selection: Selection, acts: Actions) =>
    render(
      <I18nProvider>
        <Inspector
          doc={{ plan: plan(), seq: 0 }}
          floorId="f1"
          selection={selection}
          actions={acts}
          renaming={null}
          onRenamed={() => {}}
        />
      </I18nProvider>,
    )

  const cell = (col: number, level: number): Selection => ({
    rooms: [], cases: ['c1'],
    cells: [{ caseId: 'c1', sectionId: 's1', col, level }],
  })

  it('asks before taking off a shelf that holds BOOKS and no photographs', async () => {
    // ⚠ The half that matters most, and the one that was unmeasured: a
    // review changed the test to `shelf.photos === 0` and nothing failed.
    const user = userEvent.setup()
    const acts = actions()
    const confirm = vi.fn(() => false)
    vi.stubGlobal('confirm', confirm)
    showWith(cell(2, 0), acts)

    await user.click(screen.getByRole('button', { name: HE.shelf_take_off_map }))
    expect(confirm).toHaveBeenCalledWith(HE.shelf_take_off_map_confirm(4, 0))
    expect(acts.unbindShelf).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('offers no unbind on a cell whose shelf the server has never seen', () => {
    // The predicate the paste bug rode on: a cell this session drew has no
    // `id`, so there is nothing to take off the map — and a control that
    // sends a request naming `undefined` is worse than one that is absent.
    showWith(cell(1, 1), actions())
    expect(screen.queryByRole('button', { name: HE.shelf_take_off_map }))
      .toBeNull()
  })

  it('says the list could not be READ, never that it is empty', async () => {
    // ⚠⚠ Absent is not unknown. With `GET /shelves` down, the picker
    // announced "every shelf is already on the map" while FORTY stood
    // nowhere — including the owner's real 22-book one. Measured in a
    // browser; the same shape this project already has on record about "no
    // admin" beside a card saying two users.
    const user = userEvent.setup()
    const acts = actions()
    acts.shelvesOffTheMap = vi.fn(async () => { throw new Error('offline') })
    showWith(cell(1, 0), acts)

    await user.click(screen.getByRole('button', { name: HE.put_a_shelf_here }))
    expect(await screen.findByText(HE.shelf_list_failed)).toBeInTheDocument()
    expect(screen.queryByText(HE.no_shelves_off_the_map)).toBeNull()

    // ...and a way out that is not "select a different cell".
    acts.shelvesOffTheMap = vi.fn(async () => [])
    await user.click(screen.getByRole('button', { name: HE.shelf_list_retry }))
    expect(await screen.findByText(HE.no_shelves_off_the_map))
      .toBeInTheDocument()
  })
})

describe('what the phone walk found (P6.4c)', () => {
  const showWith = (selection: Selection, acts: Actions) =>
    render(
      <I18nProvider>
        <Inspector
          doc={{ plan: plan(), seq: 0 }}
          floorId="f1"
          selection={selection}
          actions={acts}
          renaming={null}
          onRenamed={() => {}}
        />
      </I18nProvider>,
    )

  const cell = (col: number, level: number): Selection => ({
    rooms: [], cases: ['c1'],
    cells: [{ caseId: 'c1', sectionId: 's1', col, level }],
  })

  it('calls an empty cell an empty cell, in its own legend', () => {
    // One fieldset made two contradictory claims: `מדף · עמודה 1 · גובה 1`
    // directly above `אין כאן מדף.`
    showWith(cell(1, 0), actions())
    expect(screen.getByText(HE.empty_cell_legend('', 2, 1)))
      .toBeInTheDocument()
    expect(screen.queryByText(HE.shelf_legend('', 2, 1))).toBeNull()
  })

  it('brings the panel into view, because on a phone it is 957px down', () => {
    // ⚠ Measured: the panel begins 957px inside a scroller 252px tall — 31%
    // of a 375x812 screen — with `scrollTop` 0 before the tap and 0 after.
    // *Tap a cell → the panel at the bottom* read as *nothing happens*.
    const into = vi.fn()
    // jsdom has none, which is why the call site is optional-chained.
    ;(Element.prototype as unknown as { scrollIntoView: unknown })
      .scrollIntoView = into
    showWith(cell(0, 0), actions())
    expect(into).toHaveBeenCalled()
    delete (Element.prototype as unknown as { scrollIntoView?: unknown })
      .scrollIntoView
  })

  it('gives a different free cell a picker of its own', () => {
    // Without a key the component stays mounted across cells, so the second
    // free cell opens holding the first one's list and its `open` flag.
    const acts = actions()
    const { rerender } = showWith(cell(1, 0), acts)
    const first = screen.getByRole('button', { name: HE.put_a_shelf_here })
    rerender(
      <I18nProvider>
        <Inspector
          doc={{ plan: plan(), seq: 0 }}
          floorId="f1"
          selection={cell(1, 1)}
          actions={acts}
          renaming={null}
          onRenamed={() => {}}
        />
      </I18nProvider>,
    )
    // (1,1) has a shelf, so the control is gone entirely — the point is that
    // nothing of the previous cell's picker survived the change.
    expect(screen.queryByRole('button', { name: HE.put_a_shelf_here }))
      .not.toBe(first)
  })

  it('says a shelf holds nothing rather than counting two zeroes', async () => {
    const user = userEvent.setup()
    const acts = actions()
    acts.shelvesOffTheMap = vi.fn(async () => [
      { id: 'a', label: 'ריקה', capture_count: 0, book_count: 0 },
    ])
    showWith(cell(1, 0), acts)
    await user.click(screen.getByRole('button', { name: HE.put_a_shelf_here }))
    expect(await screen.findByText(HE.shelf_holds_nothing)).toBeInTheDocument()
    expect(screen.queryByText(HE.shelf_holds(0, 0))).toBeNull()
  })
})

describe('filing a photo from the bookcase panel (P6.7d)', () => {
  /** The owner asked for the gesture in BOTH places — *"on the shelf itself
   *  and also in the bookcase (when a shelf is selected)"* — and it is one
   *  component, so the two cannot drift into two different promises about
   *  what filing a photo costs. */
  it('offers it on the selected cell, and files against THAT shelf', async () => {
    const acts = actions()
    render(
      <I18nProvider>
        <Inspector doc={{ plan: plan(), seq: 0 }} floorId="f1"
                   selection={onShelf} actions={acts} renaming={null}
                   onRenamed={() => {}} />
      </I18nProvider>,
    )

    await userEvent.upload(
      screen.getByLabelText('הוספת תמונה'),
      new File([new Uint8Array([1])], 'a.jpg', { type: 'image/jpeg' }))

    // ⚠ Depth 1 from the map, always: this panel has no depth picker, and a
    // photo filed at a row the shelf does not have is the one thing
    // `new_capture` refuses. The shelf screen is where a row is chosen.
    // ⚠ `expect.any(File)` and then the name read off the call. A File's
    // `name` lives on the prototype, so `objectContaining({name})` never
    // matches one — it reports "File {}" and looks like the wrong argument.
    expect(acts.attachPhoto).toHaveBeenCalledWith('sh-1', 1, expect.any(File))
    const [, , sent] = vi.mocked(acts.attachPhoto).mock.calls[0]!
    expect(sent.name).toBe('a.jpg')
  })

  it('offers nothing on a cell the server says is empty', async () => {
    // There is no shelf to file against. Every control in that branch would
    // be an operation on a row that does not exist (P6.4c).
    render(
      <I18nProvider>
        <Inspector doc={{ plan: plan(), seq: 0 }} floorId="f1"
                   selection={{ rooms: [], cases: ['c1'],
                                cells: [{ caseId: 'c1', sectionId: 's1',
                                          col: 0, level: 1 }] }}
                   actions={actions()} renaming={null} onRenamed={() => {}} />
      </I18nProvider>,
    )
    expect(screen.queryByLabelText('הוספת תמונה')).toBeNull()
  })
})

