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
import { I18nProvider } from '../lib/i18n'
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
        bookcases: [], sections: [],
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
    if (method === 'GET' && path === '/shelves') return respond([])
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
