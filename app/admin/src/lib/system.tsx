/**
 * What the operator can SEE (the staff service) and what they can CHANGE (the
 * product API), loaded once and shared by every screen.
 *
 * ⚠⚠ **The two are different scopes and must not be conflated.**
 * `libraries`/`accounts`/`overview` come from `/api/staff/v1` and span EVERY
 * tenant. `mine` comes from `/api/v1/libraries` and is only the operator's own
 * memberships — the sole set they may write to, because every product route
 * resolves a library through membership and answers 404 for anything else
 * (§4.2). A screen that offered an edit control on a library outside `mine`
 * would be offering a button that 404s.
 *
 * Keeping both in one provider, rather than one each, is deliberate: the
 * question "may I act on this row?" is asked on every screen and needs both
 * halves in hand at once.
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef,
  useState, type ReactNode,
} from 'react'

import { listLibraries } from '../api/client'
import {
  getOverview, listAllAccounts, listAllLibraries,
  type StaffAccount, type StaffLibrary, type StaffOverview,
} from '../api/staff'
import type { LibraryDTO } from '../api/schema'

interface SystemState {
  overview: StaffOverview | undefined
  libraries: StaffLibrary[]
  accounts: StaffAccount[]
  /** The operator's OWN memberships — the only libraries they may write to. */
  mine: LibraryDTO[]
  loading: boolean
  /** Set when the staff service could not be reached or refused the token. */
  error: string | undefined
  /** True when the staff service answered 401: the console needs a token. */
  needsToken: boolean
  reload: () => void
  /** Can the operator write to this library through the product API? */
  canWrite: (libraryId: string) => boolean
  /** A library's display name, from the system-wide list. */
  labelOf: (libraryId: string) => string
}

const Ctx = createContext<SystemState | null>(null)

export function SystemProvider({ children }: { children: ReactNode }) {
  const [overview, setOverview] = useState<StaffOverview | undefined>(undefined)
  const [libraries, setLibraries] = useState<StaffLibrary[]>([])
  const [accounts, setAccounts] = useState<StaffAccount[]>([])
  const [mine, setMine] = useState<LibraryDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>(undefined)
  const [needsToken, setNeedsToken] = useState(false)
  const [nonce, setNonce] = useState(0)
  const seq = useRef(0)

  useEffect(() => {
    const id = ++seq.current
    const ctrl = new AbortController()
    const opts = { signal: ctrl.signal }
    setLoading(true)
    setError(undefined)

    // ⚠ `allSettled`, not `all`. The staff service and the product API are two
    // processes: one being down must degrade what it provides, not blank the
    // console. In particular a missing staff token must still leave `mine`
    // usable, so the operator can see the one library they administer while
    // being told plainly why the rest is missing.
    Promise.allSettled([
      getOverview(opts), listAllLibraries(opts), listAllAccounts(opts),
      listLibraries(opts),
    ]).then(([o, libs, accs, own]) => {
      if (id !== seq.current) return
      if (o.status === 'fulfilled') setOverview(o.value)
      if (libs.status === 'fulfilled') setLibraries(libs.value)
      if (accs.status === 'fulfilled') setAccounts(accs.value)
      if (own.status === 'fulfilled') setMine(own.value)

      const failure = [o, libs, accs].find((r) => r.status === 'rejected')
      if (failure && failure.status === 'rejected') {
        const reason = failure.reason as { status?: number; message?: string }
        setNeedsToken(reason?.status === 401)
        setError(reason?.message ?? String(failure.reason))
      } else {
        setNeedsToken(false)
      }
      setLoading(false)
    })
    return () => ctrl.abort()
  }, [nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  const value = useMemo<SystemState>(() => {
    const writable = new Set(mine.map((l) => l.id))
    const labels = new Map(libraries.map((l) => [l.id, l.label]))
    return {
      overview, libraries, accounts, mine, loading, error, needsToken, reload,
      canWrite: (id: string) => writable.has(id),
      // Falls back to the product list, then to the id: a library that exists
      // in one source and not the other still needs a name on screen, and an
      // id is a worse label but never a blank cell.
      labelOf: (id: string) =>
        labels.get(id) || mine.find((l) => l.id === id)?.label || '',
    }
  }, [overview, libraries, accounts, mine, loading, error, needsToken, reload])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSystem(): SystemState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useSystem outside SystemProvider')
  return ctx
}
