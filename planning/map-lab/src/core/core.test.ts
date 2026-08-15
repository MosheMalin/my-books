/**
 * The core's tests. They port with the core (P6.3) — which is why they exist
 * in a lab that is otherwise outside every gate: the rules asserted here are
 * the rules `app/web` will inherit, and two of them are load-bearing decisions
 * rather than arithmetic.
 *
 *     npm --prefix planning/map-lab test
 */

import { describe, expect, it } from 'vitest'

import { normal, orthogonalize, pointInPolygon, pt, snapPt } from './geom'
import {
  applyDefaultDepth,
  newBookcase,
  shelfAt,
  shelvesDifferingFromDefaultDepth,
  withColumnCount,
  withColumnLevels,
  withDefaultDepth,
  withShelfDepth,
} from './model'
import type { Plan } from './model'
import { emptyPlan } from './model'
import { placeCase, nearestWall, roomFromDrag } from './snap'
import { closeLoop, readStroke, rectilinear, simplify, weld, weldPolygon } from './straighten'
import { parsePlan, serializePlan } from './persist'

const room = (id: string, x0: number, y0: number, x1: number, y1: number) => ({
  id,
  name: id,
  points: [pt(x0, y0), pt(x1, y0), pt(x1, y1), pt(x0, y1)],
})

const planWithRoom = (): Plan => ({ ...emptyPlan(), rooms: [room('r1', 0, 0, 20, 12)] })

describe('geometry', () => {
  it('snaps to whole units', () => {
    expect(snapPt(pt(3.4, 7.6))).toEqual(pt(3, 8))
  })

  it('orthogonalizes onto the dominant axis, keeping the anchor', () => {
    expect(orthogonalize(pt(0, 0), pt(10, 2))).toEqual(pt(10, 0))
    expect(orthogonalize(pt(0, 0), pt(2, 10))).toEqual(pt(0, 10))
  })

  it('knows which room a tap fell in', () => {
    const r = room('r1', 0, 0, 10, 10)
    expect(pointInPolygon(pt(5, 5), r.points)).toBe(true)
    expect(pointInPolygon(pt(15, 5), r.points)).toBe(false)
  })
})

describe('mode D — snapping at input time', () => {
  it('lands a case exactly on the wall it was dragged near', () => {
    const plan = planWithRoom()
    // dragged just inside the top wall (y=0), from x=3 to x=9, wobbling
    const placed = placeCase(plan, pt(3.2, 0.4), pt(9.1, 0.7))
    expect(placed.attach).toEqual({ roomId: 'r1', wall: 0 })
    expect(placed.a).toEqual(pt(3, 0))
    expect(placed.b).toEqual(pt(9, 0))
  })

  it('puts the case body INSIDE the room, on every wall', () => {
    // `side` is stored relative to the wall's own direction a→b, so a
    // consistently-wound room yields the SAME sign on every wall. Asserting
    // the sign would test the winding; assert where the wood ends up.
    const plan = planWithRoom()
    const poly = plan.rooms[0]!.points
    for (const drag of [
      [pt(3, 0.3), pt(9, 0.3)],   // top wall
      [pt(3, 11.7), pt(9, 11.7)], // bottom wall
      [pt(0.3, 3), pt(0.3, 9)],   // left wall
      [pt(19.7, 3), pt(19.7, 9)], // right wall
    ] as const) {
      const placed = placeCase(plan, drag[0], drag[1])
      const mid = pt((placed.a.x + placed.b.x) / 2, (placed.a.y + placed.b.y) / 2)
      const n = normal(placed.a, placed.b)
      const body = pt(mid.x + n.x * placed.side * 0.5, mid.y + n.y * placed.side * 0.5)
      expect(pointInPolygon(body, poly)).toBe(true)
    }
  })

  it('leaves an island orthogonal and unattached when no wall is near', () => {
    const plan = planWithRoom()
    const placed = placeCase(plan, pt(8, 6), pt(14.2, 6.9))
    expect(placed.attach).toBeNull()
    expect(placed.a.y).toBe(placed.b.y)
  })

  it('welds a new room corner onto an existing one so two rooms share a wall', () => {
    const plan = planWithRoom()
    // second room dragged from a hair off the first's bottom-left corner
    const points = roomFromDrag(plan, pt(0.3, 12.4), pt(20, 24))
    expect(points).toContainEqual(pt(0, 12))
  })

  it('finds no wall when the pointer is far from every room', () => {
    expect(nearestWall(planWithRoom(), pt(60, 60))).toBeNull()
  })
})

