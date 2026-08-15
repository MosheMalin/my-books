/**
 * Vector and segment maths, in ABSTRACT UNITS.
 *
 * Framework-free by rule (MAP_PLAN §5, P6.0 constraint 1): no React, no DOM,
 * no fetch. This module ports into `app/web` verbatim at P6.3.
 *
 * Nothing here knows about pixels. The plan is stored in an abstract unit
 * space and only the renderer maps units to screen — a canvas resize, a phone
 * rotation or a zoom must not be able to corrupt a plan (MAP_PLAN §3.4).
 */

export type Pt = { x: number; y: number }

/** One grid step. A typical room is ~30-50 units across. */
export const GRID = 1
/** Every Nth grid line is drawn heavier. Cosmetic only. */
export const GRID_MAJOR = 5

export const pt = (x: number, y: number): Pt => ({ x, y })
export const add = (a: Pt, b: Pt): Pt => ({ x: a.x + b.x, y: a.y + b.y })
export const sub = (a: Pt, b: Pt): Pt => ({ x: a.x - b.x, y: a.y - b.y })
export const mul = (a: Pt, k: number): Pt => ({ x: a.x * k, y: a.y * k })
export const dot = (a: Pt, b: Pt): number => a.x * b.x + a.y * b.y
export const len = (a: Pt): number => Math.hypot(a.x, a.y)
export const dist = (a: Pt, b: Pt): number => Math.hypot(b.x - a.x, b.y - a.y)
export const eq = (a: Pt, b: Pt): boolean => a.x === b.x && a.y === b.y

/** Unit vector, or {0,0} for a degenerate segment (callers must tolerate it). */
export function unit(a: Pt): Pt {
  const l = len(a)
  return l === 0 ? { x: 0, y: 0 } : { x: a.x / l, y: a.y / l }
}

/** Left-hand normal of a→b. Which physical side that is depends on the
 *  renderer's axis convention; the editor calls it `side: 1 | -1` and lets the
 *  user flip, rather than asserting a handedness nobody can verify. */
export const normal = (a: Pt, b: Pt): Pt => {
  const d = unit(sub(b, a))
  return { x: -d.y, y: d.x }
}

/** Round to the grid. The one place a coordinate becomes canonical. */
export const snapToGrid = (v: number, grid = GRID): number =>
  Math.round(v / grid) * grid

export const snapPt = (p: Pt, grid = GRID): Pt => ({
  x: snapToGrid(p.x, grid),
  y: snapToGrid(p.y, grid),
})

export type Projection = {
  /** The closest point ON the segment (clamped to its ends). */
  point: Pt
  /** Position along the segment, 0 at `a`, 1 at `b`, clamped. */
  t: number
  /** Distance from the query point to `point`. */
  d: number
}

export function projectOnSegment(p: Pt, a: Pt, b: Pt): Projection {
  const ab = sub(b, a)
  const l2 = dot(ab, ab)
  if (l2 === 0) return { point: a, t: 0, d: dist(p, a) }
  const t = Math.max(0, Math.min(1, dot(sub(p, a), ab) / l2))
  const point = add(a, mul(ab, t))
  return { point, t, d: dist(p, point) }
}

/** Signed side of the line a→b that `p` falls on: +1, -1, or 0 on the line. */
export function sideOf(p: Pt, a: Pt, b: Pt): 1 | -1 | 0 {
  const c = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
  return c > 0 ? 1 : c < 0 ? -1 : 0
}

/** Angle in radians, -PI..PI. */
export const angle = (a: Pt, b: Pt): number => Math.atan2(b.y - a.y, b.x - a.x)

/**
 * Force a segment onto the nearer axis, keeping `a` fixed and preserving the
 * dominant extent. This is the whole of "orthogonal snapping" — deliberately
 * the simplest rule that cannot surprise: the longer delta wins.
 */
export function orthogonalize(a: Pt, b: Pt): Pt {
  const dx = b.x - a.x
  const dy = b.y - a.y
  return Math.abs(dx) >= Math.abs(dy) ? { x: b.x, y: a.y } : { x: a.x, y: b.y }
}

/** Axis-aligned bounding box of a point set. Empty input → a zero box at 0,0. */
export function bbox(points: readonly Pt[]): { min: Pt; max: Pt } {
  if (points.length === 0) return { min: pt(0, 0), max: pt(0, 0) }
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const p of points) {
    if (p.x < minX) minX = p.x
    if (p.y < minY) minY = p.y
    if (p.x > maxX) maxX = p.x
    if (p.y > maxY) maxY = p.y
  }
  return { min: pt(minX, minY), max: pt(maxX, maxY) }
}

/** Point-in-polygon, ray casting. Used for "which room did I tap in?". */
export function pointInPolygon(p: Pt, poly: readonly Pt[]): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i]!
    const b = poly[j]!
    const straddles = a.y > p.y !== b.y > p.y
    if (straddles && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) {
      inside = !inside
    }
  }
  return inside
}

/** Shoelace area, always positive. Zero for a degenerate polygon. */
export function polygonArea(poly: readonly Pt[]): number {
  let acc = 0
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    acc += (poly[j]!.x + poly[i]!.x) * (poly[j]!.y - poly[i]!.y)
  }
  return Math.abs(acc / 2)
}
