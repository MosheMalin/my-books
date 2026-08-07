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
    ...init,
  }

  const respond = (body: unknown, status = 200) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status, headers: { 'Content-Type': 'application/json' },
    })

  vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
    const url = String(input)
    server.calls.push(url)
    const u = new URL(url, 'http://test')
    const parts = u.pathname.split('/').filter(Boolean) // ['api','v1','shelves',id,...]
    const depth = Number(u.searchParams.get('depth') ?? '1')

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
    created_at: null, capture_count: 1, ...over,
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
