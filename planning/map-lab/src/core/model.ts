/**
 * The plan model — framework-free, pure, and the part that ports verbatim.
 *
 * Two geometries, never one canvas (MAP_PLAN §3.2):
 *
 *   Plan       top-down, per Place: rooms and bookcases, both AXIS-ALIGNED
 *              RECTANGLES on the grid.
 *   Elevation  front-on, per Bookcase: SECTIONS stacked bottom to top, each
 *              divided into columns across x levels down.
 *
 * A length is not a column count. The rectangle says where the furniture
 * stands and how much wall it takes; the elevation says how it is divided.
 * Neither is derived from the other — the plan only DRAWS the declared depth,
 * it never infers it.
 */

import type { Pt } from './geom'
import { pt } from './geom'
import type { Rect, Side } from './rect'
import { MIN_SIZE, OPPOSITE, bottom, center, contains, flushSide, right } from './rect'

// --- shelves ---------------------------------------------------------------

/**
 * One cell of a section's elevation — and, in the product, one `Shelf` row.
 *
 * MAP_PLAN §3.1: a drawn slot IS a Shelf, created empty, carrying an address.
 * `photos` is the lab's stand-in for the captures that would hang off it, and
 * exists only so the elevation can show a half-catalogued case honestly.
 */
export type Shelf = {
  col: number
  level: number
  /** ITS OWN depth. Copied from the section default at creation — never read
   *  through to the parent afterwards (MAP_PLAN §3.3). */
  depth: number
  photos: number
}

/**
 * One built unit of a bookcase: a low base, or the taller case standing on it
 * (owner, 2026-08-16 — *"sometimes a bookcase is built of 2 bookcases one on
 * top the other"*).
 *
 * ⚠ **Called a SECTION, deliberately.** Not a "unit" — the plan's measurements
 * are already units. Not a "tier" — too close to `level`, which is the shelf
 * row inside a column. This project has been bitten by exactly this before
 * (depth ≠ row ≠ band), so the name is part of the design.
 *
 * A plain bookcase has ONE section, so the ordinary case costs nothing: the
 * editor hides the section header entirely until a second one exists.
 */
export type Section = {
  id: string
  /** One entry per column, holding that column's level count. The column count
   *  is this array's length; there is no second field to disagree. */
  columnLevels: number[]
  /** Applied WHEN A SHELF IS CREATED. Editing them does not reach back into
   *  existing shelves — that is an explicit action (MAP_PLAN §3.3). */
  defaultLevels: number
  defaultDepth: number
  shelves: Shelf[]
}

/**
 * A storey. Rooms belong to one; nothing else does.
 *
 * ⚠ **A floor is NOT part of a shelf's address** (owner, 2026-08-16: *"it can
 * be simply just another name for a room — no need to change the address
 * structure"*). It is a grouping over rooms so the MAP can show one storey at
 * a time, and that is all it is: two floors both start at 0,0, so drawing them
 * on one canvas puts the bedroom on top of the kitchen.
 */
export type Floor = {
  id: string
  name: string
}

export type Room = {
  id: string
  name: string
  rect: Rect
  floorId: string
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
  /** The room the case stands in. Null for a case attached to no room. */
  roomId: string | null
  /** Which storey it stands on. Kept in step with its room's floor whenever it
   *  attaches to one; carried on the case as well so an unattached bookcase is
   *  still somewhere rather than everywhere. */
  floorId: string
  /** **Bottom first.** Index 0 is what stands on the floor. The elevation
   *  renders them in reverse, because a screen draws downwards and furniture
   *  stacks upwards — see `sectionsTopDown`. */
  sections: Section[]
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
  floors: Floor[]
  rooms: Room[]
  cases: Bookcase[]
  underlay: Underlay | null
}

/** Every plan has at least one floor, so nothing has to handle "no floor". */
export const GROUND_FLOOR: Floor = { id: 'f1', name: 'Ground floor' }

export const emptyPlan = (): Plan => ({
  floors: [GROUND_FLOOR],
  rooms: [],
  cases: [],
  underlay: null,
})

export const roomsOn = (plan: Plan, floorId: string): Room[] =>
  plan.rooms.filter((r) => r.floorId === floorId)

export const casesOn = (plan: Plan, floorId: string): Bookcase[] =>
  plan.cases.filter((c) => c.floorId === floorId)

/** How much would be lost with this storey — what a delete has to be able to
 *  say before it refuses. */
export const floorContents = (plan: Plan, floorId: string): { rooms: number; cases: number } => ({
  rooms: roomsOn(plan, floorId).length,
  cases: casesOn(plan, floorId).length,
})

// --- constants -------------------------------------------------------------

