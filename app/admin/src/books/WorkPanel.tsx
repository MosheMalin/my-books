/**
 * One WORK — what it is, and where it stands. **Nothing else.**
 *
 * ⚠⚠ **No library, no shelf, at the top.** That is the owner's instruction for
 * this panel — *"same upon book's info, no library no shelf. maybe number of
 * libraries and first found (across all libs)"* — and it is not cosmetic: a
 * work does not HAVE a library. The households appear below, as a list, which
 * is the only place the question "whose copy?" has an answer.
 *
 * ⚠⚠ **THE CONSOLE DOES NOT MODERATE A HOUSEHOLD'S BOOKS** (owner,
 * 2026-08-13). This panel offered approve, edit and delete on any copy the
 * operator happened to be a member of, behind revision 2's
 * read-cross-tenant / write-your-own-memberships split. The owner removed the
 * capability outright:
 *
 *   > in the list of libraries — I should not be able to approve it or remove
 *   > it or edit it. this is not mine to do so. I can only see info about it
 *   > and about the libraries.
 *
 * The old split answered "may this request succeed?"; the rule is now about
 * WHOSE JOB IT IS. That an operator happens to hold a membership in one
 * household is an accident of this being the owner's own machine, not a
 * licence to retitle their books from a system console — and the console has
 * no login and no audit trail to justify one. Moderation lives in the
 * household's own app, where the person doing it owns the shelf.
 *
 * ⚠ It is ABSENT, not disabled, and absent STRUCTURALLY: `api/client.ts` no
 * longer exports `approveBook`/`patchBook`/`deleteBook` at all, and
 * `boundaries.test.ts` fails if they come back. A hidden button is a decision
 * someone re-reads as an oversight; a missing function is a decision someone
 * has to argue with.
 *
 * ⚠ What the console still writes is TENANCY, never CONTENT: create a library
 * and rename one, on the accounts screen. That is the line — administering a
 * customer's account versus editing their catalogue.
 */
import { useEffect, useRef } from 'react'

import { listWorkInstances, type StaffBook, type StaffWork } from '../api/staff'
import { useI18n } from '../lib/i18n'
import { LibraryName } from '../lib/ui'
import {
  Empty, ErrorBox, Loading, StatusBadge, formatDate, formatNumber, useAsync,
} from '@booksnap/ui'

