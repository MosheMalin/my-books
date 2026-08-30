/**
 * The editor over a network: what a RELOAD must not do.
 *
 * The lab had one state — the document — and reloading meant reading
 * `localStorage` again. Here there are three: the document, the last plan the
 * server was ASKED for (`initial`), and the last plan it was TOLD
 * (`confirmed`). They agree only until the first successful push, and every
 * remount of the editor pushes its own starting document.
 *
 * A data-integrity review measured what that costs: press *Plan ▸ Reload from
 * the server* after drawing a bookcase and the editor remounted with the plan
 * from BEFORE the drawing, diffed it against what the server had been told,
 * and pushed the reverse — `DELETE /map/bookcases/<id>/slots` then `DELETE
 * /map/bookcases/<id>`. Clearing a case's slots detaches the shelves books
 * stand on, so once P6.4 binds photographed shelves this is book-location
 * loss. The same path fired on any refusal, which is how the editor "recovers"
 * from one.
 *
 * ⚠ The fake is a `fetch` stub, never a mock of `../api/client`. Mocking the
 * client module worked when this file ran alone and FAILED under
 * `tools/check.py`: `isolate: false` shares one module registry across the
 * files in a worker, so whether the mock or the real module wins depends on
 * which file imported it first. The repo rule ("client suites mock `fetch`,
 * never the hooks") is not a style preference — it is the seam that does not
 * move.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { userEvent } from '../test/user'
import { I18nProvider, useI18n } from '../lib/i18n'
import { PlanScreen } from './PlanScreen'
import { mapText } from './text'

const HE = mapText('he')

/** A map server that remembers, so a reload hands back what the pushes made. */
function fakeMapServer() {
  const state = {
    calls: [] as string[],
    sites: [] as { id: string; name: string; order: number }[],
    floors: [] as { id: string; site_id: string; name: string; order: number }[],
    places: [] as { id: string; floor_id: string; name: string;
                    rect: { x: number; y: number; w: number; h: number };
                    order: number }[],
    /** P6.5c: a drawn bookcase, its one section, and the shelves standing
     *  in it. Empty by default, so every existing test is untouched. */
    bookcases: [] as Record<string, unknown>[],
    sections: [] as Record<string, unknown>[],
    shelves: [] as Record<string, unknown>[],
    /** Refuse the next POST with this status, the way a 409 arrives. */
    refuseNext: null as number | null,
    /**
     * ⚠ Refuse the next DELETE specifically.
     *
     * One flag saying "the next write" is ambiguous the moment a flow makes
     * several, and this one does: adding a site is a POST, and the loader then
     * mints that site's first storey with another. A test arming a refusal for
     * a REMOVAL had it eaten by a create it never thought about — the removal
     * then succeeded and the test failed asserting a banner that was never
     * shown. Intermittent, and mine.
     */
    refuseDeleteNext: null as number | null,
    /** Drop the next write the way a lift does: no response at all. */
    dropNext: false,
    /** P6.4b: refuse `POST /map/undo` with this status. */
    refuseUndo: null as number | null,
    /** …and the reason `GET /map/undo` then gives for it. */
    undoReason: 'world_moved',
    /** What `GET /map/undo` says MOVED — the counted sentence reads it. */
    undoChanged: ['shelves:sh-1'] as string[],
    /** Hold every POST until `release()`, so a test can make an edit arrive
     *  while an earlier one is still in flight. */
    holding: false,
    /** Hold only the DOCUMENT's writes, so a site gesture can overtake one. */
    holdFloors: false,
    /** Do the next write and then lose the ANSWER — the case where a failure
     *  does not mean nothing happened. */
    dropAnswerNext: false,
    held: [] as (() => void)[],
    release() {
      state.holding = false
      state.holdFloors = false
      for (const go of state.held.splice(0)) go()
    },
    n: 0,
  }

  const respond = (body: unknown, status = 200) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status, headers: { 'Content-Type': 'application/json' },
    })

  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://test')
    const path = url.pathname.replace('/api/v1', '')
    const method = init?.method ?? 'GET'
    state.calls.push(`${method} ${path}`)
    const body = init?.body ? JSON.parse(String(init.body)) : {}

    if (method === 'GET' && path === '/map') {
      return respond({
        sites: state.sites.map((s) => ({ ...s })),
        floors: state.floors.map((f) => ({ ...f })),
        places: state.places.map((p) => ({ ...p })),
        bookcases: state.bookcases.map((b) => ({ ...b })),
        sections: state.sections.map((x) => ({ ...x })),
      })
    }
    if (method === 'DELETE' && path.startsWith('/map/sites/')) {
      const id = path.split('/').pop()!
      if (state.dropAnswerNext) {
        state.dropAnswerNext = false
        state.sites = state.sites.filter((x) => x.id !== id)
        state.floors = state.floors.filter((f) => f.site_id !== id)
        throw new TypeError('Failed to fetch')
      }
      if (state.refuseDeleteNext) {
        const status = state.refuseDeleteNext
        state.refuseDeleteNext = null
        return respond({ detail: 'עדיין יש כאן חדרים' }, status)
      }
      state.sites = state.sites.filter((x) => x.id !== id)
      state.floors = state.floors.filter((f) => f.site_id !== id)
      return respond(null, 204)
    }
    if (method === 'GET' && path === '/shelves')
      return respond(state.shelves.map((x) => ({ ...x })))
    if (method === 'GET' && path.startsWith('/shelves/')
        && path.endsWith('/overview')) {
      return respond({
        shelf: { id: path.split('/')[2], label: '', depth_count: 1,
                 virtual: false, created_at: null, capture_count: 0,
                 book_count: 0, address: null, formerly: [] },
        depths: [], last_read_at: null,
      })
    }
    // P6.4b's two routes. The GET is read only AFTER a refusal, and it is
    // what decides WHICH refusal the owner is shown — so the fake honours
    // `undoReason` rather than answering one shape for every case, which is
    // the trap this suite already records about `limit`.
    if (path === '/map/undo') {
      if (method === 'GET') return respond({
        available: false, reason: state.undoReason, kind: '', recorded_at: '',
        restores: {}, changed: state.undoChanged,
      })
      if (state.refuseUndo) {
        return respond({ detail: 'the world moved' }, state.refuseUndo)
      }
      // ⚠ `restores: {}` and `restored: {…}`, which is the SHAPE the route
      // sends and the reason this test was passing on a lie. The offer AFTER
      // an undo is correctly empty — there is nothing left to take back — so
      // a client announcing from it can only ever say zero, and this suite
      // asserted the zero as the success message. A test that expects
      // `undo_done(0)` cannot fail.
      return respond({ available: false, reason: 'already_undone', kind:
                       'remove_column', recorded_at: '', restores: {},
                       restored: { shelves: 5 }, changed: [] })
    }
    if (method === 'POST') {
      if (state.holding || (state.holdFloors && path === '/map/floors'))
        await new Promise<void>((go) => state.held.push(go))
      if (state.dropNext) {
        state.dropNext = false
        throw new TypeError('Failed to fetch')
      }
      if (state.refuseNext) {
        const status = state.refuseNext
        state.refuseNext = null
        return respond({ detail: 'לא ניתן' }, status)
      }
      state.n += 1
      const id = `srv${state.n}`
      if (path === '/map/sites') {
        state.sites.push({ id, name: String(body.name ?? ''), order: 0 })
      } else if (path === '/map/floors') {
        state.floors.push({ id, site_id: String(body.site_id),
                            name: String(body.name ?? ''), order: 0 })
      }
      return respond({ id, ...body }, 201)
    }
    if (method === 'PATCH' && path.startsWith('/map/sites/')) {
      const site = state.sites.find((x) => path.endsWith(x.id))
      if (site && typeof body.name === 'string') site.name = body.name
      return respond(site ?? {})
    }
    if (method === 'PATCH') {
      const floor = state.floors.find((f) => path.endsWith(f.id))
      if (floor && typeof body.name === 'string') floor.name = body.name
      return respond({})
    }
    if (method === 'DELETE') {
      state.floors = state.floors.filter((f) => !path.endsWith(f.id))
      return respond(null, 204)
    }
    return respond({ detail: `no route for ${method} ${path}` }, 404)
  })

  return state
}

