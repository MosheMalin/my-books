/**
 * The admin console's typed API client.
 *
 * ⚠⚠ **The library reference is a per-call argument here, and there is no
 * setter.** `app/web/src/api/client.ts` keeps the selection in a module global
 * and argues for it well — one module instance is one person's tab, so the
 * selection is exactly as global as the browser window. *That argument does
 * not survive in an admin console.* Every screen here is cross-library by
 * nature: the dashboard fans out over every library at once, and the books
 * screen merges several. A global "current library" would be a variable that
 * is wrong in the middle of every render, and the bug it caused would be one
 * library's rows shown under another's name.
 *
 * So `libraryId` travels explicitly, and the two transports the server
 * supports are used for exactly what each is for (`app/api/deps.py`):
 *
 *   - `X-Booksnap-Library` for anything this module `fetch`es;
 *   - `?library=` for URLs the BROWSER fetches for itself — a download
 *     `<a href>`, an `<img src>` — which cannot carry a custom header. That
 *     asymmetry is not a nicety: it shipped broken in the product for an
 *     afternoon and made every photo in a second library render empty.
 *
 * Response types all come from the generated contract (`./schema`). Nothing
 * here hand-writes a DTO shape.
 */
import type {
  BookDTO,
  BookPageDTO,
  BookPatch,
  BookSort,
  DuplicateQuestionDTO,
  LibraryDTO,
  MetaResponse,
  ReadSummaryDTO,
  ShelfDTO,
  ShelfOverviewDTO,
  Status,
} from './schema'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface CallOptions {
  /** Which library to resolve against. Omitted only for the account-scoped
   *  routes (`/meta`, `/libraries`), which resolve no library at all. */
  libraryId?: string | undefined
  signal?: AbortSignal | undefined
  fetchImpl?: typeof fetch | undefined
}

type Query = Record<string, string | number | boolean | undefined>

function headersFor(opts: CallOptions, extra?: Record<string, string>): HeadersInit {
  const headers: Record<string, string> = { Accept: 'application/json', ...extra }
  if (opts.libraryId) headers['X-Booksnap-Library'] = opts.libraryId
  return headers
}

function withQuery(path: string, query?: Query): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== '') params.set(k, String(v))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

