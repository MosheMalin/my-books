/**
 * The full-page mount at `#/book/<id>` — deep-linkable and returnable
 * (UI_PLAN §5). Same renderer as the drawer; only the wrapper differs.
 *
 * "Returnable" is doing real work: Back goes through history rather than
 * navigating to `#/library`, so the list comes back at the row you left rather
 * than at the top of 251.
 */
import { useI18n } from '../lib/i18n'
import { BookSurface } from './BookSurface'
import { useBookRecord } from './useBookRecord'

export interface BookPageProps {
  bookId: string
  onBack: () => void
  onAuthor: (authorKey: string) => void
}

export function BookPage({ bookId, onBack, onAuthor }: BookPageProps) {
  const { t } = useI18n()
  const record = useBookRecord(bookId)

  return (
    <div className="bookpage">
      <button type="button" className="btn ghost" onClick={onBack}>
        ← {t.back}
      </button>

      {record.state === 'loading' && <p className="loading">{t.loading}</p>}
      {record.state === 'missing' && <p className="empty">{t.not_found}</p>}
      {record.state === 'ready' && (
        <BookSurface
          book={record.book}
          full
          onAuthor={onAuthor}
          onDeleted={onBack}
        />
      )}
    </div>
  )
}
