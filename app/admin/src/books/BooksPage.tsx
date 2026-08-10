/**
 * Every book in the system — one tenant-spanning, server-paged query.
 *
 * ⚠ This screen used to carry the console's one real compromise: with no
 * cross-library route, "all libraries" meant fetching each tenant separately,
 * merging in the browser, and sorting with `localeCompare` — which is not the
 * server's normalized key, so the merged order differed from a single
 * library's and the screen had to say so. `GET /api/staff/v1/books` retired
 * all of it: ordering and Hebrew ranking now happen once, server-side, by the
 * same measured rules the product uses.
 *
 * ⚠ Reading spans every tenant; WRITING does not. The moderation actions in
 * the panel go through the product API, which resolves the operator's own
 * membership — so a book in a library they do not belong to is shown and not
 * editable, and the panel says which it is.
 */
import { useEffect, useMemo, useState } from 'react'

import { listAllBooks, type StaffBook } from '../api/staff'
import { useI18n, type Strings } from '../lib/i18n'
import { navigate } from '../lib/route'
import { useSystem } from '../lib/system'
import {
  Empty, ErrorBox, Loading, SortControl, StatusBadge, formatDate, formatNumber, libraryName, useAsync, Select } from '@booksnap/ui'
import { BookPanel } from './BookPanel'

/** Rows per screen. */
const PAGE = 25

/** Typing pauses before a request goes out. Matches the product's own. */
const DEBOUNCE_MS = 250

type Sort = 'title' | 'author' | 'recently_added'

/**
 * What this screen can sort by, and — the load-bearing half — the direction
 * each key MEANS. A–Z for text, newest first for a date: carrying A–Z's
 * "ascending" onto a date key silently answers a question nobody asked
 * ("recently added, oldest first").
 *
 * ⚠ It is declared here, per option, rather than as a rule inside the shared
 * control: which keys exist is this screen's business, and a control that
 * guessed a direction from a key's NAME would be wrong the first time a screen
 * added `least_recently_seen`.
 */
const SORT_OPTIONS = [
  { value: 'title', label: 'sort_title' },
  { value: 'author', label: 'sort_author' },
  { value: 'recently_added', label: 'sort_recent', naturalAscending: false },
] as const satisfies readonly { value: Sort; label: keyof Strings; naturalAscending?: boolean }[]

