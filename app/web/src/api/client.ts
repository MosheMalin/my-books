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
import type { paths } from './schema'

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
