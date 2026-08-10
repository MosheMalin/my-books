import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import { setCurrentLibrary } from '../api/client'

/**
 * One reset, for every test in every file.
 *
 * ⚠ This is what pays for `isolate: false` in `vite.config.ts` (see the note
 * there: loading jsdom once per test FILE was 18 of the suite's 28 seconds).
 * Without isolation, files that share a worker share the module registry and
 * the DOM, so anything module-level outlives the file that set it. Two things
 * here are module-level ON PURPOSE and would leak:
 *
 *   - `client.ts`'s selected library — deliberately global, because one module
 *     instance is one person's tab (its own docstring argues this at length).
 *     Left set, the next file's very first request goes out naming a library
 *     that file never chose, and the failure would look like a header bug;
 *   - `localStorage` — the language choice persists on purpose, so a file that
 *     switched to English would hand the next one an English UI and every
 *     Hebrew `getByRole` name would miss.
 *
 * Individual files still have their own `afterEach`; the duplication is
 * harmless and this one is the guarantee. Anything else that becomes
 * module-level state belongs in this list, not in a workaround.
 *
 * ⚠ Stated honestly: **no test fails today if the library reset is removed**
 * (checked, by removing it and running every file through one worker). It is
 * a guard, not a fix — the leak `isolate: false` makes possible, closed before
 * the first test that would depend on the initial state gets written. Do not
 * read the passing suite as evidence the line is unnecessary.
 */
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  setCurrentLibrary(undefined)
  globalThis.localStorage?.clear()
  globalThis.location.hash = ''
  document.documentElement.dir = 'rtl'
  document.documentElement.lang = 'he'
})

/**
 * jsdom has no IntersectionObserver, and the feed uses one for endless scroll.
 *
 * Deliberately a stub that never fires: paging behaviour is asserted through
 * the store (query changes reset the offset), not by faking a scroll. A stub
 * that DID fire would make every list test load every page, which is slower
 * and tests the observer rather than the code that uses it.
 */
class NoopIntersectionObserver implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly thresholds: readonly number[] = []
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}

globalThis.IntersectionObserver =
  NoopIntersectionObserver as unknown as typeof IntersectionObserver

/**
 * jsdom has no object URL machinery, and the Capture tab (P2.7) previews each
 * dropped file with `URL.createObjectURL` before it has finished uploading.
 * A no-op stub is enough — no test inspects the resulting string, only that
 * calling it (and its `revoke` counterpart, on unmount) does not throw.
 */
if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = () => 'blob:mock'
}
if (typeof URL.revokeObjectURL !== 'function') {
  URL.revokeObjectURL = () => undefined
}
