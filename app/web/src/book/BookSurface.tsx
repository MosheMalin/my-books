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
 *   Where it is / Copies .. location comes from the map (P6); a second copy
 *                           only ever exists after "I have another copy" (P1.7),
 *                           and §5.1 says the word "copies" appears only when
 *                           there is more than one — so today, never
 *   Mine (rating/notes) ... VISION §6 "Should", phase 2; no API for it yet
 *   Where it was seen ..... reads belong to a shelf (P2.5)
 *   remove from shelf ..... there is no shelf to remove from until P2.1
 *
 * A greyed-out control that can never be clicked reads as a bug. Absence reads
 * as a product that has not grown that far, which is the truth.
 */
import { useEffect, useRef, useState } from 'react'
import type { Book } from '../api/client'
import { isConflict, useBooks } from '../lib/books'
import { useI18n } from '../lib/i18n'
import { StatusBadge } from '../books/Feed'

function formatDate(iso: string | null | undefined, lang: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(lang === 'he' ? 'he-IL' : 'en-GB', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

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

  // A different book arrived in the same mount (the drawer stays open while
  // the user clicks another row): drop any half-finished edit rather than
  // carrying one book's text onto another.
  useEffect(() => {
    setEditing(false)
    setConfirming(false)
    setError(null)
    setTitle(book.title)
    setAuthor(book.author)
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

  const lastSeen = book.copies[0]?.last_seen?.captured_at

  return (
    <div className="dbody">
      <div className="bhero">
        {editing ? (
          <form className="editform" onSubmit={save}>
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
          <>
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
          </>
        )}
      </div>

      <dl className="bookmeta">
        {book.added_at && (
          <>
            <dt>{t.added_at}</dt>
            <dd>{formatDate(book.added_at, lang)}</dd>
          </>
        )}
        {lastSeen && (
          <>
            <dt>{t.last_seen}</dt>
            <dd>{formatDate(lastSeen, lang)}</dd>
          </>
        )}
      </dl>

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