export function BooksPage({ initialLibraryId }: { initialLibraryId: string | undefined }) {
  const { t, ui, lang } = useI18n()
  const { libraries, loading: sysLoading, labelOf, canWrite } = useSystem()

  const [libraryId, setLibraryId] = useState<string | undefined>(initialLibraryId)
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [sort, setSort] = useState<Sort>('title')
  const [ascending, setAscending] = useState(true)
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<StaffBook | undefined>(undefined)

  /**
   * Writes are folded in locally instead of refetching: a page of a
   * system-wide list is a real query, and redoing it after every approve
   * would make the console feel broken on a phone. `null` marks a deleted
   * book; the table applies the map while rendering, and the next real fetch
   * supersedes it.
   */
  const [overrides, setOverrides] = useState<Map<string, StaffBook | null>>(new Map())

  useEffect(() => {
    const id = setTimeout(() => setQ(typed), DEBOUNCE_MS)
    return () => clearTimeout(id)
  }, [typed])

  // Any change to WHAT is being asked returns to the first page. Staying on
  // page 4 of a filter that now matches 12 books shows an empty table, which
  // reads as "no results".
  useEffect(() => {
    setPage(0)
  }, [libraryId, q, status, sort, ascending])

  const result = useAsync(
    (signal) => listAllBooks({
      q: q.trim() || undefined,
      libraryId, status, sort, ascending,
      limit: PAGE, offset: page * PAGE,
    }, { signal }),
    [libraryId, q, status, sort, ascending, page],
  )

  const rows = useMemo(() => {
    const items = result.data?.items ?? []
    return items.flatMap((book) => {
      if (!overrides.has(book.id)) return [book]
      const replacement = overrides.get(book.id)
      return replacement ? [replacement] : []
    })
  }, [result.data, overrides])

  const onChanged = (bookId: string, book: StaffBook | null) => {
    setOverrides((prev) => new Map(prev).set(bookId, book))
    if (book === null) setSelected(undefined)
    else setSelected((cur) => (cur && cur.id === bookId ? book : cur))
  }

  if (sysLoading) return <Loading />

  const total = result.data?.total ?? 0
  const searching = q.trim().length > 0
  const lastPage = Math.max(0, Math.ceil(total / PAGE) - 1)

  return (
    <>
      <h1>{t.books_title}</h1>
      <p className="sub">{t.sys_scope}</p>

      <div className="row" style={{ marginBottom: 12 }}>
        <Select value={libraryId ?? ''} aria-label={t.bp_library}
                onChange={(e) => {
                  const next = e.target.value || undefined
                  setLibraryId(next)
                  // The route carries the narrowing, so a reload or a shared
                  // link lands on the same view.
                  navigate({ name: 'books', libraryId: next })
                }}>
          <option value="">{t.books_all_libraries}</option>
          {libraries.map((lib) => (
            <option key={lib.id} value={lib.id}>
              {libraryName(lib.label, t.lib_unnamed)}
            </option>
          ))}
        </Select>

        <input type="search" value={typed} placeholder={t.books_search}
               aria-label={t.books_search} className="rtl-safe"
               style={{ flex: '1 1 220px' }}
               onChange={(e) => setTyped(e.target.value)} />

        <Select value={status ?? ''} aria-label={t.th_status}
                onChange={(e) => setStatus(e.target.value || undefined)}>
          <option value="">{t.books_status_any}</option>
          {/* The same three words the badge in the table uses — from the
              shared table, so a filter and the rows it produces cannot come
              to name one state two ways. */}
          <option value="auto">{ui.st_auto}</option>
          <option value="approved">{ui.st_approved}</option>
          <option value="manual">{ui.st_manual}</option>
        </Select>

        {/* The product's control, shared (`@booksnap/ui`) rather than the
            bare select + ↑/↓ button this screen used to draw. That version
            read as two questions and, worse, carried A–Z's "ascending" onto
            the date key on a key change — the bug the reset below prevents,
            declared per option so it cannot be forgotten.

            ⚠ Inert while searching: the server ranks by RELEVANCE (P1.5's
            measured Hebrew search) and ignores `sort`, so a live control
            would promise an ordering nobody applies. */}
        <SortControl
          value={sort}
          ascending={ascending}
          options={SORT_OPTIONS.map((o) => ({ ...o, label: t[o.label] }))}
          label={t.books_sort}
          disabled={searching}
          disabledReason={t.books_sort_ignored}
          // The box says what the ordering IS while searching, rather than a
          // key the server is ignoring — the product's own behaviour, and the
          // reason the shared control has this prop at all.
          inertOption={{ value: 'relevance', label: t.books_sort_relevance }}
          onChange={(next, asc) => {
            setSort(next as Sort)
            setAscending(asc)
          }}
        />
      </div>

      {searching && <p className="sub">{t.books_sort_ignored}</p>}
      {result.data?.truncated && <p className="note warn">{t.books_truncated}</p>}

      {result.error && <ErrorBox message={result.error} onRetry={result.reload} />}
      {result.loading && <Loading />}
      {!result.loading && rows.length === 0 && <Empty>{t.books_empty}</Empty>}

      {rows.length > 0 && (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.th_title}</th>
                <th>{t.th_author}</th>
                <th>{t.th_status}</th>
                {!libraryId && <th>{t.th_library}</th>}
                <th className="num">{t.th_copies}</th>
                <th>{t.th_added}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((book) => (
                <tr key={`${book.library_id}:${book.id}`}
                    onClick={() => setSelected(book)}
                    style={{ cursor: 'pointer' }}>
                  <td className="rtl-safe">
                    <button type="button" className="btn link"
                            onClick={(e) => { e.stopPropagation(); setSelected(book) }}>
                      <span className="t">{book.title}</span>
                    </button>
                  </td>
                  <td className="rtl-safe a">{book.author}</td>
                  <td><StatusBadge status={book.status} /></td>
                  {!libraryId && (
                    <td className="rtl-safe a">
                      {libraryName(labelOf(book.library_id), t.lib_unnamed)}
                    </td>
                  )}
                  <td className="num">{book.copy_count}</td>
                  <td>{formatDate(book.added_at, lang) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="row" style={{ marginTop: 12 }}>
        <span className="sub" style={{ margin: 0 }}>
          {t.books_count(Math.min((page + 1) * PAGE, total), total)}
        </span>
        <button type="button" className="btn small" disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}>
          {t.books_prev}
        </button>
        <button type="button" className="btn small" disabled={page >= lastPage}
                onClick={() => setPage((p) => p + 1)}>
          {t.books_next}
        </button>
        <button type="button" className="btn small" onClick={result.reload}>
          {t.refresh}
        </button>
        <span className="sub" style={{ margin: 0 }}>
          {formatNumber(page + 1, lang)} / {formatNumber(lastPage + 1, lang)}
        </span>
      </div>

      {selected && (
        // ⚠ Keyed on the book, so choosing another row REMOUNTS the panel and
        // a half-typed edit cannot survive onto a different book. See the
        // panel's own note for why this is a key rather than an effect.
        <BookPanel key={`${selected.library_id}:${selected.id}`}
                   book={selected}
                   libraryLabel={libraryName(labelOf(selected.library_id), t.lib_unnamed)}
                   writable={canWrite(selected.library_id)}
                   onClose={() => setSelected(undefined)}
                   onChanged={onChanged} />
      )}
    </>
  )
}
