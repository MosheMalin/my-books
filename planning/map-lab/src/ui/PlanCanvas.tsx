/**
 * The plan — top-down, SVG, pointer-driven.
 *
 * Both authoring modes render through this one component, and both place a
 * bookcase through the same `placeCase` rule. Only the GESTURE differs, which
 * is what makes the comparison in MAP_PLAN §4 a comparison of one variable.
 *
 * Pinned LTR (MAP_PLAN §3.5): a floor plan does not mirror when the language
 * flips — the furniture did not move. Only labels follow the language, and
 * they carry `unicode-bidi: plaintext` so a Hebrew room name resolves its own
 * direction.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { Pt } from '../core/geom'
import { GRID, GRID_MAJOR, dist, pointInPolygon, snapPt } from '../core/geom'
import type { Bookcase, Plan, Room } from '../core/model'
import {
  caseLength,
  caseMidpoint,
  casePolygon,
  columnCount,
  columnDividers,
  maxDepth,
} from '../core/model'
import type { CasePlacement } from '../core/snap'
import { isDegenerate, placeCase, roomFromDrag } from '../core/snap'
import { readStroke } from '../core/straighten'
import type { Selection, Tool } from './types'
import type { Rect, View } from './viewport'
import {
  groupTransform,
  magnetUnits,
  toWorld,
  visibleBounds,
  zoomAbout,
} from './viewport'

/**
 * ⚠ There is no `mode` prop, and that is the finding rather than an omission:
 * once both modes place a bookcase through `placeCase`, the canvas only ever
 * needs to know WHICH TOOL is active. The two authoring models differ by one
 * gesture and nothing else — which is exactly the isolation the comparison
 * needs, and it is nice that the type system noticed before we did.
 */
type Props = {
  plan: Plan
  tool: Tool
  selection: Selection
  view: View
  onView: (v: View) => void
  onSelect: (s: Selection) => void
  onCreateRoom: (points: Pt[]) => void
  onCreateCase: (p: CasePlacement) => void
  onReplaceCase: (id: string, p: CasePlacement) => void
  onMoveRoom: (id: string, delta: Pt) => void
  onRejected: (reason: string) => void
}

type Drag =
  | null
  | { kind: 'pan'; from: Pt; view: View }
  | { kind: 'rect'; from: Pt; to: Pt }
  | { kind: 'case'; from: Pt; to: Pt }
  | { kind: 'stroke'; points: Pt[] }
  | { kind: 'slide'; id: string; from: Pt; to: Pt; orig: Bookcase }
  | { kind: 'handle'; id: string; anchor: Pt; to: Pt }
  | { kind: 'room'; id: string; from: Pt; to: Pt; orig: Pt[] }

