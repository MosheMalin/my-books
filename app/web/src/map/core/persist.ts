/**
 * Serialization — pure, and defensive on the way IN.
 *
 * The lab's export is how the owner hands a real drawing over ("here is my
 * house"), so the format is the interesting artefact, not the localStorage
 * convenience. It is integers in abstract units, with no pixel, no viewport
 * and no centimetre anywhere in it (MAP_PLAN §3.4).
 *
 * The underlay is NOT exported: a tracing image is scaffolding, and its `src`
 * is an object URL that means nothing in another session.
 *
 * ⚠ **It is live again as of P6.7e**, and the condition the old note set is
 * the thing that changed. That note said: `parsePlan` REBUILDS section ids
 * from array position, on the stated grounds that nothing outside the
 * document refers to one — which stopped being true the moment
 * `shelves.section_id` existed, and an import that re-mints ids re-addresses
 * every shelf in the file. So **version 5 carries identity**, and the
 * positional rebuild survives only for the older shapes, where the ids in the
 * file really were positional and trusting them would be worse.
 *
 * ⚠ What the file carries is the DRAWING plus the two ids that make it
 * restorable over this library — not the catalogue. Shelf labels, book counts
 * and photo counts stay out: they are the library's facts, and a file that
 * carried them would claim a shelf holds books it has never seen. The thing
 * that backs up a library is `tools/backup.py`.
 *
 * The owner settled the purpose on 2026-08-30: *a backup of THIS library*, so
 * that importing restores the same drawing and every book stays on the shelf
 * it was on. That is what the ids are for, and it is the whole reason this
 * format gained a version.
 */

import type { Bookcase, Floor, Plan, Room, Section, Shelf } from './model'
import { DEFAULT_DEPTH, DEFAULT_LEVELS, GROUND_FLOOR, emptyPlan, inExtent } from './model'
import type { Rect, Side } from './rect'
import { integral } from './rect'

export const FORMAT = 'booksnap.map-lab.plan'
/**
 * 3: bookcases hold SECTIONS — a v2 case (`columnLevels`/`shelves` directly on
 *    the bookcase) is read as a single section.
 * 4: plans hold FLOORS — a file without them gets one, and everything in it
 *    lands on that floor.
 * 5: sections and shelves carry their IDS, and the file says which library and
 *    which site it was taken from. Everything below 5 had positional section
 *    ids, so those are still rebuilt — reading them would re-address every
 *    shelf in the file, which is precisely the hazard this version exists to
 *    remove.
 *
 * Older shapes are read rather than refused because the owner keeps a real
 * drawing in a real browser, and losing it to a lab refactor would be exactly
 * the "work will not get lost" failure this file exists to prevent.
 */
export const FORMAT_VERSION = 5

/** Which drawing this is, so a restore can refuse to be pointed at another
 *  one. Absent in every file written before version 5. */
export type PlanOrigin = {
  /** The library the drawing belongs to. */
  library: string
  /** The SITE it is of. `toPlan` builds one site at a time, so a file is one
   *  site's drawing and restoring it into a different one is nonsense. */
  siteId: string
  /** Only so a person can tell two files apart in a downloads folder. Never
   *  matched on — a site may be renamed between the save and the restore. */
  siteName: string
  /** When it was written, ISO-8601. Provenance for a human, never a rule. */
  savedAt: string
}

export type PlanFile = {
  format: typeof FORMAT
  version: number
  origin?: PlanOrigin
  plan: Plan
}

export function serializePlan(plan: Plan, origin?: PlanOrigin): string {
  const file: PlanFile = {
    format: FORMAT,
    version: FORMAT_VERSION,
    ...(origin ? { origin } : {}),
    plan: { ...plan, underlay: null, cases: plan.cases.map(forExport) },
  }
  return JSON.stringify(file, null, 2)
}

