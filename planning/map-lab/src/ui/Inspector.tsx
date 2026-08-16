/**
 * The properties panel — "edit their settings" (owner, 2026-08-16).
 *
 * Size is editable BOTH ways: drag the handles on the plan, or type the
 * numbers here. Dragging is faster and typing is exact, and a free-measurement
 * plan needs both — the units are relative, so the only thing that matters is
 * that this case is twice the width of that one.
 *
 * It is also where MAP_PLAN §3.3 becomes visible rather than merely true: the
 * case's depth is a DEFAULT, and when existing shelves disagree with it the
 * panel says how many and offers to apply — it never applies silently.
 */

import { useEffect, useRef } from 'react'

import { Elevation } from './Elevation'
import type { Doc, Selection } from './types'
import { count, only } from './types'
import { useSticky } from './useSticky'
import type { Bookcase, Plan, Room } from '../core/model'
import {
  MAX_DEPTH,
  allShelves,
  caseLength,
  caseThickness,
  sectionById,
  sectionIndex,
  shelfAt,
} from '../core/model'

const SIDE_NAME = { N: 'up', S: 'down', E: 'right', W: 'left' } as const

export type Actions = {
  renameRoom: (id: string, name: string) => void
  resizeRoom: (id: string, w: number, h: number) => void
  renameCase: (id: string, name: string) => void
  resizeCase: (id: string, w: number, h: number) => void
  setCaseRoom: (id: string, roomId: string | null) => void
  turnCase: (id: string) => void
  setColumnCount: (id: string, sectionId: string, n: number) => void
  setColumnLevels: (id: string, sectionId: string, col: number, n: number) => void
  setDefaultLevels: (id: string, sectionId: string, n: number) => void
  applyDefaultLevels: (id: string, sectionId: string) => void
  setDefaultDepth: (id: string, sectionId: string, n: number) => void
  applyDefaultDepth: (id: string, sectionId: string) => void
  setShelfDepth: (id: string, sectionId: string, col: number, level: number, n: number) => void
  setShelfPhotos: (id: string, sectionId: string, col: number, level: number, n: number) => void
  addSection: (id: string, where: 'top' | 'bottom') => void
  removeSection: (id: string, sectionId: string) => void
  deleteSelection: () => void
  copySelection: () => void
  paste: () => void
  select: (s: Selection) => void
}

const isRoom = (o: Room | Bookcase): o is Room => !('front' in o)

export type Renaming = { kind: 'room' | 'case'; id: string } | null

export function Inspector({
  doc,
  floorId,
  selection,
  actions,
  renaming,
  onRenamed,
}: {
  doc: Doc
  floorId: string
  selection: Selection
  actions: Actions
  renaming: Renaming
  onRenamed: () => void
}) {
  const { plan } = doc
  const n = count(selection)

  if (n === 0) return <Empty plan={plan} />
  if (n > 1) return <Many plan={plan} selection={selection} actions={actions} />

  const one = only(selection, plan)
  if (!one) return <Empty plan={plan} />
  return isRoom(one) ? (
    <RoomPanel room={one} plan={plan} actions={actions} renaming={renaming} onRenamed={onRenamed} />
  ) : (
    <CasePanel
      bc={one}
      plan={plan}
      floorId={floorId}
      selection={selection}
      actions={actions}
      renaming={renaming}
      onRenamed={onRenamed}
    />
  )
}

// --- many ------------------------------------------------------------------

