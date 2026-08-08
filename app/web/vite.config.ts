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
  },
})
