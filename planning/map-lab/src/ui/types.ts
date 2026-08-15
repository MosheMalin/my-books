import type { Plan } from '../core/model'

/**
 * ⚠ There is no `Mode` any more. The freehand/straighten model (VISION §7
 * approach A, "S") was built, drawn on, and REJECTED by the owner on
 * 2026-08-16: *"the free draw was too free"*. Everything is a rectangle on the
 * grid now — see MAP_PLAN §4.
 */
export type Tool = 'select' | 'room' | 'case' | 'pan'

export type Theme = 'dark' | 'light'

export type Selection =
  | { kind: 'room'; id: string }
  | { kind: 'case'; id: string }
  | { kind: 'shelf'; caseId: string; col: number; level: number }
  | null

/**
 * The document. `seq` rides with the plan so ids are a pure function of the
 * document's history rather than of the clock — an imported plan continues
 * numbering without colliding, and nothing here calls Math.random.
 */
export type Doc = { plan: Plan; seq: number }
