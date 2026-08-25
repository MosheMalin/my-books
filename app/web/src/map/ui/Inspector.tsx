import { useI18n } from '../../lib/i18n'
import { mapText } from '../text'
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

import { useEffect, useRef, useState } from 'react'

import { Select } from '@booksnap/ui'

import { Elevation } from './Elevation'
import type { MergePreview, OffMapShelf, StripOrder } from '../useMapSync'
import type { Cell, Doc, Selection } from './types'
import { count, markCell, only, onlyCell } from './types'
import { useSticky } from './useSticky'
import type { Bookcase, GapCell, Plan, Room, Section, Shelf } from '../core/model'
import {
  MAX_DEPTH,
  allShelves,
  caseLength,
  caseThickness,
  sectionById,
  sectionIndex,
  shelfAt,
} from '../core/model'

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
  /** Switch cells off, or a hole back on (MAP_PLAN §3.10a). */
  setGaps: (id: string, sectionId: string, cells: GapCell[], gap: boolean) => void
  /**
   * P6.4c, and the three of them are SERVER gestures — unlike everything
   * above, which edits the document and is pushed as a diff. Which shelf
   * stands in a slot is a row the document cannot hold (§3.1: a drawn slot IS
   * a shelf, so the document has slots and never identities), so these ask
   * the server and then re-derive.
   */
  shelvesOffTheMap: () => Promise<OffMapShelf[]>
  bindShelf: (shelfId: string, sectionId: string, col: number, level: number,
              name: string) => void
  unbindShelf: (shelfId: string, sectionId: string, col: number,
                level: number, name: string) => void
  /**
   * P6.4d, and a SEPARATE pair from the bind above — never one button
   * (§3.14). A bind gives an unaddressed shelf an address and moves nothing;
   * a merge makes two identities one, which moves a population of copies,
   * joins two capture strips and overwrites standing answers. The preview is
   * the other half of the ✓: seeing what moves is what makes it a decision.
   */
  previewMerge: (absorbedId: string, survivorId: string,
                 strip: StripOrder) => Promise<MergePreview>
  mergeShelf: (absorbedId: string, survivorId: string, strip: StripOrder,
               name: string) => void
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
  const T = mapText(useI18n().lang)
  const rooms = plan.rooms.filter((r) => selection.rooms.includes(r.id))
  const cases = plan.cases.filter((c) => selection.cases.includes(c.id))
  const carried = plan.cases.filter(
    (c) => c.roomId && selection.rooms.includes(c.roomId) && !selection.cases.includes(c.id),
  )
  return (
    <div className="inspector">
      <h2>{T.selected_n(count(selection))}</h2>
      <p className="note">
        {T.selected_mix(rooms.length, cases.length)}
        {carried.length > 0 && <> {T.selected_carried(carried.length)}</>}
      </p>
      <ul className="picked">
        {rooms.map((r) => (
          <li key={r.id} className="rtl-safe">
            {r.name || T.unnamed_room(r.rect.w, r.rect.h)}
          </li>
        ))}
        {cases.map((c) => (
          <li key={c.id} className="rtl-safe">
            {c.name || T.unnamed_case(c.rect.w, c.rect.h)}
          </li>
        ))}
      </ul>
      <div className="row">
        <button type="button" onClick={actions.copySelection}>
          {T.copy}
        </button>
        <button type="button" onClick={actions.paste}>
          {T.paste}
        </button>
      </div>
      <button type="button" className="danger" onClick={actions.deleteSelection}>
        {T.delete_all(count(selection))}
      </button>
      <p className="note">{T.rooms_keep_their_cases}</p>
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

/**
 * Enter — and Escape — hand the keyboard back to the board (owner,
 * 2026-08-16). A name box that keeps focus is one you have to click your way
 * out of, and every single-key shortcut is dead while it holds it.
 */
const finishOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
  if (e.key === 'Enter' || e.key === 'Escape') e.currentTarget.blur()
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
  const T = mapText(useI18n().lang)
  const nameRef = useRenameFocus(renaming?.kind === 'room' && renaming.id === room.id, onRenamed)
  const attached = plan.cases.filter((c) => c.roomId === room.id)
  return (
    <div className="inspector">
      <h2>{T.room}</h2>
      <label className="field">
        <span>{T.name}</span>
        <input
          ref={nameRef}
          className="rtl-safe"
          value={room.name}
          placeholder={T.room_name_example}
          onKeyDown={finishOnEnter}
          onChange={(e) => actions.renameRoom(room.id, e.target.value)}
        />
      </label>
      <Size
        w={room.rect.w}
        h={room.rect.h}
        labelW={T.room_width}
        labelH={T.room_height}
        onChange={(w, h) => actions.resizeRoom(room.id, w, h)}
      />

      <fieldset>
        <legend>{T.cases_attached}</legend>
        {attached.length === 0 ? (
          <p className="note">{T.no_cases_yet}</p>
        ) : (
          <>
            <ul className="picked">
              {attached.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    className="link rtl-safe"
                    aria-label={T.select_case(c.name || c.id)}
                    onClick={() => actions.select({ rooms: [], cases: [c.id], cells: [] })}
                  >
                    {c.name || T.unnamed_case(c.rect.w, c.rect.h)}
                  </button>
                </li>
              ))}
            </ul>
            <p className="note">{T.cases_move_with_room}</p>
          </>
        )}
      </fieldset>

      <button type="button" className="danger" onClick={actions.deleteSelection}>
        {T.delete_room}
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
  const T = mapText(useI18n().lang)
  const room = plan.rooms.find((r) => r.id === bc.roomId) ?? null
  const wanted = renaming?.kind === 'case' && renaming.id === bc.id
  const nameRef = useRenameFocus(wanted, onRenamed)
  return (
    <div className="inspector">
      <h2>{T.bookcase}</h2>

      {/* Where the case IS collapses; what is ON it does not. The shelf editor
          is the part you come back to, and on a phone the panel is 38% of the
          screen — four fields above it push the grid off the bottom. */}
      <Fold
        storageKey="booksnap.map.fold.caseDetails"
        /* ⚠ Closed FIRST on a phone. The panel is 38% of the screen there, and
           a review measured the elevation grid 351px below its top and the
           per-column controls 580px below — two panel-heights of scrolling to
           reach the thing the bookcase was selected for. The fold's summary
           already says name · size · facing, so its closed state hides nothing
           it does not state. Sticky, so this is the DEFAULT for someone who
           has never touched it, not a rule about what they may open. */
        startClosed={onPhone()}
        forceOpen={wanted}
        label={T.case_details}
        summary={T.case_summary(bc.name || T.unnamed, bc.rect.w, bc.rect.h,
                                T.side(bc.front))}
      >
        <label className="field">
          <span>{T.name}</span>
          <input
            ref={nameRef}
            className="rtl-safe"
            value={bc.name}
            placeholder={T.case_name_example}
            onKeyDown={finishOnEnter}
            onChange={(e) => actions.renameCase(bc.id, e.target.value)}
          />
        </label>

        <Size
          w={bc.rect.w}
          h={bc.rect.h}
          labelW={T.case_width}
          labelH={T.case_height}
          onChange={(w, h) => actions.resizeCase(bc.id, w, h)}
        />

        <label className="field inline">
          <span>{T.moves_with}</span>
          {/* The SHARED control, not a bare <select>: Chrome pins the UA
              chevron a fixed distance from the border and ignores
              padding-inline-end, so one dropdown on the page would look
              designed and this one defaulted. `app/ui`'s own test refuses a
              bare one in this app — it caught this line on the day the lab
              came over. */}
          <Select
            className="rtl-safe"
            aria-label={T.moves_with}
            value={bc.roomId ?? ''}
            onChange={(e) => actions.setCaseRoom(bc.id, e.target.value || null)}
          >
            <option value="">{T.stands_alone}</option>
            {/* Only rooms on THIS storey: a bookcase cannot move with a room on
                another floor, and offering it would be offering a broken link. */}
            {plan.rooms
              .filter((r) => r.floorId === floorId)
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name || T.unnamed_room(r.rect.w, r.rect.h)}
                </option>
              ))}
          </Select>
        </label>

        <div className="field inline">
          <span>{T.books_face}</span>
          <button
            type="button"
            onClick={() => actions.turnCase(bc.id)}
            aria-label={T.turn_case}
          >
            {T.turn_to(T.side(bc.front))}
          </button>
        </div>

        <p className="note">
          {T.case_facts(caseLength(bc), caseThickness(bc), allShelves(bc).length)}
          {bc.sections.length > 1 ? T.in_sections(bc.sections.length) : ''}
          {/* ⚠ The SAME name the room's own controls print. Falling back to
              a bare "unnamed" glued the Hebrew preposition onto it — the
              panel read בללא שם — and disagreed with the Select two rows
              above, which has always called this room חדר 26×25. */}
          {room
            ? T.in_room(room.name || T.unnamed_room(room.rect.w, room.rect.h))
            : T.in_no_room}
          {'.'}
          <br />
          {T.free_measurement}
        </p>
      </Fold>

      <Elevation
        bc={bc}
        selection={selection}
        onSelectShelf={(sectionId, col, level, add) =>
          actions.select(
            markCell(selection, { caseId: bc.id, sectionId, col, level }, add))
        }
        onGaps={(sectionId, cells, gap) => actions.setGaps(bc.id, sectionId, cells, gap)}
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
        {T.delete_case}
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
/** A phone, by the same breakpoint `map.css` uses. Guarded, because jsdom has
 *  no `matchMedia` — and a missing one must mean "not a phone", not a crash. */
