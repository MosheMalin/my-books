/**
 * The undo stack. Pure, framework-free — and the reason the editor can afford
 * to snap aggressively: every snap is one Ctrl+Z away.
 *
 * It holds a real stack, not one step: `HISTORY_LIMIT` edits deep, in both
 * directions, and redo survives until you make a different edit — which is the
 * moment the future genuinely stops existing.
 */

export type History<T> = {
  past: T[]
  present: T
  future: T[]
  /**
   * What produced the present entry. Two commits carrying the SAME tag
   * collapse into one, which is what keeps typing a name from filling the
   * stack with one entry per keystroke. A drag or a create passes no tag and
   * therefore always pushes.
   */
  tag: string | null
}

/** Deep enough that a long session does not lose its early moves, bounded so
 *  it cannot grow forever. */
export const HISTORY_LIMIT = 200

export const initHistory = <T>(present: T): History<T> => ({
  past: [],
  present,
  future: [],
  tag: null,
})

/**
 * Record a new present.
 *
 * A no-op commit (the identical reference) is ignored, so callers may commit
 * freely from event handlers. A commit whose `tag` matches the current one
 * REPLACES the present instead of stacking a second entry — 14 keystrokes of
 * a room name are one undo, not fourteen.
 */
export function commit<T>(
  h: History<T>,
  next: T,
  tag: string | null = null,
  limit = HISTORY_LIMIT,
): History<T> {
  if (next === h.present) return h
  if (tag !== null && tag === h.tag) return { ...h, present: next, future: [] }
  const past = h.past.concat(h.present)
  return {
    past: past.length > limit ? past.slice(past.length - limit) : past,
    present: next,
    future: [],
    tag,
  }
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
    // The tag describes how the PRESENT was made. After stepping back it no
    // longer does, and leaving it set would let the next edit silently merge
    // into an entry the user has already undone past.
    tag: null,
  }
}

export function redo<T>(h: History<T>): History<T> {
  const next = h.future[0]
  if (next === undefined) return h
  return {
    past: h.past.concat(h.present),
    present: next,
    future: h.future.slice(1),
    tag: null,
  }
}
