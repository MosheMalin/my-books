import { useCallback, useEffect, useRef, useState } from 'react'

import type { Bookcase, Floor, Plan, Room, Underlay } from './core/model'
import {
  TURN,
  addSection,
  casesOn,
  floorContents,
  applyDefaultDepth,
  applyDefaultLevels,
  emptyPlan,
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
  withDefaultLevels,
  withRect,
  withShelfDepth,
  withShelfPhotos,
} from './core/model'
import type { Rect } from './core/rect'
import type { History } from './core/history'
import { canRedo, canUndo, commit, initHistory, redo, undo } from './core/history'
import { parsePlan, serializePlan } from './core/persist'
import { FloorBadge } from './ui/FloorBadge'
import { Inspector, type Actions } from './ui/Inspector'
import { PlanCanvas } from './ui/PlanCanvas'
import { Toolbar } from './ui/Toolbar'
import type { Clipboard, Doc, Selection, Theme, Tool } from './ui/types'
import { EMPTY, count, hasCase, hasRoom, selectCase, selectRoom } from './ui/types'
import { fitTo, initialView, zoomAbout, type View } from './ui/viewport'

const STORAGE_KEY = 'booksnap.map-lab.doc'
const THEME_KEY = 'booksnap.map-lab.theme'
const FLOOR_KEY = 'booksnap.map-lab.floor'
const SIDE_KEY = 'booksnap.map-lab.side'
const SIDE_MIN = 220
const SIDE_MAX = 720
const clampSide = (w: number) => Math.max(SIDE_MIN, Math.min(SIDE_MAX, Math.round(w)))
/** How far a pasted copy lands from its original, in units. Far enough to see
 *  it, near enough to drag into place. */
const PASTE_OFFSET = 2

const emptyDoc = (): Doc => ({ plan: emptyPlan(), seq: 0 })

