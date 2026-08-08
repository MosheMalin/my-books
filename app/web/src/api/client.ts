/**
 * The typed API client.
 *
 * Every response type comes from `schema.d.ts`, which is GENERATED from the
 * server's OpenAPI document and committed (D3). Nothing here hand-writes a
 * DTO shape — that is the whole mechanism: rename a field in
 * `app/api/dto.py`, regenerate, and this file stops compiling.
 *
 * `tools/api_contract.py --check` fails the commit if the generated types are
 * stale relative to the server.
 */
import type { components, paths } from './schema'

/** All paths are versioned server-side (H3); the client never builds a URL
 *  by hand, so it cannot accidentally call an unversioned endpoint. */
type ApiPath = keyof paths

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

/** Success body of a GET, straight out of the generated schema. */
export type GetResponse<P extends ApiPath> = paths[P] extends {
  get: { responses: { 200: { content: { 'application/json': infer T } } } }
}
  ? T
  : never

export type Meta = GetResponse<'/api/v1/meta'>
export type BookPage = GetResponse<'/api/v1/books'>
export type Book = BookPage['items'][number]
export type Copy = Book['copies'][number]

/**
 * A library reference travels with every request (§1.3), even though there is
 * exactly one library until pillar 3. The header is the transport; the server
 * ignores it today and starts honouring it at P3.1 — at which point no call
 * site changes.
 */
export interface ApiOptions {
  libraryId?: string | undefined
  fetchImpl?: typeof fetch | undefined
  signal?: AbortSignal | undefined
  /** Query parameters. Kept separate from the path so the path stays a
   *  literal the generated types can key on. */
  query?: Record<string, string | number | boolean | undefined> | undefined
}

function withQuery(path: string, query: ApiOptions['query']): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined) params.set(k, String(v))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

export async function apiGet<P extends ApiPath>(
  path: P,
  opts: ApiOptions = {},
): Promise<GetResponse<P>> {
  const doFetch = opts.fetchImpl ?? globalThis.fetch
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.libraryId) headers['X-Booksnap-Library'] = opts.libraryId

  const url = withQuery(path, opts.query)
  const res = await doFetch(url, {
    headers,
    ...(opts.signal ? { signal: opts.signal } : {}),
  })
  if (!res.ok) {
    throw new ApiError(res.status, path, `GET ${path} failed: ${res.status}`)
  }
  return (await res.json()) as GetResponse<P>
}

export const getMeta = (opts?: ApiOptions): Promise<Meta> =>
  apiGet('/api/v1/meta', opts)

export const listBooks = (opts?: ApiOptions): Promise<BookPage> =>
  apiGet('/api/v1/books', opts)

/**
 * One book. The URL is built here rather than passed through `apiGet`,
 * because the generated key is the TEMPLATE `/api/v1/books/{book_id}` and the
 * request needs the substituted path — but the RESPONSE type still comes from
 * the schema, which is the part that must not be hand-written.
 */
export type BookDetail =
  paths['/api/v1/books/{book_id}']['get'] extends {
    responses: { 200: { content: { 'application/json': infer T } } }
  }
    ? T
    : never

export async function getBook(
  id: string,
  opts: ApiOptions = {},
): Promise<BookDetail> {
  const doFetch = opts.fetchImpl ?? globalThis.fetch
  const path = `/api/v1/books/${encodeURIComponent(id)}`
  const res = await doFetch(path, {
    headers: { Accept: 'application/json' },
    ...(opts.signal ? { signal: opts.signal } : {}),
  })
  if (!res.ok) throw new ApiError(res.status, path, `GET ${path}: ${res.status}`)
  return (await res.json()) as BookDetail
}

/** Bodies, straight out of the generated schema — never hand-written. */
export type BookPatch =
  paths['/api/v1/books/{book_id}']['patch'] extends {
    requestBody: { content: { 'application/json': infer T } }
  }
    ? T
    : never
export type BookCreate =
  paths['/api/v1/books']['post'] extends {
    requestBody: { content: { 'application/json': infer T } }
  }
    ? T
    : never

