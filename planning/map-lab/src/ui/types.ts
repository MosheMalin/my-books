import type { Bookcase, Plan, Room } from '../core/model'

/**
 * ⚠ There is no `Mode` any more. The freehand/straighten model (VISION §7
 * approach A, "S") was built, drawn on, and REJECTED by the owner on
 * 2026-08-16: *"the free draw was too free"*. Everything is a rectangle on the
 * grid now — see MAP_PLAN §4.
 */
export type Tool = 'select' | 'room' | 'case' | 'pan'

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
export type Selection = {
  rooms: string[]
  cases: string[]
  shelf: { caseId: string; col: number; level: number } | null
}

export const EMPTY: Selection = { rooms: [], cases: [], shelf: null }

export const selectRoom = (id: string): Selection => ({ rooms: [id], cases: [], shelf: null })
export const selectCase = (id: string): Selection => ({ rooms: [], cases: [id], shelf: null })

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
  return { ...s, [key]: next, shelf: null }
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
