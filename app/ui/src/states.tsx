/**
 * Loading, failed, empty — the three states every screen has and nobody
 * designs. One definition so they cannot drift into several slightly different
 * sentences across two apps.
 */
import type { ReactNode } from 'react'

import { useUi } from './i18n'

export function Loading() {
  const { ui } = useUi()
  return <p className="empty">{ui.loading}</p>
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>
}

export function ErrorBox({ message, onRetry }: {
  /** The server's own `detail`, verbatim. */
  message: string
  onRetry?: (() => void) | undefined
}) {
  const { ui } = useUi()
  return (
    <div className="err">
      {/* ⚠ Shown verbatim, and `.rtl-safe` because it may be Hebrew: someone
          diagnosing a 409 needs the server's sentence, not a generic apology.
          The fallback covers a thrown error with no message at all. */}
      <div className="rtl-safe">{message || ui.load_error}</div>
      {onRetry && (
        <button type="button" className="btn small" onClick={onRetry} style={{ marginTop: 8 }}>
          {ui.retry}
        </button>
      )}
    </div>
  )
}
