/**
 * The console's chrome: a title, four tabs, a language toggle, and whichever
 * screen the hash names.
 *
 * ⚠ Nothing here holds a "current library". The product client remounts its
 * whole tree on a library switch precisely because every screen below it
 * holds state about ONE library; this app inverts that — its screens are
 * cross-library by nature, and the one screen that narrows carries the id in
 * its own route. So there is no scope to key on and nothing to remount.
 */
import { AccessPage } from './access/AccessPage'
import { AccountsPage } from './accounts/AccountsPage'
import { BooksPage } from './books/BooksPage'
import { Dashboard } from './dash/Dashboard'
import { ImagesPage } from './images/ImagesPage'
import { useI18n } from './lib/i18n'
import { href, useRoute, type Route } from './lib/route'
import { StaffTokenForm } from './lib/StaffToken'
import { useSystem } from './lib/system'

function Tabs({ route }: { route: Route }) {
  const { t } = useI18n()
  const tabs: Array<{ to: Route; label: string; active: boolean }> = [
    { to: { name: 'dashboard' }, label: t.nav_dashboard, active: route.name === 'dashboard' },
    {
      to: { name: 'accounts' },
      label: t.nav_accounts,
      // The drawer is a child of the list, so the tab stays lit while one
      // account is open — otherwise a deep link lands on a console that looks
      // like it has no section at all.
      active: route.name === 'accounts' || route.name === 'account',
    },
    { to: { name: 'books', libraryId: undefined }, label: t.nav_books, active: route.name === 'books' },
    { to: { name: 'images', libraryId: undefined }, label: t.nav_images, active: route.name === 'images' },
    { to: { name: 'access' }, label: t.nav_access, active: route.name === 'access' },
  ]
  return (
    <nav className="tabs" aria-label={t.console}>
      {tabs.map((tab) => (
        <a key={tab.label} href={href(tab.to)} className={tab.active ? 'on' : ''}
           aria-current={tab.active ? 'page' : undefined}>
          {tab.label}
        </a>
      ))}
    </nav>
  )
}

function Screen({ route }: { route: Route }) {
  switch (route.name) {
    case 'dashboard': return <Dashboard />
    case 'accounts': return <AccountsPage openId={undefined} />
    case 'account': return <AccountsPage openId={route.id} />
    case 'books': return <BooksPage initialLibraryId={route.libraryId} />
    case 'images': return <ImagesPage initialLibraryId={route.libraryId} />
    case 'access': return <AccessPage />
  }
}

export function App() {
  const { t, toggleLang } = useI18n()
  const route = useRoute()
  const { needsToken, reload } = useSystem()

  // ⚠ A refused token blocks every screen, so the form replaces the app rather
  // than sitting on one tab. Anything else would show four screens' worth of
  // empty tables and let the operator conclude the system is empty.
  if (needsToken) {
    return (
      <div className="app">
        <header className="appbar">
          <div className="brand">
            <span>{t.app}</span>
            <span className="tag">{t.console}</span>
          </div>
        </header>
        <main><StaffTokenForm onSaved={reload} /></main>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="appbar">
        <div className="brand">
          <span>{t.app}</span>
          <span className="tag">{t.console}</span>
        </div>
        <Tabs route={route} />
        <button type="button" className="btn small" onClick={toggleLang}>
          {t.lang_toggle}
        </button>
      </header>
      <main>
        <Screen route={route} />
      </main>
    </div>
  )
}
