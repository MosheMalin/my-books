/**
 * The SYSTEM-admin API client — `/api/staff/v1`, cross-tenant, read-only.
 *
 * ⚠⚠ **This is a different service from `/api/v1`, not a wider view of it.**
 * Every product route resolves a library through the caller's MEMBERSHIPS, by
 * design (§4.2: a foreign record reads as ABSENT), so no amount of client
 * cleverness makes it answer "every tenant". The staff service is a second
 * application on its own port with its own credential; see
 * `app/staff_api/__init__.py` for why a system administrator cannot be
 * expressed as a `Role`.
 *
 * The console therefore talks to BOTH, and the split is the useful one:
 *
 *   - **this module** — everything the operator can SEE: every account, every
 *     library, every book, system totals. Read-only, by construction;
 *   - **`./client.ts`** — everything the operator can CHANGE, which is only
 *     ever inside libraries they are themselves a member of, through the
 *     ordinary product API and the ordinary rules.
 *
 * ⚠ The DTOs below were HAND-MIRRORED from `app/staff_api/app.py` until
 * 2026-08-10, under the constraint that forbade touching
 * `tools/api_contract.py`. They are generated now — `app/staff_api/openapi.json`
 * → `./staff-schema.d.ts`, the same pipeline and the same committed-artefact
 * rule as the product contract — so a renamed staff DTO is a COMPILE error
 * here rather than an `undefined` appearing in a table. The names below are
 * aliases kept for the screens that already read them.
 */

export class StaffError extends Error {
  constructor(readonly status: number, readonly path: string, message: string) {
    super(message)
    this.name = 'StaffError'
  }
}

// --- the credential ---------------------------------------------------------
//
// ⚠ Module-level, and persisted — the same shape `client.ts` argues for its
// library selection, and the same justification: one module instance is one
// operator's tab. It is NOT a login (there is no account behind it); it is the
// shared secret that stands between the LAN and every tenant's data, so it is
// held in one place rather than threaded through screens that could forget it.

const TOKEN_KEY = 'booksnap.admin.staffToken'

let token: string | undefined = (() => {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? undefined
  } catch {
    return undefined
  }
})()

export function setStaffToken(next: string | undefined): void {
  token = next?.trim() || undefined
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* private mode — it simply does not persist */
  }
}

export const getStaffToken = (): string | undefined => token

// --- DTOs (GENERATED — see the header) --------------------------------------

import type { components } from './staff-schema'

type Schemas = components['schemas']

/** System totals. `authenticated: false` means the service has no token
 *  configured and anyone who can reach the port reads every tenant — shown on
 *  screen, never swallowed. `orphan_libraries` are libraries with no
 *  membership at all: nobody can see or administer them. */
export type StaffOverview = Schemas['OverviewDTO']
export type StaffLibrary = Schemas['LibraryDTO']
export type StaffMembership = Schemas['MembershipDTO']
export type StaffAccount = Schemas['AccountDTO']
export type StaffBook = Schemas['BookDTO']
/** `truncated` means a ranked search hit the server's scan cap: `total` is
 *  honest, but pages past the cap are unreachable. Told, not hidden. */
export type StaffBookPage = Schemas['BookPageDTO']
export type StaffShelf = Schemas['ShelfDTO']
export type StaffRead = Schemas['ReadDTO']

// --- transport --------------------------------------------------------------

export interface StaffOptions {
  signal?: AbortSignal | undefined
  fetchImpl?: typeof fetch | undefined
}

type Query = Record<string, string | number | boolean | undefined>

function withQuery(path: string, query?: Query): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== '') params.set(k, String(v))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

async function get<T>(path: string, opts: StaffOptions, query?: Query): Promise<T> {
  const doFetch = opts.fetchImpl ?? globalThis.fetch
  const url = withQuery(`/api/staff/v1${path}`, query)
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (token) headers['X-Booksnap-Staff'] = token

  const res = await doFetch(url, {
    headers,
    ...(opts.signal ? { signal: opts.signal } : {}),
  })
  if (!res.ok) {
    let detail = `GET ${url} failed: ${res.status}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* not JSON — the status carries the meaning */
    }
    throw new StaffError(res.status, url, detail)
  }
  return (await res.json()) as T
}

export const getOverview = (opts: StaffOptions = {}) =>
  get<StaffOverview>('/overview', opts)

export const listAllLibraries = (opts: StaffOptions = {}) =>
  get<StaffLibrary[]>('/libraries', opts)

export const listAllAccounts = (opts: StaffOptions = {}) =>
  get<StaffAccount[]>('/accounts', opts)

export const listLibraryShelves = (libraryId: string, opts: StaffOptions = {}) =>
  get<StaffShelf[]>(`/libraries/${encodeURIComponent(libraryId)}/shelves`, opts)

export interface StaffBookQuery {
  q?: string | undefined
  libraryId?: string | undefined
  status?: string | undefined
  sort?: 'title' | 'author' | 'recently_added' | undefined
  ascending?: boolean | undefined
  limit?: number | undefined
  offset?: number | undefined
}

/**
 * Books across every tenant, PAGED BY THE SERVER.
 *
 * ⚠ This is what retired the console's one real compromise. Before the staff
 * service existed, "all libraries" meant fetching each tenant separately,
 * merging in the browser and sorting with `localeCompare` — which is not the
 * server's normalized key, so the merged order differed from a single
 * library's and the screen had to say so. Ordering and ranking now happen once,
 * server-side, by the same measured Hebrew rules the product uses.
 */
export const listAllBooks = (query: StaffBookQuery = {}, opts: StaffOptions = {}) =>
  get<StaffBookPage>('/books', opts, {
    q: query.q,
    library_id: query.libraryId,
    status: query.status,
    sort: query.sort,
    ascending: query.ascending,
    limit: query.limit,
    offset: query.offset,
  })

export const listRecentReads = (
  limit = 30, libraryId?: string, opts: StaffOptions = {},
) => get<StaffRead[]>('/reads', opts, { limit, library_id: libraryId })
