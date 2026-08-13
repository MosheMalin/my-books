/**
 * Which library the client is looking at (P3.1, §1.3).
 *
 * The vision's tenancy boundary is the Library (§4.1) and an account may
 * belong to several, so "the" library is not a thing any screen may assume.
 * This module owns the selection: it restores it, validates it against what
 * the server says this account actually has, sends it on every request (via
 * `setCurrentLibrary`), and switches it.
 *
 * ⚠ **The stored id is applied at MODULE LOAD, not in an effect.** Every
 * screen fetches on mount, and an effect runs after its children's first
 * render — so a selection applied there would let the first page of books go
 * out under the *default* library and never be refetched. Reading
 * localStorage synchronously here means the very first request already
 * carries the right tenant.
 *
 * ⚠ **Switching REMOUNTS the app** (`main.tsx` keys the tree on the current
 * id) rather than asking each screen to refetch. Every piece of state below
 * is about one library — the book store's record map, the intake queue, an
 * open drawer, a shelf's read history — and a per-screen "reload on change"
 * is a list that gets one entry longer with every new screen and is wrong the
 * first time someone forgets. Remounting is the one mechanism that cannot be
 * partially applied.
 */
import {
  Fragment,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  createLibrary,
  listLibraries,
  setCurrentLibrary,
  type LibraryDTO,
} from '../api/client'
import { LIBRARY_HASH } from './route'

const STORAGE_KEY = 'booksnap.library'

function stored(): string | undefined {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) ?? undefined
  } catch {
    /* private mode; the server's default library is a fine answer */
    return undefined
  }
}

function remember(id: string | undefined): void {
  try {
    if (id) globalThis.localStorage?.setItem(STORAGE_KEY, id)
    else globalThis.localStorage?.removeItem(STORAGE_KEY)
  } catch {
    /* the choice just won't survive a reload */
  }
}

/** Restore the remembered selection into the API client.
 *
 * Called once at module load, before any component renders — see the ⚠ at the
 * top. Exported because a test that simulates a RELOAD has to re-run exactly
 * this step: the module only initialises once per process, so without it the
 * "remembers the choice" test would be asserting against state the previous
 * test left behind rather than against localStorage.
 */
export function applyStoredLibrary(): void {
  setCurrentLibrary(stored())
}

applyStoredLibrary()

export interface LibraryApi {
  /** Every library this account belongs to, in the server's (domain) order. */
  libraries: LibraryDTO[]
  /** The selected one, once known. Null while loading, or if the account has
   *  none — a real state (P4.3's sign-up), not an error. */
  current: LibraryDTO | null
  currentId: string | undefined
  loading: boolean
  /** The list could not be loaded. The app still works: requests fall back to
   *  whatever the server resolves, which for one household is the right
   *  library — the switcher just cannot show its name. */
  failed: boolean
  switchTo: (id: string) => void
  create: (label: string) => Promise<LibraryDTO>
  /** Absorb rows that appeared out-of-band — an accepted invite (P4.3) is
   *  the case the mount-once ⚠ below always named. Rows merge by id; the
   *  first NEW one becomes the selection, because "show me what just
   *  opened up" is the whole reason the caller has rows in hand. */
  absorb: (rows: LibraryDTO[]) => void
}

const Ctx = createContext<LibraryApi | null>(null)

