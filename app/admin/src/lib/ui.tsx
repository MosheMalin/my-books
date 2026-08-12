/** The one repeated piece that is this console's own.
 *
 *  `Loading` / `ErrorBox` / `Empty` / `StatusBadge` moved to `@booksnap/ui`:
 *  the three async states and §5.1's ladder are things BOTH clients render,
 *  and the two apps had already drifted on the ladder's wording (the console
 *  said `auto` in English, which reads like a raw enum value rather than a
 *  state). A stat card, by contrast, exists only on a dashboard.
 */
import type { Lang } from '@booksnap/ui'
import { formatNumber, libraryName, Select } from '@booksnap/ui'

import { useI18n } from './i18n'
import { useSystem } from './system'

/**
 * A library, always naming the customer that owns it.
 *
 * ⚠⚠ **A library name on its own is not an answer to "whose is this?"** — and
 * on a cross-tenant console that is the question. `My library` and `lib2` say
 * nothing about which household is being looked at, and since P3.7b a customer
 * may own several, so the collection name is not even a unique handle. Every
 * place outside an account's own drawer that names a library uses this: the
 * images table and panel, the work panel's per-household cards, and the access
 * screen's membership list.
 *
 * ⚠ TWO elements, never one interpolated string. `.rtl-safe` is
 * `unicode-bidi: plaintext`, which resolves ONE direction per paragraph from
 * its first strong character — so `lib2 · משפחת מלין` would lay the Hebrew
 * account name out in the Latin library name's direction and put the separator
 * on the wrong side. Direction per STRING is the rule (§7.2), which is why the
 * work panel already splits a title from its author the same way.
 *
 * ⚠ The account may be unknown: `/accounts` and `/libraries` are two requests
 * that fail independently. It renders the library alone rather than inventing
 * an owner — see `accountOfLibrary`.
 */
export function LibraryName({ libraryId }: { libraryId: string }) {
  const { t } = useI18n()
  const { labelOf, accountOfLibrary } = useSystem()
  const account = accountOfLibrary(libraryId)
  return (
    <>
      <div className="rtl-safe">{libraryName(labelOf(libraryId), t.lib_unnamed)}</div>
      {account && (
        <div className="rtl-safe sub">
          {libraryName(account.label, t.acct_unnamed)}
        </div>
      )}
    </>
  )
}

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

/**
 * The library filter, GROUPED BY CUSTOMER — the books and images screens share
 * it so their narrowing cannot come to mean two things.
 *
 * ⚠ `<optgroup>` rather than a prefixed label, because the grouping is real:
 * an operator narrowing to a collection is almost always narrowing to a
 * household first, and a flat list of names like "My library / lib2 / Books"
 * makes them guess which customer each belongs to. An account owning no
 * library contributes no group — there is nothing to select.
 */
export function LibraryPicker({ value, onChange }: {
  value: string | undefined
  onChange: (next: string | undefined) => void
}) {
  const { t } = useI18n()
  const { accounts, libraries, librariesOf } = useSystem()
  // Libraries whose owning account is missing from `/accounts` — two requests
  // that fail independently. Listed under no group rather than dropped: a
  // filter that silently cannot reach a collection is worse than an ugly one.
  const grouped = new Set(accounts.flatMap((a) => librariesOf(a.id).map((l) => l.id)))
  const orphans = libraries.filter((l) => !grouped.has(l.id))

  return (
    <Select value={value ?? ''} aria-label={t.bp_library}
            onChange={(e) => onChange(e.target.value || undefined)}>
      <option value="">{t.books_all_libraries}</option>
      {accounts.map((account) => {
        const owned = librariesOf(account.id)
        if (owned.length === 0) return null
        return (
          <optgroup key={account.id}
                    label={libraryName(account.label, t.acct_unnamed)}>
            {owned.map((lib) => (
              <option key={lib.id} value={lib.id}>
                {libraryName(lib.label, t.lib_unnamed)}
              </option>
            ))}
          </optgroup>
        )
      })}
      {orphans.map((lib) => (
        <option key={lib.id} value={lib.id}>
          {libraryName(lib.label, t.lib_unnamed)}
        </option>
      ))}
    </Select>
  )
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
