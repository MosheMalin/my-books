/**
 * A fake server, and the provider stack the real entry point uses.
 *
 * ⚠ The providers are composed here in the SAME order as `src/main.tsx`, and
 * that is the point: composing them differently in the ring means the ring
 * cannot catch a regression in the composition itself.
 *
 * The harness answers requests with the exact payloads a route would — it
 * does NOT reimplement anything the server decides (search ranking,
 * reconciliation, the §5.1 ladder). Same standard as the product's own
 * capture/shelf harnesses and the Python API ring's `StubReader`: a fake that
 * re-derives the rules under test is a second implementation that can agree
 * with the code while both are wrong.
 */
import { render, type RenderResult } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { vi } from 'vitest'

import { I18nProvider } from '../lib/i18n'
import { SystemProvider } from '../lib/system'
import type { BookDTO, LibraryDTO } from '../api/schema'
import type {
  StaffBook, StaffImage, StaffLibrary, StaffOverview, StaffUser, StaffWork,
} from '../api/staff'

export interface Recorded {
  url: string
  method: string
  /** The product API's tenant header, when the request carried one. */
  library: string | undefined
  /** The staff service's shared secret, when the request carried one. */
  staffToken: string | undefined
  body: unknown
}

export interface FakeServer {
  /** Every request the app made, in order — including the tenant header,
   *  which is the thing most worth asserting in a cross-library console. */
  calls: Recorded[]
  /** Route handlers, keyed by `METHOD path` prefix match. Later entries win,
   *  so a test can override one route of the default set. */
  route: (match: string, handler: (req: Recorded) => unknown) => void
}

export function makeBook(over: Partial<BookDTO> = {}): BookDTO {
  return {
    id: 'b1',
    title: 'ספר',
    author: 'מחבר',
    author_key: 'מחבר',
    status: 'auto',
    copy_count: 1,
    added_at: '2026-01-02T00:00:00Z',
    shared_book_id: null,
    work: { series: null, series_index: null, year: null, language: null },
    copies: [{
      id: 'c1', status: 'auto', label: '', shelf_id: null, depth: null,
      tags: [], condition: '', acquired_at: null, lending: null,
      last_seen: null, sighting_count: 0, not_seen_streak: null,
    }],
    ...over,
  } as BookDTO
}

export function makeLibrary(over: Partial<LibraryDTO> = {}): LibraryDTO {
  return {
    id: 'lib-1', account_id: 'acc-1', label: 'הספרייה', role: 'admin',
    created_at: '2026-01-01T00:00:00Z',
    ...over,
  }
}

// --- the staff service ------------------------------------------------------
//
// Separate factories from the product ones above, deliberately: the two
// services return DIFFERENT shapes for what sounds like the same noun, and a
// shared factory would hide exactly the mismatch these tests exist to catch.

export function makeStaffLibrary(over: Partial<StaffLibrary> = {}): StaffLibrary {
  return {
    id: 'lib-1', account_id: 'acc-1', label: 'הבית',
    created_at: '2026-01-01T00:00:00Z',
    members: 1, admins: 1, books: 0, copies: 0, auto: 0, approved: 0,
    manual: 0, shelves: 0, captures: 0, reads: 0, duplicates: 0,
    lent_out: 0, last_activity: null, image_files: 0, image_bytes: 0,
    ...over,
  }
}

export function makeStaffBook(over: Partial<StaffBook> = {}): StaffBook {
  return {
    id: 'b1', library_id: 'lib-1', title: 'ספר', author: 'מחבר',
    status: 'auto', copy_count: 1, shelf_count: 0,
    added_at: '2026-01-02T00:00:00Z',
    ...over,
  }
}

export function makeStaffWork(over: Partial<StaffWork> = {}): StaffWork {
  return {
    key: 'ספר|מחבר', title: 'ספר', author: 'מחבר', status: 'auto',
    mixed: false, libraries: 1, copies: 1,
    first_added: '2026-01-02T00:00:00Z', last_added: '2026-01-02T00:00:00Z',
    ...over,
  }
}