export function PlanCanvas(props: Props) {
  const { plan, tool, selection, view } = props
  const svgRef = useRef<SVGSVGElement | null>(null)
  const [rect, setRect] = useState<Rect>({ left: 0, top: 0, width: 800, height: 600 })
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

  // --- picking -------------------------------------------------------------

  const caseAt = (p: Pt): Bookcase | null => {
    for (let i = plan.cases.length - 1; i >= 0; i--) {
      const bc = plan.cases[i]!
      if (pointInPolygon(p, casePolygon(bc))) return bc
    }
    return null
  }

  const roomAt = (p: Pt): Room | null => {
    for (let i = plan.rooms.length - 1; i >= 0; i--) {
      const r = plan.rooms[i]!
      if (pointInPolygon(p, r.points)) return r
    }
    return null
  }

  const selectedCase =
    selection?.kind === 'case' || selection?.kind === 'shelf'
      ? plan.cases.find(
          (c) => c.id === (selection.kind === 'case' ? selection.id : selection.caseId),
        ) ?? null
      : null

  const handleAt = (p: Pt): { id: string; anchor: Pt } | null => {
    if (!selectedCase) return null
    if (dist(p, selectedCase.a) <= magnet) {
      return { id: selectedCase.id, anchor: selectedCase.b }
    }
    if (dist(p, selectedCase.b) <= magnet) {
      return { id: selectedCase.id, anchor: selectedCase.a }
    }
    return null
  }

  // --- pointer -------------------------------------------------------------

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    // Capture keeps a drag alive when the finger leaves the svg. It throws
    // InvalidPointerId for a pointer the browser no longer considers active —
    // which a lost touch and a dispatched event both produce — and losing the
    // whole gesture to that is worse than losing the capture.
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

    if (tool === 'pan') return setDrag({ kind: 'pan', from: p, view })
    if (tool === 'room') return setDrag({ kind: 'rect', from: p, to: p })
    if (tool === 'case') return setDrag({ kind: 'case', from: p, to: p })
    if (tool === 'draw') return setDrag({ kind: 'stroke', points: [p] })

    const h = handleAt(p)
    if (h) return setDrag({ kind: 'handle', id: h.id, anchor: h.anchor, to: p })

    const bc = caseAt(p)
    if (bc) {
      props.onSelect({ kind: 'case', id: bc.id })
      return setDrag({ kind: 'slide', id: bc.id, from: p, to: p, orig: bc })
    }
    const room = roomAt(p)
    if (room) {
      props.onSelect({ kind: 'room', id: room.id })
      return setDrag({ kind: 'room', id: room.id, from: p, to: p, orig: room.points })
    }
    props.onSelect(null)
    setDrag({ kind: 'pan', from: p, view })
  }

  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (pointers.current.has(e.pointerId)) {
      pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    }
    if (pointers.current.size === 2 && pinch.current) {
      const [a, b] = [...pointers.current.values()]
      if (!a || !b) return
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
      const anchor = toWorld(mid, rect, view)
      const factor = dist(a, b) / Math.max(1, pinch.current.d)
      props.onView(zoomAbout(view, anchor, pinch.current.scale * factor))
      return
    }
    if (!drag) return
    const p = world(e)
    if (drag.kind === 'pan') {
      // Pan in SCREEN space against the frozen start view, so the world point
      // under the finger stays under the finger.
      const v = drag.view
      const start = drag.from
      props.onView({ ...view, cx: v.cx + (start.x - p.x), cy: v.cy + (start.y - p.y) })
      return
    }
    // ⚠ Functional update, not `{...drag, …}`. pointermove is a CONTINUOUS
    // event, so React batches a burst of them into one render and every
    // handler in that burst closes over the same stale `drag` — the second
    // move overwrites the first instead of appending. On a 120 Hz phone that
    // is most of a freehand stroke thrown away, and it reads as "the
    // straightener is bad" rather than as dropped input.
    setDrag((prev) => {
      if (!prev) return prev
      if (prev.kind === 'pan') return prev
      if (prev.kind === 'stroke') return { ...prev, points: prev.points.concat(p) }
      return { ...prev, to: p }
    })
  }

  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    pointers.current.delete(e.pointerId)
    if (pointers.current.size < 2) pinch.current = null
    if (!drag) return
    // The release carries its OWN position, and it is not always the last
    // pointermove: lift fast and the browser coalesces the tail of the
    // gesture into the up event. Taking `to` from state alone silently
    // shortened every quick drag — measured in the browser, not guessed.
    const end = world(e)
    const d: Drag =
      drag.kind === 'stroke'
        ? { ...drag, points: drag.points.concat(end) }
        : drag.kind === 'pan'
          ? drag
          : { ...drag, to: end }
    setDrag(null)

    if (d.kind === 'rect') {
      const points = roomFromDrag(plan, d.from, d.to, magnet)
      if (Math.abs(points[0]!.x - points[2]!.x) < 1 || Math.abs(points[0]!.y - points[2]!.y) < 1) {
        props.onRejected('too small to be a room')
        return
      }
      props.onCreateRoom(points)
    }

    if (d.kind === 'case') {
      const placed = placeCase(plan, d.from, d.to, magnet)
      if (isDegenerate(placed.a, placed.b)) {
        props.onRejected('a bookcase needs a length — drag along a wall')
        return
      }
      props.onCreateCase(placed)
    }

    if (d.kind === 'stroke') {
      const read = readStroke(d.points)
      if (read.kind === 'none') return props.onRejected(read.reason)
      if (read.kind === 'room') return props.onCreateRoom(read.points)
      const placed = placeCase(plan, read.from, read.to, magnet)
      if (isDegenerate(placed.a, placed.b)) {
        return props.onRejected('the stroke straightened to nothing')
      }
      props.onCreateCase(placed)
    }

    if (d.kind === 'slide') {
      const moved = slidePreview(plan, d)
      if (moved) props.onReplaceCase(d.id, moved)
    }

    if (d.kind === 'handle') {
      const placed = placeCase(plan, d.anchor, d.to, magnet)
      if (!isDegenerate(placed.a, placed.b)) props.onReplaceCase(d.id, placed)
    }

    if (d.kind === 'room') {
      const delta = snapPt({ x: d.to.x - d.from.x, y: d.to.y - d.from.y })
      if (delta.x !== 0 || delta.y !== 0) props.onMoveRoom(d.id, delta)
    }
  }

  const onWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    const anchor = world(e)
    props.onView(zoomAbout(view, anchor, view.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15)))
  }

  // Wheel must be non-passive to be preventable; React's onWheel is passive in
  // some builds, so the listener is attached by hand.
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const stop = (ev: WheelEvent) => ev.preventDefault()
    el.addEventListener('wheel', stop, { passive: false })
    return () => el.removeEventListener('wheel', stop)
  }, [])

  // --- previews ------------------------------------------------------------

  const previewRoom =
    drag?.kind === 'rect' ? roomFromDrag(plan, drag.from, drag.to, magnet) : null
  const previewCase =
    drag?.kind === 'case'
      ? placeCase(plan, drag.from, drag.to, magnet)
      : drag?.kind === 'handle'
        ? placeCase(plan, drag.anchor, drag.to, magnet)
        : drag?.kind === 'slide'
          ? slidePreview(plan, drag)
          : null
  const previewStroke = drag?.kind === 'stroke' ? drag.points : null
  const roomDelta =
    drag?.kind === 'room'
      ? snapPt({ x: drag.to.x - drag.from.x, y: drag.to.y - drag.from.y })
      : null

  const bounds = visibleBounds(rect, view)
  const cursor =
    tool === 'pan' ? 'grab' : tool === 'select' ? 'default' : 'crosshair'

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

        {plan.rooms.map((r) => {
          const moving = roomDelta && drag?.kind === 'room' && drag.id === r.id
          const points = moving
            ? r.points.map((p) => ({ x: p.x + roomDelta.x, y: p.y + roomDelta.y }))
            : r.points
          return (
            <RoomShape
              key={r.id}
              room={r}
              points={points}
              selected={selection?.kind === 'room' && selection.id === r.id}
            />
          )
        })}

        {plan.cases.map((bc) => (
          <CaseShape
            key={bc.id}
            bc={
              previewCase && drag && 'id' in drag && drag.id === bc.id
                ? { ...bc, ...previewCase }
                : bc
            }
            selected={selectedCase?.id === bc.id}
          />
        ))}

        {previewRoom && (
          <polygon className="preview-room" points={previewRoom.map((p) => `${p.x},${p.y}`).join(' ')} />
        )}
        {previewCase && !(drag && 'id' in drag) && <PreviewCase p={previewCase} />}
        {previewStroke && (
          <polyline
            className="preview-stroke"
            points={previewStroke.map((p) => `${p.x},${p.y}`).join(' ')}
          />
        )}

        {selectedCase && !drag && (
          <>
            <circle className="handle" cx={selectedCase.a.x} cy={selectedCase.a.y} r={magnet * 0.6} />
            <circle className="handle" cx={selectedCase.b.x} cy={selectedCase.b.y} r={magnet * 0.6} />
          </>
        )}
      </g>
    </svg>
  )
}

