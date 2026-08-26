/**
 * Binding a shelf to a slot, at the two seams that decide it (P6.4c).
 *
 * The gesture cannot be driven end to end in jsdom: reaching the panel means
 * SELECTING a bookcase, and the plan canvas hit-tests one `onPointerDown`
 * against real coordinates that jsdom does not have — the same wall
 * `PlanScreen.test.tsx` records about drawing. So the two halves are tested
 * where they are: the HOOK against a fake `MapSource` (the seam `push`'s own
 * tests already use), and the PANEL against a fake `Actions`. The whole flow
 * on a real phone viewport is the browser walk this item owes.
 */
import { describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'

import { I18nProvider } from '../lib/i18n'
import { mapText } from './text'
import type { MapSource, MapSync, OffMapShelf } from './useMapSync'
import { useMapSync } from './useMapSync'

const HE = mapText('he')
const WAIT = { timeout: 4000 } as const

const EMPTY_MAP = {
  sites: [{ id: 'st', name: 'הבית', order: 0 }],
  floors: [{ id: 'fl', site_id: 'st', name: 'קרקע', order: 0 }],
  places: [], bookcases: [], sections: [],
}

/** A `MapSource` that records what it was asked to do. */
function fakeSource(overrides: Partial<MapSource> = {}) {
  const calls: [string, string, unknown][] = []
  let loads = 0
  const source: MapSource = {
    load: async () => {
      loads += 1
      return { map: EMPTY_MAP as never, shelves: [] as never }
    },
    ensureHome: async () => ({ siteId: 'st' }),
    offTheMap: async () => [],
    api: {
      post: async (p, b) => { calls.push(['POST', p, b]); return {} },
      put: async (p, b) => { calls.push(['PUT', p, b]); return {} },
      patch: async (p, b) => { calls.push(['PATCH', p, b]); return {} },
      del: async (p) => { calls.push(['DELETE', p, undefined]); return {} },
    },
    ...overrides,
  }
  return { source, calls, loads: () => loads }
}

/** Mount the hook and hand it back. Nothing is mocked but the source. */
function mountHook(source: MapSource) {
  const seen: { sync: MapSync | null } = { sync: null }
  function Probe() {
    const sync = useMapSync(source, HE)
    seen.sync = sync
    return <p>{sync.ready ? 'ready' : 'loading'}</p>
  }
  render(<I18nProvider><Probe /></I18nProvider>)
  return seen
}

describe('the hook that binds a shelf to a slot', () => {
  it('sends 1-BASED column and level, whatever the document counts from', async () => {
    // ⚠ The pillar's one off-by-one, and the reason it is a named gate: the
    // document's col/level are 0-based array positions and the API's are
    // 1-based. `ShelfAddress` refuses a 0 rather than re-basing silently, so
    // a forgotten shift raises on the server — but an EXTRA one does not. It
    // files the shelf one cell over, which nothing refuses and nobody sees.
    const { source, calls } = fakeSource()
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    act(() => seen.sync!.bindShelf('sh-1', 'sec-1', 0, 0, 'מדף'))
    await waitFor(() => expect(calls).toHaveLength(1), WAIT)
    expect(calls[0]).toEqual([
      'PUT', '/map/shelves/sh-1/address',
      { section_id: 'sec-1', col: 1, level: 1 },
    ])

    act(() => seen.sync!.bindShelf('sh-2', 'sec-1', 2, 3, 'מדף'))
    await waitFor(() => expect(calls).toHaveLength(2), WAIT)
    expect(calls[1]![2]).toEqual({ section_id: 'sec-1', col: 3, level: 4 })
  })

  it('re-derives after a bind, because `free` and `id` are server facts', async () => {
    const { source, calls, loads } = fakeSource()
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)
    const before = loads()

    act(() => seen.sync!.bindShelf('sh-1', 'sec-1', 0, 0, 'מדף התחתון'))
    await waitFor(() => expect(calls).toHaveLength(1), WAIT)
    await waitFor(() => expect(loads()).toBe(before + 1), WAIT)
    expect(seen.sync!.flash).toBe(HE.bound_here('מדף התחתון'))
  })

  it('unbinds by DELETE and says it can be taken back', async () => {
    const { source, calls } = fakeSource()
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    act(() => seen.sync!.unbindShelf('sh-9', 'sec-1', 1, 2, 'מדף א'))
    await waitFor(() => expect(calls).toHaveLength(1), WAIT)
    expect(calls[0]![0]).toBe('DELETE')
    // ⚠ The CELL travels with it, 1-based like every address on the wire: a
    // panel that has not seen the shelf move must not detach it from
    // wherever it now stands.
    expect(calls[0]![1]).toBe(
      '/map/shelves/sh-9/address?section_id=sec-1&col=2&level=3')
    await waitFor(() => expect(seen.sync!.flash)
      .toBe(HE.unbound_shelf('מדף א')), WAIT)
  })

  it('shows OUR sentence for a refusal, never the server English', async () => {
    // The server's 409 is "column 2, level 3 already holds shelf 9f3a…" —
    // true, English, and not something a household member can act on. The
    // client already knows what any refusal here MEANS: it only offers a bind
    // into a slot it was told was free, so a 4xx is the drawing having moved.
    const { source } = fakeSource({
      api: {
        post: async () => ({}),
        put: async () => {
          throw { status: 409, detail: 'column 2, level 3 already holds shelf x' }
        },
        patch: async () => ({}),
        del: async () => ({}),
      },
    })
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    act(() => seen.sync!.bindShelf('sh-1', 'sec-1', 0, 0, 'מדף'))
    await waitFor(() => expect(seen.sync!.notice).not.toBeNull(), WAIT)
    const notice = seen.sync!.notice!
    expect(notice.kind).toBe('refused')
    expect(notice.say?.(HE)).toBe(HE.slot_moved_on)
    expect(JSON.stringify(notice)).not.toContain('already holds shelf')
  })

  it('re-derives after a REFUSED bind too — the document is stale either way', async () => {
    // ⚠ The opposite of `undoLastEdit`, deliberately. A refused undo wrote
    // nothing, so re-deriving there would cost the owner their drawing
    // history for a press that changed nothing. Every refusal HERE means the
    // drawing moved under them, so the document is wrong and showing it for
    // one more gesture is how the second attempt is refused as well.
    const { source, loads } = fakeSource({
      api: {
        post: async () => ({}),
        put: async () => { throw { status: 409, detail: 'taken' } },
        patch: async () => ({}),
        del: async () => ({}),
      },
    })
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)
    const before = loads()

    act(() => seen.sync!.bindShelf('sh-1', 'sec-1', 0, 0, 'מדף'))
    await waitFor(() => expect(loads()).toBe(before + 1), WAIT)
    expect(seen.sync!.saved).toBe('saved')
  })

  it('asks the server for the off-the-map list rather than the document', async () => {
    // The shelf somebody opens this picker for is often the one photographed
    // two minutes ago, which a document derived before it existed cannot have.
    const off: OffMapShelf[] = [
      { id: 'sh-a', label: '', capture_count: 2, book_count: 0 },
    ]
    const offTheMap = vi.fn(async () => off)
    const { source } = fakeSource({ offTheMap })
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    expect(await seen.sync!.shelvesOffTheMap()).toEqual(off)
    expect(offTheMap).toHaveBeenCalledTimes(1)
  })

  it('DRAINS the push queue before it re-derives, or the drawing is lost', async () => {
    // ⚠⚠ The rule `slotWrite`'s docstring is emphatic about, and nothing
    // held it: a review dropped `await inflight.current` and the whole ring
    // stayed green. What it costs is the owner's work — `startOver()` bumps
    // `era`, and a queued `record` task whose era is stale RETURNS WITHOUT
    // SENDING its ops. So a room renamed a moment before pressing *take off
    // the map* would never reach the server, and nothing would say so.
    //
    // Held open by making the document's push wait: if the bind goes out
    // before that push has landed, the drain is not there.
    let releasePush: () => void = () => {}
    const held = new Promise<void>((go) => { releasePush = go })
    const order: string[] = []
    const { source } = fakeSource({
      api: {
        post: async (p) => { order.push(`POST ${p}`); await held; return { id: 'x' } },
        put: async (p) => { order.push(`PUT ${p}`); return {} },
        patch: async () => ({}),
        del: async () => ({}),
      },
    })
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    // One document edit, still in flight...
    act(() => seen.sync!.record({
      ...seen.sync!.initial!,
      rooms: [{ id: 'r1', name: 'חדר חדש', rect: { x: 0, y: 0, w: 4, h: 3 },
                floorId: 'fl' }],
    }))
    await waitFor(() => expect(order).toHaveLength(1), WAIT)

    // ...and a bind on top of it.
    act(() => seen.sync!.bindShelf('sh-1', 'sec-1', 0, 0, 'מדף'))
    await new Promise((go) => setTimeout(go, 20))
    expect(order, 'the bind overtook an edit that had not reached the server')
      .toEqual(['POST /map/places'])

    releasePush()
    await waitFor(() => expect(order).toEqual(
      ['POST /map/places', 'PUT /map/shelves/sh-1/address']), WAIT)
  })

  it('escapes the shelf id it puts in the path', async () => {
    // Ids are minted, so this is not a live injection — it is the escaping
    // being pinned, because "the ids are safe" is a claim about a different
    // module than the one building the URL.
    const { source, calls } = fakeSource()
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    act(() => seen.sync!.bindShelf('a b/c?d', 'sec 1', 0, 0, 'מדף'))
    await waitFor(() => expect(calls).toHaveLength(1), WAIT)
    expect(calls[0]![1]).toBe('/map/shelves/a%20b%2Fc%3Fd/address')

    act(() => seen.sync!.unbindShelf('a b/c?d', 'sec 1', 0, 0, 'מדף'))
    await waitFor(() => expect(calls).toHaveLength(2), WAIT)
    expect(calls[1]![1]).toBe(
      '/map/shelves/a%20b%2Fc%3Fd/address?section_id=sec%201&col=1&level=1')
  })

  it('says the SERVER\'s words for a refusal that is not about the drawing', async () => {
    // ⚠ A review measured a 403 answering "the drawing has changed since —
    // try again". The same sentence covered 401 (a session that expired
    // while the tab was backgrounded, which is the ordinary phone flow), 429
    // and every 5xx. Every one is a lie, and "try again" is an instruction
    // that will fail identically forever.
    const { source } = fakeSource({
      api: {
        post: async () => ({}),
        put: async () => { throw { status: 403, detail: 'you are a viewer' } },
        patch: async () => ({}),
        del: async () => ({}),
      },
    })
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    act(() => seen.sync!.bindShelf('sh-1', 'sec-1', 0, 0, 'מדף'))
    await waitFor(() => expect(seen.sync!.notice).not.toBeNull(), WAIT)
    expect(seen.sync!.notice!.say?.(HE)).toBeUndefined()
    expect(seen.sync!.notice!.detail).toBe('you are a viewer')
  })

  it("says the SERVER's sentence when a MERGE is refused, not ours", async () => {
    // ⚠ A merge's 409 is not a stale drawing. It is *a read of this shelf is
    // still running*, or *that shelf has itself been absorbed* — six things
    // to do next, carried in `detail.reason` with the sentence beside it so
    // no client has to parse English. Mapping them all to `slot_moved_on`
    // told the owner to try again, which for a running read fails
    // identically until it finishes. Same failure the bind path already
    // records fixing for 401/403/429.
    const { source } = fakeSource({
      api: {
        post: async () => {
          throw { status: 409,
                  detail: { reason: 'read_running',
                            say: 'a read of sh-1 is still running' } }
        },
        put: async () => ({}), patch: async () => ({}), del: async () => ({}),
      },
    })
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    act(() => seen.sync!.mergeShelf('ph-1', 'sh-1', 'survivor_first', 'מדף'))
    await waitFor(() => expect(seen.sync!.notice).not.toBeNull(), WAIT)

    expect(seen.sync!.notice!.detail).toBe('a read of sh-1 is still running')
    expect(seen.sync!.notice!.say?.(HE)).toBeUndefined()
  })

  it('still says OUR words when a merge meets a stale drawing (404)', async () => {
    const { source } = fakeSource({
      api: {
        post: async () => { throw { status: 404, detail: 'no such shelf' } },
        put: async () => ({}), patch: async () => ({}), del: async () => ({}),
      },
    })
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    act(() => seen.sync!.mergeShelf('ph-1', 'sh-1', 'survivor_first', 'מדף'))
    await waitFor(() => expect(seen.sync!.notice).not.toBeNull(), WAIT)

    expect(seen.sync!.notice!.say?.(HE)).toBe(HE.slot_moved_on)
  })

  it('does NOT blank the editor for a bind, and does for a site switch', async () => {
    // ⚠⚠ CLAUDE.md's own trap — *a refresh is not a first load* — attached to
    // a per-cell gesture. A review measured 1.42s of blank on localhost for
    // one tap: plan, bookcase, elevation and panel all gone, then back with
    // nothing selected. A site switch is the opposite answer on purpose: it
    // changes WHICH document this is, and showing the previous one meanwhile
    // would be showing another site's rooms.
    let release: () => void = () => {}
    const held = new Promise<void>((go) => { release = go })
    let loads = 0
    const { source } = fakeSource({
      load: async () => {
        loads += 1
        if (loads > 1) await held
        return { map: EMPTY_MAP as never, shelves: [] as never }
      },
    })
    const seen = mountHook(source)
    await screen.findByText('ready', {}, WAIT)

    act(() => seen.sync!.bindShelf('sh-1', 'sec-1', 0, 0, 'מדף'))
    await waitFor(() => expect(seen.sync!.ready).toBe(false), WAIT)
    expect(seen.sync!.refreshing, 'the screen would go blank for a bind')
      .toBe(true)
    release()
    await waitFor(() => expect(seen.sync!.ready).toBe(true), WAIT)
    expect(seen.sync!.refreshing).toBe(false)
  })
})
