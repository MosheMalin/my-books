import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { BooksProvider } from './lib/books'
import { I18nProvider } from './lib/i18n'
import './styles/tokens.css'
import './styles/base.css'
import './styles/books.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root missing from index.html')

createRoot(root).render(
  <StrictMode>
    <I18nProvider>
      <BooksProvider>
        <App />
      </BooksProvider>
    </I18nProvider>
  </StrictMode>,
)
