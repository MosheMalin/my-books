/**
 * The ceilings the SERVER enforces, so the editor never offers a gesture it
 * will refuse.
 *
 * MAP_PLAN's own note on what P6.2 landed: *"the editor must not offer a
 * gesture that asks for more than the ceiling, or the owner meets a 409"*. The
 * limits are a resource guard with a measured reason — a 110-byte request
 * asking for 40 columns of 40 wrote 1600 rows in 16.5 seconds — not a
 * modelling opinion, so the client does not re-derive them, it mirrors them.
 *
 * ⚠ **Two copies of a number, pinned by a test.** `tests/test_api.py` reads
 * this file and asserts it against `app/domain/place.py`, the same way
 * `ClaimRow.tsx`'s `MAX_SCORE` must track `match.py`. Changing one side alone
 * fails the Python ring rather than shipping an editor that promises what the
 * server will not do.
 */

import type { Bookcase, GapCell, Section } from './core/model'
import { allShelves, shelfAt } from './core/model'

/** The most slots one bookcase may hold, across every section. */
export const MAX_SLOTS_PER_BOOKCASE = 400
/** Sections stack bottom to top; more than a handful is not furniture. */
export const MAX_SECTIONS_PER_BOOKCASE = 8
/**
 * The per-field ceilings on the wire (`SectionPatch`, `SectionCreate`).
 *
 * ⚠ A number box does not enforce its own `max`: typing 41 into *new levels*
 * sent `{"default_levels": 41}` and came back 422 — and a 422's `detail` is a
 * LIST, so the banner rendered `[object Object]` until `client.ts` learned to
 * read one. Both halves were measured; this is the half that stops the request
 * being made at all.
 */
export const MAX_LEVELS_PER_COLUMN = 40
export const MAX_COLUMNS_PER_SECTION = 40

/** A typed level count, kept inside what the server accepts. An empty box
 *  reads as 0 and means one, which is the existing behaviour of every number
 *  field in this editor. */
export const clampLevels = (n: number): number =>
  Math.max(1, Math.min(MAX_LEVELS_PER_COLUMN, Math.round(n) || 1))

export const clampColumns = (n: number): number =>
  Math.max(1, Math.min(MAX_COLUMNS_PER_SECTION, Math.round(n) || 1))

/** Which ceiling an edit would cross, with the number that crosses it — or
 *  null, which is the answer for every gesture anybody actually makes. */
export type OverCeiling =
  | { what: 'slots'; asked: number }
  | { what: 'sections' }
  | null

/**
 * ⚠ Only a gesture that GROWS is refused, and that clause is load-bearing: a
 * case that is somehow already over a ceiling — a plan imported before the
 * ceiling existed, a document restored by undo — must still be shrinkable, or
 * the guard becomes the trap. Shrinking one crossed ceiling while another is
 * still crossed is allowed for the same reason.
 */
export function overCeiling(before: Bookcase, after: Bookcase): OverCeiling {
  const slots = allShelves(after).length
  if (slots > MAX_SLOTS_PER_BOOKCASE && slots > allShelves(before).length)
    return { what: 'slots', asked: slots }
  if (after.sections.length > MAX_SECTIONS_PER_BOOKCASE &&
      after.sections.length > before.sections.length)
    return { what: 'sections' }
  return null
}


/**
 * Why these cells cannot be switched off — in the document, before the press.
 *
 * The server refuses a gap over anything the owner declared (books, a
 * photograph, a name, a row behind the shelf) with a 409. That refusal is the
 * backstop for what another tab did; it is not the right way for the owner to
 * find out, because it arrives in English after the gesture, and MapScreen's
 * own rule is *"a refusal for a rule the screen could have stated before the
 * press"*.
 *
 * ⚠ **Books, photographs and depth only — a LABEL is not in the document.**
 * `Shelf` here carries `books`, `photos` and `depth`; it has never carried the
 * name, because nothing in the editor shows one. So a named-but-empty cell
 * still meets the server's 409, and that is the one case this cannot pre-empt.
 * Saying so here is cheaper than the next reader discovering it as a bug.
 */
export type NotGappable = { cells: number; books: number; photos: number; deeper: number }

export function whyNotGap(sec: Section, cells: GapCell[]): NotGappable | null {
  let books = 0, photos = 0, deeper = 0, blocked = 0
  for (const cell of cells) {
    const shelf = shelfAt(sec, cell.col, cell.level)
    if (!shelf) continue
    // DEEPER than a fresh shelf here would be, never merely different: the
    // server compares the same way, and for the same reason — editing a
    // section's default leaves existing shelves behind it (§3.3), and
    // refusing on that would refuse every cell of an ordinary bookcase.
    const isDeeper = shelf.depth > sec.defaultDepth
    if (shelf.books === 0 && shelf.photos === 0 && !isDeeper) continue
    blocked += 1
    if (shelf.books > 0) books += 1
    if (shelf.photos > 0) photos += 1
    if (isDeeper) deeper += 1
  }
  return blocked > 0 ? { cells: blocked, books, photos, deeper } : null
}
