/**
 * The shell: app bar, route, and the drawer that overlays whatever is behind.
 *
 * The drawer is mounted HERE rather than inside the Books tab so it survives
 * a tab change later — and so there is exactly one of it. Two drawer mounts
 * would be two focus traps fighting over the same page.
 */
import { useCallback, useEffect, useState } from 'react'
import { BookDrawer } from './book/BookDrawer'
import { BookPage } from './book/BookPage'
import { BooksTab } from './books/BooksTab'
import { CaptureTab } from './capture/CaptureTab'
import { getMeta, type Meta } from './api/client'
import { useBooks } from './lib/books'
import { useI18n } from './lib/i18n'
import { bookHash, CAPTURE_HASH, LIBRARY_HASH, useRoute } from './lib/route'

export function App() {
  const { t, lang, toggleLang } = useI18n()
  const books = useBooks()
  const { route, navigate, back } = useRoute()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [drawerId, setDrawerId] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    getMeta()
      .then((m) => live && setMeta(m))
      // The library name is chrome, not content: failing to load it must not
      // take the books down with it.
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [])

  // Promoting the drawer to the full page closes the drawer — otherwise the
  // same surface renders twice, and the focus trap stays over a page the user
  // has navigated to.
  const promote = useCallback(
    (id: string) => {
      setDrawerId(null)
      navigate(bookHash(id))
    },
    [navigate],
  )

  const filterByAuthor = useCallback(
    (authorKey: string) => {
      books.setQuery({ authorKey })
      navigate(LIBRARY_HASH)
    },
    [books, navigate],
  )

  // Two tabs exist today (Books, Capture) — Map and Settings are later
  // pillars (UI_PLAN §1) and are ABSENT from the nav rather than disabled
  // links to nothing.
  const onBooks = route.name === 'library' || route.name === 'book'
  const onCapture = route.name === 'capture'

  return (
    <>
      <header className="appbar">
        <span className="brand">{t.app}</span>
        <span className="rtl-safe muted">{meta?.library.label ?? ''}</span>
        <nav className="nav" aria-label={t.app}>
          <button
            type="button"
            className={onBooks ? 'on' : ''}
            aria-pressed={onBooks}
            onClick={() => navigate(LIBRARY_HASH)}
          >
            {t.books}
          </button>
          <button
            type="button"
            className={onCapture ? 'on' : ''}
            aria-pressed={onCapture}
            onClick={() => navigate(CAPTURE_HASH)}
          >
            {t.capture_tab}
          </button>
        </nav>
        <span className="spacer" />
        <button
          type="button"
          className="langswitch"
          onClick={toggleLang}
          // The English mode exists to prove the layout mirrors and that
          // mixed-script alignment holds both ways (UI_PLAN §7.1/§7.2).
          aria-label={lang === 'he' ? 'Switch to English' : 'עברו לעברית'}
        >
          {t.lang}
        </button>
      </header>

      <main className="page">
        {route.name === 'book' ? (
          <BookPage bookId={route.id} onBack={back} onAuthor={filterByAuthor} />
        ) : route.name === 'capture' ? (
          <CaptureTab />
        ) : (
          <BooksTab onOpen={setDrawerId} />
        )}
      </main>

      <BookDrawer
        bookId={route.name === 'book' ? null : drawerId}
        onClose={() => setDrawerId(null)}
        onPromote={promote}
        onAuthor={filterByAuthor}
      />
    </>
  )
}
