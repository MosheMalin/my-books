/**
 * Points and the grid, in ABSTRACT UNITS.
 *
 * Framework-free by rule (MAP_PLAN §5, P6.0 constraint 1): no React, no DOM,
 * no fetch. This module ports into `app/web` verbatim at P6.3.
 *
 * Nothing here knows about pixels. The plan is stored in an abstract unit
 * space and only the renderer maps units to screen — a canvas resize, a phone
 * rotation or a zoom must not be able to corrupt a plan (MAP_PLAN §3.4).
 */

export type Pt = { x: number; y: number }

/** One grid step. A room is a few dozen units across. */
export const GRID = 1
/** Every Nth grid line is drawn heavier. Cosmetic only. */
export const GRID_MAJOR = 5

export const pt = (x: number, y: number): Pt => ({ x, y })
export const sub = (a: Pt, b: Pt): Pt => ({ x: a.x - b.x, y: a.y - b.y })
export const dist = (a: Pt, b: Pt): number => Math.hypot(b.x - a.x, b.y - a.y)

/** Round to the grid. The one place a coordinate becomes canonical. */
export const snapToGrid = (v: number, grid = GRID): number =>
  Math.round(v / grid) * grid

export const snapPt = (p: Pt, grid = GRID): Pt => ({
  x: snapToGrid(p.x, grid),
  y: snapToGrid(p.y, grid),
})
