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

import { Elevation } from './Elevation'
import type { Doc, Selection } from './types'
import { count, only } from './types'
import type { Bookcase, Plan, Room } from '../core/model'
import {
  MAX_DEPTH,
  caseLength,
  caseThickness,
  columnCount,
  shelfAt,
  shelvesDifferingFromDefaultDepth,
  shelvesInColumns,
} from '../core/model'

const SIDE_NAME = { N: 'up', S: 'down', E: 'right', W: 'left' } as const

export type Actions = {
  renameRoom: (id: string, name: string) => void
  resizeRoom: (id: string, w: number, h: number) => void
  renameCase: (id: string, name: string) => void
  resizeCase: (id: string, w: number, h: number) => void
  setCaseRoom: (id: string, roomId: string | null) => void
  turnCase: (id: string) => void
  setColumnCount: (id: string, n: number) => void
  setColumnLevels: (id: string, col: number, n: number) => void
  setDefaultLevels: (id: string, n: number) => void
  applyDefaultLevels: (id: string) => void
  setDefaultDepth: (id: string, n: number) => void
  applyDefaultDepth: (id: string) => void
  setShelfDepth: (id: string, col: number, level: number, n: number) => void
  setShelfPhotos: (id: string, col: number, level: number, n: number) => void
  deleteSelection: () => void
  copySelection: () => void
  paste: () => void
  select: (s: Selection) => void
}

const isRoom = (o: Room | Bookcase): o is Room => !('front' in o)

export function Inspector({
  doc,
  selection,
  actions,
}: {
  doc: Doc
  selection: Selection
  actions: Actions
}) {
  const { plan } = doc
  const n = count(selection)

  if (n === 0) return <Empty plan={plan} />
  if (n > 1) return <Many plan={plan} selection={selection} actions={actions} />

  const one = only(selection, plan)
  if (!one) return <Empty plan={plan} />
  return isRoom(one) ? (
    <RoomPanel room={one} plan={plan} actions={actions} />
  ) : (
    <CasePanel bc={one} plan={plan} selection={selection} actions={actions} />
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

function RoomPanel({ room, plan, actions }: { room: Room; plan: Plan; actions: Actions }) {
  const attached = plan.cases.filter((c) => c.roomId === room.id)
  return (
    <div className="inspector">
      <h2>Room</h2>
      <label className="field">
        <span>Name</span>
        <input
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
  selection,
  actions,
}: {
  bc: Bookcase
  plan: Plan
  selection: Selection
  actions: Actions
}) {
  const room = plan.rooms.find((r) => r.id === bc.roomId) ?? null
  return (
    <div className="inspector">
      <h2>Bookcase</h2>
      <label className="field">
        <span>Name</span>
        <input
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
          {plan.rooms.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name || `room ${r.rect.w}×${r.rect.h}`}
            </option>
          ))}
        </select>
      </label>

      <div className="field inline">
        <span>Books face</span>
        <button type="button" onClick={() => actions.turnCase(bc.id)} aria-label="turn the bookcase">
          {SIDE_NAME[bc.front]} ⟳ turn
        </button>
      </div>

      <p className="note">
        <strong>{caseLength(bc)} units</strong> of wall, {caseThickness(bc)} deep as drawn
        {room ? ` · in ${room.name || 'an unnamed room'}` : ' · attached to no room'} ·{' '}
        {bc.shelves.length} shelves.
        <br />
        Free measurement — relative to this room's walls, never centimetres, and
        nothing here infers how many books fit.
      </p>

      <Elevation
        bc={bc}
        selection={selection}
        onSelectShelf={(col, level) =>
          actions.select({ rooms: [], cases: [bc.id], shelf: { caseId: bc.id, col, level } })
        }
        onColumnLevels={(col, n) => actions.setColumnLevels(bc.id, col, n)}
        onColumnCount={(n) => {
          if (n < columnCount(bc)) {
            const losing = shelvesInColumns(bc, n)
            if (losing > 0 && !confirm(`Remove the last column and its ${losing} shelves?`)) return
          }
          actions.setColumnCount(bc.id, n)
        }}
      />

      <Defaults bc={bc} actions={actions} />
      <ShelfPanel bc={bc} selection={selection} actions={actions} />

      <button type="button" className="danger" onClick={actions.deleteSelection}>
        Delete this bookcase
      </button>
    </div>
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

function Defaults({ bc, actions }: { bc: Bookcase; actions: Actions }) {
  const differing = shelvesDifferingFromDefaultDepth(bc)
  return (
    <fieldset className="defaults">
      <legend>Defaults for NEW shelves</legend>

      <label className="field inline">
        <span>Levels per column</span>
        <input
          type="number"
          min={1}
          max={12}
          value={bc.defaultLevels}
          aria-label="default levels per column"
          onChange={(e) => actions.setDefaultLevels(bc.id, Number(e.target.value))}
        />
      </label>
      <button type="button" onClick={() => actions.applyDefaultLevels(bc.id)}>
        Apply to every existing column
      </button>

      <label className="field inline">
        <span>Depth (rows front-to-back)</span>
        <input
          type="number"
          min={1}
          max={MAX_DEPTH}
          value={bc.defaultDepth}
          aria-label="default depth"
          onChange={(e) => actions.setDefaultDepth(bc.id, Number(e.target.value))}
        />
      </label>

      {differing > 0 ? (
        <p className="rule">
          <strong>{differing}</strong> existing{' '}
          {differing === 1 ? 'shelf keeps its own depth' : 'shelves keep their own depth'}.
          Changing the default never reaches back into them — that would delete
          the location of every book standing in a back row.
          <button type="button" onClick={() => actions.applyDefaultDepth(bc.id)}>
            Apply the default to all {bc.shelves.length} shelves
          </button>
        </p>
      ) : (
        <p className="note">Every existing shelf currently matches this default.</p>
      )}
    </fieldset>
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
  const shelf = shelfAt(bc, sel.col, sel.level)
  if (!shelf) return null
  return (
    <fieldset className="shelf-panel">
      <legend>
        Shelf · col {shelf.col + 1} · level {shelf.level + 1}
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
            actions.setShelfDepth(bc.id, shelf.col, shelf.level, Number(e.target.value))
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
            actions.setShelfPhotos(bc.id, shelf.col, shelf.level, Number(e.target.value))
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
