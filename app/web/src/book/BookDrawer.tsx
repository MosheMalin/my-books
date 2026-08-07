/**
 * The drawer mount: a panel over an untouched list (UI_PLAN §5).
 *
 * It carries the accessibility the mock has none of — a focus trap, Escape to
 * close, and focus returned to whatever opened it. That is not polish: a
 * dialog you can Tab out of leaves a keyboard user typing into a list they
 * cannot see, and losing focus to `<body>` on close means starting the whole
 * page again.
 *
 * The drawer is deliberately NOT a route. It overlays the list, so putting it
 * in the URL would make Back close it rather than leave the tab. ⤢ promotes
 * it to `#/book/<id>`, and that transition is the deep-linkable one.
 */
import { useEffect, useRef } from 'react'
import { useI18n } from '../lib/i18n'
import { BookSurface } from './BookSurface'
import { useBookRecord } from './useBookRecord'

export interface BookDrawerProps {
  bookId: string | null
  onClose: () => void
  onPromote: (id: string) => void
  onAuthor: (authorKey: string) => void
}

export function BookDrawer({
  bookId,
  onClose,
  onPromote,
  onAuthor,
}: BookDrawerProps) {
  const { t } = useI18n()
  const record = useBookRecord(bookId)
  const panel = useRef<HTMLElement | null>(null)
  const opener = useRef<HTMLElement | null>(null)

  const open = bookId !== null

  useEffect(() => {
    if (!open) return
    opener.current = document.activeElement as HTMLElement | null
    // Focus the panel itself rather than its first control: a screen reader
    // then announces the dialog before its buttons.
    panel.current?.focus()
    return () => opener.current?.focus?.()
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab' || !panel.current) return
      const focusable = panel.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) return
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      <div
        className={`scrim${open ? ' on' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className={`drawer${open ? ' on' : ''}`}
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={t.details}
        aria-hidden={!open}
        // Keeps a closed drawer out of the tab order while it is still in the
        // DOM for the slide-out transition.
        inert={!open}
      >
        <div className="dhead">
          <button type="button" className="btn ghost" onClick={onClose}>
            ✕ <span className="visually-hidden">{t.close}</span>
          </button>
          <strong>{t.details}</strong>
        </div>

        {open && record.state === 'loading' && (
          <p className="loading">{t.loading}</p>
        )}
        {open && record.state === 'missing' && (
          <p className="empty">{t.not_found}</p>
        )}
        {open && record.state === 'ready' && (
          <BookSurface
            book={record.book}
            onAuthor={(key) => {
              onAuthor(key)
              onClose()
            }}
            onPromote={() => onPromote(record.book.id)}
            onDeleted={onClose}
          />
        )}
      </aside>
    </>
  )
}
