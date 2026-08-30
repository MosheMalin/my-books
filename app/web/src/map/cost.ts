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
import type { Bookcase, Plan } from './core/model'
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

/**
 * What restoring a saved drawing would cost (P6.7f).
 *
 * The owner settled the semantics: *"ask if the user is sure and say data
 * will get unbound. if user agrees — replace."* This is the sentence's
 * arithmetic, and it is deliberately asked of the SHELF IDS rather than of
 * the geometry:
 *
 *   a live slot survives the restore if the file still holds its shelf id.
 *
 * Nothing else is a safe question. A cell at the same (case, section, column,
 * level) is not the same shelf — the whole reason version 5 carries ids is
 * that positions move — and comparing positions would report a column shrink
 * as free while quietly detaching the books in it.
 *
 * ⚠ A live slot with NO id is not counted. It is either a cell this session
 * drew, which the server has never seen, or one the server says is free;
 * neither holds a book or a photograph, so calling it lost would inflate the
 * only number in the dialog that matters.
 */
export const importCost = (live: Plan, incoming: Plan): Cost => {
  const survives = new Set<string>()
  for (const bc of incoming.cases)
    for (const sec of bc.sections)
      for (const sh of sec.shelves) if (sh.id) survives.add(sh.id)

  const standing = new Set(incoming.cases.map((c) => c.id))
  const lost = live.cases
    .flatMap((c) => allShelves(c))
    .filter((sh) => sh.id && !survives.has(sh.id))

  return {
    // Whole pieces of furniture the file does not have. A case that survives
    // with fewer columns is not counted here — its lost slots are.
    cases: live.cases.filter((c) => !standing.has(c.id)).length,
    shelves: lost.length,
    photos: lost.filter((sh) => sh.photos > 0).length,
    books: lost.reduce((n, sh) => n + sh.books, 0),
    empty: lost.every((sh) => sh.photos === 0 && sh.books === 0),
  }
}

/** The same question about any set of cells — one column, one section, one
 *  slot. Deleting them costs nothing when nothing stands on them. */
export const nothingBound = (shelves: { photos: number; books: number }[]): boolean =>
  shelves.every((s) => s.photos === 0 && s.books === 0)
