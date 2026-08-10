/**
 * The book surface — ONE renderer, two mounts (UI_PLAN §5).
 *
 * The drawer and the full page differ only in their wrapper. That is the whole
 * point: two implementations of one screen drift, and the drift is invisible
 * until someone reports that editing works in one place and not the other.
 *
 * Sections UI_PLAN §5 describes that are NOT here, and why each is absent
 * rather than stubbed:
 *
 *   spine crop ............ needs a BlobStore (P3.5)
 *   Where it is (location) . comes from the map (P6) — every copy is
 *                           unlocated until then, so there is nothing to show
 *   Mine (rating/notes) ... VISION §6 "Should", phase 2; no API for it yet
 *   Where it was seen ..... reads belong to a shelf (P2.5)
 *   remove from shelf ..... there is no shelf to remove from until P2.1
 *
 * Copies graduated out of this list at P1.7: label/tags/condition, lending
 * and "I have another copy" are built below. The word "copies" and the count
 * still appear only when there's more than one (§5.1) — a book that has never
 * needed the concept should not be introduced to it.
 *
 * A greyed-out control that can never be clicked reads as a bug. Absence reads
 * as a product that has not grown that far, which is the truth.
 */
import { useEffect, useRef, useState } from 'react'
import type { Book, Copy } from '../api/client'
import { isConflict, useBooks } from '../lib/books'
import { formatDate } from '@booksnap/ui'
import { useI18n } from '../lib/i18n'
import { CopyBadges, StatusBadge } from '../books/Feed'

export interface BookSurfaceProps {
  book: Book
  /** Full page rather than drawer. Changes the wrapper, never the content. */
  full?: boolean
  onAuthor: (authorKey: string) => void
  onPromote?: (() => void) | undefined
  onDeleted: () => void
}

