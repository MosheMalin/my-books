/**
 * Rectangles, and the snapping that makes them attach to each other.
 *
 * Everything on the plan is an axis-aligned rectangle on the grid — rooms AND
 * bookcases (owner, 2026-08-16: *"a rectangular draw… the free draw was too
 * free"*). That decision paid for itself immediately: an L-shaped room is two
 * rectangles attached, which is the same mechanism as two rooms attached, so
 * there is one snapping rule instead of a polygon editor.
 *
 * Pure. No React, no DOM.
 */

import type { Pt } from './geom'
import { snapToGrid } from './geom'

export type Rect = { x: number; y: number; w: number; h: number }

/** Which edge of a rectangle we mean. N is the smaller y. */
export type Side = 'N' | 'S' | 'E' | 'W'

export const OPPOSITE: Record<Side, Side> = { N: 'S', S: 'N', E: 'W', W: 'E' }

export const rectFrom = (a: Pt, b: Pt): Rect => ({
  x: Math.min(a.x, b.x),
  y: Math.min(a.y, b.y),
  w: Math.abs(b.x - a.x),
  h: Math.abs(b.y - a.y),
})

export const right = (r: Rect): number => r.x + r.w
export const bottom = (r: Rect): number => r.y + r.h
export const center = (r: Rect): Pt => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 })

export const contains = (r: Rect, p: Pt): boolean =>
  p.x >= r.x && p.x <= right(r) && p.y >= r.y && p.y <= bottom(r)

export const corners = (r: Rect): [Pt, Pt, Pt, Pt] => [
  { x: r.x, y: r.y },
  { x: right(r), y: r.y },
  { x: right(r), y: bottom(r) },
  { x: r.x, y: bottom(r) },
]

export const translate = (r: Rect, dx: number, dy: number): Rect => ({
  ...r,
  x: r.x + dx,
  y: r.y + dy,
})

/** The segment of one edge, in plan coordinates. */
export function edge(r: Rect, side: Side): { a: Pt; b: Pt } {
  switch (side) {
    case 'N':
      return { a: { x: r.x, y: r.y }, b: { x: right(r), y: r.y } }
    case 'S':
      return { a: { x: r.x, y: bottom(r) }, b: { x: right(r), y: bottom(r) } }
    case 'W':
      return { a: { x: r.x, y: bottom(r) }, b: { x: r.x, y: r.y } }
    case 'E':
      return { a: { x: right(r), y: r.y }, b: { x: right(r), y: bottom(r) } }
  }
}

/** Outward unit normal of a side. */
export function outward(side: Side): Pt {
  switch (side) {
    case 'N':
      return { x: 0, y: -1 }
    case 'S':
      return { x: 0, y: 1 }
    case 'W':
      return { x: -1, y: 0 }
    case 'E':
      return { x: 1, y: 0 }
  }
}

// --- snapping --------------------------------------------------------------

/**
 * Snap one coordinate to the nearest CANDIDATE if one is in reach, otherwise
 * to the grid.
 *
 * Candidates win over the grid on purpose: "flush against that wall" is a
 * physical fact the user is asserting, and rounding it to the nearest grid
 * line instead would leave a hairline gap that no amount of zooming closes.
 */
export function snapCoord(v: number, candidates: readonly number[], tol: number): number {
  let best: number | null = null
  let bestD = tol
  for (const c of candidates) {
    const d = Math.abs(c - v)
    if (d <= bestD) {
      best = c
      bestD = d
    }
  }
  return best ?? snapToGrid(v)
}

/** The x coordinates worth snapping to: every vertical edge of every target. */
export const xEdges = (targets: readonly Rect[]): number[] =>
  targets.flatMap((r) => [r.x, right(r)])

export const yEdges = (targets: readonly Rect[]): number[] =>
  targets.flatMap((r) => [r.y, bottom(r)])

/** Snap the free corner of a rectangle being DRAWN or RESIZED. */
export function snapPoint(p: Pt, targets: readonly Rect[], tol: number): Pt {
  return {
    x: snapCoord(p.x, xEdges(targets), tol),
    y: snapCoord(p.y, yEdges(targets), tol),
  }
}