export default function App() {
  const [hist, setHist] = useState<History<Doc>>(() => initHistory(loadDoc()))
  const [tool, setTool] = useState<Tool>('auto')
  const [theme, setTheme] = useState<Theme>(loadTheme)
  const [selection, setSelection] = useState<Selection>(EMPTY)
  const [floorPick, setFloorPick] = useState<string>(loadFloor)
  const [clipboard, setClipboard] = useState<Clipboard>(null)
  const [view, setView] = useState<View>(initialView)
  const [message, setMessage] = useState<string | null>(null)
  const [ghosts, setGhosts] = useState(false)
  const [allFloors, setAllFloors] = useState(false)
  /** Which object the canvas asked to have renamed. The panel opens its fold
   *  and puts the caret in the name box — one editor, not two. */
  const [renaming, setRenaming] = useState<{ kind: 'room' | 'case'; id: string } | null>(null)
  const [sideWidth, setSideWidth] = useState<number>(loadSideWidth)
  const [saved, setSaved] = useState<'saving' | 'saved' | 'failed'>('saved')
  const wrapRef = useRef<HTMLDivElement | null>(null)

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
   * work will not get lost"*). The toolbar SAYS so, because an autosave nobody
   * can see is indistinguishable from no autosave — and the honest caveat is
   * on the same line: this is browser storage, and *Save to file* is the copy
   * that survives a cleared browser.
   */
  useEffect(() => {
    setSaved('saving')
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ plan: { ...doc.plan, underlay: null }, seq: doc.seq }),
      )
      setSaved('saved')
    } catch {
      setSaved('failed')
    }
  }, [doc])

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDE_KEY, String(sideWidth))
    } catch {
      /* ignore */
    }
  }, [sideWidth])

  useEffect(() => {
    try {
      window.localStorage.setItem(FLOOR_KEY, floorId)
    } catch {
      /* ignore */
    }
  }, [floorId])

  useEffect(() => {
    document.documentElement.dataset['theme'] = theme
    try {
      window.localStorage.setItem(THEME_KEY, theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  const say = useCallback((text: string) => {
    setMessage(text)
    window.setTimeout(() => setMessage((m) => (m === text ? null : m)), 2600)
  }, [])

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

  const deleteSelection = useCallback(() => {
    if (count(selection) === 0) return
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
  }, [selection, update])

  // --- copy / paste --------------------------------------------------------

  const copySelection = useCallback(() => {
    const rooms = doc.plan.rooms.filter((r) => hasRoom(selection, r.id))
    const cases = doc.plan.cases.filter((c) => hasCase(selection, c.id))
    if (rooms.length + cases.length === 0) return
    // Deep-cloned at COPY time: a later edit to the original must not reach
    // into the clipboard, and a paste must not alias the shelves it came from.
    setClipboard(JSON.parse(JSON.stringify({ rooms, cases })) as Clipboard)
    say(`Copied ${rooms.length + cases.length} item${rooms.length + cases.length > 1 ? 's' : ''}.`)
  }, [doc.plan, selection, say])

  const paste = useCallback(() => {
    if (!clipboard) return
    let seq = doc.seq
    const roomIdMap = new Map<string, string>()
    const rooms: Room[] = clipboard.rooms.map((r) => {
      seq += 1
      const id = `r${seq}`
      roomIdMap.set(r.id, id)
      // Onto the storey you are LOOKING at — copying the ground floor's layout
      // as a starting point for the first floor is the obvious use.
      return { ...r, id, rect: offset(r.rect), floorId }
    })
    const cases: Bookcase[] = clipboard.cases.map((c) => {
      seq += 1
      return {
        ...c,
        id: `c${seq}`,
        rect: offset(c.rect),
        floorId,
        // A case copied together with its room stays with THAT copy, not with
        // the original room — otherwise pasting a room-and-its-cases produces
        // furniture that moves when the wrong room moves.
        roomId: c.roomId ? roomIdMap.get(c.roomId) ?? c.roomId : null,
      }
    })
    update((d) => ({
      seq,
      plan: {
        ...d.plan,
        rooms: d.plan.rooms.concat(rooms),
        cases: d.plan.cases
          .concat(cases)
          .map((c) => (cases.some((n) => n.id === c.id) && !c.roomId ? reattach(c, d.plan) : c)),
      },
    }))
    setSelection({ rooms: rooms.map((r) => r.id), cases: cases.map((c) => c.id), shelf: null })
  }, [clipboard, doc.seq, update, floorId])

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
    setColumnCount: (id, sid, n) => mapCase(id, (bc) => mapSection(bc, sid, (s) => withColumnCount(s, n))),
    setColumnLevels: (id, sid, col, n) =>
      mapCase(id, (bc) => mapSection(bc, sid, (s) => withColumnLevels(s, col, n))),
    setDefaultLevels: (id, sid, n) =>
      mapCase(id, (bc) => mapSection(bc, sid, (s) => withDefaultLevels(s, n)), `deflevels:${sid}`),
    applyDefaultLevels: (id, sid) => mapCase(id, (bc) => mapSection(bc, sid, applyDefaultLevels)),
    setDefaultDepth: (id, sid, n) =>
      mapCase(id, (bc) => mapSection(bc, sid, (s) => withDefaultDepth(s, n)), `defdepth:${sid}`),
    applyDefaultDepth: (id, sid) => mapCase(id, (bc) => mapSection(bc, sid, applyDefaultDepth)),
    setShelfDepth: (id, sid, col, level, n) =>
      mapCase(
        id,
        (bc) => mapSection(bc, sid, (s) => withShelfDepth(s, col, level, n)),
        `shelfdepth:${sid}:${col}:${level}`,
      ),
    setShelfPhotos: (id, sid, col, level, n) =>
      mapCase(
        id,
        (bc) => mapSection(bc, sid, (s) => withShelfPhotos(s, col, level, n)),
        `shelfphotos:${sid}:${col}:${level}`,
      ),
    addSection: (id, where) => mapCase(id, (bc) => addSection(bc, where)),
    removeSection: (id, sid) => {
      mapCase(id, (bc) => removeSection(bc, sid))
      // The selected cell may have been inside it. Dropping the shelf while
      // keeping the case selected is the least surprising landing.
      setSelection((sel) => (sel.shelf?.sectionId === sid ? { ...sel, shelf: null } : sel))
    },
    deleteSelection,
    copySelection,
    paste,
    select: setSelection,
  }

  /** Double-click on the plan: select it and ask the panel to start editing. */
  const beginRename = useCallback((kind: 'room' | 'case', id: string) => {
    setSelection(kind === 'room' ? selectRoom(id) : selectCase(id))
    setRenaming({ kind, id })
  }, [])

  // --- floors --------------------------------------------------------------

  const addFloor = useCallback(() => {
    const n = doc.plan.floors.length + 1
    const floor: Floor = { id: `f${n}`, name: `Floor ${n}` }
    update((d) => ({ ...d, plan: { ...d.plan, floors: d.plan.floors.concat(floor) } }))
    setFloorPick(floor.id)
    setSelection(EMPTY)
  }, [doc.plan.floors.length, update])

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
    if (doc.plan.floors.length <= 1) return say('A plan has at least one floor.')
    const { rooms, cases } = floorContents(doc.plan, floorId)
    if (rooms + cases > 0) {
      const parts = [
        rooms > 0 ? `${rooms} room${rooms > 1 ? 's' : ''}` : '',
        cases > 0 ? `${cases} bookcase${cases > 1 ? 's' : ''}` : '',
      ].filter(Boolean)
      return say(`Not removed — ${parts.join(' and ')} still on this floor.`)
    }
    update((d) => ({ ...d, plan: { ...d.plan, floors: d.plan.floors.filter((f) => f.id !== floorId) } }))
    setFloorPick(doc.plan.floors.find((f) => f.id !== floorId)!.id)
  }, [doc.plan, floorId, update, say])

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
        say('Traced sketch loaded — draw over it, then remove it.')
      }
      img.onerror = () => say('That file did not decode as an image.')
      img.src = src
    }
    reader.onerror = () => say('Could not read that file.')
    reader.readAsDataURL(file)
  }

  // --- files ---------------------------------------------------------------

  const doExport = () => {
    const blob = new Blob([serializePlan(doc.plan)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'house.map-lab.json'
    a.click()
    URL.revokeObjectURL(url)
    say('Saved to your downloads folder.')
  }

  const doImport = async (file: File) => {
    const result = parsePlan(await file.text())
    if (!result.ok) return say(`Not opened: ${result.error}.`)
    const maxSeq = [...result.plan.rooms, ...result.plan.cases].reduce((m, o) => {
      const n = Number(o.id.replace(/\D/g, ''))
      return Number.isFinite(n) ? Math.max(m, n) : m
    }, 0)
    setHist((h) => commit(h, { plan: result.plan, seq: maxSeq }))
    setSelection(EMPTY)
    say('Opened.')
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
    <div className="app">
      <Toolbar
        tool={tool}
        theme={theme}
        ghosts={ghosts}
        allFloors={allFloors}
        manyFloors={doc.plan.floors.length > 1}
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
        onFit={doFit}
        onCopy={copySelection}
        onPaste={paste}
        onDelete={deleteSelection}
        onExport={doExport}
        onImport={doImport}
        onUnderlay={loadUnderlay}
        onUnderlayChange={(patch) =>
          setUnderlay(doc.plan.underlay ? { ...doc.plan.underlay, ...patch } : null)
        }
        onUnderlayClear={() => setUnderlay(null)}
        onClear={() => {
          if (confirm('Throw away this drawing?')) {
            setHist((h) => commit(h, emptyDoc()))
            setSelection(EMPTY)
          }
        }}
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
          <Hint tool={tool} overview={overview} />
          <FloorBadge
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
          />
          {message && <div className="toast">{message}</div>}
        </div>
        {/* Drag to widen the settings. The elevation of a wide bookcase wants
            the room, and 330 px is a guess about someone else's screen. */}
        <div
          className="resizer"
          role="separator"
          aria-label="drag to resize the settings panel"
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
              setSideWidth(clampSide(startW + (startX - ev.clientX)))
            }
            const up = () => {
              window.removeEventListener('pointermove', move)
              window.removeEventListener('pointerup', up)
            }
            window.addEventListener('pointermove', move)
            window.addEventListener('pointerup', up)
          }}
        />
        <aside className="side" style={{ width: sideWidth, flexBasis: sideWidth }}>
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