async function request<T>(
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  opts: CallOptions,
  body?: unknown,
  query?: Query,
): Promise<T> {
  const doFetch = opts.fetchImpl ?? globalThis.fetch
  const url = withQuery(path, query)
  const res = await doFetch(url, {
    method,
    headers: headersFor(
      opts,
      body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    ),
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...(opts.signal ? { signal: opts.signal } : {}),
  })
  if (!res.ok) {
    // The server's own `detail` is the useful half — a 409 from
    // `PATCH /books/{id}` names the book you already own, and an admin
    // needs to read that, not "409".
    let detail = `${method} ${url} failed: ${res.status}`
    try {
      const parsed = (await res.json()) as { detail?: unknown }
      if (typeof parsed?.detail === 'string') detail = parsed.detail
    } catch {
      /* a 204, or an HTML error page — the status carries the meaning */
    }
    throw new ApiError(res.status, path, detail)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

/**
 * A URL the browser fetches itself. The library goes in the query string
 * because a header is not available to an `<a href>` — see the module note.
 */
export function browserUrl(
  path: string,
  libraryId: string | undefined,
  params: Record<string, string> = {},
): string {
  const qs = new URLSearchParams(params)
  if (libraryId) qs.set('library', libraryId)
  const s = qs.toString()
  return s ? `${path}?${s}` : path
}

// --- account scope: who is asking, and what they may name --------------------

export const getMeta = (opts: CallOptions = {}): Promise<MetaResponse> =>
  request('GET', '/api/v1/meta', opts)

/** ⚠ The libraries THIS ACCOUNT belongs to — the only listing the server
 *  offers. There is no cross-account view, which is why the console's numbers
 *  are scoped to one administrator (see `AccessPage`). */
export const listLibraries = (opts: CallOptions = {}): Promise<LibraryDTO[]> =>
  request('GET', '/api/v1/libraries', opts)

export const createLibrary = (label: string, opts: CallOptions = {}) =>
  request<LibraryDTO>('POST', '/api/v1/libraries', opts, { label })

export const renameLibrary = (id: string, label: string, opts: CallOptions = {}) =>
  request<LibraryDTO>(
    'PATCH', `/api/v1/libraries/${encodeURIComponent(id)}`, opts, { label },
  )

// --- books ------------------------------------------------------------------

export interface BookQuery {
  q?: string | undefined
  status?: Status | undefined
  authorKey?: string | undefined
  lentOut?: boolean | undefined
  duplicates?: boolean | undefined
  sort?: BookSort | undefined
  ascending?: boolean | undefined
  limit?: number | undefined
  offset?: number | undefined
}

const bookParams = (q: BookQuery): Query => ({
  q: q.q,
  status: q.status,
  author_key: q.authorKey,
  lent_out: q.lentOut,
  duplicates: q.duplicates || undefined,
  sort: q.sort,
  ascending: q.ascending,
  limit: q.limit,
  offset: q.offset,
})

export const listBooks = (
  libraryId: string, query: BookQuery = {}, opts: CallOptions = {},
): Promise<BookPageDTO> =>
  request('GET', '/api/v1/books', { ...opts, libraryId }, undefined,
          bookParams(query))

/**
 * How many books match — one row fetched, `total` read off it.
 *
 * `BookPageDTO` carries the total beside the page precisely so a client can
 * render "1-20 of 251" without a second round trip, which makes `limit=1` a
 * COUNT query costing one row. That is what makes the dashboard affordable:
 * a library's whole status breakdown is four of these.
 */
export async function countBooks(
  libraryId: string, query: BookQuery = {}, opts: CallOptions = {},
): Promise<number> {
  const page = await listBooks(libraryId, { ...query, limit: 1, offset: 0 }, opts)
  return page.total
}

export const getBook = (
  libraryId: string, id: string, opts: CallOptions = {},
): Promise<BookDTO> =>
  request('GET', `/api/v1/books/${encodeURIComponent(id)}`, { ...opts, libraryId })

export const patchBook = (
  libraryId: string, id: string, payload: BookPatch, opts: CallOptions = {},
): Promise<BookDTO> =>
  request('PATCH', `/api/v1/books/${encodeURIComponent(id)}`,
          { ...opts, libraryId }, payload)

/** Raise an `auto` record to `approved` (§5.1). Idempotent, never a
 *  demotion — a `manual` book comes back unchanged. */
export const approveBook = (
  libraryId: string, id: string, opts: CallOptions = {},
): Promise<BookDTO> =>
  request('POST', `/api/v1/books/${encodeURIComponent(id)}/approve`,
          { ...opts, libraryId }, undefined)

/** ⚠ Removes every copy AND records a standing rejection at each
 *  (shelf, depth) the book stood at, so the next read of that shelf does not
 *  put it straight back (§5.6). Not a soft hide. */
export const deleteBook = (
  libraryId: string, id: string, opts: CallOptions = {},
): Promise<void> =>
  request('DELETE', `/api/v1/books/${encodeURIComponent(id)}`,
          { ...opts, libraryId })

export const exportUrl = (libraryId: string, format: 'csv' | 'json'): string =>
  browserUrl('/api/v1/books/export', libraryId, { format })

// --- shelves, reads, open questions ------------------------------------------

export const listShelves = (
  libraryId: string, includeVirtual = false, opts: CallOptions = {},
): Promise<ShelfDTO[]> =>
  request('GET', '/api/v1/shelves', { ...opts, libraryId }, undefined,
          { include_virtual: includeVirtual || undefined })

export const getShelfOverview = (
  libraryId: string, shelfId: string, opts: CallOptions = {},
): Promise<ShelfOverviewDTO> =>
  request('GET', `/api/v1/shelves/${encodeURIComponent(shelfId)}/overview`,
          { ...opts, libraryId })

export const listShelfReads = (
  libraryId: string, shelfId: string, opts: CallOptions = {},
): Promise<ReadSummaryDTO[]> =>
  request('GET', `/api/v1/shelves/${encodeURIComponent(shelfId)}/reads`,
          { ...opts, libraryId })

/** The open §5.4 questions — "is this the copy I already have?" — for one
 *  library. Whole-library by design server-side, not nested under a shelf. */
export const listDuplicates = (
  libraryId: string, opts: CallOptions = {},
): Promise<DuplicateQuestionDTO[]> =>
  request('GET', '/api/v1/duplicates', { ...opts, libraryId })
