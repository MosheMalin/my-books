/**
 * Mode S — freehand stroke, straightened afterwards.
 *
 * VISION §7's approach A, implemented honestly so the comparison against mode
 * D is fair: simplify, force each edge onto an axis, weld, snap, close. If S
 * loses it should lose on its own merits, not on a straw-man straightener.
 *
 * The pipeline is deliberately readable end to end, because the thing being
 * measured is *whether a user can predict it*.
 *
 * Pure. No React, no DOM.
 */

import type { Pt } from './geom'
import { dist, polygonArea, projectOnSegment, snapPt } from './geom'

/** RDP tolerance, in units. Bigger = fewer corners survive. */
export const SIMPLIFY_EPS = 0.9
/** Endpoints closer than this close the loop. */
export const CLOSE_TOL = 2.5
/** A room must enclose at least this much area to be believed. */
export const MIN_ROOM_AREA = 4

/** Ramer–Douglas–Peucker. Keeps the endpoints, drops what the line explains. */
export function simplify(points: readonly Pt[], eps = SIMPLIFY_EPS): Pt[] {
  if (points.length <= 2) return points.slice()
  const first = points[0]!
  const last = points[points.length - 1]!
  let worst = 0
  let idx = 0
  for (let i = 1; i < points.length - 1; i++) {
    const d = projectOnSegment(points[i]!, first, last).d
    if (d > worst) {
      worst = d
      idx = i
    }
  }
  if (worst <= eps) return [first, last]
  const left = simplify(points.slice(0, idx + 1), eps)
  const right = simplify(points.slice(idx), eps)
  return left.slice(0, -1).concat(right)
}

/**
 * Force a polyline onto the axes. Each edge takes the axis of its dominant
 * delta and the previous point supplies the other coordinate, so the result is
 * rectilinear by construction rather than by hope.
 */
export function rectilinear(points: readonly Pt[]): Pt[] {
  if (points.length < 2) return points.slice()
  const out: Pt[] = [points[0]!]
  for (let i = 1; i < points.length; i++) {
    const prev = out[out.length - 1]!
    const v = points[i]!
    const dx = Math.abs(v.x - prev.x)
    const dy = Math.abs(v.y - prev.y)
    out.push(dx >= dy ? { x: v.x, y: prev.y } : { x: prev.x, y: v.y })
  }
  return out
}

/** Drop zero-length edges and merge consecutive edges sharing an axis. */
export function weld(points: readonly Pt[]): Pt[] {
  const out: Pt[] = []
  for (const p of points) {
    const last = out[out.length - 1]
    if (last && last.x === p.x && last.y === p.y) continue
    out.push(p)
  }
  let i = 1
  while (i < out.length - 1) {
    const a = out[i - 1]!
    const b = out[i]!
    const c = out[i + 1]!
    const collinear = (a.x === b.x && b.x === c.x) || (a.y === b.y && b.y === c.y)
    if (collinear) out.splice(i, 1)
    else i++
  }
  return out
}

/**
 * Close a rectilinear polyline into a polygon.
 *
 * If the closing edge would be diagonal, one corner is INSERTED rather than a
 * point being dragged — dragging moves a wall the user drew, inserting adds
 * one they did not. Adding is the smaller lie, and it is visible.
 */
export function closeLoop(points: readonly Pt[]): Pt[] {
  const out = points.slice()
  if (out.length < 3) return out
  const first = out[0]!
  const last = out[out.length - 1]!
  if (last.x === first.x && last.y === first.y) return out.slice(0, -1)
  if (last.x === first.x || last.y === first.y) return out
  const prev = out[out.length - 2]!
  const lastEdgeIsHorizontal = prev.y === last.y
  out.push(
    lastEdgeIsHorizontal ? { x: last.x, y: first.y } : { x: first.x, y: last.y },
  )
  return weld(out)
}

/**
 * `weld` for a CLOSED polygon: it also checks the wrap-around triples, which
 * an open polyline has no reason to. Without it a traced rectangle comes back
 * with five corners — four walls and a seam — and the inspector then tells the
 * user their rectangular room has five walls.
 */
export function weldPolygon(points: readonly Pt[]): Pt[] {
  let out = weld(points)
  let changed = true
  while (changed && out.length > 3) {
    changed = false
    for (let i = 0; i < out.length; i++) {
      const a = out[(i - 1 + out.length) % out.length]!
      const b = out[i]!
      const c = out[(i + 1) % out.length]!
      const collinear = (a.x === b.x && b.x === c.x) || (a.y === b.y && b.y === c.y)
      if (collinear) {
        out = out.filter((_, j) => j !== i)
        changed = true
        break
      }
    }
  }
  return out
}

export type StrokeReading =
  | { kind: 'room'; points: Pt[] }
  | { kind: 'case'; from: Pt; to: Pt }
  | { kind: 'none'; reason: string }

/**
 * What the stroke MEANT. One gesture, two outcomes — which is exactly the
 * risk mode S carries and mode D does not: the reading can be wrong, and the
 * only correction is to undo and redraw.
 *
 * A stroke whose ends meet is a room. A stroke whose ends do not meet is a
 * bookcase, placed through the SAME wall-attachment rule mode D uses, so the
 * comparison isolates the authoring gesture and nothing else.
 */
export function readStroke(raw: readonly Pt[]): StrokeReading {
  if (raw.length < 2) return { kind: 'none', reason: 'a tap is not a stroke' }
  const simplified = simplify(raw)
  const closed = dist(simplified[0]!, simplified[simplified.length - 1]!) <= CLOSE_TOL

  if (closed) {
    const poly = weldPolygon(closeLoop(weld(rectilinear(simplified)).map((p) => snapPt(p))))
    if (poly.length < 4) return { kind: 'none', reason: 'not enough corners for a room' }
    if (polygonArea(poly) < MIN_ROOM_AREA) {
      return { kind: 'none', reason: 'too small to be a room' }
    }
    return { kind: 'room', points: poly }
  }

  const line = weld(rectilinear(simplified).map((p) => snapPt(p)))
  const seg = longestEdge(line)
  if (!seg) return { kind: 'none', reason: 'the stroke straightened to nothing' }
  return { kind: 'case', from: seg[0], to: seg[1] }
}

/** A bookcase is one straight run; a wandering stroke offers several, and the
 *  longest is the least surprising choice. */
export function longestEdge(points: readonly Pt[]): [Pt, Pt] | null {
  let best: [Pt, Pt] | null = null
  let bestLen = 0
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!
    const b = points[i]!
    const l = dist(a, b)
    if (l > bestLen) {
      bestLen = l
      best = [a, b]
    }
  }
  return bestLen > 0 ? best : null
}
