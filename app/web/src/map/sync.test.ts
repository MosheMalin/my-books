/**
 * The port's own seam: document ⇄ `/api/v1/map`.
 *
 * `core/*` came over from the lab byte-for-byte and its own 83 tests run
 * here unchanged — nothing below re-tests the editor. What is tested here is
 * only what the port ADDED: the shape translation, the off-by-one it must
 * survive, and the calls a change produces.
 */
import { describe, expect, it } from 'vitest'

import { allShelves, emptyPlan, newBookcase, newSection, withColumnCount, withGaps } from './core/model'
import type { Bookcase, Plan, Section } from './core/model'
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
    gaps: [],
      default_levels: 2, default_depth: 1,
    },
    {
      id: 'base', bookcase_id: 'bc', ordinal: 1, column_levels: [2, 3],
    gaps: [],
      default_levels: 3, default_depth: 2,
    },
  ],
}

const SHELVES: ShelfWire[] = [
  { id: 'sh-a', depth_count: 2, capture_count: 1, book_count: 0,
    address: { section_id: 'base', col: 1, level: 1 } },
  { id: 'sh-b', depth_count: 4, capture_count: 0, book_count: 0,
    address: { section_id: 'base', col: 2, level: 3 } },
  { id: 'sh-photo', depth_count: 1, capture_count: 3, book_count: 0, address: null },
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

  it('notices the case was TURNED, which is a fact about the furniture', () => {
    // `front` decides which physical end is column 1 (MAP_PLAN §7 Q3), so a
    // turn that never reaches the server re-labels every shelf in the case.
    const before = drawn()
    const after: Plan = {
      ...before, cases: [{ ...before.cases[0]!, front: 'N' }],
    }
    expect(planDiff(before, after).map((o) => o.kind)).toEqual(['case.edit'])
  })

  it('sees nothing when nothing changed', () => {
    expect(planDiff(drawn(), drawn())).toEqual([])
  })

  it('sends the column count AND the heights in one pass, count first', () => {
    // ⚠ The API's rule is one grid instruction per REQUEST. The old code read
    // it as one per PASS and left the heights "to the next pass, which
    // converges" — but `confirmed` becomes this document as soon as the push
    // succeeds, so there is no next pass and the heights were simply dropped.
    const before = drawn()
    const section = before.cases[0]!.sections[0]!
    const wider = withColumnCount(section, 3)
    const ragged: Section = { ...wider, columnLevels: [5, 5, 2] }
    const after: Plan = {
      ...before, cases: [{ ...before.cases[0]!, sections: [ragged] }],
    }
    const ops = planDiff(before, after)
    expect(ops.map((o) => o.kind))
      .toEqual(['section.columns', 'section.levels'])
    expect(ops[1]).toMatchObject({ col: 2, levels: 2 })
  })
})

// --- a case that is CREATED with more than the create call can say ---------

/** A section built by hand, so a test can state a shape the editor would take
 *  several gestures to reach. */
const section = (
  id: string, columnLevels: number[], defaultLevels: number, defaultDepth: number,
): Section => ({
  id,
  columnLevels,
  gaps: [],
  defaultLevels,
  defaultDepth,
  shelves: columnLevels.flatMap((levels, col) =>
    Array.from({ length: levels }, (_, level) =>
      ({ col, level, depth: defaultDepth, photos: 0, books: 0 }))),
})