/** The live position of a case being slid. Attached cases stay on their wall;
 *  an island moves freely. Both grid-snap. */
function slidePreview(
  plan: Plan,
  d: { id: string; from: Pt; to: Pt; orig: Bookcase },
): CasePlacement | null {
  const delta = snapPt({ x: d.to.x - d.from.x, y: d.to.y - d.from.y })
  if (delta.x === 0 && delta.y === 0) return null
  const moved = {
    a: { x: d.orig.a.x + delta.x, y: d.orig.a.y + delta.y },
    b: { x: d.orig.b.x + delta.x, y: d.orig.b.y + delta.y },
  }
  if (!d.orig.attach) {
    return { ...moved, side: d.orig.side, attach: null }
  }
  // Re-run the same placement rule: sliding past a corner should hand the case
  // to the next wall rather than leave it floating off the end of this one.
  return placeCase(plan, moved.a, moved.b)
}

function Grid({ min, max, scale }: { min: Pt; max: Pt; scale: number }) {
  const step = scale < 9 ? GRID * GRID_MAJOR : GRID
  const lines: React.ReactElement[] = []
  const x0 = Math.floor(min.x / step) * step
  const y0 = Math.floor(min.y / step) * step
  for (let x = x0; x <= max.x; x += step) {
    const major = Math.round(x) % GRID_MAJOR === 0
    lines.push(
      <line
        key={`x${x}`}
        className={major ? 'grid-major' : 'grid-minor'}
        x1={x}
        y1={min.y}
        x2={x}
        y2={max.y}
      />,
    )
  }
  for (let y = y0; y <= max.y; y += step) {
    const major = Math.round(y) % GRID_MAJOR === 0
    lines.push(
      <line
        key={`y${y}`}
        className={major ? 'grid-major' : 'grid-minor'}
        x1={min.x}
        y1={y}
        x2={max.x}
        y2={y}
      />,
    )
  }
  return <g pointerEvents="none">{lines}</g>
}

