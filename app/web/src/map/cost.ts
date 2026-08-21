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
  /**
   * How many of those carry photographs.
   *
   * ⚠ Photographs, not BOOKS. The client knows `capture_count` because the
   * shelf list carries it; it does not know what stands on a shelf, and the
   * split that matters (`deleted` vs `detached`) is what the server reports
   * AFTER the call. So this is the number that can be stated honestly, and the
   * wording promises the mechanism rather than a count nobody has.
   */
  photos: number
}

export const deletionCost = (cases: Bookcase[]): Cost => {
  const shelves = cases.flatMap((c) => allShelves(c))
  return {
    cases: cases.length,
    shelves: shelves.length,
    photos: shelves.filter((s) => s.photos > 0).length,
  }
}
