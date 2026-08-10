/**
 * The filter row.
 *
 * UI_PLAN §2 lists more chips than are here — shelf, ☆ wishlist. Each needs
 * an entity that does not exist yet (Shelf is P2.1; the wishlist is a
 * virtual Shelf, same dependency). They are ABSENT rather than disabled: a
 * greyed-out control that never becomes clickable reads as a bug, while a
 * control that is not there yet reads as a product that has not grown that
 * far. Lent-out graduated out of that list at P1.7, and כפילויות לבירור (the
 * "duplicates to resolve" queue) at P2.6 — both needed nothing this tab
 * didn't already have: a boolean filter on `list`, same shape as status.
 *
 * The author chip is reached by CLICKING an author, never typed (§2) — which
 * is why it appears here only once one is active.
 */
import { useI18n } from '../lib/i18n'
import type { StatusFilter } from '../lib/books'

export interface FilterBarProps {
  status: StatusFilter
  authorKey: string | null
  authorLabel: string | null
  lentOut: boolean
  duplicates: boolean
  active: boolean
  onStatus: (status: StatusFilter) => void
  onClearAuthor: () => void
  onLentOut: (lentOut: boolean) => void
  onDuplicates: (duplicates: boolean) => void
  onClearAll: () => void
}

const STATUSES: Exclude<StatusFilter, null>[] = ['auto', 'approved', 'manual']

export function FilterBar({
  status,
  authorKey,
  authorLabel,
  lentOut,
  duplicates,
  active,
  onStatus,
  onClearAuthor,
  onLentOut,
  onDuplicates,
  onClearAll,
}: FilterBarProps) {
  const { t, ui } = useI18n()
  // The same three words the badges use, from the shared table — a filter
  // and the rows it produces must not name one state two ways.
  const label = { auto: ui.st_auto, approved: ui.st_approved, manual: ui.st_manual }

  return (
    <div className="filterbar">
      {STATUSES.map((s) => (
        <button
          key={s}
          type="button"
          className={`chip${status === s ? ' on' : ''}`}
          aria-pressed={status === s}
          // Clicking the active one clears it: a single-select filter with no
          // way back to "all" is a trap.
          onClick={() => onStatus(status === s ? null : s)}
        >
          {label[s]}
        </button>
      ))}

      <button
        type="button"
        className={`chip${lentOut ? ' on' : ''}`}
        aria-pressed={lentOut}
        onClick={() => onLentOut(!lentOut)}
      >
        {t.lent_only}
      </button>

      <button
        type="button"
        className={`chip${duplicates ? ' on' : ''}`}
        aria-pressed={duplicates}
        onClick={() => onDuplicates(!duplicates)}
      >
        {t.duplicates_only}
      </button>

      {authorKey && (
        <button type="button" className="chip on" onClick={onClearAuthor}>
          <span className="rtl-safe">{authorLabel || authorKey}</span>
          <span className="x" aria-hidden="true">✕</span>
        </button>
      )}

      {active && (
        <button type="button" className="clearlink" onClick={onClearAll}>
          {t.clear}
        </button>
      )}
    </div>
  )
}