/**
 * Draw one bookcase with one 1x1 section on `floorId`, and stand a shelf in
 * it — the smallest world in which `#/plan/<shelfId>` has anything to point
 * at. Returns the shelf's id.
 */
function drawOne(state: ReturnType<typeof fakeMapServer>,
                 floorId: string, tag: string): string {
  state.bookcases.push({
    id: `bc-${tag}`, floor_id: floorId, place_id: null, name: '',
    front: 'S', rect: { x: 0, y: 0, w: 4, h: 1 }, order: 0,
  })
  state.sections.push({
    id: `sec-${tag}`, bookcase_id: `bc-${tag}`, ordinal: 1,
    column_levels: [1], gaps: [], default_levels: 1, default_depth: 1,
  })
  state.shelves.push({
    id: `sh-${tag}`, label: '', depth_count: 1, virtual: false,
    created_at: null, capture_count: 0, book_count: 0, formerly: [],
    address: { section_id: `sec-${tag}`, col: 1, level: 1 },
  })
  return `sh-${tag}`
}

let server: ReturnType<typeof fakeMapServer>

beforeEach(() => {
  server = fakeMapServer()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  globalThis.localStorage.clear()
})

/**
 * ⚠ A longer wait than the 1000ms default, and not a workaround. These tests
 * drive a load, a push and a re-derive; under `tools/check.py` every ring runs
 * at once under a core budget, and a ring that flakes there is a gate nobody
 * trusts. The duration is not what is being asserted — the call that is or is
 * not made is.
 */
const WAIT = { timeout: 4000 } as const

const open = () =>
  render(<I18nProvider><PlanScreen library="lib-test" /></I18nProvider>)

const posted = (path: string) =>
  server.calls.filter((c) => c === `POST ${path}`)

/** How many times the document has been read. Counted RELATIVE to a settled
 *  editor: the first load may legitimately read twice, because a site with no
 *  storey gets one and is then re-read. */
const derives = () => server.calls.filter((c) => c === 'GET /map').length

/** Add a storey through the floor menu — the one edit reachable with a click
 *  in jsdom, since drawing needs real pointer coordinates. */
async function addFloor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: HE.floor_menu }))
  await user.click(screen.getByRole('menuitem', { name: HE.add_floor }))
}

describe('reloading the plan', () => {
  it('does not push the reverse of everything this session created', async () => {
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await addFloor(user)
    await waitFor(() => expect(posted('/map/floors')).toHaveLength(2), WAIT)
    expect(server.floors).toHaveLength(2)

    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.reload }))
    await waitFor(() => expect(screen.getByRole('radio', { name: HE.arrow }))
      .toBeInTheDocument(), WAIT)
    // Let any queued push settle before believing the absence of a call.
    await new Promise((r) => setTimeout(r, 0))

    expect(server.calls.filter((c) => c.startsWith('DELETE'))).toEqual([])
    expect(server.floors).toHaveLength(2)
  })

  it('drops an edit that was queued behind a push when the reload lands', async () => {
    // ⚠ The window `setReady(false)` alone does NOT close. An edit made while
    // an earlier push is in flight is queued; if the reload happens before it
    // runs, it would be diffed against a `confirmed` the server is about to
    // contradict, and the load's own GET may have been issued before it — so
    // the next diff would re-issue its create. That is the "phantom rooms"
    // shape, one turn later.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)

    server.holding = true
    await addFloor(user)
    await waitFor(() => expect(posted('/map/floors')).toHaveLength(2), WAIT)
    // A second storey, queued behind the held one.
    await addFloor(user)

    const settled = derives()
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.reload }))
    server.release()
    // ⚠ Wait for the LAST re-derive, not the first: the push that landed
    // during the reload triggers a second one, and querying between them
    // finds the loading screen.
    await waitFor(() => {
      expect(derives()).toBeGreaterThanOrEqual(settled + 2)
      expect(screen.getByRole('radio', { name: HE.arrow })).toBeInTheDocument()
    }, WAIT)

    expect(posted('/map/floors')).toHaveLength(2)
    expect(server.calls.filter((c) => c.startsWith('DELETE'))).toEqual([])
    // ⚠ And the storey that DID land is on screen. The reload's own GET went
    // out while that POST was still in flight, so the first document derived
    // was already behind it — the editor asks again rather than showing a
    // drawing that is missing what the session created.
    expect(server.floors).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: HE.floor_menu }))
    // A storey row is a `menuitemcheckbox` — it renders whether or not it is
    // the one being edited — while *add a floor* is a plain `menuitem`.
    await waitFor(() => expect(
      screen.getByRole('menuitemcheckbox', { name: HE.floor_n(2) }))
      .toBeInTheDocument(), WAIT)
  })

  it('keeps the drawing when a push never reaches the server', async () => {
    // ⚠ The asymmetry a UX review measured, and it was backwards: a REFUSAL
    // (the server saying no) kept the editor, while a dropped connection —
    // the recoverable one — answered the LOAD's error screen, which unmounts
    // everything. On a phone in a lift that is the drawing, the selection, the
    // undo stack and every edit since the last successful push, replaced by
    // one line and a button that re-derives from the server rather than
    // retrying: the work was not recovered, it was discarded.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    const settled = derives()

    server.dropNext = true
    await addFloor(user)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(),
                  WAIT)

    // The editor is still there, and it still holds the storey just added.
    expect(screen.getByRole('radio', { name: HE.arrow })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(HE.not_saved_yet)
    // ⚠ NOT re-derived: re-deriving is what would discard the un-pushed edit,
    // and this is the state where the editor must keep it.
    expect(derives()).toBe(settled)

    // …and the next edit carries the dropped one with it, because `confirmed`
    // never advanced. Two floors reach the server from three local ones.
    await addFloor(user)
    await waitFor(() => expect(server.floors).toHaveLength(3), WAIT)
  })

  it('re-derives from the server after a refusal instead of undoing it', async () => {
    // ⚠ The refusal path bumps the same `generation`, so it carried the same
    // reversal: the storeys that HAD landed were deleted while the editor was
    // reporting the refusal.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await addFloor(user)
    await waitFor(() => expect(posted('/map/floors')).toHaveLength(2), WAIT)

    server.refuseNext = 409
    await addFloor(user)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(),
                  WAIT)
    await new Promise((r) => setTimeout(r, 0))

    expect(server.calls.filter((c) => c.startsWith('DELETE'))).toEqual([])
    expect(server.floors).toHaveLength(2)
  })
})

