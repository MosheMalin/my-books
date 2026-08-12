/**
 * Every book in the system, as a CATALOGUE rather than a pile of household
 * lists — one row per work, across every tenant.
 *
 * ⚠⚠ **There is no library column, and its absence is the item.** The owner's
 * note that opened console revision 4:
 *
 *   > unlike the user application, it should not think in terms of a single
 *   > library or single account. when it comes to books info, it's either
 *   > about aggregation or lists.
 *
 * A book row used to be `(library_id, book id)`, which made this screen a
 * concatenation of household lists — it answered *whose is it*, a question an
 * operator never asks. It now answers *how widespread is it*: how many
 * libraries hold this work, and when it was first seen anywhere. The
 * households are behind the drawer, because that is where acting on one
 * belongs.
 *
 * ⚠ The library SELECT survives as a filter. "Works present in library X" is a
 * legitimate narrowing and it is how the account screen links in here. It does
 * not change what a row reports: a work in three libraries still says three
 * while the list is filtered to one — see the server's HAVING-not-WHERE note.
 *
 * ⚠ Reading spans every tenant; WRITING does not, and that is unchanged. The
 * moderation actions live in the drawer's per-household list and go through
 * the product API, which resolves the operator's own membership.
 */
import { useEffect, useMemo, useState } from 'react'

import { listWorks, type StaffWork } from '../api/staff'
import { useI18n, type Strings } from '../lib/i18n'
import { navigate } from '../lib/route'
import { useSystem } from '../lib/system'
import { LibraryPicker } from '../lib/ui'
import {
  Empty, ErrorBox, Loading, SortControl, formatDate, formatNumber, useAsync,
  Select,
} from '@booksnap/ui'
import { WorkPanel } from './WorkPanel'

/** Rows per screen. */
const PAGE = 25

/** Typing pauses before a request goes out. Matches the product's own. */
const DEBOUNCE_MS = 250

type Sort = 'title' | 'author' | 'first_added' | 'libraries'

/**
 * What this screen can sort by, and — the load-bearing half — the direction
 * each key MEANS. A–Z for text, newest first for a date, widest first for a
 * count: carrying A–Z's "ascending" onto a date key silently answers a
 * question nobody asked.
 *
 * ⚠ Declared here, per option, rather than as a rule inside the shared
 * control: which keys exist is this screen's business, and a control guessing
 * a direction from a key's NAME would be wrong the first time a screen added
 * one it had not seen.
 */
const SORT_OPTIONS = [
  { value: 'title', label: 'sort_title' },
  { value: 'author', label: 'sort_author' },
  { value: 'first_added', label: 'sort_first_found', naturalAscending: false },
  { value: 'libraries', label: 'sort_spread', naturalAscending: false },
] as const satisfies readonly { value: Sort; label: keyof Strings; naturalAscending?: boolean }[]

