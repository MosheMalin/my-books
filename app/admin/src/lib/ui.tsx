/** The few pieces every screen repeats. One definition, so the loading and
 *  error states cannot drift into four slightly different sentences. */
import type { ReactNode } from 'react'

import { useI18n } from './i18n'
import type { Status } from '../api/schema'

export function Loading() {
  const { t } = useI18n()
  return <p className="empty">{t.loading}</p>
}

export function ErrorBox({ message, onRetry }: {
  message: string
  onRetry?: (() => void) | undefined
}) {
  const { t } = useI18n()
  return (
    <div className="err">
      {/* The server's own `detail` is shown verbatim — an admin diagnosing a
          409 needs the sentence, not a generic apology. */}
      <div className="rtl-safe">{message || t.load_error}</div>
      {onRetry && (
        <button type="button" className="btn small" onClick={onRetry}
                style={{ marginTop: 8 }}>
          {t.retry}
        </button>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>
}

/**
 * §5.1's ladder as a badge: `auto < approved < manual`.
 *
 * ⚠ `manual` OUTRANKS approved — a book someone typed by hand is vouched for
 * by the act of typing it — so it must never be drawn as the weaker state.
 * The product shipped that bug: its badge fired only on the literal
 * `approved` rung, and the one record a human had entered themselves looked
 * like the one thing nobody had confirmed.
 */
export function StatusBadge({ status }: { status: Status | string }) {
  const { t } = useI18n()
  const label =
    status === 'auto' ? t.st_auto
    : status === 'approved' ? t.st_approved
    : status === 'manual' ? t.st_manual
    : status
  return <span className={`badge ${status}`}>{label}</span>
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
