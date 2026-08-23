import type { Bookcase, Plan, Room } from '../core/model'

/**
 * ⚠ There is no `Mode` any more. The freehand/straighten model (VISION §7
 * approach A, "S") was built, drawn on, and REJECTED by the owner on
 * 2026-08-16: *"the free draw was too free"*. Everything is a rectangle on the
 * grid now — see MAP_PLAN §4.
 */
/**
 * `auto` is the arrow, and it decides what a drag means from WHERE it starts
 * (owner, 2026-08-16 — *"touching the border switches to move… touching inside
 * the room switches to draw bookcase… more fluent"*):
 *
 *   over an existing room or bookcase   → select, move, resize
 *   on a room's BORDER                  → move that room
 *   inside a room                       → draw a bookcase
 *   outside every room                  → draw a room
 *   Ctrl/Shift + drag on empty          → select several
 *
 * ⚠ Existing objects always win. A bookcase stands ON the wall, so "the border
 * means move the room" and "there is a bookcase here" collide constantly, and
 * the furniture has to be the answer. `room` and `case` remain as explicit
 * tools for when the guess is not what you want — a small room is mostly
 * border once the zone is fingertip-sized.
 */
export type Tool = 'auto' | 'room' | 'case' | 'pan'

export type Theme = 'dark' | 'light'

/**
 * A SET of selected things, not one thing (owner, 2026-08-16: *"allow multi
 * select… and then delete multiple items"*).
 *
 * Rooms and cases are held in separate lists rather than one list of tagged
 * ids: every consumer already knows which of the two it wants, and a single
 * list would make each of them filter and re-narrow. `shelf` is the cell
 * selected INSIDE a bookcase — it is not a plan object, it never joins a
 * marquee, and it never gets deleted by the Delete key.
 */
/** One cell of one section's face. 0-based here, like every index in the
 *  document; the wire is 1-based (see `sync.ts`'s ⚠). */
export type Cell = { caseId: string; sectionId: string; col: number; level: number }

export type Selection = {
  rooms: string[]
  cases: string[]
  /** The cells selected INSIDE a bookcase. Their address is (section, column,
   *  level) — a case may be built of a base and a taller unit standing on it,
   *  and those divide differently.
   *
   *  ⚠ A LIST since P6.3.2b, and for the owner's reason: *"I want to be able
   *  to mark several cells and click delete"* — a television is a rectangle
   *  of cells, not one. Panels that edit a single shelf ask `onlyCell`, the
   *  way panels that edit one object already ask `only`. It still never joins
   *  a marquee and is still never deleted by the Delete key: that key means
   *  furniture, and a cell is not furniture. */
  cells: Cell[]
}

export const EMPTY: Selection = { rooms: [], cases: [], cells: [] }

export const selectRoom = (id: string): Selection => ({ rooms: [id], cases: [], cells: [] })
export const selectCase = (id: string): Selection => ({ rooms: [], cases: [id], cells: [] })

export const count = (s: Selection): number => s.rooms.length + s.cases.length

export const hasRoom = (s: Selection, id: string): boolean => s.rooms.includes(id)
export const hasCase = (s: Selection, id: string): boolean => s.cases.includes(id)

/** The single selected thing, or null when zero or several are selected. Panels
 *  that edit one object ask for this rather than reaching into the arrays. */
export function only(s: Selection, plan: Plan): Room | Bookcase | null {
  if (count(s) !== 1) return null
  const roomId = s.rooms[0]
  if (roomId) return plan.rooms.find((r) => r.id === roomId) ?? null
  const caseId = s.cases[0]
  return plan.cases.find((c) => c.id === caseId) ?? null
}

/** Ctrl-click semantics: in the set → out of it, and vice versa. */
export function toggle(s: Selection, kind: 'room' | 'case', id: string): Selection {
  const key = kind === 'room' ? 'rooms' : 'cases'
  const list = s[key]
  const next = list.includes(id) ? list.filter((x) => x !== id) : list.concat(id)
  return { ...s, [key]: next, cells: [] }
}

const sameCell = (a: Cell, b: Cell): boolean =>
  a.sectionId === b.sectionId && a.col === b.col && a.level === b.level

/** The single selected cell, or null when zero or several are. The shelf
 *  panel edits ONE shelf's depth, so it asks this rather than reaching into
 *  the list — `only`'s rule, one level down. */
export function onlyCell(s: Selection): Cell | null {
  return s.cells.length === 1 ? (s.cells[0] ?? null) : null
}

export const hasCell = (s: Selection, cell: Cell): boolean =>
  s.cells.some((c) => sameCell(c, cell))

/**
 * Mark a cell, or add it to the marked set.
 *
 * ⚠ Cells of ONE bookcase, always: `caseId` is what the elevation is showing,
 * and a set spanning two cases could be deleted by one gesture while only one
 * of them is on screen. Marking a cell of another case starts a new set.
 */
export function markCell(s: Selection, cell: Cell, add: boolean): Selection {
  const mine = s.cells.filter((c) => c.caseId === cell.caseId)
  if (!add) return { rooms: [], cases: s.cases, cells: [cell] }
  const next = mine.some((c) => sameCell(c, cell))
    ? mine.filter((c) => !sameCell(c, cell))
    : mine.concat(cell)
  return { rooms: [], cases: s.cases, cells: next }
}

/**
 * The document. `seq` rides with the plan so ids are a pure function of the
 * document's history rather than of the clock — an imported plan continues
 * numbering without colliding, and nothing here calls Math.random.
 */
export type Doc = { plan: Plan; seq: number }

/** What Ctrl+C put aside. Plain objects, cloned at copy time, so a later edit
 *  to the original cannot reach into the clipboard. */
export type Clipboard = { rooms: Room[]; cases: Bookcase[] } | null
