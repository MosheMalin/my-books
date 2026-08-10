/**
 * One book, and the three things an operator may do to it — where they may.
 *
 * ⚠⚠ **Reading is cross-tenant; writing is not, and this is the screen where
 * that distinction becomes visible.** The row came from the staff service,
 * which spans every tenant and never writes. The three actions go through the
 * ordinary product API, which resolves the caller's own membership and answers
 * 404 for anything else (§4.2). So `writable` is false for a book in a library
 * the operator does not belong to, and the panel says so instead of offering
 * buttons that would 404 on click.
 *
 * That is a deliberate limit, not a missing feature: a system administrator
 * silently rewriting a household's book titles is a power this product has no
 * reason to grant before it has a login, an audit trail, or anyone to explain
 * it to.
 *
 * Where writing IS allowed, all three are doors the product already has (H3 —
 * the console does not grow a fourth way to write a title):
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
 * ⚠⚠ **A half-typed edit must not survive onto a different book**, or the next
 * Save renames the wrong one — across tenants, at that. The reset is done by
 * the CALLER keying this component on the book, not by an effect copying props
 * into state. The effect version was written first and was reproducibly
 * broken: the focus effect above it depended on `onClose`, a fresh closure
 * every render, so it re-ran on every commit — and `.focus()` blurring the
 * edited input makes React fire a change for the controlled value, which
 * re-renders DURING the effect flush and leaves the reset effect comparing
 * against the very values it was meant to react to. It silently never ran.
 */
import { useEffect, useRef, useState } from 'react'

import { approveBook, deleteBook, patchBook } from '../api/client'
import type { StaffBook } from '../api/staff'
import { useI18n } from '../lib/i18n'
import { ErrorBox, formatDate, StatusBadge, vouchedFor } from '@booksnap/ui'

export function BookPanel({ book, libraryLabel, writable, onClose, onChanged }: {
  book: StaffBook
  libraryLabel: string
  writable: boolean
  onClose: () => void
  onChanged: (bookId: string, book: StaffBook | null) => void
}) {
  const { t, lang } = useI18n()

  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(book.title)
  const [author, setAuthor] = useState(book.author)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)
  const [flash, setFlash] = useState<string | undefined>(undefined)

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
    const updated = await patchBook(book.library_id, book.id, { title, author })
    // The product returns its OWN BookDTO; only the fields this list renders
    // are carried across, so the staff row stays the shape the table expects.
    onChanged(book.id, { ...book, title: updated.title, author: updated.author,
                         status: updated.status, copy_count: updated.copy_count })
    setEditing(false)
    setFlash(t.bp_saved)
  })

  const approve = () => run(async () => {
    const updated = await approveBook(book.library_id, book.id)
    onChanged(book.id, { ...book, status: updated.status })
    setFlash(t.bp_approved)
  })

  const remove = () => run(async () => {
    await deleteBook(book.library_id, book.id)
    onChanged(book.id, null)
  })

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

        {editing ? (
          <div style={{ marginTop: 12 }}>
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
            <div className="row" style={{ marginTop: 10 }}>
              <button type="button" className="btn primary"
                      disabled={busy || !title.trim()} onClick={save}>
                {t.save}
              </button>
              <button type="button" className="btn" onClick={() => {
                setEditing(false)
                setTitle(book.title)
                setAuthor(book.author)
              }}>
                {t.cancel}
              </button>
            </div>
          </div>
        ) : (
          <div style={{ marginTop: 12 }}>
            <h2 className="rtl-safe" style={{ margin: '0 0 2px' }}>{book.title}</h2>
            <div className="a rtl-safe">{book.author}</div>
          </div>
        )}

        {flash && <p className="note" style={{ marginTop: 10 }}>{flash}</p>}
        {error && <div style={{ marginTop: 10 }}><ErrorBox message={error} /></div>}

        <div style={{ marginTop: 14 }}>
          <div className="kv">
            <span className="k">{t.bp_library}</span>
            <span className="rtl-safe">{libraryLabel}</span>
          </div>
          <div className="kv">
            <span className="k">{t.bp_status}</span>
            <StatusBadge status={book.status} />
          </div>
          <div className="kv">
            <span className="k">{t.bp_copies}</span>
            <span>{book.copy_count}</span>
          </div>
          <div className="kv">
            <span className="k">{t.bp_shelf}</span>
            <span>{book.shelf_count > 0 ? book.shelf_count : t.bp_unshelved}</span>
          </div>
          <div className="kv">
            <span className="k">{t.bp_added}</span>
            <span>{formatDate(book.added_at, lang) || '—'}</span>
          </div>
          <div className="kv">
            <span className="k">{t.lib_id}</span>
            <span className="mono">{book.id}</span>
          </div>
        </div>

        {!writable ? (
          <p className="note warn" style={{ marginTop: 14 }}>{t.books_readonly}</p>
        ) : (
          <>
            <div className="row" style={{ marginTop: 14 }}>
              {!vouchedFor(book.status) && (
                <button type="button" className="btn primary" disabled={busy}
                        onClick={approve}>
                  {t.bp_approve}
                </button>
              )}
              {!editing && (
                <button type="button" className="btn" disabled={busy}
                        onClick={() => setEditing(true)}>
                  {t.bp_edit}
                </button>
              )}
            </div>

            <div className="dangerzone">
              {confirming ? (
                <>
                  <p className="rtl-safe">{t.bp_delete_confirm}</p>
                  <div className="row">
                    <button type="button" className="btn danger" disabled={busy}
                            onClick={remove}>
                      {t.bp_delete_yes}
                    </button>
                    <button type="button" className="btn"
                            onClick={() => setConfirming(false)}>
                      {t.cancel}
                    </button>
                  </div>
                </>
              ) : (
                <button type="button" className="btn"
                        onClick={() => setConfirming(true)}>
                  {t.bp_delete}
                </button>
              )}
            </div>
          </>
        )}
      </aside>
    </>
  )
}
