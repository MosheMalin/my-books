/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/** `@booksnap/ui` is consumed as SOURCE, from the sibling directory — see
 *  `app/ui/README.md` for why there is no build step in between. */
const UI = fileURLToPath(new URL('../ui/src', import.meta.url))

/**
 * Dev: Vite serves the client and proxies /api to the product server.
 * Prod: `npm run build` emits dist/, which FastAPI mounts (see app/main.py).
 *
 * Port 8757 is the product API, one above the tuning server's 8756 — both run
 * side by side through pillars 1-2 (IMPLEMENTATION_PLAN, Risk 1).
 *
 * No CDN: everything is bundled locally, consistent with the project's
 * offline/credential posture (D3).
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [{ find: /^@booksnap\/ui(\/.*)?$/, replacement: `${UI}$1` }],
    // ⚠ NOT optional, and the list is longer than it looks like it should be.
    //
    // Without it Vite resolves a bare import from app/ui's own node_modules
    // for shared files and from this app's for app files. For `react` that is
    // the familiar two-copies bug: hooks break, with an error pointing nowhere
    // near the cause.
    //
    // ⚠⚠ The TESTING libraries need it for a subtler reason, found by watching
    // one test fail after `test/user.ts` moved into the shared package.
    // `@testing-library/dom` keeps its config in MODULE state, and
    // `@testing-library/react` writes React's `act` into it on import. A
    // second copy has its own, unconfigured config — so `userEvent` built from
    // that copy fires events OUTSIDE `act`, React never flushes the resulting
    // effects, and the symptom is a component that simply has not rendered
    // its data yet. It reads as a timing flake, not as a resolution problem.
    dedupe: [
      'react',
      'react-dom',
      '@testing-library/dom',
      '@testing-library/react',
      '@testing-library/user-event',
    ],
  },
  server: {
    port: 5173,
    // The dev server must be allowed to read the sibling package it aliases.
    fs: { allow: ['..'] },
    // Listen on the LAN, not just loopback. Capture is a PHONE flow — the
    // owner photographs a shelf and uploads from the camera roll — so a dev
    // server only its own machine can reach cannot be used for the one thing
    // this tab is for. The product API binds 0.0.0.0 for the same reason
    // (.claude/launch.json), as the tuning server already did.
    host: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8757', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // ⚠ `isolate: false` is a MEASURED necessity here, not a shortcut.
    // `require('jsdom')` costs **3.5 seconds** on this machine — 650 small
    // files through a Windows filesystem, of which only 0.75s is actually
    // reading them — and vitest builds the environment once per test FILE
    // while isolated, so 18 of the suite's 28 seconds were loading the same
    // library five times. Without isolation a worker loads it once and reuses
    // it for every file it runs. (Measured against happy-dom too, in case the
    // engine was the problem: 3120 files, **22 seconds** to require. It is
    // not the engine.)
    //
    // What that costs, and how it is paid for: files sharing a worker now also
    // share the module registry and the DOM, so anything module-level survives
    // from one file into the next. `src/test/setup.ts` resets the two things
    // that are module-level on purpose — the client's selected library and
    // localStorage — in a global `afterEach`, so the sharing is declared and
    // enforced rather than hoped for. Add to that list, do not work around it.
    isolate: false,
    // ⚠ Two, on a four-core box, and measured rather than assumed. Each extra
    // worker is another 3.5s `require('jsdom')`, so the usual "one worker per
    // core" makes this suite SLOWER: 4 workers 28.4s, 1 worker 31.7s, 2
    // workers 25.1s. Re-measure if the file count changes much.
    maxWorkers: 2,
  },
})
