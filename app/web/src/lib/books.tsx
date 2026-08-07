/**
 * The book store: one query, one record map, and the invalidation rules.
 *
 * This is the part plan D3 called "a state problem, not a rendering problem" —
 * *"One book record, two mounts, a list behind it repainting."* The mock did it
 * with a global `book:changed` event and a manual re-render; here it is a
 * context, and every surface reads the same record.
 *
 * **Why hand-rolled and not TanStack Query.** The surface is genuinely small:
 * one paginated list query, one record map, three mutations. A query library
 * would earn its place on caching across many endpoints and on background
 * refetch; here it would mostly be API surface. The one thing it would give us
 * for free — not applying a response that arrived after its query changed — is
 * a request-id guard, which is written out below and tested. Revisit when a
 * second screen needs its own cache, not before.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  ApiError,
  createBook as apiCreate,
  deleteBook as apiDelete,
  listBooks,
  patchBook as apiPatch,
  type Book,
} from '../api/client'

export type SortKey = 'title' | 'author' | 'recently_added'
export type StatusFilter = 'auto' | 'approved' | 'manual' | null

export interface BooksQuery {
  q: string
  sort: SortKey
  status: StatusFilter
  authorKey: string | null
}

export const EMPTY_QUERY: BooksQuery = {
  q: '',
  sort: 'title',
  status: null,
  authorKey: null,
}

/** 30 matches the mock's feel; the API caps a page at 200. */
export const PAGE_SIZE = 30

interface BooksState {
  query: BooksQuery
  items: Book[]
  total: number
  loading: boolean
  /** A page beyond the first is in flight — distinct from `loading`, so the
   *  feed can keep showing rows instead of blanking on every scroll. */
  loadingMore: boolean
  error: string | null
  hasMore: boolean
}

export interface BooksApi extends BooksState {
  setQuery: (patch: Partial<BooksQuery>) => void
  resetQuery: () => void
  loadMore: () => void
  /** Sorting is ignored by the server while searching — relevance IS the
   *  order — so the UI must say so rather than pretend the control applies. */
  sortApplies: boolean
  filtersActive: boolean
  get: (id: string) => Book | undefined
  edit: (id: string, patch: { title?: string; author?: string }) => Promise<Book>
  add: (payload: { title: string; author: string }) => Promise<Book>
  remove: (id: string) => Promise<void>
}

const Ctx = createContext<BooksApi | null>(null)

export function useBooks(): BooksApi {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useBooks outside <BooksProvider>')
  return ctx
}

function toParams(query: BooksQuery, offset: number) {
  const searching = query.q.trim().length > 0
  return {
    limit: PAGE_SIZE,
    offset,
    ...(searching ? { q: query.q.trim() } : {}),
    // Sending a sort alongside q would be a lie; the server ignores it.
    ...(searching ? {} : { sort: query.sort, ascending: query.sort !== 'recently_added' }),
    ...(query.status ? { status: query.status } : {}),
    ...(query.authorKey ? { author_key: query.authorKey } : {}),
  }
}

export function BooksProvider({ children }: { children: ReactNode }) {
  const [query, setQueryState] = useState<BooksQuery>(EMPTY_QUERY)
  const [state, setState] = useState<Omit<BooksState, 'query'>>({
    items: [],
    total: 0,
    loading: true,
    loadingMore: false,
    error: null,
    hasMore: false,
  })

  // Every fetch carries the id of the query it belongs to. A response whose id
  // is stale is DROPPED — otherwise a slow page-3 request lands after the user
  // has typed a search and appends books that do not match it. This is the one
  // race a query library would have handled for us.
  const queryId = useRef(0)
  const inFlight = useRef<AbortController | null>(null)

  const run = useCallback(
    async (q: BooksQuery, offset: number, id: number) => {
      inFlight.current?.abort()
      const controller = new AbortController()
      inFlight.current = controller
      setState((s) => ({
        ...s,
        error: null,
        loading: offset === 0,
        loadingMore: offset > 0,
      }))
      try {
        const page = await listBooks({
          query: toParams(q, offset),
          signal: controller.signal,
        })
        if (id !== queryId.current) return // superseded; drop it
        setState((s) => {
          const items = offset === 0 ? page.items : [...s.items, ...page.items]
          return {
            items,
            total: page.total,
            loading: false,
            loadingMore: false,
            error: null,
            hasMore: items.length < page.total,
          }
        })
      } catch (err) {
        if (controller.signal.aborted || id !== queryId.current) return
        setState((s) => ({
          ...s,
          loading: false,
          loadingMore: false,
          error: err instanceof Error ? err.message : String(err),
        }))
      }
    },
    [],
  )

  // Refetch from the top whenever the query changes. `query` is a value
  // object, so this fires on exactly the changes that matter.
  useEffect(() => {
    const id = ++queryId.current
    void run(query, 0, id)
    return () => inFlight.current?.abort()
  }, [query, run])

  const setQuery = useCallback((patch: Partial<BooksQuery>) => {
    setQueryState((prev) => {
      const next = { ...prev, ...patch }
      // Same values in, same object out: avoids a refetch when a debounced
      // search box re-emits the text the user already typed.
      const same = (Object.keys(next) as (keyof BooksQuery)[]).every(
        (k) => next[k] === prev[k],
      )
      return same ? prev : next
    })
  }, [])

  const resetQuery = useCallback(() => setQueryState(EMPTY_QUERY), [])

  const loadMore = useCallback(() => {
    setState((s) => {
      if (s.loading || s.loadingMore || !s.hasMore) return s
      void run(query, s.items.length, queryId.current)
      return { ...s, loadingMore: true }
    })
  }, [query, run])

  /** Replace one record in place. This is "edit it anywhere, it changes
   *  everywhere": the drawer, the full page and the row behind them all read
   *  from this list, so one write repaints all three. */
  const replace = useCallback((book: Book) => {
    setState((s) => ({
      ...s,
      items: s.items.map((b) => (b.id === book.id ? book : b)),
    }))
  }, [])

  const edit = useCallback(
    async (id: string, patch: { title?: string; author?: string }) => {
      const updated = await apiPatch(id, patch)
      replace(updated)
      return updated
    },
    [replace],
  )

  const remove = useCallback(async (id: string) => {
    await apiDelete(id)
    setState((s) => ({
      ...s,
      items: s.items.filter((b) => b.id !== id),
      total: Math.max(0, s.total - 1),
    }))
  }, [])

  const add = useCallback(
    async (payload: { title: string; author: string }) => {
      const created = await apiCreate(payload)
      // A new book usually belongs on a page the user has not loaded, so
      // splicing it into `items` would put it in the wrong place. Refetching
      // the pages already loaded is correct AND keeps the scroll position —
      // the alternative, jumping back to page 1, loses the reader's place.
      const id = ++queryId.current
      setState((s) => {
        void run(query, 0, id)
        return s
      })
      return created
    },
    [query, run],
  )

  const get = useCallback(
    (id: string) => state.items.find((b) => b.id === id),
    [state.items],
  )

  const value = useMemo<BooksApi>(
    () => ({
      ...state,
      query,
      setQuery,
      resetQuery,
      loadMore,
      sortApplies: query.q.trim().length === 0,
      filtersActive:
        query.q.trim() !== '' ||
        query.status !== null ||
        query.authorKey !== null ||
        query.sort !== EMPTY_QUERY.sort,
      get,
      edit,
      add,
      remove,
    }),
    [state, query, setQuery, resetQuery, loadMore, get, edit, add, remove],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** 409 means "you already own that book" — a normal answer, not a failure. */
export function isConflict(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 409
}