function Many({
  plan,
  selection,
  actions,
}: {
  plan: Plan
  selection: Selection
  actions: Actions
}) {
  const rooms = plan.rooms.filter((r) => selection.rooms.includes(r.id))
  const cases = plan.cases.filter((c) => selection.cases.includes(c.id))
  const carried = plan.cases.filter(
    (c) => c.roomId && selection.rooms.includes(c.roomId) && !selection.cases.includes(c.id),
  )
  return (
    <div className="inspector">
      <h2>{count(selection)} selected</h2>
      <p className="note">
        {rooms.length} room{rooms.length === 1 ? '' : 's'} · {cases.length} bookcase
        {cases.length === 1 ? '' : 's'}. Drag any of them and they all move.
        {carried.length > 0 && (
          <>
            {' '}
            <strong>{carried.length}</strong> more bookcase
            {carried.length === 1 ? '' : 's'} will travel along, attached to the
            selected rooms.
          </>
        )}
      </p>
      <ul className="picked">
        {rooms.map((r) => (
          <li key={r.id} className="rtl-safe">
            {r.name || `room ${r.rect.w}×${r.rect.h}`}
          </li>
        ))}
        {cases.map((c) => (
          <li key={c.id} className="rtl-safe">
            {c.name || `bookcase ${c.rect.w}×${c.rect.h}`}
          </li>
        ))}
      </ul>
      <div className="row">
        <button type="button" onClick={actions.copySelection}>
          Copy
        </button>
        <button type="button" onClick={actions.paste}>
          Paste
        </button>
      </div>
      <button type="button" className="danger" onClick={actions.deleteSelection}>
        Delete all {count(selection)}
      </button>
      <p className="note">
        Deleting a room never deletes its bookcases — they stay where they stand
        and belong to no room.
      </p>
    </div>
  )
}

// --- room ------------------------------------------------------------------

/**
 * Puts the caret in a name box when the plan asks for it — that is what a
 * double-click on a room means (owner, 2026-08-16). One editor rather than an
 * on-canvas second one: two places to type a name is two places for it to
 * disagree with itself.
 */
function useRenameFocus(active: boolean, done: () => void) {
  const ref = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    if (!active) return
    ref.current?.focus()
    ref.current?.select()
    done()
  }, [active, done])
  return ref
}

function RoomPanel({
  room,
  plan,
  actions,
  renaming,
  onRenamed,
}: {
  room: Room
  plan: Plan
  actions: Actions
  renaming: Renaming
  onRenamed: () => void
}) {
  const nameRef = useRenameFocus(renaming?.kind === 'room' && renaming.id === room.id, onRenamed)
  const attached = plan.cases.filter((c) => c.roomId === room.id)
  return (
    <div className="inspector">
      <h2>Room</h2>
      <label className="field">
        <span>Name</span>
        <input
          ref={nameRef}
          className="rtl-safe"
          value={room.name}
          placeholder="סלון · living room"
          onChange={(e) => actions.renameRoom(room.id, e.target.value)}
        />
      </label>
      <Size
        w={room.rect.w}
        h={room.rect.h}
        labelW="room width"
        labelH="room height"
        onChange={(w, h) => actions.resizeRoom(room.id, w, h)}
      />

      <fieldset>
        <legend>Bookcases attached</legend>
        {attached.length === 0 ? (
          <p className="note">
            None yet. A bookcase drawn inside this room attaches to it
            automatically, and then moves with it.
          </p>
        ) : (
          <>
            <ul className="picked">
              {attached.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    className="link rtl-safe"
                    aria-label={`select the bookcase ${c.name || c.id}`}
                    onClick={() => actions.select({ rooms: [], cases: [c.id], shelf: null })}
                  >
                    {c.name || `bookcase ${c.rect.w}×${c.rect.h}`}
                  </button>
                </li>
              ))}
            </ul>
            <p className="note">
              These move when this room moves — including any that now stand
              outside its outline.
            </p>
          </>
        )}
      </fieldset>

      <button type="button" className="danger" onClick={actions.deleteSelection}>
        Delete this room
      </button>
    </div>
  )
}

// --- bookcase --------------------------------------------------------------

