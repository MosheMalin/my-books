/**
 * Display formatting. Pure, so it is testable without a DOM.
 *
 * Both clients had a `formatDate` and they had already drifted: the product's
 * returned the raw ISO string when it could not be parsed, the console's
 * returned `''`. Neither is wrong in isolation; two of them is, because the
 * same stored value then renders two different ways depending on which app you
 * are looking at, and nobody would ever think to check.
 *
 * ⚠ The settled behaviour is the console's — **`''` for absent OR
 * unparseable** — and the reason is the caller's, not this function's: "never
 * read" and "read on a date we cannot parse" are different facts, and only the
 * column knows which of the two its em-dash should mean. Handing back the raw
 * ISO string put a machine timestamp in a reading surface, which is the one
 * outcome neither caller wanted.
 */

export type Lang = 'he' | 'en'

const LOCALE: Record<Lang, string> = { he: 'he-IL', en: 'en-GB' }

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

/** A stored ISO timestamp as a date the owner reads. `''` when there is none. */
export function formatDate(iso: string | null | undefined, lang: Lang): string {
  const d = parse(iso)
  if (!d) return ''
  return d.toLocaleDateString(LOCALE[lang], {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** The same, with the time — for a log-shaped column where the day is not
 *  enough to tell two rows apart. */
export function formatDateTime(iso: string | null | undefined, lang: Lang): string {
  const d = parse(iso)
  if (!d) return ''
  return d.toLocaleString(LOCALE[lang], {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Grouped digits. Hebrew reads Western numerals, so the locale only decides
 *  the separators. */
export const formatNumber = (n: number, lang: Lang): string => n.toLocaleString(LOCALE[lang])

/**
 * A library's name for display.
 *
 * ⚠ Schema v12 backfilled every pre-existing library with a BLANK label (a
 * migration cannot know what the owner calls their collection), so an empty
 * label is a real, expected state and not a bug — it needs a word, not an
 * empty cell that reads as a rendering failure.
 */
export const libraryName = (label: string | null | undefined, fallback: string): string =>
  (label ?? '').trim() || fallback
