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
  columnLevels: [2], gaps: [],
  defaultLevels: 2,
  defaultDepth: 1,
  shelves: [
    { col: 0, level: 0, depth: 1, photos: 3, books: 0 },
    { col: 0, level: 1, depth: 2, photos: 0, books: 0 },
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
  setShelfDepth: vi.fn(), addSection: vi.fn(), removeSection: vi.fn(),
  deleteSelection: vi.fn(), copySelection: vi.fn(), paste: vi.fn(), select: vi.fn(),
})

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
    const acts = actions()
    showPlan({ rooms: [], cases: ['c1'], cells: [] }, acts)

    await userEvent.click(screen.getByRole('button', { name: /מדף, עמודה 1, גובה 1/ }))
    expect(acts.select).toHaveBeenCalledWith(expect.objectContaining({
      cells: [{ caseId: 'c1', sectionId: 's1', col: 0, level: 0 }],
    }))

    // Ctrl ADDS — the same gesture that selects a second room.
    await userEvent.keyboard('{Control>}')
    await userEvent.click(screen.getByRole('button', { name: /מדף, עמודה 1, גובה 2/ }))
    await userEvent.keyboard('{/Control}')
    expect(acts.select).toHaveBeenLastCalledWith(expect.objectContaining({
      cells: [{ caseId: 'c1', sectionId: 's1', col: 0, level: 1 }],
    }))
  })

  it('offers "make space" only while cells are marked, and says how many', () => {
    // ABSENT, not disabled — the house rule. And it never mentions the
    // bookcase: deleting cells does not delete furniture.
    const acts = actions()
    const { unmount } = showPlan({ rooms: [], cases: ['c1'], cells: [] }, acts, emptyCase())
    expect(screen.queryByRole('button', { name: /פינוי/ })).toBeNull()
    unmount()

    showPlan({
      rooms: [], cases: ['c1'],
      cells: [
        { caseId: 'c1', sectionId: 's1', col: 0, level: 0 },
        { caseId: 'c1', sectionId: 's1', col: 0, level: 1 },
      ],
    }, acts, emptyCase())
    const button = screen.getByRole('button', { name: /פינוי 2 תאים/ })
    expect(button).toBeTruthy()
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

    await userEvent.click(screen.getByRole('button', { name: /פינוי 2 תאים/ }))
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

    expect(screen.queryByRole('button', { name: /פינוי/ })).toBeNull()
    expect(screen.getByText(/אינם ריקים/)).toBeTruthy()
    expect(acts.setGaps).not.toHaveBeenCalled()
  })
})
