/** Small formatting helpers. Pure, so they are testable without a DOM. */
import type { Lang } from './i18n'

const LOCALE: Record<Lang, string> = { he: 'he-IL', en: 'en-GB' }

/**
 * A stored ISO timestamp as a date the owner reads.
 *
 * ⚠ Returns `''` for null/undefined/unparseable rather than a placeholder:
 * "never read" and "read on an unparseable date" are different facts, and the
 * CALLER knows which of the two its column means. Inventing an em-dash here
 * would make both look the same everywhere.
 */
export function formatDate(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(LOCALE[lang], {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

export function formatDateTime(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(LOCALE[lang], {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

/** Grouped digits. Hebrew reads Western numerals, so the locale only decides
 *  the separators. */
export const formatNumber = (n: number, lang: Lang): string =>
  n.toLocaleString(LOCALE[lang])

/**
 * A library's name for display.
 *
 * ⚠ Schema v12 backfilled every pre-existing library with a BLANK label (a
 * migration cannot know what the owner calls their collection), so an empty
 * label is a real, expected state and not a bug — it needs a word, not an
 * empty cell that reads as a rendering failure.
 */
export const libraryName = (label: string, fallback: string): string =>
  label.trim() || fallback
