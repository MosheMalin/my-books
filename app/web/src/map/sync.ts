/**
 * The plan document ⇄ `/api/v1/map`.
 *
 * **This file is the whole port.** `core/*` came over from `planning/map-lab`
 * byte-for-byte — it is framework-free by construction, and its 83 tests run
 * here unchanged, which is the proof MAP_PLAN §5 asked for. The editor's
 * interaction model is therefore not re-implemented and cannot drift: what
 * changed is where the bytes go, and that is this module.
 *
 * The lab wrote the whole document to `localStorage` on every edit. A server
 * cannot be written that way — "save the whole plan" makes the last tab to
 * press a key the winner of every disagreement (`app/ports/map.py`) — so the
 * document is DIFFED against the last state the server confirmed, and the
 * difference becomes one call per changed object.
 *
 * ⚠ **Ids are translated, never rewritten.** A create mints its id on the
 * server, but the document already holds a local one and the undo stack holds
 * it too — rewriting either would corrupt history. So the local id stays what
 * it is for the session and this module keeps the mapping. On the next load
 * the document is rebuilt from the server and the ids ARE the server's. That
 * also honours MAP_PLAN's warning for P6.3: `persist.ts` rebuilds section ids
 * from array position on import, and `shelves.section_id` now refers to one.
 */

import type { Bookcase, Floor, Plan, Room, Section, Shelf } from './core/model'
import { columnCount } from './core/model'
import type { Rect, Side } from './core/rect'

// --- the wire, narrowed to what this editor uses --------------------------

export type RectWire = { x: number; y: number; w: number; h: number }

export type MapWire = {
  sites: { id: string; name: string; order: number }[]
  floors: { id: string; site_id: string; name: string; order: number }[]
  places: { id: string; floor_id: string; name: string; rect: RectWire; order: number }[]
  bookcases: {
    id: string
    floor_id: string
    place_id: string | null
    name: string
    front: string
    rect: RectWire
    order: number
  }[]
  sections: {
    id: string
    bookcase_id: string
    ordinal: number
    column_levels: number[]
    default_levels: number
    default_depth: number
  }[]
}

export type ShelfWire = {
  id: string
  depth_count: number
  capture_count: number
  address: { section_id: string; col: number; level: number } | null
}

/**
 * Server → document.
 *
 * ⚠ **The one off-by-one in the whole pillar, and it is deliberate.** The
 * document's `col`/`level` are 0-based array positions (the lab's); the API's
 * are 1-based, and `ShelfAddress` REFUSES a 0 rather than re-basing silently,
 * so a forgotten shift raises on the server instead of filing every book one
 * shelf over. `fixtures/map/lab_plan_v4.json` pins both conventions.
 */
export function toPlan(map: MapWire, shelves: ShelfWire[], siteId: string): Plan {
  const floors = map.floors
    .filter((f) => f.site_id === siteId)
    .map((f) => ({ id: f.id, name: f.name }))
  const mine = new Set(floors.map((f) => f.id))
  const byAddress = new Map<string, ShelfWire>()
  for (const shelf of shelves) {
    if (shelf.address) byAddress.set(slotKey(shelf.address.section_id,
      shelf.address.col - 1, shelf.address.level - 1), shelf)
  }
  const sectionsOf = (caseId: string): Section[] =>
    map.sections
      .filter((s) => s.bookcase_id === caseId)
      .sort((a, b) => a.ordinal - b.ordinal)      // BOTTOM first, as drawn
      .map((s) => ({
        id: s.id,
        columnLevels: s.column_levels.slice(),
        defaultLevels: s.default_levels,
        defaultDepth: s.default_depth,
        shelves: s.column_levels.flatMap((levels, col) =>
          Array.from({ length: levels }, (_, level) => {
            const shelf = byAddress.get(slotKey(s.id, col, level))
            return {
              col,
              level,
              depth: shelf?.depth_count ?? s.default_depth,
              photos: shelf?.capture_count ?? 0,
            }
          }),
        ),
      }))
  return {
    floors: floors.length > 0 ? floors : [{ id: 'f1', name: '' }],
    rooms: map.places
      .filter((p) => mine.has(p.floor_id))
      .map((p) => ({ id: p.id, name: p.name, rect: p.rect, floorId: p.floor_id })),
    cases: map.bookcases
      .filter((c) => mine.has(c.floor_id))
      .map((c) => ({
        id: c.id,
        name: c.name,
        rect: c.rect,
        front: c.front as Side,
        roomId: c.place_id,
        floorId: c.floor_id,
        sections: sectionsOf(c.id),
      })),
    underlay: null,
  }
}

const slotKey = (sectionId: string, col: number, level: number) =>
  `${sectionId}|${col}|${level}`

// --- the difference between two documents --------------------------------

