/**
 * The selection set. Pure, so it is tested — and it ports with the editor,
 * because "several things are selected" is a rule the product will inherit,
 * not a detail of this shell.
 */

import { describe, expect, it } from 'vitest'

import { EMPTY, count, hasCase, hasRoom, only, selectCase, selectRoom, toggle } from './types'
import { emptyPlan, newBookcase } from '../core/model'
import type { Plan } from '../core/model'

const plan: Plan = {
  ...emptyPlan(),
  rooms: [{ id: 'r1', name: 'salon', rect: { x: 0, y: 0, w: 20, h: 12 } }],
  cases: [newBookcase('c1', 'case', { x: 2, y: 0, w: 8, h: 1 }, 'S', 'r1')],
}

describe('the selection set', () => {
  it('starts empty', () => {
    expect(count(EMPTY)).toBe(0)
    expect(only(EMPTY, plan)).toBeNull()
  })

  it('counts rooms and cases together', () => {
    const s = { rooms: ['r1'], cases: ['c1'], shelf: null }
    expect(count(s)).toBe(2)
    expect(hasRoom(s, 'r1')).toBe(true)
    expect(hasCase(s, 'c1')).toBe(true)
  })

  it('resolves a single selection to the object itself', () => {
    expect(only(selectRoom('r1'), plan)).toEqual(plan.rooms[0])
    expect(only(selectCase('c1'), plan)).toEqual(plan.cases[0])
  })

  it('resolves to NOTHING when several are selected', () => {
    // The panels that edit one object ask for this, and the resize handles do
    // too: eight grips on each of six rooms is a field of dots, every one of
    // them ambiguous.
    expect(only({ rooms: ['r1'], cases: ['c1'], shelf: null }, plan)).toBeNull()
  })

  it('toggles in and back out again — Ctrl+click both ways', () => {
    const added = toggle(EMPTY, 'room', 'r1')
    expect(hasRoom(added, 'r1')).toBe(true)
    expect(hasRoom(toggle(added, 'room', 'r1'), 'r1')).toBe(false)
  })

  it('drops the shelf cell whenever the plan selection changes', () => {
    // A shelf belongs INSIDE one bookcase. Keeping it while the selection
    // moves to a different object would leave the panel editing a cell of
    // something nobody has selected.
    const withShelf = { rooms: [], cases: ['c1'], shelf: { caseId: 'c1', col: 0, level: 0 } }
    expect(toggle(withShelf, 'room', 'r1').shelf).toBeNull()
  })

  it('never resolves an id that is not in the plan', () => {
    expect(only(selectRoom('ghost'), plan)).toBeNull()
  })
})
