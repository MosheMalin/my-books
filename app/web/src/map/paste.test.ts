/**
 * What a paste must not share with what it was copied from.
 *
 * The lab could alias anything: the whole document was one blob in
 * `localStorage`, so two cases pointing at one section object were two views
 * of the same drawing and nothing outside noticed. In the product a section id
 * is a SHELF's address, so the aliasing reaches the database.
 */
import { describe, expect, it } from 'vitest'

import { newBookcase } from './core/model'
import type { Bookcase, Plan, Room, Section } from './core/model'
import { emptyPlan } from './core/model'
import { pasteInto } from './paste'
import { planDiff } from './sync'
import type { Doc } from './ui/types'

const section = (id: string, cols: number, levels: number, depth: number): Section => ({
  id,
  columnLevels: Array.from({ length: cols }, () => levels),
  defaultLevels: levels,
  defaultDepth: depth,
  shelves: Array.from({ length: cols }, (_, col) =>
    Array.from({ length: levels }, (_, level) => ({ col, level, depth, photos: 0 })),
  ).flat(),
})

const room = (id: string): Room =>
  ({ id, name: 'סלון', rect: { x: 0, y: 0, w: 10, h: 8 }, floorId: 'f1' })

const configured = (id: string, roomId: string | null): Bookcase => ({
  ...newBookcase(id, 'ארון הסלון', { x: 1, y: 0, w: 4, h: 1 }, 'S', roomId, 'f1', 2),
  sections: [section(`${id}:s1`, 2, 5, 1), section(`${id}:s2`, 3, 3, 2)],
})

const docOf = (plan: Plan, seq = 9): Doc => ({ plan, seq })

describe('pasting a bookcase', () => {
  const original = configured('c1', 'r1')
  const plan: Plan = { ...emptyPlan(), rooms: [room('r1')], cases: [original] }
  const clip = { rooms: [], cases: [original] }

  it('gives the copy section ids of its own', () => {
    const { doc } = pasteInto(docOf(plan), clip, 'f1')
    const copy = doc.plan.cases[1]!
    const ids = copy.sections.map((s) => s.id)
    // ⚠ The bug this file exists for: `paste` minted a case id and spread the
    // sections through unchanged, so `setShelfDepth` on the COPY addressed the
    // ORIGINAL's shelves and the server answered 200 — both ids exist, both
    // belong to this library, and nothing on either side could tell.
    expect(ids).not.toEqual(original.sections.map((s) => s.id))
    expect(new Set(ids).size).toBe(2)
    expect(ids.every((id) => id.startsWith(`${copy.id}:s`))).toBe(true)
  })

  it('keeps the shape it copied, only the identity is new', () => {
    const { doc } = pasteInto(docOf(plan), clip, 'f1')
    const copy = doc.plan.cases[1]!
    expect(copy.sections.map((s) => s.columnLevels)).toEqual([[5, 5], [3, 3, 3]])
    expect(copy.sections.map((s) => s.defaultDepth)).toEqual([1, 2])
    expect(copy.name).toBe(original.name)
  })

  it('shares no shelf object with the original, so an edit stays put', () => {
    const { doc } = pasteInto(docOf(plan), clip, 'f1')
    const copy = doc.plan.cases[1]!
    copy.sections[0]!.shelves[0]!.depth = 4
    expect(original.sections[0]!.shelves[0]!.depth).toBe(1)
    expect(copy.sections[0]!.columnLevels)
      .not.toBe(original.sections[0]!.columnLevels)
  })

  it('sends the copy to the server as a NEW case, touching no original id', () => {
    const { doc } = pasteInto(docOf(plan), clip, 'f1')
    const ops = planDiff(plan, doc.plan)
    const named = JSON.stringify(ops)
    expect(ops[0]!.kind).toBe('case.add')
    for (const id of original.sections.map((s) => s.id))
      expect(named).not.toContain(id)
  })

  it('follows the room it was copied WITH, not the room it came from', () => {
    const { doc } = pasteInto(docOf(plan), { rooms: [room('r1')], cases: [original] }, 'f1')
    const [newRoom] = doc.plan.rooms.slice(1)
    const copy = doc.plan.cases[1]!
    expect(copy.roomId).toBe(newRoom!.id)
    expect(copy.roomId).not.toBe('r1')
  })

  it('lands on the storey being LOOKED at', () => {
    const { doc, selection } = pasteInto(docOf(plan), clip, 'f2')
    expect(doc.plan.cases[1]!.floorId).toBe('f2')
    expect(selection.cases).toEqual([doc.plan.cases[1]!.id])
    expect(selection.shelf).toBeNull()
  })

  it('numbers from the document, so two pastes never collide', () => {
    const first = pasteInto(docOf(plan), clip, 'f1')
    const second = pasteInto(first.doc, clip, 'f1')
    const ids = second.doc.plan.cases.map((c) => c.id)
    expect(new Set(ids).size).toBe(ids.length)
    const sections = second.doc.plan.cases.flatMap((c) => c.sections.map((s) => s.id))
    expect(new Set(sections).size).toBe(sections.length)
  })
})
