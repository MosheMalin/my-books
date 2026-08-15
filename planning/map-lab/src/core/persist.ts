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
 */

import type { Bookcase, Plan, Room, Section, Shelf } from './model'
import { DEFAULT_DEPTH, DEFAULT_LEVELS, emptyPlan } from './model'
import type { Rect, Side } from './rect'
import { integral } from './rect'

export const FORMAT = 'booksnap.map-lab.plan'
/** 3: bookcases hold SECTIONS. A v2 case — `columnLevels`/`shelves` directly
 *  on the bookcase — is read as a single section, because the owner has a real
 *  drawing in a real browser and losing it to a lab refactor would be exactly
 *  the "work will not get lost" failure this file exists to prevent. */
export const FORMAT_VERSION = 3

export type PlanFile = {
  format: typeof FORMAT
  version: number
  plan: Plan
}

export function serializePlan(plan: Plan): string {
  const file: PlanFile = {
    format: FORMAT,
    version: FORMAT_VERSION,
    plan: { ...plan, underlay: null },
  }
  return JSON.stringify(file, null, 2)
}

export type ParseResult = { ok: true; plan: Plan } | { ok: false; error: string }

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

  const rooms = asArray(body['rooms']).map(readRoom).filter(isPresent)
  const cases = asArray(body['cases']).map(readCase).filter(isPresent)
  if (rooms.length === 0 && cases.length === 0) {
    // A v1 file (polygon rooms, baseline bookcases) lands here rather than
    // half-importing. The lab is pre-product; there is no migration to owe.
    return { ok: false, error: 'the file describes nothing this version understands' }
  }
  return { ok: true, plan: { ...emptyPlan(), rooms, cases } }
}

// --- readers ---------------------------------------------------------------

function readRoom(v: unknown): Room | null {
  if (!isRecord(v)) return null
  const rect = readRect(v['rect'])
  if (!rect) return null
  return { id: str(v['id'], 'room'), name: str(v['name'], ''), rect }
}

function readCase(v: unknown): Bookcase | null {
  if (!isRecord(v)) return null
  const rect = readRect(v['rect'])
  if (!rect) return null
  const id = str(v['id'], 'case')
  const roomId = v['roomId']
  const sections = readSections(v, id)
  if (sections.length === 0) return null
  return {
    id,
    name: str(v['name'], ''),
    rect,
    front: readSide(v['front']),
    roomId: typeof roomId === 'string' ? roomId : null,
    sections,
  }
}

/**
 * v3 sections if present; otherwise the v2 shape, read as one section.
 *
 * Section ids are REBUILT as `<caseId>:s<n>` rather than trusted from the
 * file: `nextSectionId` derives the next number from that pattern, so a file
 * carrying ids in any other shape would hand out a colliding id on the first
 * *add a section*. They are internal handles — nothing outside the document
 * refers to one.
 */
function readSections(v: Record<string, unknown>, caseId: string): Section[] {
  const listed = asArray(v['sections']).map(readSection).filter(isPresent)
  const sections = listed.length > 0 ? listed : [readSection(v)].filter(isPresent)
  return sections.map((s, i) => ({ ...s, id: `${caseId}:s${i + 1}` }))
}

function readSection(v: unknown): Section | null {
  if (!isRecord(v)) return null
  const columnLevels = asArray(v['columnLevels'])
    .map((n) => num(n, 1))
    .map((n) => Math.max(1, Math.round(n)))
  if (columnLevels.length === 0) return null
  return {
    id: '', // assigned by readSections
    columnLevels,
    defaultLevels: Math.max(1, Math.round(num(v['defaultLevels'], DEFAULT_LEVELS))),
    defaultDepth: Math.max(1, Math.round(num(v['defaultDepth'], DEFAULT_DEPTH))),
    shelves: asArray(v['shelves']).map(readShelf).filter(isPresent),
  }
}

function readShelf(v: unknown): Shelf | null {
  if (!isRecord(v)) return null
  return {
    col: Math.max(0, Math.round(num(v['col'], 0))),
    level: Math.max(0, Math.round(num(v['level'], 0))),
    depth: Math.max(1, Math.round(num(v['depth'], 1))),
    photos: Math.max(0, Math.round(num(v['photos'], 0))),
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