// --- the site picker (P6.3.1, MAP_PLAN §3.9) -------------------------------

/** Open the site menu — the segment that only exists once a second site does. */
const siteMenu = () => screen.getByRole('button', { name: HE.site_menu })

describe('the sites of one library', () => {
  /** Removing a site asks first — jsdom has no dialog, so the answer is
   *  stated. The refusal test below overrides it to `false`. */
  beforeEach(() => vi.stubGlobal('confirm', () => true))

  it('shows nothing at all while there is one, and a picker the moment there are two', async () => {
    // ⚠ The rule §3.9 shares with the library switcher: a household with one
    // home never learns the word. The one control it has is a row in the Plan
    // menu, and pressing it is what brings the segment into being.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    expect(screen.queryByRole('button', { name: HE.site_menu }))
      .not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_site }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)

    // A site is nothing without a storey to hang the drawing off — the 404
    // `ensureHome` exists to prevent.
    expect(server.sites).toHaveLength(2)
    expect(server.floors.filter((f) => f.site_id === server.sites[1]!.id))
      .toHaveLength(1)
    // …and the editor is now drawing the new one.
    await user.click(siteMenu())
    expect(screen.getByRole('menuitemcheckbox', { name: HE.site_n(2) }))
      .toHaveAttribute('aria-checked', 'true')
  })

  it('draws the storeys of the site it is on, and remembers which', async () => {
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_site }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)
    // Give the SECOND site a storey of its own, so the two differ.
    await addFloor(user)
    await waitFor(() => expect(server.floors).toHaveLength(3), WAIT)

    // Back to the first: its own single storey, and not the other's.
    await user.click(siteMenu())
    await user.click(screen.getByRole('menuitemcheckbox', { name: /הבית/ }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)
    await user.click(screen.getByRole('button', { name: HE.floor_menu }))
    const storeys = screen.getAllByRole('menuitemcheckbox')
      .map((el) => el.textContent?.replace('✓', '').trim())
    expect(storeys).toContain('קומת קרקע')
    expect(storeys).not.toContain(HE.floor_n(2))

    // ⚠ Remembered per LIBRARY, so reopening the tab lands where you left off
    // and another customer's map is unaffected.
    expect(globalThis.localStorage.getItem('booksnap.map.site.lib-test'))
      .toBe(server.sites[0]!.id)
  })

  it('recovers on its own when the remembered site is gone', async () => {
    // ⚠ Another tab can delete the site this one remembers — and the id then
    // resolves to nothing, which `toPlan` answers with a plan of one
    // synthesised storey: an EMPTY board, and the first room drawn onto it
    // refused with a 404 for a floor that exists nowhere. The same rule the
    // library switcher holds for a stale stored id: fall back, quietly.
    globalThis.localStorage.setItem('booksnap.map.site.lib-test', 'st-gone')
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await user.click(screen.getByRole('button', { name: HE.floor_menu }))
    expect(screen.getByRole('menuitemcheckbox', { name: 'קומת קרקע' }))
      .toBeInTheDocument()
  })

  it('waits for the drawing to reach the server before it re-derives', async () => {
    // ⚠ Every site gesture ends in a re-derive, and re-deriving over an edit
    // that has not landed is how it disappears. Measured before this: with one
    // storey queued behind a held push, *add a site* took the drawing from two
    // storeys to one, with no banner and the indicator reading "saved".
    // *Plan ▸ Reload* may discard — the owner asked for that. This is not.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)

    // ⚠ Only the DOCUMENT's writes are held, so the site's own POST is free
    // to overtake them — which is the whole question. Holding everything would
    // let the queue drain in order by accident and gate nothing.
    server.holdFloors = true
    await addFloor(user)
    await waitFor(() => expect(posted('/map/floors')).toHaveLength(2), WAIT)
    await addFloor(user)                       // queued behind the held one
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_site }))
    server.release()

    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)
    // Both storeys reached the server; the site was added after them.
    expect(server.floors.filter((f) => f.site_id === server.sites[0]!.id))
      .toHaveLength(3)
  })

  it('clears the last write\'s complaint when the next one works', async () => {
    // ⚠ A banner is about the LAST write. A review measured a refusal about a
    // site surviving a floor add, a trip through the overview, a floor removal
    // and the successful removal of the very site it named.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    server.dropNext = true
    await addFloor(user)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(),
                  WAIT)

    await addFloor(user)
    await waitFor(() => expect(screen.queryByRole('alert'))
      .not.toBeInTheDocument(), WAIT)
  })

  it('never repeats a name already in use', async () => {
    // ⚠ `sites.length + 1` repeats one as soon as anything is removed, and two
    // menu rows announcing one accessible name is the collision CLAUDE.md
    // records — with React dropping one of the duplicate-keyed rows, which is
    // the one state in which the picker cannot fix it.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_site }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)
    // Remove the FIRST site, leaving [אתר 2] — where the count says "2".
    // The menu removes the site being DRAWN, so switch to it first.
    await user.click(siteMenu())
    await user.click(screen.getByRole('menuitemcheckbox', { name: /הבית/ }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)
    await user.click(siteMenu())
    await user.click(screen.getByRole('menuitem', { name: HE.remove_site('הבית') }))
    await waitFor(() => expect(server.sites).toHaveLength(1), WAIT)
    // The removal re-derives; the Plan menu is not there until it lands.
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)

    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_site }))
    await waitFor(() => expect(server.sites).toHaveLength(2), WAIT)
    expect(new Set(server.sites.map((s) => s.name)).size).toBe(2)
  })

  it('asks before removing a site, and says what it took with it', async () => {
    // ⚠ A site takes every empty storey with it, and none of that is on the
    // undo stack — the same argument that put a door in front of deleting a
    // bookcase, one level up. `confirm` answering no means nothing happens.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_site }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)
    const added = server.sites[1]!.name

    vi.stubGlobal('confirm', () => false)
    await user.click(siteMenu())
    await user.click(screen.getByRole('menuitem', { name: HE.remove_site(added) }))
    await new Promise((r) => setTimeout(r, 0))
    expect(server.sites).toHaveLength(2)

    vi.stubGlobal('confirm', () => true)
    await user.click(siteMenu())
    await user.click(screen.getByRole('menuitem', { name: HE.remove_site(added) }))
    await waitFor(() => expect(server.sites).toHaveLength(1), WAIT)
    // …and it says so, rather than the board simply changing.
    expect(screen.getByText(HE.site_removed(added))).toBeInTheDocument()
  })

  it('refuses to remove a site that still has rooms, in its own words', async () => {
    // ⚠ The server refuses this too — with a 32-character id and a citation of
    // `MAP_PLAN §3.7`. This screen holds the document, so it can say what is in
    // the way and in how many words, exactly as removing a FLOOR has since the
    // lab. The server's 409 stays as the backstop for another tab's drawing.
    const user = userEvent.setup()
    server.places = [{ id: 'pl1', floor_id: 'srv2', name: 'סלון',
                       rect: { x: 0, y: 0, w: 4, h: 4 }, order: 0 }]
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_site }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)
    // Back to the site that HAS the room.
    await user.click(siteMenu())
    await user.click(screen.getByRole('menuitemcheckbox', { name: /הבית/ }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)

    await user.click(siteMenu())
    await user.click(screen.getByRole('menuitem', { name: HE.remove_site('הבית') }))
    expect(screen.getByText(HE.site_not_removed(1, 0))).toBeInTheDocument()
    expect(server.calls.filter((c) => c.startsWith('DELETE'))).toEqual([])
  })

  it('re-reads the library after a gesture fails, because it may have landed', async () => {
    // ⚠ A failure is not proof that nothing happened: the request can be
    // processed and the ANSWER lost. Without a re-derive the picker goes on
    // offering a site that is gone — and a review measured the mirror image of
    // this, where a half-landed create left a site nobody could see or remove.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_site }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)

    server.dropAnswerNext = true
    await user.click(siteMenu())
    await user.click(
      screen.getByRole('menuitem', { name: HE.remove_site(server.sites[1]!.name) }))
    // ⚠ Waits for the TEXT, not for "an alert exists". The two-step version
    // raced: `getByRole('alert')` resolves the moment the banner mounts, and
    // the assertion about WHICH notice it is then ran against whatever had
    // rendered first. A wait whose condition is weaker than the assertion
    // after it is a flake with extra steps.
    await waitFor(() => expect(screen.getByRole('alert'))
      .toHaveTextContent(HE.not_done_lead), WAIT)
    await waitFor(() => expect(screen.queryByRole('button', { name: HE.site_menu }))
      .not.toBeInTheDocument(), WAIT)
  })

  it('says why the server refused to remove one, and keeps drawing it', async () => {
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_site }))
    await waitFor(() => expect(siteMenu()).toBeInTheDocument(), WAIT)

    server.refuseDeleteNext = 409
    await user.click(siteMenu())
    await user.click(screen.getByRole('menuitem', { name: HE.remove_site(HE.site_n(2)) }))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(), WAIT)
    expect(screen.getByRole('alert')).toHaveTextContent(HE.refused_lead)
    expect(screen.getByRole('alert')).toHaveTextContent('עדיין יש כאן חדרים')
    expect(server.sites).toHaveLength(2)
  })
})


