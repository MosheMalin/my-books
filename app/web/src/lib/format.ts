/**
 * Shared display formatting. Small on purpose — this is not a utility
 * dumping ground, just the one function two screens now need (the book
 * surface's "last seen"/"added" dates, and the shelf-detail screen's
 * staleness line and read history, P2.8).
 */

export function formatDate(iso: string | null | undefined, lang: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(lang === 'he' ? 'he-IL' : 'en-GB', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}
