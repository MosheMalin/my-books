import type { Plan } from '../core/model'

/** The two authoring models under comparison (MAP_PLAN §4). */
export type Mode = 'D' | 'S'

export type Tool = 'select' | 'room' | 'case' | 'draw' | 'pan'

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

export const nextId = (doc: Doc, prefix: string): string => `${prefix}${doc.seq + 1}`
