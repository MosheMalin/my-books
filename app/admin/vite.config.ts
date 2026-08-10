/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * The admin console's dev/preview server.
 *
 * Port 5174 — one above the product client's 5173, so both can run at once.
 * They talk to the SAME product API on :8757; the console is a second client,
 * not a second backend (see planning/ADMIN_CONSOLE_PLAN.md).
 *
 * ⚠ `host: true` binds 0.0.0.0, not loopback. The owner administers this from
 * a phone, same as the capture flow — a server only its own machine can reach
 * cannot do the thing it exists for. Note this is an UNAUTHENTICATED tool on
 * the LAN until pillar 4 lands login, exactly the deliberate single-household
 * trade `:8757` and `:5173` already make.
 *
 * `vite preview` inherits the same host/port, so the built bundle is reachable
 * from a phone too — which matters here because, unlike the product client,
 * nothing mounts this app's `dist/` behind FastAPI (that would mean editing
 * `app/main.py`, which this build may not touch).
 *
 * No CDN: everything is bundled locally, consistent with the project's
 * offline/credential posture (D3).
 */
/**
 * The console talks to TWO services, and the order of these keys matters:
 * Vite matches the longest prefix, so `/api/staff` reaches the staff service
 * and everything else falls through to the product API.
 *
 *   :8758  the SYSTEM-admin service — cross-tenant, read-only, its own
 *          credential (`app/staff_api/`). Everything the operator can SEE.
 *   :8757  the ordinary product API. Everything the operator can CHANGE,
 *          which is only ever inside libraries they are a member of.
 *
 * Proxying both through this origin is also what keeps the staff token out of
 * a cross-origin preflight, and means neither service needs CORS.
 */
const PROXY = {
  '/api/staff': { target: 'http://127.0.0.1:8758', changeOrigin: false },
  '/api': { target: 'http://127.0.0.1:8757', changeOrigin: false },
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    host: true,
    proxy: PROXY,
  },
  preview: {
    port: 5174,
    strictPort: true,
    host: true,
    proxy: PROXY,
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