export function BookSurface({
  book,
  full = false,
  onAuthor,
  onPromote,
  onDeleted,
}: BookSurfaceProps) {
  const { t, lang } = useI18n()
  const books = useBooks()

  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(book.title)
  const [author, setAuthor] = useState(book.author)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Which copy has an open form, and which kind — at most one at a time,
  // same idiom as `editing` above. A copy id alone would not distinguish
  // "editing its label" from "lending it".
  const [copyAction, setCopyAction] =
    useState<{ id: string; kind: 'edit' | 'lend' } | null>(null)
  const [copyLabel, setCopyLabel] = useState('')
  const [copyTags, setCopyTags] = useState('')
  const [copyCondition, setCopyCondition] = useState('')
  const [lendTo, setLendTo] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [copyError, setCopyError] = useState<string | null>(null)
  const [copySaving, setCopySaving] = useState(false)

  // A different book arrived in the same mount (the drawer stays open while
  // the user clicks another row): drop any half-finished edit rather than
  // carrying one book's text onto another.
  useEffect(() => {
    setEditing(false)
    setConfirming(false)
    setError(null)
    setTitle(book.title)
    setAuthor(book.author)
    setCopyAction(null)
    setCopyError(null)
  }, [book.id, book.title, book.author])

  useEffect(() => () => {
    if (savedTimer.current) clearTimeout(savedTimer.current)
  }, [])

  const flashSaved = () => {
    setSaved(true)
    if (savedTimer.current) clearTimeout(savedTimer.current)
    savedTimer.current = setTimeout(() => setSaved(false), 2200)
  }

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      await books.edit(book.id, { title: title.trim(), author: author.trim() })
      setEditing(false)
      flashSaved()
    } catch (err) {
      // 409 is a normal answer — you already own a book with that title and
      // author. Resolving it (merge? keep both?) is a decision nobody has
      // made yet, so the edit is refused and the form stays open with the
      // text intact.
      setError(isConflict(err) ? t.conflict_edit : String(err))
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    try {
      await books.remove(book.id)
      onDeleted()
    } catch (err) {
      setError(String(err))
      setConfirming(false)
    }
  }

  const startEditCopy = (copy: Copy) => {
    setCopyAction({ id: copy.id, kind: 'edit' })
    setCopyLabel(copy.label)
    // Optional in the generated type: `tags: list[str] = Field(default_factory=list)`
    // has no OpenAPI `default`, so openapi-typescript can't tell it is never
    // actually absent — the server always sends a (possibly empty) array.
    setCopyTags((copy.tags ?? []).join(', '))
    setCopyCondition(copy.condition)
    setCopyError(null)
  }
  const startLend = (copy: Copy) => {
    setCopyAction({ id: copy.id, kind: 'lend' })
    setLendTo('')
    setDueAt('')
    setCopyError(null)
  }
  const cancelCopyAction = () => {
    setCopyAction(null)
    setCopyError(null)
  }

  const saveCopyEdit = async (e: React.FormEvent, copyId: string) => {
    e.preventDefault()
    if (copySaving) return
    setCopySaving(true)
    setCopyError(null)
    try {
      await books.patchCopy(book.id, copyId, {
        label: copyLabel.trim(),
        // Blank entries are dropped rather than stored as empty tags — a
        // trailing comma from typing should not become a tag made of nothing.
        tags: copyTags.split(',').map((s) => s.trim()).filter(Boolean),
        condition: copyCondition.trim(),
      })
      setCopyAction(null)
      flashSaved()
    } catch (err) {
      setCopyError(String(err))
    } finally {
      setCopySaving(false)
    }
  }

  const submitLend = async (e: React.FormEvent, copyId: string) => {
    e.preventDefault()
    if (copySaving) return
    setCopySaving(true)
    setCopyError(null)
    try {
      await books.lendCopy(book.id, copyId,
        { lent_to: lendTo.trim(), due_at: dueAt || null })
      setCopyAction(null)
      flashSaved()
    } catch (err) {
      setCopyError(String(err))
    } finally {
      setCopySaving(false)
    }
  }

  const markReturned = async (copyId: string) => {
    if (copySaving) return
    setCopySaving(true)
    setCopyError(null)
    try {
      await books.returnCopy(book.id, copyId)
      flashSaved()
    } catch (err) {
      setCopyError(String(err))
    } finally {
      setCopySaving(false)
    }
  }

  const addCopy = async () => {
    if (copySaving) return
    setCopySaving(true)
    setCopyError(null)
    try {
      // Blank on purpose — clicking IS the declaration (§5.1: the strongest
      // evidence the system gets). Label/tags/condition are filled in after,
      // through the same edit form every other copy uses.
      await books.addCopy(book.id, { label: '', tags: [], condition: '' })
      flashSaved()
    } catch (err) {
      setCopyError(String(err))
    } finally {
      setCopySaving(false)
    }
  }

  return (
    <div className="dbody">
      <div className="bhero">
        {editing ? (
          <form className="herobody" onSubmit={save}>
            <label className="field">
              <span>{t.title_label}</span>
              <input
                className="rtl-safe"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                autoFocus
              />
            </label>
            <label className="field">
              <span>{t.author_label}</span>
              <input
                className="rtl-safe"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
              />
            </label>
            {error && <p className="hint warn" role="alert">{error}</p>}
            <div className="modalfoot">
              <button
                type="button"
                className="btn ghost"
                onClick={() => {
                  setEditing(false)
                  setError(null)
                  setTitle(book.title)
                  setAuthor(book.author)
                }}
              >
                {t.cancel}
              </button>
              <button type="submit" className="btn primary" disabled={saving}>
                {t.save}
              </button>
            </div>
          </form>
        ) : (
          <div className="herobody">
            <h2 className="rtl-safe">{book.title}</h2>
            {book.author && (
              <button
                type="button"
                className="authorlink rtl-safe"
                onClick={() => onAuthor(book.author_key)}
              >
                {book.author}
              </button>
            )}
            <div className="chiprow">
              <StatusBadge status={book.status} />
              <CopyBadges book={book} />
              {saved && <span className="savednote on">{t.saved}</span>}
            </div>
            <div className="modalfoot">
              <button
                type="button"
                className="btn"
                onClick={() => setEditing(true)}
              >
                {t.edit}
              </button>
              {!full && onPromote && (
                <button type="button" className="btn ghost" onClick={onPromote}>
                  ⤢ {t.open_full}
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <dl className="bookmeta">
        {book.added_at && (
          <>
            <dt>{t.added_at}</dt>
            <dd>{formatDate(book.added_at, lang)}</dd>
          </>
        )}
      </dl>

      {/* "Last seen" moved from here into each copy's own box below (it used
          to read `copies[0].last_seen`, quietly ignoring every other copy —
          harmless with one copy, silently wrong with two). */}
      <div className="sect">
        {book.copy_count > 1 && <h4>{t.copies} ({book.copy_count})</h4>}
        {book.copies.map((copy, i) => {
          const active = copyAction?.id === copy.id ? copyAction.kind : null
          return (
            <div className="copybox" key={copy.id}>
              {book.copy_count > 1 && (
                <div className="copyhead">
                  {t.copy_n(i + 1)}{copy.label ? ` · ${copy.label}` : ''}
                </div>
              )}

              {active === 'edit' ? (
                <form className="copyedit"
                     onSubmit={(e) => void saveCopyEdit(e, copy.id)}>
                  <label className="field">
                    <span>{t.copy_label}</span>
                    <input
                      className="rtl-safe"
                      value={copyLabel}
                      placeholder={t.copy_label_placeholder}
                      onChange={(e) => setCopyLabel(e.target.value)}
                      autoFocus
                    />
                  </label>
                  <label className="field">
                    <span>{t.copy_tags}</span>
                    <input
                      className="rtl-safe"
                      value={copyTags}
                      placeholder={t.copy_tags_placeholder}
                      onChange={(e) => setCopyTags(e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>{t.copy_condition}</span>
                    <input
                      className="rtl-safe"
                      value={copyCondition}
                      onChange={(e) => setCopyCondition(e.target.value)}
                    />
                  </label>
                  {copyError && <p className="hint warn" role="alert">{copyError}</p>}
                  <div className="modalfoot">
                    <button type="button" className="btn ghost"
                           onClick={cancelCopyAction}>
                      {t.cancel}
                    </button>
                    <button type="submit" className="btn primary" disabled={copySaving}>
                      {t.save}
                    </button>
                  </div>
                </form>
              ) : active === 'lend' ? (
                <form className="lendform"
                     onSubmit={(e) => void submitLend(e, copy.id)}>
                  <label className="field">
                    <span>{t.lend_to_label}</span>
                    <input
                      className="rtl-safe"
                      value={lendTo}
                      onChange={(e) => setLendTo(e.target.value)}
                      required
                      autoFocus
                    />
                  </label>
                  <label className="field">
                    <span>{t.due_at_label}</span>
                    <input
                      type="date"
                      value={dueAt}
                      onChange={(e) => setDueAt(e.target.value)}
                    />
                  </label>
                  {copyError && <p className="hint warn" role="alert">{copyError}</p>}
                  <div className="modalfoot">
                    <button type="button" className="btn ghost"
                           onClick={cancelCopyAction}>
                      {t.cancel}
                    </button>
                    <button type="submit" className="btn primary" disabled={copySaving}>
                      {t.lend_save}
                    </button>
                  </div>
                </form>
              ) : (
                <>
                  {/* Absent, not an empty row — a fresh copy has no label,
                      tags or condition, and a row that always renders would
                      show an empty "Details:" on every book with one copy
                      (§5.1: "never seen the concept" applies here too). */}
                  {(copy.label || (copy.tags?.length ?? 0) > 0 || copy.condition) && (
                    <div className="kv">
                      <span className="k">{t.copy_details}</span>
                      <span className="rtl-safe">
                        {[copy.label, (copy.tags ?? []).join(', '), copy.condition]
                          .filter(Boolean).join(' · ')}
                      </span>
                    </div>
                  )}
                  <div className="kv">
                    <span className="k">{t.lending}</span>
                    <span>
                      {copy.lending?.is_out ? (
                        <>
                          {t.lent_to(copy.lending.lent_to)}
                          {copy.lending.due_at &&
                            ` · ${t.due(formatDate(copy.lending.due_at, lang))}`}
                        </>
                      ) : (
                        <span className="muted">{t.not_lent}</span>
                      )}
                    </span>
                  </div>
                  {copy.last_seen && (
                    <div className="kv">
                      <span className="k">{t.last_seen}</span>
                      <span>{formatDate(copy.last_seen.captured_at, lang)}</span>
                    </div>
                  )}
                  <div className="copyactions">
                    {copy.lending?.is_out ? (
                      <button
                        type="button"
                        className="btn sm ghost"
                        disabled={copySaving}
                        onClick={() => void markReturned(copy.id)}
                      >
                        {t.mark_returned}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn sm ghost"
                        onClick={() => startLend(copy)}
                      >
                        {t.lend_it}
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn sm ghost"
                      onClick={() => startEditCopy(copy)}
                    >
                      {t.copy_edit}
                    </button>
                  </div>
                </>
              )}
            </div>
          )
        })}
        <button type="button" className="btn sm" disabled={copySaving}
               onClick={() => void addCopy()}>
          ＋ {t.add_copy}
        </button>
      </div>

      {/* One of UI_PLAN §5's "two different destructive actions, deliberately
          separate". The other — remove from shelf — arrives with shelves in
          P2.1; it keeps the book and only clears a location, which is why the
          two must never be collapsed into one button. */}
      <div className="dangerzone">
        {confirming ? (
          <>
            <p>{t.delete_confirm}</p>
            <div className="modalfoot">
              <button
                type="button"
                className="btn ghost"
                onClick={() => setConfirming(false)}
              >
                {t.cancel}
              </button>
              <button type="button" className="btn danger" onClick={remove}>
                {t.delete_yes}
              </button>
            </div>
          </>
        ) : (
          <button
            type="button"
            className="btn danger"
            onClick={() => setConfirming(true)}
          >
            {t.delete_book}
          </button>
        )}
      </div>
    </div>
  )
}
