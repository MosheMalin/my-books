import { useCallback, useEffect, useRef, useState } from 'react'

import type { Bookcase, Plan, Room, Underlay } from './core/model'
import {
  TURN,
  applyDefaultDepth,
  applyDefaultLevels,
  emptyPlan,
  frontFor,
  newBookcase,
  planBounds,
  reattach,
  roomFor,
  withColumnCount,
  withColumnLevels,
  withDefaultDepth,
  withDefaultLevels,
  withShelfDepth,
} from './core/model'
import type { Rect } from './core/rect'
import type { History } from './core/history'
import { canRedo, canUndo, commit, initHistory, redo, undo } from './core/history'
import { parsePlan, serializePlan } from './core/persist'
import { Inspector, type Actions } from './ui/Inspector'
import { PlanCanvas } from './ui/PlanCanvas'
import { Toolbar } from './ui/Toolbar'
import type { Clipboard, Doc, Selection, Theme, Tool } from './ui/types'
import { EMPTY, count, hasCase, hasRoom } from './ui/types'
import { fitTo, initialView, type View } from './ui/viewport'

const STORAGE_KEY = 'booksnap.map-lab.doc'
const THEME_KEY = 'booksnap.map-lab.theme'
/** How far a pasted copy lands from its original, in units. Far enough to see
 *  it, near enough to drag into place. */
const PASTE_OFFSET = 2

const emptyDoc = (): Doc => ({ plan: emptyPlan(), seq: 0 })

export default function App() {
  const [hist, setHist] = useState<History<Doc>>(() => initHistory(loadDoc()))
  const [tool, setTool] = useState<Tool>('select')
  const [theme, setTheme] = useState<Theme>(loadTheme)
  const [selection, setSelection] = useState<Selection>(EMPTY)
  const [clipboard, setClipboard] = useState<Clipboard>(null)
  const [view, setView] = useState<View>(initialView)
  const [message, setMessage] = useState<string | null>(null)
  const [saved, setSaved] = useState<'saving' | 'saved' | 'failed'>('saved')
  const wrapRef = useRef<HTMLDivElement | null>(null)

  const doc = hist.present

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

  const createRoom = useCallback(
    (rect: Rect) =>
      update((d) => {
        const seq = d.seq + 1
        return {
          seq,
          plan: { ...d.plan, rooms: d.plan.rooms.concat({ id: `r${seq}`, name: '', rect }) },
        }
      }),
    [update],
  )

  const createCase = useCallback(
    (rect: Rect) =>
      update((d) => {
        const seq = d.seq + 1
        const room = roomFor(d.plan, rect)
        const bc = newBookcase(`c${seq}`, '', rect, frontFor(rect, room), room?.id ?? null)
        return { seq, plan: { ...d.plan, cases: d.plan.cases.concat(bc) } }
      }),
    [update],
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
            cases: d.plan.cases.map((c) => (c.id === id ? reattach({ ...c, rect }, d.plan) : c)),
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
      return { ...r, id, rect: offset(r.rect) }
    })
    const cases: Bookcase[] = clipboard.cases.map((c) => {
      seq += 1
      return {
        ...c,
        id: `c${seq}`,
        rect: offset(c.rect),
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
  }, [clipboard, doc.seq, update])

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
      mapCase(id, (bc) => ({ ...bc, rect: { ...bc.rect, w: size(w), h: size(h) } }), `size:${id}`),
    setCaseRoom: (id, roomId) => mapCase(id, (bc) => ({ ...bc, roomId })),
    turnCase: (id) => mapCase(id, (bc) => ({ ...bc, front: TURN[bc.front] })),
    setColumnCount: (id, n) => mapCase(id, (bc) => withColumnCount(bc, n)),
    setColumnLevels: (id, col, n) => mapCase(id, (bc) => withColumnLevels(bc, col, n)),
    setDefaultLevels: (id, n) =>
      mapCase(id, (bc) => withDefaultLevels(bc, n), `deflevels:${id}`),
    applyDefaultLevels: (id) => mapCase(id, applyDefaultLevels),
    setDefaultDepth: (id, n) => mapCase(id, (bc) => withDefaultDepth(bc, n), `defdepth:${id}`),
    applyDefaultDepth: (id) => mapCase(id, applyDefaultDepth),
    setShelfDepth: (id, col, level, n) =>
      mapCase(id, (bc) => withShelfDepth(bc, col, level, n), `shelfdepth:${id}:${col}:${level}`),
    setShelfPhotos: (id, col, level, n) =>
      mapCase(
        id,
        (bc) => ({
          ...bc,
          shelves: bc.shelves.map((s) =>
            s.col === col && s.level === level ? { ...s, photos: Math.max(0, Math.round(n)) } : s,
          ),
        }),
        `shelfphotos:${id}:${col}:${level}`,
      ),
    deleteSelection,
    copySelection,
    paste,
    select: setSelection,
  }

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

  const doFit = useCallback(() => {
    const el = wrapRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const b = planBounds(doc.plan)
    if (b.min.x === b.max.x && b.min.y === b.max.y) return setView(initialView())
    setView(fitTo(b.min, b.max, { left: r.left, top: r.top, width: r.width, height: r.height }))
  }, [doc.plan])

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
        return setTool('select')
      }
      if (is('Digit1', '1')) return setTool('select')
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
            plan={doc.plan}
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
          />
          <Hint tool={tool} />
          {message && <div className="toast">{message}</div>}
        </div>
        <aside className="side">
          <Inspector doc={doc} selection={selection} actions={actions} />
        </aside>
      </main>
    </div>
  )
}

const size = (v: number): number => Math.max(1, Math.round(v))

const offset = (r: Rect): Rect => ({ ...r, x: r.x + PASTE_OFFSET, y: r.y + PASTE_OFFSET })

function Hint({ tool }: { tool: Tool }) {
  const text =
    tool === 'room'
      ? 'Drag a rectangle to draw a room. Its edges snap to the grid — and to any room already there, so rooms attach.'
      : tool === 'case'
        ? 'Drag a rectangle inside a room. It snaps flush against the wall, and the books face into the room.'
        : tool === 'pan'
          ? 'Drag to slide the plan. Scroll or pinch to zoom.'
          : 'Drag to move · drag a handle to resize · Ctrl+click adds to the selection · drag empty space to select several · Ctrl+C / Ctrl+V / Delete.'
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

function loadTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}
