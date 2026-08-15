import { useCallback, useEffect, useRef, useState } from 'react'

import type { Bookcase, Underlay } from './core/model'
import {
  TURN,
  applyDefaultDepth,
  applyDefaultLevels,
  correctFront,
  emptyPlan,
  frontFor,
  newBookcase,
  planBounds,
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
import type { Doc, Selection, Theme, Tool } from './ui/types'
import { fitTo, initialView, type View } from './ui/viewport'

const STORAGE_KEY = 'booksnap.map-lab.doc'
const THEME_KEY = 'booksnap.map-lab.theme'

const emptyDoc = (): Doc => ({ plan: emptyPlan(), seq: 0 })

export default function App() {
  const [hist, setHist] = useState<History<Doc>>(() => initHistory(loadDoc()))
  const [tool, setTool] = useState<Tool>('select')
  const [theme, setTheme] = useState<Theme>(loadTheme)
  const [selection, setSelection] = useState<Selection>(null)
  const [view, setView] = useState<View>(initialView)
  const [message, setMessage] = useState<string | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)

  const doc = hist.present

  // --- persistence ---------------------------------------------------------

  useEffect(() => {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ plan: { ...doc.plan, underlay: null }, seq: doc.seq }),
      )
    } catch {
      /* a full or blocked localStorage must not break the editor */
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

  const update = useCallback(
    (fn: (d: Doc) => Doc) => setHist((h) => commit(h, fn(h.present))),
    [],
  )

  const mapCase = useCallback(
    (id: string, fn: (bc: Bookcase) => Bookcase) =>
      update((d) => ({
        ...d,
        plan: { ...d.plan, cases: d.plan.cases.map((c) => (c.id === id ? fn(c) : c)) },
      })),
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

  /** Moving a room takes its bookcases with it: furniture does not stay behind
   *  when a wall does not. Resizing it does not — the cases keep their places,
   *  and one that ends up outside says so. */
  const moveRoom = useCallback(
    (id: string, rect: Rect) =>
      update((d) => {
        const prev = d.plan.rooms.find((r) => r.id === id)
        if (!prev) return d
        const sameSize = prev.rect.w === rect.w && prev.rect.h === rect.h
        const dx = rect.x - prev.rect.x
        const dy = rect.y - prev.rect.y
        const rooms = d.plan.rooms.map((r) => (r.id === id ? { ...r, rect } : r))
        const plan = { ...d.plan, rooms }
        return {
          ...d,
          plan: {
            ...plan,
            cases: d.plan.cases.map((c) => {
              const moved =
                sameSize && c.roomId === id
                  ? { ...c, rect: { ...c.rect, x: c.rect.x + dx, y: c.rect.y + dy } }
                  : c
              const room = roomFor(plan, moved.rect)
              return correctFront({ ...moved, roomId: room?.id ?? null }, room)
            }),
          },
        }
      }),
    [update],
  )

  const moveCase = useCallback(
    (id: string, rect: Rect) =>
      update((d) => ({
        ...d,
        plan: {
          ...d.plan,
          cases: d.plan.cases.map((c) => {
            if (c.id !== id) return c
            const room = roomFor(d.plan, rect)
            return correctFront({ ...c, rect, roomId: room?.id ?? null }, room)
          }),
        },
      })),
    [update],
  )

  const actions: Actions = {
    renameRoom: (id, name) =>
      update((d) => ({
        ...d,
        plan: { ...d.plan, rooms: d.plan.rooms.map((r) => (r.id === id ? { ...r, name } : r)) },
      })),
    resizeRoom: (id, w, h) =>
      update((d) => ({
        ...d,
        plan: {
          ...d.plan,
          rooms: d.plan.rooms.map((r) =>
            r.id === id ? { ...r, rect: { ...r.rect, w: size(w), h: size(h) } } : r,
          ),
        },
      })),
    deleteRoom: (id) => {
      update((d) => ({
        ...d,
        plan: {
          ...d.plan,
          rooms: d.plan.rooms.filter((r) => r.id !== id),
          // Deleting a room does NOT cascade into its bookcases — the same
          // rule the product already holds for shelves. They stay where they
          // stand and simply belong to no room.
          cases: d.plan.cases.map((c) => (c.roomId === id ? { ...c, roomId: null } : c)),
        },
      }))
      setSelection(null)
    },
    renameCase: (id, name) => mapCase(id, (bc) => ({ ...bc, name })),
    resizeCase: (id, w, h) =>
      mapCase(id, (bc) => ({ ...bc, rect: { ...bc.rect, w: size(w), h: size(h) } })),
    deleteCase: (id) => {
      update((d) => ({ ...d, plan: { ...d.plan, cases: d.plan.cases.filter((c) => c.id !== id) } }))
      setSelection(null)
    },
    turnCase: (id) => mapCase(id, (bc) => ({ ...bc, front: TURN[bc.front] })),
    setColumnCount: (id, n) => mapCase(id, (bc) => withColumnCount(bc, n)),
    setColumnLevels: (id, col, n) => mapCase(id, (bc) => withColumnLevels(bc, col, n)),
    setDefaultLevels: (id, n) => mapCase(id, (bc) => withDefaultLevels(bc, n)),
    applyDefaultLevels: (id) => mapCase(id, applyDefaultLevels),
    setDefaultDepth: (id, n) => mapCase(id, (bc) => withDefaultDepth(bc, n)),
    applyDefaultDepth: (id) => mapCase(id, applyDefaultDepth),
    setShelfDepth: (id, col, level, n) => mapCase(id, (bc) => withShelfDepth(bc, col, level, n)),
    setShelfPhotos: (id, col, level, n) =>
      mapCase(id, (bc) => ({
        ...bc,
        shelves: bc.shelves.map((s) =>
          s.col === col && s.level === level ? { ...s, photos: Math.max(0, Math.round(n)) } : s,
        ),
      })),
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
  }

  const doImport = async (file: File) => {
    const result = parsePlan(await file.text())
    if (!result.ok) return say(`Not imported: ${result.error}.`)
    const maxSeq = [...result.plan.rooms, ...result.plan.cases].reduce((m, o) => {
      const n = Number(o.id.replace(/\D/g, ''))
      return Number.isFinite(n) ? Math.max(m, n) : m
    }, 0)
    setHist((h) => commit(h, { plan: result.plan, seq: maxSeq }))
    setSelection(null)
    say('Imported.')
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
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        setHist((h) => (e.shiftKey ? redo(h) : undo(h)))
        return
      }
      if (e.key === 'Escape' || e.key === '1') return setTool('select')
      if (e.key === '2') return setTool('room')
      if (e.key === '3') return setTool('case')
      if (e.key === '4') return setTool('pan')
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selection?.kind === 'room') actions.deleteRoom(selection.id)
        if (selection?.kind === 'case') actions.deleteCase(selection.id)
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
        underlay={doc.plan.underlay}
        canUndo={canUndo(hist)}
        canRedo={canRedo(hist)}
        onTool={setTool}
        onTheme={setTheme}
        onUndo={() => setHist(undo)}
        onRedo={() => setHist(redo)}
        onFit={doFit}
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
            setSelection(null)
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
            onMoveRoom={moveRoom}
            onMoveCase={moveCase}
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

function Hint({ tool }: { tool: Tool }) {
  const text =
    tool === 'room'
      ? 'Drag a rectangle to draw a room. Its edges snap to the grid — and to any room already there, so rooms attach.'
      : tool === 'case'
        ? 'Drag a rectangle inside a room. It snaps flush against the wall, and the books face into the room.'
        : tool === 'pan'
          ? 'Drag to slide the plan. Scroll or pinch to zoom.'
          : 'Drag a room or a bookcase to move it · drag a corner or an edge to resize · tap it to edit its settings.'
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
