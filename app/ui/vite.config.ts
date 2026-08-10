/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * There is no `build` script here on purpose: this package is never bundled on
 * its own. Both clients alias `@booksnap/ui` straight at `src/`, so a shared
 * component is compiled by the app that uses it, with that app's tsconfig and
 * that app's React. A build step would buy a second artefact to keep in sync —
 * which is the failure mode this repo has already recorded twice (the stale
 * `:8757` bundle, the stale Vite module graph).
 *
 * This config exists for ONE thing: the package's own vitest ring.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // ⚠ Same measured reason as `app/web/vite.config.ts`: `require('jsdom')`
    // costs ~3.5s on this machine and vitest builds the environment once per
    // test FILE while isolated. One worker, no isolation — this ring is a
    // handful of small files, so a second worker would only pay the jsdom
    // toll twice. `src/test/setup.ts` resets what the sharing makes global.
    isolate: false,
    maxWorkers: 1,
  },
})
