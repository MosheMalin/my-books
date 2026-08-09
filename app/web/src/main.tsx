import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { BooksProvider } from './lib/books'
import { I18nProvider } from './lib/i18n'
import { LibraryProvider, LibraryScope } from './lib/library'
import './styles/tokens.css'
import './styles/base.css'
import './styles/books.css'
import './styles/capture.css'
import './styles/shelf.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root missing from index.html')

// `LibraryScope` is what discards every screen's state when the library
// changes (P3.1) — see its own ⚠. The test harness composes the SAME three
// providers in the same order, so the switching rule has one definition.
createRoot(root).render(
  <StrictMode>
    <I18nProvider>
      <LibraryProvider>
        <LibraryScope>
          <BooksProvider>
            <App />
          </BooksProvider>
        </LibraryScope>
      </LibraryProvider>
    </I18nProvider>
  </StrictMode>,
)