describe('creating a bookcase the create call cannot describe', () => {
  /** A base of 2 columns of 5, and a hutch of 3 columns of 3 standing on it —
   *  the shape §3.6 exists for, and the shape a paste or an undo produces in
   *  ONE document change. */
  const stacked = (): Bookcase => ({
    ...newBookcase('c9', 'ארון', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 2),
    sections: [section('s1', [5, 5], 5, 1), section('s2', [3, 3, 3], 3, 2)],
  })

  const opsFor = (bc: Bookcase) =>
    planDiff(emptyPlan(), { ...emptyPlan(), cases: [bc] })

  it('asks for the hutch too, and for the shape the create could not carry', () => {
    // ⚠ Measured before this: `case.add` sent only `sections[0]`, the server
    // built a uniform case, and `confirmed` then recorded the loss as LANDED
    // — so it was never diffed again and the hutch existed only on screen.
    const kinds = opsFor(stacked()).map((o) => o.kind)
    expect(kinds.slice(0, 6)).toEqual([
      'case.add',        // base: 2 columns of 5 at depth 1 — all the body says
      'section.add',     // the hutch, which copies the base's shape server-side
      'section.defaults',
      'section.columns',
      'section.levels',  // the two columns the copy left at the base's height
      'section.levels',
    ])
    // ⚠ And six per-shelf calls, which are not waste. `create_section` fills
    // the copy's slots at the depth it copied — the base's 1 — and setting the
    // section's default afterwards deliberately does NOT reach back into
    // existing shelves (§3.3). Those ten slots become nine, and the six that
    // survive really do stand at the wrong depth until each is told.
    expect(kinds.slice(6)).toEqual(Array(6).fill('shelf.depth'))
  })

  it('states the hutch\'s own defaults, not the ones it was copied from', () => {
    const defaults = opsFor(stacked()).find((o) => o.kind === 'section.defaults')
    expect(defaults && 'section' in defaults && defaults.section)
      .toMatchObject({ id: 's2', defaultLevels: 3, defaultDepth: 2 })
  })

  it('carries a per-shelf override on a slot that did not exist yet', () => {
    // The old shelf loop compared against slots that ALREADY stood, so every
    // override on a freshly created case — exactly what a paste is — was
    // invisible to the diff.
    const bc = stacked()
    bc.sections[0]!.shelves = bc.sections[0]!.shelves.map((s) =>
      s.col === 1 && s.level === 4 ? { ...s, depth: 3 } : s)
    const ops = opsFor(bc).filter(
      (o) => o.kind === 'shelf.depth' && 'section' in o && o.section.id === 's1')
    expect(ops).toHaveLength(1)
    expect(ops[0]).toMatchObject({ col: 1, level: 4, depth: 3 })
  })

  it('carries an override on a slot the GRID ops are about to create', () => {
    // ⚠ The other half of the same defect, and the half a case with even
    // columns cannot show. `POST /map/bookcases` builds every column at the
    // section's default height, so a taller column's extra slots do not exist
    // until the `section.levels` call — and they arrive at the section's
    // default DEPTH. An override on one of them has nothing to compare
    // against, and comparing it against itself (which is what "only report a
    // slot that already stood" amounts to) reports nothing at all.
    const ragged = section('s1', [5, 7], 5, 1)
    ragged.shelves = ragged.shelves.map((s) =>
      s.col === 1 && s.level === 6 ? { ...s, depth: 4 } : s)
    const bc: Bookcase = {
      ...newBookcase('c9', '', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 2),
      sections: [ragged],
    }
    const ops = opsFor(bc)
    expect(ops.map((o) => o.kind))
      .toEqual(['case.add', 'section.levels', 'shelf.depth'])
    expect(ops[2]).toMatchObject({ col: 1, level: 6, depth: 4 })
  })

  it('names the section a new one stands ON, in every direction', () => {
    // ⚠ Three placements, one field. `top`/`bottom` could not express the
    // third: a section restored into the MIDDLE by an undo was sent as `top`,
    // appended by the server, and recorded as landed — so the drawing and the
    // library disagreed about which unit stands on which, and `ordinal` is
    // what an address prints.
    const stack = (ids: string[]): Bookcase => ({
      ...newBookcase('c1', '', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 2),
      sections: ids.map((id) => section(id, [2], 2, 1)),
    })
    const plan = (bc: Bookcase): Plan => ({ ...emptyPlan(), cases: [bc] })
    const added = (before: string[], after: string[]) =>
      planDiff(plan(stack(before)), plan(stack(after)))
        .find((o) => o.kind === 'section.add')

    expect(added(['a', 'b'], ['a', 'b', 'c'])).toMatchObject({ aboveId: 'b' })
    expect(added(['a', 'b'], ['c', 'a', 'b'])).toMatchObject({ aboveId: null })
    expect(added(['a', 'c'], ['a', 'b', 'c'])).toMatchObject({ aboveId: 'a' })
  })

  it('adds a plain section with ONE call, because the server copies its neighbour', () => {
    // The other half of the rule: what the server will build is tracked, so a
    // gesture whose result already matches it sends no corrections at all. A
    // client that "forced" the shape instead would issue five calls for every
    // press of `+ another section`.
    const before: Plan = { ...emptyPlan(), cases: [{
      ...newBookcase('c1', '', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 2),
      sections: [section('s1', [4, 4], 4, 2)],
    }] }
    const after: Plan = { ...before, cases: [{
      ...before.cases[0]!,
      sections: [...before.cases[0]!.sections, section('s2', [4, 4], 4, 2)],
    }] }
    expect(planDiff(before, after).map((o) => o.kind)).toEqual(['section.add'])
  })
})

