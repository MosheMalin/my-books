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

const SHEET = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../styles/books.css'), 'utf8')

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

describe('the breakpoint', () => {
  it('is the one the sheet reserves room for', () => {
    const want = Number(/max-width:\s*(\d+)px/.exec(NARROW_QUERY)?.[1])
    expect(want).toBeGreaterThan(0)

    // Every media block in the sheet that mentions the bottom bar — by its
    // class or by the token that reserves its height — must be that width.
    const blocks = [...SHEET.matchAll(
      /@media\s*\(max-width:\s*(\d+)px\)\s*\{([\s\S]*?)[\r\n]\}/g)]
    const reserving = blocks.filter(
      (m) => m[2]!.includes('botnav') || m[2]!.includes('.appbar .nav'))
    expect(reserving.length,
           'no breakpoint in books.css makes room for the bottom bar')
      .toBeGreaterThan(0)
    for (const m of reserving) expect(Number(m[1])).toBe(want)
  })
})