export function makeStaffImage(over: Partial<StaffImage> = {}): StaffImage {
  return {
    id: 'cap-1', library_id: 'lib-1', image_key: 'a'.repeat(64) + '.jpg',
    captured_at: '2026-01-03T00:00:00Z', shelf_id: 'sh-1', shelf_label: 'מדף',
    depth: 1, order: 0, present: true, bytes: 120_000, width: 1200,
    height: 900, content_type: 'image/jpeg', filename: 'shelf.jpg',
    reads: 1, findings: 3, auto: 2, review: 1, unmatched: 0,
    last_read: '2026-01-04T00:00:00Z',
    ...over,
  }
}

export function makeOverview(over: Partial<StaffOverview> = {}): StaffOverview {
  return {
    accounts: 1, accounts_without_admin: 0,
    users: 1, libraries: 1, memberships: 1, books: 0, copies: 0,
    shelves: 0, captures: 0, reads: 0, duplicates: 0, lent_out: 0,
    auto: 0, approved: 0, manual: 0, image_files: 0, image_bytes: 0,
    blobs_visible: true,
    authenticated: true, orphan_libraries: [],
    ...over,
  }
}

export function makeUser(over: Partial<StaffUser> = {}): StaffUser {
  return {
    id: 'usr-1', display_name: 'משה', email: null,
    created_at: '2026-01-01T00:00:00Z', memberships: [],
    ...over,
  }
}

/**
 * Install a fetch fake. Returns the recorder plus a `route` hook.
 *
 * Unmatched requests REJECT rather than returning an empty body: a screen
 * quietly rendering zero rows because nobody stubbed its endpoint is a green
 * test that proves nothing.
 */
export function fakeServer(defaults: Record<string, (req: Recorded) => unknown> = {}): FakeServer {
  const handlers = new Map<string, (req: Recorded) => unknown>(Object.entries(defaults))
  const calls: Recorded[] = []

  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const headers = new Headers(init?.headers ?? {})
    const req: Recorded = {
      url,
      method,
      library: headers.get('X-Booksnap-Library') ?? undefined,
      staffToken: headers.get('X-Booksnap-Staff') ?? undefined,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    }
    calls.push(req)

    // Longest match wins, so `GET /api/v1/books/authors` can be routed
    // separately from `GET /api/v1/books`.
    let best: ((r: Recorded) => unknown) | undefined
    let bestLen = -1
    for (const [key, handler] of handlers) {
      const [m = 'GET', path = ''] = key.split(' ')
      if (m === method && url.startsWith(path) && path.length > bestLen) {
        best = handler
        bestLen = path.length
      }
    }
    if (!best) {
      return new Response(JSON.stringify({ detail: `unrouted ${method} ${url}` }),
                          { status: 599 })
    }
    // ⚠ AWAITED. Without it a handler cannot be slow, so no test can
    // exercise a screen mid-fetch — which is how the work panel's `key`
    // lost its gate — and an async handler was silently `JSON.stringify`ed
    // to `{}` rather than failing.
    const payload = await best(req)
    if (payload instanceof Response) return payload
    return new Response(JSON.stringify(payload ?? null),
                        { status: 200, headers: { 'Content-Type': 'application/json' } })
  })

  vi.stubGlobal('fetch', impl)
  return {
    calls,
    route: (match, handler) => { handlers.set(match, handler) },
  }
}

const wrapped = (ui: ReactNode) => (
  <I18nProvider>
    <SystemProvider>{ui}</SystemProvider>
  </I18nProvider>
)

/**
 * ⚠ `rerender` is OVERRIDDEN to re-wrap. Testing Library's own replaces the
 * whole tree with what it is handed, so a bare `rerender(<Screen …/>)` drops
 * the providers and the screen throws "useI18n outside <I18nProvider>" —
 * which reads as a bug in the screen rather than in the call.
 */
export function renderApp(ui: ReactElement): RenderResult {
  const result = render(wrapped(ui))
  return { ...result, rerender: (next: ReactNode) => result.rerender(wrapped(next)) }
}