/** What a saved file is called. Dated, so two saves of one site sort. */
export function planFilename(siteName: string, savedAt: string): string {
  const day = savedAt.slice(0, 10)
  // Every character Windows refuses in a filename, plus whitespace. A site is
  // named by a person, in Hebrew, with spaces in it.
  const site = siteName.trim().replace(/[\\/:*?"<>|\s]+/g, '-') || 'map'
  return `booksnap-${site}-${day}.json`
}

/**
 * A bookcase as version 5 writes it.
 *
 * ⚠ The ids STAY, and that is the change P6.7e is. Everything else the
 * server owns goes: a shelf's NAME, whether the slot is free, and the two
 * counts. The old rule — *a plan file is a drawing, not an export of the
 * catalogue* — is unchanged and is why they go; an id is not a catalogue
 * fact, it is the handle without which a restore re-addresses every shelf in
 * the file.
 *
 * ⚠ The counts are ZEROED rather than deleted, because `Shelf` requires
 * them. `readShelf` forces `books: 0` on the way in for the same reason it
 * always has: what stands on a slot is the library's fact, and a file that
 * claimed otherwise would say a shelf holds books it has never seen.
 */
const forExport = (bc: Bookcase): Bookcase => ({
  ...bc,
  sections: bc.sections.map((s) => ({
    ...s,
    shelves: s.shelves.map(
      ({ label: _label, free: _free, ...cell }) => ({
        ...cell, books: 0, photos: 0,
      })),
  })),
})

export type ParseResult =
  | { ok: true; plan: Plan; origin: PlanOrigin | null }
  | { ok: false; error: string }

export function parsePlan(text: string): ParseResult {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return { ok: false, error: 'not JSON' }
  }
  if (!isRecord(raw)) return { ok: false, error: 'not an object' }
  if (raw['format'] !== FORMAT) return { ok: false, error: 'not a map-lab plan' }
  const body = raw['plan']
  if (!isRecord(body)) return { ok: false, error: 'no plan' }
  // ⚠ The version decides whether the ids in this file MEAN anything. Below
  // 5 they were rebuilt from array position on every write, so trusting them
  // would bind shelves to sections that never held them.
  const carriesIds = num(raw['version'], 0) >= 5

  const floors = readFloors(body)
  const home = floors[0]!.id
  const known = new Set(floors.map((f) => f.id))
  const onKnownFloor = (id: string) => (known.has(id) ? id : home)

  const rooms = asArray(body['rooms'])
    .map(readRoom)
    .filter(isPresent)
    .map((r) => ({ ...r, floorId: onKnownFloor(r.floorId) }))
  const cases = asArray(body['cases'])
    .map((c) => readCase(c, carriesIds))
    .filter(isPresent)
    .map((c) => ({ ...c, floorId: onKnownFloor(c.floorId) }))
  if (rooms.length === 0 && cases.length === 0) {
    // A v1 file (polygon rooms, baseline bookcases) lands here rather than
    // half-importing. The lab is pre-product; there is no migration to owe.
    return { ok: false, error: 'the file describes nothing this version understands' }
  }
  return { ok: true, plan: { ...emptyPlan(), floors, rooms, cases },
           origin: readOrigin(raw['origin']) }
}

/** Where this file came from, when it says. Null for every file written
 *  before version 5 — absent, which is not the same as unknown-and-wrong:
 *  the caller decides what to do with a file that cannot name its site. */
function readOrigin(v: unknown): PlanOrigin | null {
  if (!isRecord(v)) return null
  const library = str(v['library'], '')
  const siteId = str(v['siteId'], '')
  if (!library || !siteId) return null
  return {
    library,
    siteId,
    siteName: str(v['siteName'], ''),
    savedAt: str(v['savedAt'], ''),
  }
}

// --- readers ---------------------------------------------------------------

/** At least one floor, always — a plan with none would make every room
 *  homeless and every screen handle a case that cannot happen. */
function readFloors(body: Record<string, unknown>): Floor[] {
  const listed = asArray(body['floors'])
    .map((f, i) =>
      isRecord(f) ? { id: str(f['id'], `f${i + 1}`), name: str(f['name'], `Floor ${i + 1}`) } : null,
    )
    .filter(isPresent)
  return listed.length > 0 ? listed : [GROUND_FLOOR]
}

function readRoom(v: unknown): Room | null {
  if (!isRecord(v)) return null
  const rect = readRect(v['rect'])
  if (!rect) return null
  return {
    id: str(v['id'], 'room'),
    name: str(v['name'], ''),
    rect,
    floorId: str(v['floorId'], GROUND_FLOOR.id),
  }
}

function readCase(v: unknown, carriesIds: boolean): Bookcase | null {
  if (!isRecord(v)) return null
  const rect = readRect(v['rect'])
  if (!rect) return null
  const id = str(v['id'], 'case')
  const roomId = v['roomId']
  const sections = readSections(v, id, carriesIds)
  if (sections.length === 0) return null
  return {
    id,
    name: str(v['name'], ''),
    rect,
    front: readSide(v['front']),
    roomId: typeof roomId === 'string' ? roomId : null,
    floorId: str(v['floorId'], GROUND_FLOOR.id),
    sections,
  }
}

/**
 * v3 sections if present; otherwise the v2 shape, read as one section.
 *
 * ⚠ **From version 5 the id in the file is KEPT.** The old note here said
 * they are internal handles that nothing outside the document refers to — a
 * sentence `shelves.section_id` made false, and `place.py`'s `Section`
 * docstring records the same trap from the other side. Rebuilding them
 * positionally re-addresses every shelf in the file.
 *
 * ⚠ Below version 5 they are still rebuilt, because there the ids WERE
 * positional: every export wrote `<caseId>:s<n>` afresh, so what is in an old
 * file is a position wearing an id's clothes.
 *
 * ⚠ A server id does not match `<caseId>:s<n>`, which `nextSectionId` parses
 * to number the next section. That is not new and not a hazard: the LIVE
 * editor has held uuid section ids from `toPlan` since P6.3, and the fallback
 * `:s1` cannot collide twice — once one locally-minted id exists it matches
 * the pattern and the counter moves.
 */
function readSections(v: Record<string, unknown>, caseId: string,
                      carriesIds: boolean): Section[] {
  const listed = asArray(v['sections'])
    .map((x) => readSection(x, carriesIds)).filter(isPresent)
  const sections = listed.length > 0
    ? listed : [readSection(v, carriesIds)].filter(isPresent)
  return sections.map((s, i) => ({
    ...s, id: carriesIds && s.id ? s.id : `${caseId}:s${i + 1}`,
  }))
}

function readSection(v: unknown, carriesIds: boolean): Section | null {
  if (!isRecord(v)) return null
  const columnLevels = asArray(v['columnLevels'])
    .map((n) => num(n, 1))
    .map((n) => Math.max(1, Math.round(n)))
  if (columnLevels.length === 0) return null
  // ⚠ The mask is READ, not defaulted away (P6.3.2b). A file's gaps are cells
  // the owner switched off; dropping them on import would silently fill the
  // television's space with shelves, and `serializePlan` writes the whole section,
  // so an import that forgot them would lose them on the next export too.
  // Out-of-extent cells are dropped, exactly as `withGaps` and the server do.
  const gaps = asArray(v['gaps'])
    .map((g) => (isRecord(g)
      ? { col: Math.round(num(g['col'], -1)), level: Math.round(num(g['level'], -1)) }
      : { col: -1, level: -1 }))
    .filter((g) => inExtent({ columnLevels } as Section, g))
  const gapped = new Set(gaps.map((g) => `${g.col}:${g.level}`))
  return {
    // Kept from a v5 file; '' means `readSections` assigns a positional one.
    id: carriesIds ? str(v['id'], '') : '',
    columnLevels,
    gaps,
    defaultLevels: Math.max(1, Math.round(num(v['defaultLevels'], DEFAULT_LEVELS))),
    defaultDepth: Math.max(1, Math.round(num(v['defaultDepth'], DEFAULT_DEPTH))),
    // A gapped cell holds no shelf, so a file listing both loses the shelf —
    // the same precedence `toPlan` applies to the server's answer.
    shelves: asArray(v['shelves']).map((x) => readShelf(x, carriesIds))
      .filter(isPresent)
      .filter((s) => !gapped.has(`${s.col}:${s.level}`)),
  }
}

function readShelf(v: unknown, carriesIds: boolean): Shelf | null {
  if (!isRecord(v)) return null
  // ⚠ The shelf's own id, from version 5 on. This is the half that keeps a
  // restore from moving books: a slot with no id is a slot the restore has to
  // mint a new shelf for, and the books that stood there would be left on a
  // row nothing points at.
  const id = carriesIds ? str(v['id'], '') : ''
  return {
    ...(id ? { id } : {}),
    col: Math.max(0, Math.round(num(v['col'], 0))),
    level: Math.max(0, Math.round(num(v['level'], 0))),
    depth: Math.max(1, Math.round(num(v['depth'], 1))),
    photos: Math.max(0, Math.round(num(v['photos'], 0))),
    // ⚠ NOT read from the file. What stands on a slot is the library's fact,
    // not the drawing's — an import that carried its own count would claim a
    // shelf holds books it has never seen. A loaded plan learns it from the
    // server on the next read.
    books: 0,
  }
}

function readRect(v: unknown): Rect | null {
  if (!isRecord(v)) return null
  const x = num(v['x'], NaN)
  const y = num(v['y'], NaN)
  const w = num(v['w'], NaN)
  const h = num(v['h'], NaN)
  if ([x, y, w, h].some((n) => !Number.isFinite(n))) return null
  if (w <= 0 || h <= 0) return null
  // Whole units on the way in too: a file written before `integral` existed
  // carries float dust, and importing it would seed the magnet with it again.
  return integral({ x, y, w, h })
}

function readSide(v: unknown): Side {
  return v === 'N' || v === 'S' || v === 'E' || v === 'W' ? v : 'S'
}

// --- primitives ------------------------------------------------------------

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const asArray = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])

const isPresent = <T>(v: T | null): v is T => v !== null

const str = (v: unknown, fallback: string): string =>
  typeof v === 'string' && v.length > 0 ? v : fallback

const num = (v: unknown, fallback: number): number =>
  typeof v === 'number' && Number.isFinite(v) ? v : fallback
