/**
 * Add a book the reader never found.
 *
 * UI_PLAN §2: the modal *"answers 'is it already here?' as you type"*. It does
 * that with the same `?q=` search the toolbar uses — exact title+author match
 * says you already own it, any other hits say something similar exists, no
 * hits says it is new.
 *
 * The hint is a HINT, not the check. Server-side identity is
 * `normalize(title)|normalize(author)`, which folds spellings this comparison
 * cannot see, so a book can still come back 409 after a green hint. That is
 * fine and deliberate: the hint's job is to stop the obvious duplicate before
 * it is typed, and the 409 is the actual guarantee. Re-implementing normalize()
 * here to close the gap would mean two normalizers, and two normalizers drift.
 */
import { useEffect, useRef, useState } from 'react'
import { listBooks, type Book } from '../api/client'
import { useI18n } from '../lib/i18n'
import { isConflict } from '../lib/books'

type Hint = 'none' | 'similar' | 'exact' | 'idle'

export interface AddBookModalProps {
  onClose: () => void
  onCreate: (payload: { title: string; author: string }) => Promise<Book>
  onCreated: (book: Book) => void
}

export function AddBookModal({ onClose, onCreate, onCreated }: AddBookModalProps) {
  const { t } = useI18n()
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [hint, setHint] = useState<Hint>('idle')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const first = useRef<HTMLInputElement | null>(null)

  useEffect(() => first.current?.focus(), [])

  useEffect(() => {
    const typed = title.trim()
    if (typed.length < 2) {
      setHint('idle')
      return
    }
    let live = true
    const timer = setTimeout(async () => {
      try {
        const page = await listBooks({
          query: { q: [typed, author.trim()].filter(Boolean).join(' '), limit: 5 },
        })
        if (!live) return
        const exact = page.items.some(
          (b) =>
            b.title.trim() === typed &&
            (!author.trim() || b.author.trim() === author.trim()),
        )
        setHint(exact ? 'exact' : page.total > 0 ? 'similar' : 'none')
      } catch {
        if (live) setHint('idle') // a failed hint must never block the form
      }
    }, 250)
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [title, author])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || saving) return
    setSaving(true)
    setError(null)
    try {
      onCreated(await onCreate({ title: title.trim(), author: author.trim() }))
    } catch (err) {
      setError(isConflict(err) ? t.conflict_add : String(err))
    } finally {
      setSaving(false)
    }
  }

  const hintClass = { exact: 'ok', similar: 'warn', none: 'none', idle: '' }[hint]
  const hintText = { exact: t.dup_exact, similar: t.dup_similar, none: t.dup_none, idle: '' }[hint]

  return (
    <div
      className="modal on"
      role="dialog"
      aria-modal="true"
      aria-label={t.add_title}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <form
        className="modalbox"
        onSubmit={submit}
        onKeyDown={(e) => e.key === 'Escape' && onClose()}
      >
        <h2>{t.add_title}</h2>

        <label className="field">
          <span>{t.title_label}</span>
          <input
            ref={first}
            className="rtl-safe"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
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

        {hint !== 'idle' && <p className={`hint ${hintClass}`}>{hintText}</p>}
        {error && <p className="hint warn" role="alert">{error}</p>}

        <div className="modalfoot">
          <button type="button" className="btn ghost" onClick={onClose}>
            {t.cancel}
          </button>
          <button
            type="submit"
            className="btn primary"
            disabled={saving || !title.trim()}
          >
            {t.add_save}
          </button>
        </div>
      </form>
    </div>
  )
}
