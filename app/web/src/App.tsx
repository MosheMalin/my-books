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
import { FirstLibrary } from './lib/FirstLibrary'
import { InviteGate } from './lib/InviteGate'
import { MembersPanel } from './lib/MembersPanel'
import { useI18n } from './lib/i18n'
import { useLibrary } from './lib/library'
import { LibrarySwitcher } from './lib/LibrarySwitcher'
import { bookHash, CAPTURE_HASH, LIBRARY_HASH, useRoute } from './lib/route'

export function App() {
  const { t, lang, toggleLang } = useI18n()
  const { signOutNow } = useAuth()
  const { libraries, loading, failed, current } = useLibrary()
  const books = useBooks()
  const { route, navigate, back } = useRoute()
  const [drawerId, setDrawerId] = useState<string | null>(null)
  const [membersOpen, setMembersOpen] = useState(false)
  const [acctOpen, setAcctOpen] = useState(false)

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
  // P4.1c: no library yet — the tabs' screens can only 404, so the nav is
  // ABSENT during onboarding, not disabled (the house rule).
  const onboarding = !loading && !failed && libraries.length === 0

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
        {!onboarding && (
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
        )}
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
        {/* ONE account menu, not a row of rare actions: two bare
            buttons pushed the bar 77px past an iPhone width (UX review,
            MAJOR 6). Members is admins-only inside it (the server
            enforces; the client does not dangle a 403 door). Sign-out has
            no confirm — nothing is lost server-side, and behind a menu an
            accidental press takes two deliberate taps — but returning
            DOES cost a fresh link today, which is why it hides here
            rather than sitting a thumb-width from the language toggle. */}
        <div className="acctmenu">
          <button
            type="button"
            className="langswitch"
            aria-haspopup="menu"
            aria-expanded={acctOpen}
            aria-label={t.account_menu}
            onClick={() => setAcctOpen((v) => !v)}
          >
            {t.account_menu}
          </button>
          {acctOpen && (
            <div className="acctmenu-list" role="menu">
              {current?.role === 'admin' && (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setAcctOpen(false)
                    setMembersOpen(true)
                  }}
                >
                  {t.members_open}
                </button>
              )}
              <button type="button" role="menuitem" onClick={signOutNow}>
                {t.sign_out}
              </button>
            </div>
          )}
        </div>
      </header>

      {/* P4.1c: a signed-in user with NO library names their first one
          instead of seeing tabs that can only 404. `failed` stays with the
          tabs — an unreachable list is an error state, not an invitation
          to create a duplicate library. */}
      {onboarding ? (
        <FirstLibrary />
      ) : (
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
      )}

      <InviteGate />
      {membersOpen && <MembersPanel onClose={() => setMembersOpen(false)} />}
      <BookDrawer
        bookId={route.name === 'book' ? null : drawerId}
        onClose={() => setDrawerId(null)}
        onPromote={promote}
        onAuthor={filterByAuthor}
      />
    </>
  )
}
