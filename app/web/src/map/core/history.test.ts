/**
 * The undo stack — "save the editions in a stack so users can undo and redo
 * multiple times" (owner, 2026-08-16). These assert the *multiple*.
 */

import { describe, expect, it } from 'vitest'

import { HISTORY_LIMIT, canRedo, canUndo, commit, initHistory, redo, undo } from './history'

/** Push n distinct edits, untagged, so each one stacks. */
const stack = (n: number) => {
  let h = initHistory(0)
  for (let i = 1; i <= n; i++) h = commit(h, i)
  return h
}

describe('the undo stack', () => {
  it('walks back through many edits, one at a time', () => {
    let h = stack(5)
    expect(h.present).toBe(5)
    for (const expected of [4, 3, 2, 1, 0]) {
      h = undo(h)
      expect(h.present).toBe(expected)
    }
    expect(canUndo(h)).toBe(false)
    expect(undo(h).present).toBe(0) // and stops, rather than throwing
  })

  it('walks forward again through all of them', () => {
    let h = stack(5)
    for (let i = 0; i < 5; i++) h = undo(h)
    for (const expected of [1, 2, 3, 4, 5]) {
      h = redo(h)
      expect(h.present).toBe(expected)
    }
    expect(canRedo(h)).toBe(false)
  })

  it('drops the future when a NEW edit is made after undoing', () => {
    let h = stack(3)
    h = undo(h)
    h = undo(h)
    expect(canRedo(h)).toBe(true)
    h = commit(h, 99)
    expect(canRedo(h)).toBe(false)
    expect(h.past).toEqual([0, 1])
  })

  it('ignores a commit that changes nothing', () => {
    const h = stack(2)
    expect(commit(h, h.present)).toBe(h)
  })

  it('collapses same-tag edits, so typing a name is ONE undo', () => {
    let h = initHistory('')
    for (const s of ['s', 'sa', 'sal', 'salo', 'salon']) h = commit(h, s, 'rename:r1')
    expect(h.present).toBe('salon')
    expect(h.past).toEqual([''])
    expect(undo(h).present).toBe('')
  })

  it('keeps a DIFFERENT tag as its own entry', () => {
    let h = initHistory('')
    h = commit(h, 'a', 'rename:r1')
    h = commit(h, 'b', 'rename:r2')
    expect(h.past).toHaveLength(2)
  })

  it('never merges into an entry the user has already undone past', () => {
    // After stepping back, the tag no longer describes the present. Leaving it
    // set would let the next keystroke silently overwrite a restored state.
    let h = initHistory('')
    h = commit(h, 'a', 'rename:r1')
    h = undo(h)
    h = commit(h, 'z', 'rename:r1')
    expect(h.past).toEqual([''])
    expect(undo(h).present).toBe('')
  })

  it('is bounded, and forgets the OLDEST rather than the newest', () => {
    let h = initHistory(0)
    for (let i = 1; i <= HISTORY_LIMIT + 10; i++) h = commit(h, i)
    expect(h.past).toHaveLength(HISTORY_LIMIT)
    expect(h.present).toBe(HISTORY_LIMIT + 10)
    expect(h.past[0]).toBe(10)
  })
})