export function BooksPage({ initialLibraryId }: { initialLibraryId: string | undefined }) {
  const { t, ui, lang } = useI18n()
  const { loading: sysLoading } = useSystem()

  const [libraryId, setLibraryId] = useState<string | undefined>(initialLibraryId)
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [sort, setSort] = useState<Sort>('title')
  const [ascending, setAscending] = useState(true)
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<StaffWork | undefined>(undefined)

  useEffect(() => {
    const id = setTimeout(() => setQ(typed), DEBOUNCE_MS)
    return () => clearTimeout(id)
  }, [typed])

  // Any change to WHAT is being asked returns to the first page. Staying on
  // page 4 of a filter that now matches 12 works shows an empty table, which
  // reads as "no results".
  useEffect(() => {
    setPage(0)
  }, [libraryId, q, status, sort, ascending])

  const result = useAsync(
    (signal) => listWorks({
      q: q.trim() || undefined,
      libraryId, status, sort, ascending,
      limit: PAGE, offset: page * PAGE,
    }, { signal }),
    [libraryId, q, status, sort, ascending, page],
  )

  const rows = useMemo(() => result.data?.items ?? [], [result.data])

  if (sysLoading) return <Loading />

  const total = result.data?.total ?? 0
  const searching = q.trim().length > 0
  const lastPage = Math.max(0, Math.ceil(total / PAGE) - 1)
  const num = (n: number) => formatNumber(n, lang)

  return (
    <>
      <h1>{t.books_title}</h1>
      <p className="sub">{t.works_sub}</p>

      <div className="row" style={{ marginBottom: 12 }}>
        {/* Grouped by CUSTOMER — a collection name alone does not say whose
            shelf it is, and one account may own several. */}
        <LibraryPicker value={libraryId} onChange={(next) => {
          setLibraryId(next)
          // The route carries the narrowing, so a reload or a shared link
          // lands on the same view.
          navigate({ name: 'books', libraryId: next })
        }} />

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

        {/* ⚠ Inert while searching: the server ranks by RELEVANCE (P1.5's
            measured Hebrew search) and ignores `sort`, so a live control would
            promise an ordering nobody applies. The box READS "relevance" —
            the ordering actually in force — rather than a key being ignored. */}
        <SortControl
          value={sort}
          ascending={ascending}
          options={SORT_OPTIONS.map((o) => ({ ...o, label: t[o.label] }))}
          label={t.books_sort}
          disabled={searching}
          disabledReason={t.books_sort_ignored}
          inertOption={{ value: 'relevance', label: t.books_sort_relevance }}
          onChange={(next, asc) => {
            setSort(next as Sort)
            setAscending(asc)
          }}
        />
      </div>

      {/* ⚠ BOTH filters, not just status. A review caught that the sentence
          explaining what a filter does not change was missing for the
          LIBRARY filter — the one revision 4 is actually about. */}
      {(status || libraryId) && <p className="sub">{t.works_filter_keeps_spread}</p>}
      {/* ⚠ The filter survives the column's removal, and means something the
          column could not: "works with AT LEAST ONE copy in this state". That
          is a real question — "is anything out there still unapproved?" — and
          it is answerable precisely because it does not claim the work HAS a
          status. Said out loud, since the rows no longer show one. */}
      {status && <p className="sub">{t.works_status_selects}</p>}
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
                {/* ⚠⚠ NO STATUS COLUMN (owner, 2026-08-13): *"in 2 libraries
                    it can be different status. what to display? simply do not
                    display."* A work is an aggregate across households and
                    §5.1 is a property of one COPY in one library, so there is
                    no honest single answer — showing the strongest would tell
                    an operator asking "is anything unapproved out there?" a
                    confident no. The status lives where it is true: on each
                    household's card in the drawer. */}
                <th className="num">{t.th_libraries}</th>
                <th className="num">{t.th_copies}</th>
                <th>{t.th_first_found}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((work) => (
                <tr key={work.key} onClick={() => setSelected(work)}
                    style={{ cursor: 'pointer' }}>
                  <td className="rtl-safe">
                    <button type="button" className="btn link"
                            onClick={(e) => { e.stopPropagation(); setSelected(work) }}>
                      <span className="t">{work.title}</span>
                    </button>
                  </td>
                  <td className="rtl-safe a">{work.author}</td>
                  <td className="num">
                    {/* The number IS the link — the owner's own sketch. It
                        opens the same drawer the title does, because the list
                        of households is what the drawer is mostly for. */}
                    <button type="button" className="btn link"
                            aria-label={t.works_open_spread(work.libraries)}
                            onClick={(e) => { e.stopPropagation(); setSelected(work) }}>
                      {num(work.libraries)}
                    </button>
                  </td>
                  <td className="num">{num(work.copies)}</td>
                  <td>{formatDate(work.first_added, lang) || '—'}</td>
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
        // ⚠ Still keyed on the work: choosing another row REMOUNTS the panel,
        // so its instance fetch cannot show the previous book's households
        // while the new one loads. (It used to also reset a half-typed edit —
        // that editor is gone, but the remount is right for the fetch too.)
        <WorkPanel key={selected.key}
                   work={selected}
                   onClose={() => setSelected(undefined)} />
      )}
    </>
  )
}
