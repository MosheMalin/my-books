import { useCallback, useEffect, useRef, useState } from 'react'

import { useI18n } from '../lib/i18n'

import type { Bookcase, Plan, Underlay } from './core/model'
import {
  TURN,
  addSection,
  casesOn,
  floorContents,
  applyDefaultDepth,
  applyDefaultLevels,
  frontFor,
  mapSection,
  newBookcase,
  overviewBounds,
  planBounds,
  reattach,
  removeSection,
  roomFor,
  roomsOn,
  withColumnCount,
  withColumnLevels,
  withDefaultDepth,
  withGaps,
  withDefaultLevels,
  withRect,
  withShelfDepth,
} from './core/model'
import type { Rect } from './core/rect'
import type { History } from './core/history'
import { canRedo, canUndo, commit, initHistory, redo, undo } from './core/history'
import { FloorBadge } from './ui/FloorBadge'
import { Inspector, type Actions } from './ui/Inspector'
import { PlanCanvas } from './ui/PlanCanvas'
import { Toolbar } from './ui/Toolbar'
import type { Clipboard, Doc, Selection, Theme, Tool } from './ui/types'
import { EMPTY, count, hasCase, hasRoom, selectCase, selectRoom } from './ui/types'
import { fitTo, initialView, zoomAbout, type View } from './ui/viewport'
import { deletionCost } from './cost'
import { pasteInto } from './paste'
import {
  MAX_SECTIONS_PER_BOOKCASE,
  MAX_SLOTS_PER_BOOKCASE,
  clampColumns,
  clampLevels,
  overCeiling,
} from './limits'
import { mapText, type MapText } from './text'
import type { ShelfOverviewDTO } from '../api/client'
import type { MergePreview, OffMapShelf, StripOrder } from './useMapSync'

/**
 * The owner's own state: panel width, current storey, background.
 *
 * booksnap.map.*, not booksnap.map-lab.*. The lab is deleted, and renaming
 * these later would silently reset all three for everyone who had used the
 * editor. It is free exactly now, on a branch that has not merged, and never
 * again.
 */
const THEME_KEY = 'booksnap.map.theme'
/** ⚠ Per SITE, per library. One global key made the storey a household was
 *  looking at the answer for every customer and every property — bounded,
 *  because `floorId` is validated against the document every render, but it
 *  degrades to "the badge forgets", which is the failure the site key is
 *  keyed to avoid. */
const FLOOR_KEY = (scope: string) => `booksnap.map.floor.${scope}`
const SIDE_KEY = 'booksnap.map.side'
const SIDE_MIN = 220
const SIDE_MAX = 720
const clampSide = (w: number) => Math.max(SIDE_MIN, Math.min(SIDE_MAX, Math.round(w)))

export type MapScreenProps = {
  /** The drawing as the server confirmed it. The editor is MOUNTED with it —
   *  see the module note in `PlanScreen`. */
  initialPlan: Plan
  onChange: (plan: Plan) => void
  saved: 'saving' | 'saved' | 'failed'
  onReload: () => void
  /**
   * Write the drawing ON SCREEN to a file (P6.7e).
   *
   * ⚠ The current document, not `sync.initial`. Those two disagree from the
   * first unsaved edit onwards, and a *save to file* that quietly wrote the
   * last thing the SERVER said would be the worst kind of backup: it looks
   * like it captured what you were looking at.
   */
  onExport?: ((plan: Plan) => void) | undefined
  /** The sites this library has, and the one being drawn (§3.9). Passed
   *  through rather than held here: a site decides WHICH document this is, so
   *  it cannot live in the document. */
  site: {
    sites: { id: string; name: string }[]
    siteId: string
    onSite: (id: string) => void
    onAddSite: () => void
    onRenameSite: (id: string, name: string) => void
    onRemoveSite: (id: string) => void
    /** P6.4b's SERVER undo — a different thing from `onUndo`, which is this
     *  session's drawing history. It lives on `site` for the same reason the
     *  site gestures do: it is not expressible in the document, because what
     *  it takes back is rows the document never held. */
    onUndoLastEdit: () => void
  }
  /**
   * P6.4c. The same kind of thing as `onUndoLastEdit` and a separate group
   * because there are now three of them: a prop called `site` holding four
   * things that are not sites is how a name stops meaning anything.
   */
  /**
   * What was selected when the last document was replaced (P6.4c).
   *
   * ⚠ Every server gesture RE-DERIVES, which re-keys this component, and a
   * remount starts with nothing selected. A review measured what that costs
   * on a phone: take a shelf off the map and the bookcase you were working in
   * is deselected, so you must find it again on the plan — an 11×88 pixel
   * sliver at 375px. The ids survive a re-derive (they are the server's), so
   * the selection is still meaningful; it just has to be handed back.
   */
  initialSelection?: Selection
  onSelectionChange?: (selection: Selection) => void
  /**
   * The document on screen is about to be replaced (P6.4c).
   *
   * ⚠⚠ It dresses THIS component's own root rather than a wrapper around it,
   * and that is not a preference. The first cut put an `inert` div in
   * between, the whole gate stayed green, and the drawing canvas measured
   * **375×0** in a real browser: `.mapscreen` fills its board through a chain
   * of percentage heights, and a bare `<div>` in the middle of that chain has
   * no height to inherit. CLAUDE.md's own rule — jsdom sees no CSS, so a UI
   * claim is verified in a browser.
   */
  refreshing?: boolean
  shelves: {
    offTheMap: () => Promise<OffMapShelf[]>
    bind: (shelfId: string, sectionId: string, col: number, level: number,
           name: string) => void
    unbind: (shelfId: string, sectionId: string, col: number, level: number,
             name: string) => void
    previewMerge: (absorbedId: string, survivorId: string,
                   strip: StripOrder) => Promise<MergePreview>
    merge: (absorbedId: string, survivorId: string, strip: StripOrder,
            name: string) => void
    /** P6.7a — swap two sections of one bookcase. A server write: `ordinal`
     *  is not something `planDiff` can express. */
    moveSection: (sectionId: string, direction: 'up' | 'down',
                  label: string) => void
    /** P6.7d — file a photograph against this cell's shelf. Stored, not
     *  read; the map re-derives afterwards because `photos` is a document
     *  field the server owns. */
    attachPhoto: (shelfId: string, depth: number, photo: File) => Promise<void>
    /**
     * What this shelf's own screen knows about it (P6.5c): when it was last
     * read, and whether any row front-to-back is stale.
     *
     * ⚠ VISION §7 asks for *"3 rows, back two not read since March"* to be
     * answerable FROM the map. The map answers the first half — the declared
     * depth is already in this panel — and this adds *whether there is
     * anything stale here*. It does NOT re-render the sentence: that lives on
     * the shelf screen, and building it twice out of two string tables is how
     * one rule becomes two that disagree. Different grain on purpose: the map
     * says there is something to look at, the shelf screen says what.
     */
    overview: (shelfId: string) => Promise<ShelfOverviewDTO>
    /** P6.6 — count the shelves in one photograph. Optional everywhere: a
     *  host that does not offer it makes the control ABSENT. */
    proposeLevels?: ((photo: File) => Promise<number>) | undefined
  }
}

