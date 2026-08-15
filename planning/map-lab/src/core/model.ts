/**
 * The plan model — framework-free, pure, and the part that ports verbatim.
 *
 * Two geometries, never one canvas (MAP_PLAN §3.2):
 *
 *   Plan       top-down, per Place: rooms and bookcases, both AXIS-ALIGNED
 *              RECTANGLES on the grid.
 *   Elevation  front-on, per Bookcase: columns across x levels down.
 *
 * A length is not a column count. The rectangle says where the furniture
 * stands and how much wall it takes; the elevation says how it is divided.
 * Neither is derived from the other — the plan only DRAWS the declared depth,
 * it never infers it.
 */

import type { Pt } from './geom'
import { pt } from './geom'
import type { Rect, Side } from './rect'
import { OPPOSITE, bottom, center, contains, flushSide, right } from './rect'

// --- shelves ---------------------------------------------------------------

/**
 * One cell of a bookcase's elevation — and, in the product, one `Shelf` row.
 *
 * MAP_PLAN §3.1: a drawn slot IS a Shelf, created empty, carrying an address.
 * `photos` is the lab's stand-in for the captures that would hang off it, and
 * exists only so the elevation can show a half-catalogued case honestly.
 */
export type Shelf = {
  col: number
  level: number
  /** ITS OWN depth. Copied from the case default at creation — never read
   *  through to the parent afterwards (MAP_PLAN §3.3). */
  depth: number
  photos: number
}

export type Room = {
  id: string
  name: string
  rect: Rect
}

export type Bookcase = {
  id: string
  name: string
  /** Footprint on the plan. The user draws it and drags its size; nothing is
   *  computed from it. */
  rect: Rect
  /** Which edge the books face out of. Derived when the case is drawn flush
   *  against a wall, and turnable by hand afterwards. */
  front: Side
  /** The room the case stands in, by containment of its centre. Null for a
   *  case standing outside every room — legal, and drawn as such. */
  roomId: string | null
  /** Defaults applied WHEN A SHELF IS CREATED. Editing them does not reach
   *  back into existing shelves — that is an explicit action. */
  defaultLevels: number
  defaultDepth: number
  /** One entry per column, holding that column's level count. The column
   *  count is this array's length; there is no second field to disagree. */
  columnLevels: number[]
  shelves: Shelf[]
}

export type Underlay = {
  /** Object URL or data URL. Not persisted across reloads by design: an
   *  underlay is scaffolding, not data. */
  src: string
  x: number
  y: number
  /** How many plan units WIDE the image is drawn. Height follows `aspect`, so
   *  a traced floor plan cannot be silently distorted. */
  scale: number
  aspect: number
  opacity: number
}

export type Plan = {
  rooms: Room[]
  cases: Bookcase[]
  underlay: Underlay | null
}

export const emptyPlan = (): Plan => ({ rooms: [], cases: [], underlay: null })

// --- bookcases -------------------------------------------------------------

export const DEFAULT_LEVELS = 5
export const DEFAULT_DEPTH = 1
export const MAX_DEPTH = 4
/** Below this a drag is a mis-tap, not a rectangle. */
export const MIN_SIZE = 1

export function isTooSmall(r: Rect): boolean {
  return r.w < MIN_SIZE || r.h < MIN_SIZE
}

/**
 * Which way the books face, for a case drawn inside a room.
 *
 * Flush against the north wall means facing south. That is the only rule, and
 * it is right often enough that *Turn* is a correction rather than a step.
 */
export function frontFor(rect: Rect, room: Room | null): Side {
  const flush = room ? flushSide(rect, room.rect) : null
  if (flush) return OPPOSITE[flush]
  return rect.w >= rect.h ? 'S' : 'E'
}

/**
 * Fix a front that is obviously wrong, and only then.
 *
 * A case standing flush against a wall with its books facing INTO that wall is
 * never what anyone meant, so moving it there corrects it. Anything else is
 * left alone — re-deriving the front on every move would silently undo the
 * *Turn* button, and a tool that fights a deliberate choice is worse than one
 * that occasionally needs a second tap.
 */
export function correctFront(bc: Bookcase, room: Room | null): Bookcase {
  if (!room) return bc
  const flush = flushSide(bc.rect, room.rect)
  return flush === bc.front ? { ...bc, front: OPPOSITE[flush] } : bc
}

export function roomAt(plan: Plan, p: Pt): Room | null {
  for (let i = plan.rooms.length - 1; i >= 0; i--) {
    const r = plan.rooms[i]!
    if (contains(r.rect, p)) return r
  }
  return null
}