async function send(
  method: 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body: unknown,
  opts: ApiOptions = {},
): Promise<unknown> {
  const doFetch = opts.fetchImpl ?? globalThis.fetch
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (opts.libraryId) headers['X-Booksnap-Library'] = opts.libraryId

  const res = await doFetch(path, {
    method,
    headers,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...(opts.signal ? { signal: opts.signal } : {}),
  })
  if (!res.ok) {
    // 409 is a NORMAL outcome here, not a crash: renaming onto a book you
    // already own, or adding one you already have. Callers branch on
    // `.status`, so the message stays for the console and the status carries
    // the meaning.
    let detail = `${method} ${path} failed: ${res.status}`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      /* a 204 or an HTML error page — the status is what matters */
    }
    throw new ApiError(res.status, path, detail)
  }
  return res.status === 204 ? undefined : await res.json()
}

export const createBook = (payload: BookCreate, opts?: ApiOptions) =>
  send('POST', '/api/v1/books', payload, opts) as Promise<Book>

export const patchBook = (id: string, payload: BookPatch, opts?: ApiOptions) =>
  send('PATCH', `/api/v1/books/${encodeURIComponent(id)}`, payload,
       opts) as Promise<Book>

export const deleteBook = (id: string, opts?: ApiOptions) =>
  send('DELETE', `/api/v1/books/${encodeURIComponent(id)}`, undefined,
       opts) as Promise<void>

// --- copies (P1.7) ---------------------------------------------------------
//
// Every one of these returns the whole Book, not a copy — same reasoning as
// `patchBook`: the store replaces one record by id, and every surface
// showing that book (row, drawer, full page) reads from the same map, so a
// response carrying only the changed copy would leave the rest stale.

export type CopyCreate =
  paths['/api/v1/books/{book_id}/copies']['post'] extends {
    requestBody: { content: { 'application/json': infer T } }
  }
    ? T
    : never
export type CopyPatch =
  paths['/api/v1/books/{book_id}/copies/{copy_id}']['patch'] extends {
    requestBody: { content: { 'application/json': infer T } }
  }
    ? T
    : never
export type LendRequest =
  paths['/api/v1/books/{book_id}/copies/{copy_id}/lend']['post'] extends {
    requestBody: { content: { 'application/json': infer T } }
  }
    ? T
    : never

const bookPath = (id: string, copyId?: string, tail = '') =>
  `/api/v1/books/${encodeURIComponent(id)}/copies` +
  (copyId ? `/${encodeURIComponent(copyId)}${tail}` : '')

export const addCopy = (bookId: string, payload: CopyCreate, opts?: ApiOptions) =>
  send('POST', bookPath(bookId), payload, opts) as Promise<Book>

export const patchCopy = (
  bookId: string, copyId: string, payload: CopyPatch, opts?: ApiOptions,
) => send('PATCH', bookPath(bookId, copyId), payload, opts) as Promise<Book>

export const lendCopy = (
  bookId: string, copyId: string, payload: LendRequest, opts?: ApiOptions,
) => send('POST', bookPath(bookId, copyId, '/lend'), payload,
         opts) as Promise<Book>

export const returnCopy = (bookId: string, copyId: string, opts?: ApiOptions) =>
  send('POST', bookPath(bookId, copyId, '/return'), undefined,
       opts) as Promise<Book>

/** Export is a file download, so it is a URL rather than a fetch — letting the
 *  browser handle Content-Disposition is what makes "Save as…" work. */
export const exportUrl = (format: 'csv' | 'json'): string =>
  `/api/v1/books/export?format=${format}`

// --- capture: images, shelves, captures, reads (P2.7) -----------------------
//
// Straight off `components['schemas']`, the same generated source as every
// type above — the `paths[P]` extraction `BookPatch`/`BookCreate` use reads
// no better here and adds a layer of indirection for paths this file never
// calls through `apiGet`/`send`'s literal-path generics (image upload is
// multipart; reads are nested under a dynamic `shelf_id`). Still the SAME
// contract: a DTO rename in `app/api/dto.py` breaks this file at compile
// time either way.

