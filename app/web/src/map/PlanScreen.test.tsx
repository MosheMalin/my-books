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
    /** Refuse the next write with this status, the way a 409 arrives. */
    refuseNext: null as number | null,
    /** Hold every POST until `release()`, so a test can make an edit arrive
     *  while an earlier one is still in flight. */
    holding: false,
    held: [] as (() => void)[],
    release() {
      state.holding = false
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
        places: [], bookcases: [], sections: [],
      })
    }
    if (method === 'GET' && path === '/shelves') return respond([])
    if (method === 'POST') {
      if (state.holding) await new Promise<void>((go) => state.held.push(go))
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

const open = () => render(<I18nProvider><PlanScreen /></I18nProvider>)

const posted = (path: string) =>
  server.calls.filter((c) => c === `POST ${path}`)

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

    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    await user.click(screen.getByRole('menuitem', { name: HE.reload }))
    server.release()
    // ⚠ Wait for the LAST re-derive, not the first: the push that landed
    // during the reload triggers a second one, and querying between them
    // finds the loading screen.
    await waitFor(() => {
      expect(server.calls.filter((c) => c === 'GET /map').length)
        .toBeGreaterThanOrEqual(4)
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
