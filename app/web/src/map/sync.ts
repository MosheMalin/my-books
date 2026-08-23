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

import type { Bookcase, Floor, GapCell, Plan, Room, Section, Shelf } from './core/model'
import {
  DEFAULT_DEPTH,
  DEFAULT_LEVELS,
  columnCount,
  inExtent,
  withColumnCount,
} from './core/model'
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
    /** Cells that hold no shelf (P6.3.2). 1-BASED, like every address on the
     *  wire; the document re-bases them with everything else. */
    gaps: { column: number; level: number }[]
    default_levels: number
    default_depth: number
  }[]
}

export type ShelfWire = {
  id: string
  depth_count: number
  capture_count: number
  book_count: number
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
      .map((s) => {
        // 1-based on the wire, 0-based here — the pillar's one off-by-one,
        // applied to the mask exactly as it is to an address.
        const gaps = (s.gaps ?? []).map((g) => ({ col: g.column - 1, level: g.level - 1 }))
        const gapped = new Set(gaps.map((g) => slotKey(s.id, g.col, g.level)))
        return {
          id: s.id,
          columnLevels: s.column_levels.slice(),
          gaps,
          defaultLevels: s.default_levels,
          defaultDepth: s.default_depth,
          // ⚠ The extent still says how tall the column is — a gap does NOT
          // shorten it — but a gapped cell gets no shelf entry. That is what
          // keeps `allShelves` (and `limits.ts:overCeiling` through it)
          // counting what the server counts: addresses, not cells.
          shelves: s.column_levels.flatMap((levels, col) =>
            Array.from({ length: levels }, (_, level) => ({ col, level }))
              .filter(({ col: c, level: l }) => !gapped.has(slotKey(s.id, c, l)))
              .map(({ col: c, level: l }) => {
                const shelf = byAddress.get(slotKey(s.id, c, l))
                return {
                  col: c,
                  level: l,
                  depth: shelf?.depth_count ?? s.default_depth,
                  photos: shelf?.capture_count ?? 0,
                  books: shelf?.book_count ?? 0,
                }
              }),
          ),
        }
      })
  return {
    // ⚠ The fallback is a LAST RESORT, not a normal path, and it is why
    // `ensureHome` exists: an earlier version let this synthesise a storey the
    // server had never heard of, and the first room drawn onto it was refused
    // with a 404 for a floor id that existed nowhere but the document. The
    // loader now creates a real one BEFORE this runs, so an empty list here
    // means the site was deleted underneath us — a blank canvas is a better
    // answer than a crash, and the next edit will be refused rather than
    // filed somewhere wrong, because this id belongs to nothing.
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
  /** ⚠ `aboveId` is the section it STANDS ON, and null means the floor.
   *  `top`/`bottom` could not say *back where it was*: a section restored into
   *  the middle of a stack by an undo was sent as `top`, the server appended
   *  it, and the client recorded the append as landed — so the drawing and the
   *  library disagreed about which unit stands on which, with nothing left to
   *  re-diff, and `ordinal` is what an address PRINTS. */
  | { kind: 'section.add'; caseId: string; section: Section; aboveId: string | null }
  | { kind: 'section.columns'; section: Section; columns: number }
  | { kind: 'section.levels'; section: Section; col: number; levels: number }
  | { kind: 'section.defaults'; section: Section }
  /** Cells switched off, or back on (P6.3.2). One op per DIRECTION, never
   *  a mixed list: the route carries the sign explicitly, for the reason
   *  `patch_section` refuses two grid instructions in one request. */
  | { kind: 'section.gaps'; section: Section; cells: GapCell[]; gap: boolean }
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
 * ⚠ **One grid instruction per REQUEST.** P6.2 answers 400 for a request
 * carrying both `columns` and `column`/`levels`, because the old fall-through
 * silently applied half an edit. That is a rule about one call, not about one
 * pass: a pass that changes both sends the column count and then the heights,
 * in that order. There is no "next pass" to leave the rest to — `confirmed`
 * becomes this document as soon as the push succeeds.
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
      // ⚠ AND the rest of the furniture. The create builds ONE section —
      // the first — and only from its column count and its two defaults,
      // because that is all the create body carries (`push.ts`). A pasted or
      // undo-restored case with a hutch, ragged columns or per-shelf depths
      // needs everything else asked for explicitly, and a review measured
      // what happens when it is not: the case is created uniform, `confirmed`
      // records the loss as LANDED, and it is never diffed again.
      ops.push(...sectionOps(asDrawn(bookcase), bookcase))
      continue
    }
    if (!sameCase(had, bookcase))
      ops.push({
        kind: 'case.edit',
        bookcase,
        roomChanged: had.roomId !== bookcase.roomId,
      })
    ops.push(...sectionOps(had.sections, bookcase))
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

/**
 * The section calls for one bookcase, given what the server holds for it.
 *
 * ⚠ **What the server holds is TRACKED, not guessed.** `POST /map/sections`
 * states no shape at all — it copies the section it stands against
 * (`next_section`, `app/domain/place.py`) — so the corrections a new section
 * needs depend on the ops issued before it in this same pass. The list below
 * is the server's own, bottom→top, advanced as each op lands. A section
 * removed in this pass stays in it on purpose: removals are issued LAST, so
 * it is still there to be copied.
 */
function sectionOps(live: Section[], after: Bookcase): Op[] {
  const ops: Op[] = []
  const standing = live.slice()
  after.sections.forEach((section, i) => {
    let had = standing.find((s) => s.id === section.id)
    if (!had) {
      // What it stands ON, in the document — and therefore on the server,
      // since the sections below it are dealt with first. Null is the floor,
      // and then the server copies whatever is standing there.
      const below = i > 0
        ? standing.find((s) => s.id === after.sections[i - 1]!.id)
        : undefined
      ops.push({
        kind: 'section.add', caseId: after.id, section,
        aboveId: below?.id ?? null,
      })
      had = asCreated(section.id, below ?? (i === 0 ? standing[0] : undefined))
      standing.splice(
        below ? standing.findIndex((s) => s.id === below.id) + 1 : 0, 0, had)
    }
    ops.push(...shapeOps(had, section))
    // Everything above lands before the next section is added, so by now the
    // server holds exactly what the document says — which is what makes the
    // neighbour a later `section.add` copies knowable at all.
    standing[standing.findIndex((s) => s.id === section.id)] = section
  })
  return ops
}

/** The calls that turn `had` — the section as the server has it — into
 *  `section`. */
function shapeOps(had: Section, section: Section): Op[] {
  const ops: Op[] = []
  if (had.defaultLevels !== section.defaultLevels ||
      had.defaultDepth !== section.defaultDepth)
    ops.push({ kind: 'section.defaults', section })
  // ⚠ One grid instruction per REQUEST — never "one per pass". The API
  // answers 400 for `columns` and `column`/`levels` in one body, and the
  // previous shape left the per-column heights *"to the next pass, which
  // converges"*: there is no next pass, because `confirmed` becomes this
  // document the moment the push succeeds. Two requests, one instruction
  // each, in this order.
  let heights = had.columnLevels
  if (columnCount(had) !== columnCount(section)) {
    ops.push({ kind: 'section.columns', section, columns: columnCount(section) })
    // What a count change LEAVES behind: the columns that were there keep
    // their heights and new trailing ones arrive at the section's default
    // (`with_column_count`) — which the defaults op above has just set.
    heights = Array.from({ length: columnCount(section) },
      (_, col) => had.columnLevels[col] ?? section.defaultLevels)
  }
  section.columnLevels.forEach((levels, col) => {
    if (heights[col] !== levels)
      ops.push({ kind: 'section.levels', section, col, levels })
  })
  // ⚠ AFTER the grid ops, and split by direction. After, because a cell has
  // to exist before it can be switched off — the server refuses a gap outside
  // the extent with a 400. Split, because the route takes one instruction
  // with a sign, and because the two are not each other's undo in a single
  // request: gapping cannot be sent alongside restoring and still be read.
  const key = (c: GapCell) => `${c.col}:${c.level}`
  const before = new Set(had.gaps.map(key))
  const after = new Set(section.gaps.map(key))
  const opened = section.gaps.filter((g) => !before.has(key(g)))
  const closed = had.gaps.filter((g) => !after.has(key(g)) && inExtent(section, g))
  if (opened.length > 0)
    ops.push({ kind: 'section.gaps', section, cells: opened, gap: true })
  if (closed.length > 0)
    ops.push({ kind: 'section.gaps', section, cells: closed, gap: false })
  for (const shelf of section.shelves) {
    const stood = had.shelves.find(
      (s) => s.col === shelf.col && s.level === shelf.level)
    // A slot the grid ops above just created arrives at the section's own
    // default depth; one that was already standing keeps whatever it had.
    // Comparing only against slots that already existed is how a pasted
    // case's per-shelf overrides went missing.
    const depth = stood ? stood.depth : section.defaultDepth
    if (depth !== shelf.depth)
      ops.push({
        kind: 'shelf.depth', section, col: shelf.col,
        level: shelf.level, depth: shelf.depth,
      })
  }
  return ops
}

/** A section built to a stated shape, with the shelves it implies. The
 *  client's `withColumnCount` and the server's `with_column_count` are the
 *  same arithmetic, so this is a prediction only in name. */
const built = (id: string, columns: number, levels: number, depth: number): Section =>
  withColumnCount(
    { id, columnLevels: [], gaps: [], defaultLevels: levels, defaultDepth: depth,
      shelves: [] },
    Math.max(1, columns),
  )

/** A section as `POST /map/sections` will create it: shaped like the one it
 *  stands against, or one column of the defaults when there is none. */
const asCreated = (id: string, neighbour: Section | undefined): Section =>
  built(
    id,
    neighbour ? columnCount(neighbour) : 1,
    neighbour?.defaultLevels ?? DEFAULT_LEVELS,
    neighbour?.defaultDepth ?? DEFAULT_DEPTH,
  )

/** What `POST /map/bookcases` will have created: the FIRST section only,
 *  uniform, from the column count and the two defaults `push.ts` sends. */
const asDrawn = (bc: Bookcase): Section[] => {
  const first = bc.sections[0]
  return first
    ? [built(first.id, columnCount(first), first.defaultLevels, first.defaultDepth)]
    : []
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
