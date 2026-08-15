/**
 * Mode D — snapping AT INPUT TIME.
 *
 * The whole argument for D over S (MAP_PLAN §4): snapping while you drag can
 * never guess wrong about what you already finished drawing, because there is
 * nothing finished to guess about. Every intermediate state is visible and
 * every one of them is legal.
 *
 * Pure. No React, no DOM.
 */

import type { Plan, Room, Wall } from './model'
import { rectPoints, wallsOf } from './model'
import type { Pt } from './geom'
import {
  add,
  dist,
  mul,
  orthogonalize,
  projectOnSegment,
  sideOf,
  snapPt,
  snapToGrid,
  sub,
  unit,
} from './geom'

/** How close a pointer must come, in UNITS, to be captured by a magnet. The
 *  renderer converts a finger-sized screen tolerance into units, so this is a
 *  floor, not the whole story. */
export const MAGNET = 1.2

export type WallHit = { roomId: string; wall: Wall; t: number; d: number; point: Pt }

/** The nearest wall of any room, within `tol` units. Ties go to the earlier
 *  room, which is stable rather than correct — no case has yet needed better. */
export function nearestWall(plan: Plan, p: Pt, tol = MAGNET): WallHit | null {
  let best: WallHit | null = null
  for (const room of plan.rooms) {
    for (const wall of wallsOf(room)) {
      const pr = projectOnSegment(p, wall.a, wall.b)
      if (pr.d <= tol && (best === null || pr.d < best.d)) {
        best = { roomId: room.id, wall, t: pr.t, d: pr.d, point: pr.point }
      }
    }
  }
  return best
}

/** Every room corner, for corner-to-corner magnets between adjacent rooms. */
export function nearestVertex(plan: Plan, p: Pt, tol = MAGNET): Pt | null {
  let best: Pt | null = null
  let bestD = tol
  for (const room of plan.rooms) {
    for (const v of room.points) {
      const d = dist(p, v)
      if (d <= bestD) {
        best = v
        bestD = d
      }
    }
  }
  return best
}

/**
 * The pointer position a room-drawing drag should actually use: an existing
 * corner if one is in reach (so two rooms share a wall exactly), otherwise the
 * grid.
 */
export function snapRoomCorner(plan: Plan, p: Pt, tol = MAGNET): Pt {
  return nearestVertex(plan, p, tol) ?? snapPt(p)
}

export function roomFromDrag(plan: Plan, from: Pt, to: Pt, tol = MAGNET): Pt[] {
  return rectPoints(snapRoomCorner(plan, from, tol), snapRoomCorner(plan, to, tol))
}

/** Polygon centroid by vertex average. Good enough to answer "which side is
 *  inside?" for the convex-ish rooms a house is made of. */
export function centroid(room: Room): Pt {
  if (room.points.length === 0) return { x: 0, y: 0 }
  let x = 0
  let y = 0
  for (const p of room.points) {
    x += p.x
    y += p.y
  }
  return { x: x / room.points.length, y: y / room.points.length }
}

export type CasePlacement = {
  a: Pt
  b: Pt
  side: 1 | -1
  attach: { roomId: string; wall: number } | null
}

/**
 * Place a bookcase from a drag.
 *
 * On a wall: both ends project onto that wall and slide along it in grid
 * steps, so the case is exactly ON the wall and exactly as long as you
 * dragged — the "length relative to the room walls" the brief asks for, with
 * no number typed anywhere.
 *
 * Off every wall: the segment is orthogonalized and grid-snapped, which is the
 * island case (MAP_PLAN §7 Q2 — snap is the default, not the only option).
 */
export function placeCase(plan: Plan, from: Pt, to: Pt, tol = MAGNET): CasePlacement {
  const hit = nearestWall(plan, from, tol)
  if (hit) {
    const room = plan.rooms.find((r) => r.id === hit.roomId)
    const dir = unit(sub(hit.wall.b, hit.wall.a))
    const along = (p: Pt): Pt => {
      const pr = projectOnSegment(p, hit.wall.a, hit.wall.b)
      const d = snapToGrid(dist(hit.wall.a, pr.point))
      return add(hit.wall.a, mul(dir, d))
    }
    const a = along(from)
    const b = along(to)
    // ⚠ Relative to the CASE's own baseline a→b, never to the wall's a→b.
    // They disagree whenever the user drags right-to-left, and the renderer
    // offsets the body along the case's baseline — so a wall-relative sign
    // put the wood outside the room on half the drags. Measured, not guessed.
    const inside = room ? sideOf(centroid(room), a, b) : 1
    return {
      a,
      b,
      side: inside === -1 ? -1 : 1,
      attach: { roomId: hit.roomId, wall: hit.wall.index },
    }
  }
  const a = snapPt(from)
  const b = snapPt(orthogonalize(a, to))
  return { a, b, side: 1, attach: null }
}

/** A drag is only a case once it has length. Below this it is a mis-tap. */
export const MIN_CASE_LENGTH = 1

export function isDegenerate(a: Pt, b: Pt): boolean {
  return dist(a, b) < MIN_CASE_LENGTH
}

/**
 * Slide an attached case along its own wall by `delta` units, clamped to the
 * wall's ends. Moving a case must not detach it: furniture slides along a
 * wall far more often than it leaves one.
 */
export function slideAlongWall(
  plan: Plan,
  placement: CasePlacement,
  delta: number,
): CasePlacement {
  if (!placement.attach) return placement
  const room = plan.rooms.find((r) => r.id === placement.attach!.roomId)
  if (!room) return placement
  const wall = wallsOf(room)[placement.attach.wall]
  if (!wall) return placement
  const dir = unit(sub(wall.b, wall.a))
  const wallLen = dist(wall.a, wall.b)
  const t0 = dist(wall.a, placement.a)
  const t1 = dist(wall.a, placement.b)
  const lo = Math.min(t0, t1)
  const hi = Math.max(t0, t1)
  const shift = Math.max(-lo, Math.min(wallLen - hi, snapToGrid(delta)))
  return {
    ...placement,
    a: add(wall.a, mul(dir, t0 + shift)),
    b: add(wall.a, mul(dir, t1 + shift)),
  }
}