export const DEFAULT_LEVELS = 5
export const DEFAULT_DEPTH = 1
/** Two, because most bookcases are (owner, 2026-08-16). One was a modelling
 *  minimum masquerading as a default. */
export const DEFAULT_COLUMNS = 2
export const MAX_DEPTH = 4

export function isTooSmall(r: Rect): boolean {
  return r.w < MIN_SIZE || r.h < MIN_SIZE
}

export const clampDepth = (d: number): number =>
  Math.max(1, Math.min(MAX_DEPTH, Math.round(d)))

/** Turn the case a quarter turn: N → E → S → W → N. */
export const TURN: Record<Side, Side> = { N: 'E', E: 'S', S: 'W', W: 'N' }

// --- sections --------------------------------------------------------------

export function newSection(id: string, columns = 1): Section {
  const base: Section = {
    id,
    columnLevels: [],
    defaultLevels: DEFAULT_LEVELS,
    defaultDepth: DEFAULT_DEPTH,
    shelves: [],
  }
  return withColumnCount(base, Math.max(1, columns))
}

/** Bottom-up index of a section, or -1. The panel numbers sections this way
 *  because that is how they are built: section 1 stands on the floor. */
export const sectionIndex = (bc: Bookcase, sectionId: string): number =>
  bc.sections.findIndex((s) => s.id === sectionId)

export const sectionById = (bc: Bookcase, sectionId: string): Section | null =>
  bc.sections.find((s) => s.id === sectionId) ?? null

/** Sections as the ELEVATION draws them: topmost first. */
export const sectionsTopDown = (bc: Bookcase): Section[] => bc.sections.slice().reverse()

/** A stable id, derived from the case's existing sections — no clock, no
 *  randomness, so the same edits always produce the same document. */
function nextSectionId(bc: Bookcase): string {
  const used = bc.sections
    .map((s) => Number(s.id.split(':s')[1]))
    .filter((n) => Number.isFinite(n))
  return `${bc.id}:s${Math.max(0, ...used) + 1}`
}

/**
 * Add a section. A new one copies the NEIGHBOURING section's shape — a hutch
 * usually has about as many columns as the base it stands on, and starting
 * from a blank 1×5 would mean re-entering what is already on screen.
 */
export function addSection(bc: Bookcase, where: 'top' | 'bottom'): Bookcase {
  const neighbour = where === 'top' ? bc.sections[bc.sections.length - 1] : bc.sections[0]
  const blank: Section = {
    id: nextSectionId(bc),
    columnLevels: [],
    defaultLevels: neighbour?.defaultLevels ?? DEFAULT_LEVELS,
    defaultDepth: neighbour?.defaultDepth ?? DEFAULT_DEPTH,
    shelves: [],
  }
  const made = withColumnCount(blank, neighbour ? columnCount(neighbour) : 1)
  return {
    ...bc,
    sections: where === 'top' ? bc.sections.concat(made) : [made, ...bc.sections],
  }
}

/** Remove a section — never the last one. A bookcase with no sections is not a
 *  simpler bookcase, it is an unaddressable one. */
export function removeSection(bc: Bookcase, sectionId: string): Bookcase {
  if (bc.sections.length <= 1) return bc
  return { ...bc, sections: bc.sections.filter((s) => s.id !== sectionId) }
}

export function mapSection(
  bc: Bookcase,
  sectionId: string,
  fn: (s: Section) => Section,
): Bookcase {
  return { ...bc, sections: bc.sections.map((s) => (s.id === sectionId ? fn(s) : s)) }
}

// --- section edits (pure, one section at a time) ---------------------------

export function columnCount(sec: Section): number {
  return sec.columnLevels.length
}

export function shelfAt(sec: Section, col: number, level: number): Shelf | null {
  return sec.shelves.find((s) => s.col === col && s.level === level) ?? null
}

/**
 * Add or remove trailing columns. New columns get the section's CURRENT
 * default level count and their shelves the current default depth — the
 * creation-time copy of §3.3.
 */
export function withColumnCount(sec: Section, count: number): Section {
  const n = Math.max(1, Math.round(count))
  if (n === sec.columnLevels.length) return sec
  if (n < sec.columnLevels.length) {
    return {
      ...sec,
      columnLevels: sec.columnLevels.slice(0, n),
      shelves: sec.shelves.filter((s) => s.col < n),
    }
  }
  const columnLevels = sec.columnLevels.slice()
  const shelves = sec.shelves.slice()
  for (let col = sec.columnLevels.length; col < n; col++) {
    columnLevels.push(sec.defaultLevels)
    for (let level = 0; level < sec.defaultLevels; level++) {
      shelves.push({ col, level, depth: sec.defaultDepth, photos: 0 })
    }
  }
  return { ...sec, columnLevels, shelves }
}

