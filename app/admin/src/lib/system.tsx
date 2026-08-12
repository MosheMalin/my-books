/**
 * What the operator can SEE (the staff service) and what they can CHANGE (the
 * product API), loaded once and shared by every screen.
 *
 * ⚠⚠ **The two are different scopes and must not be conflated.**
 * `libraries`/`users`/`overview` come from `/api/staff/v1` and span EVERY
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
  getOverview, listAllAccounts, listAllLibraries, listAllUsers,
  type StaffAccount, type StaffLibrary, type StaffOverview, type StaffUser,
} from '../api/staff'
import type { LibraryDTO } from '../api/schema'

interface SystemState {
  overview: StaffOverview | undefined
  /** The CUSTOMERS — the console's primary row since P3.7e. */
  accounts: StaffAccount[]
  /** The COLLECTIONS. Not the customers: an account owns one or more of
   *  these, and the real database has exactly that shape. Kept because the
   *  books and images screens narrow by library and nothing else. */
  libraries: StaffLibrary[]
  users: StaffUser[]
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
  /** The collections one customer owns, in the order the service listed them. */
  librariesOf: (accountId: string) => StaffLibrary[]
  /**
   * The people who belong to one customer, with the role they hold THERE.
   *
   * ⚠ Lives here because two screens fold `users[].memberships` the same way
   * and one of them had no gate: a version that reached for `memberships[0]`
   * instead of the entry naming the open account listed a stranger from
   * another customer and showed them the wrong badge, and the whole ring
   * passed. One fold, one place, one test.
   *
   * ⚠ A membership names an ACCOUNT since P3.7b, so this is a single lookup
   * and never a union over the account's libraries.
   */
  membersOf: (accountId: string) => Array<{ user: StaffUser; role: string;
                                            joinedAt: string | null }>
  /** Just the admins of one customer — the same fold, narrowed. */
  adminsOf: (accountId: string) => StaffUser[]
  /**
   * Did the people list actually arrive?
   *
   * ⚠⚠ Load-bearing, not diagnostics. "This customer has no admin" and "this
   * customer has no members" are ANOMALIES the console exists to surface —
   * `new_account` mints an admin in the same call and `NoAdminLeft` keeps it
   * so, which is why the screens render them in warning tone. Derived from an
   * empty `users` list, they are also exactly what a failed `/users` request
   * looks like. A console that reports a transport failure as a customer
   * nobody can administer is stating a false reason in an alarming voice.
   */
  peopleKnown: boolean
  /**
   * Which customer owns this library, or `undefined`.
   *
   * ⚠ This is what keeps an operator's old bookmark working. `#/accounts/<id>`
   * carried a LIBRARY id until P3.7e and carries an ACCOUNT id now; the route
   * parser cannot tell them apart (an id is opaque), so the screen resolves —
   * and a link to a collection lands on the customer that holds it, which is
   * the honest answer rather than a 404.
   */
  accountOfLibrary: (libraryId: string) => StaffAccount | undefined
}

const Ctx = createContext<SystemState | null>(null)

export function SystemProvider({ children }: { children: ReactNode }) {
  const [overview, setOverview] = useState<StaffOverview | undefined>(undefined)
  const [accounts, setAccounts] = useState<StaffAccount[]>([])
  const [libraries, setLibraries] = useState<StaffLibrary[]>([])
  const [users, setUsers] = useState<StaffUser[]>([])
  const [mine, setMine] = useState<LibraryDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>(undefined)
  const [needsToken, setNeedsToken] = useState(false)
  const [peopleKnown, setPeopleKnown] = useState(false)
  const [nonce, setNonce] = useState(0)
  const seq = useRef(0)
  const loaded = useRef(false)

  useEffect(() => {
    const id = ++seq.current
    const ctrl = new AbortController()
    const opts = { signal: ctrl.signal }
    // ⚠⚠ A REFRESH IS NOT A FIRST LOAD. `loading` blanks every screen to a
    // spinner (`if (loading) return <Loading/>`), so raising it on a reload
    // unmounted the accounts list AND the open drawer: renaming a library
    // from inside the drawer threw the screen away and brought it back
    // scrolled to the top, with the four preview fetches re-issued. Measured
    // with a MutationObserver across a real rename. Once anything has
    // arrived, a reload updates in place.
    if (!loaded.current) setLoading(true)
    setError(undefined)

    // ⚠ `allSettled`, not `all`. The staff service and the product API are two
    // processes: one being down must degrade what it provides, not blank the
    // console. In particular a missing staff token must still leave `mine`
    // usable, so the operator can see the one library they administer while
    // being told plainly why the rest is missing.
    Promise.allSettled([
      getOverview(opts), listAllAccounts(opts), listAllLibraries(opts),
      listAllUsers(opts), listLibraries(opts),
    ]).then(([o, accs, libs, usrs, own]) => {
      if (id !== seq.current) return
      if (o.status === 'fulfilled') setOverview(o.value)
      if (accs.status === 'fulfilled') setAccounts(accs.value)
      if (libs.status === 'fulfilled') setLibraries(libs.value)
      if (usrs.status === 'fulfilled') setUsers(usrs.value)
      if (own.status === 'fulfilled') setMine(own.value)
      // ⚠ Tracked per SOURCE, not folded into `error`. Which list is missing
      // decides what a screen may say; one boolean for four requests cannot.
      setPeopleKnown(usrs.status === 'fulfilled')
      loaded.current = true

      const failure = [o, accs, libs, usrs].find((r) => r.status === 'rejected')
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
    const byAccount = new Map<string, StaffLibrary[]>()
    for (const lib of libraries) {
      const held = byAccount.get(lib.account_id)
      if (held) held.push(lib)
      else byAccount.set(lib.account_id, [lib])
    }
    const accountById = new Map(accounts.map((a) => [a.id, a]))
    const ownerOf = new Map(libraries.map((l) => [l.id, l.account_id]))
    const membersOf = (accountId: string) => users.flatMap((user) => {
      const m = user.memberships.find((x) => x.account_id === accountId)
      return m ? [{ user, role: m.role, joinedAt: m.joined_at ?? null }] : []
    })
    return {
      overview, accounts, libraries, users, mine, loading, error, needsToken,
      peopleKnown, reload,
      membersOf,
      adminsOf: (accountId: string) =>
        membersOf(accountId).filter((m) => m.role === 'admin')
          .map((m) => m.user),
      canWrite: (id: string) => writable.has(id),
      // Falls back to the product list, then to the id: a library that exists
      // in one source and not the other still needs a name on screen, and an
      // id is a worse label but never a blank cell.
      labelOf: (id: string) =>
        labels.get(id) || mine.find((l) => l.id === id)?.label || '',
      librariesOf: (accountId: string) => byAccount.get(accountId) ?? [],
      // ⚠ Two hops, and the second one can miss. `/accounts` and `/libraries`
      // are two requests: one may have failed while the other succeeded
      // (`allSettled` above exists for exactly that), so a library whose owner
      // is not in hand answers `undefined` rather than inventing a customer.
      accountOfLibrary: (libraryId: string) => {
        const owner = ownerOf.get(libraryId)
        return owner ? accountById.get(owner) : undefined
      },
    }
  }, [overview, accounts, libraries, users, mine, loading, error, needsToken,
      peopleKnown, reload])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSystem(): SystemState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useSystem outside SystemProvider')
  return ctx
}
