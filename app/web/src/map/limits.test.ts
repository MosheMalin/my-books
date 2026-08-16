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
import type { Bookcase, Section } from './core/model'
import { MAX_SLOTS_PER_BOOKCASE, overCeiling } from './limits'

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