/** The storey a selection stands on, if it names anything drawn. */
function floorOfSelection(plan: Plan, selection?: Selection): string | null {
  const caseId = selection?.cells[0]?.caseId ?? selection?.cases[0]
  if (!caseId) return null
  return plan.cases.find((c) => c.id === caseId)?.floorId ?? null
}

export default function MapScreen(props: MapScreenProps) {
  const { onChange, saved } = props
  const { lang } = useI18n()
  const T = mapText(lang)
  /** The plan is pinned LTR (§3.5); the CHROME around it mirrors. */
  const rtl = lang === 'he'
  const [hist, setHist] = useState<History<Doc>>(
    () => initHistory({ plan: props.initialPlan, seq: 0 }))
  const [tool, setTool] = useState<Tool>('auto')
  const [theme, setTheme] = useState<Theme>(loadTheme)
  const [selection, setSelection] = useState<Selection>(
    props.initialSelection ?? EMPTY)
  /**
   * Which storey the editor opens on.
   *
   * ⚠ A selection WINS over what was last looked at, and that is a rule
   * rather than a convenience for P6.5c's deep link. `initialSelection` is
   * also how a selection survives a re-derive — so without this, taking a
   * shelf off the map while looking at the first floor could hand the
   * rebuilt editor a selection on the ground floor, which `visible` then
   * filters out of the canvas entirely: a panel describing a bookcase that
   * is not drawn anywhere on screen.
   */
  const [floorPick, setFloorPick] = useState<string>(
    () => floorOfSelection(props.initialPlan, props.initialSelection)
      ?? loadFloor(props.site.siteId))
  const [clipboard, setClipboard] = useState<Clipboard>(null)
  const [view, setView] = useState<View>(initialView)
  const [message, setMessage] = useState<{ text: string; n: number } | null>(null)
  const [ghosts, setGhosts] = useState(false)
  const [allFloors, setAllFloors] = useState(false)
  /** Which object the canvas asked to have renamed. The panel opens its fold
   *  and puts the caret in the name box — one editor, not two. */
  const [renaming, setRenaming] = useState<{ kind: 'room' | 'case'; id: string } | null>(null)
  const [sideWidth, setSideWidth] = useState<number>(loadSideWidth)

  const wrapRef = useRef<HTMLDivElement | null>(null)

  // Reported upwards so a re-derive can hand it back. A ref rather than an
  // effect on `selection`: what the parent needs is the LAST value before it
  // replaces the document, not a render-by-render stream.
  const report = props.onSelectionChange
  useEffect(() => {
    report?.(selection)
  }, [report, selection])

  const doc = hist.present

  /**
   * Which storey is on screen. Validated against the document every render, so
   * an undo that removes a floor cannot leave the editor pointed at one that
   * no longer exists — and a plan always has at least one.
   */
  const floorId = doc.plan.floors.some((f) => f.id === floorPick)
    ? floorPick
    : doc.plan.floors[0]!.id
  /** What the canvas may see and touch: one storey. Two floors both start at
   *  0,0, so drawing them together would put the bedroom on the kitchen. */
  const visible: Plan = {
    ...doc.plan,
    rooms: roomsOn(doc.plan, floorId),
    cases: casesOn(doc.plan, floorId),
  }

  /** The overview needs a second storey to be an overview at all. */
  const overview = allFloors && doc.plan.floors.length > 1

  // --- persistence ---------------------------------------------------------

  /**
   * Every edit is written immediately (owner, 2026-08-16: *"allow to save, so
   * work will not get lost"*), and the toolbar SAYS so — an autosave nobody
   * can see is indistinguishable from no autosave.
   *
   * ⚠ The first run is the document this component was MOUNTED with, so it
   * diffs to nothing. That is the whole reason the editor is mounted with its
   * plan rather than handed one later: a guard here could not help, because
   * on the render where the data arrives `doc.plan` is still the old one
   * whatever order the effects run in — measured as a freshly created storey
   * being deleted by the load that created it.
   */
  useEffect(() => {
    onChange(doc.plan)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.plan])

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDE_KEY, String(sideWidth))
    } catch {
      /* ignore */
    }
  }, [sideWidth])

  useEffect(() => {
    try {
      window.localStorage.setItem(FLOOR_KEY(props.site.siteId), floorId)
    } catch {
      /* ignore */
    }
  }, [floorId, props.site.siteId])

  /**
   * The keys the lab left behind. `planning/map-lab` is deleted and these were
   * renamed to `booksnap.map.*` before anyone had the editor, so nothing reads
   * them — but they are the owner's browser storage, and a name that means
   * nothing is litter that outlives whoever could explain it.
   */
  useEffect(() => {
    for (const dead of ['theme', 'floor', 'side', 'fold.caseDetails']) {
      try {
        window.localStorage.removeItem(`booksnap.map-lab.${dead}`)
      } catch {
        /* a blocked localStorage is not a reason to fail a render */
      }
    }
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(THEME_KEY, theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  /**
   * ⚠ Keyed, so pressing a refused control TWICE says something twice.
   *
   * The previous shape set `message` to the identical string, React bailed out
   * of the render, and the natural "did that work?" second tap produced
   * literally nothing — no flash, no re-announcement — while the first press's
   * timer went on owning the clear, so the toast could vanish under the second
   * press. A counter makes each answer its own state, with its own 2600ms.
   * `role="status"` is on the element: the read-only bar beside it has had one
   * since the lab, and this is the surface that carries a refusal.
   */
  const say = useCallback((text: string) => {
    setMessage((m) => ({ text, n: (m?.n ?? 0) + 1 }))
  }, [])

  useEffect(() => {
    if (!message) return
    const timer = window.setTimeout(() => setMessage(null), 2600)
    return () => window.clearTimeout(timer)
  }, [message])

  // --- document edits ------------------------------------------------------

  /**
   * `tag` collapses a run of the same edit into ONE undo step: typing a
   * fourteen-letter room name is one Ctrl+Z, not fourteen. Discrete actions —
   * a drag, a create, a turn — pass none and therefore always stack.
   */
  const update = useCallback(
    (fn: (d: Doc) => Doc, tag: string | null = null) =>
      setHist((h) => commit(h, fn(h.present), tag)),
    [],
  )

  const mapCase = useCallback(
    (id: string, fn: (bc: Bookcase) => Bookcase, tag: string | null = null) =>
      update(
        (d) => ({
          ...d,
          plan: { ...d.plan, cases: d.plan.cases.map((c) => (c.id === id ? fn(c) : c)) },
        }),
        tag,
      ),
    [update],
  )

  /**
   * A structural edit, refused HERE when the server would refuse it there.
   *
   * MAP_PLAN's note on what P6.2 landed says it plainly: *the editor must not
   * offer a gesture that asks for more than the ceiling, or the owner meets a
   * 409*. Without this, `+ column` on a wide case reported "not saved" in a
   * corner and the whole editor then RELOADED to re-derive from the server —
   * a refusal for a rule the screen could have stated before the press.
   *
   * ⚠ Only a gesture that GROWS is refused. A case that is somehow already
   * over a ceiling must still be shrinkable, or the guard becomes the trap.
   */
  const growCase = useCallback(
    (id: string, fn: (bc: Bookcase) => Bookcase, tag: string | null = null) => {
      const bc = doc.plan.cases.find((c) => c.id === id)
      const over = bc ? overCeiling(bc, fn(bc)) : null
      if (over) {
        return say(over.what === 'slots'
          ? T.too_many_slots(over.asked, MAX_SLOTS_PER_BOOKCASE)
          : T.too_many_sections(MAX_SECTIONS_PER_BOOKCASE))
      }
      mapCase(id, fn, tag)
    },
    [doc.plan.cases, mapCase, say, T],
  )

  /**
   * A newly drawn thing is SELECTED (owner, 2026-08-16: *"allow to delete or
   * copy once an item is drawn, without needing to switch to Move & edit"*).
   * The drawing tool stays active so you can keep drawing, but Delete, Ctrl+C
   * and the panel all now act on what you just made — which is what "without
   * switching" actually requires, since none of them were tool-scoped.
   */
  const createRoom = useCallback(
    (rect: Rect) => {
      const id = `r${doc.seq + 1}`
      update((d) => ({
        seq: d.seq + 1,
        plan: {
          ...d.plan,
          rooms: d.plan.rooms.concat({ id: `r${d.seq + 1}`, name: '', rect, floorId }),
        },
      }))
      setSelection(selectRoom(id))
    },
    [update, doc.seq, floorId],
  )

  const createCase = useCallback(
    (rect: Rect) => {
      const id = `c${doc.seq + 1}`
      update((d) => {
        const seq = d.seq + 1
        const room = roomFor(d.plan, rect, floorId)
        const bc = newBookcase(
          `c${seq}`,
          '',
          rect,
          frontFor(rect, room),
          room?.id ?? null,
          floorId,
        )
        return { seq, plan: { ...d.plan, cases: d.plan.cases.concat(bc) } }
      })
      setSelection(selectCase(id))
    },
    [update, doc.seq, floorId],
  )

  /**
   * Move everything that is selected — and every bookcase attached to a
   * selected room, whether or not it was selected itself. That attachment is
   * what makes a room a room rather than a rectangle drawn behind the
   * furniture.
   */
  const moveSelection = useCallback(
    (dx: number, dy: number) =>
      update((d) => {
        const rooms = d.plan.rooms.map((r) =>
          hasRoom(selection, r.id) ? { ...r, rect: { ...r.rect, x: r.rect.x + dx, y: r.rect.y + dy } } : r,
        )
        // ⚠ Two populations, and they are treated differently.
        //
        // DRAGGED — the user picked this case up, so where it lands decides
        // which room it belongs to.
        //
        // CARRIED — it moved only because its room did. Re-deriving its room
        // here is what made an explicit attachment last exactly one move: a
        // case attached to the far room, carried by that room, landed inside
        // the room it physically overlaps and was silently handed back to it.
        // A room moving its own furniture must not change whose furniture it
        // is.
        const dragged = new Set(d.plan.cases.filter((c) => hasCase(selection, c.id)).map((c) => c.id))
        const carried = new Set(
          d.plan.cases
            .filter((c) => !dragged.has(c.id) && c.roomId && hasRoom(selection, c.roomId))
            .map((c) => c.id),
        )
        const plan: Plan = { ...d.plan, rooms }
        return {
          ...d,
          plan: {
            ...plan,
            cases: d.plan.cases.map((c) => {
              if (!dragged.has(c.id) && !carried.has(c.id)) return c
              const rect = { ...c.rect, x: c.rect.x + dx, y: c.rect.y + dy }
              return dragged.has(c.id) ? reattach({ ...c, rect }, plan) : { ...c, rect }
            }),
          },
        }
      }),
    [update, selection],
  )

  const resizeItem = useCallback(
    (kind: 'room' | 'case', id: string, rect: Rect) =>
      update((d) => {
        if (kind === 'room') {
          return {
            ...d,
            plan: {
              ...d.plan,
              rooms: d.plan.rooms.map((r) => (r.id === id ? { ...r, rect } : r)),
            },
          }
        }
        return {
          ...d,
          plan: {
            ...d.plan,
            cases: d.plan.cases.map((c) =>
              c.id === id
                ? reattach(withRect(c, rect, roomFor(d.plan, rect, c.floorId)), d.plan)
                : c,
            ),
          },
        }
      }),
    [update],
  )

  /**
   * ⚠ **The door.** Deleting a bookcase empties its slots first, and emptying
   * a slot detaches the shelf standing in it — the books keep their shelf, the
   * shelf loses its address, and nothing on this screen says so afterwards.
   * That is the identical argument that removed *Clear the plan*, and two
   * reviews pointed out it had been applied to one control and not to this
   * one, which does the same thing to less data. Removing a column and
   * removing a section have asked since the lab.
   *
   * The counts are what this client can honestly state: how many shelves go,
   * and how many of them carry photographs. It cannot say how many hold BOOKS
   * — the server reports that split (`deleted` vs `detached`) only after the
   * call — so the wording promises the mechanism rather than a number it does
   * not have. A room alone asks nothing: deleting one destroys no shelf and
   * never cascades into its furniture.
   */
  const deleteSelection = useCallback(() => {
    if (count(selection) === 0) return
    const cost = deletionCost(doc.plan.cases.filter((c) => hasCase(selection, c.id)))
    // ⚠ `empty`, not `shelves > 0`. A freshly drawn case is fifteen slots
    // that hold nothing whatever, and asking about them was noise in front of
    // the commonest gesture there is — drawing something and changing your
    // mind (owner, drawing with it).
    if (!cost.empty &&
        !confirm(T.delete_cases_confirm(cost.cases, cost.shelves, cost.photos)))
      return
    update((d) => ({
      ...d,
      plan: {
        ...d.plan,
        rooms: d.plan.rooms.filter((r) => !hasRoom(selection, r.id)),
        // Deleting a room does NOT cascade into its bookcases — the same rule
        // the product already holds for shelves. They stay where they stand
        // and belong to no room.
        cases: d.plan.cases
          .filter((c) => !hasCase(selection, c.id))
          .map((c) => (c.roomId && hasRoom(selection, c.roomId) ? { ...c, roomId: null } : c)),
      },
    }))
    setSelection(EMPTY)
  }, [selection, update, doc.plan.cases, T])

  // --- copy / paste --------------------------------------------------------

  const copySelection = useCallback(() => {
    const rooms = doc.plan.rooms.filter((r) => hasRoom(selection, r.id))
    const cases = doc.plan.cases.filter((c) => hasCase(selection, c.id))
    if (rooms.length + cases.length === 0) return
    // Deep-cloned at COPY time: a later edit to the original must not reach
    // into the clipboard, and a paste must not alias the shelves it came from.
    setClipboard(JSON.parse(JSON.stringify({ rooms, cases })) as Clipboard)
    say(T.copied(rooms.length + cases.length))
  }, [doc.plan, selection, say, T])

  /** ⚠ The copy gets section ids of its OWN — see `paste.ts`. Sharing them
   *  made an edit on the copy write to the original's shelves. */
  const paste = useCallback(() => {
    if (!clipboard) return
    const pasted = pasteInto(doc, clipboard, floorId)
    update(() => pasted.doc)
    setSelection(pasted.selection)
  }, [clipboard, doc, update, floorId])

  const actions: Actions = {
    renameRoom: (id, name) =>
      update(
        (d) => ({
          ...d,
          plan: { ...d.plan, rooms: d.plan.rooms.map((r) => (r.id === id ? { ...r, name } : r)) },
        }),
        `rename:${id}`,
      ),
    resizeRoom: (id, w, h) =>
      update(
        (d) => ({
          ...d,
          plan: {
            ...d.plan,
            rooms: d.plan.rooms.map((r) =>
              r.id === id ? { ...r, rect: { ...r.rect, w: size(w), h: size(h) } } : r,
            ),
          },
        }),
        `size:${id}`,
      ),
    renameCase: (id, name) => mapCase(id, (bc) => ({ ...bc, name }), `rename:${id}`),
    resizeCase: (id, w, h) =>
      update(
        (d) => ({
          ...d,
          plan: {
            ...d.plan,
            cases: d.plan.cases.map((c) => {
              if (c.id !== id) return c
              const rect = { ...c.rect, w: size(w), h: size(h) }
              return withRect(c, rect, roomFor(d.plan, rect, c.floorId))
            }),
          },
        }),
        `size:${id}`,
      ),
    setCaseRoom: (id, roomId) => mapCase(id, (bc) => ({ ...bc, roomId })),
    turnCase: (id) => mapCase(id, (bc) => ({ ...bc, front: TURN[bc.front] })),
    // ⚠ Clamped where the number ENTERS the document, not where it is shown:
    // an `<input max=…>` is a hint, and a typed 41 reached the wire as a 422.
    setColumnCount: (id, sid, n) =>
      growCase(id, (bc) => mapSection(bc, sid, (s) => withColumnCount(s, clampColumns(n)))),
    setColumnLevels: (id, sid, col, n) =>
      growCase(id, (bc) => mapSection(bc, sid, (s) => withColumnLevels(s, col, clampLevels(n)))),
    setDefaultLevels: (id, sid, n) =>
      mapCase(id, (bc) => mapSection(bc, sid, (s) => withDefaultLevels(s, clampLevels(n))), `deflevels:${sid}`),
    applyDefaultLevels: (id, sid) => growCase(id, (bc) => mapSection(bc, sid, applyDefaultLevels)),
    setDefaultDepth: (id, sid, n) =>
      mapCase(id, (bc) => mapSection(bc, sid, (s) => withDefaultDepth(s, n)), `defdepth:${sid}`),
    applyDefaultDepth: (id, sid) => mapCase(id, (bc) => mapSection(bc, sid, applyDefaultDepth)),
    setShelfDepth: (id, sid, col, level, n) =>
      mapCase(
        id,
        (bc) => mapSection(bc, sid, (s) => withShelfDepth(s, col, level, n)),
        `shelfdepth:${sid}:${col}:${level}`,
      ),
    // ⚠ `growCase`, not `mapCase`, and only for the RESTORE direction — that
    // is the one that creates slots, and the ceiling guard is one-directional
    // for the reason `limits.ts` states. Switching cells OFF can never cross
    // a ceiling, and refusing it would trap a case that is already over one.
    setGaps: (id, sid, cells, gap) => {
      const edit = (bc: Bookcase) => mapSection(bc, sid, (s) => withGaps(s, cells, gap))
      if (gap) {
        mapCase(id, edit)
        // The cells the owner just emptied are no longer cells to act on, and
        // leaving them marked would offer *make space* for holes.
        setSelection((sel) => ({ ...sel, cells: [] }))
      } else {
        growCase(id, edit)
      }
    },
    addSection: (id, where) => growCase(id, (bc) => addSection(bc, where)),
    /**
     * P6.7a — straight through to the server, like the bind and the unbind:
     * `ordinal` is not something `planDiff` can express, and a document edit
     * here would be an optimistic reorder with nothing to roll it back.
     *
     * ⚠ The label is the section's number BEFORE the swap, because that is
     * the control the owner pressed. Naming it by where it landed would say
     * *"section 1 moved"* about the button labelled 2.
     */
    moveSection: (sectionId, direction) => {
      const owner = doc.plan.cases.find(
        (c) => c.sections.some((s) => s.id === sectionId))
      const index = owner
        ? owner.sections.findIndex((s) => s.id === sectionId) : -1
      props.shelves.moveSection(sectionId, direction, T.section_n(index + 1))
    },
    removeSection: (id, sid) => {
      mapCase(id, (bc) => removeSection(bc, sid))
      // The selected cell may have been inside it. Dropping the shelf while
      // keeping the case selected is the least surprising landing.
      setSelection((sel) =>
        sel.cells.some((c) => c.sectionId === sid) ? { ...sel, cells: [] } : sel)
    },
    deleteSelection,
    copySelection,
    paste,
    select: setSelection,
    // Straight through: these three write to the SERVER, so there is no
    // document edit to make and nothing here to add to them.
    shelvesOffTheMap: props.shelves.offTheMap,
    bindShelf: props.shelves.bind,
    unbindShelf: props.shelves.unbind,
    previewMerge: props.shelves.previewMerge,
    mergeShelf: props.shelves.merge,
    shelfOverview: props.shelves.overview,
    proposeLevels: props.shelves.proposeLevels,
    attachPhoto: props.shelves.attachPhoto,
  }

  /** Double-click on the plan: select it and ask the panel to start editing. */
  const beginRename = useCallback((kind: 'room' | 'case', id: string) => {
    setSelection(kind === 'room' ? selectRoom(id) : selectCase(id))
    setRenaming({ kind, id })
  }, [])

  // --- floors --------------------------------------------------------------

  const addFloor = useCallback(() => {
    const n = doc.plan.floors.length + 1
    // ⚠ The id comes from `seq`, never from the COUNT. Add two storeys, remove
    // the first while it is empty, add again: the count mints an id that is
    // already taken, `planDiff` indexes floors by id, and the duplicate
    // collapses — no `floor.add` is issued, the storey never reaches the
    // server, and it silently merges with the one it collided with. Rooms and
    // bookcases have always numbered from `seq`; this is the same rule.
    //
    // The NAME is in the reader's language, and it is DATA: the lab wrote
    // "Floor 2" and the port kept it, so a Hebrew library grew English
    // storeys that went to the server and stayed there.
    update((d) => ({
      seq: d.seq + 1,
      plan: {
        ...d.plan,
        floors: d.plan.floors.concat({ id: `fl${d.seq + 1}`, name: T.floor_n(n) }),
      },
    }))
    setFloorPick(`fl${doc.seq + 1}`)
    setSelection(EMPTY)
  }, [doc.plan.floors.length, doc.seq, update, T])

  const renameFloor = useCallback(
    (id: string, name: string) =>
      update(
        (d) => ({
          ...d,
          plan: {
            ...d.plan,
            floors: d.plan.floors.map((f) => (f.id === id ? { ...f, name } : f)),
          },
        }),
        `floor:${id}`,
      ),
    [update],
  )

  /** Refuses to take a storey down with the house still on it. Nothing here
   *  auto-removes: the count says what is in the way. */
  const removeFloor = useCallback(() => {
    if (doc.plan.floors.length <= 1) return say(T.one_floor_at_least)
    const { rooms, cases } = floorContents(doc.plan, floorId)
    if (rooms + cases > 0) return say(T.floor_not_removed(rooms, cases))
    update((d) => ({ ...d, plan: { ...d.plan, floors: d.plan.floors.filter((f) => f.id !== floorId) } }))
    setFloorPick(doc.plan.floors.find((f) => f.id !== floorId)!.id)
  }, [doc.plan, floorId, update, say, T])

  /**
   * ⚠ The door in front of removing a site, and the refusal in the owner's
   * words.
   *
   * The server's own 409 names the site by a 32-character id and cites
   * `MAP_PLAN §3.7` — true, and not a sentence for a household. This screen
   * holds the document, so it can say what is in the way and in how many
   * words: exactly the shape `removeFloor` has had since the lab. The server's
   * refusal stays as the backstop for anything drawn in another tab.
   *
   * And a confirmation, because a site takes every empty storey with it and
   * none of it is on the undo stack — the same argument that put a door in
   * front of deleting a bookcase, one level up.
   */
  const removeSite = useCallback((id: string) => {
    if (id !== props.site.siteId) return props.site.onRemoveSite(id)
    const rooms = doc.plan.rooms.length
    const cases = doc.plan.cases.length
    if (rooms + cases > 0) return say(T.site_not_removed(rooms, cases))
    const name = props.site.sites.find((s) => s.id === id)?.name || T.site
    if (!confirm(T.remove_site_confirm(name, doc.plan.floors.length))) return
    props.site.onRemoveSite(id)
  }, [doc.plan, props.site, say, T])

  // --- underlay ------------------------------------------------------------

  const setUnderlay = (u: Underlay | null) =>
    update((d) => ({ ...d, plan: { ...d.plan, underlay: u } }))

  const loadUnderlay = (file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const src = String(reader.result)
      const img = new Image()
      img.onload = () => {
        setUnderlay({
          src,
          x: 0,
          y: 0,
          scale: 60,
          aspect: img.naturalWidth / Math.max(1, img.naturalHeight),
          opacity: 0.45,
        })
        say(T.trace_loaded)
      }
      img.onerror = () => say(T.trace_not_an_image)
      img.src = src
    }
    reader.onerror = () => say(T.trace_unreadable)
    reader.readAsDataURL(file)
  }

  const doZoom = useCallback(
    (factor: number) => {
      const el = wrapRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      // About the CENTRE of what is on screen, which is the only anchor a menu
      // command has — a wheel zoom has the pointer, this does not.
      setView((v) => zoomAbout(v, { x: v.cx, y: v.cy }, v.scale * factor))
      void r
    },
    [],
  )

  const doFit = useCallback(() => {
    const el = wrapRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const b = overview ? overviewBounds(doc.plan) : planBounds(doc.plan, floorId)
    if (b.min.x === b.max.x && b.min.y === b.max.y) return setView(initialView())
    setView(fitTo(b.min, b.max, { left: r.left, top: r.top, width: r.width, height: r.height }))
  }, [doc.plan, floorId, overview])

  // --- keyboard ------------------------------------------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) {
        return
      }
      const meta = e.metaKey || e.ctrlKey

      // ⚠ Shortcuts key off `event.code` — the PHYSICAL key — never
      // `event.key`. On a Hebrew layout the C key reports `key: 'ב'`, so
      // `key.toLowerCase() === 'c'` is false and Ctrl+C silently does nothing.
      // That is not an edge case in a Hebrew-first product: it is the owner's
      // own keyboard, and it is why the buttons worked and the shortcuts did
      // not. `code` is layout-independent; `key` is kept only as a fallback
      // for anything that reports no code.
      const is = (code: string, latin: string) =>
        e.code === code || (!e.code && e.key.toLowerCase() === latin)

      if (meta && is('KeyZ', 'z')) {
        e.preventDefault()
        setHist((h) => (e.shiftKey ? redo(h) : undo(h)))
        return
      }
      // Ctrl+Y is redo on Windows; Ctrl+Shift+Z is the same thing everywhere
      // else. Both, because the owner asked for Ctrl+Y by name.
      if (meta && is('KeyY', 'y')) {
        e.preventDefault()
        setHist(redo)
        return
      }
      if (meta && is('KeyC', 'c')) {
        e.preventDefault()
        return copySelection()
      }
      if (meta && is('KeyV', 'v')) {
        e.preventDefault()
        return paste()
      }
      if (meta) return
      if (e.code === 'Escape' || e.key === 'Escape') {
        setSelection(EMPTY)
        return setTool('auto')
      }
      if (e.key === '+' || e.key === '=') return doZoom(1.25)
      if (e.key === '-' || e.key === '_') return doZoom(1 / 1.25)
      if (is('Digit1', '1')) return setTool('auto')
      if (is('Digit2', '2')) return setTool('room')
      if (is('Digit3', '3')) return setTool('case')
      if (is('Digit4', '4')) return setTool('pan')
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault()
        deleteSelection()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    // ⚠ INERT while re-deriving, not merely dimmed. Keeping the old editor
    // visible trades a blank screen for a window in which the owner could
    // edit a document that is about to be replaced — and `useMapSync`'s `era`
    // guard DISCARDS a queued push from a stale era, silently. A blank was
    // the wrong answer; an editable stale one would be worse. `inert` takes
    // it out of the tab order and swallows pointer events in one attribute.
    <div className={`app mapscreen${props.refreshing ? ' refreshing' : ''}`}
         data-map-theme={theme}
         {...(props.refreshing ? { inert: '' as unknown as boolean } : {})}
         aria-busy={props.refreshing}>
      <Toolbar
        tool={tool}
        theme={theme}
        ghosts={ghosts}
        allFloors={allFloors}
        manyFloors={doc.plan.floors.length > 1}
        readOnly={overview}
        onAllFloors={setAllFloors}
        onZoom={doZoom}
        onGhosts={setGhosts}
        saved={saved}
        underlay={doc.plan.underlay}
        canUndo={canUndo(hist)}
        canRedo={canRedo(hist)}
        canPaste={clipboard !== null}
        selectedCount={count(selection)}
        onTool={setTool}
        onTheme={setTheme}
        onUndo={() => setHist(undo)}
        onRedo={() => setHist(redo)}
        onUndoLastEdit={props.site.onUndoLastEdit}
        onFit={doFit}
        onCopy={copySelection}
        onPaste={paste}
        onDelete={deleteSelection}
        onReload={props.onReload}
        onExport={() => props.onExport?.(doc.plan)}
        // ⚠ The acknowledgment is NOT said here. Adding a site re-derives,
        // which remounts this component and would take the toast with it —
        // `MapSync.flash` is the surface that survives.
        onAddSite={props.site.onAddSite}
        onUnderlay={loadUnderlay}
        onUnderlayChange={(patch) =>
          setUnderlay(doc.plan.underlay ? { ...doc.plan.underlay, ...patch } : null)
        }
        onUnderlayClear={() => setUnderlay(null)}
      />

      <main className="body">
        {/* dir=ltr: the plan is pinned LTR (MAP_PLAN §3.5) — the furniture does
            not move when the language flips. Labels inside it carry
            unicode-bidi: plaintext and resolve their own direction. */}
        <div className="canvas-wrap" ref={wrapRef} dir="ltr">
          <PlanCanvas
            plan={visible}
            ghosts={ghosts ? doc.plan.rooms.filter((r) => r.floorId !== floorId) : []}
            tool={tool}
            selection={selection}
            view={view}
            onView={setView}
            onSelect={setSelection}
            onCreateRoom={createRoom}
            onCreateCase={createCase}
            onMoveSelection={moveSelection}
            onResize={resizeItem}
            onRejected={say}
            onRename={beginRename}
            overview={
              overview
                ? {
                    plan: doc.plan,
                    onFocus: (id) => {
                      setAllFloors(false)
                      setFloorPick(id)
                      setSelection(EMPTY)
                    },
                  }
                : null
            }
          />
          <Hint tool={tool} overview={overview} T={T} />
          {/* ⚠ The overview had no visible exit: the way out was a menu item
              in the corner, and "I could not get rid of it no matter which
              button I clicked" is what that costs. A mode with no door on
              screen is a trap, however few keystrokes it really takes. */}
          {overview && (
            <div className="readonly-bar" role="status">
              {/* With one site the name would say nothing; with two, "every
                  floor" is ambiguous without it. */}
              <span>
                {props.site.sites.length > 1
                  ? T.overview_of(props.site.sites.find(
                      (s) => s.id === props.site.siteId)?.name || T.site)
                  : T.read_only_bar}
              </span>
              <button type="button" className="rtl-safe"
                      onClick={() => setAllFloors(false)}>
                {T.back_to(
                  doc.plan.floors.find((f) => f.id === floorId)?.name || T.the_plan)}
              </button>
            </div>
          )}
          {/* ⚠ The badge is ABSENT in the overview, not merely behind the bar.
              Both sit at `top: 10px` in the same wrapper — the bar centred, the
              badge at the inline start — and on a 390px phone in Hebrew they
              overlapped by 87px, with the badge painting last: a UX review
              hit-tested the exit and found 19 of its 96px reachable, the rest
              opening the floor menu. That is the trap the comment above
              describes ("I could not get rid of it no matter which button I
              clicked") re-created by geometry. Nothing is lost by hiding it:
              the bar already names the mode, and three of the badge's five
              menu items are disabled while it is up. */}
          {!overview && <FloorBadge
            site={{ ...props.site, onRemoveSite: removeSite }}
            floors={doc.plan.floors}
            floorId={floorId}
            allFloors={overview}
            onFloor={(id) => {
              setFloorPick(id)
              setSelection(EMPTY)
            }}
            onAllFloors={setAllFloors}
            onAdd={addFloor}
            onRename={renameFloor}
            onRemove={removeFloor}
          />}
          {message && (
            <div className="toast rtl-safe" role="status" key={message.n}>
              {message.text}
            </div>
          )}
        </div>
        {/* Drag to widen the settings. The elevation of a wide bookcase wants
            the room, and 330 px is a guess about someone else's screen. */}
        <div
          className="resizer"
          role="separator"
          aria-label={T.panel_resize}
          aria-orientation="vertical"
          onPointerDown={(e) => {
            // Same guard as the canvas: capture throws InvalidPointerId for a
            // pointer the browser no longer considers active, and letting that
            // escape would abort the handler BEFORE the listeners are attached
            // — the drag would then do nothing at all.
            try {
              e.currentTarget.setPointerCapture(e.pointerId)
            } catch {
              /* the window listeners below are what actually drive the drag */
            }
            const startX = e.clientX
            const startW = sideWidth
            const move = (ev: PointerEvent) => {
              // ⚠ Away from the PANEL widens it, and which way that is depends
              // on the reading direction: the settings sit at the inline end,
              // so in English they are on the right (drag left to widen) and
              // in Hebrew on the left (drag right). Hard-coded to the English
              // side, the divider fought the owner on his own language.
              const wider = rtl ? ev.clientX - startX : startX - ev.clientX
              setSideWidth(clampSide(startW + wider))
            }
            const up = () => {
              window.removeEventListener('pointermove', move)
              window.removeEventListener('pointerup', up)
            }
            window.addEventListener('pointermove', move)
            window.addEventListener('pointerup', up)
          }}
        />
        {/* ⚠ `map-side`, not `side`. `base.css` carries this app's exception to
            `.rtl-safe` for the book row's end-aligned location column, and it
            is written `:root[dir=rtl] .side .rtl-safe { text-align: left }` —
            four class-weight terms, which no rule in this sheet can outrank.
            The panel's Hebrew was measured aligning LEFT, and its English
            RIGHT: exactly inverted, in both directions. */}
        <aside className="map-side" style={{ width: sideWidth, flexBasis: sideWidth }}>
          <Inspector
            doc={doc}
            floorId={floorId}
            selection={selection}
            actions={actions}
            renaming={renaming}
            onRenamed={() => setRenaming(null)}
          />
        </aside>
      </main>
    </div>
  )
}

const size = (v: number): number => Math.max(1, Math.round(v))

function Hint({ tool, overview, T }: { tool: Tool; overview: boolean; T: MapText }) {
  if (overview) return <p className="hint">{T.hint_overview}</p>
  const text =
    tool === 'room'
      ? T.hint_room
      : tool === 'case'
        ? T.hint_case
        : tool === 'pan'
          ? T.hint_pan
          : T.hint_arrow
  return <p className="hint">{text}</p>
}

function loadSideWidth(): number {
  try {
    const raw = Number(window.localStorage.getItem(SIDE_KEY))
    return Number.isFinite(raw) && raw > 0 ? clampSide(raw) : 330
  } catch {
    return 330
  }
}

function loadFloor(scope: string): string {
  try {
    return window.localStorage.getItem(FLOOR_KEY(scope)) ?? 'f1'
  } catch {
    return 'f1'
  }
}

function loadTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}
