import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

/**
 * One reset, for every test in every file — what pays for `isolate: false` in
 * `vite.config.ts`. Files that share a worker share the module registry and
 * the DOM, so anything global outlives the file that set it:
 *
 *   - `localStorage` holds the language choice ON PURPOSE, so a file that
 *     switched to English would hand the next one an English UI and every
 *     Hebrew assertion would miss;
 *   - the hash is global too, and so are `dir`/`lang` on `<html>` — which the
 *     i18n provider writes and the bidi rules read.
 *
 * Both client rings record the same trap. Anything else that becomes global
 * belongs in this list rather than in a per-file workaround.
 */
afterEach(() => {
  cleanup()
  globalThis.localStorage?.clear()
  globalThis.location.hash = ''
  document.documentElement.dir = 'rtl'
  document.documentElement.lang = 'he'
})