describe('the bookcase, and the depth rule', () => {
  it('materializes a shelf per column per level, at the default depth', () => {
    const bc = withColumnCount(
      newBookcase('c1', 'case', pt(0, 0), pt(6, 0), 1, null),
      3,
    )
    expect(bc.columnLevels).toEqual([5, 5, 5])
    expect(bc.shelves).toHaveLength(15)
    expect(shelfAt(bc, 2, 4)?.depth).toBe(1)
  })

  it('gives one column its own level count without touching the others', () => {
    const bc = withColumnLevels(
      withColumnCount(newBookcase('c1', 'case', pt(0, 0), pt(6, 0), 1, null), 3),
      1,
      2,
    )
    expect(bc.columnLevels).toEqual([5, 2, 5])
    expect(bc.shelves.filter((s) => s.col === 1)).toHaveLength(2)
    expect(bc.shelves.filter((s) => s.col === 0)).toHaveLength(5)
  })

  it('MAP_PLAN §3.3 — changing the case default leaves existing shelves alone', () => {
    const bc = newBookcase('c1', 'case', pt(0, 0), pt(6, 0), 1, null)
    const deepened = withDefaultDepth(bc, 3)
    expect(deepened.defaultDepth).toBe(3)
    expect(deepened.shelves.every((s) => s.depth === 1)).toBe(true)
    expect(shelvesDifferingFromDefaultDepth(deepened)).toBe(5)
  })

  it('MAP_PLAN §3.3 — a NEW column takes the default; the old ones do not', () => {
    const bc = withColumnCount(
      withDefaultDepth(newBookcase('c1', 'case', pt(0, 0), pt(6, 0), 1, null), 2),
      2,
    )
    expect(bc.shelves.filter((s) => s.col === 0).every((s) => s.depth === 1)).toBe(true)
    expect(bc.shelves.filter((s) => s.col === 1).every((s) => s.depth === 2)).toBe(true)
  })

  it('applies the default to existing shelves only when asked', () => {
    const bc = applyDefaultDepth(
      withDefaultDepth(newBookcase('c1', 'case', pt(0, 0), pt(6, 0), 1, null), 3),
    )
    expect(bc.shelves.every((s) => s.depth === 3)).toBe(true)
  })

  it('keeps a per-shelf override when the case default moves under it', () => {
    let bc = newBookcase('c1', 'case', pt(0, 0), pt(6, 0), 1, null)
    bc = withShelfDepth(bc, 0, 2, 3)
    bc = withDefaultDepth(bc, 2)
    expect(shelfAt(bc, 0, 2)?.depth).toBe(3)
    expect(shelfAt(bc, 0, 1)?.depth).toBe(1)
  })
})