function RoomShape({
  room,
  points,
  selected,
}: {
  room: Room
  points: Pt[]
  selected: boolean
}) {
  const cx = points.reduce((s, p) => s + p.x, 0) / (points.length || 1)
  const cy = points.reduce((s, p) => s + p.y, 0) / (points.length || 1)
  return (
    <g className={selected ? 'room selected' : 'room'}>
      <polygon points={points.map((p) => `${p.x},${p.y}`).join(' ')} />
      {room.name && (
        <text className="room-label" x={cx} y={cy} textAnchor="middle">
          {room.name}
        </text>
      )}
    </g>
  )
}

function CaseShape({ bc, selected }: { bc: Bookcase; selected: boolean }) {
  const poly = casePolygon(bc)
  const mid = caseMidpoint(bc)
  const cols = columnCount(bc)
  const depth = maxDepth(bc)
  return (
    <g className={selected ? 'case selected' : 'case'}>
      <polygon points={poly.map((p) => `${p.x},${p.y}`).join(' ')} />
      {columnDividers(bc).map((d, i) => (
        <line key={i} className="case-divider" x1={d.a.x} y1={d.a.y} x2={d.b.x} y2={d.b.y} />
      ))}
      {/* the front face — which way the books look out */}
      <line className="case-front" x1={bc.a.x} y1={bc.a.y} x2={bc.b.x} y2={bc.b.y} />
      <text className="case-label" x={mid.x} y={mid.y} textAnchor="middle">
        {bc.name || '—'}
      </text>
      <title>
        {`${bc.name || 'bookcase'} · ${caseLength(bc)} units · ${cols} col · depth ≤${depth}`}
      </title>
    </g>
  )
}

function PreviewCase({ p }: { p: CasePlacement }) {
  return (
    <g className="preview-case">
      <line x1={p.a.x} y1={p.a.y} x2={p.b.x} y2={p.b.y} />
      <circle cx={p.a.x} cy={p.a.y} r={0.3} />
      <circle cx={p.b.x} cy={p.b.y} r={0.3} />
    </g>
  )
}