export function roomFor(plan: Plan, rect: Rect): Room | null {
  return roomAt(plan, center(rect))
}

/** True when the front edge runs left-right, so columns divide along x. */
export const frontIsHorizontal = (bc: Bookcase): boolean =>
  bc.front === 'N' || bc.front === 'S'

/** The extent along the front — how much wall the case occupies. */
export const caseLength = (bc: Bookcase): number =>
  frontIsHorizontal(bc) ? bc.rect.w : bc.rect.h

/** The extent front-to-back, as DRAWN. Not the declared depth. */
export const caseThickness = (bc: Bookcase): number =>
  frontIsHorizontal(bc) ? bc.rect.h : bc.rect.w

export function maxDepth(bc: Bookcase): number {
  return bc.shelves.reduce((m, s) => Math.max(m, s.depth), bc.defaultDepth)
}

export function columnCount(bc: Bookcase): number {
  return bc.columnLevels.length
}

export function shelfAt(bc: Bookcase, col: number, level: number): Shelf | null {
  return bc.shelves.find((s) => s.col === col && s.level === level) ?? null
}

export function newBookcase(
  id: string,
  name: string,
  rect: Rect,
  front: Side,
  roomId: string | null,
  columns = 1,
): Bookcase {
  const base: Bookcase = {
    id,
    name,
    rect,
    front,
    roomId,
    defaultLevels: DEFAULT_LEVELS,
    defaultDepth: DEFAULT_DEPTH,
    columnLevels: [],
    shelves: [],
  }
  return withColumnCount(base, Math.max(1, columns))
}

/**
 * Add or remove trailing columns. New columns get the case's CURRENT default
 * level count and their shelves get the current default depth — the creation
 * -time copy of §3.3. Removing a column drops its shelves; the caller is
 * expected to have said how many (`shelvesInColumns`).
 */
export function withColumnCount(bc: Bookcase, count: number): Bookcase {
  const n = Math.max(1, Math.round(count))
  if (n === bc.columnLevels.length) return bc
  if (n < bc.columnLevels.length) {
    return {
      ...bc,
      columnLevels: bc.columnLevels.slice(0, n),
      shelves: bc.shelves.filter((s) => s.col < n),
    }
  }
  const columnLevels = bc.columnLevels.slice()
  const shelves = bc.shelves.slice()
  for (let col = bc.columnLevels.length; col < n; col++) {
    columnLevels.push(bc.defaultLevels)
    for (let level = 0; level < bc.defaultLevels; level++) {
      shelves.push({ col, level, depth: bc.defaultDepth, photos: 0 })
    }
  }
  return { ...bc, columnLevels, shelves }
}

/** Change ONE column's level count. Growing creates shelves at the case's
 *  current default depth; shrinking drops the bottom ones. */
export function withColumnLevels(bc: Bookcase, col: number, levels: number): Bookcase {
  if (col < 0 || col >= bc.columnLevels.length) return bc
  const n = Math.max(1, Math.round(levels))
  const current = bc.columnLevels[col]!
  if (n === current) return bc
  const columnLevels = bc.columnLevels.slice()
  columnLevels[col] = n
  let shelves = bc.shelves.filter((s) => s.col !== col || s.level < n)
  if (n > current) {
    for (let level = current; level < n; level++) {
      shelves = shelves.concat({ col, level, depth: bc.defaultDepth, photos: 0 })
    }
  }
  return { ...bc, columnLevels, shelves }
}

/** How many shelves live in columns at or beyond `from` — what a "remove
 *  column" confirmation has to be able to say. */
export function shelvesInColumns(bc: Bookcase, from: number): number {
  return bc.shelves.filter((s) => s.col >= from).length
}

/**
 * Set the case's default depth. **Existing shelves are untouched** — that is
 * the rule (MAP_PLAN §3.3), and the reason it is a rule: reading the parent
 * live would delete the location of every book standing at depth 2 the moment
 * someone edits the case to 1.
 */
export function withDefaultDepth(bc: Bookcase, depth: number): Bookcase {
  return { ...bc, defaultDepth: clampDepth(depth) }
}

export function withDefaultLevels(bc: Bookcase, levels: number): Bookcase {
  return { ...bc, defaultLevels: Math.max(1, Math.round(levels)) }
}

/** How many existing shelves would CHANGE if the default were applied — the
 *  number the confirmation shows. */
export function shelvesDifferingFromDefaultDepth(bc: Bookcase): number {
  return bc.shelves.filter((s) => s.depth !== bc.defaultDepth).length
}