/** Change ONE column's level count. Growing creates shelves at the section's
 *  current default depth; shrinking drops the bottom ones. */
export function withColumnLevels(sec: Section, col: number, levels: number): Section {
  if (col < 0 || col >= sec.columnLevels.length) return sec
  const n = Math.max(1, Math.round(levels))
  const current = sec.columnLevels[col]!
  if (n === current) return sec
  const columnLevels = sec.columnLevels.slice()
  columnLevels[col] = n
  let shelves = sec.shelves.filter((s) => s.col !== col || s.level < n)
  if (n > current) {
    for (let level = current; level < n; level++) {
      shelves = shelves.concat({ col, level, depth: sec.defaultDepth, photos: 0 })
    }
  }
  return { ...sec, columnLevels, shelves }
}

/** How many shelves live in columns at or beyond `from` — what a "remove
 *  column" confirmation has to be able to say. */
export function shelvesInColumns(sec: Section, from: number): number {
  return sec.shelves.filter((s) => s.col >= from).length
}

/**
 * Set the section's default depth. **Existing shelves are untouched** — that
 * is the rule (MAP_PLAN §3.3), and the reason it is a rule: reading the parent
 * live would delete the location of every book standing at depth 2 the moment
 * someone edits the section to 1.
 */
export function withDefaultDepth(sec: Section, depth: number): Section {
  return { ...sec, defaultDepth: clampDepth(depth) }
}

export function withDefaultLevels(sec: Section, levels: number): Section {
  return { ...sec, defaultLevels: Math.max(1, Math.round(levels)) }
}

/** How many existing shelves would CHANGE if the default were applied — the
 *  number the confirmation shows. */
export function shelvesDifferingFromDefaultDepth(sec: Section): number {
  return sec.shelves.filter((s) => s.depth !== sec.defaultDepth).length
}

/**
 * The explicit, opt-in application of the default to existing shelves.
 *
 * In the product this must additionally refuse to take a shelf below its
 * deepest OCCUPIED row. The lab has no books, so it carries the signature and
 * the note rather than a fake occupancy check — the clamp belongs to P6.1,
 * where copies exist.
 */
export function applyDefaultDepth(sec: Section): Section {
  return { ...sec, shelves: sec.shelves.map((s) => ({ ...s, depth: sec.defaultDepth })) }
}

export function applyDefaultLevels(sec: Section): Section {
  let out = sec
  for (let col = 0; col < sec.columnLevels.length; col++) {
    out = withColumnLevels(out, col, sec.defaultLevels)
  }
  return out
}

export function withShelfDepth(
  sec: Section,
  col: number,
  level: number,
  depth: number,
): Section {
  const d = clampDepth(depth)
  return {
    ...sec,
    shelves: sec.shelves.map((s) =>
      s.col === col && s.level === level ? { ...s, depth: d } : s,
    ),
  }
}

export function withShelfPhotos(
  sec: Section,
  col: number,
  level: number,
  photos: number,
): Section {
  const n = Math.max(0, Math.round(photos))
  return {
    ...sec,
    shelves: sec.shelves.map((s) =>
      s.col === col && s.level === level ? { ...s, photos: n } : s,
    ),
  }
}

// --- bookcase aggregates ---------------------------------------------------

export function newBookcase(
  id: string,
  name: string,
  rect: Rect,
  front: Side,
  roomId: string | null,
  floorId: string,
  columns = DEFAULT_COLUMNS,
): Bookcase {
  return {
    id,
    name,
    rect,
    front,
    roomId,
    floorId,
    sections: [newSection(`${id}:s1`, columns)],
  }
}

export const allShelves = (bc: Bookcase): Shelf[] => bc.sections.flatMap((s) => s.shelves)

/**
 * Resize a bookcase, turning it when the resize changed which side is LONGER
 * (owner, 2026-08-16: *"if the new width is larger than the new length, change
 * the columns orientation"*).
 *
 * Columns divide across the front, and the front is the long face — that is
 * what a bookcase IS. So making a tall narrow case wide has to move the
 * columns with it, or the elevation stops describing the furniture. It fires
 * only on the flip, so a one-unit nudge never undoes a deliberate *Turn*, and
 * a case flush against a wall still faces into the room: `frontFor` asks the
 * wall first.
 */
export function withRect(bc: Bookcase, rect: Rect, room: Room | null): Bookcase {
  const flipped = bc.rect.w >= bc.rect.h !== rect.w >= rect.h
  return { ...bc, rect, front: flipped ? frontFor(rect, room) : bc.front }
}