/**
 * Snap a rectangle being MOVED, without changing its size.
 *
 * Both of its edges on an axis compete for the snap and the smaller correction
 * wins, so a room can attach by its left edge OR its right edge to whatever is
 * nearest — which is what "rooms should be able to get attached to each
 * other" means in practice. The whole rectangle then translates by that one
 * correction; snapping the edges independently would silently resize it.
 */
export function snapRect(r: Rect, targets: readonly Rect[], tol: number): Rect {
  const dx = bestShift([r.x, right(r)], xEdges(targets), tol)
  const dy = bestShift([r.y, bottom(r)], yEdges(targets), tol)
  return translate(r, dx, dy)
}

function bestShift(edges: number[], candidates: readonly number[], tol: number): number {
  let shift: number | null = null
  let bestD = tol
  for (const e of edges) {
    for (const c of candidates) {
      const d = Math.abs(c - e)
      if (d <= bestD) {
        bestD = d
        shift = c - e
      }
    }
  }
  if (shift !== null) return shift
  // No neighbour in reach: fall back to the grid, again choosing whichever
  // edge is closer to a grid line so the rectangle keeps its exact size.
  const first = edges[0] ?? 0
  return snapToGrid(first) - first
}

// --- resize handles --------------------------------------------------------

/** Which handle: -1 is the low edge, +1 the high edge, 0 the middle. */
export type Handle = { hx: -1 | 0 | 1; hy: -1 | 0 | 1 }

/**
 * The eight resize handles — minus the corners, when the rectangle is too thin
 * to hold them apart.
 *
 * A bookcase IS thin: one unit deep against a wall is the normal case, not the
 * edge case. At that size the four corners sit inside a fingertip of the edge
 * midpoints, and the corner wins — so dragging the right edge to make the case
 * LONGER instead collapsed its depth to zero. Corners are a luxury of large
 * rectangles; on a thin one the edges are what anybody is aiming at.
 */
export function handlePositions(r: Rect, minSide = 0): { h: Handle; at: Pt }[] {
  const thin = r.w < minSide * 2 || r.h < minSide * 2
  const xs = [r.x, r.x + r.w / 2, right(r)]
  const ys = [r.y, r.y + r.h / 2, bottom(r)]
  const out: { h: Handle; at: Pt }[] = []
  for (const hy of [-1, 0, 1] as const) {
    for (const hx of [-1, 0, 1] as const) {
      if (hx === 0 && hy === 0) continue
      if (thin && hx !== 0 && hy !== 0) continue
      out.push({ h: { hx, hy }, at: { x: xs[hx + 1]!, y: ys[hy + 1]! } })
    }
  }
  return out
}

/** The handle under a pointer — the NEAREST one, never merely the first in
 *  reach. With crowded handles "first" is an arbitrary answer that happens to
 *  be wrong about half the time. */
export function handleAt(r: Rect, p: Pt, tol: number, minSide = tol): Handle | null {
  let best: Handle | null = null
  let bestD = tol
  for (const { h, at } of handlePositions(r, minSide)) {
    const d = Math.hypot(at.x - p.x, at.y - p.y)
    if (d <= bestD) {
      best = h
      bestD = d
    }
  }
  return best
}

/** Rectangles overlap if they share interior area — touching is not overlap. */
export function overlaps(a: Rect, b: Rect): boolean {
  return a.x < right(b) && right(a) > b.x && a.y < bottom(b) && bottom(a) > b.y
}

/**
 * Which side of `r` lies flush against an edge of `host` (within `tol`).
 *
 * When a bookcase is pushed into a corner two sides are flush, so the side
 * along the case's LONGER dimension wins: a long thin case against a corner is
 * standing along the long wall, not the short one.
 */
export function flushSide(r: Rect, host: Rect, tol = 0.02): Side | null {
  const hits: Side[] = []
  if (Math.abs(r.y - host.y) <= tol) hits.push('N')
  if (Math.abs(bottom(r) - bottom(host)) <= tol) hits.push('S')
  if (Math.abs(r.x - host.x) <= tol) hits.push('W')
  if (Math.abs(right(r) - right(host)) <= tol) hits.push('E')
  if (hits.length === 0) return null
  const horizontal = r.w >= r.h
  const preferred = hits.filter((s) => (horizontal ? s === 'N' || s === 'S' : s === 'E' || s === 'W'))
  return (preferred[0] ?? hits[0]) ?? null
}
