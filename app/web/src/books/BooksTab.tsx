/**
 * Tab 1 — Books (UI_PLAN §2): toolbar, filters, count line, feed.
 *
 * The tab owns only view state (list vs grid, which modal is open). Everything
 * about WHICH books are shown lives in the store, so the drawer, the full page
 * and this list all read one record — "edit it anywhere, it changes
 * everywhere" (UI_PLAN §5).
 */
import { useState } from 'react'
import { useBooks, type SortKey, type StatusFilter } from '../lib/books'
import { useI18n } from '../lib/i18n'
import { AddBookModal } from './AddBookModal'
import { FilterBar } from './FilterBar'
import { Feed, type View } from './Feed'
import { Toolbar } from './Toolbar'

export function BooksTab({ onOpen }: { onOpen: (id: string) => void }) {
  const { t } = useI18n()
  const books = useBooks()
  const [view, setView] = useState<View>('list')
  const [adding, setAdding] = useState(false)

  // The chip shows the author's real name, not the normalized key it filters
  // on — the key is machine identity (§5.1: authors are strings, not entities)
  // and would read as a typo on screen.
  const authorLabel =
    books.items.find((b) => b.author_key === books.query.authorKey)?.author ?? null

  return (
    <>
      <Toolbar
        q={books.query.q}
        sort={books.query.sort}
        ascending={books.query.ascending}
        sortApplies={books.sortApplies}
        view={view}
        onSearch={(q) => books.setQuery({ q })}
        onSort={(sort: SortKey) => books.setQuery({ sort })}
        onAscending={(ascending: boolean) => books.setQuery({ ascending })}
        onView={setView}
        onAdd={() => setAdding(true)}
      />

      <FilterBar
        status={books.query.status}
        authorKey={books.query.authorKey}
        authorLabel={authorLabel}
        lentOut={books.query.lentOut}
        duplicates={books.query.duplicates}
        active={books.filtersActive}
        onStatus={(status: StatusFilter) => books.setQuery({ status })}
        onClearAuthor={() => books.setQuery({ authorKey: null })}
        onLentOut={(lentOut: boolean) => books.setQuery({ lentOut })}
        onDuplicates={(duplicates: boolean) => books.setQuery({ duplicates })}
        onClearAll={books.resetQuery}
      />

      <p className="countline" aria-live="polite">
        {books.total === 0
          ? books.loading
            ? t.loading
            : t.count_none
          : t.count(books.items.length, books.total)}
      </p>

      {books.error && (
        <div className="errorbox" role="alert">
          <span>{t.load_error} — {books.error}</span>
          <button
            type="button"
            className="btn ghost"
            onClick={() => books.setQuery({})}
          >
            {t.retry}
          </button>
        </div>
      )}

      {!books.loading && !books.error && books.items.length === 0 && (
        <div className="empty">
          <p>{t.empty}</p>
          {books.filtersActive && (
            <button type="button" className="btn ghost" onClick={books.resetQuery}>
              {t.empty_hint}
            </button>
          )}
        </div>
      )}

      <Feed
        items={books.items}
        view={view}
        hasMore={books.hasMore}
        loadingMore={books.loadingMore}
        onLoadMore={books.loadMore}
        onOpen={onOpen}
      />

      {adding && (
        <AddBookModal
          onClose={() => setAdding(false)}
          onCreate={books.add}
          onCreated={(book) => {
            setAdding(false)
            onOpen(book.id)
          }}
        />
      )}
    </>
  )
}
