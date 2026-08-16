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
  nearBorder,
  overlaps,
  rectFrom,
  right,
  snapCoord,
  snapCorner,
  snapPoint,
  snapRect,
} from './rect'
import {
  DEFAULT_COLUMNS,
  addSection,
  floorContents,
  allShelves,
  applyDefaultDepth,
  columnCount,
  columnDividers,
  depthLines,
  frontFor,
  isTooSmall,
  mapSection,
  maxDepth,
  newBookcase,
  newSection,
  overviewLayout,
  reattach,
  removeSection,
  roomFor,
  sectionIndex,
  sectionsTopDown,
  shelfAt,
  shelvesDifferingFromDefaultDepth,
  withColumnCount,
  withColumnLevels,
  withDefaultDepth,
  withRect,
  withShelfDepth,
} from './model'
import type { Plan, Room } from './model'
import { emptyPlan } from './model'
import { parsePlan, serializePlan } from './persist'

const rect = (x: number, y: number, w: number, h: number): Rect => ({ x, y, w, h })
const room = (id: string, r: Rect): Room => ({ id, name: id, rect: r, floorId: 'f1' })
const livingRoom = room('r1', rect(0, 0, 20, 12))
const planWith = (...rooms: Room[]): Plan => ({ ...emptyPlan(), rooms })
const F = 'f1'

