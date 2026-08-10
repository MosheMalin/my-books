import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
  // ⚠ jsdom keeps `localStorage` across tests in a file, and the language
  // choice persists DELIBERATELY — so without this every test after one that
  // switches to English starts in English and looks for the wrong strings.
  // The product's ring records the same trap.
  localStorage.clear()
  // The hash is global too: a test that navigated leaves the next one on
  // whatever screen it ended on.
  window.location.hash = ''
})
