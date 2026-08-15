import { useCallback, useEffect, useRef, useState } from 'react'

import type { Pt } from './core/geom'
import type { Bookcase, Underlay } from './core/model'
import {
  applyDefaultDepth,
  applyDefaultLevels,
  emptyPlan,
  newBookcase,
  planBounds,
  withColumnCount,
  withColumnLevels,
  withDefaultDepth,
  withDefaultLevels,
  withShelfDepth,
} from './core/model'
import type { History } from './core/history'
import { canRedo, canUndo, commit, initHistory, redo, undo } from './core/history'
import { parsePlan, serializePlan } from './core/persist'
import type { CasePlacement } from './core/snap'
import { Inspector, type Actions } from './ui/Inspector'
import { PlanCanvas } from './ui/PlanCanvas'
import { Toolbar } from './ui/Toolbar'
import type { Doc, Mode, Selection, Tool } from './ui/types'
import { fitTo, initialView, type View } from './ui/viewport'

const STORAGE_KEY = 'booksnap.map-lab.doc'

const emptyDoc = (): Doc => ({ plan: emptyPlan(), seq: 0 })

export default function App() {
  const [hist, setHist] = useState<History<Doc>>(() => initHistory(loadDoc()))
  const [mode, setMode] = useState<Mode>('D')
  const [tool, setTool] = useState<Tool>('select')
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

  // --- transient message ---------------------------------------------------

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
    (points: Pt[]) =>
      update((d) => {
        const seq = d.seq + 1
        return {
          seq,
          plan: {
            ...d.plan,
            rooms: d.plan.rooms.concat({ id: `r${seq}`, name: '', points }),
          },
        }
      }),
    [update],
  )

  const createCase = useCallback(
    (p: CasePlacement) =>
      update((d) => {
        const seq = d.seq + 1
        const bc = newBookcase(`c${seq}`, '', p.a, p.b, p.side, p.attach)
        return { seq, plan: { ...d.plan, cases: d.plan.cases.concat(bc) } }
      }),
    [update],
  )

  const replaceCase = useCallback(
    (id: string, p: CasePlacement) =>
      mapCase(id, (bc) => ({ ...bc, a: p.a, b: p.b, side: p.side, attach: p.attach })),
    [mapCase],
  )

  const moveRoom = useCallback(
    (id: string, delta: Pt) =>
      update((d) => ({
        ...d,
        plan: {
          ...d.plan,
          rooms: d.plan.rooms.map((r) =>
            r.id === id
              ? { ...r, points: r.points.map((p) => ({ x: p.x + delta.x, y: p.y + delta.y })) }
              : r,
          ),
          // A room that moves takes its wall-mounted cases with it: furniture
          // does not stay behind when a wall does not.
          cases: d.plan.cases.map((c) =>
            c.attach?.roomId === id
              ? {
                  ...c,
                  a: { x: c.a.x + delta.x, y: c.a.y + delta.y },
                  b: { x: c.b.x + delta.x, y: c.b.y + delta.y },
                }
              : c,
          ),
        },
      })),
    [update],
  )

  const actions: Actions = {
    renameRoom: (id, name) =>
      update((d) => ({
        ...d,
        plan: {
          ...d.plan,
          rooms: d.plan.rooms.map((r) => (r.id === id ? { ...r, name } : r)),
        },
      })),
    deleteRoom: (id) => {
      update((d) => ({
        ...d,
        plan: {
          ...d.plan,
          rooms: d.plan.rooms.filter((r) => r.id !== id),
          // Deleting a room does NOT cascade into its bookcases — same rule
          // the product already holds for shelves. They detach and stay.
          cases: d.plan.cases.map((c) =>
            c.attach?.roomId === id ? { ...c, attach: null } : c,
          ),
        },
      }))
      setSelection(null)
    },
    renameCase: (id, name) => mapCase(id, (bc) => ({ ...bc, name })),
    deleteCase: (id) => {
      update((d) => ({ ...d, plan: { ...d.plan, cases: d.plan.cases.filter((c) => c.id !== id) } }))
      setSelection(null)
    },
    flipCase: (id) => mapCase(id, (bc) => ({ ...bc, side: bc.side === 1 ? -1 : 1 })),
    detachCase: (id) => mapCase(id, (bc) => ({ ...bc, attach: null })),
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
          s.col === col && s.level === level
            ? { ...s, photos: Math.max(0, Math.round(n)) }
            : s,
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
          scale: 40,
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
      const meta = e.metaKey || e.ctrlKey
      if (meta && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        setHist((h) => (e.shiftKey ? redo(h) : undo(h)))
        return
      }
      if (e.key === 'Escape') return setTool('select')
      if (e.key === '1') return setTool('select')
      if (e.key === '2') return setTool(mode === 'D' ? 'room' : 'draw')
      if (e.key === '3' && mode === 'D') return setTool('case')
      if (e.key === '4') return setTool('pan')
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selection?.kind === 'room') actions.deleteRoom(selection.id)
        if (selection?.kind === 'case') actions.deleteCase(selection.id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // Switching mode resets the tool: mode D has no Draw and mode S has no Room,
  // so keeping the old tool would leave a dead pointer.
  useEffect(() => {
    setTool('select')
  }, [mode])

  return (
    <div className="app">
      <Toolbar
        mode={mode}
        tool={tool}
        underlay={doc.plan.underlay}
        canUndo={canUndo(hist)}
        canRedo={canRedo(hist)}
        onMode={setMode}
        onTool={setTool}
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
        {/* dir=ltr: the plan is pinned LTR (MAP_PLAN §3.5) — the furniture
            does not move when the language flips. Labels inside it carry
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
            onReplaceCase={replaceCase}
            onMoveRoom={moveRoom}
            onRejected={say}
          />
          <Hint mode={mode} tool={tool} />
          {message && <div className="toast">{message}</div>}
        </div>
        <aside className="side">
          <Inspector doc={doc} selection={selection} actions={actions} />
        </aside>
      </main>
    </div>
  )
}

function Hint({ mode, tool }: { mode: Mode; tool: Tool }) {
  const text =
    mode === 'S'
      ? tool === 'draw'
        ? 'Draw freehand. A stroke that closes becomes a room; one that does not becomes a bookcase — straightened when you lift.'
        : 'Mode S: the stroke is read after you lift. Pick Draw.'
      : tool === 'room'
        ? 'Drag a room. Corners weld onto existing corners, so two rooms share a wall exactly.'
        : tool === 'case'
          ? 'Drag ALONG a wall. The case lands on it, as long as you dragged.'
          : 'Tap a room or a bookcase. Drag a bookcase to slide it along its wall; drag an end handle to change its length.'
  return <p className="hint">{text}</p>
}

function loadDoc(): Doc {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return emptyDoc()
    const parsed = parsePlan(
      JSON.stringify({ format: 'booksnap.map-lab.plan', version: 1, plan: JSON.parse(raw).plan }),
    )
    if (!parsed.ok) return emptyDoc()
    const seq = Number(JSON.parse(raw).seq)
    return { plan: parsed.plan, seq: Number.isFinite(seq) ? seq : 0 }
  } catch {
    return emptyDoc()
  }
}