describe('pushing', () => {
  /**
   * ⚠ The fake answers `/map/bookcases` with the SECTION it minted, because
   * the real one does. A review caught this modelling the pre-`BookcaseDrawnDTO`
   * shape: the client's half of that fix — reading `made.section.id` — could
   * be deleted with the whole ring green, which is exactly how the previous
   * attempt shipped a line reading a field that did not exist.
   */
  const recorder = () => {
    const calls: [string, string, unknown][] = []
    const api: Api = {
      post: async (p, b) => {
        calls.push(['POST', p, b])
        if (p === '/map/sections') return { section: { id: 'server-sec' } }
        if (p === '/map/bookcases') {
          return { id: `server-${calls.length}`,
                   section: { id: `server-first-${calls.length}` } }
        }
        return { id: `server-${calls.length}` }
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

  it('addresses the section the CREATE minted, not the local id', async () => {
    // ⚠ The measured symptom of getting this wrong: draw a bookcase, press
    // `+ column`, and every case drawn in the session answered `404 no such
    // section`. The server half is gated in `tests/test_api.py`; this is the
    // client half, which was previously deletable with a green board.
    const { calls, api } = recorder()
    const ids = new Ids()
    const bc = {
      ...newBookcase('c1', '', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 2),
      sections: [section('c1:s1', [5, 5], 5, 1)],
    }
    const first = bc.sections[0]!
    await push(api, [
      { kind: 'case.add', bookcase: bc },
      { kind: 'section.columns', section: first, columns: 3 },
      { kind: 'section.add', caseId: 'c1', section: section('c1:s2', [2], 2, 1),
        aboveId: 'c1:s1' },
    ], ids, 'st')
    expect(calls[0]![2]).toMatchObject({ columns: 2, levels: 5, depth: 1 })
    expect(calls[1]![1]).toBe('/map/sections/server-first-1')
    // …and the section it stands on is named by the server's id too.
    expect(calls[2]![2]).toMatchObject({ above_id: 'server-first-1' })
  })

  it('says `bottom` only for a section standing on the floor', async () => {
    const { calls, api } = recorder()
    await push(api, [{
      kind: 'section.add', caseId: 'c1', section: newSection('s9', 1),
      aboveId: null,
    }], new Ids(), 'st')
    expect(calls[0]![2]).toEqual({ bookcase_id: 'c1', where: 'bottom' })
  })

  it('empties a section\'s slots before removing it, in that order', async () => {
    // The op that detaches every shelf in a section from its address. The
    // ORDER is the rule: the server refuses the delete while a slot is full.
    const { calls, api } = recorder()
    const before: Plan = { ...emptyPlan(), cases: [{
      ...newBookcase('c1', '', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 2),
      sections: [section('s1', [2], 2, 1), section('s2', [2], 2, 1)],
    }] }
    const after: Plan = { ...before, cases: [{
      ...before.cases[0]!, sections: [before.cases[0]!.sections[0]!],
    }] }
    const ops = planDiff(before, after)
    expect(ops.map((o) => o.kind)).toEqual(['section.remove'])
    await push(api, ops, new Ids(), 'st')
    expect(calls.map((c) => `${c[0]} ${c[1]}`)).toEqual([
      'DELETE /map/sections/s2/slots',
      'DELETE /map/sections/s2',
    ])
  })

  it('sends `detach` rather than a null room, because null means unchanged', async () => {
    const { calls, api } = recorder()
    const bc = newBookcase('c1', '', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 2)
    await push(api, [
      { kind: 'case.edit', bookcase: bc, roomChanged: true },
    ], new Ids(), 'st')
    expect(calls[0]![2]).toMatchObject({ detach: true })
    expect(calls[0]![2]).not.toHaveProperty('place_id')
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

describe('gaps on the wire (P6.3.2)', () => {
  const wire = (gaps: { column: number; level: number }[]): MapWire => ({
    sites: [{ id: 'st', name: 'הבית', order: 0 }],
    floors: [{ id: 'f1', site_id: 'st', name: 'קרקע', order: 0 }],
    places: [{ id: 'p1', floor_id: 'f1', name: 'סלון', rect: { x: 0, y: 0, w: 9, h: 7 }, order: 0 }],
    bookcases: [{ id: 'c1', floor_id: 'f1', place_id: 'p1', name: 'כוננית', front: 'S',
                  rect: { x: 0, y: 0, w: 4, h: 1 }, order: 0 }],
    sections: [{ id: 's1', bookcase_id: 'c1', ordinal: 1, column_levels: [3, 3],
                 gaps, default_levels: 3, default_depth: 1 }],
  })

  it('re-bases the mask to 0 and leaves the gapped cell without a shelf', () => {
    // The pillar's one off-by-one, applied to the mask exactly as it is to an
    // address: the wire is 1-based, the document counts from 0.
    const plan = toPlan(wire([{ column: 2, level: 3 }]), [], 'st')
    const sec = plan.cases[0]!.sections[0]!

    expect(sec.gaps).toEqual([{ col: 1, level: 2 }])
    expect(sec.columnLevels).toEqual([3, 3], )
    expect(sec.shelves.some((s) => s.col === 1 && s.level === 2)).toBe(false)
    // …and the five other cells of the case are all still there, at the
    // levels they had. A gap is a mask, not a resize.
    expect(sec.shelves).toHaveLength(5)
    expect(sec.shelves.filter((s) => s.col === 1).map((s) => s.level)).toEqual([0, 1])
  })

  it('counts slots the way the server counts addresses, so the ceilings agree', () => {
    // `limits.ts:overCeiling` promises it MIRRORS the server. It counts
    // `allShelves`, and the server counts `Section.addresses` — which skips a
    // gapped cell. Building a shelf per CELL would have made the client
    // refuse gestures the server accepts, on a masked case.
    const masked = toPlan(wire([{ column: 1, level: 1 }, { column: 1, level: 2 }]), [], 'st')
    expect(allShelves(masked.cases[0]!)).toHaveLength(4)
  })

  it('sends one op per direction, and only after the grid has room for it', () => {
    // A cell must EXIST before it can be switched off — the server answers
    // 400 for a gap outside the extent — so the mask op follows the grid ops
    // in the same push.
    const had = toPlan(wire([]), [], 'st')
    const now = structuredClone(had)
    const sec = now.cases[0]!.sections[0]!
    now.cases[0]!.sections[0] = withGaps(
      { ...sec, columnLevels: [4, 3] }, [{ col: 0, level: 3 }], true)

    const ops = planDiff(had, now)
    expect(ops.map((o) => o.kind)).toEqual(['section.levels', 'section.gaps'])
    const op = ops[1] as { kind: 'section.gaps'; cells: unknown[]; gap: boolean }
    expect(op.gap).toBe(true)
    expect(op.cells).toEqual([{ col: 0, level: 3 }])
  })

  it('splits opening from restoring, because the route carries one sign', () => {
    const had = toPlan(wire([{ column: 1, level: 1 }]), [], 'st')
    const now = structuredClone(had)
    const sec = now.cases[0]!.sections[0]!
    now.cases[0]!.sections[0] = withGaps(
      withGaps(sec, [{ col: 0, level: 0 }], false),   // this one comes back
      [{ col: 1, level: 1 }], true,                   // this one goes
    )

    const ops = planDiff(had, now).filter((o) => o.kind === 'section.gaps') as {
      kind: 'section.gaps'; cells: { col: number; level: number }[]; gap: boolean
    }[]
    expect(ops).toHaveLength(2)
    expect(ops.find((o) => o.gap)!.cells).toEqual([{ col: 1, level: 1 }])
    expect(ops.find((o) => !o.gap)!.cells).toEqual([{ col: 0, level: 0 }])
  })

  it('does not ask to restore a cell the extent no longer has', () => {
    // Shrinking a column past a hole takes the hole with it (the server's
    // `_pruned`). Sending "put that cell back" afterwards would be a 400 for
    // a cell that is not there — the client must not manufacture one.
    const had = toPlan(wire([{ column: 1, level: 3 }]), [], 'st')
    const now = structuredClone(had)
    const sec = now.cases[0]!.sections[0]!
    now.cases[0]!.sections[0] = { ...sec, columnLevels: [1, 3], gaps: [],
      shelves: sec.shelves.filter((s) => s.col !== 0 || s.level < 1) }

    const ops = planDiff(had, now)
    expect(ops.map((o) => o.kind)).toEqual(['section.levels'])
  })
})