const onPhone = (): boolean => {
  try {
    return window.matchMedia?.('(max-width: 640px)').matches ?? false
  } catch {
    return false
  }
}

function Fold({
  storageKey,
  label,
  summary,
  forceOpen,
  startClosed,
  children,
}: {
  storageKey: string
  label: string
  summary: string
  forceOpen?: boolean
  startClosed?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useSticky(storageKey, !startClosed)
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
  const T = mapText(useI18n().lang)
  return (
    <div className="field inline size">
      <span>{T.size_units}</span>
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
  const T = mapText(useI18n().lang)
  const sel = onlyCell(selection)
  if (!sel || sel.caseId !== bc.id) {
    return <p className="note">{T.pick_a_cell}</p>
  }
  const sec = sectionById(bc, sel.sectionId)
  const shelf = sec ? shelfAt(sec, sel.col, sel.level) : null
  if (!sec || !shelf) return null
  // The address prints only what DISCRIMINATES: a one-section case never says
  // "section 1", because saying it would imply there is a section 2.
  const where =
    bc.sections.length > 1 ? `${T.section_n(sectionIndex(bc, sec.id) + 1)} · ` : ''
  const name = shelf.label || T.shelf_unnamed
  return (
    <fieldset className="shelf-panel" ref={useCellInView(sel)}>
      <legend>
        {shelf.free
          ? T.empty_cell_legend(where, shelf.col + 1, shelf.level + 1)
          : T.shelf_legend(where, shelf.col + 1, shelf.level + 1)}
      </legend>
      {/* ⚠ A cell the SERVER says holds no shelf (P6.4c). Everything below
          would be a control over a row that does not exist — the depth box
          most sharply, since `PATCH .../shelves/{col}/{level}` answers 404 for
          an empty slot and the toolbar would have said "saved". */}
      {shelf.free ? (
        // ⚠ KEYED by the cell. Without it, selecting a different free cell
        // keeps this component mounted with the previous cell's `open` and
        // its stale list — a picker offering the answer to a question nobody
        // asked here.
        <EmptyCell key={`${sec.id}:${shelf.col}:${shelf.level}`}
                   sec={sec} shelf={shelf} actions={actions} />
      ) : (
        <>
          {/* The one fact the grid cannot show: a cell is 44 pixels wide. */}
          {shelf.label && (
            <p className="note rtl-safe">{T.shelf_is_named(shelf.label)}</p>
          )}
          <label className="field inline">
            <span>{T.own_depth}</span>
            <input
              type="number"
              min={1}
              max={MAX_DEPTH}
              value={shelf.depth}
              aria-label={T.shelf_depth}
              onChange={(e) =>
                actions.setShelfDepth(bc.id, sec.id, shelf.col, shelf.level, Number(e.target.value))
              }
            />
          </label>
          {/* ⚠ A FACT, not a field. In the lab the photo count was a number you
              typed, so a case could be made to look half-catalogued while you
              drew. Here it is `capture_count` off the shelf, and there is no op
              behind it: as an input it accepted an edit, the toolbar said
              "saved", and the next load showed the old number. A control that
              discards what it takes is worse than one that is absent. */}
          <div className="field inline">
            <span>{T.photos_attached}</span>
            <strong>{shelf.photos}</strong>
          </div>
          <p className="note">{T.photos_are_captures}</p>
          {shelf.id && (
            // ⚠ KEYED by the cell, like `EmptyCell` — otherwise selecting a
            // different occupied cell keeps this mounted with the previous
            // one's open picker and its preview, which is an itemised account
            // of a merge nobody asked about between two shelves that are no
            // longer on screen.
            <MergeHere key={`m:${sec.id}:${shelf.col}:${shelf.level}`}
                       survivorId={shelf.id} survivorName={name}
                       actions={actions} />
          )}
          {shelf.id && (
            <button
              type="button"
              className="danger"
              onClick={() => {
                // ⚠ Asked only when something would be LOST, which is the
                // rule the section header already follows: a dialog in front
                // of a gesture that destroys nothing is what teaches people
                // to click through the ones that do. An empty drawn shelf
                // leaving the map costs nothing; one holding books loses the
                // address they are printed with — and the confirmation says
                // both halves, including that it can be taken back.
                if (shelf.books + shelf.photos === 0
                    || confirm(T.shelf_take_off_map_confirm(shelf.books,
                                                            shelf.photos))) {
                  // The CELL, not only the shelf — the counts in that dialog
                  // came from this cell, and the server refuses if the shelf
                  // has moved out of it since.
                  actions.unbindShelf(shelf.id as string, sec.id, shelf.col,
                                      shelf.level, name)
                }
              }}
            >
              {T.shelf_take_off_map}
            </button>
          )}
        </>
      )}
    </fieldset>
  )
}

/**
 * Bring the shelf panel into view when the owner taps a different cell.
 *
 * ⚠ Not a nicety on a phone. A review measured the panel beginning **957px**
 * inside a scroller that is **252px** tall — 31% of a 375×812 screen — with
 * `scrollTop` at 0 before the tap and 0 after it. So *tap a cell → the panel
 * at the bottom* read as *tap a cell, nothing happens*, and P6.4c's entire UI
 * lives down there. `grep scrollIntoView app/web/src/map/` had no matches.
 *
 * Keyed on the CELL, so re-selecting the same one does not yank the view
 * while somebody is reading it.
 */
function useCellInView(cell: Cell | null) {
  const box = useRef<HTMLFieldSetElement | null>(null)
  const at = cell ? `${cell.sectionId}:${cell.col}:${cell.level}` : ''
  useEffect(() => {
    // ⚠ Guarded, like `onPhone`'s `matchMedia` two folds up: jsdom has no
    // `scrollIntoView`, and a missing one must mean "cannot scroll", not a
    // crash that takes the whole panel down with it.
    if (at) box.current?.scrollIntoView?.({ block: 'nearest' })
  }, [at])
  return box
}

/**
 * A slot with nothing in it, and the way to fill it (P6.4c, MAP_PLAN §3.14).
 *
 * **Only what the owner TYPED decides anything here.** The list is every shelf
 * standing nowhere, in the server's own order, and the ✓ is the owner picking
 * one — nothing is proposed from a photograph, a timestamp or a label match.
 *
 * ⚠ The list is fetched when the picker OPENS, not carried in the document. A
 * shelf photographed on the phone two minutes ago is exactly the one somebody
 * opens this for, and it is not in a document that was derived before it
 * existed.
 */
function EmptyCell({
  sec,
  shelf,
  actions,
}: {
  sec: Section
  shelf: Shelf
  actions: Actions
}) {
  const { t, lang } = useI18n()
  const T = mapText(lang)
  const [open, setOpen] = useState(false)
  /**
   * ⚠ THREE states, and the third is the finding. A failure used to land as
   * an empty list, which printed *"every shelf is already on the map"* — a
   * confident false statement, measured with `GET /shelves` down while forty
   * shelves stood nowhere, one of them the owner's real 22-book one. Absent
   * is not unknown; this project has the same measurement on record about
   * "no admin" beside a card saying two users.
   */
  const [list, setList] = useState<OffMapShelf[] | 'failed' | null>(null)

  const read = () => {
    setList(null)
    void actions.shelvesOffTheMap()
      .then(setList)
      .catch(() => setList('failed'))
  }

  if (!open) {
    return (
      <>
        <p className="note rtl-safe">{T.cell_has_no_shelf}</p>
        <button type="button" onClick={() => { setOpen(true); read() }}>
          {T.put_a_shelf_here}
        </button>
      </>
    )
  }
  return (
    <div className="shelf-pick">
      <p className="note rtl-safe">{T.pick_a_shelf}</p>
      {list === null ? (
        <p className="note">{t.loading}</p>
      ) : list === 'failed' ? (
        // The reason, and the way out. A picker with neither is a dead end
        // whose only escape is selecting a different cell, which nothing says.
        <>
          <p className="note warn rtl-safe" role="status">
            {T.shelf_list_failed}
          </p>
          <button type="button" onClick={read}>{T.shelf_list_retry}</button>
        </>
      ) : list.length === 0 ? (
        <p className="note rtl-safe">{T.no_shelves_off_the_map}</p>
      ) : (
        <ul>
          {list.map((s, i) => (
            <li key={s.id}>
              {/* ⚠ NUMBERED in the accessible name, and it is not decoration:
                  two unnamed shelves holding nothing announce the identical
                  sentence otherwise, which is the collision CLAUDE.md records
                  — and unnamed is the COMMON case here, since these are the
                  photo-born half of the population. */}
              <button
                type="button"
                aria-label={T.pick_shelf_option(
                  i + 1, s.label || T.shelf_unnamed, s.book_count,
                  s.capture_count)}
                onClick={() =>
                  actions.bindShelf(s.id, sec.id, shelf.col, shelf.level,
                                    s.label || T.shelf_unnamed)}
              >
                <span className="rtl-safe">{s.label || T.shelf_unnamed}</span>
                <span className="note rtl-safe">
                  {/* Forty rows reading `0 ספרים · 0 תמונות` is noise in the
                      one list whose job is to tell shelves apart. */}
                  {s.book_count + s.capture_count === 0
                    ? T.shelf_holds_nothing
                    : T.shelf_holds(s.book_count, s.capture_count)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {/* A way out that is not "select a different cell". */}
      <button type="button" className="linkish"
              onClick={() => { setOpen(false); setList(null) }}>
        {T.pick_a_shelf_cancel}
      </button>
    </div>
  )
}


/**
 * Absorbing another identity into the shelf that stands here (P6.4d, §3.11).
 *
 * **Three steps, and the middle one is the item.** Pick a shelf; read what
 * moves; say which half is on the left and press merge. §3.14 forbids
 * shortening it: *"a wrong binding moves a POPULATION of copies, merges two
 * capture strips, and looks like success, because the map gets fuller."*
 *
 * ⚠ **The strip order has no default anywhere**, and this is where that is
 * visible: neither radio is pre-selected, so the button stays disabled until
 * the owner answers. §5.7's rule is *declared, never detected*, and a
 * pre-selected radio is the system detecting it on their behalf every time.
 *
 * ⚠ The list is the same one the empty-cell picker reads — shelves standing
 * NOWHERE. A shelf that is already on the map is not offered, because two
 * drawn slots turning out to be one piece of wood is a different conversation
 * (one of the two cells has to stop existing) and this item does not have it.
 */
function MergeHere({
  survivorId,
  survivorName,
  actions,
}: {
  survivorId: string
  survivorName: string
  actions: Actions
}) {
  const { t, lang } = useI18n()
  const T = mapText(lang)
  const [open, setOpen] = useState(false)
  const [list, setList] = useState<OffMapShelf[] | 'failed' | null>(null)
  const [chosen, setChosen] = useState<OffMapShelf | null>(null)
  // Three states again, and the third for `EmptyCell`'s reason: a preview
  // that failed must not read as a merge that moves nothing.
  const [seen, setSeen] = useState<MergePreview | 'failed' | null>(null)
  const [strip, setStrip] = useState<StripOrder | null>(null)

  const read = () => {
    setList(null)
    void actions.shelvesOffTheMap().then(setList).catch(() => setList('failed'))
  }

  const look = (shelf: OffMapShelf) => {
    setChosen(shelf)
    setSeen(null)
    // ⚠ The preview is asked with a strip order because the ANSWER depends on
    // one, and `survivor_first` is what it is asked with — but the radio
    // below stays unanswered. What the preview counts (books, photographs,
    // answers, depth) is the same either way; only the ORDER differs, and
    // that is the one thing the owner declares.
    void actions.previewMerge(shelf.id, survivorId, 'survivor_first')
      .then(setSeen)
      .catch(() => setSeen('failed'))
  }

  const close = () => {
    setOpen(false)
    setList(null)
    setChosen(null)
    setSeen(null)
    setStrip(null)
  }

  if (!open) {
    return (
      <button type="button" className="merge-open"
              onClick={() => { setOpen(true); read() }}>
        {T.merge_a_shelf_here}
      </button>
    )
  }

  if (!chosen) {
    return (
      <div className="shelf-pick">
        <p className="note rtl-safe">{T.merge_pick}</p>
        {list === null ? (
          <p className="note">{t.loading}</p>
        ) : list === 'failed' ? (
          <>
            <p className="note warn rtl-safe" role="status">
              {T.shelf_list_failed}
            </p>
            <button type="button" onClick={read}>{T.shelf_list_retry}</button>
          </>
        ) : list.length === 0 ? (
          <p className="note rtl-safe">{T.no_shelves_off_the_map}</p>
        ) : (
          <ul>
            {list.map((s, i) => (
              <li key={s.id}>
                <button
                  type="button"
                  aria-label={T.merge_pick_option(
                    i + 1, s.label || T.shelf_unnamed, s.book_count,
                    s.capture_count)}
                  onClick={() => look(s)}
                >
                  <span className="rtl-safe">{s.label || T.shelf_unnamed}</span>
                  <span className="note rtl-safe">
                    {s.book_count + s.capture_count === 0
                      ? T.shelf_holds_nothing
                      : T.shelf_holds(s.book_count, s.capture_count)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="linkish" onClick={close}>
          {T.merge_cancel}
        </button>
      </div>
    )
  }

  const name = chosen.label || T.shelf_unnamed
  const books = seen && seen !== 'failed' ? seen.books : 0
  const photos = seen && seen !== 'failed'
    ? seen.photos.reduce((n, p) => n + p.count, 0) : 0
  return (
    <div className="merge-preview">
      {seen === null ? (
        <p className="note" role="status">{T.merge_reading}</p>
      ) : seen === 'failed' ? (
        <>
          <p className="note warn rtl-safe" role="status">
            {T.merge_read_failed}
          </p>
          <button type="button" onClick={() => look(chosen)}>
            {T.shelf_list_retry}
          </button>
        </>
      ) : seen.refused ? (
        // The server's own sentence, because the six reasons are six
        // different things to do next and this client has no better words for
        // *a read of this shelf is still running* than the one that knows it.
        <p className="note warn rtl-safe" role="status">
          {T.merge_refused} {seen.refused.say}
        </p>
      ) : seen.already ? (
        <p className="note rtl-safe" role="status">{T.merge_already}</p>
      ) : (
        <>
          <p className="note rtl-safe">
            {T.merge_would_move(name, survivorName)}
          </p>
          <ul className="merge-facts">
            {books + photos === 0 ? (
              <li className="rtl-safe">{T.merge_moves_nothing}</li>
            ) : (
              <>
                {books > 0 && <li className="rtl-safe">{T.merge_books(books)}</li>}
                {photos > 0 && (
                  <li className="rtl-safe">{T.merge_photos(photos)}</li>
                )}
              </>
            )}
            {seen.answers_moved > 0 && (
              <li className="rtl-safe">{T.merge_answers(seen.answers_moved)}</li>
            )}
            {seen.identities_moved > 0 && (
              <li className="rtl-safe">
                {T.merge_identities(seen.identities_moved)}
              </li>
            )}
            <li className="rtl-safe">{T.merge_depth_after(seen.depth)}</li>
            {seen.clashes.length > 0 && (
              <li className="rtl-safe warn">
                {T.merge_clashes(seen.clashes.length)}
              </li>
            )}
          </ul>
          {/* ⚠ Offered only when there is something to order. With
              photographs on one side or none at all, "which half is on the
              left" is a question about nothing — and a required answer to it
              would be a required answer to nothing. */}
          {photos > 0 && (
            <fieldset className="merge-strip">
              <legend>{T.merge_strip}</legend>
              <label className="field inline">
                <input type="radio" name="strip" value="survivor_first"
                       checked={strip === 'survivor_first'}
                       onChange={() => setStrip('survivor_first')} />
                <span className="rtl-safe">
                  {T.merge_strip_survivor_first(survivorName)}
                </span>
              </label>
              <label className="field inline">
                <input type="radio" name="strip" value="absorbed_first"
                       checked={strip === 'absorbed_first'}
                       onChange={() => setStrip('absorbed_first')} />
                <span className="rtl-safe">
                  {T.merge_strip_absorbed_first(name)}
                </span>
              </label>
            </fieldset>
          )}
          <button
            type="button"
            className="danger"
            disabled={photos > 0 && strip === null}
            onClick={() => {
              actions.mergeShelf(chosen.id, survivorId,
                                 // Nothing to order, so the declaration is
                                 // not owed and the survivor's (empty) strip
                                 // comes first by arithmetic, not by guess.
                                 strip ?? 'survivor_first', name)
              close()
            }}
          >
            {T.merge_confirm}
          </button>
        </>
      )}
      <button type="button" className="linkish" onClick={close}>
        {T.merge_cancel}
      </button>
    </div>
  )
}


function Empty({ plan }: { plan: Plan }) {
  const T = mapText(useI18n().lang)
  return (
    <div className="inspector">
      <h2>{T.nothing_selected}</h2>
      <p className="note">{T.counts(plan.rooms.length, plan.cases.length)}</p>
      <ol className="steps">
        {/* The tool's own name in bold, from the same key the toolbar reads —
            an instruction naming a button that is labelled differently is
            worse than no instruction. */}
        <li>
          <strong>{T.draw_room}</strong> {T.step_room}
        </li>
        <li>
          <strong>{T.draw_case}</strong> {T.step_case}
        </li>
        <li>
          <strong>{T.arrow}</strong> {T.step_edit}
        </li>
      </ol>
    </div>
  )
}