function CasePanel({
  bc,
  plan,
  floorId,
  selection,
  actions,
  renaming,
  onRenamed,
}: {
  bc: Bookcase
  plan: Plan
  floorId: string
  selection: Selection
  actions: Actions
  renaming: Renaming
  onRenamed: () => void
}) {
  const room = plan.rooms.find((r) => r.id === bc.roomId) ?? null
  const wanted = renaming?.kind === 'case' && renaming.id === bc.id
  const nameRef = useRenameFocus(wanted, onRenamed)
  return (
    <div className="inspector">
      <h2>Bookcase</h2>

      {/* Where the case IS collapses; what is ON it does not. The shelf editor
          is the part you come back to, and on a phone the panel is 38% of the
          screen — four fields above it push the grid off the bottom. */}
      <Fold
        storageKey="booksnap.map-lab.fold.caseDetails"
        forceOpen={wanted}
        label="Name, size, room, facing"
        summary={`${bc.name || 'unnamed'} · ${bc.rect.w}×${bc.rect.h} · faces ${SIDE_NAME[bc.front]}`}
      >
        <label className="field">
          <span>Name</span>
          <input
            ref={nameRef}
            className="rtl-safe"
            value={bc.name}
            placeholder="ארון הסלון"
            onChange={(e) => actions.renameCase(bc.id, e.target.value)}
          />
        </label>

        <Size
          w={bc.rect.w}
          h={bc.rect.h}
          labelW="bookcase width"
          labelH="bookcase height"
          onChange={(w, h) => actions.resizeCase(bc.id, w, h)}
        />

        <label className="field inline">
          <span>Moves with</span>
          <select
            className="rtl-safe"
            aria-label="the room this bookcase is attached to"
            value={bc.roomId ?? ''}
            onChange={(e) => actions.setCaseRoom(bc.id, e.target.value || null)}
          >
            <option value="">nothing — stands alone</option>
            {/* Only rooms on THIS storey: a bookcase cannot move with a room on
                another floor, and offering it would be offering a broken link. */}
            {plan.rooms
              .filter((r) => r.floorId === floorId)
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name || `room ${r.rect.w}×${r.rect.h}`}
                </option>
              ))}
          </select>
        </label>

        <div className="field inline">
          <span>Books face</span>
          <button
            type="button"
            onClick={() => actions.turnCase(bc.id)}
            aria-label="turn the bookcase"
          >
            {SIDE_NAME[bc.front]} ⟳ turn
          </button>
        </div>

        <p className="note">
          <strong>{caseLength(bc)} units</strong> of wall, {caseThickness(bc)} deep as drawn
          {room ? ` · in ${room.name || 'an unnamed room'}` : ' · attached to no room'} ·{' '}
          {allShelves(bc).length} shelves
          {bc.sections.length > 1 ? ` in ${bc.sections.length} sections` : ''}.
          <br />
          Free measurement — relative to this room's walls, never centimetres,
          and nothing here infers how many books fit.
        </p>
      </Fold>

      <Elevation
        bc={bc}
        selection={selection}
        onSelectShelf={(sectionId, col, level) =>
          actions.select({
            rooms: [],
            cases: [bc.id],
            shelf: { caseId: bc.id, sectionId, col, level },
          })
        }
        onColumnLevels={(sectionId, col, n) => actions.setColumnLevels(bc.id, sectionId, col, n)}
        onColumnCount={(sectionId, n) => actions.setColumnCount(bc.id, sectionId, n)}
        onDefaultLevels={(sectionId, n) => actions.setDefaultLevels(bc.id, sectionId, n)}
        onDefaultDepth={(sectionId, n) => actions.setDefaultDepth(bc.id, sectionId, n)}
        onApplyDefaultLevels={(sectionId) => actions.applyDefaultLevels(bc.id, sectionId)}
        onApplyDefaultDepth={(sectionId) => actions.applyDefaultDepth(bc.id, sectionId)}
        onAddSection={(where) => actions.addSection(bc.id, where)}
        onRemoveSection={(sectionId) => actions.removeSection(bc.id, sectionId)}
      />

      <ShelfPanel bc={bc} selection={selection} actions={actions} />

      <button type="button" className="danger" onClick={actions.deleteSelection}>
        Delete this bookcase
      </button>
    </div>
  )
}

/**
 * A collapsible block that says what it is hiding.
 *
 * The summary line is not decoration: a fold whose closed state reads only
 * "Details ▸" makes you open it to find out whether you needed it, which
 * costs more than it saved.
 */
