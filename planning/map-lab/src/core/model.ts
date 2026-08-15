/**
 * The plan model — framework-free, pure, and the part that ports verbatim.
 *
 * Two geometries, never one canvas (MAP_PLAN §3.2):
 *
 *   Plan       top-down, per Place: rooms as polygons, bookcases as a front
 *              baseline standing on (or off) a wall.
 *   Elevation  front-on, per Bookcase: columns across x levels down.
 *
 * A length is not a column count. The two are linked only for DRAWING — a
 * deeper case is drawn thicker — never for deriving one from the other.
 */

import type { Pt } from './geom'
import { add, bbox, dist, mul, normal, pt, sub, unit } from './geom'

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

export type Bookcase = {
  id: string
  name: string
  /** The front baseline, in plan units. Length is relative — never cm. */
  a: Pt
  b: Pt
  /** Which side of a→b the case body occupies. The user flips it; we do not
   *  assert a handedness they cannot verify. */
  side: 1 | -1
  /** Set when the case is snapped onto a wall; null for an island. */
  attach: { roomId: string; wall: number } | null
  /** Defaults applied WHEN A SHELF IS CREATED. Editing them does not reach
   *  back into existing shelves — that is an explicit action. */
  defaultLevels: number
  defaultDepth: number
  /** One entry per column, holding that column's level count. The column
   *  count is this array's length; there is no second field to disagree. */
  columnLevels: number[]
  shelves: Shelf[]
}

export type Room = {
  id: string
  name: string
  /** Closed polygon. Walls are its edges — see `wallsOf`. */
  points: Pt[]
}

export type Underlay = {
  /** Object URL or data URL. Not persisted across reloads by design: an
   *  underlay is scaffolding, not data. */
  src: string
  /** Top-left corner, in plan units. */
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

// --- rooms -----------------------------------------------------------------

export type Wall = { index: number; a: Pt; b: Pt }

/** A room's walls, in polygon order. Index is stable for `Bookcase.attach`
 *  only while the polygon's point count is unchanged — the editor re-attaches
 *  on reshape rather than pretending otherwise. */
export function wallsOf(room: Room): Wall[] {
  const out: Wall[] = []
  const n = room.points.length
  for (let i = 0; i < n; i++) {
    out.push({ index: i, a: room.points[i]!, b: room.points[(i + 1) % n]! })
  }
  return out
}

/** The rectangle two dragged corners describe, as a 4-point polygon. */
export function rectPoints(from: Pt, to: Pt): Pt[] {
  const x0 = Math.min(from.x, to.x)
  const x1 = Math.max(from.x, to.x)
  const y0 = Math.min(from.y, to.y)
  const y1 = Math.max(from.y, to.y)
  return [pt(x0, y0), pt(x1, y0), pt(x1, y1), pt(x0, y1)]
}

// --- bookcases -------------------------------------------------------------

export const DEFAULT_LEVELS = 5
export const DEFAULT_DEPTH = 1
export const MAX_DEPTH = 4

/** Plan thickness for drawing, in units. A 2-deep case IS visibly deeper than
 *  a 1-deep one; that is the only coupling between the two geometries, and it
 *  runs one way (MAP_PLAN §3.2). */
export function caseThickness(bc: Bookcase): number {
  return 0.8 + 0.5 * (maxDepth(bc) - 1)
}

export function maxDepth(bc: Bookcase): number {
  return bc.shelves.reduce((m, s) => Math.max(m, s.depth), bc.defaultDepth)
}

export function caseLength(bc: Bookcase): number {
  return dist(bc.a, bc.b)
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
  a: Pt,
  b: Pt,
  side: 1 | -1,
  attach: Bookcase['attach'],
  columns = 1,
): Bookcase {
  const base: Bookcase = {
    id,
    name,
    a,
    b,
    side,
    attach,
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

// --- the case's footprint, for drawing and for hit-testing -----------------

/** The four corners of the case's footprint: the front baseline a→b, pushed
 *  back by its thickness on `side`. Front face is always a→b. */
export function casePolygon(bc: Bookcase): [Pt, Pt, Pt, Pt] {
  const n = mul(normal(bc.a, bc.b), bc.side * caseThickness(bc))
  return [bc.a, bc.b, add(bc.b, n), add(bc.a, n)]
}

/** The internal column boundaries, as segments across the footprint. Purely
 *  a drawing aid — the plan never derives a column count from a length. */
export function columnDividers(bc: Bookcase): { a: Pt; b: Pt }[] {
  const cols = columnCount(bc)
  if (cols < 2) return []
  const dir = unit(sub(bc.b, bc.a))
  const step = caseLength(bc) / cols
  const n = mul(normal(bc.a, bc.b), bc.side * caseThickness(bc))
  const out: { a: Pt; b: Pt }[] = []
  for (let i = 1; i < cols; i++) {
    const base = add(bc.a, mul(dir, step * i))
    out.push({ a: base, b: add(base, n) })
  }
  return out
}

export function caseMidpoint(bc: Bookcase): Pt {
  return pt((bc.a.x + bc.b.x) / 2, (bc.a.y + bc.b.y) / 2)
}

// --- whole-plan queries ----------------------------------------------------

export function shelfCount(plan: Plan): number {
  return plan.cases.reduce((n, bc) => n + bc.shelves.length, 0)
}

export function planBounds(plan: Plan): { min: Pt; max: Pt } {
  const points: Pt[] = []
  for (const r of plan.rooms) points.push(...r.points)
  for (const c of plan.cases) points.push(c.a, c.b)
  return bbox(points)
}

export function casesInRoom(plan: Plan, roomId: string): Bookcase[] {
  return plan.cases.filter((c) => c.attach?.roomId === roomId)
}