export function LibraryProvider({ children }: { children: ReactNode }) {
  const [libraries, setLibraries] = useState<LibraryDTO[]>([])
  const [currentId, setCurrentId] = useState<string | undefined>(stored)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  // ⚠ Fetched ONCE, on mount, and this provider sits above `LibraryScope`
  // so it never remounts short of a full page load. The case this always
  // named — an accepted invite appearing mid-session — is answered since
  // P4.3 by `absorb()`: the accept response's rows merge in the way
  // `create()`'s do. A library created out-of-band at a terminal is still
  // invisible until reload, which is fine: the terminal user can press F5.
  useEffect(() => {
    let live = true
    listLibraries()
      .then((rows) => {
        if (!live) return
        setLibraries(rows)
        // ⚠ A stored id that is no longer in the list — a library someone
        // left, or a browser carrying another install's key — must not stay
        // selected: every request would 404 and the app would look broken
        // rather than simply pointing at the wrong shelf. Fall back to the
        // first one the account really has.
        const chosen = rows.find((r) => r.id === stored()) ?? rows[0]
        setCurrentLibrary(chosen?.id)
        setCurrentId(chosen?.id)
        remember(chosen?.id)
      })
      .catch(() => live && setFailed(true))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [])

  const switchTo = useCallback((id: string) => {
    if (id === currentId) return
    setCurrentLibrary(id)
    remember(id)
    // Back to the Books tab: a deep link (#/book/<id>, #/map/<shelfId>) names
    // a record of the library being left, and it would 404 in the new one.
    globalThis.location.hash = LIBRARY_HASH
    setCurrentId(id)
  }, [currentId])

  const create = useCallback(async (label: string) => {
    const made = await createLibrary(label)
    setLibraries((prev) => [...prev, made])
    // Switching to it is the point of having made it.
    setCurrentLibrary(made.id)
    remember(made.id)
    globalThis.location.hash = LIBRARY_HASH
    setCurrentId(made.id)
    return made
  }, [])

  const absorb = useCallback((rows: LibraryDTO[]) => {
    if (!rows.length) return
    setLibraries((prev) => {
      const known = new Set(prev.map((l) => l.id))
      const fresh = rows.filter((r) => !known.has(r.id))
      if (fresh.length) {
        const target = fresh[0]!.id
        setCurrentLibrary(target)
        remember(target)
        globalThis.location.hash = LIBRARY_HASH
        setCurrentId(target)
      }
      return [...prev, ...rows.filter((r) => !known.has(r.id))]
    })
  }, [])

  const value = useMemo<LibraryApi>(() => ({
    libraries,
    current: libraries.find((l) => l.id === currentId) ?? null,
    currentId,
    loading,
    failed,
    switchTo,
    create,
    absorb,
  }), [libraries, currentId, loading, failed, switchTo, create, absorb])

  // ⚠ Nothing renders until the library is known, and the reason is not
  // cosmetic. Every screen fetches on mount; a screen mounted before
  // `GET /libraries` answers sends its first request under whatever was
  // stored (or none at all) and never asks again. The alternatives are both
  // worse: remounting a moment later throws away anything typed in that
  // first second — it is what broke the search race-guard test — and letting
  // the first page load untenanted makes "every request carries the library"
  // nearly-true, which is the state this whole item exists to leave.
  //
  // The wait is one local request, and it is skipped entirely when it fails
  // (`failed`), so a switcher that cannot load never holds the books hostage.
  return (
    <Ctx.Provider value={value}>{loading ? null : children}</Ctx.Provider>
  )
}

export function useLibrary(): LibraryApi {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useLibrary outside <LibraryProvider>')
  return ctx
}

/**
 * Everything inside this is thrown away and rebuilt when the library changes.
 *
 * ⚠ One `key`, defined once and used by both `main.tsx` and the test harness
 * — a rule the tests reproduce with their own copy of is a rule the tests
 * cannot catch a regression in.
 *
 * It must sit BELOW `LibraryProvider` (whose state has to survive the
 * remount it triggers) and ABOVE everything that holds per-library state:
 * the book store's record map, the intake queue, an open drawer, a shelf's
 * read history. Asking each of those to notice a switch is a list that gets
 * longer with every screen and is wrong the first time someone forgets one —
 * and "wrong" here means one library's books under another's name.
 */
export function LibraryScope({ children }: { children: ReactNode }) {
  const { currentId } = useLibrary()
  return <Fragment key={currentId ?? 'default'}>{children}</Fragment>
}