function Fold({
  storageKey,
  label,
  summary,
  forceOpen,
  children,
}: {
  storageKey: string
  label: string
  summary: string
  forceOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useSticky(storageKey, true)
  // A rename that lands in a collapsed fold would put the caret somewhere
  // invisible, which reads as "double-click did nothing".
  useEffect(() => {
    if (forceOpen && !open) setOpen(true)
  }, [forceOpen, open, setOpen])
  return (
    <section className={open ? 'fold open' : 'fold'}>
      <button
        type="button"
        className="fold-head"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="fold-caret" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        <span className="fold-label">{label}</span>
        {!open && <span className="fold-summary rtl-safe">{summary}</span>}
      </button>
      {open && <div className="fold-body">{children}</div>}
    </section>
  )
}

function Size({
  w,
  h,
  labelW,
  labelH,
  onChange,
}: {
  w: number
  h: number
  labelW: string
  labelH: string
  onChange: (w: number, h: number) => void
}) {
  return (
    <div className="field inline size">
      <span>Size (units)</span>
      <span className="size-inputs">
        <input
          type="number"
          min={1}
          max={200}
          value={w}
          aria-label={labelW}
          onChange={(e) => onChange(Number(e.target.value), h)}
        />
        <span aria-hidden="true">×</span>
        <input
          type="number"
          min={1}
          max={200}
          value={h}
          aria-label={labelH}
          onChange={(e) => onChange(w, Number(e.target.value))}
        />
      </span>
    </div>
  )
}

function ShelfPanel({
  bc,
  selection,
  actions,
}: {
  bc: Bookcase
  selection: Selection
  actions: Actions
}) {
  const sel = selection.shelf
  if (!sel || sel.caseId !== bc.id) {
    return <p className="note">Pick a cell above to set one shelf's own depth.</p>
  }
  const sec = sectionById(bc, sel.sectionId)
  const shelf = sec ? shelfAt(sec, sel.col, sel.level) : null
  if (!sec || !shelf) return null
  // The address prints only what DISCRIMINATES: a one-section case never says
  // "section 1", because saying it would imply there is a section 2.
  const where =
    bc.sections.length > 1 ? `section ${sectionIndex(bc, sec.id) + 1} · ` : ''
  return (
    <fieldset className="shelf-panel">
      <legend>
        Shelf · {where}col {shelf.col + 1} · level {shelf.level + 1}
      </legend>
      <label className="field inline">
        <span>Its own depth</span>
        <input
          type="number"
          min={1}
          max={MAX_DEPTH}
          value={shelf.depth}
          aria-label="this shelf's depth"
          onChange={(e) =>
            actions.setShelfDepth(bc.id, sec.id, shelf.col, shelf.level, Number(e.target.value))
          }
        />
      </label>
      <label className="field inline">
        <span>Photos attached</span>
        <input
          type="number"
          min={0}
          max={20}
          value={shelf.photos}
          aria-label="photos attached to this shelf"
          onChange={(e) =>
            actions.setShelfPhotos(bc.id, sec.id, shelf.col, shelf.level, Number(e.target.value))
          }
        />
      </label>
      <p className="note">
        Many photos per shelf, each with its own depth, already exists in the
        product (<code>Capture&#123;shelf, depth, order&#125;</code>). The count
        here is a stand-in, so a half-catalogued case looks half-catalogued.
      </p>
    </fieldset>
  )
}


function Empty({ plan }: { plan: Plan }) {
  return (
    <div className="inspector">
      <h2>Nothing selected</h2>
      <p className="note">
        {plan.rooms.length} rooms · {plan.cases.length} bookcases.
      </p>
      <ol className="steps">
        <li>
          <strong>Draw room</strong> — drag a rectangle. Drag the next one near
          it and they attach edge to edge.
        </li>
        <li>
          <strong>Draw bookcase</strong> — drag a rectangle inside a room. It
          snaps flush to the wall, attaches to that room, and moves with it.
        </li>
        <li>
          <strong>Move &amp; edit</strong> — drag to move, drag a handle to
          resize, tap to edit here. Ctrl+click adds to the selection, and
          dragging empty space selects everything the band touches.
        </li>
      </ol>
    </div>
  )
}
