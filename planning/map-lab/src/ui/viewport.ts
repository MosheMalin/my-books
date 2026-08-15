/**
 * Screen ↔ world. The ONE place pixels exist.
 *
 * Everything above this line is in abstract units; everything below is in
 * device pixels. Keeping the conversion in one tiny module is what lets the
 * model promise that a resize, a rotation or a zoom cannot corrupt a plan.
 */

import type { Pt } from '../core/geom'

export type View = {
  /** World point at the centre of the viewport. */
  cx: number
  cy: number
  /** Pixels per unit. */
  scale: number
}

export const MIN_SCALE = 4
export const MAX_SCALE = 90

export const initialView = (): View => ({ cx: 12, cy: 9, scale: 22 })

export type Rect = { left: number; top: number; width: number; height: number }

export function toWorld(client: Pt, rect: Rect, view: View): Pt {
  return {
    x: view.cx + (client.x - rect.left - rect.width / 2) / view.scale,
    y: view.cy + (client.y - rect.top - rect.height / 2) / view.scale,
  }
}

export function toScreen(world: Pt, rect: Rect, view: View): Pt {
  return {
    x: (world.x - view.cx) * view.scale + rect.width / 2 + rect.left,
    y: (world.y - view.cy) * view.scale + rect.height / 2 + rect.top,
  }
}

/** The transform for the content group: world units in, pixels out. */
export function groupTransform(rect: Rect, view: View): string {
  const tx = rect.width / 2 - view.cx * view.scale
  const ty = rect.height / 2 - view.cy * view.scale
  return `translate(${tx} ${ty}) scale(${view.scale})`
}

export const clampScale = (s: number): number =>
  Math.max(MIN_SCALE, Math.min(MAX_SCALE, s))

/** Zoom about a fixed screen point, so the world under the finger stays put. */
export function zoomAbout(view: View, anchorWorld: Pt, nextScale: number): View {
  const scale = clampScale(nextScale)
  const k = 1 - view.scale / scale
  return {
    scale,
    cx: view.cx + (anchorWorld.x - view.cx) * k,
    cy: view.cy + (anchorWorld.y - view.cy) * k,
  }
}

/** Fit a world bounding box into the viewport with a margin. */
export function fitTo(min: Pt, max: Pt, rect: Rect, margin = 2): View {
  const w = Math.max(1, max.x - min.x + margin * 2)
  const h = Math.max(1, max.y - min.y + margin * 2)
  const scale = clampScale(Math.min(rect.width / w, rect.height / h))
  return { cx: (min.x + max.x) / 2, cy: (min.y + max.y) / 2, scale }
}

/** World rectangle currently visible — what the grid renderer iterates. */
export function visibleBounds(rect: Rect, view: View): { min: Pt; max: Pt } {
  const halfW = rect.width / 2 / view.scale
  const halfH = rect.height / 2 / view.scale
  return {
    min: { x: view.cx - halfW, y: view.cy - halfH },
    max: { x: view.cx + halfW, y: view.cy + halfH },
  }
}

/**
 * A finger is about 10 px. Converting that into units means the magnet is as
 * forgiving when zoomed out as when zoomed in — the alternative is an editor
 * that feels precise on a desktop and hostile on a phone.
 */
export function magnetUnits(view: View, px = 14, floor = 0.6): number {
  return Math.max(floor, px / view.scale)
}