const offset = (r: Rect): Rect => ({ ...r, x: r.x + PASTE_OFFSET, y: r.y + PASTE_OFFSET })

function Hint({ tool, overview }: { tool: Tool; overview: boolean }) {
  if (overview) {
    return <p className="hint">Every floor, side by side. Double-click one to work on it.</p>
  }
  const text =
    tool === 'room'
      ? 'Drag a rectangle to draw a room. Its edges snap to the grid — and to any room already there, so rooms attach.'
      : tool === 'case'
        ? 'Drag a rectangle inside a room. It snaps flush against the wall, and the books face into the room.'
        : tool === 'pan'
          ? 'Drag to slide the plan. Scroll or pinch to zoom.'
          : 'A room’s border moves it · inside a room draws a bookcase · outside draws a room · double-click to name · Ctrl+drag selects several.'
  return <p className="hint">{text}</p>
}

function loadDoc(): Doc {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return emptyDoc()
    const stored = JSON.parse(raw)
    const parsed = parsePlan(
      JSON.stringify({ format: 'booksnap.map-lab.plan', version: 2, plan: stored.plan }),
    )
    if (!parsed.ok) return emptyDoc()
    const seq = Number(stored.seq)
    return { plan: parsed.plan, seq: Number.isFinite(seq) ? seq : 0 }
  } catch {
    return emptyDoc()
  }
}

function loadSideWidth(): number {
  try {
    const raw = Number(window.localStorage.getItem(SIDE_KEY))
    return Number.isFinite(raw) && raw > 0 ? clampSide(raw) : 330
  } catch {
    return 330
  }
}

function loadFloor(): string {
  try {
    return window.localStorage.getItem(FLOOR_KEY) ?? 'f1'
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
