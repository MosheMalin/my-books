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
import { getMeta, type Meta } from './api/client'
import { useBooks } from './lib/books'
import { useI18n } from './lib/i18n'
import { bookHash, LIBRARY_HASH, useRoute } from './lib/route'

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

  return (
    <>
      <header className="appbar">
        <span className="brand">{t.app}</span>
        <span className="rtl-safe muted">{meta?.library.label ?? ''}</span>
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
