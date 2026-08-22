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

import { I18nProvider } from '../../lib/i18n'
import { Inspector, type Actions } from './Inspector'
import type { Selection } from './types'
import { emptyPlan, newBookcase } from '../core/model'
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
  columnLevels: [2],
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
  resizeCase: vi.fn(), setCaseRoom: vi.fn(), turnCase: vi.fn(),
  setColumnCount: vi.fn(), setColumnLevels: vi.fn(), setDefaultLevels: vi.fn(),
  applyDefaultLevels: vi.fn(), setDefaultDepth: vi.fn(), applyDefaultDepth: vi.fn(),
  setShelfDepth: vi.fn(), addSection: vi.fn(), removeSection: vi.fn(),
  deleteSelection: vi.fn(), copySelection: vi.fn(), paste: vi.fn(), select: vi.fn(),
})

const onShelf: Selection = {
  rooms: [], cases: ['c1'],
  shelf: { caseId: 'c1', sectionId: 's1', col: 0, level: 0 },
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
    show({ rooms: [], cases: ['c1'], shelf: null })
    const fold = screen.getByRole('button', { name: new RegExp(HE.case_details) })
    expect(fold).toHaveAttribute('aria-expanded', 'false')
    // The grid is still there — closing the fold is what puts it on screen.
    expect(screen.getByText(HE.col_head(1))).toBeInTheDocument()
  })

  it('calls an unnamed room what its own controls call it', () => {
    // ⚠ ' · ב' + 'ללא שם' is not Hebrew — the panel read "בללא שם" — and it
    // disagreed with the Select two rows above, which has always called this
    // room "חדר 10×8". One room, one name, in the same fold.
    show({ rooms: [], cases: ['c1'], shelf: null })
    // The Select offers the room by that name, and the note names it too —
    // which is the point: they used to disagree.
    const said = screen.getAllByText(new RegExp(HE.unnamed_room(10, 8)))
    expect(said.length).toBeGreaterThan(1)
    const note = said.find((el) => el.classList.contains('note'))
    expect(note, 'the case note never names the room').toBeDefined()
    expect(note!.textContent).not.toContain(`ב${HE.unnamed}`)
  })

  it('leaves the fold open on anything bigger', () => {
    show({ rooms: [], cases: ['c1'], shelf: null })
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
    show({ rooms: ['r1'], cases: [], shelf: null })
    expect(screen.getByRole('heading', { name: HE.room })).toBeInTheDocument()
    expect(screen.getByText(HE.cases_attached)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: HE.delete_room })).toBeInTheDocument()
  })
})
