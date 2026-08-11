/**
 * One WORK — what it is, where it stands, and the three things an operator may
 * do to any one household's copy of it.
 *
 * ⚠⚠ **No library, no shelf, at the top.** That is the owner's instruction for
 * this panel — *"same upon book's info, no library no shelf. maybe number of
 * libraries and first found (across all libs)"* — and it is not cosmetic: a
 * work does not HAVE a library. The households appear below, as a list, which
 * is the only place the question "whose copy?" has an answer.
 *
 * ⚠⚠ **Reading is cross-tenant; writing is not**, and this is still the screen
 * where that becomes visible. The instance list came from the staff service,
 * which spans every tenant and never writes. The three actions go through the
 * ordinary product API, which resolves the caller's own membership and answers
 * 404 for anything else (§4.2). So a row for a library the operator does not
 * belong to shows its numbers and says it is read-only, instead of offering
 * buttons that would 404 on click.
 *
 * ⚠⚠ **There is no "approve everywhere".** The aggregate is a reading device;
 * every write is per household, deliberately. A system administrator silently
 * rewriting several households' catalogues in one click is a power this
 * product has no reason to grant before it has a login, an audit trail, or
 * anyone to explain it to — and the fan-out failure mode (three succeed, two
 * 404) has no honest way to be reported.
 *
 * ⚠ **A half-typed edit must not survive onto a different book.** The reset is
 * done by KEYING — the page keys this panel on the work, and this panel keys
 * each editor on the instance. The effect version was written first and was
 * reproducibly broken; `BookPanel`'s retired note recorded exactly why (a
 * focus effect depending on `onClose` re-ran on every commit and the reset
 * effect compared against the values it was meant to react to).
 */
import { useEffect, useRef, useState } from 'react'

import { approveBook, deleteBook, patchBook } from '../api/client'
import { listWorkInstances, type StaffBook, type StaffWork } from '../api/staff'
import { useI18n } from '../lib/i18n'
import { useSystem } from '../lib/system'
import {
  Empty, ErrorBox, Loading, StatusBadge, formatDate, formatNumber,
  libraryName, useAsync, vouchedFor,
} from '@booksnap/ui'

export function WorkPanel({ work, onClose, onChanged }: {
  work: StaffWork
  onClose: () => void
  /** The aggregate changed underneath — a delete can drop a library from the
   *  spread, and a row that still said "3" would be a lie the operator caused
   *  themselves. */
  onChanged: () => void
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

  const afterWrite = () => {
    instances.reload()
    onChanged()
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
            <span>{num(work.libraries)}</span>
          </div>
          <div className="kv">
            <span className="k">{t.bp_status}</span>
            <span>
              <StatusBadge status={work.status} />
              {work.mixed && <> <span className="badge">{t.works_mixed}</span></>}
            </span>
          </div>
          <div className="kv">
            <span className="k">{t.bp_copies}</span>
            <span>{num(work.copies)}</span>
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
        {work.libraries > 1 && (
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
                    book={instance} onChanged={afterWrite} />
        ))}
      </aside>
    </>
  )
}

/**
 * One household's copy, and what may be done to it here.
 *
 * The three actions are doors the product already has (H3 — the console does
 * not grow a fourth way to write a title):
 *
 *   - **approve** — idempotent, never a demotion. ⚠ Offered only on the `auto`
 *     rung: a confirmed finding is created APPROVED and a hand-typed book is
 *     `manual`, which OUTRANKS it (§5.1);
 *   - **edit** — `PATCH /books/{id}`, which the domain marks `manual`, because
 *     a human typing a title is a stronger claim than the engine's reading;
 *   - **delete** — ⚠ not a soft hide: it removes every copy AND records a
 *     standing rejection at each (shelf, depth) the book stood at, so the next
 *     read of that shelf does not put it straight back (§5.6). Hence the
 *     confirmation.
 *
 * ⚠ An edit here can change the book's KEY — retitling it moves that copy to a
 * different work. So a write always re-fetches rather than patching the list
 * in place: the instance may legitimately no longer belong to the work whose
 * panel is open, and a locally-patched row would keep showing it under the old
 * title forever.
 */
