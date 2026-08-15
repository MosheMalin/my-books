/**
 * The plan — top-down, SVG, pointer-driven. Everything on it is an
 * axis-aligned rectangle on the grid.
 *
 * ⚠ **Dragging empty space does NOT pan** (owner, 2026-08-16: *"the grid moves
 * when I drag it — it should not move"*). Panning is deliberate: the Pan tool,
 * the middle button, or two fingers. An editor whose background slides out
 * from under a mis-aimed drag feels broken even when nothing was damaged.
 *
 * Pinned LTR (MAP_PLAN §3.5): a floor plan does not mirror when the language
 * flips — the furniture did not move. Only labels follow the language, and
 * they carry `unicode-bidi: plaintext`.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { Pt } from '../core/geom'
import { GRID, GRID_MAJOR, dist } from '../core/geom'
import type { Bookcase, Plan, Room } from '../core/model'
import {
  columnDividers,
  depthLines,
  frontEdge,
  isTooSmall,
  maxDepth,
} from '../core/model'
import type { Handle, Rect } from '../core/rect'
import {
  bottom,
  center,
  contains,
  handleAt,
  handlePositions,
  rectFrom,
  right,
  snapPoint,
  snapRect,
} from '../core/rect'
import type { Selection, Tool } from './types'
import type { Rect as ScreenRect, View } from './viewport'
import { groupTransform, magnetUnits, toWorld, visibleBounds, zoomAbout } from './viewport'

type Props = {
  plan: Plan
  tool: Tool
  selection: Selection
  view: View
  onView: (v: View) => void
  onSelect: (s: Selection) => void
  onCreateRoom: (r: Rect) => void
  onCreateCase: (r: Rect) => void
  onMoveRoom: (id: string, r: Rect) => void
  onMoveCase: (id: string, r: Rect) => void
  onRejected: (reason: string) => void
}

type Drag =
  | null
  | { kind: 'pan'; from: Pt; view: View }
  | { kind: 'draw'; what: 'room' | 'case'; from: Pt; to: Pt }
  | { kind: 'move'; what: 'room' | 'case'; id: string; from: Pt; to: Pt; orig: Rect }
  | { kind: 'resize'; what: 'room' | 'case'; id: string; handle: Handle; to: Pt; orig: Rect }

export function PlanCanvas(props: Props) {
  const { plan, tool, selection, view } = props
  const svgRef = useRef<SVGSVGElement | null>(null)
  const [rect, setRect] = useState<ScreenRect>({ left: 0, top: 0, width: 800, height: 600 })
  const [drag, setDrag] = useState<Drag>(null)
  const pointers = useRef(new Map<number, Pt>())
  const pinch = useRef<{ d: number; scale: number } | null>(null)

  useLayoutEffect(() => {
    const el = svgRef.current
    if (!el) return
    const measure = () => {
      const r = el.getBoundingClientRect()
      setRect({ left: r.left, top: r.top, width: r.width, height: r.height })
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    window.addEventListener('scroll', measure, true)
    return () => {
      ro.disconnect()
      window.removeEventListener('scroll', measure, true)
    }
  }, [])

  const world = useCallback(
    (e: { clientX: number; clientY: number }): Pt =>
      toWorld({ x: e.clientX, y: e.clientY }, rect, view),
    [rect, view],
  )

  const magnet = magnetUnits(view)
  const selectedId = selection?.kind === 'room' ? selection.id : caseIdOf(selection)
  const selectedRoom = plan.rooms.find((r) => r.id === selectedId) ?? null
  const selectedCase = plan.cases.find((c) => c.id === selectedId) ?? null
  const selectedRect = selectedRoom?.rect ?? selectedCase?.rect ?? null

  /** What a drawn or moved rectangle should snap to. A room attaches to rooms;
   *  a bookcase attaches to the room it stands in and to its neighbours. */
  const targetsFor = (what: 'room' | 'case', exceptId?: string): Rect[] =>
    what === 'room'
      ? plan.rooms.filter((r) => r.id !== exceptId).map((r) => r.rect)
      : [
          ...plan.rooms.map((r) => r.rect),
          ...plan.cases.filter((c) => c.id !== exceptId).map((c) => c.rect),
        ]

  // --- picking -------------------------------------------------------------

  const grabHandle = (p: Pt): Handle | null =>
    selectedRect ? handleAt(selectedRect, p, magnet) : null

  const caseAt = (p: Pt): Bookcase | null => {
    for (let i = plan.cases.length - 1; i >= 0; i--) {
      const bc = plan.cases[i]!
      if (contains(bc.rect, p)) return bc
    }
    return null
  }

  const roomAt = (p: Pt): Room | null => {
    for (let i = plan.rooms.length - 1; i >= 0; i--) {
      const r = plan.rooms[i]!
      if (contains(r.rect, p)) return r
    }
    return null
  }

  // --- pointer -------------------------------------------------------------

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    try {
      ;(e.target as Element).setPointerCapture?.(e.pointerId)
    } catch {
      /* not capturable; the drag still works while the pointer stays inside */
    }
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      if (a && b) pinch.current = { d: dist(a, b), scale: view.scale }
      setDrag(null)
      return
    }
    const p = world(e)

    // Middle button pans from anywhere — the one shortcut, and it is one
    // nobody presses by accident.
    if (tool === 'pan' || e.button === 1) return setDrag({ kind: 'pan', from: p, view })
    if (tool === 'room') return setDrag({ kind: 'draw', what: 'room', from: p, to: p })
    if (tool === 'case') return setDrag({ kind: 'draw', what: 'case', from: p, to: p })

    const h = grabHandle(p)
    if (h && selectedRect) {
      const what = selectedCase ? 'case' : 'room'
      const id = selectedCase?.id ?? selectedRoom?.id
      if (id) return setDrag({ kind: 'resize', what, id, handle: h, to: p, orig: selectedRect })
    }

    const bc = caseAt(p)
    if (bc) {
      props.onSelect({ kind: 'case', id: bc.id })
      return setDrag({ kind: 'move', what: 'case', id: bc.id, from: p, to: p, orig: bc.rect })
    }
    const room = roomAt(p)
    if (room) {
      props.onSelect({ kind: 'room', id: room.id })
      return setDrag({ kind: 'move', what: 'room', id: room.id, from: p, to: p, orig: room.rect })
    }
    // Empty space: deselect, and NOTHING else. No pan (owner, 2026-08-16).
    props.onSelect(null)
  }

  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (pointers.current.has(e.pointerId)) {
      pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    }
    if (pointers.current.size === 2 && pinch.current) {
      const [a, b] = [...pointers.current.values()]
      if (!a || !b) return
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
      const factor = dist(a, b) / Math.max(1, pinch.current.d)
      props.onView(zoomAbout(view, toWorld(mid, rect, view), pinch.current.scale * factor))
      return
    }
    if (!drag) return
    const p = world(e)
    if (drag.kind === 'pan') {
      const v = drag.view
      props.onView({ ...view, cx: v.cx + (drag.from.x - p.x), cy: v.cy + (drag.from.y - p.y) })
      return
    }
    // ⚠ Functional update, not `{...drag, …}`. pointermove is a CONTINUOUS
    // event, so React batches a burst of them into one render and every
    // handler in that burst closes over the same stale `drag`.
    setDrag((prev) => (prev && prev.kind !== 'pan' ? { ...prev, to: p } : prev))
  }

  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    pointers.current.delete(e.pointerId)
    if (pointers.current.size < 2) pinch.current = null
    if (!drag) return
    // The release carries its OWN position, and it is not always the last
    // pointermove: lift fast and the browser coalesces the tail of the
    // gesture into the up event.
    const end = world(e)
    const d: Drag = drag.kind === 'pan' ? drag : { ...drag, to: end }
    setDrag(null)
    if (!d || d.kind === 'pan') return

    const r = resolve(d, plan, magnet, targetsFor)
    if (!r) return
    if (isTooSmall(r)) {
      return props.onRejected(
        d.kind === 'draw'
          ? `too small — drag out at least ${GRID} × ${GRID} squares`
          : 'that would leave nothing to see',
      )
    }
    if (d.kind === 'draw') {
      return d.what === 'room' ? props.onCreateRoom(r) : props.onCreateCase(r)
    }
    if (d.what === 'room') props.onMoveRoom(d.id, r)
    else props.onMoveCase(d.id, r)
  }

  const onWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    props.onView(zoomAbout(view, world(e), view.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15)))
  }

  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const stop = (ev: WheelEvent) => ev.preventDefault()
    el.addEventListener('wheel', stop, { passive: false })
    return () => el.removeEventListener('wheel', stop)
  }, [])

  // --- preview -------------------------------------------------------------

  const live = drag && drag.kind !== 'pan' ? resolve(drag, plan, magnet, targetsFor) : null
  const liveId = drag && drag.kind !== 'pan' && drag.kind !== 'draw' ? drag.id : null
  const bounds = visibleBounds(rect, view)
  const cursor = tool === 'pan' ? 'grab' : tool === 'select' ? 'default' : 'crosshair'

  return (
    <svg
      ref={svgRef}
      className="plan"
      style={{ cursor, touchAction: 'none' }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onWheel={onWheel}
      onContextMenu={(e) => e.preventDefault()}
      role="application"
      aria-label="floor plan"
    >
      <g transform={groupTransform(rect, view)}>
        <Grid min={bounds.min} max={bounds.max} scale={view.scale} />

        {plan.underlay && (
          <image
            href={plan.underlay.src}
            x={plan.underlay.x}
            y={plan.underlay.y}
            width={plan.underlay.scale}
            height={plan.underlay.scale / (plan.underlay.aspect || 1)}
            opacity={plan.underlay.opacity}
            preserveAspectRatio="none"
            pointerEvents="none"
          />
        )}

        {plan.rooms.map((r) => (
          <RoomShape
            key={r.id}
            room={r}
            rect={liveId === r.id && live ? live : r.rect}
            selected={selectedId === r.id}
          />
        ))}

        {plan.cases.map((bc) => (
          <CaseShape
            key={bc.id}
            bc={liveId === bc.id && live ? { ...bc, rect: live } : bc}
            selected={selectedId === bc.id}
          />
        ))}

        {drag?.kind === 'draw' && live && (
          <rect
            className={`preview-${drag.what}`}
            x={live.x}
            y={live.y}
            width={live.w}
            height={live.h}
          />
        )}

        {selectedRect && !drag && (
          <g className="handles">
            {handlePositions(selectedRect, magnet).map(({ h, at }) => (
              <rect
                key={`${h.hx},${h.hy}`}
                x={at.x - magnet * 0.45}
                y={at.y - magnet * 0.45}
                width={magnet * 0.9}
                height={magnet * 0.9}
              />
            ))}
          </g>
        )}
      </g>

      {/* The size readout lives in SCREEN space so it never scales away. */}
      {live && (
        <SizeBadge rect={live} screen={rect} view={view} />
      )}
    </svg>
  )
}