export function maxDepth(bc: Bookcase): number {
  return bc.sections.reduce(
    (m, sec) => sec.shelves.reduce((n, s) => Math.max(n, s.depth), Math.max(m, sec.defaultDepth)),
    1,
  )
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

/**
 * Re-derive which room a bookcase belongs to, and which way it faces.
 *
 * ⚠ Containment can only REASSIGN, never orphan: a case dragged out of every
 * room keeps the room it had. That is deliberate — "attach bookcases to a room
 * so they move together" is the point, and a case nudged half a unit past its
 * wall silently losing its room is exactly the bug this prevents. Detaching is
 * done on purpose, in the panel.
 */
export function reattach(bc: Bookcase, plan: Plan): Bookcase {
  const room = roomFor(plan, bc.rect, bc.floorId)
  if (!room) return bc
  return correctFront({ ...bc, roomId: room.id, floorId: room.floorId }, room)
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

/** Rooms are only ever found on ONE storey: the kitchen is not under your feet
 *  when you are drawing the bedroom. */
export function roomAt(plan: Plan, p: Pt, floorId: string): Room | null {
  const rooms = roomsOn(plan, floorId)
  for (let i = rooms.length - 1; i >= 0; i--) {
    const r = rooms[i]!
    if (contains(r.rect, p)) return r
  }
  return null
}

export function roomFor(plan: Plan, rect: Rect, floorId: string): Room | null {
  return roomAt(plan, center(rect), floorId)
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

/**
 * Column boundaries, drawn perpendicular to the front.
 *
 * ⚠ From the BOTTOM section only. Once sections can divide differently there
 * is no single honest answer, and the bottom one is the least arbitrary: the
 * plan rectangle is a footprint, and the footprint is what stands on the
 * floor. A drawing aid either way — the plan never derives a column count from
 * a length.
 */
export function columnDividers(bc: Bookcase): { a: Pt; b: Pt }[] {
  const cols = bc.sections[0] ? columnCount(bc.sections[0]) : 0
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
  return plan.cases.reduce((n, bc) => n + allShelves(bc).length, 0)
}

export function planBounds(plan: Plan, floorId?: string): { min: Pt; max: Pt } {
  const rooms = floorId ? roomsOn(plan, floorId) : plan.rooms
  const cases = floorId ? casesOn(plan, floorId) : plan.cases
  const rects = [...rooms.map((r) => r.rect), ...cases.map((c) => c.rect)]
  if (rects.length === 0) return { min: pt(0, 0), max: pt(0, 0) }
  return {
    min: pt(Math.min(...rects.map((r) => r.x)), Math.min(...rects.map((r) => r.y))),
    max: pt(Math.max(...rects.map(right)), Math.max(...rects.map(bottom))),
  }
}

/**
 * Where each storey sits when they are all shown at once.
 *
 * Floors are laid out LEFT TO RIGHT at their natural size, each shifted so its
 * own left edge starts where the previous one ended. They cannot simply be
 * drawn together — every storey starts at 0,0, so the bedroom would land on
 * the kitchen — and stacking them vertically would fight the fact that a plan
 * is usually wider than it is tall.
 */
export function overviewLayout(
  plan: Plan,
  gap = 6,
): { floor: Floor; dx: number; dy: number; band: number; bandStart: number; width: number }[] {
  // EQUAL bands, one per storey, STACKED — three floors make three rows
  // (owner, 2026-08-16). Rows rather than columns because that is how a
  // building is: the storey above is above. Equal rather than natural size
  // because comparing them is what the view is for, and a small storey packed
  // beside a large one just looks squeezed.
  const bounds = plan.floors.map((f) => planBounds(plan, f.id))
  const width = Math.max(gap, ...bounds.map((b) => b.max.x - b.min.x))
  const band = Math.max(gap, ...bounds.map((b) => b.max.y - b.min.y))
  return plan.floors.map((floor, i) => {
    const b = bounds[i]!
    const bandStart = i * (band + gap)
    // centred in its band both ways, so a small storey sits under its own
    // label rather than hard against a divider
    const dx = (width - (b.max.x - b.min.x)) / 2 - b.min.x
    const dy = bandStart + (band - (b.max.y - b.min.y)) / 2 - b.min.y
    return { floor, dx, dy, band, bandStart, width }
  })
}

/** The whole overview's extent, for *Show all* while it is on screen. */
export function overviewBounds(plan: Plan, gap = 6): { min: Pt; max: Pt } {
  const cells = overviewLayout(plan, gap)
  const last = cells[cells.length - 1]
  if (!last) return { min: pt(0, 0), max: pt(0, 0) }
  return { min: pt(0, -4), max: pt(last.width, last.bandStart + last.band) }
}

export function casesInRoom(plan: Plan, roomId: string): Bookcase[] {
  return plan.cases.filter((c) => c.roomId === roomId)
}
