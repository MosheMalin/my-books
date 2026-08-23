/**
 * The ceilings the editor must not offer to cross.
 *
 * MAP_PLAN, on what P6.2 measured: a 110-byte request asking for 40 columns of
 * 40 wrote 1600 rows in 16.5 seconds, so the server refuses above 400 slots —
 * *"the editor must not offer a gesture that asks for more than the ceiling,
 * or the owner meets a 409"*. A 409 here is expensive twice: the refusal
 * banner, and the reload the sync does to re-derive a document it can no
 * longer describe.
 */
import { describe, expect, it } from 'vitest'

import { newBookcase, newSection, withColumnCount } from './core/model'
import type { Bookcase, Section, Shelf } from './core/model'
import { deletionCost } from './cost'
import {
  MAX_COLUMNS_PER_SECTION,
  MAX_LEVELS_PER_COLUMN,
  MAX_SLOTS_PER_BOOKCASE,
  clampColumns,
  clampLevels,
  overCeiling,
  whyNotGap,
} from './limits'

const wide = (id: string, cols: number, levels: number): Section =>
  withColumnCount({ ...newSection(id, 1), defaultLevels: levels,
                    columnLevels: [], shelves: [] }, cols)

const caseOf = (...sections: Section[]): Bookcase => ({
  ...newBookcase('c1', '', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 1),
  sections,
})

describe('the slot ceiling', () => {
  it('refuses the column that would cross it, and names the number', () => {
    const before = caseOf(wide('s1', 39, 10))          // 390
    const after = caseOf(wide('s1', 41, 10))           // 410
    expect(overCeiling(before, after))
      .toEqual({ what: 'slots', asked: 410 })
    expect(MAX_SLOTS_PER_BOOKCASE).toBe(400)
  })

  it('lets a bookcase right up to the ceiling', () => {
    expect(overCeiling(caseOf(wide('s1', 39, 10)), caseOf(wide('s1', 40, 10))))
      .toBeNull()
  })

  it('counts every section, because the server does', () => {
    const before = caseOf(wide('s1', 20, 10), wide('s2', 19, 10))   // 390
    const after = caseOf(wide('s1', 20, 10), wide('s2', 21, 10))    // 410
    expect(overCeiling(before, after)).toMatchObject({ what: 'slots' })
  })

  it('never blocks the way OUT of a case that is already too big', () => {
    // ⚠ The load-bearing clause. A document restored by undo, or a plan drawn
    // before the ceiling existed, must still be shrinkable — a guard that
    // refuses every edit to an over-large case is the trap, not the fix.
    const huge = caseOf(wide('s1', 60, 10))            // 600
    expect(overCeiling(huge, caseOf(wide('s1', 50, 10)))).toBeNull()
    expect(overCeiling(huge, caseOf(wide('s1', 60, 10)))).toBeNull()
    expect(overCeiling(huge, caseOf(wide('s1', 61, 10))))
      .toMatchObject({ what: 'slots' })
  })

  it('refuses the ninth section', () => {
    const eight = Array.from({ length: 8 }, (_, i) => wide(`s${i}`, 1, 1))
    expect(overCeiling(caseOf(...eight.slice(0, 7)), caseOf(...eight))).toBeNull()
    expect(overCeiling(caseOf(...eight), caseOf(...eight, wide('s9', 1, 1))))
      .toEqual({ what: 'sections' })
  })
})

describe('a typed number', () => {
  it('never leaves the range the wire accepts', () => {
    // ⚠ An `<input max=…>` is a hint, not a gate: typing 41 into *new levels*
    // sent `{"default_levels": 41}`, came back 422, and a 422's `detail` is a
    // LIST — so the banner rendered `[object Object]`. Both halves were
    // measured; this is the one that stops the request being made.
    expect(clampLevels(41)).toBe(MAX_LEVELS_PER_COLUMN)
    expect(clampColumns(999)).toBe(MAX_COLUMNS_PER_SECTION)
    expect(clampLevels(40)).toBe(40)
    // An empty box reads as 0 and means one — the behaviour every number
    // field in this editor already had.
    expect(clampLevels(0)).toBe(1)
    expect(clampLevels(Number.NaN)).toBe(1)
    expect(clampColumns(-3)).toBe(1)
  })
})