/**
 * P6.4b — the server undo, from the one control the owner has for it.
 *
 * Not covered by the dead-key scan, which proves only that a key is READ
 * somewhere. What matters here is that the right one is shown: the three
 * refusals are three different sentences, and showing "things have changed
 * on those shelves" to somebody who had simply already pressed undo is a
 * false statement about their data.
 */
describe('taking back the last destructive map edit', () => {
  const openEdit = (user: ReturnType<typeof userEvent.setup>) =>
    user.click(screen.getByRole('button', { name: HE.menu_edit }))

  const press = async (user: ReturnType<typeof userEvent.setup>) => {
    await openEdit(user)
    await user.click(screen.getByRole('menuitem', { name: HE.undo_last_edit }))
  }

  /** What the owner is actually told, and where. `status` is the neutral
   *  acknowledgement, `alert` the refusal — asserted by ROLE because that is
   *  what makes the sentence announced rather than merely present.
   *
   *  ⚠ getAll, not get: the toolbar's *saved* indicator is a `status` too, so
   *  the singular query throws "found multiple" and the failure reads as a
   *  missing message rather than a second live region. */
  const saidIn = (role: string, wanted: string) =>
    waitFor(() => expect(
      screen.getAllByRole(role).map((e) => e.textContent).join(' | '),
    ).toContain(wanted), WAIT)
      .then(() => screen.getAllByRole(role).map((e) => e.textContent).join(' | '))

  it('is its own control, named differently from the drawing undo', async () => {
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await openEdit(user)

    // ⚠ Compared over the menu's OWN accessible names, not by looking each
    // one up: the drawing undo announces as "ביטולCtrl+Z" — its label and its
    // <kbd> — so fetching it by `HE.undo` finds nothing and would have made
    // this test pass for the wrong reason if it had been written the other
    // way round. What the rule forbids is two rows sharing a name.
    const names = screen.getAllByRole('menuitem').map((m) => m.textContent)
    expect(names).toContain(HE.undo_last_edit)
    expect(new Set(names).size).toBe(names.length)
    expect(HE.undo_last_edit).not.toBe(HE.undo)
  })

  it('asks the server, and says so when it worked', async () => {
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    const settled = derives()
    await press(user)

    await waitFor(() => expect(posted('/map/undo')).toHaveLength(1), WAIT)
    await waitFor(() => expect(derives()).toBeGreaterThan(settled), WAIT)
    expect(await saidIn('status', HE.undo_done(5))).toContain(HE.undo_done(5))
    // ⚠ And NOT the zero. The route's `restores` is empty after a successful
    // undo by design, so announcing from it printed *"0 shelves are back in
    // place"* — measured on the merge path as *"0 books went back"* with 22
    // of them back on the shelf and the alias gone.
    expect(screen.getAllByRole('status').map((e) => e.textContent).join(' | '))
      .not.toContain(HE.undo_done(0))
    // …and the drawing is re-derived, because the server has just changed
    // rows this session's document knows nothing about.
    //
    // ⚠ Counted RELATIVE to a settled editor, the idiom the five sibling
    // tests in this file already use. `> 1` was green against the bug: the
    // mount alone issues FOUR `GET /map`, so bypassing the re-derive entirely
    // left it passing — and with it the drain whose absence a review measured
    // as data loss on the site gestures.
    expect(derives()).toBeGreaterThanOrEqual(settled + 1)
  })

  it('says nothing changed when the refusal is that it was already undone',
     async () => {
    const user = userEvent.setup()
    server.refuseUndo = 409
    server.undoReason = 'already_undone'
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await press(user)

    // ⚠ The FLASH (`status`), not the banner. Nothing was refused — the
    // owner's library is fine and everything is already back — and reporting
    // that under "the server refused the change" is a fault report where
    // there is no fault.
    const said = await saidIn('status', HE.undo_already)
    expect(said).toContain(HE.undo_already)
    expect(screen.queryByRole('alert')).toBeNull()
    // It ASKED why rather than assuming — the request that makes the
    // difference between an honest sentence and a plausible one.
    expect(server.calls).toContain('GET /map/undo')
  })

  it('says the shelves moved only when they actually did', async () => {
    const user = userEvent.setup()
    server.refuseUndo = 409
    server.undoReason = 'world_moved'
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await press(user)

    // This one IS a refusal — something really is in the way — so it keeps
    // the banner, and it NAMES what moved.
    const said = await saidIn('alert', 'מדף אחד השתנה')
    expect(said).toContain(HE.undo_moved(1, 0))
    expect(said).not.toContain(HE.undo_already)
  })


  it('does not throw the editor away when the undo was refused', async () => {
    // ⚠ A refused undo wrote NOTHING, so re-deriving buys nothing and costs
    // the owner their drawing history. Measured before this fix: the whole
    // editor was replaced for 1.28s and the SVG node swapped, discarding this
    // session's Ctrl+Z stack, the selection and the viewport — for a press
    // that changed nothing.
    const user = userEvent.setup()
    server.refuseUndo = 409
    server.undoReason = 'nothing_recorded'
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    const settled = derives()
    await press(user)

    await waitFor(() => expect(posted('/map/undo')).toHaveLength(1), WAIT)
    await saidIn('status', HE.undo_nothing)
    expect(derives()).toBe(settled)
    // …and the editor never went through its loading state.
    expect(screen.getByRole('radio', { name: HE.arrow })).toBeInTheDocument()
  })

  it('offers the undo at the moment something is removed', async () => {
    // ⚠ The real defect this closes: `ביטול` sits FIRST in the same menu,
    // becomes enabled the instant something is deleted, and re-draws the slot
    // — minting a new empty shelf while the owner's label and books stay
    // behind detached. It looks like it worked. No label fixes that, because
    // the owner never compares the two rows; a sentence at the moment of the
    // removal does.
    const user = userEvent.setup()
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await addFloor(user)
    await waitFor(() => expect(posted('/map/floors')).toHaveLength(2), WAIT)

    // Adding is not destructive, so nothing is offered…
    expect([...document.querySelectorAll('[role=status]')]
      .map((e) => e.textContent).join(' ')).not.toContain(HE.undo_offered)

    // …and removing that same storey IS, so it is.
    await user.click(screen.getByRole('button', { name: HE.floor_menu }))
    await user.click(screen.getAllByRole('menuitem')
      .find((m) => m.textContent?.startsWith('הסרת הקומה'))!)
    await waitFor(() => expect(
      server.calls.some((c) => c.startsWith('DELETE /map/floors/'))).toBe(true),
      WAIT)
    expect(await saidIn('status', HE.undo_offered)).toContain(HE.undo_offered)
  })

  it('re-renders a refusal in the language on screen, not the one it was raised in',
     async () => {
    // Its own render, with a real toggle INSIDE the real provider — the app
    // shell's language button is not part of this screen.
    function WithToggle() {
      const { toggleLang } = useI18n()
      return (
        <>
          <button type="button" onClick={toggleLang}>flip</button>
          <PlanScreen library="lib-test" />
        </>
      )
    }
    // ⚠ `detail` is frozen at the moment of the notice, and the LEAD is
    // recomputed every render — so a notice built from our own vocabulary
    // used to split down the middle when the language changed:
    // "The server refused: אין מחיקה לשחזר". Measured.
    const user = userEvent.setup()
    server.refuseUndo = 409
    server.undoReason = 'world_moved'
    render(<I18nProvider><WithToggle /></I18nProvider>)
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await press(user)
    await saidIn('alert', 'מאז')

    await user.click(screen.getByRole('button', { name: 'flip' }))
    const said = await saidIn('alert', 'since')
    expect(said).not.toMatch(/[\u0590-\u05FF]/)
  })

  it('never claims a reason it was not given', async () => {
    // The fallback, and the one that matters: if the GET fails or answers
    // something new, the owner must not be told a specific thing that may be
    // untrue. `world_moved` is the safe default because it is the only one
    // that describes a state the server is in rather than one the OWNER is
    // in — being told to look again is never a lie about what they did.
    const user = userEvent.setup()
    server.refuseUndo = 409
    server.undoReason = 'something_new'
    open()
    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    await press(user)

    const said = await saidIn('alert', 'מאז')
    expect(said).not.toContain(HE.undo_already)
    expect(said).not.toContain(HE.undo_nothing)
  })
})

