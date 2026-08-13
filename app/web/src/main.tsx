import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { AuthProvider } from './lib/auth'
import { BooksProvider } from './lib/books'
import { I18nProvider } from './lib/i18n'
import { LibraryProvider, LibraryScope } from './lib/library'
import './styles/tokens.css'
// After the tokens (it reads them through the --ui-* bridge), before this
// app's own sheets (so a rule this app owns can still win).
import '@booksnap/ui/styles/ui.css'
import './styles/base.css'
import './styles/books.css'
import './styles/capture.css'
import './styles/shelf.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root missing from index.html')

// `LibraryScope` is what discards every screen's state when the library
// changes (P3.1) — see its own ⚠. `AuthProvider` sits between i18n and the
// library: the login screen needs the language, and signing in remounts
// everything below (P4.1b). The test harness composes the SAME providers in
// the same order, so both remount rules have one definition.
createRoot(root).render(
  <StrictMode>
    <I18nProvider>
      <AuthProvider>
        <LibraryProvider>
          <LibraryScope>
            <BooksProvider>
              <App />
            </BooksProvider>
          </LibraryScope>
        </LibraryProvider>
      </AuthProvider>
    </I18nProvider>
  </StrictMode>,
)
