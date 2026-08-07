/**
 * The filter row.
 *
 * UI_PLAN §2 lists more chips than are here — shelf, ☆ wishlist, lent-out,
 * כפילויות לבירור. Every one of them needs an entity that does not exist yet
 * (Shelf is P2.1, lending P1.7, the duplicates queue P2.4). They are ABSENT
 * rather than disabled: a greyed-out control that never becomes clickable
 * reads as a bug, while a control that is not there yet reads as a product
 * that has not grown that far.
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
  active: boolean
  onStatus: (status: StatusFilter) => void
  onClearAuthor: () => void
  onClearAll: () => void
}

const STATUSES: Exclude<StatusFilter, null>[] = ['auto', 'approved', 'manual']

export function FilterBar({
  status,
  authorKey,
  authorLabel,
  active,
  onStatus,
  onClearAuthor,
  onClearAll,
}: FilterBarProps) {
  const { t } = useI18n()
  const label = { auto: t.st_auto, approved: t.st_approved, manual: t.st_manual }

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