export type Op =
  | { kind: 'floor.add'; floor: Floor }
  | { kind: 'floor.rename'; id: string; name: string }
  | { kind: 'floor.remove'; id: string }
  | { kind: 'room.add'; room: Room }
  | { kind: 'room.edit'; room: Room; movedStorey: boolean }
  | { kind: 'room.remove'; id: string }
  | { kind: 'case.add'; bookcase: Bookcase }
  | { kind: 'case.edit'; bookcase: Bookcase; roomChanged: boolean }
  | { kind: 'case.remove'; id: string }
  | { kind: 'section.add'; caseId: string; section: Section; atBottom: boolean }
  | { kind: 'section.columns'; section: Section; columns: number }
  | { kind: 'section.levels'; section: Section; col: number; levels: number }
  | { kind: 'section.defaults'; section: Section }
  | { kind: 'section.remove'; id: string }
  | { kind: 'shelf.depth'; section: Section; col: number; level: number; depth: number }

/**
 * What changed, as the calls that would reproduce it.
 *
 * Pure, and therefore the part of the sync that is actually tested. The
 * ORDER is not incidental: creates before edits (a case cannot attach to a
 * room the server has not got), and every removal LAST — a room's delete is
 * refused while its bookcases are being moved out of it, and a section's
 * while its slots are being emptied.
 *
 * ⚠ **One grid instruction per section per pass.** P6.2 answers 400 for a
 * request carrying both `columns` and `column`/`levels`, because the old
 * fall-through silently applied half an edit. A single gesture only ever
 * changes one of them; a batch that somehow changed both emits the column
 * count and leaves the per-column heights to the next pass, which converges.
 */
export function planDiff(before: Plan, after: Plan): Op[] {
  const ops: Op[] = []
  const wasFloor = index(before.floors)
  const wasRoom = index(before.rooms)
  const wasCase = index(before.cases)

  for (const floor of after.floors) {
    const had = wasFloor.get(floor.id)
    if (!had) ops.push({ kind: 'floor.add', floor })
    else if (had.name !== floor.name)
      ops.push({ kind: 'floor.rename', id: floor.id, name: floor.name })
  }
  for (const room of after.rooms) {
    const had = wasRoom.get(room.id)
    if (!had) ops.push({ kind: 'room.add', room })
    else if (!sameRoom(had, room))
      ops.push({ kind: 'room.edit', room, movedStorey: had.floorId !== room.floorId })
  }
  for (const bookcase of after.cases) {
    const had = wasCase.get(bookcase.id)
    if (!had) {
      ops.push({ kind: 'case.add', bookcase })
      continue
    }
    if (!sameCase(had, bookcase))
      ops.push({
        kind: 'case.edit',
        bookcase,
        roomChanged: had.roomId !== bookcase.roomId,
      })
    ops.push(...sectionDiff(had, bookcase))
  }

  // Removals last, and innermost first — a bookcase cannot go while its
  // sections are being counted, nor a floor while its rooms are still there.
  for (const bookcase of before.cases) {
    const still = after.cases.find((c) => c.id === bookcase.id)
    if (!still) {
      ops.push({ kind: 'case.remove', id: bookcase.id })
      continue
    }
    for (const section of bookcase.sections)
      if (!still.sections.some((s) => s.id === section.id))
        ops.push({ kind: 'section.remove', id: section.id })
  }
  for (const room of before.rooms)
    if (!after.rooms.some((r) => r.id === room.id))
      ops.push({ kind: 'room.remove', id: room.id })
  for (const floor of before.floors)
    if (!after.floors.some((f) => f.id === floor.id))
      ops.push({ kind: 'floor.remove', id: floor.id })
  return ops
}

function sectionDiff(before: Bookcase, after: Bookcase): Op[] {
  const ops: Op[] = []
  const had = index(before.sections)
  after.sections.forEach((section, i) => {
    const was = had.get(section.id)
    if (!was) {
      ops.push({ kind: 'section.add', caseId: after.id, section, atBottom: i === 0 })
      return
    }
    if (was.defaultLevels !== section.defaultLevels ||
        was.defaultDepth !== section.defaultDepth)
      ops.push({ kind: 'section.defaults', section })
    if (columnCount(was) !== columnCount(section)) {
      ops.push({ kind: 'section.columns', section, columns: columnCount(section) })
    } else {
      section.columnLevels.forEach((levels, col) => {
        if (was.columnLevels[col] !== levels)
          ops.push({ kind: 'section.levels', section, col, levels })
      })
    }
    for (const shelf of section.shelves) {
      const stood = was.shelves.find(
        (s) => s.col === shelf.col && s.level === shelf.level)
      if (stood && stood.depth !== shelf.depth)
        ops.push({
          kind: 'shelf.depth', section, col: shelf.col,
          level: shelf.level, depth: shelf.depth,
        })
    }
  })
  return ops
}

const index = <T extends { id: string }>(xs: T[]) =>
  new Map(xs.map((x) => [x.id, x]))

const sameRect = (a: Rect, b: Rect) =>
  a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h

const sameRoom = (a: Room, b: Room) =>
  a.name === b.name && a.floorId === b.floorId && sameRect(a.rect, b.rect)

const sameCase = (a: Bookcase, b: Bookcase) =>
  a.name === b.name && a.front === b.front && a.roomId === b.roomId &&
  a.floorId === b.floorId && sameRect(a.rect, b.rect)

/** A shelf's own depth, as the elevation shows it. Exported for the tests
 *  that pin the 0-based ⇄ 1-based shift. */
export const wireAddress = (section: Section, shelf: Shelf) => ({
  section_id: section.id,
  col: shelf.col + 1,
  level: shelf.level + 1,
})