describe('mode S — straightening', () => {
  it('drops the points the line already explains', () => {
    const line = [pt(0, 0), pt(1, 0.1), pt(2, 0), pt(3, 0.1), pt(10, 0)]
    expect(simplify(line).length).toBeLessThan(line.length)
  })

  it('forces every edge onto an axis', () => {
    const out = rectilinear([pt(0, 0), pt(10, 1), pt(11, 9)])
    for (let i = 1; i < out.length; i++) {
      const a = out[i - 1]!
      const b = out[i]!
      expect(a.x === b.x || a.y === b.y).toBe(true)
    }
  })

  it('inserts one corner rather than dragging a wall the user drew', () => {
    // an L that ends short of its start in BOTH axes
    const closed = closeLoop(weld([pt(0, 0), pt(10, 0), pt(10, 8), pt(3, 8)]))
    expect(closed[closed.length - 1]).toEqual(pt(3, 0))
    expect(closed).toContainEqual(pt(10, 8))
  })

  it('reads a closed wobble as a room', () => {
    const stroke = [
      pt(0, 0), pt(5, 0.4), pt(10.2, 0), pt(10, 4), pt(10.3, 8),
      pt(5, 8.2), pt(0.2, 8), pt(0, 4), pt(0.1, 0.6),
    ]
    const read = readStroke(stroke)
    expect(read.kind).toBe('room')
    if (read.kind === 'room') expect(read.points.length).toBeGreaterThanOrEqual(4)
  })

  it('reads an open wobble as a bookcase along its longest run', () => {
    const read = readStroke([pt(2, 0.3), pt(5, 0.1), pt(8, 0.4), pt(9, 0.2)])
    expect(read.kind).toBe('case')
    if (read.kind === 'case') expect(read.from.y).toBe(read.to.y)
  })

  it('refuses a tap', () => {
    expect(readStroke([pt(1, 1)]).kind).toBe('none')
  })

  it('reads a REAL traced rectangle as four walls, not five', () => {
    // The stroke a browser actually produced: a hand-drawn ~12x8 room, ten
    // samples a side, corners overshooting and undershooting. It came back
    // with a fifth corner at the seam until `weldPolygon` looked across it —
    // and the inspector then told the owner his rectangular room had 5 walls.
    const corners = [
      pt(20, 1.98), pt(32, 2.16), pt(31.8, 9.98), pt(20.18, 9.8), pt(20.09, 2.3),
    ]
    const stroke: ReturnType<typeof pt>[] = []
    for (let i = 1; i < corners.length; i++) {
      const a = corners[i - 1]!
      const b = corners[i]!
      for (let s = 0; s < 10; s++) {
        stroke.push(
          pt(
            a.x + ((b.x - a.x) * s) / 10 + Math.sin(s) * 0.18,
            a.y + ((b.y - a.y) * s) / 10 + Math.cos(s) * 0.18,
          ),
        )
      }
    }
    const read = readStroke(stroke)
    expect(read.kind).toBe('room')
    if (read.kind !== 'room') return
    expect(read.points).toHaveLength(4)
    for (let i = 0; i < 4; i++) {
      const a = read.points[i]!
      const b = read.points[(i + 1) % 4]!
      expect(a.x === b.x || a.y === b.y).toBe(true)
    }
  })

  it('welds a collinear seam corner that plain weld cannot see', () => {
    // a,b,c collinear ACROSS the wrap: the last point sits on the closing edge
    const poly = weldPolygon([pt(0, 0), pt(10, 0), pt(10, 8), pt(0, 8), pt(0, 4)])
    expect(poly).toHaveLength(4)
  })
})

describe('the exported file', () => {
  it('round-trips rooms and cases', () => {
    const plan: Plan = {
      ...planWithRoom(),
      cases: [newBookcase('c1', 'ארון הסלון', pt(3, 0), pt(9, 0), 1, { roomId: 'r1', wall: 0 })],
    }
    const back = parsePlan(serializePlan(plan))
    expect(back.ok).toBe(true)
    if (back.ok) {
      expect(back.plan.rooms[0]!.points).toEqual(plan.rooms[0]!.points)
      expect(back.plan.cases[0]!.name).toBe('ארון הסלון')
      expect(back.plan.cases[0]!.shelves).toHaveLength(5)
    }
  })

  it('never exports the tracing underlay', () => {
    const plan: Plan = {
      ...planWithRoom(),
      underlay: { src: 'blob:whatever', x: 0, y: 0, scale: 1, aspect: 1.5, opacity: 0.5 },
    }
    expect(serializePlan(plan)).not.toContain('blob:')
  })

  it('refuses junk instead of importing half a plan', () => {
    expect(parsePlan('nonsense').ok).toBe(false)
    expect(parsePlan('{"format":"something.else"}').ok).toBe(false)
    expect(parsePlan(JSON.stringify({ format: 'booksnap.map-lab.plan', plan: {} })).ok).toBe(false)
  })
})
