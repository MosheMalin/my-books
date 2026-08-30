/**
 * What a destructive gesture costs, asked before it happens.
 *
 * `deletionCost` is exercised through the panels that use it; what lives here
 * is `importCost` (P6.7f), because a restore is the one destructive gesture
 * whose damage cannot be read off the thing you pressed. Deleting a bookcase
 * costs that bookcase; restoring a file costs whatever the file happens not
 * to contain, and the only honest way to know is to compare.
 */
import { describe, expect, it } from 'vitest'

import { emptyPlan, GROUND_FLOOR, type Bookcase, type Plan, type Shelf } from './core/model'
import { importCost } from './cost'

const shelf = (over: Partial<Shelf> & { col: number; level: number }): Shelf => ({
  depth: 1, photos: 0, books: 0, ...over,
})

const caseWith = (id: string, shelves: Shelf[]): Bookcase => ({
  id,
  name: '',
  rect: { x: 0, y: 0, w: 4, h: 1 },
  front: 'S',
  roomId: null,
  floorId: GROUND_FLOOR.id,
  sections: [{
    id: `${id}:s1`,
    columnLevels: [Math.max(1, shelves.length)],
    gaps: [],
    defaultLevels: 1,
    defaultDepth: 1,
    shelves,
  }],
})

const planOf = (...cases: Bookcase[]): Plan => ({ ...emptyPlan(), cases })

describe('what restoring a saved drawing would cost (P6.7f)', () => {
  it('counts a shelf as lost when the file does not hold its ID', () => {
    // ⚠⚠ The whole rule. A cell at the same (case, section, column, level) is
    // NOT the same shelf — version 5 carries ids precisely because positions
    // move — so a comparison by position would report a column shrink as free
    // while detaching the books standing in it.
    const live = planOf(caseWith('c1', [
      shelf({ col: 0, level: 0, id: 'stays', books: 2 }),
      shelf({ col: 0, level: 1, id: 'goes', books: 3, photos: 1 }),
    ]))
    // Same case, same position for the survivor, and the second cell now
    // holds a DIFFERENT shelf — which is exactly the shape that fools a
    // positional comparison.
    const file = planOf(caseWith('c1', [
      shelf({ col: 0, level: 0, id: 'stays' }),
      shelf({ col: 0, level: 1, id: 'someone-else' }),
    ]))

    const cost = importCost(live, file)
    expect(cost.shelves).toBe(1)
    expect(cost.books).toBe(3)
    expect(cost.photos).toBe(1)
    expect(cost.empty).toBe(false)
  })

  it('counts a whole bookcase the file has never heard of', () => {
    const live = planOf(
      caseWith('c1', [shelf({ col: 0, level: 0, id: 'a' })]),
      caseWith('c2', [shelf({ col: 0, level: 0, id: 'b', books: 4 })]),
    )
    const file = planOf(caseWith('c1', [shelf({ col: 0, level: 0, id: 'a' })]))

    const cost = importCost(live, file)
    expect(cost.cases).toBe(1)
    expect(cost.shelves).toBe(1)
    expect(cost.books).toBe(4)
  })

  it('does not count a case that merely SHRANK as a case that goes', () => {
    // Its lost slots are counted; the furniture is still there. A dialog that
    // said "one bookcase goes" about a bookcase that stays is the kind of
    // wrong stated reason that makes the next person distrust the number that
    // matters.
    const live = planOf(caseWith('c1', [
      shelf({ col: 0, level: 0, id: 'a' }),
      shelf({ col: 0, level: 1, id: 'b', books: 1 }),
    ]))
    const file = planOf(caseWith('c1', [shelf({ col: 0, level: 0, id: 'a' })]))

    const cost = importCost(live, file)
    expect(cost.cases).toBe(0)
    expect(cost.shelves).toBe(1)
    expect(cost.books).toBe(1)
  })

  it('ignores a slot the server has never seen', () => {
    // A cell this session drew has no shelf row yet, and a cell the server
    // says is free holds nothing. Counting either would inflate the only
    // number in the dialog anybody reads.
    const live = planOf(caseWith('c1', [
      shelf({ col: 0, level: 0 }),
      shelf({ col: 0, level: 1, free: true }),
    ]))

    const cost = importCost(live, planOf())
    expect(cost.shelves).toBe(0)
    expect(cost.books).toBe(0)
    expect(cost.empty).toBe(true)
  })

  it('says nothing is lost when nothing stands on what goes', () => {
    // `empty` is what makes the dialog's two sentences differ, and the rule
    // it follows is the owner's own: a confirmation in front of a gesture
    // that destroys nothing teaches people to click through the ones that do.
    // A restore always asks — it replaces the drawing — but it must not claim
    // a loss it cannot name.
    const live = planOf(caseWith('c1', [shelf({ col: 0, level: 0, id: 'a' })]))

    const cost = importCost(live, planOf())
    expect(cost.cases).toBe(1)
    expect(cost.shelves).toBe(1)
    expect(cost.empty).toBe(true)
  })
})
