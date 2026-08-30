/**
 * Test harness for the shelf-detail screen (P2.8) — same idiom as
 * `capture/captureHarness.ts`: a fake SERVER (mocks `fetch`), not a fake
 * store, so `useShelfDetail`'s own request wiring is what gets exercised.
 * Each test hands this fake the exact overview/books/history it wants —
 * the same "inject, don't reimplement the rule engine" idiom the Python API
 * ring uses with `StubReader`.
 */
import { vi } from 'vitest'
import type {
  Book,
  CaptureDTO,
  DepthStatusDTO,
  ReadSummaryDTO,
  Shelf,
} from '../api/client'

export interface FakeShelfServer {
  calls: string[]
  shelf: Shelf | null
  depths: DepthStatusDTO[]
  lastReadAt: string | null
  /** books keyed by depth */
  books: Record<number, Book[]>
  /** captures keyed by depth */
  captures: Record<number, CaptureDTO[]>
  /** read history keyed by depth */
  history: Record<number, ReadSummaryDTO[]>
  /**
   * Every write this screen made, in order, with its body (P6.7d).
   *
   * ⚠ The METHOD and the PATH, not just the path: `calls` above records the
   * url alone, so it cannot tell a GET of the read history from a POST that
   * STARTS one — which is the exact distinction the item turns on.
   */
  writes: { method: string; path: string; body: unknown }[]
  /** Refuse the next `POST /captures` with this status. */
  refuseCapture: number | null
}

export function fakeShelfServer(init: Partial<FakeShelfServer> = {}): FakeShelfServer {
  const server: FakeShelfServer = {
    calls: [],
    shelf: null,
    depths: [],
    lastReadAt: null,
    books: {},
    captures: {},
    history: {},
    writes: [],
    refuseCapture: null,
    ...init,
  }

  const respond = (body: unknown, status = 200) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status, headers: { 'Content-Type': 'application/json' },
    })

  vi.stubGlobal('fetch', async (input: RequestInfo | URL,
                                init?: RequestInit) => {
    const url = String(input)
    server.calls.push(url)
    const u = new URL(url, 'http://test')
    const parts = u.pathname.split('/').filter(Boolean) // ['api','v1','shelves',id,...]
    const depth = Number(u.searchParams.get('depth') ?? '1')
    const method = (init?.method ?? 'GET').toUpperCase()

    if (method !== 'GET') {
      // ⚠ A FormData body is recorded as its entries rather than stringified.
      // `JSON.stringify(new FormData())` is `{}`, which is also what a
      // multipart call sent through the JSON `send()` helper looks like on
      // the wire — so a fake that flattened both to `{}` could not tell the
      // bug from the fix. CLAUDE.md records that exact defect.
      const raw = init?.body
      const body = raw instanceof FormData
        ? Object.fromEntries([...raw.entries()].map(
            ([k, v]) => [k, v instanceof File ? `file:${v.name}` : v]))
        : typeof raw === 'string' ? JSON.parse(raw) : raw
      server.writes.push({ method, path: u.pathname, body })
    }

    // --- the two calls that file a photo (P6.7d) ---
    if (parts[2] === 'images' && method === 'POST') {
      return respond({ key: 'img-key', width: 10, height: 10, bytes: 3,
                       filename: 'x.jpg', content_type: 'image/jpeg' }, 201)
    }
    if (parts[2] === 'captures' && method === 'POST') {
      if (server.refuseCapture) {
        return respond({ detail: 'no' }, server.refuseCapture)
      }
      const sent = server.writes[server.writes.length - 1]!.body as
        { shelf_id: string; depth: number; image_id: string }
      const capture: CaptureDTO = {
        id: `cap-${server.writes.length}`, shelf_id: sent.shelf_id,
        depth: sent.depth, order: 0, image_id: sent.image_id,
        captured_at: null,
      }
      const at = server.captures[sent.depth] ?? []
      server.captures[sent.depth] = [...at, capture]
      return respond({ capture, shelf: server.shelf, shelf_created: false }, 201)
    }

    if (parts[2] !== 'shelves' || !parts[3]) {
      return respond({ detail: `unhandled ${u.pathname}` }, 404)
    }
    if (!server.shelf || server.shelf.id !== parts[3]) {
      return respond({ detail: 'no such shelf' }, 404)
    }

    if (parts[4] === 'overview') {
      return respond({
        shelf: server.shelf, depths: server.depths, last_read_at: server.lastReadAt,
      })
    }
    if (parts[4] === 'books') {
      return respond(server.books[depth] ?? [])
    }
    if (parts[4] === 'captures') {
      return respond(server.captures[depth] ?? [])
    }
    if (parts[4] === 'reads') {
      return respond(server.history[depth] ?? [])
    }
    if (parts[4] === 'depths') {
      server.shelf = { ...server.shelf, depth_count: server.shelf.depth_count + 1 }
      server.depths = [...server.depths,
        { depth: server.depths.length + 1, last_read_at: null, is_stale: false }]
      return respond(server.shelf)
    }
    return respond({ detail: `unhandled ${u.pathname}` }, 404)
  })

  return server
}

export function fakeShelf(over: Partial<Shelf> = {}): Shelf {
  return {
    id: 'sh1', label: 'סלון, כוננית 2', depth_count: 1, virtual: false,
    created_at: null, capture_count: 1, book_count: 0, ...over,
  }
}

export function fakeBook(over: Partial<Book> & { id: string; title: string }): Book {
  return {
    author: '', author_key: '', status: 'auto', copy_count: 1, added_at: null,
    shared_book_id: null, work: { rating: null, notes: '', read_status: null },
    copies: [{
      id: `${over.id}c1`, status: 'auto', label: '', shelf_id: 'sh1', depth: 1,
      tags: [], condition: '', acquired_at: null, lending: null, last_seen: null,
      sighting_count: 1, not_seen_streak: null,
    }],
    ...over,
  }
}
