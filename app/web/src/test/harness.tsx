/**
 * Test harness: a fake API and a render helper.
 *
 * The fake stands in for the SERVER, not for the store — the store, the
 * request-id race guard and the paging arithmetic are exactly what the tests
 * need to exercise, so mocking `useBooks` would test nothing. It mocks
 * `globalThis.fetch` instead, which is the real seam.
 */
import { render, type RenderResult } from '@testing-library/react'
import { vi } from 'vitest'
import type { ReactElement } from 'react'
import { BooksProvider } from '../lib/books'
import { I18nProvider } from '../lib/i18n'

export interface FakeBook {
  id: string
  title: string
  author?: string
  status?: 'auto' | 'approved' | 'manual'
  added_at?: string | null
}

export type FakeBookRecord = ReturnType<typeof book>

export function book(b: FakeBook) {
  return {
    id: b.id,
    title: b.title,
    author: b.author ?? '',
    author_key: (b.author ?? '').trim(),
    status: b.status ?? 'auto',
    copy_count: 1,
    added_at: (b.added_at ?? '2026-01-01T00:00:00+00:00') as string | null,
    shared_book_id: null,
    work: { rating: null, notes: '', read_status: null },
    copies: [
      {
        id: `${b.id}c1`,
        status: b.status ?? 'auto',
        label: '',
        shelf_id: null,
        tags: [],
        condition: '',
        acquired_at: null,
        lending: null,
        last_seen: null,
        sighting_count: 0,
      },
    ],
  }
}

export interface FakeServer {
  books: FakeBookRecord[]
  /** Every request URL, in order — lets a test assert what was ASKED for. */
  calls: string[]
  /** Force the next mutating request to fail with this status. */
  failNextWith: number | null
  /** Hold the list responses this predicate selects until `release()`, so a
   *  test can make a STALE response land after a newer one. */
  holdWhen: ((url: string) => boolean) | null
  release: () => void
}

export function fakeServer(initial: FakeBookRecord[] = []): FakeServer {
  const pending: (() => void)[] = []
  const server: FakeServer = {
    books: [...initial],
    calls: [],
    failNextWith: null,
    holdWhen: null,
    release: () => {
      while (pending.length) pending.shift()?.()
    },
  }

  const respond = (body: unknown, status = 200) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })

  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    server.calls.push(url)
    const method = init?.method ?? 'GET'
    const u = new URL(url, 'http://test')

    if (u.pathname === '/api/v1/meta') {
      return respond({
        app: 'booksnap',
        version: '0.1.0',
        api_version: 'v1',
        library: { id: 'lib-test', label: 'ספרייה' },
      })
    }

    if (u.pathname === '/api/v1/books' && method === 'POST') {
      if (server.failNextWith) {
        const status = server.failNextWith
        server.failNextWith = null
        return respond({ detail: 'conflict' }, status)
      }
      const payload = JSON.parse(String(init?.body)) as {
        title: string
        author: string
      }
      const created = book({ id: `new-${server.books.length}`, ...payload,
                             status: 'manual' })
      server.books.push(created)
      return respond(created, 201)
    }

    if (u.pathname.startsWith('/api/v1/books/') && method === 'PATCH') {
      if (server.failNextWith) {
        const status = server.failNextWith
        server.failNextWith = null
        return respond({ detail: 'conflict' }, status)
      }
      const id = decodeURIComponent(u.pathname.split('/').pop() ?? '')
      const patch = JSON.parse(String(init?.body)) as Partial<FakeBook>
      const idx = server.books.findIndex((b) => b.id === id)
      const updated = {
        ...server.books[idx]!,
        ...patch,
        status: 'manual' as const,
      }
      server.books[idx] = updated
      return respond(updated)
    }

    if (u.pathname.startsWith('/api/v1/books/') && method === 'DELETE') {
      const id = decodeURIComponent(u.pathname.split('/').pop() ?? '')
      server.books = server.books.filter((b) => b.id !== id)
      return respond(null, 204)
    }

    if (u.pathname.startsWith('/api/v1/books/') && method === 'GET') {
      const id = decodeURIComponent(u.pathname.split('/').pop() ?? '')
      const found = server.books.find((b) => b.id === id)
      return found ? respond(found) : respond({ detail: 'no such book' }, 404)
    }

    // The list. Filters just enough to be honest about what was requested.
    const q = u.searchParams.get('q')?.trim() ?? ''
    const status = u.searchParams.get('status')
    const authorKey = u.searchParams.get('author_key')
    const limit = Number(u.searchParams.get('limit') ?? 50)
    const offset = Number(u.searchParams.get('offset') ?? 0)

    let items = server.books
    if (q) items = items.filter((b) => (b.title + ' ' + b.author).includes(q))
    if (status) items = items.filter((b) => b.status === status)
    if (authorKey) items = items.filter((b) => b.author_key === authorKey)

    const body = {
      items: items.slice(offset, offset + limit),
      total: items.length,
      offset,
      limit,
    }
    if (server.holdWhen?.(url)) {
      return new Promise<Response>((resolve) =>
        pending.push(() => resolve(respond(body))),
      )
    }
    return respond(body)
  })

  return server
}

export function renderApp(ui: ReactElement): RenderResult {
  return render(
    <I18nProvider>
      <BooksProvider>{ui}</BooksProvider>
    </I18nProvider>,
  )
}