/** The rectangle a drag currently describes, snapped. One function for the
 *  live preview and for the commit, so what you see is what you get. */
function resolve(
  d: Exclude<Drag, null | { kind: 'pan'; from: Pt; view: View }>,
  _plan: Plan,
  magnet: number,
  targetsFor: (what: 'room' | 'case', exceptId?: string) => Rect[],
): Rect | null {
  if (d.kind === 'draw') {
    const targets = targetsFor(d.what)
    return rectFrom(snapPoint(d.from, targets, magnet), snapPoint(d.to, targets, magnet))
  }
  if (d.kind === 'move') {
    const moved = {
      ...d.orig,
      x: d.orig.x + (d.to.x - d.from.x),
      y: d.orig.y + (d.to.y - d.from.y),
    }
    return snapRect(moved, targetsFor(d.what, d.id), magnet)
  }
  const targets = targetsFor(d.what, d.id)
  const p = snapPoint(d.to, targets, magnet)
  const x0 = d.handle.hx === -1 ? p.x : d.orig.x
  const x1 = d.handle.hx === 1 ? p.x : right(d.orig)
  const y0 = d.handle.hy === -1 ? p.y : d.orig.y
  const y1 = d.handle.hy === 1 ? p.y : bottom(d.orig)
  return rectFrom({ x: x0, y: y0 }, { x: x1, y: y1 })
}

