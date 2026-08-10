/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

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
  server: {
    port: 5173,
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