function Instance({ book, onChanged }: {
  book: StaffBook
  onChanged: () => void
}) {
  const { t, lang } = useI18n()
  const { canWrite, labelOf } = useSystem()
  const writable = canWrite(book.library_id)

  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(book.title)
  const [author, setAuthor] = useState(book.author)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(undefined)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const save = () => run(async () => {
    await patchBook(book.library_id, book.id, { title, author })
    setEditing(false)
    onChanged()
  })

  const approve = () => run(async () => {
    await approveBook(book.library_id, book.id)
    onChanged()
  })

  const remove = () => run(async () => {
    await deleteBook(book.library_id, book.id)
    onChanged()
  })

  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong className="rtl-safe">
          {libraryName(labelOf(book.library_id), t.lib_unnamed)}
        </strong>
        <StatusBadge status={book.status} />
      </div>

      {/* The household's OWN spelling, when it is not the one the panel is
          titled with — otherwise the operator cannot tell why two rows
          normalize to one work. */}
      <div className="rtl-safe a" style={{ marginTop: 2 }}>
        {book.title}{book.author ? ` · ${book.author}` : ''}
      </div>

      <div className="sub" style={{ marginTop: 4 }}>
        {t.works_copies_here(book.copy_count)}
        {' · '}
        {book.shelf_count > 0
          ? t.works_on_shelves(book.shelf_count)
          : t.bp_unshelved}
        {' · '}
        {formatDate(book.added_at, lang) || '—'}
      </div>

      {error && <div style={{ marginTop: 8 }}><ErrorBox message={error} /></div>}

      {editing && (
        <div style={{ marginTop: 8 }}>
          <label className="field">
            {t.bp_title_label}
            <input type="text" value={title} className="rtl-safe" autoFocus
                   onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="field" style={{ marginTop: 8 }}>
            {t.bp_author_label}
            <input type="text" value={author} className="rtl-safe"
                   onChange={(e) => setAuthor(e.target.value)} />
          </label>
          <p className="sub" style={{ margin: '6px 0 0' }}>{t.works_edit_rekeys}</p>
          <div className="row" style={{ marginTop: 8 }}>
            <button type="button" className="btn small primary"
                    disabled={busy || !title.trim()} onClick={save}>
              {t.save}
            </button>
            <button type="button" className="btn small" onClick={() => {
              setEditing(false)
              setTitle(book.title)
              setAuthor(book.author)
            }}>
              {t.cancel}
            </button>
          </div>
        </div>
      )}

      {!writable ? (
        <p className="note warn" style={{ marginTop: 10 }}>{t.books_readonly}</p>
      ) : (
        <>
          {!editing && (
            <div className="row" style={{ marginTop: 10 }}>
              {!vouchedFor(book.status) && (
                <button type="button" className="btn small primary" disabled={busy}
                        onClick={approve}>
                  {t.bp_approve}
                </button>
              )}
              <button type="button" className="btn small" disabled={busy}
                      onClick={() => setEditing(true)}>
                {t.bp_edit}
              </button>
              {!confirming && (
                <button type="button" className="btn small"
                        onClick={() => setConfirming(true)}>
                  {t.bp_delete}
                </button>
              )}
            </div>
          )}

          {confirming && (
            <div className="dangerzone">
              <p className="rtl-safe">{t.bp_delete_confirm}</p>
              <div className="row">
                <button type="button" className="btn small danger" disabled={busy}
                        onClick={remove}>
                  {t.bp_delete_yes}
                </button>
                <button type="button" className="btn small"
                        onClick={() => setConfirming(false)}>
                  {t.cancel}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
