/**
 * The core's tests. They port with the core (P6.3) — which is why they exist
 * in a lab that is otherwise outside every gate: the rules asserted here are
 * the rules `app/web` will inherit, and several are load-bearing decisions
 * rather than arithmetic.
 *
 *     npm --prefix planning/map-lab test
 */

import { describe, expect, it } from 'vitest'

import { pt, snapToGrid } from './geom'
import type { Rect } from './rect'
import {
  bottom,
  flushSide,
  handleAt,
  handlePositions,
  intersects,
  overlaps,
  rectFrom,
  right,
  snapCoord,
  snapCorner,
  snapPoint,
  snapRect,
} from './rect'
import {
  applyDefaultDepth,
  columnDividers,
  depthLines,
  frontFor,
  isTooSmall,
  newBookcase,
  reattach,
  roomFor,
  shelfAt,
  shelvesDifferingFromDefaultDepth,
  withColumnCount,
  withColumnLevels,
  withDefaultDepth,
  withShelfDepth,
} from './model'
import type { Plan, Room } from './model'
import { emptyPlan } from './model'
import { parsePlan, serializePlan } from './persist'

const rect = (x: number, y: number, w: number, h: number): Rect => ({ x, y, w, h })
const room = (id: string, r: Rect): Room => ({ id, name: id, rect: r })
const livingRoom = room('r1', rect(0, 0, 20, 12))
const planWith = (...rooms: Room[]): Plan => ({ ...emptyPlan(), rooms })

describe('rectangles', () => {
  it('normalizes a drag in any direction', () => {
    expect(rectFrom(pt(10, 8), pt(2, 3))).toEqual(rect(2, 3, 8, 5))
  })

  it('snaps to the grid when nothing is near', () => {
    expect(snapToGrid(3.4)).toBe(3)
    expect(snapCoord(3.4, [], 1)).toBe(3)
  })

  it('prefers a neighbour edge OVER the grid', () => {
    // 12.4 would round to 12; a wall at 12.5 is what the user meant. Rounding
    // to the grid instead leaves a hairline gap no zoom level can close.
    expect(snapCoord(12.4, [12.5], 1)).toBe(12.5)
  })

  it('attaches one room flush to another WITHOUT resizing it', () => {
    // second room dragged to just past the first one's right edge
    const moved = snapRect(rect(20.4, 0.3, 14, 10), [livingRoom.rect], 1.2)
    expect(moved.x).toBe(20) // flush with right(r1) === 20
    expect(moved.y).toBe(0)
    expect(moved.w).toBe(14) // unchanged — a move never resizes
    expect(moved.h).toBe(10)
  })

  it('attaches by whichever edge is nearer, not always the first', () => {
    // dragged so its RIGHT edge is what sits near the room's left edge
    const moved = snapRect(rect(-14.3, 0, 14, 10), [livingRoom.rect], 1.2)
    expect(right(moved)).toBe(0)
    expect(moved.w).toBe(14)
  })

  it('snaps a corner being drawn onto a neighbour edge', () => {
    const p = snapPoint(pt(19.7, 11.6), [livingRoom.rect], 1.2)
    expect(p).toEqual(pt(20, 12))
  })

  it('treats touching as touching, not overlapping', () => {
    expect(overlaps(livingRoom.rect, rect(20, 0, 5, 5))).toBe(false)
    expect(overlaps(livingRoom.rect, rect(19, 0, 5, 5))).toBe(true)
  })

  it('lets a selection band catch a bookcase flush against a wall', () => {
    // A case standing on the wall shares exactly its edge with the room, so a
    // band dragged along that wall must count touching as a hit.
    const band = rect(0, 10, 6, 2)
    const flushCase = rect(2, 12, 5, 1)
    expect(overlaps(band, flushCase)).toBe(false)
    expect(intersects(band, flushCase)).toBe(true)
    expect(intersects(band, rect(2, 20, 5, 1))).toBe(false)
  })

  it('never lets a magnet collapse the rectangle being drawn', () => {
    // The magnet is measured on SCREEN; at 11 px a cell a fingertip is 1.3
    // units — wider than a bookcase is deep. Drawing a one-unit-deep case
    // against the north wall pulled BOTH its edges onto y=0 and it vanished.
    const anchor = pt(2, 0) // already snapped onto the wall
    const free = snapCorner(pt(10, 1.2), anchor, [livingRoom.rect], 1.3)
    expect(free.y).toBe(1)
    expect(free.x).toBe(10)
  })

  it('still lets the far edge snap to a genuine neighbour', () => {
    const anchor = pt(2, 0)
    // the room's south wall is 12 away — nothing to do with collapsing
    expect(snapCorner(pt(11.7, 4), anchor, [livingRoom.rect], 1.3).x).toBe(12)
  })

  it('picks the wall along the case s LONG side when it is in a corner', () => {
    // a long thin case in the top-left corner is against the TOP wall
    expect(flushSide(rect(0, 0, 8, 1), livingRoom.rect)).toBe('N')
    // a tall thin one in the same corner is against the LEFT wall
    expect(flushSide(rect(0, 0, 1, 8), livingRoom.rect)).toBe('W')
  })

  it('keeps all eight handles on a rectangle with room for them', () => {
    expect(handlePositions(livingRoom.rect, 1.3)).toHaveLength(8)
  })

  it('drops the CORNER handles on a thin bookcase, keeping the edges', () => {
    // A bookcase one unit deep is the normal case. At that size the corners
    // sit inside a fingertip of the edge midpoints and win the hit test — so
    // dragging the right edge to lengthen the case collapsed its depth to 0.
    const thin = rect(3, 11, 8, 1)
    const hs = handlePositions(thin, 1.3)
    expect(hs).toHaveLength(4)
    expect(hs.every(({ h }) => h.hx === 0 || h.hy === 0)).toBe(true)
  })

  it('grabs the NEAREST handle, not the first one in reach', () => {
    const thin = rect(3, 11, 8, 1)
    // pressing the middle of the right edge must lengthen it, not resize depth
    expect(handleAt(thin, pt(11, 11.5), 1.3)).toEqual({ hx: 1, hy: 0 })
    // and the top edge midpoint is still the top edge
    expect(handleAt(thin, pt(7, 11), 1.3)).toEqual({ hx: 0, hy: -1 })
  })

  it('grabs nothing when the pointer is nowhere near a handle', () => {
    expect(handleAt(livingRoom.rect, pt(10, 6), 1.3)).toBeNull()
  })

  it('refuses a mis-tap as a rectangle', () => {
    expect(isTooSmall(rectFrom(pt(3, 3), pt(3.4, 9)))).toBe(true)
    expect(isTooSmall(rect(4, 1, 4, 1))).toBe(false)
  })
})

