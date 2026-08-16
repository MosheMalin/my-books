/**
 * The plan — top-down, SVG, pointer-driven. Everything on it is an
 * axis-aligned rectangle on the grid.
 *
 * ⚠ **Dragging empty space does NOT pan** (owner, 2026-08-16: *"the grid moves
 * when I drag it — it should not move"*). It draws a selection band. Panning is
 * deliberate: the Pan tool, the middle button, or two fingers.
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
  casesOn,
  columnDividers,
  depthLines,
  frontEdge,
  isTooSmall,
  maxDepth,
  overviewLayout,
  roomsOn,
} from '../core/model'
import type { Handle, Rect } from '../core/rect'
import {
  bottom,
  center,
  contains,
  handleAt,
  nearBorder,
  handlePositions,
  intersects,
  rectFrom,
  right,
  snapCorner,
  snapPoint,
  snapRect,
} from '../core/rect'
import type { Selection, Tool } from './types'
import { EMPTY, count, hasCase, hasRoom, only, selectCase, selectRoom, toggle } from './types'
import type { Rect as ScreenRect, View } from './viewport'
import {
  borderInner,
  borderOuter,
  groupTransform,
  magnetUnits,
  toWorld,
  visibleBounds,
  zoomAbout,
} from './viewport'

type Kind = 'room' | 'case'

type Props = {
  plan: Plan
  /** Rooms on the OTHER storeys, drawn faintly and untouchable. Aligning a
   *  bookcase over the stairwell below is the whole reason to want them. */
  ghosts: Room[]
  tool: Tool
  selection: Selection
  view: View
  onView: (v: View) => void
  onSelect: (s: Selection) => void
  onCreateRoom: (r: Rect) => void
  onCreateCase: (r: Rect) => void
  onMoveSelection: (dx: number, dy: number) => void
  onResize: (kind: Kind, id: string, r: Rect) => void
  onRejected: (reason: string) => void
  /** Double-click on a room or bookcase — the fluent way to name one. */
  onRename: (kind: Kind, id: string) => void
  /** Every storey at once, read-only; double-clicking one focuses it. */
  overview: { plan: Plan; onFocus: (floorId: string) => void } | null
}

type Drag =
  | null
  | { kind: 'pan'; from: Pt; view: View }
  | { kind: 'draw'; what: Kind; from: Pt; to: Pt }
  | { kind: 'move'; what: Kind; id: string; from: Pt; to: Pt; orig: Rect }
  | { kind: 'resize'; what: Kind; id: string; handle: Handle; to: Pt; orig: Rect }
  | { kind: 'band'; from: Pt; to: Pt; add: boolean }

