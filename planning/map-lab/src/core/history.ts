/**
 * A generic undo stack. Pure, framework-free, ~40 lines — and the reason the
 * editor can afford to snap aggressively: every snap is one ⌘Z away.
 */

export type History<T> = {
  past: T[]
  present: T
  future: T[]
}

/** Bounded so a long drawing session cannot grow without limit. */
export const HISTORY_LIMIT = 120

export const initHistory = <T>(present: T): History<T> => ({
  past: [],
  present,
  future: [],
})

/** Record a new present. A no-op commit (identical reference) is ignored, so
 *  callers may commit freely from event handlers. */
export function commit<T>(h: History<T>, next: T, limit = HISTORY_LIMIT): History<T> {
  if (next === h.present) return h
  const past = h.past.concat(h.present)
  return {
    past: past.length > limit ? past.slice(past.length - limit) : past,
    present: next,
    future: [],
  }
}

/** Replace the present WITHOUT a history entry — for a live drag preview,
 *  which must not leave one undo step per pointermove. */
export function amend<T>(h: History<T>, next: T): History<T> {
  return next === h.present ? h : { ...h, present: next }
}

export const canUndo = <T>(h: History<T>): boolean => h.past.length > 0
export const canRedo = <T>(h: History<T>): boolean => h.future.length > 0

export function undo<T>(h: History<T>): History<T> {
  const prev = h.past[h.past.length - 1]
  if (prev === undefined) return h
  return {
    past: h.past.slice(0, -1),
    present: prev,
    future: [h.present, ...h.future],
  }
}

export function redo<T>(h: History<T>): History<T> {
  const next = h.future[0]
  if (next === undefined) return h
  return {
    past: h.past.concat(h.present),
    present: next,
    future: h.future.slice(1),
  }
}