describe('the bookcase on the plan', () => {
  it('faces INTO the room from every wall', () => {
    expect(frontFor(rect(2, 0, 8, 1), livingRoom)).toBe('S') // north wall
    expect(frontFor(rect(2, 11, 8, 1), livingRoom)).toBe('N') // south wall
    expect(frontFor(rect(0, 2, 1, 8), livingRoom)).toBe('E') // west wall
    expect(frontFor(rect(19, 2, 1, 8), livingRoom)).toBe('W') // east wall
  })

  it('falls back to its long side when it stands free of every wall', () => {
    expect(frontFor(rect(5, 5, 6, 1), livingRoom)).toBe('S')
    expect(frontFor(rect(5, 5, 1, 6), livingRoom)).toBe('E')
  })

  it('re-attaches to the room it is moved INTO', () => {
    const plan = planWith(livingRoom, room('r2', rect(20, 0, 14, 10)))
    const bc = newBookcase('c1', '', rect(2, 0, 8, 1), 'S', 'r1')
    const movedIntoR2 = reattach({ ...bc, rect: rect(22, 0, 8, 1) }, plan)
    expect(movedIntoR2.roomId).toBe('r2')
  })

  it('KEEPS its room when moved outside every room — attachment is the point', () => {
    // "Attach bookcases to a room so they move together" (owner, 2026-08-16).
    // A case nudged half a unit past its wall silently losing its room is the
    // bug this rule exists to prevent. Detaching is done on purpose, in the
    // panel.
    const plan = planWith(livingRoom)
    const bc = newBookcase('c1', '', rect(2, 0, 8, 1), 'S', 'r1')
    const outside = reattach({ ...bc, rect: rect(2, 40, 8, 1) }, plan)
    expect(outside.roomId).toBe('r1')
  })

  it('turns a case that would otherwise face into the wall it just met', () => {
    const plan = planWith(livingRoom)
    const facingUp = newBookcase('c1', '', rect(2, 5, 8, 1), 'N', 'r1')
    // slide it onto the north wall: facing N would be facing into the wall
    const onWall = reattach({ ...facingUp, rect: rect(2, 0, 8, 1) }, plan)
    expect(onWall.front).toBe('S')
  })

  it('leaves a deliberately turned case alone when it is not against a wall', () => {
    const plan = planWith(livingRoom)
    const turned = newBookcase('c1', '', rect(4, 5, 8, 1), 'N', 'r1')
    expect(reattach({ ...turned, rect: rect(5, 6, 8, 1) }, plan).front).toBe('N')
  })

  it('knows which room it stands in, by its centre', () => {
    const plan = planWith(livingRoom, room('r2', rect(20, 0, 14, 10)))
    expect(roomFor(plan, rect(2, 0, 8, 1))?.id).toBe('r1')
    expect(roomFor(plan, rect(22, 0, 8, 1))?.id).toBe('r2')
    expect(roomFor(plan, rect(60, 60, 2, 2))).toBeNull()
  })

  it('divides columns ACROSS the front, whichever way it faces', () => {
    const wide = withColumnCount(newBookcase('c1', '', rect(2, 0, 9, 1), 'S', 'r1'), 3)
    expect(columnDividers(wide).every((d) => d.a.x === d.b.x)).toBe(true)
    const tall = withColumnCount(newBookcase('c2', '', rect(0, 2, 1, 9), 'E', 'r1'), 3)
    expect(columnDividers(tall).every((d) => d.a.y === d.b.y)).toBe(true)
  })

  it('draws one line per extra DECLARED depth row, not per drawn thickness', () => {
    const bc = newBookcase('c1', '', rect(2, 0, 8, 3), 'S', 'r1')
    expect(depthLines(bc)).toHaveLength(0)
    expect(depthLines(withDefaultDepth(bc, 3))).toHaveLength(2)
    // the drawn rectangle is unchanged: depth is declared, never derived
    expect(withDefaultDepth(bc, 3).rect).toEqual(bc.rect)
  })
})