export function WorkPanel({ work, onClose }: {
  work: StaffWork
  onClose: () => void
}) {
  const { t, lang } = useI18n()
  const closeRef = useRef<HTMLButtonElement>(null)

  // ⚠ `onClose` is a fresh closure on every parent render, so this effect must
  // NOT depend on it — it would tear down and re-run on every repaint,
  // stealing focus back to the close button mid-typing. Held in a ref so the
  // listener is installed once and still calls the current one.
  const closeApi = useRef(onClose)
  closeApi.current = onClose

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeApi.current() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const instances = useAsync(
    (signal) => listWorkInstances(work.key, { signal }), [work.key])

  const num = (n: number) => formatNumber(n, lang)

  /**
   * ⚠ Still DERIVED from the instances rather than read off the row, though
   * nothing here can change them any more. The reason survives the removal of
   * the write path: the row is a snapshot taken when the drawer opened, and
   * the list behind it refetches on its own schedule, so the instances — which
   * arrive with this panel — are the fresher of the two. The row is the
   * fallback for the moment before they land. The two agree by construction:
   * the server derives the aggregate from the same rows.
   *
   * ⚠ No `status` and no `mixed`. See the table on the list screen: a work
   * does not have a status, and the strongest-claim-across-households answer
   * this used to show was the same fiction one level in.
   */
  const rows = instances.data
  const summary = rows === undefined ? {
    libraries: work.libraries, copies: work.copies,
  } : {
    libraries: new Set(rows.map((r) => r.library_id)).size,
    copies: rows.reduce((n, r) => n + r.copy_count, 0),
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="panel" role="dialog" aria-label={t.bp_title}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <strong>{t.bp_title}</strong>
          <button type="button" className="btn small" ref={closeRef} onClick={onClose}>
            {t.close}
          </button>
        </div>

        <div style={{ marginTop: 12 }}>
          <h2 className="rtl-safe" style={{ margin: '0 0 2px' }}>{work.title}</h2>
          <div className="a rtl-safe">{work.author}</div>
        </div>

        <div style={{ marginTop: 14 }}>
          <div className="kv">
            <span className="k">{t.th_libraries}</span>
            <span>{num(summary.libraries)}</span>
          </div>
          <div className="kv">
            <span className="k">{t.bp_copies}</span>
            <span>{num(summary.copies)}</span>
          </div>
          <div className="kv">
            <span className="k">{t.th_first_found}</span>
            <span>{formatDate(work.first_added, lang) || '—'}</span>
          </div>
          {/* ⚠ Shown only when it differs. "First found" and "last added" on
              the same date is one event described twice, and a panel that
              repeats itself teaches the reader to skim. */}
          {work.last_added && work.last_added !== work.first_added && (
            <div className="kv">
              <span className="k">{t.works_last_added}</span>
              <span>{formatDate(work.last_added, lang) || '—'}</span>
            </div>
          )}
        </div>

        {/* ⚠ The DISPLAY spelling above is one household's, chosen by a rule
            (strongest claim, then earliest). Two houses may spell one work two
            ways that normalize alike — that is what the key is for — so the
            panel says which title it is showing rather than implying the work
            has one. */}
        {summary.libraries > 1 && (
          <p className="sub" style={{ marginTop: 8 }}>{t.works_display_title}</p>
        )}

        <h3 style={{ marginTop: 18 }}>{t.works_where}</h3>
        {instances.error && (
          <ErrorBox message={instances.error} onRetry={instances.reload} />
        )}
        {instances.loading && <Loading />}
        {instances.data && instances.data.length === 0 && (
          <Empty>{t.works_gone}</Empty>
        )}
        {instances.data?.map((instance) => (
          <Instance key={`${instance.library_id}:${instance.id}`}
                    book={instance} />
        ))}

        {/* ⚠ Said ONCE, at the bottom, rather than on every card — and said
            at all because "absent, not disabled" only works if the absence is
            explained. An operator who used to approve a book from here needs
            to know the capability was removed on purpose and where it went,
            not wonder whether the buttons failed to render. */}
        {instances.data && instances.data.length > 0 && (
          <p className="note" style={{ marginTop: 12 }}>{t.books_readonly}</p>
        )}
      </aside>
    </>
  )
}

/**
 * One household's copy — INFORMATION, and nothing to press.
 *
 * ⚠⚠ It carried approve / edit / delete until 2026-08-13. The owner's rule is
 * that moderating a household's catalogue is not a system operator's job, so
 * the card reports and stops: which collection and which CUSTOMER holds it,
 * that household's own spelling, its §5.1 status, how many copies on how many
 * shelves, and when it arrived.
 *
 * ⚠ The status badge STAYS here, and only here. It is the accurate thing: this
 * is one copy, in one library, in one state. What was removed is the AGGREGATE
 * — the panel's summary and the list's column — because a work held by two
 * households in two states has no single status to show.
 *
 * ⚠ Naming the account is the point of the card's heading. `My library` tells
 * an operator nothing about whose shelf it is, and one customer may own
 * several collections since P3.7b.
 */
function Instance({ book }: { book: StaffBook }) {
  const { t, lang } = useI18n()

  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong><LibraryName libraryId={book.library_id} /></strong>
        <StatusBadge status={book.status} />
      </div>

      {/* The household's OWN spelling, when it is not the one the panel is
          titled with — otherwise the operator cannot tell why two rows
          normalize to one work. */}
      {/* ⚠ TWO elements, not one string. `.rtl-safe` is
          `unicode-bidi: plaintext`, which resolves ONE direction per paragraph
          from its first strong character — so a Hebrew title beside a Latin
          author would lay the author out in the title's direction and put the
          separator on the wrong side. Direction per STRING is the rule
          (CLAUDE.md, §7.2); the panel's own heading two blocks up already
          splits them for the same reason. */}
      <div className="rtl-safe a" style={{ marginTop: 2 }}>{book.title}</div>
      {book.author && <div className="rtl-safe a">{book.author}</div>}

      <div className="sub" style={{ marginTop: 4 }}>
        {t.works_copies_here(book.copy_count)}
        {' · '}
        {book.shelf_count > 0
          ? t.works_on_shelves(book.shelf_count)
          : t.bp_unshelved}
        {' · '}
        {formatDate(book.added_at, lang) || '—'}
      </div>
    </div>
  )
}
