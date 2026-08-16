/**
 * The port's own seam: document ⇄ `/api/v1/map`.
 *
 * `core/*` came over from the lab byte-for-byte and its own 83 tests run
 * here unchanged — nothing below re-tests the editor. What is tested here is
 * only what the port ADDED: the shape translation, the off-by-one it must
 * survive, and the calls a change produces.
 */
import { describe, expect, it } from 'vitest'

import { emptyPlan, newBookcase, newSection, withColumnCount } from './core/model'
import type { Plan } from './core/model'
import { Ids, push, type Api } from './push'
import { planDiff, toPlan, type MapWire, type ShelfWire } from './sync'

const WIRE: MapWire = {
  sites: [{ id: 'st', name: 'הבית', order: 0 }],
  floors: [
    { id: 'fl', site_id: 'st', name: 'קומת קרקע', order: 0 },
    { id: 'up', site_id: 'st', name: 'קומה א', order: 1 },
    { id: 'other', site_id: 'st2', name: 'אצל ההורים', order: 0 },
  ],
  places: [
    { id: 'pl', floor_id: 'fl', name: 'סלון', rect: { x: 0, y: 0, w: 12, h: 9 }, order: 0 },
    { id: 'pl2', floor_id: 'other', name: 'לא שלי', rect: { x: 0, y: 0, w: 4, h: 4 }, order: 0 },
  ],
  bookcases: [
    {
      id: 'bc', floor_id: 'fl', place_id: 'pl', name: 'הכוננית', front: 'S',
      rect: { x: 0, y: 0, w: 4, h: 1 }, order: 0,
    },
  ],
  sections: [
    {
      id: 'hutch', bookcase_id: 'bc', ordinal: 2, column_levels: [2],
      default_levels: 2, default_depth: 1,
    },
    {
      id: 'base', bookcase_id: 'bc', ordinal: 1, column_levels: [2, 3],
      default_levels: 3, default_depth: 2,
    },
  ],
}

const SHELVES: ShelfWire[] = [
  { id: 'sh-a', depth_count: 2, capture_count: 1,
    address: { section_id: 'base', col: 1, level: 1 } },
  { id: 'sh-b', depth_count: 4, capture_count: 0,
    address: { section_id: 'base', col: 2, level: 3 } },
  { id: 'sh-photo', depth_count: 1, capture_count: 3, address: null },
]

describe('the document the server hands back', () => {
  it('carries section ids and orders them BOTTOM first', () => {
    const plan = toPlan(WIRE, SHELVES, 'st')
    const bookcase = plan.cases[0]!
    expect(bookcase.sections.map((s) => s.id)).toEqual(['base', 'hutch'])
    // ⚠ Ids CARRIED, never rebuilt from array position: `shelves.section_id`
    // refers to one now, and `persist.ts` regenerates them on file import.
    expect(bookcase.sections[0]!.id).toBe('base')
  })

  it('shifts col and level from the wire 1-based to the document 0-based', () => {
    const plan = toPlan(WIRE, SHELVES, 'st')
    const base = plan.cases[0]!.sections[0]!
    const first = base.shelves.find((s) => s.col === 0 && s.level === 0)!
    expect(first.depth).toBe(2)
    expect(first.photos).toBe(1)
    // (col 2, level 3) on the wire is (1, 2) in the document.
    const far = base.shelves.find((s) => s.col === 1 && s.level === 2)!
    expect(far.depth).toBe(4)
    expect(base.shelves.some((s) => s.col === -1 || s.level === -1)).toBe(false)
  })

  it('gives an undrawn slot the section default, not a missing shelf', () => {
    const base = toPlan(WIRE, SHELVES, 'st').cases[0]!.sections[0]!
    expect(base.shelves).toHaveLength(2 + 3)
    const blank = base.shelves.find((s) => s.col === 0 && s.level === 1)!
    expect(blank.depth).toBe(2)
    expect(blank.photos).toBe(0)
  })

  it('shows only the storeys of the site being edited', () => {
    const plan = toPlan(WIRE, SHELVES, 'st')
    expect(plan.floors.map((f) => f.id)).toEqual(['fl', 'up'])
    expect(plan.rooms.map((r) => r.id)).toEqual(['pl'])
    expect(plan.cases).toHaveLength(1)
  })

  it('leaves an unaddressed shelf out of the drawing entirely', () => {
    const plan = toPlan(WIRE, SHELVES, 'st')
    const every = plan.cases.flatMap((c) => c.sections.flatMap((s) => s.shelves))
    expect(every.some((s) => s.photos === 3)).toBe(false)
  })
})