export type Shelf = components['schemas']['ShelfDTO']
export type ShelfCreate = components['schemas']['ShelfCreate']
export type CaptureDTO = components['schemas']['CaptureDTO']
export type CaptureCreate = components['schemas']['CaptureCreate']
export type CapturePatch = components['schemas']['CapturePatch']
export type CaptureBinding = components['schemas']['CaptureBinding']
export type ImageDTO = components['schemas']['ImageDTO']
export type ReadCreate = components['schemas']['ReadCreate']
export type ReadDTO = components['schemas']['ReadDTO']
export type ReadSummaryDTO = components['schemas']['ReadSummaryDTO']
export type DiffSummaryDTO = components['schemas']['DiffSummaryDTO']
export type ClaimDTO = components['schemas']['ClaimDTO']
export type AlternativeDTO = components['schemas']['AlternativeDTO']
export type DiffDTO = components['schemas']['DiffDTO']
export type ClaimOutcomeDTO = components['schemas']['ClaimOutcomeDTO']
export type NotSeenEntryDTO = components['schemas']['NotSeenEntryDTO']
export type ApplyDiffRequest = components['schemas']['ApplyDiffRequest']
export type AnswerIn = components['schemas']['AnswerIn']
export type ShelfOverviewDTO = components['schemas']['ShelfOverviewDTO']
export type DepthStatusDTO = components['schemas']['DepthStatusDTO']

/** GET by a path this file builds itself (a dynamic `shelf_id`/`read_id`
 *  segment `apiGet`'s literal-key generic cannot express) — same request
 *  shape as `apiGet`, just not keyed by a `paths` literal. `getBook` above
 *  predates this and inlines the same few lines once; two more call sites
 *  below is what earns it a name. */
async function getJson<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const doFetch = opts.fetchImpl ?? globalThis.fetch
  const res = await doFetch(path, {
    headers: { Accept: 'application/json' },
    ...(opts.signal ? { signal: opts.signal } : {}),
  })
  if (!res.ok) throw new ApiError(res.status, path, `GET ${path}: ${res.status}`)
  return (await res.json()) as T
}

export const listShelves = (opts: ApiOptions = {}): Promise<Shelf[]> =>
  apiGet('/api/v1/shelves', opts)

export const listShelfCaptures = (
  shelfId: string, depth?: number, opts: ApiOptions = {},
): Promise<CaptureDTO[]> =>
  getJson(
    `/api/v1/shelves/${encodeURIComponent(shelfId)}/captures` +
    (depth !== undefined ? `?depth=${depth}` : ''),
    opts,
  )

export const addShelfDepth = (shelfId: string, opts?: ApiOptions): Promise<Shelf> =>
  send('POST', `/api/v1/shelves/${encodeURIComponent(shelfId)}/depths`,
       undefined, opts) as Promise<Shelf>

/**
 * Store a photo's bytes. Multipart, so it bypasses `send()`'s JSON body —
 * everything else (headers, error mapping) matches it exactly.
 */
export async function uploadImage(
  file: File | Blob,
  filename: string,
  opts: ApiOptions = {},
): Promise<ImageDTO> {
  const doFetch = opts.fetchImpl ?? globalThis.fetch
  const body = new FormData()
  body.append('file', file, filename)
  body.append('filename', filename)
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.libraryId) headers['X-Booksnap-Library'] = opts.libraryId
  const path = '/api/v1/images'
  const res = await doFetch(path, {
    method: 'POST', headers, body,
    ...(opts.signal ? { signal: opts.signal } : {}),
  })
  if (!res.ok) {
    throw new ApiError(res.status, path, `POST ${path} failed: ${res.status}`)
  }
  return (await res.json()) as ImageDTO
}

export const createCapture = (payload: CaptureCreate, opts?: ApiOptions) =>
  send('POST', '/api/v1/captures', payload, opts) as Promise<CaptureBinding>

export const patchCapture = (
  captureId: string, payload: CapturePatch, opts?: ApiOptions,
) => send('PATCH', `/api/v1/captures/${encodeURIComponent(captureId)}`,
         payload, opts) as Promise<CaptureBinding>

const readsPath = (shelfId: string, tail = '') =>
  `/api/v1/shelves/${encodeURIComponent(shelfId)}/reads${tail}`

export const startRead = (
  shelfId: string, payload: ReadCreate, opts?: ApiOptions,
) => send('POST', readsPath(shelfId), payload, opts) as Promise<ReadDTO>

