/**
 * The drill, both ways (P6.5c).
 *
 * UI_PLAN §3's three levels were all BUILT — as editing. The plan selects a
 * bookcase, the elevation selects a cell, and `#/map/<shelfId>` has been the
 * shelf screen since P2.8. What was missing is that nothing ever linked
 * between them: the only route into level 3 was a typed URL, and there was no
 * route back onto the drawing at all.
 *
 * Each decision below is mutation-checked. The two that carry the most are
 * the ones about a shelf that is NOT where you are looking — a cell on
 * another storey, and a shelf in another site — because those are the ones a
 * test written against a one-floor fixture cannot see.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { userEvent } from '../test/user'

import { I18nProvider } from '../lib/i18n'
import { parseHash, planHash } from '../lib/route'
import MapScreen from './MapScreen'
import { emptyPlan, newBookcase, type Plan } from './core/model'
import type { Selection } from './ui/types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  globalThis.location.hash = ''
})

const OVERVIEW = (stale: number, last: string | null) => ({
  shelf: { id: 'sh-1', label: '', depth_count: 1, virtual: false,
           created_at: null, capture_count: 0, book_count: 0, address: null,
           formerly: [] },
  depths: Array.from({ length: Math.max(stale, 1) }, (_, i) => ({
    depth: i + 1, last_read_at: last, is_stale: i < stale,
  })),
  last_read_at: last,
})

/** Give every drawn slot the SERVER id it would have. A freshly drawn
 *  bookcase's shelves carry none until the push comes back, and every control
 *  in the panel that names a shelf is guarded on it — so a fixture without
 *  ids silently renders a panel with no actions at all. */
function saved(bc: ReturnType<typeof newBookcase>) {
  return {
    ...bc,
    sections: bc.sections.map((sec) => ({
      ...sec,
      shelves: sec.shelves.map((sh) => ({ ...sh, id: `${bc.id}-shelf` })),
    })),
  }
}

/** Two storeys, one bookcase on each. Built with the real factories, because
 *  a hand-written `Section` is the fixture-you-invented trap: mine had no
 *  `columnLevels` and the canvas threw before a single assertion ran. */
function twoStoreys(): Plan {
  return {
    ...emptyPlan(),
    floors: [{ id: 'f1', name: 'קרקע' }, { id: 'f2', name: 'עליונה' }],
    rooms: [],
    cases: [saved(newBookcase('cA', 'למטה', { x: 0, y: 0, w: 4, h: 1 },
                              'S', null, 'f1', 1)),
            saved(newBookcase('cB', 'למעלה', { x: 0, y: 0, w: 4, h: 1 },
                              'S', null, 'f2', 1))],
  }
}

const ONE_SITE = {
  sites: [{ id: 'st1', name: 'הבית' }],
  siteId: 'st1',
  onSite: () => {},
  onAddSite: () => {},
  onRenameSite: () => {},
  onRemoveSite: () => {},
  onUndoLastEdit: () => {},
}

function editor(initialSelection?: Selection, overview = OVERVIEW(0, null)) {
  return render(
    <I18nProvider>
      <MapScreen
        initialPlan={twoStoreys()}
        {...(initialSelection ? { initialSelection } : {})}
        onChange={() => {}}
        saved="saved"
        onReload={() => {}}
        site={ONE_SITE}
        shelves={{
          offTheMap: async () => [],
          bind: () => {}, unbind: () => {}, merge: () => {},
          previewMerge: async () => ({
            absorbed_id: 'a', survivor_id: 'b', refused: null, already: false,
            depth: 1, books: 0, copies: [], photos: [], clashes: [],
            answers_moved: 0, identities_moved: 0,
          }),
          overview: async () => overview,
        } as never}
      />
    </I18nProvider>,
  )
}

/** ⚠ The CASE stays selected. `pickCell` keeps `cases` (`ui/types.ts`), and
 *  the shelf panel is drawn INSIDE the bookcase panel — a selection carrying
 *  only cells renders the "nothing selected" note, which is what a
 *  hand-written one did here and what `PlanScreen.cellOf` was building. */
const upstairsCell: Selection = {
  rooms: [], cases: ['cB'],
  cells: [{ caseId: 'cB', sectionId: 'cB:s1', col: 0, level: 0 }],
}

