/**
 * "Where is it" (P6.5b) — VISION §7's requirement on the surface that asks it.
 *
 * Every decision here is one the server does NOT make: the server sends parts
 * and the counts that decide which parts exist, and this client turns them
 * into a line a person reads. What is pinned is therefore the RENDERING —
 * three distinct empty states, one element per segment, and the link going to
 * the id the server resolved rather than the one the copy stored.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, screen, waitFor, within } from '@testing-library/react'

import { App } from '../App'
import type { ShelfWhere } from '../api/client'
import { book, fakeServer, renderApp } from '../test/harness'
import { userEvent } from '../test/user'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  globalThis.location.hash = ''
})

const AT = (over: Partial<ShelfWhere> = {}): ShelfWhere => ({
  shelf_id: 'sh-1',
  label: '',
  depth_count: 1,
  site: null,
  address: {
    place: 'סלון', bookcase: 'Ikea Billy',
    section: null, column: 2, level: 3, depth: null,
  },
  ...over,
} as ShelfWhere)

const A_BOOK = (over: Record<string, unknown> = {}) => book({
  id: 'b1', title: 'היער השיכור', author: "ג'ראלד דארל", ...over,
})

async function openDrawer() {
  await userEvent.click(await screen.findByText('היער השיכור'))
  return await screen.findByRole('dialog')
}

describe('a copy that stands somewhere', () => {
  it('names the room, the case and the level, each in its own element',
     async () => {
    // ⚠ Its OWN element is the assertion, not the text. `unicode-bidi:
    // plaintext` resolves a paragraph from its first strong character, so
    // «סלון · Ikea Billy · עמודה 2» as one string prints left-to-right and
    // puts the parts in the wrong order — the failure this repo has met on a
    // shelf name, a site name and a library name. A test that only checked
    // the words would pass on the broken version.
    const server = fakeServer([A_BOOK({ shelfId: 'sh-1', depth: 1 })])
    server.whereByShelf['sh-1'] = AT()
    renderApp(<App />)
    const drawer = await openDrawer()

    const line = await waitFor(() => {
      const el = drawer.querySelector('.whereline')
      expect(el).toBeTruthy()
      return el as HTMLElement
    })
    expect(within(line).getByText('סלון')).toHaveClass('rtl-safe')
    expect(within(line).getByText('Ikea Billy')).toHaveClass('rtl-safe')
    // Ours, so no `rtl-safe`: they are already in the UI's direction.
    expect(within(line).getByText('עמודה 2')).not.toHaveClass('rtl-safe')
    expect(within(line).getByText('גובה 3')).toBeInTheDocument()
    // One section, so the server sent none and none is printed.
    expect(line.textContent).not.toMatch(/יחידה/)
  })

  it('links into the shelf screen using the id the SERVER resolved',
     async () => {
    // §3.11. A copy's `shelf_id` is a stored value: after a merge it names an
    // identity that is answered FOR. Linking to the stored id would still
    // work — the route resolves — but the link the person copies out of the
    // address bar would name a shelf that no longer stands anywhere, and the
    // whole point of the alias is that one hop happens once, on the server.
    const server = fakeServer([A_BOOK({ shelfId: 'sh-old', depth: 1 })])
    server.whereByShelf['sh-old'] = AT({ shelf_id: 'sh-survivor' })
    renderApp(<App />)
    const drawer = await openDrawer()

    const link = await within(drawer).findByRole('link',
                                                 { name: 'למדף שלו →' })
    expect(link).toHaveAttribute('href', '#/map/sh-survivor')
  })

  it('names the row only when it is behind the front one, and says why',
     async () => {
    // §5.7's whole reason for surfacing depth: reaching a back-row book means
    // moving the row in front of it. The fake applies the rule the SERVER
    // owns, so this also proves the depth reached the wire.
    const server = fakeServer([A_BOOK({ shelfId: 'sh-1', depth: 2 })])
    server.whereByShelf['sh-1'] = AT({ depth_count: 3 })
    renderApp(<App />)
    const drawer = await openDrawer()

    await waitFor(() =>
      expect(within(drawer).getByText('שורה 2')).toBeInTheDocument())
    expect(within(drawer).getByText('צריך להזיז את השורה שלפניו'))
      .toBeInTheDocument()
    expect(server.calls.some((c) => c.includes('/map/where/sh-1?depth=2')))
      .toBe(true)
  })

  it('says nothing about a row when the copy is in the front one', async () => {
    const server = fakeServer([A_BOOK({ shelfId: 'sh-1', depth: 1 })])
    server.whereByShelf['sh-1'] = AT({ depth_count: 3 })
    renderApp(<App />)
    const drawer = await openDrawer()

    await waitFor(() =>
      expect(within(drawer).getByText('סלון')).toBeInTheDocument())
    expect(within(drawer).queryByText(/שורה/)).not.toBeInTheDocument()
    expect(within(drawer).queryByText('צריך להזיז את השורה שלפניו'))
      .not.toBeInTheDocument()
  })
})

describe('the three ways a copy has no address', () => {
  it('distinguishes on no shelf, not on the map, and a lookup that failed',
     async () => {
    // ⚠ The third is the one that gets collapsed into the second, and doing
    // so reports a server error as a fact about the furniture — "not on the
    // map yet" invites the owner to go and draw something that is already
    // drawn. Absent, unknown and broken are three states (CLAUDE.md:
    // *absent is not unknown*).
    const server = fakeServer([
      A_BOOK({ id: 'b1', title: 'ספר בלי מדף' }),
      A_BOOK({ id: 'b2', title: 'ספר על מדף לא מצויר', shelfId: 'sh-2',
               depth: 1 }),
      A_BOOK({ id: 'b3', title: 'ספר שהחיפוש נכשל', shelfId: 'sh-3',
               depth: 1 }),
    ])
    server.whereByShelf['sh-2'] = AT({ shelf_id: 'sh-2', address: null })
    server.whereFails.add('sh-3')
    renderApp(<App />)

    for (const [title, said] of [
      ['ספר בלי מדף', 'לא על מדף'],
      ['ספר על מדף לא מצויר', 'עדיין לא על המפה'],
      ['ספר שהחיפוש נכשל', 'לא הצלחנו לברר איפה זה עומד'],
    ] as const) {
      await userEvent.click(await screen.findByText(title))
      const drawer = await screen.findByRole('dialog')
      await waitFor(() =>
        expect(within(drawer).getByText(said)).toBeInTheDocument())
      await userEvent.click(within(drawer).getByRole('button',
                                                     { name: '✕ סגירה' }))
    }
  })

  it('asks nothing at all for a copy on no shelf', async () => {
    // A `null` shelf is a legitimate state, not a lookup. Firing a request
    // for it would make every unshelved book in a 286-book library a round
    // trip that can only answer 404.
    const server = fakeServer([A_BOOK()])
    renderApp(<App />)
    await openDrawer()

    await waitFor(() =>
      expect(screen.getByText('לא על מדף')).toBeInTheDocument())
    expect(server.calls.filter((c) => c.includes('/map/where/'))).toEqual([])
  })
})

describe('a book with two copies', () => {
  it('answers for each of them separately', async () => {
    // The defect "last seen" had before P1.7, which this section was built
    // to avoid repeating: reading `copies[0]` is harmless with one copy and
    // silently wrong with two — and two copies in two rooms is exactly the
    // household that needs "where is it" at all.
    const server = fakeServer([book({
      id: 'b1', title: 'היער השיכור', author: "ג'ראלד דארל",
      shelfId: 'sh-a', depth: 1,
      alsoAt: [{ shelfId: 'sh-b' }],
    })])
    server.whereByShelf['sh-a'] = AT({ shelf_id: 'sh-a' })
    server.whereByShelf['sh-b'] = AT({
      shelf_id: 'sh-b',
      address: { place: 'חדר הורים', bookcase: 'הכוננית הגדולה',
                 section: 2, column: null, level: 1, depth: null },
    } as Partial<ShelfWhere>)
    renderApp(<App />)
    const drawer = await openDrawer()

    await waitFor(() =>
      expect(within(drawer).getByText('סלון')).toBeInTheDocument())
    expect(within(drawer).getByText('חדר הורים')).toBeInTheDocument()
    // A two-section case DOES name its section; the one-section case above
    // does not. Same rule, opposite side.
    expect(within(drawer).getByText('יחידה 2')).toBeInTheDocument()
  })
})
