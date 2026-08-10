/**
 * VISION §5.1's ladder as a badge: `auto < approved < manual`.
 *
 * ⚠ `manual` OUTRANKS approved — a book someone typed by hand is vouched for
 * by the act of typing it — so it must never be drawn as the weaker state. The
 * product shipped exactly that bug: its badge fired only on the literal
 * `approved` rung, and the one record a human had entered themselves looked
 * like the one thing nobody had confirmed. `vouchedFor` is that rule as a
 * function, exported so a caller counting "still unapproved" and a caller
 * drawing a badge cannot come to disagree.
 *
 * The stored status is never rewritten to match: downgrading `manual` to
 * `approved` would throw away which of the two actually happened.
 */
import { useUi } from './i18n'

export type BookStatus = 'auto' | 'approved' | 'manual'

/** Has a human said yes to this record? Everything off the `auto` rung has. */
export const vouchedFor = (status: string): boolean => status !== 'auto'

export function StatusBadge({ status }: { status: BookStatus | string }) {
  const { ui } = useUi()
  const label =
    status === 'auto' ? ui.st_auto
    : status === 'approved' ? ui.st_approved
    : status === 'manual' ? ui.st_manual
    // An unknown status is shown VERBATIM rather than mapped to a default.
    // A new rung added server-side must read as itself, not silently as the
    // one below it.
    : status
  return <span className={`badge ${status}`}>{label}</span>
}
