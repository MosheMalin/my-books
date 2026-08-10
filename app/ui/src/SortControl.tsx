/**
 * One control, one question: **what to sort by, and which way.**
 *
 * The product client grew this shape and the owner tested it at length; the
 * console re-invented it as a bare `<select>` with a `↑/↓` button beside it and
 * lost the two things that make this one work. Both are here now, and both are
 * mutation-checked in this package's own ring:
 *
 *   - **the direction lives INSIDE the box**, at its inline-START edge — the
 *     right in Hebrew, the left in English, and always the edge the native
 *     dropdown chevron is *not* on. Two adjacent controls read as two
 *     questions; this is one;
 *   - **changing the KEY resets the direction to that key's natural one.**
 *     Carrying A–Z's "ascending" onto a date key silently answers a question
 *     nobody asked — *recently added, oldest first*. The natural direction is
 *     declared on each option, beside its label, because it is a property of
 *     what you are sorting by and the caller is the only one who knows it.
 *
 * ⚠ It is NOT a `<label>`. The direction toggle sits inside the box, and a
 * click on a button inside a label is forwarded to the labelled control — so
 * pressing the arrow would also open the dropdown.
 *
 * ⚠ The chevron is drawn, not a background image. Chrome pins the UA chevron a
 * fixed distance from the border and ignores `padding-inline-end`, so it is
 * replaced by `::after` — which, unlike a data-URI image, can read
 * `var(--ui-muted)` and therefore follows dark mode.
 */
import { useUi } from './i18n'

export interface SortOption {
  /** The value the server understands. */
  value: string
  label: string
  /**
   * The direction this key means when you pick it — A–Z for text, newest
   * first for a date. Defaults to ascending, which is right for text and is
   * the reason a date option must say so explicitly.
   */
  naturalAscending?: boolean
}

export interface SortControlProps {
  /** The selected key. */
  value: string
  ascending: boolean
  options: readonly SortOption[]
  /**
   * Both halves, always together — a key change carries the direction that
   * key implies, so a caller cannot apply one and forget the other.
   */
  onChange: (value: string, ascending: boolean) => void
  /** `aria-label` for the select. The app's word for "sort". */
  label: string
  /**
   * Inert, with the reason ON the control. The product disables it while a
   * search is running because the server ranks by RELEVANCE and ignores
   * `sort` — a live control would promise an ordering nobody applies.
   */
  disabled?: boolean
  /** Shown as the title on both halves while disabled. Say WHY, not "disabled". */
  disabledReason?: string
  /**
   * What the box reads while disabled. The product shows *relevance* — the
   * ordering that is actually in force — rather than a stale key the server is
   * ignoring.
   */
  inertOption?: SortOption
}

export function SortControl({
  value,
  ascending,
  options,
  onChange,
  label,
  disabled = false,
  disabledReason,
  inertOption,
}: SortControlProps) {
  const { ui } = useUi()
  const directionLabel = ascending ? ui.sort_asc : ui.sort_desc
  const title = disabled && disabledReason ? disabledReason : undefined

  const shown = disabled && inertOption ? inertOption.value : value

  return (
    <div className="sortwrap">
      <button
        type="button"
        className={`sortdir${ascending ? '' : ' desc'}`}
        disabled={disabled}
        aria-label={directionLabel}
        title={title ?? directionLabel}
        onClick={() => onChange(value, !ascending)}
      >
        {/* One glyph, flipped — so ascending and descending can never drift
            into two shapes that disagree about which way is which. */}
        <svg viewBox="0 0 12 14" width="12" height="14" aria-hidden="true">
          <path
            d="M6 12.5V2.2M1.8 6.4 6 2.2l4.2 4.2"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <select
        aria-label={label}
        value={shown}
        disabled={disabled}
        title={title ?? label}
        onChange={(e) => {
          const next = options.find((o) => o.value === e.target.value)
          if (!next) return
          onChange(next.value, next.naturalAscending ?? true)
        }}
      >
        {disabled && inertOption && (
          <option value={inertOption.value}>{inertOption.label}</option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}