const caseIdOf = (s: Selection): string | null =>
  s?.kind === 'case' ? s.id : s?.kind === 'shelf' ? s.caseId : null

function Grid({ min, max, scale }: { min: Pt; max: Pt; scale: number }) {
  // Below ~7 px a cell the minor lines stop being a grid and become a texture.
  const step = scale < 7 ? GRID * GRID_MAJOR : GRID
  const lines: React.ReactElement[] = []
  for (let x = Math.floor(min.x / step) * step; x <= max.x; x += step) {
    lines.push(
      <line
        key={`x${x}`}
        className={Math.round(x) % GRID_MAJOR === 0 ? 'grid-major' : 'grid-minor'}
        x1={x}
        y1={min.y}
        x2={x}
        y2={max.y}
      />,
    )
  }
  for (let y = Math.floor(min.y / step) * step; y <= max.y; y += step) {
    lines.push(
      <line
        key={`y${y}`}
        className={Math.round(y) % GRID_MAJOR === 0 ? 'grid-major' : 'grid-minor'}
        x1={min.x}
        y1={y}
        x2={max.x}
        y2={y}
      />,
    )
  }
  return <g pointerEvents="none">{lines}</g>
}

function RoomShape({ room, rect, selected }: { room: Room; rect: Rect; selected: boolean }) {
  const c = center(rect)
  return (
    <g className={selected ? 'room selected' : 'room'}>
      <rect x={rect.x} y={rect.y} width={rect.w} height={rect.h} />
      <text className="room-label" x={c.x} y={c.y} textAnchor="middle">
        {room.name || `${rect.w}×${rect.h}`}
      </text>
    </g>
  )
}

