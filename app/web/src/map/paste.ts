/**
 * Pasting a copy, and why it lives in the seam rather than in `MapScreen`.
 *
 * In the lab a section id was an array key inside a browser-storage document,
 * so a copy could share one and nothing ever noticed. Here it is the handle a
 * SHELF's address holds (`shelves.section_id`), which is exactly the warning
 * MAP_PLAN's "what P6.1 hands P6.3" carries about `persist.ts`. The ported
 * `paste` minted a new bookcase id and spread the sections through unchanged,
 * so every cell of the COPY addressed the ORIGINAL's shelves: setting a depth
 * on the copy edited the original, and the server answered 200 because both
 * ids exist and both belong to this library. Measured by a review.
 *
 * Pure, so the rule is testable without a canvas.
 */
import type { Bookcase, Room, Section } from './core/model'
import { reattach } from './core/model'
import type { Clipboard, Doc, Selection } from './ui/types'

/** How far a pasted copy lands from its original, in units. Far enough to see
 *  it, near enough to drag into place. */
export const PASTE_OFFSET = 2

/**
 * The document after a paste, and what the paste selected.
 *
 * Everything minted here is deterministic in `doc.seq` — no clock, no
 * randomness — so the same edits always produce the same document, and an
 * imported plan carries on numbering without colliding.
 */
export function pasteInto(
  doc: Doc,
  clip: NonNullable<Clipboard>,
  floorId: string,
): { doc: Doc; selection: Selection } {
  let seq = doc.seq
  const roomIdMap = new Map<string, string>()
  const rooms: Room[] = clip.rooms.map((r) => {
    seq += 1
    const id = `r${seq}`
    roomIdMap.set(r.id, id)
    // Onto the storey you are LOOKING at — copying the ground floor's layout
    // as a starting point for the first floor is the obvious use.
    return { ...r, id, rect: offset(r.rect), floorId }
  })
  const cases: Bookcase[] = clip.cases.map((c) => {
    seq += 1
    const id = `c${seq}`
    return {
      ...c,
      id,
      rect: offset(c.rect),
      floorId,
      // A case copied together with its room stays with THAT copy, not with
      // the original room — otherwise pasting a room-and-its-cases produces
      // furniture that moves when the wrong room moves.
      roomId: c.roomId ? roomIdMap.get(c.roomId) ?? c.roomId : null,
      sections: c.sections.map((s, i) => freshSection(s, `${id}:s${i + 1}`)),
    }
  })
  const plan = {
    ...doc.plan,
    rooms: doc.plan.rooms.concat(rooms),
    cases: doc.plan.cases
      .concat(cases)
      .map((c) => (cases.some((n) => n.id === c.id) && !c.roomId
        ? reattach(c, doc.plan)
        : c)),
  }
  return {
    doc: { seq, plan },
    selection: {
      rooms: rooms.map((r) => r.id),
      cases: cases.map((c) => c.id),
      cells: [],
    },
  }
}

/**
 * The same section, under an id of its own — in the form `nextSectionId`
 * parses (`<case>:s<n>`), so adding a section to the copy keeps numbering
 * from where the paste left off instead of starting again at 1.
 *
 * The shelves are rebuilt rather than shared: pasting the same clipboard
 * twice must not hand two bookcases one array to edit.
 *
 * ⚠⚠ **And the SERVER's fields are dropped**, not spread. This file's own
 * header records the same failure once already — every cell of the COPY
 * addressed the ORIGINAL's shelves, so setting a depth on the copy edited the
 * original — and P6.4c walked it straight back in through this one line, with
 * worse consequences: `id` made *הורדה מהמפה* on a pasted cell send
 * `DELETE /map/shelves/<the original's id>/address`. Nothing refuses it; that
 * shelf is real, in this library, with a real address. The copy's cell still
 * looks bound afterwards, so the only visible change is a shelf that quietly
 * left the drawing somewhere else on the plan. Measured by a review.
 *
 * `free` is the milder half and goes for the same reason: a pasted free cell
 * would offer *put a shelf here* against a section the server has not created
 * yet, and answer 409 for a slot that is about to be filled.
 *
 * A pasted cell is a slot nobody has drawn yet. It has no identity until the
 * push mints one — which is exactly what `withColumnCount` produces, and what
 * `readShelf` produces on import.
 */
const freshSection = (s: Section, id: string): Section => ({
  ...s,
  id,
  columnLevels: s.columnLevels.slice(),
  shelves: s.shelves.map(
    ({ id: _id, label: _label, free: _free, ...cell }) => ({ ...cell })),
})

const offset = <T extends { x: number; y: number }>(r: T): T => ({
  ...r,
  x: r.x + PASTE_OFFSET,
  y: r.y + PASTE_OFFSET,
})
