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

describe('the parts of an address that a review deleted unnoticed', () => {
  it('names the site once a household has two', async () => {
    // §3.7 keeps the site OUT of the address and beside it, and only once
    // there is a second one — two sites may each have a *living room*. The
    // server decides whether to send it; this is the half that prints it, and
    // no fixture ever set it: deleting the segment altogether left the whole
    // 407-test ring green.
    const server = fakeServer([A_BOOK({ shelfId: 'sh-1', depth: 1 })])
    server.whereByShelf['sh-1'] = AT({ site: 'הורים' })
    renderApp(<App />)
    const drawer = await openDrawer()

    const line = await waitFor(() => {
      const el = drawer.querySelector('.whereline')
      expect(el).toBeTruthy()
      return el as HTMLElement
    })
    expect(within(line).getByText('הורים')).toHaveClass('rtl-safe')
    // Beside the address, and FIRST — it is the widest thing said.
    expect(line.textContent!.indexOf('הורים'))
      .toBeLessThan(line.textContent!.indexOf('סלון'))
  })

  it('says so when the bookcase and the room have no names', async () => {
    // ⚠ The state the owner's whole library is in: **all 11 bookcases
    // unnamed**, and 20 of 152 addressed shelves standing on bookcases
    // attached to no room at all. Both fallbacks had no gate — every fixture
    // named both — so a review deleted each and the ring stayed green.
    // Omitting the case says the room has one bookcase; omitting the room
    // says the building has one room. Neither is an omission; both are
    // claims.
    const server = fakeServer([A_BOOK({ shelfId: 'sh-1', depth: 1 })])
    server.whereByShelf['sh-1'] = AT({
      address: { place: '', bookcase: '', section: null, column: 1, level: 4,
                 depth: null },
    } as Partial<ShelfWhere>)
    renderApp(<App />)
    const drawer = await openDrawer()

    const line = await waitFor(() => {
      const el = drawer.querySelector('.whereline')
      expect(el).toBeTruthy()
      return el as HTMLElement
    })
    expect(within(line).getByText('חדר ללא שם')).toBeInTheDocument()
    expect(within(line).getByText('כוננית ללא שם')).toBeInTheDocument()
    // Ours, not the owner's — so no `rtl-safe`.
    expect(within(line).getByText('כוננית ללא שם'))
      .not.toHaveClass('rtl-safe')
  })
})

describe('the link out of the book surface', () => {
  it('closes the drawer as it goes', async () => {
    // ⚠⚠ The drawer is this surface's DEFAULT mount, and `App` clears it only
    // when the route becomes a BOOK — so this anchor, the first one the file
    // has ever carried, navigated to the shelf screen and left a
    // focus-trapped overlay on top of it. Measured: `elementFromPoint` at the
    // middle of the viewport returned the book drawer's body, and recovery
    // was two taps. `promote()` in the same file exists for exactly this and
    // already says so.
    const server = fakeServer([A_BOOK({ shelfId: 'sh-1', depth: 1 })])
    server.whereByShelf['sh-1'] = AT()
    renderApp(<App />)
    const drawer = await openDrawer()

    const link = await within(drawer).findByRole('link',
                                                 { name: 'למדף שלו →' })
    await userEvent.click(link)

    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('offers no link back to the shelf you are reading', async () => {
    // The same control on the shelf screen pointed at the shelf screen: an
    // action that moves nothing, on the surface where it is likeliest to be
    // pressed.
    const server = fakeServer([A_BOOK({ shelfId: 'sh-1', depth: 1 })])
    server.whereByShelf['sh-1'] = AT()
    globalThis.location.hash = '#/map/sh-1'
    renderApp(<App />)

    await userEvent.click(await screen.findByText('היער השיכור'))
    const drawer = await screen.findByRole('dialog')
    await waitFor(() =>
      expect(within(drawer).getByText('סלון')).toBeInTheDocument())
    expect(within(drawer).queryByRole('link', { name: 'למדף שלו →' }))
      .not.toBeInTheDocument()
  })

  it('points the shelf screen at its own cell on the drawing', async () => {
    // The UP half of P6.5c's drill, and it had no gate at all: a review
    // deleted the link, and pointed it at a bare `#/plan`, and 407 tests
    // stayed green. It is the control that makes an address usable on a
    // library whose bookcases are all unnamed.
    const server = fakeServer([A_BOOK({ shelfId: 'sh-1', depth: 1 })])
    server.whereByShelf['sh-1'] = AT()
    globalThis.location.hash = '#/map/sh-1'
    renderApp(<App />)

    const show = await screen.findByRole(
      'link', { name: 'הצגה על השרטוט →' })
    expect(show).toHaveAttribute('href', '#/plan/sh-1')
  })

  it('offers the drawing to a shelf that is not on it', async () => {
    // ⚠ The state that needs an ACTION had no control on it, while the state
    // that needs none had one — and it is the state 22 of 22 of the owner's
    // shelved books are in. The remedy is one tab away and nothing named it.
    const server = fakeServer([A_BOOK({ shelfId: 'sh-2', depth: 1 })])
    server.whereByShelf['sh-2'] = AT({ shelf_id: 'sh-2', address: null })
    globalThis.location.hash = '#/map/sh-2'
    renderApp(<App />)

    const put = await screen.findByRole('link',
                                        { name: 'מקמו אותו על השרטוט →' })
    expect(put).toHaveAttribute('href', '#/plan')
  })
})