describe('what deleting a bookcase would cost', () => {
  it('counts the shelves that stop being addressed, and the photographed ones', () => {
    // Removing a COLUMN has asked since the lab and removing a SECTION has
    // asked since the lab; deleting the whole case asked nothing, while doing
    // the same thing to more data. These are the numbers the door states.
    const withPhotos = (id: string): Bookcase => {
      const bc = caseOf(wide(id, 2, 3))
      const sec = bc.sections[0]!
      sec.shelves = sec.shelves.map((s, i) => (i < 2 ? { ...s, photos: 1 } : s))
      return { ...bc, id }
    }
    expect(deletionCost([withPhotos('a'), withPhotos('b')]))
      .toEqual({ cases: 2, shelves: 12, photos: 4, books: 0, empty: false })
    // A selection of rooms alone destroys no shelf, and asks nothing.
    expect(deletionCost([]))
      .toEqual({ cases: 0, shelves: 0, photos: 0, books: 0, empty: true })
  })

  it('says NOTHING is bound when no slot holds a photo or a book', () => {
    // ⚠ The owner, drawing with it: *"if it's not connected to any image — no
    // need to raise a dialog. It's annoying, and nothing is bound to it."* A
    // confirmation in front of a gesture that destroys nothing is what teaches
    // people to click through the ones that do.
    const bare = caseOf(wide('s1', 2, 3))
    expect(deletionCost([bare]).empty).toBe(true)

    const held = caseOf(wide('s1', 2, 3))
    held.sections[0]!.shelves[0]!.books = 1
    expect(deletionCost([held]).empty).toBe(false)
    expect(deletionCost([held]).books).toBe(1)
  })
})

describe('whyNotGap — the server refusal, stated before the press', () => {
  const sec = (shelves: Shelf[]): Section => ({
    id: 's1', columnLevels: [2], gaps: [], defaultLevels: 2, defaultDepth: 2, shelves,
  })
  const cell = { col: 0, level: 0 }
  const at = (over: Partial<Shelf>): Shelf =>
    ({ col: 0, level: 0, depth: 2, photos: 0, books: 0, ...over })

  it('lets an empty cell through', () => {
    expect(whyNotGap(sec([at({})]), [cell])).toBeNull()
  })

  it('refuses books and photographs, the way the server asks both stores', () => {
    expect(whyNotGap(sec([at({ books: 1 })]), [cell])).toMatchObject({ cells: 1, books: 1 })
    expect(whyNotGap(sec([at({ photos: 1 })]), [cell])).toMatchObject({ cells: 1, photos: 1 })
  })

  it('refuses a row declared BEHIND the shelf, and only that', () => {
    // ⚠ Deeper, never merely different — the same clause, and the same
    // reason, as `app/map_edit.py:apply_gaps`. §3.3 makes a section's default
    // drift away from its shelves by design, so `!==` would refuse every cell
    // of any case whose default had been edited: the feature's own scenario,
    // and it would refuse it BEFORE the press, with the button absent.
    expect(whyNotGap(sec([at({ depth: 3 })]), [cell])).toMatchObject({ cells: 1, deeper: 1 })
    expect(whyNotGap(sec([at({ depth: 1 })]), [cell])).toBeNull()
    expect(whyNotGap(sec([at({ depth: 2 })]), [cell])).toBeNull()
  })

  it('counts the cells that block, not the reasons', () => {
    const two = sec([at({ books: 1, photos: 2 }), at({ level: 1, depth: 4 })])
    expect(whyNotGap(two, [cell, { col: 0, level: 1 }]))
      .toEqual({ cells: 2, books: 1, photos: 1, deeper: 1 })
  })

  it('says nothing about a cell that is already a hole', () => {
    expect(whyNotGap({ ...sec([]), gaps: [cell] }, [cell])).toBeNull()
  })
})
