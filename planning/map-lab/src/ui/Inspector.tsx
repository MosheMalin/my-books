/**
 * The properties panel.
 *
 * It is also where MAP_PLAN §3.3 becomes visible rather than merely true: the
 * case's depth is a DEFAULT, and when existing shelves disagree with it the
 * panel says how many and offers to apply — it never applies silently.
 */

import { Elevation } from './Elevation'
import type { Doc, Selection } from './types'
import type { Bookcase } from '../core/model'
import {
  MAX_DEPTH,
  caseLength,
  columnCount,
  shelfAt,
  shelvesDifferingFromDefaultDepth,
  shelvesInColumns,
} from '../core/model'

export type Actions = {
  renameRoom: (id: string, name: string) => void
  deleteRoom: (id: string) => void
  renameCase: (id: string, name: string) => void
  deleteCase: (id: string) => void
  flipCase: (id: string) => void
  detachCase: (id: string) => void
  setColumnCount: (id: string, n: number) => void
  setColumnLevels: (id: string, col: number, n: number) => void
  setDefaultLevels: (id: string, n: number) => void
  applyDefaultLevels: (id: string) => void
  setDefaultDepth: (id: string, n: number) => void
  applyDefaultDepth: (id: string) => void
  setShelfDepth: (id: string, col: number, level: number, n: number) => void
  setShelfPhotos: (id: string, col: number, level: number, n: number) => void
  select: (s: Selection) => void
}

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

  if (selection?.kind === 'room') {
    const room = plan.rooms.find((r) => r.id === selection.id)
    if (!room) return <Empty plan={plan} />
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
        <p className="note">
          {room.points.length} walls · bookcases snap onto them as you drag.
        </p>
        <button type="button" className="danger" onClick={() => actions.deleteRoom(room.id)}>
          Delete this room
        </button>
      </div>
    )
  }

  const caseId =
    selection?.kind === 'case'
      ? selection.id
      : selection?.kind === 'shelf'
        ? selection.caseId
        : null
  const bc = caseId ? plan.cases.find((c) => c.id === caseId) ?? null : null
  if (!bc) return <Empty plan={plan} />

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

      <p className="note">
        <strong>{caseLength(bc)} units</strong> long
        {bc.attach ? ' · standing on a wall' : ' · free-standing island'} ·{' '}
        {bc.shelves.length} shelves
        <br />
        Free measurement — relative to this room's walls, never centimetres, and
        nothing here infers how many books fit.
      </p>

      <Elevation
        bc={bc}
        selection={selection}
        onSelectShelf={(col, level) => actions.select({ kind: 'shelf', caseId: bc.id, col, level })}
        onColumnLevels={(col, n) => actions.setColumnLevels(bc.id, col, n)}
        onColumnCount={(n) => {
          if (n < columnCount(bc)) {
            const losing = shelvesInColumns(bc, n)
            const keeping = shelvesInColumns(bc, columnCount(bc) - 1)
            if (losing > 0 && !confirm(`Remove the last column and its ${keeping} shelves?`)) return
          }
          actions.setColumnCount(bc.id, n)
        }}
      />

      <Defaults bc={bc} actions={actions} />
      <ShelfPanel bc={bc} selection={selection} actions={actions} />

      <div className="row">
        <button type="button" onClick={() => actions.flipCase(bc.id)}>
          Flip which way it faces
        </button>
        {bc.attach && (
          <button type="button" onClick={() => actions.detachCase(bc.id)}>
            Detach from the wall
          </button>
        )}
      </div>
      <button type="button" className="danger" onClick={() => actions.deleteCase(bc.id)}>
        Delete this bookcase
      </button>
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
  if (selection?.kind !== 'shelf' || selection.caseId !== bc.id) {
    return <p className="note">Pick a cell above to set one shelf's own depth.</p>
  }
  const shelf = shelfAt(bc, selection.col, selection.level)
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

function Empty({ plan }: { plan: { rooms: unknown[]; cases: unknown[] } }) {
  return (
    <div className="inspector">
      <h2>Nothing selected</h2>
      <p className="note">
        {plan.rooms.length} rooms · {plan.cases.length} bookcases.
      </p>
      <p className="note">
        Draw a room, then drag a bookcase <em>along one of its walls</em>. Tap a
        bookcase to open its columns, levels and depth.
      </p>
    </div>
  )
}
