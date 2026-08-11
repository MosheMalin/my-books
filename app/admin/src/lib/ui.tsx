/** The one repeated piece that is this console's own.
 *
 *  `Loading` / `ErrorBox` / `Empty` / `StatusBadge` moved to `@booksnap/ui`:
 *  the three async states and §5.1's ladder are things BOTH clients render,
 *  and the two apps had already drifted on the ladder's wording (the console
 *  said `auto` in English, which reads like a raw enum value rather than a
 *  state). A stat card, by contrast, exists only on a dashboard.
 */
import type { Lang } from '@booksnap/ui'
import { formatNumber } from '@booksnap/ui'

/**
 * Bytes, as an operator reads them.
 *
 * ⚠ Deliberately NOT in `@booksnap/ui`, though `formatNumber` lives there.
 * That package is for what BOTH clients need or must not disagree about
 * (CLAUDE.md rule 6), and the household app shows no storage figure — putting
 * this there would be pre-sharing a rule with one caller. It moves the day the
 * product grows a quota screen; until then one copy exists, here.
 *
 * ⚠ Binary units (1024), labelled as such, because that is what the filesystem
 * reports and a console whose number disagrees with `du` is a console nobody
 * trusts. One decimal from MB up: "1.4 GB" is a size, "1.43829 GB" is a
 * measurement nobody asked for.
 */
export function formatBytes(bytes: number, lang: Lang): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  const rounded = unit >= 2 ? Math.round(value * 10) / 10 : Math.round(value)
  return `${formatNumber(rounded, lang)} ${units[unit]}`
}

export function StatCard({ label, value, warn }: {
  label: string
  value: string
  warn?: boolean
}) {
  return (
    <div className={`card stat${warn ? ' warn' : ''}`}>
      <div className="n">{value}</div>
      <div className="k">{label}</div>
    </div>
  )
}
