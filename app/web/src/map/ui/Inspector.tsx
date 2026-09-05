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

import { formatDate, Select } from '@booksnap/ui'

import { Elevation } from './Elevation'
import type { ShelfOverviewDTO } from '../../api/client'
import { shelfHash } from '../../lib/route'
import { Hint } from '../../lib/Hint'
import { AttachPhoto } from '../../shelf/AttachPhoto'
import type { MergePreview, OffMapShelf, StripOrder } from '../useMapSync'
import type { Cell, Doc, Selection } from './types'
import { count, markCell, only, onlyCell } from './types'
import { useSticky } from './useSticky'
import type { Bookcase, GapCell, Plan, Room, Section, Shelf } from '../core/model'
import {
  MAX_DEPTH,
  allShelves,
  caseLength,
  facesTheShortSide,
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
  /** When this shelf was last read, and whether a row is stale (P6.5c). */
  shelfOverview: (shelfId: string) => Promise<ShelfOverviewDTO>
  /** How many shelves one photograph of a bookcase shows (P6.6). Optional:
   *  a host that cannot ask renders no control. */
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
  /** P6.7a — swap two sections. A SERVER write like the bind and the
   *  unbind: it changes no slot, so there is no document diff to carry it. */
  moveSection: (sectionId: string, direction: 'up' | 'down') => void
  /** P6.7d — a photograph filed against this shelf, with no read behind it. */
  attachPhoto: (shelfId: string, depth: number, photo: File) => Promise<void>
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
      <Hint about={T.delete_room}>{T.rooms_keep_their_cases}</Hint>
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
          {/* ⚠ The FACTS stay — they describe the bookcase in front of you.
              What moves behind the ⓘ is the RULE, which is the same sentence
              on every bookcase in the library and is therefore the definition
              of noise on the twelfth one. */}
          <Hint about={T.free_measurement_about}>{T.free_measurement}</Hint>
        </p>

        {/*
          P6.7h. The owner raised this twice — *"upon drawing a bookcase, the
          columns should be vertical to the shorter dimension"* — and I could
          not find a code path that draws one wrong. Then I counted his
          drawing: NINE of thirteen bookcases have their front on the short
          side, so the elevation describes a two-unit face on a five-unit
          case. The state is real whatever produced it.

          ⚠ A NOTICE, not a guard, and not an auto-correct. §3.4: free
          measurements mean the system may never infer capacity, and a case
          five deep and two wide is legal furniture. What it may do is SAY so,
          beside the control that fixes it — `frontFor` applies §3.8 when a
          case is drawn or flipped and nothing applies it afterwards, because
          *Turn* is manual by design and a room can move out from under a
          case.

          ⚠ Absent unless true, which is the house rule and also what keeps
          it readable: on a drawing where this is the common state, a line
          shown always would be furniture rather than information.
        */}
        {facesTheShortSide(bc) && (
          <p className="note warn rtl-safe" role="status">
            {T.faces_the_short_side(caseLength(bc), caseThickness(bc))}
          </p>
        )}
      </Fold>

      {/*
        ⚠ ABOVE the elevation since P6.7b, and the move is the whole item.
        It used to be the last control in the panel — below the grid and the
        shelf panel — and the owner walking his own library reported that
        while editing cells the only delete he could find destroyed CELLS.
        It did work; it was two panel-heights down, past two other
        destructive controls, on a bookcase whose grid is 38 cells.

        ⚠ It stays ONE control with ONE name. A second *delete this
        bookcase* beside the first is the accessible-name collision
        CLAUDE.md records, and duplicating a destructive control is the
        worst place to earn one.

        ⚠ And it stays behind `delete_cases_confirm`, which counts the
        shelves and photographs that would go with it — moving a destructive
        control closer to the thumb is only safe while the sentence in front
        of it still says what it costs.
      */}
      <button type="button" className="danger case-delete"
              onClick={actions.deleteSelection}>
        {T.delete_case}
      </button>

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
        onMoveSection={actions.moveSection}
      />

      <ShelfPanel bc={bc} selection={selection} actions={actions} />
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
  // ⚠⚠ **ABOVE the early returns, and it was below them.** `useCellInView`
  // holds a `useRef` and a `useEffect`, so calling it after `return <p>` made
  // it a CONDITIONAL hook: the moment the selection went from *no cell* to
  // *a cell*, React logged *"a change in the order of Hooks called by
  // ShelfPanel — 2. undefined → useRef"*, then *"Should have a queue"*, then
  // *"Internal React error: Expected static flag was missing"*. Measured in a
  // real browser on the owner's own library; the whole ring stayed green,
  // because jsdom re-mounts between tests and never walks that transition.
  const box = useCellInView(sel && sel.caseId === bc.id ? sel : null)
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
    <fieldset className="shelf-panel" ref={box}>
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
          <Hint about={T.photos_attached}>{T.photos_are_captures}</Hint>
          {/*
            P6.7d, and it stands here rather than beside the count above for
            a reason: the count is a FACT (see the ⚠ on it) and this is the
            one thing that can change it. The owner asked for the gesture in
            both places — *"on the shelf itself and also in the bookcase
            (when a shelf is selected)"* — and it is ONE component, so the
            two cannot drift into two different promises about what filing a
            photo costs.

            ⚠ The cell's OWN declared depth, never the section's default:
            §3.3, and a photo filed at a row the shelf does not have is the
            one thing `new_capture` refuses.
          */}
          {shelf.id && (
            <AttachPhoto
              depth={1}
              depthCount={shelf.depth}
              onAttach={(photo) => actions.attachPhoto(shelf.id as string, 1, photo)}
            />
          )}
          {shelf.id && <ReadState shelfId={shelf.id} actions={actions} />}
          {/* ⚠ The drill DOWN, and until P6.5c the map had no way to it at
              all: `#/map/<shelfId>` has been level 3 since P2.8 and the only
              things that ever linked to it were the Capture tab (removed by
              the owner in 2026-08) and a typed URL. UI_PLAN §3's three drill
              levels were built as EDITING — the plan selects a bookcase, the
              elevation selects a cell — and this is the step that makes them
              navigation. An `<a>`, not a button: it is a place, so it opens
              in a new tab, copies as a link, and reads as one. */}
          {shelf.id && (
            <a className="linkish open-shelf"
               href={shelfHash(shelf.id as string)}>
              {T.open_this_shelf}
            </a>
          )}
          {shelf.id && (
            // ⚠ KEYED by the cell, like `EmptyCell` — otherwise selecting a
            // different occupied cell keeps this mounted with the previous
            // one's open picker and its preview, which is an itemised account
            // of a merge nobody asked about between two shelves that are no
            // longer on screen.
            <MergeHere key={`m:${sec.id}:${shelf.col}:${shelf.level}`}
                       survivorId={shelf.id} survivorName={name}
                       survivorPhotos={shelf.photos} actions={actions} />
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
 * When this cell's shelf was last read, and whether a row is stale.
 *
 * ⚠ VISION §7: *"a shelf on the map carries its declared depth, so '3 rows,
 * back two not read since March' is answerable from the map"*. The declared
 * depth is the field above; this is the other half — but only its FIRST
 * clause. The sentence naming WHICH rows lives on the shelf screen, and
 * rendering it here too would be one rule built out of two string tables,
 * which is how a rule becomes two that disagree. So the map says *there is
 * something stale here*, and the link beside it goes to the screen that says
 * what.
 *
 * ⚠ Silent while it loads, and silent if it fails. This is a fact ABOUT the
 * cell, not the cell itself; an editor that grows a grey apology every time a
 * request loses is worse than one that shows what it has.
 */
function ReadState({ shelfId, actions }: { shelfId: string; actions: Actions }) {
  const { t, lang } = useI18n()
  const T = mapText(lang)
  const [state, setState] = useState<ShelfOverviewDTO | 'failed' | null>(null)
  // ⚠ Held in a REF, so the effect depends on the cell and on nothing else.
  // Measured at 375x812 before this: **four** requests for one selected cell,
  // from two unstable identities one per layer — `MapScreen` rebuilds
  // `actions` as an object literal every render, and `PlanScreen` wrapped the
  // fetch in a fresh arrow. Depending on either is depending on a render
  // count. The rule belongs HERE rather than on both callers being careful:
  // *what to fetch* is the cell, and the function is only how. Same shape as
  // `@booksnap/ui`'s `useAsync`, which holds its `fn` the same way.
  const ask = useRef(actions.shelfOverview)
  ask.current = actions.shelfOverview
  useEffect(() => {
    let alive = true
    setState(null)
    void ask.current(shelfId)
      .then((got) => { if (alive) setState(got) })
      .catch(() => { if (alive) setState('failed') })
    return () => { alive = false }
  }, [shelfId])
  if (state === null || state === 'failed') return null
  const stale = state.depths.filter((d) => d.is_stale).length
  // ⚠ Absent when there is nothing to say. A drawn shelf that has never been
  // read is the NORMAL state — 152 of the owner's 153 shelves — so a row
  // reading «נקרא לאחרונה: המדף הזה עדיין לא נקרא» would print on
  // almost every cell anyone taps, and a label whose value negates it is not a
  // fact, it is furniture. Measured on the owner's library.
  if (!state.last_read_at && stale === 0) return null
  return (
    <>
      <div className="field inline read-state">
        <span>{T.last_read}</span>
        <strong>
          {state.last_read_at
            ? formatDate(state.last_read_at, lang)
            : t.shelf_never_read}
        </strong>
      </div>
      {/* ⚠ A SENTENCE, not a dot with a tooltip. The first cut was a 7x17px
          ● inside the date's own `<strong>`, so it read as punctuation on the
          date — and its only explanation was a `title`: no hover on a phone,
          so the words were unreachable by tap on the device this product is
          for, and the span carried no role, so a screen reader met them only
          in read-all mode. VISION §7's clause was delivered on desktop only.
          Same words; they are on the screen now. */}
      {stale > 0 && <p className="note warn">{T.rows_stale(stale)}</p>}
    </>
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
    if (!at) return
    // ⚠⚠ **The CELL first, then the panel** — and on a phone the cell is the
    // one that matters. Scrolling only the fieldset was measured at 375x812
    // arriving from `#/plan/<shelfId>`: the panel's 219px pane opened at
    // `scrollTop: 644` with the highlighted cell **409px above the fold** and
    // no scrollbar to say so. P6.5c's whole case for that link is *"a
    // highlighted cell can tell two unnamed bookcases apart"*, and the
    // highlight was off-screen. Marking the cell LAST wins when both cannot
    // fit, which is exactly the phone.
    box.current?.scrollIntoView?.({ block: 'nearest' })
    box.current?.closest('.map-side')
      ?.querySelector('.elev-cell.selected')
      ?.scrollIntoView?.({ block: 'nearest' })
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
  survivorPhotos,
  actions,
}: {
  survivorId: string
  survivorName: string
  /**
   * ⚠ The SURVIVOR's photographs, and they were missing.
   *
   * The preview's `photos` is `MergePlan.photos_per_depth`, filtered to the
   * ABSORBED shelf — so the condition below asked *does the shelf I picked
   * have any?* while the question it gates is *which of the two halves is on
   * the left*. With photographs on one side only, both orderings produce a
   * byte-identical strip (measured), and the client still showed two radios
   * and refused the ✓ until one was chosen: a required answer to a question
   * with one answer. The comment right below claimed the opposite, which is
   * the kind of wrong stated reason that makes the next reader delete the
   * guard — and the flagship *declared, never detected* test was set up in
   * exactly that scenario, so it pinned §5.7 over nothing.
   */
  survivorPhotos: number
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
  /**
   * ⚠ The preview appears BELOW the picker inside `.map-side`, which is
   * **251px tall on a 375×812 phone**. Measured: with the account of what
   * would move rendered, the ✓ sat at y=978 in a window whose bottom edge is
   * around y=812 — off screen, reachable only by scrolling a panel nothing
   * says is scrollable. Same shape as the finding P6.4c already paid for one
   * fold up, and worse here: what is out of sight is the confirmation of the
   * one gesture in this pillar that moves books.
   */
  const foot = useRef<HTMLDivElement | null>(null)
  /** The declaration §5.7 requires, when there is one to make. */
  const ask = useRef<HTMLFieldSetElement | null>(null)

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
      .then((answer) => {
        setSeen(answer)
        // After the paint, not before it: the account of what would move is
        // what pushes the ✓ out of the window, so scrolling to where it USED
        // to be scrolls to the wrong place.
        //
        // ⚠ To the QUESTION when there is one, and to the foot otherwise. In
        // a 251px panel the two do not fit together, and scrolling past the
        // question left a greyed button with nothing on screen explaining it.
        requestAnimationFrame(() => (ask.current || foot.current)
          ?.scrollIntoView?.({ block: 'nearest' }))
      })
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
          // ⚠ Not the bind's sentence. *"Every shelf is already on the map"*
          // is a statement about PLACEMENT under a question about IDENTITY,
          // and it never says the actual reason a merge has nothing to offer.
          <p className="note rtl-safe">{T.merge_none_off_the_map}</p>
        ) : (
          <ul>
            {list.map((s, i) => (
              <li key={s.id}>
                <button
                  type="button"
                  // ⚠ The same `holds nothing` branch the row shows. Its
                  // bind sibling has it and this one did not, so a row
                  // reading *ריק* announced *0 ספרים · 0 תמונות* — two
                  // descriptions of one shelf, which is the bug that branch
                  // was written for. Three taps to reach.
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
  // Order exists only when BOTH halves have something to order. Shelf-level
  // rather than per-depth, which is the grain `_restrip` actually works at —
  // the honest ninety per cent, and the wording the legend uses.
  const ordered = photos > 0 && survivorPhotos > 0
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
        // ⚠ TRANSLATED by `reason`, with the server's `say` as the fallback
        // for a code this table does not know. `MergeRefused` carries a
        // stable code beside the sentence and says in its own docstring that
        // it is there *so a client can translate it* — and this one
        // translated none of six, so a household member met four lines of
        // English and a 32-character hex id. The engine's *rejection reasons
        // are shown verbatim* convention is about a reader's FINDINGS, not
        // about a control refusing to act.
        <>
          <p className="note warn rtl-safe" role="status">
            {T.merge_refused} {T.merge_reason(seen.refused.reason)
              || seen.refused.say}
          </p>
          {/* Transient by nature, so the way forward is to ask again — the
              two failure branches beside this one both offer it. */}
          {seen.refused.reason === 'read_running' && (
            <button type="button" onClick={() => look(chosen)}>
              {T.shelf_list_retry}
            </button>
          )}
        </>
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
          {ordered && (
            <fieldset className="merge-strip" ref={ask}>
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
          {/* ⚠ The reason, beside the control. Measured: with the radio
              fieldset on screen the auto-scroll lands past the question, so
              what the owner sees is a greyed destructive button, no question
              and no account of what would move — which is exactly what
              *reads as broken* means. */}
          {ordered && strip === null && (
            <p className="note rtl-safe" id="merge-why">{T.merge_pick_order}</p>
          )}
          <button
            type="button"
            className="danger"
            aria-describedby={ordered && strip === null
              ? 'merge-why' : undefined}
            disabled={ordered && strip === null}
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
      <div ref={foot}>
        <button type="button" className="linkish" onClick={close}>
          {T.merge_cancel}
        </button>
      </div>
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
