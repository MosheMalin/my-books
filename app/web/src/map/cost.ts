/**
 * What a destructive gesture would cost, so the screen can say it first.
 *
 * Deleting a bookcase is not a drawing edit: the client empties its slots
 * (`DELETE /map/bookcases/<id>/slots`) and the server DETACHES every shelf
 * standing in one — the books keep their shelf, the shelf loses its address,
 * and nothing on the plan says so afterwards. `app/map_edit.py` states the
 * expectation in as many words: *"the API calls this first, having shown the
 * owner the counts."*
 *
 * Pure, and separate from the screen, because the counts are the part worth
 * testing — two reviews pointed out that removing a COLUMN has asked since the
 * lab, removing a SECTION has asked since the lab, and deleting the whole case
 * asked nothing.
 */
import type { Bookcase } from './core/model'
import { allShelves } from './core/model'

export type Cost = {
  /** How many pieces of furniture go. */
  cases: number
  /** How many slots stop being addressed. */
  shelves: number
  /** How many of those carry photographs. */
  photos: number
  /** How many books stand on them. */
  books: number
  /**
   * Nothing would be lost — no photograph, no book, on any slot.
   *
   * ⚠ This is what makes a dialog optional rather than polite. The owner,
   * drawing with it: *"when deleting a shelf or column or bookcase — if it's
   * not connected to any image — no need to raise a dialog. It's annoying,
   * and nothing is bound to it."* A confirmation in front of a gesture that
   * destroys nothing teaches people to click through the ones that do.
   */
  empty: boolean
}

export const deletionCost = (cases: Bookcase[]): Cost => {
  const shelves = cases.flatMap((c) => allShelves(c))
  const photos = shelves.filter((s) => s.photos > 0).length
  const books = shelves.reduce((n, s) => n + s.books, 0)
  return {
    cases: cases.length,
    shelves: shelves.length,
    photos,
    books,
    empty: photos === 0 && books === 0,
  }
}

/** The same question about any set of cells — one column, one section, one
 *  slot. Deleting them costs nothing when nothing stands on them. */
export const nothingBound = (shelves: { photos: number; books: number }[]): boolean =>
  shelves.every((s) => s.photos === 0 && s.books === 0)