describe('rectangles', () => {
  it('normalizes a drag in any direction', () => {
    expect(rectFrom(pt(10, 8), pt(2, 3))).toEqual(rect(2, 3, 8, 5))
  })

  it('keeps every rectangle on WHOLE units', () => {
    // Rendered on screen as "11.000000000000004×9". `snapRect` moves by adding
    // a correction, and x + (round(x) - x) is not exactly round(x); the dust
    // then became a snap candidate and spread to the next rectangle.
    expect(rectFrom(pt(0.0000001, 0), pt(11.000000000000004, 9))).toEqual(rect(0, 0, 11, 9))
    const drifted = { x: 9.000000000000002, y: 0, w: 11, h: 9 }
    expect(snapRect(drifted, [], 1.2)).toEqual(rect(9, 0, 11, 9))
    expect(Number.isInteger(right(snapRect(drifted, [], 1.2)))).toBe(true)
  })

  it('sweeps float dust out of a file on the way in', () => {
    const file = {
      format: 'booksnap.map-lab.plan',
      plan: {
        rooms: [{ id: 'r1', name: '', rect: { x: 9.000000000000002, y: 0, w: 11.000000000000004, h: 9 } }],
        cases: [],
      },
    }
    const back = parsePlan(JSON.stringify(file))
    expect(back.ok).toBe(true)
    if (back.ok) expect(back.plan.rooms[0]!.rect).toEqual(rect(9, 0, 11, 9))
  })

  it('snaps to the grid when nothing is near', () => {
    expect(snapToGrid(3.4)).toBe(3)
    expect(snapCoord(3.4, [], 1)).toBe(3)
  })

  it('lets a rectangle change by ONE unit next to a neighbour', () => {
    // "In some cases I could not increase/decrease bookcases in 1 unit, only
    // by 2" (owner, 2026-08-16). With a neighbour edge at 12, aiming at
    // exactly 11 put the pointer 1.0 units away — inside the 1.3 magnet — so
    // the magnet dragged it to 12 while the grid line it sat exactly on was
    // ignored. A magnet that overrides a perfect grid hit is not helping.
    expect(snapCoord(11, [12], 1.3)).toBe(11)
    expect(snapCoord(11.1, [12], 1.3)).toBe(11)
    // still snaps once the neighbour really is the nearer thing
    expect(snapCoord(11.8, [12], 1.3)).toBe(12)
  })

  it('moves a rectangle by ONE unit next to a neighbour too', () => {
    // same rule on the move path, which has its own shift arithmetic
    const moved = snapRect(rect(11, 0, 4, 4), [rect(16, 0, 4, 4)], 1.3)
    expect(moved.x).toBe(11)
    expect(right(moved)).toBe(15)
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

  it('grabs a room from ON or JUST OUTSIDE its wall', () => {
    const r = rect(0, 0, 20, 12)
    expect(nearBorder(r, pt(10, 0), 0.2, 1)).toBe(true) // exactly on it
    expect(nearBorder(r, pt(10, -0.8), 0.2, 1)).toBe(true) // just outside
    expect(nearBorder(r, pt(-0.5, 6), 0.2, 1)).toBe(true) // outside the left wall
  })

  it('leaves room to draw a bookcase FLUSH against the wall', () => {
    // "So if I want to draw a case near the border it will not move the room
    // instead" (owner, 2026-08-16). The band is lopsided on purpose: you aim
    // AT the wall to grab the room and just INSIDE it to draw against it.
    const r = rect(0, 0, 20, 12)
    expect(nearBorder(r, pt(10, 0.3), 0.2, 1)).toBe(false)
    expect(nearBorder(r, pt(10, 6), 0.2, 1)).toBe(false) // deep inside
    expect(nearBorder(r, pt(10, -2), 0.2, 1)).toBe(false) // well clear of it
  })

  it('never leaves a thin rectangle with no border at all', () => {
    // a one-unit-deep bookcase would otherwise be entirely "inside"
    const thin = rect(0, 0, 8, 1)
    expect(nearBorder(thin, pt(4, 0.5), 2, 1)).toBe(true)
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
    const bc = newBookcase('c1', '', rect(2, 0, 8, 1), 'S', 'r1', F)
    const movedIntoR2 = reattach({ ...bc, rect: rect(22, 0, 8, 1) }, plan)
    expect(movedIntoR2.roomId).toBe('r2')
  })

  it('KEEPS its room when moved outside every room — attachment is the point', () => {
    // "Attach bookcases to a room so they move together" (owner, 2026-08-16).
    // A case nudged half a unit past its wall silently losing its room is the
    // bug this rule exists to prevent. Detaching is done on purpose, in the
    // panel.
    const plan = planWith(livingRoom)
    const bc = newBookcase('c1', '', rect(2, 0, 8, 1), 'S', 'r1', F)
    const outside = reattach({ ...bc, rect: rect(2, 40, 8, 1) }, plan)
    expect(outside.roomId).toBe('r1')
  })

  it('turns a case that would otherwise face into the wall it just met', () => {
    const plan = planWith(livingRoom)
    const facingUp = newBookcase('c1', '', rect(2, 5, 8, 1), 'N', 'r1', F)
    // slide it onto the north wall: facing N would be facing into the wall
    const onWall = reattach({ ...facingUp, rect: rect(2, 0, 8, 1) }, plan)
    expect(onWall.front).toBe('S')
  })

  it('leaves a deliberately turned case alone when it is not against a wall', () => {
    const plan = planWith(livingRoom)
    const turned = newBookcase('c1', '', rect(4, 5, 8, 1), 'N', 'r1', F)
    expect(reattach({ ...turned, rect: rect(5, 6, 8, 1) }, plan).front).toBe('N')
  })

  it('knows which room it stands in, by its centre', () => {
    const plan = planWith(livingRoom, room('r2', rect(20, 0, 14, 10)))
    expect(roomFor(plan, rect(2, 0, 8, 1), F)?.id).toBe('r1')
    expect(roomFor(plan, rect(22, 0, 8, 1), F)?.id).toBe('r2')
    expect(roomFor(plan, rect(60, 60, 2, 2), F)).toBeNull()
  })

  it('divides columns ACROSS the front, whichever way it faces', () => {
    const wide = newBookcase('c1', '', rect(2, 0, 9, 1), 'S', 'r1', F, 3)
    expect(columnDividers(wide).every((d) => d.a.x === d.b.x)).toBe(true)
    const tall = newBookcase('c2', '', rect(0, 2, 1, 9), 'E', 'r1', F, 3)
    expect(columnDividers(tall).every((d) => d.a.y === d.b.y)).toBe(true)
  })

  it('draws one line per extra DECLARED depth row, not per drawn thickness', () => {
    const bc = newBookcase('c1', '', rect(2, 0, 8, 3), 'S', 'r1', F)
    const deep = mapSection(bc, bc.sections[0]!.id, (s) => withDefaultDepth(s, 3))
    expect(depthLines(bc)).toHaveLength(0)
    expect(depthLines(deep)).toHaveLength(2)
    // the drawn rectangle is unchanged: depth is declared, never derived
    expect(deep.rect).toEqual(bc.rect)
  })
})

describe('columns, levels, and the depth rule (per section)', () => {
  const base = () => newSection('s1')

  it('materializes a shelf per column per level, at the default depth', () => {
    const sec = withColumnCount(base(), 3)
    expect(sec.columnLevels).toEqual([5, 5, 5])
    expect(sec.shelves).toHaveLength(15)
    expect(shelfAt(sec, 2, 4)?.depth).toBe(1)
  })

  it('gives one column its own level count without touching the others', () => {
    const sec = withColumnLevels(withColumnCount(base(), 3), 1, 2)
    expect(sec.columnLevels).toEqual([5, 2, 5])
    expect(sec.shelves.filter((s) => s.col === 1)).toHaveLength(2)
    expect(sec.shelves.filter((s) => s.col === 0)).toHaveLength(5)
  })

  it('MAP_PLAN §3.3 — changing the default leaves existing shelves alone', () => {
    const deepened = withDefaultDepth(base(), 3)
    expect(deepened.defaultDepth).toBe(3)
    expect(deepened.shelves.every((s) => s.depth === 1)).toBe(true)
    expect(shelvesDifferingFromDefaultDepth(deepened)).toBe(5)
  })

  it('MAP_PLAN §3.3 — a NEW column takes the default; the old ones do not', () => {
    const sec = withColumnCount(withDefaultDepth(base(), 2), 2)
    expect(sec.shelves.filter((s) => s.col === 0).every((s) => s.depth === 1)).toBe(true)
    expect(sec.shelves.filter((s) => s.col === 1).every((s) => s.depth === 2)).toBe(true)
  })

  it('applies the default to existing shelves only when asked', () => {
    const sec = applyDefaultDepth(withDefaultDepth(base(), 3))
    expect(sec.shelves.every((s) => s.depth === 3)).toBe(true)
  })

  it('keeps a per-shelf override when the default moves under it', () => {
    let sec = base()
    sec = withShelfDepth(sec, 0, 2, 3)
    sec = withDefaultDepth(sec, 2)
    expect(shelfAt(sec, 0, 2)?.depth).toBe(3)
    expect(shelfAt(sec, 0, 1)?.depth).toBe(1)
  })
})

describe('sections — a bookcase built of two, one on the other', () => {
  const base = () => newBookcase('c1', 'case', rect(2, 0, 8, 1), 'S', 'r1', F, 3)

  it('gives a new bookcase TWO columns, because most bookcases have two', () => {
    const bc = newBookcase('c1', '', rect(2, 0, 8, 1), 'S', 'r1', F)
    expect(columnCount(bc.sections[0]!)).toBe(DEFAULT_COLUMNS)
    expect(DEFAULT_COLUMNS).toBe(2)
  })

  it('starts as ONE section, so the ordinary bookcase costs nothing', () => {
    const bc = base()
    expect(bc.sections).toHaveLength(1)
    expect(columnCount(bc.sections[0]!)).toBe(3)
    expect(allShelves(bc)).toHaveLength(15)
  })

  it('stacks a second section on top, keeping index 0 on the floor', () => {
    const bc = addSection(base(), 'top')
    expect(bc.sections).toHaveLength(2)
    // stored bottom-first, drawn top-first — one reversal, in one place
    expect(sectionsTopDown(bc)[0]!.id).toBe(bc.sections[1]!.id)
    expect(sectionIndex(bc, bc.sections[0]!.id)).toBe(0)
  })

  it('lets the two sections divide DIFFERENTLY — the whole point', () => {
    let bc = addSection(base(), 'top')
    const top = bc.sections[1]!.id
    bc = mapSection(bc, top, (s) => withColumnCount(s, 2))
    expect(columnCount(bc.sections[0]!)).toBe(3)
    expect(columnCount(bc.sections[1]!)).toBe(2)
    expect(allShelves(bc)).toHaveLength(15 + 10)
  })

  it('seeds a new section from its neighbour rather than from nothing', () => {
    // a hutch has about as many columns as the base it stands on; starting
    // from a blank 1x5 would mean re-entering what is already on screen
    const bc = addSection(mapSection(base(), 'c1:s1', (s) => withDefaultDepth(s, 2)), 'top')
    expect(columnCount(bc.sections[1]!)).toBe(3)
    expect(bc.sections[1]!.shelves.every((s) => s.depth === 2)).toBe(true)
  })

  it('gives every section a distinct id, including after a removal', () => {
    let bc = addSection(addSection(base(), 'top'), 'top')
    bc = removeSection(bc, bc.sections[1]!.id)
    bc = addSection(bc, 'top')
    expect(new Set(bc.sections.map((s) => s.id)).size).toBe(bc.sections.length)
  })

  it('refuses to remove the last section', () => {
    const bc = base()
    expect(removeSection(bc, bc.sections[0]!.id).sections).toHaveLength(1)
  })

  it('reports the deepest declared depth across every section', () => {
    let bc = addSection(base(), 'top')
    bc = mapSection(bc, bc.sections[1]!.id, (s) => applyDefaultDepth(withDefaultDepth(s, 3)))
    expect(maxDepth(bc)).toBe(3)
    expect(depthLines(bc)).toHaveLength(2)
  })

  it('draws the plan dividers from the BOTTOM section — the footprint', () => {
    let bc = addSection(base(), 'top')
    bc = mapSection(bc, bc.sections[1]!.id, (s) => withColumnCount(s, 5))
    expect(columnDividers(bc)).toHaveLength(2) // 3 columns on the floor
  })
})

describe('floors', () => {
  it('starts with exactly one, so nothing handles "no floor"', () => {
    expect(emptyPlan().floors).toHaveLength(1)
  })

  it('finds a room only on ITS OWN storey', () => {
    // Two floors both start at 0,0. Without this the kitchen is under your
    // feet while you draw the bedroom, and a bookcase attaches downwards.
    const ground = { ...room('r1', rect(0, 0, 20, 12)), floorId: 'f1' }
    const upstairs = { ...room('r2', rect(0, 0, 20, 12)), floorId: 'f2' }
    const plan: Plan = { ...emptyPlan(), floors: [{ id: 'f1', name: 'g' }, { id: 'f2', name: 'u' }], rooms: [ground, upstairs] }
    expect(roomFor(plan, rect(2, 0, 8, 1), 'f1')?.id).toBe('r1')
    expect(roomFor(plan, rect(2, 0, 8, 1), 'f2')?.id).toBe('r2')
  })

  it('never attaches a bookcase to a room on another storey', () => {
    const upstairs = { ...room('r2', rect(0, 0, 20, 12)), floorId: 'f2' }
    const plan: Plan = { ...emptyPlan(), floors: [{ id: 'f1', name: 'g' }, { id: 'f2', name: 'u' }], rooms: [upstairs] }
    const bc = newBookcase('c1', '', rect(2, 0, 8, 1), 'S', null, 'f1')
    expect(reattach(bc, plan).roomId).toBeNull()
  })

  it('counts what is standing on a storey, for a delete that refuses', () => {
    const plan: Plan = {
      ...emptyPlan(),
      rooms: [room('r1', rect(0, 0, 20, 12))],
      cases: [newBookcase('c1', '', rect(2, 0, 8, 1), 'S', 'r1', F)],
    }
    expect(floorContents(plan, F)).toEqual({ rooms: 1, cases: 1 })
    expect(floorContents(plan, 'f2')).toEqual({ rooms: 0, cases: 0 })
  })

  it('reads a file with no floors as one floor holding everything', () => {
    const older = {
      format: 'booksnap.map-lab.plan',
      version: 3,
      plan: {
        rooms: [{ id: 'r1', name: 'סלון', rect: { x: 0, y: 0, w: 20, h: 12 } }],
        cases: [],
      },
    }
    const back = parsePlan(JSON.stringify(older))
    expect(back.ok).toBe(true)
    if (!back.ok) return
    expect(back.plan.floors).toHaveLength(1)
    expect(back.plan.rooms[0]!.floorId).toBe(back.plan.floors[0]!.id)
  })

  it('rehomes anything pointing at a floor the file does not contain', () => {
    const broken = {
      format: 'booksnap.map-lab.plan',
      plan: {
        floors: [{ id: 'f1', name: 'Ground floor' }],
        rooms: [{ id: 'r1', name: '', rect: { x: 0, y: 0, w: 4, h: 4 }, floorId: 'f9' }],
        cases: [],
      },
    }
    const back = parsePlan(JSON.stringify(broken))
    if (!back.ok) throw new Error('should parse')
    expect(back.plan.rooms[0]!.floorId).toBe('f1')
  })

  it('stacks storeys as ROWS — three floors, three rows', () => {
    // Rows rather than columns because that is how a building is: the storey
    // above is above (owner, 2026-08-16).
    const plan: Plan = {
      ...emptyPlan(),
      floors: [{ id: 'f1', name: 'g' }, { id: 'f2', name: 'u' }, { id: 'f3', name: 't' }],
      rooms: [
        room('r1', rect(0, 0, 20, 12)),
        { ...room('r2', rect(0, 0, 10, 8)), floorId: 'f2' },
        { ...room('r3', rect(0, 0, 14, 6)), floorId: 'f3' },
      ],
    }
    const cells = overviewLayout(plan, 6)
    expect(cells.map((c) => c.bandStart)).toEqual([0, 18, 36]) // band 12 + gap 6
    expect(new Set(cells.map((c) => c.band)).size).toBe(1) // equal rows
    expect(new Set(cells.map((c) => c.width)).size).toBe(1) // and one column
  })

  it('gives every storey an EQUAL band, whatever its own size', () => {
    // "Three floors — divide the board to 3, each has one floor" (owner,
    // 2026-08-16). Packing them at their natural widths made a small storey
    // look squeezed beside a large one, when comparing them is the point.
    const plan: Plan = {
      ...emptyPlan(),
      floors: [{ id: 'f1', name: 'g' }, { id: 'f2', name: 'u' }],
      rooms: [
        room('r1', rect(0, 0, 20, 12)),
        { ...room('r2', rect(0, 0, 10, 8)), floorId: 'f2' },
      ],
    }
    const [ground, upstairs] = overviewLayout(plan, 6)
    expect(ground!.band).toBe(12) // the tallest storey sets the row height
    expect(upstairs!.band).toBe(12) // equal, though its plan is shorter
    expect(ground!.bandStart).toBe(0)
    expect(upstairs!.bandStart).toBe(18)
  })

  it('centres a narrow storey in its band rather than jamming it against the rule', () => {
    const plan: Plan = {
      ...emptyPlan(),
      floors: [{ id: 'f1', name: 'g' }, { id: 'f2', name: 'u' }],
      rooms: [
        room('r1', rect(0, 0, 20, 12)),
        { ...room('r2', rect(0, 0, 10, 8)), floorId: 'f2' },
      ],
    }
    const [, upstairs] = overviewLayout(plan, 6)
    // the column is 20 wide and this plan is 10, so it starts 5 in; its row
    // runs 18..30 and the plan is 8 tall, so it starts 2 down
    expect(upstairs!.dx).toBe(5)
    expect(upstairs!.dy).toBe(20)
  })

  it('shifts a storey that does not start at the origin back into its band', () => {
    const plan: Plan = {
      ...emptyPlan(),
      floors: [{ id: 'f1', name: 'g' }],
      rooms: [room('r1', rect(40, 30, 10, 10))],
    }
    // otherwise a plan drawn far from 0,0 would sit outside its band entirely
    expect(overviewLayout(plan)[0]!.dx).toBe(-40)
    expect(overviewLayout(plan)[0]!.dy).toBe(-30)
  })

  it('turns a bookcase when a resize makes it wider than it is tall', () => {
    // Columns divide across the FRONT, and the front is the long face — that
    // is what a bookcase is. Making a tall narrow case wide has to move the
    // columns with it (owner, 2026-08-16).
    const tall = newBookcase('c1', '', rect(5, 4, 1, 8), 'E', null, F)
    const wide = withRect(tall, rect(5, 4, 8, 1), null)
    expect(tall.front).toBe('E')
    expect(wide.front).toBe('S')
  })

  it('leaves the facing alone when the resize does not flip which side is longer', () => {
    // so a one-unit nudge never undoes a deliberate Turn
    const bc = newBookcase('c1', '', rect(5, 4, 8, 1), 'N', null, F)
    expect(withRect(bc, rect(5, 4, 9, 1), null).front).toBe('N')
  })

  it('still faces into the room when the flipped case is against a wall', () => {
    const flipped = withRect(
      newBookcase('c1', '', rect(0, 2, 1, 8), 'E', 'r1', F),
      rect(0, 0, 8, 1),
      livingRoom,
    )
    expect(flipped.front).toBe('S') // north wall, so the books look south
  })

  it('round-trips several floors', () => {
    const plan: Plan = {
      ...emptyPlan(),
      floors: [{ id: 'f1', name: 'קרקע' }, { id: 'f2', name: 'עליה' }],
      rooms: [room('r1', rect(0, 0, 20, 12)), { ...room('r2', rect(0, 0, 10, 10)), floorId: 'f2' }],
    }
    const back = parsePlan(serializePlan(plan))
    if (!back.ok) throw new Error('should parse')
    expect(back.plan.floors.map((f) => f.name)).toEqual(['קרקע', 'עליה'])
    expect(back.plan.rooms[1]!.floorId).toBe('f2')
  })
})

describe('the exported file', () => {
  it('round-trips rooms and cases', () => {
    const plan: Plan = {
      ...planWith(livingRoom),
      cases: [newBookcase('c1', 'ארון הסלון', rect(2, 0, 8, 1), 'S', 'r1', F)],
    }
    const back = parsePlan(serializePlan(plan))
    expect(back.ok).toBe(true)
    if (back.ok) {
      expect(back.plan.rooms[0]!.rect).toEqual(livingRoom.rect)
      expect(back.plan.cases[0]!.name).toBe('ארון הסלון')
      expect(back.plan.cases[0]!.front).toBe('S')
      expect(allShelves(back.plan.cases[0]!)).toHaveLength(10) // 2 columns x 5
    }
  })

  it('reads a v2 bookcase as ONE section, so a saved drawing survives', () => {
    // The owner had a real plan in a real browser when sections landed.
    // Dropping it to a lab refactor would be exactly the "work will not get
    // lost" failure the autosave exists to prevent.
    const v2 = {
      format: 'booksnap.map-lab.plan',
      version: 2,
      plan: {
        rooms: [{ id: 'r1', name: 'סלון', rect: { x: 0, y: 0, w: 20, h: 12 } }],
        cases: [
          {
            id: 'c2',
            name: 'ארון',
            rect: { x: 2, y: 0, w: 8, h: 1 },
            front: 'S',
            roomId: 'r1',
            defaultLevels: 4,
            defaultDepth: 2,
            columnLevels: [4, 4],
            shelves: [{ col: 0, level: 0, depth: 3, photos: 1 }],
          },
        ],
      },
    }
    const back = parsePlan(JSON.stringify(v2))
    expect(back.ok).toBe(true)
    if (!back.ok) return
    const bc = back.plan.cases[0]!
    expect(bc.sections).toHaveLength(1)
    expect(bc.sections[0]!.id).toBe('c2:s1') // rebuilt, so "add a section" cannot collide
    expect(bc.sections[0]!.columnLevels).toEqual([4, 4])
    expect(bc.sections[0]!.defaultDepth).toBe(2)
    expect(shelfAt(bc.sections[0]!, 0, 0)?.depth).toBe(3)
    expect(bc.name).toBe('ארון')
  })

  it('gives an imported case ids the section editor can extend', () => {
    const plan: Plan = {
      ...planWith(livingRoom),
      cases: [addSection(newBookcase('c1', '', rect(2, 0, 8, 1), 'S', 'r1', F), 'top')],
    }
    const back = parsePlan(serializePlan(plan))
    if (!back.ok) throw new Error('should parse')
    const grown = addSection(back.plan.cases[0]!, 'top')
    expect(new Set(grown.sections.map((s) => s.id)).size).toBe(3)
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
      cases: [newBookcase('c1', '', rect(2, 0, 8, 1), 'S', 'r1', F)],
    }
    const back = parsePlan(serializePlan(plan))
    if (!back.ok) throw new Error('should parse')
    expect(back.plan.cases[0]!.rect.y).toBe(back.plan.rooms[0]!.rect.y)
    expect(bottom(back.plan.rooms[0]!.rect)).toBe(12)
  })
})
