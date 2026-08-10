import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { I18nProvider } from './lib/i18n'
import { SystemProvider } from './lib/system'

import './styles/tokens.css'
import './styles/base.css'

/**
 * ⚠ The provider order here and in `src/test/harness.tsx` must MATCH. The
 * product records why: composing them differently in the test ring than in
 * the real entry point means the ring cannot catch a regression in the
 * composition itself. `SystemProvider` sits inside `I18nProvider` because
 * an error it renders needs the strings.
 */
const root = document.getElementById('root')
if (!root) throw new Error('#root missing from index.html')

createRoot(root).render(
  <StrictMode>
    <I18nProvider>
      <SystemProvider>
        <App />
      </SystemProvider>
    </I18nProvider>
  </StrictMode>,
)