describe('what a change asks the server to do', () => {
  const drawn = (): Plan => ({
    ...emptyPlan(),
    rooms: [{ id: 'r1', name: 'סלון', rect: { x: 0, y: 0, w: 9, h: 9 }, floorId: 'f1' }],
    cases: [newBookcase('c1', 'כוננית', { x: 0, y: 0, w: 4, h: 1 }, 'S', 'r1', 'f1', 2)],
  })

  it('creates before it edits, and removes last', () => {
    const before = drawn()
    const after: Plan = {
      ...before,
      rooms: [...before.rooms,
        { id: 'r2', name: 'מטבח', rect: { x: 9, y: 0, w: 5, h: 5 }, floorId: 'f1' }],
      cases: [],
    }
    const kinds = planDiff(before, after).map((o) => o.kind)
    expect(kinds).toEqual(['room.add', 'case.remove'])
  })

  it('sends the storey WITH the room, never on its own', () => {
    const before = drawn()
    const after: Plan = {
      ...before,
      floors: [...before.floors, { id: 'f2', name: 'קומה א' }],
      rooms: [{ ...before.rooms[0]!, floorId: 'f2' }],
    }
    const ops = planDiff(before, after)
    const edit = ops.find((o) => o.kind === 'room.edit')
    // ⚠ A room that changes storey alone leaves its bookcase behind and
    // BRICKS it — the server moves the furniture, and only if it is told
    // this was a storey move.
    expect(edit && 'movedStorey' in edit && edit.movedStorey).toBe(true)
  })

  it('says when a case let go of its room, because null means unchanged', () => {
    const before = drawn()
    const after: Plan = {
      ...before,
      cases: [{ ...before.cases[0]!, roomId: null }],
    }
    const op = planDiff(before, after)[0]!
    expect(op.kind).toBe('case.edit')
    expect('roomChanged' in op && op.roomChanged).toBe(true)
  })

  it('never sends a column count and a column height in one pass', () => {
    const before = drawn()
    const section = before.cases[0]!.sections[0]!
    const wider = withColumnCount(section, 4)
    const after: Plan = {
      ...before,
      cases: [{ ...before.cases[0]!, sections: [wider] }],
    }
    const grid = planDiff(before, after).filter(
      (o) => o.kind === 'section.columns' || o.kind === 'section.levels')
    // The API answers 400 for a request carrying both — the old
    // fall-through silently applied half an edit and reported success.
    expect(grid.map((o) => o.kind)).toEqual(['section.columns'])
  })

  it('reports a per-shelf depth override on its own', () => {
    const before = drawn()
    const section = before.cases[0]!.sections[0]!
    const bumped = {
      ...section,
      shelves: section.shelves.map((s) =>
        s.col === 1 && s.level === 2 ? { ...s, depth: 3 } : s),
    }
    const after: Plan = {
      ...before, cases: [{ ...before.cases[0]!, sections: [bumped] }],
    }
    const ops = planDiff(before, after)
    expect(ops).toHaveLength(1)
    expect(ops[0]).toMatchObject({ kind: 'shelf.depth', col: 1, level: 2, depth: 3 })
  })

  it('sees nothing when nothing changed', () => {
    expect(planDiff(drawn(), drawn())).toEqual([])
  })
})

describe('pushing', () => {
  const recorder = () => {
    const calls: [string, string, unknown][] = []
    const api: Api = {
      post: async (p, b) => {
        calls.push(['POST', p, b])
        return p === '/map/sections' ? { section: { id: 'server-sec' } }
          : { id: `server-${calls.length}` }
      },
      patch: async (p, b) => { calls.push(['PATCH', p, b]); return {} },
      del: async (p) => { calls.push(['DELETE', p, null]); return {} },
    }
    return { calls, api }
  }

  it('translates a locally minted id into the one the server chose', async () => {
    const { calls, api } = recorder()
    const ids = new Ids()
    const before = emptyPlan()
    const after: Plan = {
      ...before,
      rooms: [{ id: 'local-room', name: 'סלון',
        rect: { x: 0, y: 0, w: 9, h: 9 }, floorId: 'f1' }],
    }
    const room = after.rooms[0]!
    const later: Plan = { ...after, rooms: [{ ...room, name: 'הסלון' }] }

    expect((await push(api, planDiff(before, after), ids, 'st')).refusal)
      .toBeNull()
    expect((await push(api, planDiff(after, later), ids, 'st')).refusal)
      .toBeNull()
    // The document still calls it `local-room`; the wire never does again.
    expect(calls[1]![1]).toBe('/map/places/server-1')
  })

  it('empties a bookcase\'s slots before deleting it, in that order', async () => {
    const { calls, api } = recorder()
    const before: Plan = {
      ...emptyPlan(),
      cases: [newBookcase('c1', '', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1')],
    }
    await push(api, planDiff(before, emptyPlan()), new Ids(), 'st')
    expect(calls.map((c) => `${c[0]} ${c[1]}`)).toEqual([
      'DELETE /map/bookcases/c1/slots',
      'DELETE /map/bookcases/c1',
    ])
  })

  it('stops at the first refusal and hands it back', async () => {
    const calls: string[] = []
    const api: Api = {
      post: async (p) => {
        calls.push(p)
        throw { status: 409, detail: 'a bookcase holds at most 400 shelves' }
      },
      patch: async () => ({}),
      del: async () => ({}),
    }
    const before = emptyPlan()
    const after: Plan = {
      ...before,
      rooms: [{ id: 'r1', name: '', rect: { x: 0, y: 0, w: 9, h: 9 }, floorId: 'f1' },
              { id: 'r2', name: '', rect: { x: 9, y: 0, w: 9, h: 9 }, floorId: 'f1' }],
    }
    const { done, refusal } = await push(api, planDiff(before, after),
                                        new Ids(), 'st')
    expect(refusal?.status).toBe(409)
    expect(refusal?.detail).toContain('400 shelves')
    // ⚠ HOW FAR it got, which is what stops a retry replaying a create that
    // succeeded — the "phantom rooms" a review measured.
    expect(done).toBe(0)
    // ⚠ STOPPED. The second room's call assumed the first landed; pressing
    // on sends calls whose premise is gone.
    expect(calls).toHaveLength(1)
  })

  it('shifts a per-shelf depth back to the wire\'s 1-based address', async () => {
    const { calls, api } = recorder()
    const section = newSection('sec', 2)
    await push(api, [{
      kind: 'shelf.depth', section, col: 1, level: 2, depth: 3,
    }], new Ids(), 'st')
    expect(calls[0]![1]).toBe('/map/sections/sec/shelves/2/3')
    expect(calls[0]![2]).toEqual({ depth_count: 3 })
  })
})