describe('the way down: a cell opens its shelf', () => {
  it('offers a LINK to the shelf screen, at that shelf’s own route',
     async () => {
    // A link, not a button: it is a place. It opens in a new tab, copies as a
    // URL, and reads as one to a screen reader.
    editor(upstairsCell)
    const open = await screen.findByRole('link',
                                         { name: 'פתחו את המדף הזה →' })
    expect(open).toHaveAttribute('href', '#/map/cB-shelf')
  })

  it('says when the cell was last read, and marks a stale row', async () => {
    // VISION §7: "a shelf on the map carries its declared depth, so '3 rows,
    // back two not read since March' is answerable from the map". The FIRST
    // clause — that there is something stale here — belongs on the map; the
    // sentence naming which rows stays on the shelf screen, because building
    // it twice out of two string tables is how one rule becomes two.
    editor(upstairsCell, OVERVIEW(2, '2026-03-11T10:00:00+00:00'))
    await screen.findByText('נקרא לאחרונה')
    const dot = await screen.findByTitle(
      '2 שורות לא נקראו מזמן — פתחו את המדף כדי לראות אילו')
    expect(dot).toBeInTheDocument()
  })

  it('asks the server ONCE for a cell, not once per render', async () => {
    // ⚠ Measured at 375x812 before this was pinned: **four** requests for one
    // selected cell. Two unstable identities, one per layer — `MapScreen`
    // rebuilds `actions` as an object literal every render, and `PlanScreen`
    // wrapped the fetch in a fresh arrow. In production that is a request
    // storm behind a tap; in a ring it is invisible unless somebody counts.
    //
    // The harness below is `PlanScreen`'s SHAPE: a parent that re-renders and
    // rebuilds the `shelves` bag inline. Rendering `MapScreen` directly could
    // not catch it — its props object would never change identity, which is
    // exactly why the first version of this test passed on the broken code.
    const ask = vi.fn(
      async (_shelfId: string) => OVERVIEW(0, '2026-03-11T10:00:00+00:00'))
    function Harness() {
      const [n, setN] = useState(0)
      return (
        <I18nProvider>
          <button type="button" onClick={() => setN(n + 1)}>bump {n}</button>
          <MapScreen
            initialPlan={twoStoreys()}
            initialSelection={upstairsCell}
            onChange={() => {}} saved="saved" onReload={() => {}}
            site={ONE_SITE}
            shelves={{
              offTheMap: async () => [], bind: () => {}, unbind: () => {},
              merge: () => {}, previewMerge: async () => ({}),
              overview: (id: string) => ask(id),
            } as never}
          />
        </I18nProvider>
      )
    }
    render(<Harness />)

    await screen.findByText('נקרא לאחרונה')
    expect(ask).toHaveBeenCalledTimes(1)
    expect(ask).toHaveBeenCalledWith('cB-shelf')

    await userEvent.click(screen.getByRole('button', { name: 'bump 0' }))
    await screen.findByRole('button', { name: 'bump 1' })
    expect(ask).toHaveBeenCalledTimes(1)
  })

  it('says nothing at all when the lookup fails', async () => {
    // An editor that grows a grey apology every time a request loses is worse
    // than one that shows what it has. This is a fact ABOUT the cell, not the
    // cell — the panel's own controls all still work.
    render(
      <I18nProvider>
        <MapScreen
          initialPlan={twoStoreys()}
          initialSelection={upstairsCell}
          onChange={() => {}} saved="saved" onReload={() => {}}
          site={ONE_SITE}
          shelves={{
            offTheMap: async () => [], bind: () => {}, unbind: () => {},
            merge: () => {}, previewMerge: async () => ({}),
            overview: async () => { throw new Error('down') },
          } as never}
        />
      </I18nProvider>,
    )
    await screen.findByRole('link', { name: 'פתחו את המדף הזה →' })
    expect(screen.queryByText('נקרא לאחרונה')).not.toBeInTheDocument()
  })
})

describe('the way back: the drawing opens on the right storey', () => {
  it('shows the storey the selection is on, not the one last looked at',
     async () => {
    // ⚠ The defect this pins is older than the deep link. `initialSelection`
    // is ALSO how a selection survives a re-derive, and the storey came from
    // `localStorage` — so taking a shelf off the map while upstairs could hand
    // the rebuilt editor a selection on the ground floor, which `visible`
    // then filters out of the canvas entirely: a panel describing a bookcase
    // that is drawn nowhere on screen.
    globalThis.localStorage.setItem('booksnap.map.floor.st1', 'f1')
    editor(upstairsCell)

    // The panel is describing the upstairs cell…
    await screen.findByRole('link', { name: 'פתחו את המדף הזה →' })
    // …and the canvas is drawing the upstairs bookcase, not the other one.
    await waitFor(() =>
      expect(document.querySelector('.case-label')?.textContent)
        .toBe('למעלה'))
  })

  it('falls back to what was last looked at when nothing is selected',
     async () => {
    globalThis.localStorage.setItem('booksnap.map.floor.st1', 'f2')
    editor()
    await waitFor(() =>
      expect(document.querySelector('.case-label')?.textContent)
        .toBe('למעלה'))
  })
})

describe('the route that carries the focus', () => {
  it('reads a shelf id off #/plan/<id>, and a bare #/plan carries none', () => {
    expect(parseHash('#/plan/sh-9')).toEqual({ name: 'plan', focus: 'sh-9' })
    expect(parseHash('#/plan')).toEqual({ name: 'plan', focus: null })
    // ⚠ Still not the shelf screen. `#/map/<id>` has meant level 3 since P2.8
    // and the two must not collide.
    expect(parseHash('#/map/sh-9')).toEqual({ name: 'shelf', id: 'sh-9' })
  })

  it('builds the link, escaping what an id may contain', () => {
    expect(planHash('a/b')).toBe('#/plan/a%2Fb')
    expect(planHash()).toBe('#/plan')
  })
})
