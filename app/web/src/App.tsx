/**
 * The shell: app bar, route, and the drawer that overlays whatever is behind.
 *
 * The drawer is mounted HERE rather than inside the Books tab so it survives
 * a tab change later — and so there is exactly one of it. Two drawer mounts
 * would be two focus traps fighting over the same page.
 */
import { useCallback, useState } from 'react'
import { BookDrawer } from './book/BookDrawer'
import { BookPage } from './book/BookPage'
import { BooksTab } from './books/BooksTab'
import { CaptureTab } from './capture/CaptureTab'
import { ShelfPage } from './shelf/ShelfPage'
import { useAuth } from './lib/auth'
import { useBooks } from './lib/books'
import { useI18n } from './lib/i18n'
import { LibrarySwitcher } from './lib/LibrarySwitcher'
import { bookHash, CAPTURE_HASH, LIBRARY_HASH, useRoute } from './lib/route'

export function App() {
  const { t, lang, toggleLang } = useI18n()
  const { signOutNow } = useAuth()
  const books = useBooks()
  const { route, navigate, back } = useRoute()
  const [drawerId, setDrawerId] = useState<string | null>(null)

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
        {/* P3.1 replaces P1.0's plain label: §4.1 makes Library the tenancy
            boundary and an account may belong to several, so the app bar has
            to let you change which one you are looking at, not just name it.
            `meta` still loads (it is how the client learns the server is
            there); its library is the RESOLVED one, which is what the
            switcher's own list is checked against server-side. */}
        <LibrarySwitcher />
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
        {/* P4.1b: its own accessible name (the collision rule) and no
            confirmation — sign-out is a state to arrive at, and the login
            screen it lands on is one click from returning. */}
        <button
          type="button"
          className="langswitch"
          onClick={signOutNow}
          aria-label={t.sign_out}
        >
          {t.sign_out}
        </button>
      </header>

      <main className="page">
        {route.name === 'book' ? (
          <BookPage bookId={route.id} onBack={back} onAuthor={filterByAuthor} />
        ) : route.name === 'capture' ? (
          <CaptureTab />
        ) : route.name === 'shelf' ? (
          <ShelfPage shelfId={route.id} onBack={back} onOpen={setDrawerId} />
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