export const getRead = (
  shelfId: string, readId: string, opts: ApiOptions = {},
): Promise<ReadDTO> =>
  getJson(readsPath(shelfId, `/${encodeURIComponent(readId)}`), opts)

export const stopRead = (
  shelfId: string, readId: string, opts?: ApiOptions,
) => send('POST', readsPath(shelfId, `/${encodeURIComponent(readId)}/stop`),
         undefined, opts) as Promise<ReadDTO>

export const getDiff = (
  shelfId: string, readId: string, opts: ApiOptions = {},
): Promise<DiffDTO> =>
  getJson(readsPath(shelfId, `/${encodeURIComponent(readId)}/diff`), opts)

export const applyDiff = (
  shelfId: string, readId: string, payload: ApplyDiffRequest, opts?: ApiOptions,
) => send('POST', readsPath(shelfId, `/${encodeURIComponent(readId)}/apply`),
         payload, opts) as Promise<DiffDTO>

export const listReadHistory = (
  shelfId: string, depth?: number, opts: ApiOptions = {},
): Promise<ReadSummaryDTO[]> =>
  getJson(
    readsPath(shelfId) + (depth !== undefined ? `?depth=${depth}` : ''),
    opts,
  )

// --- the image workspace (P2.10, §12.2 #10) ---------------------------------
//
// An image is the durable object; its runs hang off it, and a finding stays
// actionable long after its read settled. None of these re-reads a photo.

export const listCaptureReads = (
  captureId: string, opts: ApiOptions = {},
): Promise<ReadSummaryDTO[]> =>
  getJson(`/api/v1/captures/${encodeURIComponent(captureId)}/reads`, opts)

export type ManualFindingIn = components['schemas']['ManualFindingIn']

/** *"The engine missed this book"* — file one onto this photo by hand. It
 *  needs no approval (typing the title IS the approval), so this returns the
 *  diff with the book already in it. */
export const addFindingByHand = (
  shelfId: string, readId: string, payload: ManualFindingIn, opts?: ApiOptions,
) => send('POST', readsPath(shelfId, `/${encodeURIComponent(readId)}/findings`),
         payload, opts) as Promise<DiffDTO>

export const approveBook = (bookId: string, opts?: ApiOptions) =>
  send('POST', `/api/v1/books/${encodeURIComponent(bookId)}/approve`,
       undefined, opts) as Promise<Book>

const findingPath = (shelfId: string, readId: string, claimId: string,
                     action: 'retract' | 'restore') =>
  readsPath(shelfId, `/${encodeURIComponent(readId)}/findings`
                   + `/${encodeURIComponent(claimId)}/${action}`)

/** ✕ — this finding is wrong. Returns the diff recomputed after the write,
 *  same contract as `applyDiff`, so one response repaints every badge. */
export const retractFinding = (
  shelfId: string, readId: string, claimId: string, opts?: ApiOptions,
) => send('POST', findingPath(shelfId, readId, claimId, 'retract'), undefined,
         opts) as Promise<DiffDTO>

/** ↩ — undo that. Clears the standing rejection and lets the read apply
 *  itself again; never re-reads the photo. */
export const restoreFinding = (
  shelfId: string, readId: string, claimId: string, opts?: ApiOptions,
) => send('POST', findingPath(shelfId, readId, claimId, 'restore'), undefined,
         opts) as Promise<DiffDTO>

// --- the shelf-detail screen (P2.8) -----------------------------------------

export const getShelf = (shelfId: string, opts: ApiOptions = {}): Promise<Shelf> =>
  getJson(`/api/v1/shelves/${encodeURIComponent(shelfId)}`, opts)

export const getShelfOverview = (
  shelfId: string, opts: ApiOptions = {},
): Promise<ShelfOverviewDTO> =>
  getJson(`/api/v1/shelves/${encodeURIComponent(shelfId)}/overview`, opts)

export const getShelfBooks = (
  shelfId: string, depth: number, opts: ApiOptions = {},
): Promise<Book[]> =>
  getJson(`/api/v1/shelves/${encodeURIComponent(shelfId)}/books?depth=${depth}`, opts)