describe('pointing the drawing at a shelf (P6.5c)', () => {
  /**
   * ⚠ This whole block exists because a quality review deleted the feature
   * six different ways and the 407-test ring stayed green: the link could be
   * removed, pointed at a bare `#/plan`, made never to apply, dropped out of
   * the remount key, made to return a cell WITHOUT its bookcase (the exact
   * defect the item's own commit message says was found in two places at
   * once), or made to re-apply on every load. The only verification was a
   * browser walk, which is not repeatable — and this is the headline feature
   * of the item, the thing that makes an address usable at all on a library
   * whose bookcases are all unnamed.
   */
  const openAt = (shelf: string | null) => render(
    <I18nProvider>
      <PlanScreen library="lib-test" focusShelf={shelf} />
    </I18nProvider>,
  )

  it('selects the shelf’s bookcase AND its cell', async () => {
    // ⚠ Both. `pickCell` keeps `cases` because the shelf panel is drawn
    // INSIDE the bookcase panel, so a selection carrying only cells opens the
    // editor on the right storey and then reads "nothing selected".
    server.sites.push({ id: 'st1', name: '\u05d4\u05d1\u05d9\u05ea', order: 0 })
    server.floors.push({ id: 'f1', site_id: 'st1', name: '\u05e7\u05e8\u05e7\u05e2', order: 0 })
    const shelf = drawOne(server, 'f1', 'a')

    openAt(shelf)

    // The bookcase panel is what carries the shelf panel.
    await screen.findByRole('link', { name: HE.open_this_shelf }, WAIT)
    expect(screen.getByRole('button',
                            { name: '\u05de\u05d3\u05e3, \u05e2\u05de\u05d5\u05d3\u05d4 1, \u05d2\u05d5\u05d1\u05d4 1' }))
      .toHaveAttribute('aria-pressed', 'true')
  })

  it('opens the storey the shelf is on, not the one last looked at',
     async () => {
    server.sites.push({ id: 'st1', name: '\u05d4\u05d1\u05d9\u05ea', order: 0 })
    server.floors.push({ id: 'f1', site_id: 'st1', name: '\u05e7\u05e8\u05e7\u05e2', order: 0 })
    server.floors.push({ id: 'f2', site_id: 'st1', name: '\u05e2\u05dc\u05d9\u05d5\u05e0\u05d4', order: 1 })
    drawOne(server, 'f1', 'down')
    const upstairs = drawOne(server, 'f2', 'up')
    globalThis.localStorage.setItem('booksnap.map.floor.st1', 'f1')

    openAt(upstairs)

    await screen.findByRole('link', { name: HE.open_this_shelf }, WAIT)
    expect(screen.getByText('\u05e2\u05dc\u05d9\u05d5\u05e0\u05d4')).toBeInTheDocument()
  })

  it('switches SITE for a shelf drawn in another one', async () => {
    // `toPlan` builds one site at a time, so a shelf in the parents' place is
    // simply not in the document on screen. The screen asks the server which
    // site owns it and switches — the same call the picker makes.
    server.sites.push({ id: 'st1', name: '\u05d4\u05d1\u05d9\u05ea', order: 0 })
    server.sites.push({ id: 'st2', name: '\u05d4\u05d5\u05e8\u05d9\u05dd', order: 1 })
    server.floors.push({ id: 'f1', site_id: 'st1', name: '\u05e7\u05e8\u05e7\u05e2', order: 0 })
    server.floors.push({ id: 'f2', site_id: 'st2', name: '\u05e7\u05e8\u05e7\u05e2', order: 0 })
    const theirs = drawOne(server, 'f2', 'theirs')
    globalThis.localStorage.setItem('booksnap.map.site.lib-test', 'st1')

    openAt(theirs)

    await screen.findByRole('link', { name: HE.open_this_shelf }, WAIT)
    expect(screen.getByRole('button',
                            { name: '\u05de\u05d3\u05e3, \u05e2\u05de\u05d5\u05d3\u05d4 1, \u05d2\u05d5\u05d1\u05d4 1' }))
      .toHaveAttribute('aria-pressed', 'true')
  })

  it('re-points at a second shelf without a fresh mount', async () => {
    // ⚠ The route change this feature actually arrives by. Following
    // *הצגה על השרטוט* from the shelf screen changes the hash inside a
    // MOUNTED app, so `PlanScreen` re-renders rather than remounting — and
    // `MapScreen` reads `initialSelection` in a `useState` initialiser, which
    // is consumed once. The focus is part of the remount key for that reason,
    // and a review deleted the key and every test stayed green, because they
    // all mount fresh. A rerender is what reproduces the real journey.
    server.sites.push({ id: 'st1', name: 'הבית', order: 0 })
    server.floors.push({ id: 'f1', site_id: 'st1', name: 'קרקע', order: 0 })
    const first = drawOne(server, 'f1', 'one')
    const second = drawOne(server, 'f1', 'two')

    const view = render(
      <I18nProvider>
        <PlanScreen library="lib-test" focusShelf={first} />
      </I18nProvider>,
    )
    await screen.findByRole('link', { name: HE.open_this_shelf }, WAIT)
    expect(screen.getByRole('link', { name: HE.open_this_shelf }))
      .toHaveAttribute('href', `#/map/${first}`)

    view.rerender(
      <I18nProvider>
        <PlanScreen library="lib-test" focusShelf={second} />
      </I18nProvider>,
    )

    await waitFor(() =>
      expect(screen.getByRole('link', { name: HE.open_this_shelf }))
        .toHaveAttribute('href', `#/map/${second}`), WAIT)
  })

  it('lands quietly when the shelf it names stands nowhere', async () => {
    // The link is only ever offered when there IS an address, so this is a
    // hand-typed URL. Nothing is selected and nothing is announced — an alert
    // about a shelf the owner did not ask about would be noise on the screen
    // they did ask for. What is asserted is that it does not CRASH and does
    // not raise the editor's banner.
    server.sites.push({ id: 'st1', name: '\u05d4\u05d1\u05d9\u05ea', order: 0 })
    server.floors.push({ id: 'f1', site_id: 'st1', name: '\u05e7\u05e8\u05e7\u05e2', order: 0 })
    server.shelves.push({
      id: 'sh-free', label: '', depth_count: 1, virtual: false,
      created_at: null, capture_count: 0, book_count: 0, formerly: [],
      address: null,
    })

    openAt('sh-free')

    await screen.findByRole('radio', { name: HE.arrow }, WAIT)
    expect(screen.queryByRole('link', { name: HE.open_this_shelf }))
      .not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('coming back to where you were (P6.7c)', () => {
  /**
   * The owner, walking the finished pillar: *"click back from a shelf should
   * go back to where we was. I started from a specific bookcase — I want to
   * return to it, not to the map."*
   *
   * `back()` was never wrong: it is `history.back()`. What was wrong is that
   * the entry it returns to said only `#/plan`, because the editor holds its
   * selection in React state and nothing wrote it down. So the map now STAMPS
   * what is selected into the current history entry — and the two halves of
   * that (write it, read it back) are what this block pins.
   */
  const openAt = (focus: string | null) => render(
    <I18nProvider>
      <PlanScreen library="lib-test" focusShelf={focus} />
    </I18nProvider>,
  )

  const world = () => {
    server.sites.push({ id: 'st1', name: 'הבית', order: 0 })
    server.floors.push({ id: 'f1', site_id: 'st1', name: 'קרקע', order: 0 })
    return drawOne(server, 'f1', 'a')
  }

  it('opens on the BOOKCASE when the id names one, not just a shelf', async () => {
    // The half that makes the journey work. `#/plan/<id>` has always taken a
    // shelf; the id is opaque (`parseHash` never looks at it), so the same
    // route now resolves a bookcase — which is what the owner started from
    // and what he expects back.
    world()

    openAt('bc-a')

    // The bookcase panel, with its elevation — the screen he left.
    expect(await screen.findByRole('button',
                                   { name: HE.delete_case }, WAIT))
      .toBeInTheDocument()
  })

  it('writes the selection into the URL so BACK can find it', async () => {
    // ⚠ The stamp is the whole feature. Without it the history entry says
    // `#/plan`, and returning from a shelf screen lands on a map with nothing
    // selected — which is exactly what the owner reported.
    //
    // The MOST SPECIFIC thing selected: a cell answers with the shelf
    // standing in it, not with its bookcase.
    const shelf = world()
    globalThis.location.hash = '#/plan'

    openAt(shelf)

    await screen.findByRole('link', { name: HE.open_this_shelf }, WAIT)
    await waitFor(
      () => expect(globalThis.location.hash).toBe(`#/plan/${shelf}`), WAIT)
  })

  it('stamps a BOOKCASE when that is all that is selected', async () => {
    // A slot this session just drew has no shelf row, and a bookcase selected
    // on its own has no cell — stamping nothing there would lose the very
    // thing the owner wants back.
    world()
    globalThis.location.hash = '#/plan'

    openAt('bc-a')

    await screen.findByRole('button', { name: HE.delete_case }, WAIT)
    await waitFor(
      () => expect(globalThis.location.hash).toBe('#/plan/bc-a'), WAIT)
  })

  it('does the same for a ROOM, which is also a place you came from', async () => {
    // The third thing `#/plan/<id>` can name. Rooms are selectable and have
    // a panel of their own, so leaving one and coming back is the same
    // journey — and an untested branch is a branch that stops working.
    world()
    server.places.push({ id: 'pl1', floor_id: 'f1', name: 'סלון',
                         rect: { x: 0, y: 0, w: 10, h: 8 }, order: 0 })
    globalThis.location.hash = '#/plan'

    openAt('pl1')

    await screen.findByRole('button', { name: HE.delete_room }, WAIT)
    await waitFor(
      () => expect(globalThis.location.hash).toBe('#/plan/pl1'), WAIT)
  })

  it('stamps WITHOUT navigating, so the drawing is not torn down', async () => {
    // ⚠⚠ The reason this uses `history.replaceState` and not `location.hash`
    // or `location.replace`. Both of those fire `hashchange`; `PlanScreen`
    // keys `MapScreen` on the focus id, so a real navigation here would
    // REMOUNT the whole editor on every tap — and this file's header is about
    // what a remount costs: it pushes its own starting document and can undo
    // the session's work.
    //
    // Asserted at the MECHANISM, because that is the thing that must not
    // change: the hash moves and no listener hears it.
    const shelf = world()
    globalThis.location.hash = '#/plan'
    // ⚠ The EVENT's own `newURL`, never `location.hash` read at delivery.
    // jsdom dispatches `hashchange` asynchronously, so the assignment two
    // lines above arrives after the stamp has already happened — a listener
    // that reads the live hash reports the stamped value for an event that
    // was announcing something else, and the test fails for a reason that is
    // not true. Measured, writing this.
    const heard: string[] = []
    const listener = (e: Event) =>
      heard.push(new URL((e as HashChangeEvent).newURL).hash)
    globalThis.addEventListener('hashchange', listener)
    try {
      openAt(shelf)
      await screen.findByRole('link', { name: HE.open_this_shelf }, WAIT)
      await waitFor(
        () => expect(globalThis.location.hash).toBe(`#/plan/${shelf}`), WAIT)
      expect(heard).not.toContain(`#/plan/${shelf}`)
    } finally {
      globalThis.removeEventListener('hashchange', listener)
    }
  })
})

describe('saving the drawing to a file (P6.7e)', () => {
  /**
   * The owner: *"I'm missing an explicit save or export for the map. I want
   * to be able to save copies and tries by myself. How else can a user try
   * and save backups he can later upload?"*
   *
   * The format's own guarantees are pinned in `core.test.ts`. What is here is
   * the wiring: that the menu item writes a file at all, that it writes the
   * document ON SCREEN, and that it says so.
   */
  const saved = () => {
    const written: { name: string; text: string }[] = []
    const seen = new Map<string, Blob>()
    let n = 0
    // ⚠ The two STATIC methods, never the `URL` global itself. Replacing it
    // wholesale takes `new URL(...)` with it, which the fake server uses to
    // route every request — the editor then renders its "could not load"
    // state and the test fails somewhere that has nothing to do with saving.
    // Measured, writing this. jsdom implements neither method, so they are
    // assigned rather than spied, and `afterEach` deletes them.
    const url = URL as unknown as Record<string, unknown>
    url['createObjectURL'] = (b: Blob) => {
      const made = `blob:${(n += 1)}`
      seen.set(made, b)
      return made
    }
    url['revokeObjectURL'] = () => {}
    // jsdom performs no navigation for a download, so the anchor's click is
    // where the file "arrives". Reading the Blob back is what proves the
    // bytes, rather than trusting that a URL was minted.
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        const blob = seen.get(this.href)
        if (blob) void blob.text().then((text) =>
          written.push({ name: this.download, text }))
      })
    return { written, click }
  }

  afterEach(() => {
    const url = URL as unknown as Record<string, unknown>
    delete url['createObjectURL']
    delete url['revokeObjectURL']
  })

  it('writes the document ON SCREEN, naming its library and site', async () => {
    // ⚠ On screen, not `sync.initial`. Those two disagree from the first
    // unsaved edit onwards, and a save that quietly wrote the last thing the
    // SERVER said would be the worst kind of backup — it looks like it
    // captured what you were looking at.
    server.sites.push({ id: 'st1', name: 'הבית', order: 0 })
    server.floors.push({ id: 'f1', site_id: 'st1', name: 'קרקע', order: 0 })
    drawOne(server, 'f1', 'a')
    const file = saved()
    open()
    await screen.findByRole('button', { name: HE.menu_plan }, WAIT)

    // ⚠ An UNSAVED edit first, and it is the whole point of this assertion:
    // `doc.plan` and `sync.initial` agree until the session's first edit and
    // never again, so a save reading the wrong one passes every test that
    // exports a freshly loaded drawing.
    await userEvent.click(screen.getByRole('button', { name: HE.floor_menu }))
    await userEvent.click(screen.getByRole('menuitem', { name: HE.add_floor }))
    await screen.findByText(HE.floor_n(2), {}, WAIT)

    await userEvent.click(screen.getByRole('button', { name: HE.menu_plan }))
    await userEvent.click(screen.getByRole('menuitem', { name: HE.save_to_file }))

    await waitFor(() => expect(file.written).toHaveLength(1), WAIT)
    const { name, text } = file.written[0]!
    expect(name).toMatch(/^booksnap-הבית-\d{4}-\d{2}-\d{2}\.json$/)
    const body = JSON.parse(text) as {
      version: number
      origin: { library: string; siteId: string }
      plan: { floors: unknown[]; cases: { sections: { id: string }[] }[] }
    }
    expect(body.plan.floors).toHaveLength(2)
    expect(body.version).toBe(5)
    expect(body.origin).toMatchObject({ library: 'lib-test', siteId: 'st1' })
    expect(body.plan.cases[0]!.sections[0]!.id).toBe('sec-a')
  })

  it('says it saved, and names the file', async () => {
    // A download that says nothing is indistinguishable from a control that
    // did nothing: the browser's own chrome for it is a corner of a desktop
    // window and is invisible on a phone.
    server.sites.push({ id: 'st1', name: 'הבית', order: 0 })
    server.floors.push({ id: 'f1', site_id: 'st1', name: 'קרקע', order: 0 })
    saved()
    open()
    await screen.findByRole('button', { name: HE.menu_plan }, WAIT)

    await userEvent.click(screen.getByRole('button', { name: HE.menu_plan }))
    await userEvent.click(screen.getByRole('menuitem', { name: HE.save_to_file }))

    expect(await screen.findByText(/^נשמר לקובץ booksnap-/, {}, WAIT))
      .toBeInTheDocument()
  })
})

describe('restoring a saved drawing (P6.7f)', () => {
  /**
   * The owner settled the semantics: *"ask if the user is sure and say data
   * will get unbound. if user agrees — replace."*
   *
   * ⚠ This is the most destructive gesture in the product, and the ONE it
   * cannot undo: §3.15's journal takes back the head entry, and a restore is
   * many operations. So the way back is a file written before the replace,
   * without being asked for — which makes the ORDER the safety argument, the
   * same shape P6.4d's merge had to learn.
   */
  const world = () => {
    server.sites.push({ id: 'st1', name: 'הבית', order: 0 })
    server.floors.push({ id: 'f1', site_id: 'st1', name: 'קרקע', order: 0 })
    return drawOne(server, 'f1', 'a')
  }

  /** A v5 file of one site, holding whatever cases are passed. */
  const planFile = (over: Record<string, unknown> = {}) => new File(
    [JSON.stringify({
      format: 'booksnap.map-lab.plan',
      version: 5,
      origin: { library: 'lib-test', siteId: 'st1', siteName: 'הבית',
                savedAt: '2026-08-30T09:00:00Z' },
      plan: {
        floors: [{ id: 'f1', name: 'קרקע' }],
        rooms: [{ id: 'r9', name: 'חדר מהקובץ',
                  rect: { x: 0, y: 0, w: 6, h: 6 }, floorId: 'f1' }],
        cases: [],
      },
      ...over,
    })],
    'drawing.json', { type: 'application/json' })

  const restore = async (file: File) => {
    await screen.findByRole('button', { name: HE.menu_plan }, WAIT)
    await userEvent.upload(screen.getByLabelText(HE.restore_upload), file)
  }

  it('refuses a file of a DIFFERENT site, and changes nothing', async () => {
    // `toPlan` builds one site at a time, so a file of another site describes
    // furniture this document has never heard of — restoring it would delete
    // everything on screen and recreate a house somewhere else.
    world()
    open()
    await screen.findByRole('button', { name: HE.menu_plan }, WAIT)
    const before = server.calls.length

    await restore(planFile({
      origin: { library: 'lib-test', siteId: 'ANOTHER', siteName: 'x',
                savedAt: '2026-08-30T09:00:00Z' },
    }))

    expect(await screen.findByText(HE.restore_other_site, {}, WAIT))
      .toBeInTheDocument()
    expect(server.calls.length).toBe(before)
  })

  it('opens the file picker from the menu, not from nowhere', async () => {
    // The item is one line of wiring and the menu test can only see its
    // LABEL — a menu row that opens nothing reads exactly like one that
    // does, and the guard beside it would pass forever.
    world()
    open()
    await screen.findByRole('button', { name: HE.menu_plan }, WAIT)
    const picker = screen.getByLabelText(HE.restore_upload)
    const clicked = vi.spyOn(picker, 'click').mockImplementation(() => {})

    await userEvent.click(screen.getByRole('button', { name: HE.menu_plan }))
    await userEvent.click(
      screen.getByRole('menuitem', { name: HE.open_from_file }))

    expect(clicked).toHaveBeenCalled()
  })

  it('refuses a file that is not a drawing at all', async () => {
    world()
    open()
    await restore(new File(['{"hello":1}'], 'x.json',
                           { type: 'application/json' }))

    expect(await screen.findByText(HE.restore_not_a_plan, {}, WAIT))
      .toBeInTheDocument()
  })

  it('asks, NAMES what loses its place, and obeys a no', async () => {
    // The fixture's shelf stands in the drawn bookcase, and the file holds no
    // cases at all — so the honest sentence is one bookcase, one shelf.
    world()
    const asked: string[] = []
    vi.stubGlobal('confirm', (q: string) => { asked.push(q); return false })
    open()
    await screen.findByRole('button', { name: HE.menu_plan }, WAIT)
    const before = server.calls.length

    await restore(planFile())

    await waitFor(() => expect(asked).toHaveLength(1), WAIT)
    expect(asked[0]).toContain(HE.restore_nothing_lost(1))
    // ⚠ And the promise that makes the answer safe to give.
    expect(asked[0]).toContain(HE.restore_backup_first)
    expect(server.calls.length).toBe(before)
    expect(screen.queryByText('חדר מהקובץ')).toBeNull()
  })

  it('writes the current drawing to a file BEFORE it replaces anything',
     async () => {
    // ⚠⚠ The order IS the safety argument. There is no undo for this, so the
    // file written first is the only way back — and a restore that replaced
    // and then failed to save would have destroyed the drawing and the way
    // back to it in one press.
    world()
    const written: string[] = []
    const seen = new Map<string, Blob>()
    let n = 0
    const url = URL as unknown as Record<string, unknown>
    url['createObjectURL'] = (b: Blob) => {
      const made = `blob:${(n += 1)}`
      seen.set(made, b)
      return made
    }
    url['revokeObjectURL'] = () => {}
    const order: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(
      function (this: HTMLAnchorElement) {
        order.push('saved')
        written.push(this.download)
      })
    vi.stubGlobal('confirm', () => true)
    open()

    await restore(planFile())

    await waitFor(() => expect(order).toEqual(['saved']), WAIT)
    expect(written[0]).toMatch(/^booksnap-הבית-/)
    expect(await screen.findByText(HE.restored, {}, WAIT)).toBeInTheDocument()

    // ⚠⚠ And it is still the sentence on screen after the push lands.
    // Measured: the restore's push destroys things, so `record` announced
    // *Edit ▸ take back the last removal* over the top of it — a promise the
    // journal cannot keep, because an import is many operations and the undo
    // takes back the head. The way back from a restore is the file written a
    // line earlier, and that is what the owner must be looking at.
    expect(screen.queryByText(HE.undo_offered)).toBeNull()

    // ⚠ And the document really was REPLACED. Saying so and doing nothing
    // is the failure mode this whole item is exposed to: the flash fires,
    // the backup lands, and the drawing on screen is the one you were
    // trying to replace.
    expect(await screen.findByText('חדר מהקובץ', {}, WAIT))
      .toBeInTheDocument()

    const url2 = URL as unknown as Record<string, unknown>
    delete url2['createObjectURL']
    delete url2['revokeObjectURL']
  })
})

