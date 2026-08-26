/**
 * The phone's navigation (P6.5a).
 *
 * Three decisions, each mutation-checked:
 *   1. below the breakpoint the tabs are in a BOTTOM bar and the app bar has
 *      none — and there is exactly ONE control per destination, because the
 *      accessibility half of this fix is that two navs never coexist;
 *   2. above it, nothing changed;
 *   3. the breakpoint the hook mounts at is the one the SHEET makes room for.
 *
 * ⚠ (3) reads `books.css` rather than listing a number, for the reason
 * CLAUDE.md records four times: a guard that enumerates from a list is a
 * guard that stops watching the moment the source grows. If the sheet's
 * breakpoint moves and the hook's does not, the bar mounts where no padding
 * was reserved for it — a fixed, opaque strip over the last row of every page
 * and over the bottom 56px of the plan workspace.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, screen, waitFor } from '@testing-library/react'

import { App } from '../App'
import { book, fakeServer, renderApp } from '../test/harness'
import { userEvent } from '../test/user'
import { NARROW_QUERY } from './narrow'

const HERE = dirname(fileURLToPath(import.meta.url))
/** ⚠ Comments stripped at the door. A review measured the cost of not doing
 *  it: with the scan confused, the failure named a 620px block that reserves
 *  nothing, because the word `botnav` appeared in its PROSE. `scoping.test.ts`
 *  has stripped comments before scanning since it was written. */
const sheet = (path: string) =>
  readFileSync(join(HERE, path), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

const SHEET = sheet('../styles/books.css')
/** The shared package, consumed as SOURCE by both clients — and the third
 *  place the breakpoint is spelled. */
const SHARED = sheet('../../../ui/src/styles/ui.css')

const A_BOOK = book({ id: 'b1', title: 'היער השיכור', author: "ג'ראלד דארל" })

/** jsdom has no `matchMedia`; the hook treats a missing one as "not narrow",
 *  so a test that wants the phone has to supply one. */
function viewport(narrow: boolean) {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: q === NARROW_QUERY ? narrow : false,
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  }))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  globalThis.location.hash = ''
})

describe('the navigation a phone gets', () => {
  it('moves the tabs to a bottom bar, leaving ONE control per destination',
     async () => {
    viewport(true)
    fakeServer([A_BOOK])
    renderApp(<App />)

    // ⚠ `getAllBy`, not `getBy`: the failure this pins is a DUPLICATE, and
    // `getBy` reports a duplicate as "found multiple" — which reads as a
    // broken test rather than the collision it is. Asserting the count says
    // what the rule is.
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'ספרים' })).toHaveLength(1))
    for (const name of ['ספרים', 'צילום וקריאה', 'המפה']) {
      expect(screen.getAllByRole('button', { name })).toHaveLength(1)
      expect(screen.getByRole('button', { name }).closest('nav'))
        .toHaveClass('botnav')
    }
    expect(document.querySelector('.appbar .nav')).toBeNull()
  })

  it('keeps them in the app bar on anything wider', async () => {
    viewport(false)
    fakeServer([A_BOOK])
    renderApp(<App />)

    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'ספרים' })).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'ספרים' }).closest('nav'))
      .toHaveClass('nav')
    expect(document.querySelector('.botnav')).toBeNull()
  })

  it('navigates from the bottom bar, and says which tab you are on',
     async () => {
    viewport(true)
    fakeServer([A_BOOK])
    renderApp(<App />)

    const plan = await screen.findByRole('button', { name: 'המפה' })
    // The pressed state is the whole point of a tab bar you cannot see the
    // page behind: it is the only thing that answers "where am I".
    expect(plan).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(plan)
    await waitFor(() => expect(globalThis.location.hash).toBe('#/plan'))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'המפה' }))
        .toHaveAttribute('aria-pressed', 'true'))
  })
})

/** The one number, taken from the hook rather than written down again. */
const WANT = Number(/max-width:\s*(\d+)px/.exec(NARROW_QUERY)?.[1])

describe('the breakpoint', () => {
  it('is the one the sheet reserves room for', () => {
    const want = WANT
    expect(want).toBeGreaterThan(0)

    // Every media block in the sheet that mentions the bottom bar — by its
    // class or by the token that reserves its height — must be that width.
    //
    // ⚠ The disjunct that stood here also tested for `.appbar .nav`, which
    // `books.css` has never contained: the product styles it as a bare `.nav`,
    // and `.appbar .nav { display: none }` is the MOCK's selector — the
    // CSS-hide approach this item deliberately rejected in favour of
    // unmounting. A branch that can never fire, implying coverage of a
    // mechanism that does not exist.
    const blocks = [...SHEET.matchAll(
      /@media\s*\(max-width:\s*(\d+)px\)\s*\{([\s\S]*?)[\r\n]\}/g)]
    const reserving = blocks.filter((m) => m[2]!.includes('botnav'))
    expect(reserving.length,
           'no breakpoint in books.css makes room for the bottom bar')
      .toBeGreaterThan(0)
    for (const m of reserving) expect(Number(m[1])).toBe(want)
  })

  it('is the one the SHARED sheet uses too', () => {
    // ⚠ Third copy of the number, and it was the one with no guard — behind a
    // comment in `ui.css` asserting there was one. A review changed it from
    // 760 to 900 and both rings stayed green. `touch.test.ts` reads that
    // sheet, but it checks HEIGHTS, never the breakpoint: "if a comment names
    // a guard, open the guard" (CLAUDE.md).
    //
    // The rule is that `ui.css` has ONE phone breakpoint and it is the
    // shell's, because a shared control that becomes thumb-sized at a
    // different width than the page around it is two designs. The day it
    // genuinely needs a second, this line is where that gets decided.
    const widths = [...SHARED.matchAll(/@media[^{]*max-width:\s*(\d+)px/g)]
      .map((m) => Number(m[1]))
    expect(widths.length, 'the shared sheet has no phone breakpoint at all')
      .toBeGreaterThan(0)
    expect([...new Set(widths)]).toEqual([WANT])
  })
})