function CaseShape({ bc, selected }: { bc: Bookcase; selected: boolean }) {
  const r = bc.rect
  const c = center(r)
  const f = frontEdge(bc)
  return (
    <g className={selected ? 'case selected' : 'case'}>
      <rect x={r.x} y={r.y} width={r.w} height={r.h} />
      {depthLines(bc).map((d, i) => (
        <line key={`d${i}`} className="case-depth" x1={d.a.x} y1={d.a.y} x2={d.b.x} y2={d.b.y} />
      ))}
      {columnDividers(bc).map((d, i) => (
        <line key={`c${i}`} className="case-divider" x1={d.a.x} y1={d.a.y} x2={d.b.x} y2={d.b.y} />
      ))}
      {/* the front face — which way the books look out */}
      <line className="case-front" x1={f.a.x} y1={f.a.y} x2={f.b.x} y2={f.b.y} />
      <text className="case-label" x={c.x} y={c.y} textAnchor="middle">
        {bc.name}
      </text>
      <title>
        {`${bc.name || 'bookcase'} · ${r.w}×${r.h} · ${bc.columnLevels.length} col · depth ≤${maxDepth(bc)}`}
      </title>
    </g>
  )
}

/** "12 × 8" beside the rectangle being drawn or dragged — the feedback that
 *  makes "control its size" true rather than aspirational. */
function SizeBadge({ rect, screen, view }: { rect: Rect; screen: ScreenRect; view: View }) {
  const x = (rect.x + rect.w / 2 - view.cx) * view.scale + screen.width / 2
  const y = (rect.y - view.cy) * view.scale + screen.height / 2 - 12
  return (
    <g className="size-badge" pointerEvents="none">
      <rect x={x - 28} y={y - 13} width={56} height={20} rx={5} />
      <text x={x} y={y + 1} textAnchor="middle" dominantBaseline="middle">
        {rect.w} × {rect.h}
      </text>
    </g>
  )
}