/**
 * The explicit, opt-in application of the default to existing shelves.
 *
 * In the product this must additionally refuse to take a shelf below its
 * deepest OCCUPIED row. The lab has no books, so it carries the signature and
 * the note rather than a fake occupancy check — the clamp belongs to P6.1,
 * where copies exist.
 */
export function applyDefaultDepth(bc: Bookcase): Bookcase {
  return { ...bc, shelves: bc.shelves.map((s) => ({ ...s, depth: bc.defaultDepth })) }
}

export function applyDefaultLevels(bc: Bookcase): Bookcase {
  let out = bc
  for (let col = 0; col < bc.columnLevels.length; col++) {
    out = withColumnLevels(out, col, bc.defaultLevels)
  }
  return out
}

export function withShelfDepth(
  bc: Bookcase,
  col: number,
  level: number,
  depth: number,
): Bookcase {
  const d = clampDepth(depth)
  return {
    ...bc,
    shelves: bc.shelves.map((s) =>
      s.col === col && s.level === level ? { ...s, depth: d } : s,
    ),
  }
}

export const clampDepth = (d: number): number =>
  Math.max(1, Math.min(MAX_DEPTH, Math.round(d)))

/** Turn the case a quarter turn: N → E → S → W → N. */
export const TURN: Record<Side, Side> = { N: 'E', E: 'S', S: 'W', W: 'N' }

// --- drawing aids ----------------------------------------------------------

/** The front edge as a segment — the face the books look out of. */
export function frontEdge(bc: Bookcase): { a: Pt; b: Pt } {
  const r = bc.rect
  switch (bc.front) {
    case 'N':
      return { a: pt(r.x, r.y), b: pt(right(r), r.y) }
    case 'S':
      return { a: pt(r.x, bottom(r)), b: pt(right(r), bottom(r)) }
    case 'W':
      return { a: pt(r.x, r.y), b: pt(r.x, bottom(r)) }
    case 'E':
      return { a: pt(right(r), r.y), b: pt(right(r), bottom(r)) }
  }
}

/** Column boundaries, drawn perpendicular to the front. A drawing aid only —
 *  the plan never derives a column count from a length. */
export function columnDividers(bc: Bookcase): { a: Pt; b: Pt }[] {
  const cols = columnCount(bc)
  if (cols < 2) return []
  const r = bc.rect
  const out: { a: Pt; b: Pt }[] = []
  for (let i = 1; i < cols; i++) {
    const f = i / cols
    if (frontIsHorizontal(bc)) {
      const x = r.x + r.w * f
      out.push({ a: pt(x, r.y), b: pt(x, bottom(r)) })
    } else {
      const y = r.y + r.h * f
      out.push({ a: pt(r.x, y), b: pt(right(r), y) })
    }
  }
  return out
}

/** One line per extra declared depth row, parallel to the front. This RENDERS
 *  the declared depth; it does not derive it from the drawn thickness. */
export function depthLines(bc: Bookcase): { a: Pt; b: Pt }[] {
  const d = maxDepth(bc)
  if (d < 2) return []
  const r = bc.rect
  const out: { a: Pt; b: Pt }[] = []
  for (let i = 1; i < d; i++) {
    const f = i / d
    switch (bc.front) {
      case 'N':
        out.push({ a: pt(r.x, r.y + r.h * f), b: pt(right(r), r.y + r.h * f) })
        break
      case 'S':
        out.push({ a: pt(r.x, bottom(r) - r.h * f), b: pt(right(r), bottom(r) - r.h * f) })
        break
      case 'W':
        out.push({ a: pt(r.x + r.w * f, r.y), b: pt(r.x + r.w * f, bottom(r)) })
        break
      case 'E':
        out.push({ a: pt(right(r) - r.w * f, r.y), b: pt(right(r) - r.w * f, bottom(r)) })
        break
    }
  }
  return out
}

// --- whole-plan queries ----------------------------------------------------

export function shelfCount(plan: Plan): number {
  return plan.cases.reduce((n, bc) => n + bc.shelves.length, 0)
}

export function planBounds(plan: Plan): { min: Pt; max: Pt } {
  const rects = [...plan.rooms.map((r) => r.rect), ...plan.cases.map((c) => c.rect)]
  if (rects.length === 0) return { min: pt(0, 0), max: pt(0, 0) }
  return {
    min: pt(
      Math.min(...rects.map((r) => r.x)),
      Math.min(...rects.map((r) => r.y)),
    ),
    max: pt(Math.max(...rects.map(right)), Math.max(...rects.map(bottom))),
  }
}

export function casesInRoom(plan: Plan, roomId: string): Bookcase[] {
  return plan.cases.filter((c) => c.roomId === roomId)
}