describe('columns, levels, and the depth rule', () => {
  const base = () => newBookcase('c1', 'case', rect(2, 0, 8, 1), 'S', 'r1')

  it('materializes a shelf per column per level, at the default depth', () => {
    const bc = withColumnCount(base(), 3)
    expect(bc.columnLevels).toEqual([5, 5, 5])
    expect(bc.shelves).toHaveLength(15)
    expect(shelfAt(bc, 2, 4)?.depth).toBe(1)
  })

  it('gives one column its own level count without touching the others', () => {
    const bc = withColumnLevels(withColumnCount(base(), 3), 1, 2)
    expect(bc.columnLevels).toEqual([5, 2, 5])
    expect(bc.shelves.filter((s) => s.col === 1)).toHaveLength(2)
    expect(bc.shelves.filter((s) => s.col === 0)).toHaveLength(5)
  })

  it('MAP_PLAN §3.3 — changing the case default leaves existing shelves alone', () => {
    const deepened = withDefaultDepth(base(), 3)
    expect(deepened.defaultDepth).toBe(3)
    expect(deepened.shelves.every((s) => s.depth === 1)).toBe(true)
    expect(shelvesDifferingFromDefaultDepth(deepened)).toBe(5)
  })

  it('MAP_PLAN §3.3 — a NEW column takes the default; the old ones do not', () => {
    const bc = withColumnCount(withDefaultDepth(base(), 2), 2)
    expect(bc.shelves.filter((s) => s.col === 0).every((s) => s.depth === 1)).toBe(true)
    expect(bc.shelves.filter((s) => s.col === 1).every((s) => s.depth === 2)).toBe(true)
  })

  it('applies the default to existing shelves only when asked', () => {
    const bc = applyDefaultDepth(withDefaultDepth(base(), 3))
    expect(bc.shelves.every((s) => s.depth === 3)).toBe(true)
  })

  it('keeps a per-shelf override when the case default moves under it', () => {
    let bc = base()
    bc = withShelfDepth(bc, 0, 2, 3)
    bc = withDefaultDepth(bc, 2)
    expect(shelfAt(bc, 0, 2)?.depth).toBe(3)
    expect(shelfAt(bc, 0, 1)?.depth).toBe(1)
  })
})

describe('the exported file', () => {
  it('round-trips rooms and cases', () => {
    const plan: Plan = {
      ...planWith(livingRoom),
      cases: [newBookcase('c1', 'ארון הסלון', rect(2, 0, 8, 1), 'S', 'r1')],
    }
    const back = parsePlan(serializePlan(plan))
    expect(back.ok).toBe(true)
    if (back.ok) {
      expect(back.plan.rooms[0]!.rect).toEqual(livingRoom.rect)
      expect(back.plan.cases[0]!.name).toBe('ארון הסלון')
      expect(back.plan.cases[0]!.front).toBe('S')
      expect(back.plan.cases[0]!.shelves).toHaveLength(5)
    }
  })

  it('never exports the tracing underlay', () => {
    const plan: Plan = {
      ...planWith(livingRoom),
      underlay: { src: 'blob:whatever', x: 0, y: 0, scale: 1, aspect: 1.5, opacity: 0.5 },
    }
    expect(serializePlan(plan)).not.toContain('blob:')
  })

  it('refuses junk instead of importing half a plan', () => {
    expect(parsePlan('nonsense').ok).toBe(false)
    expect(parsePlan('{"format":"something.else"}').ok).toBe(false)
    expect(parsePlan(JSON.stringify({ format: 'booksnap.map-lab.plan', plan: {} })).ok).toBe(false)
  })

  it('refuses a zero-area rectangle rather than importing an invisible room', () => {
    const file = {
      format: 'booksnap.map-lab.plan',
      plan: { rooms: [{ id: 'r1', name: '', rect: { x: 0, y: 0, w: 0, h: 5 } }], cases: [] },
    }
    expect(parsePlan(JSON.stringify(file)).ok).toBe(false)
  })

  it('keeps a room and a bookcase that were drawn flush EXACTLY flush', () => {
    const plan: Plan = {
      ...planWith(livingRoom),
      cases: [newBookcase('c1', '', rect(2, 0, 8, 1), 'S', 'r1')],
    }
    const back = parsePlan(serializePlan(plan))
    if (!back.ok) throw new Error('should parse')
    expect(back.plan.cases[0]!.rect.y).toBe(back.plan.rooms[0]!.rect.y)
    expect(bottom(back.plan.rooms[0]!.rect)).toBe(12)
  })
})