export function PlanCanvas(props: Props) {
  const { plan, tool, selection, view } = props
  const svgRef = useRef<SVGSVGElement | null>(null)
  const [rect, setRect] = useState<ScreenRect>({ left: 0, top: 0, width: 800, height: 600 })
  const [drag, setDrag] = useState<Drag>(null)
  const [hover, setHover] = useState<'move' | 'room' | 'case'>('room')
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
  const inner = borderInner(view)
  const outer = borderOuter(view)


  /** The room whose border is under `p` — checked against every room rather
   *  than only the one containing it, so the band works from OUTSIDE too. */
  const roomBorderAt = (p: Pt): Room | null => {
    for (let i = plan.rooms.length - 1; i >= 0; i--) {
      const r = plan.rooms[i]!
      if (nearBorder(r.rect, p, inner, outer)) return r
    }
    return null
  }
  /** Handles belong to a single selection. Eight grips on each of six selected
   *  rooms is a field of dots, and every one of them is ambiguous. */
  const lone = only(selection, plan)
  const loneRect = lone?.rect ?? null

  /**
   * ⚠ A handle grabs what it DRAWS, and no more — and never more than a third
   * of the shape it sits on.
   *
   * It used a full magnet (14 px, nearly twice the drawn square), so the grips
   * of a selected room claimed a wide dead zone along its walls and starting a
   * bookcase flush against one resized the room instead. The second clause
   * matters just as much: a bookcase is ONE unit deep, so at a fixed size its
   * top and bottom grips met in the middle and the case had no body left to
   * pick up by.
   */
  const gripFor = (r: Rect): number =>
    Math.min(magnet * 0.5, Math.min(r.w, r.h) / 3)
  const grip = loneRect ? gripFor(loneRect) : magnet * 0.5

  const targetsFor = (what: Kind, exceptId?: string): Rect[] =>
    what === 'room'
      ? plan.rooms.filter((r) => r.id !== exceptId).map((r) => r.rect)
      : [
          ...plan.rooms.map((r) => r.rect),
          ...plan.cases.filter((c) => c.id !== exceptId).map((c) => c.rect),
        ]

  /**
   * What a drag starting here would DO. One function, so the cursor, the hint
   * and the pointer handler can never disagree about it.
   */
  /**
   * What a drag starting here would DO. One function, so the cursor, the hint
   * and the pointer handler can never disagree — and one order, which is the
   * whole rule (owner, 2026-08-16):
   *
   *   a handle of the selected thing  → resize
   *   INSIDE a bookcase               → move it, always, in every tool
   *   on a room's border              → move that room
   *   the tool, if one is held        → draw that
   *   inside a room                   → draw a bookcase
   *   outside every room              → draw a room
   */
  const intentAt = (p: Pt): 'move' | 'room' | 'case' => {
    if (tool === 'pan') return 'move'
    if (loneRect && handleAt(loneRect, p, grip)) return 'move'
    // Nobody draws a bookcase inside a bookcase, so its interior is never
    // anything but a grip — in the drawing tools too.
    if (caseAt(p)) return 'move'
    if (roomBorderAt(p)) return 'move'
    if (tool !== 'auto') return tool
    return roomAt(p) ? 'case' : 'room'
  }

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
    const add = e.ctrlKey || e.metaKey || e.shiftKey

    if (tool === 'pan' || e.button === 1) return setDrag({ kind: 'pan', from: p, view })
    if (props.overview) return setDrag({ kind: 'pan', from: p, view })

    // Handles and borders come FIRST, whatever tool is held.
    if (loneRect && !add) {
      const h = handleAt(loneRect, p, grip)
      if (h) {
        const what: Kind = plan.cases.some((c) => c.id === lone?.id) ? 'case' : 'room'
        const id = lone?.id
        if (id) return setDrag({ kind: 'resize', what, id, handle: h, to: p, orig: loneRect })
      }
    }
    // A bookcase's interior grabs it in EVERY tool.
    const bc = caseAt(p)
    if (bc) {
      if (add) return props.onSelect(toggle(selection, 'case', bc.id))
      if (!hasCase(selection, bc.id)) props.onSelect(selectCase(bc.id))
      return setDrag({ kind: 'move', what: 'case', id: bc.id, from: p, to: p, orig: bc.rect })
    }
    const border = roomBorderAt(p)
    if (border && !add) {
      if (!hasRoom(selection, border.id)) props.onSelect(selectRoom(border.id))
      return setDrag({
        kind: 'move',
        what: 'room',
        id: border.id,
        from: p,
        to: p,
        orig: border.rect,
      })
    }
    if (tool !== 'auto') return setDrag({ kind: 'draw', what: tool, from: p, to: p })

    const room = roomAt(p)
    if (room && add) return props.onSelect(toggle(selection, 'room', room.id))
    // ⚠ Ctrl/Shift claims the band, because a plain drag on empty canvas now
    // DRAWS. Selecting several is the rarer act, so it is the one that pays a
    // modifier.
    if (add) return setDrag({ kind: 'band', from: p, to: p, add })
    if (room) {
      props.onSelect(selectRoom(room.id))
      return setDrag({ kind: 'draw', what: 'case', from: p, to: p })
    }
    props.onSelect(EMPTY)
    setDrag({ kind: 'draw', what: 'room', from: p, to: p })
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
    if (!drag) {
      // Only when the ANSWER changes, not on every pixel: this runs on every
      // pointermove and a re-render per pixel is a lot of nothing.
      if (tool !== 'pan' && !props.overview) {
        const next = intentAt(world(e))
        setHover((h) => (h === next ? h : next))
      }
      return
    }
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

    if (d.kind === 'band') {
      const band = rectFrom(d.from, d.to)
      // A band with no area is a click on nothing, which already cleared the
      // selection on the way down. Selecting everything would be a surprise.
      if (band.w < 0.3 && band.h < 0.3) return
      const rooms = plan.rooms.filter((r) => intersects(band, r.rect)).map((r) => r.id)
      const cases = plan.cases.filter((c) => intersects(band, c.rect)).map((c) => c.id)
      return props.onSelect(
        d.add
          ? {
              rooms: [...new Set([...selection.rooms, ...rooms])],
              cases: [...new Set([...selection.cases, ...cases])],
              shelf: null,
            }
          : { rooms, cases, shelf: null },
      )
    }

    const r = resolve(d, magnet, targetsFor)
    if (!r) return
    if (isTooSmall(r)) {
      // In `auto` a tap is not a failed drawing, it is a tap: select whatever
      // is under it and say nothing. Complaining about a click would make the
      // fluent mode the noisiest one.
      if (d.kind === 'draw' && tool === 'auto') {
        const bc = caseAt(end)
        const room = roomAt(end)
        return props.onSelect(bc ? selectCase(bc.id) : room ? selectRoom(room.id) : EMPTY)
      }
      return props.onRejected(
        d.kind === 'draw'
          ? `too small — drag out at least ${GRID} × ${GRID} squares`
          : 'that would leave nothing to see',
      )
    }
    if (d.kind === 'draw') {
      return d.what === 'room' ? props.onCreateRoom(r) : props.onCreateCase(r)
    }
    if (d.kind === 'move') {
      const dx = r.x - d.orig.x
      const dy = r.y - d.orig.y
      if (dx !== 0 || dy !== 0) props.onMoveSelection(dx, dy)
      return
    }
    props.onResize(d.what, d.id, r)
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

  const live =
    drag && drag.kind !== 'pan' && drag.kind !== 'band' ? resolve(drag, magnet, targetsFor) : null
  const moveDelta =
    drag?.kind === 'move' && live ? { dx: live.x - drag.orig.x, dy: live.y - drag.orig.y } : null
  const band = drag?.kind === 'band' ? rectFrom(drag.from, drag.to) : null
  const bounds = visibleBounds(rect, view)
  // ⚠ `hover` decides in EVERY drawing tool, not only the arrow. It read the
  // tool first, so an edge that was genuinely grabbable still showed a
  // crosshair — the behaviour was right and the only thing telling the user
  // about it was wrong.
  const cursor = props.overview
    ? 'pointer'
    : tool === 'pan'
      ? 'grab'
      : hover === 'move'
        ? 'move'
        : 'crosshair'

  /** Where a rectangle sits RIGHT NOW, mid-drag. Everything that travels with
   *  the selection previews together, or a multi-move looks broken until the
   *  mouse comes up. */
  const shown = (id: string, kind: Kind, r: Rect): Rect => {
    if (drag?.kind === 'resize' && drag.id === id && live) return live
    if (!moveDelta) return r
    const travelling =
      kind === 'room'
        ? hasRoom(selection, id)
        : hasCase(selection, id) ||
          plan.rooms.some(
            (room) =>
              hasRoom(selection, room.id) &&
              plan.cases.find((c) => c.id === id)?.roomId === room.id,
          )
    return travelling ? { ...r, x: r.x + moveDelta.dx, y: r.y + moveDelta.dy } : r
  }

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
      onDoubleClick={(e) => {
        const p = world(e)
        if (props.overview) {
          const hit = overviewLayout(props.overview.plan).find(
            (f) => p.y >= f.bandStart - 3 && p.y <= f.bandStart + f.band + 3,
          )
          if (hit) props.overview.onFocus(hit.floor.id)
          return
        }
        const bc = caseAt(p)
        if (bc) return props.onRename('case', bc.id)
        const room = roomAt(p)
        if (room) props.onRename('room', room.id)
      }}
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

        {props.overview &&
          overviewLayout(props.overview.plan).map(({ floor, dx, dy, bandStart, width }, i) => (
            <g key={floor.id} className="storey">
              <text className="storey-label" x={0} y={bandStart - 1} textAnchor="start">
                {floor.name}
              </text>
              {i > 0 && (
                <line
                  className="storey-rule"
                  x1={-4}
                  y1={bandStart - 3}
                  x2={width + 4}
                  y2={bandStart - 3}
                />
              )}
              <g transform={`translate(${dx} ${dy})`}>
                {roomsOn(props.overview!.plan, floor.id).map((r) => (
                  <RoomShape key={r.id} room={r} rect={r.rect} selected={false} />
                ))}
                {casesOn(props.overview!.plan, floor.id).map((bc) => (
                  <CaseShape key={bc.id} bc={bc} selected={false} />
                ))}
              </g>
            </g>
          ))}

        {props.ghosts.map((r) => (
          <rect
            key={`ghost-${r.id}`}
            className="ghost"
            x={r.rect.x}
            y={r.rect.y}
            width={r.rect.w}
            height={r.rect.h}
          />
        ))}

        {!props.overview && plan.rooms.map((r) => (
          <RoomShape
            key={r.id}
            room={r}
            rect={shown(r.id, 'room', r.rect)}
            selected={hasRoom(selection, r.id)}
          />
        ))}

        {!props.overview && plan.cases.map((bc) => (
          <CaseShape
            key={bc.id}
            bc={{ ...bc, rect: shown(bc.id, 'case', bc.rect) }}
            selected={hasCase(selection, bc.id)}
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

        {band && (
          <rect className="band" x={band.x} y={band.y} width={band.w} height={band.h} />
        )}

        {loneRect && !drag && tool !== 'pan' && !props.overview && (
          <g className="handles">
            {handlePositions(loneRect, magnet).map(({ h, at }) => (
              <rect
                key={`${h.hx},${h.hy}`}
                x={at.x - grip}
                y={at.y - grip}
                width={grip * 2}
                height={grip * 2}
              />
            ))}
          </g>
        )}
      </g>

      {/* The size readout lives in SCREEN space so it never scales away. */}
      {live && drag?.kind !== 'move' && <SizeBadge rect={live} screen={rect} view={view} />}
      {count(selection) > 1 && !drag && (
        <text className="multi-count" x={12} y={22}>
          {count(selection)} selected · Delete removes them · Ctrl+C copies
        </text>
      )}
    </svg>
  )
}

/** The rectangle a drag currently describes, snapped. One function for the
 *  live preview and for the commit, so what you see is what you get. */
function resolve(
  d: Exclude<Drag, null | { kind: 'pan'; from: Pt; view: View } | { kind: 'band' }>,
  magnet: number,
  targetsFor: (what: Kind, exceptId?: string) => Rect[],
): Rect | null {
  if (d.kind === 'draw') {
    const targets = targetsFor(d.what)
    const anchor = snapPoint(d.from, targets, magnet)
    return rectFrom(anchor, snapCorner(d.to, anchor, targets, magnet))
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
  // The anchor is the edge that is NOT moving — the same collapse rule applies.
  const anchor = {
    x: d.handle.hx === -1 ? right(d.orig) : d.orig.x,
    y: d.handle.hy === -1 ? bottom(d.orig) : d.orig.y,
  }
  const p = snapCorner(d.to, anchor, targets, magnet)
  const x0 = d.handle.hx === -1 ? p.x : d.orig.x
  const x1 = d.handle.hx === 1 ? p.x : right(d.orig)
  const y0 = d.handle.hy === -1 ? p.y : d.orig.y
  const y1 = d.handle.hy === 1 ? p.y : bottom(d.orig)
  return rectFrom({ x: x0, y: y0 }, { x: x1, y: y1 })
}

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
        {`${bc.name || 'bookcase'} · ${r.w}×${r.h} · ${bc.sections.length} section${bc.sections.length > 1 ? 's' : ''} · depth ≤${maxDepth(bc)}`}
      </title>
    </g>
  )
}

/** "12 × 8" beside the rectangle being drawn or resized — the feedback that
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
