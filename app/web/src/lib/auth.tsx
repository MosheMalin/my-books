/**
 * Signed-in state for the whole tree (P4.1b).
 *
 * The session itself is an HttpOnly cookie the browser holds — this
 * provider never sees it. What it holds is the CONSEQUENCE: whether the
 * last word from the server was "who are you?" (any request answering 401
 * fires `SIGNED_OUT_EVENT` from the one place all requests fail through),
 * and the redemption of an emailed link landing on `#/login?token=…`.
 *
 * Boots OPTIMISTIC ('in'): the first paint is the app, and if the very
 * first request 401s the login screen replaces it — one flicker on a
 * signed-out load, zero extra requests on every signed-in one. A dedicated
 * "am I signed in?" probe would cost every real load a round trip to save
 * a stranger a flicker.
 *
 * Sits ABOVE `LibraryProvider` (see `main.tsx` — the harness mirrors the
 * same stack): signing in remounts everything below via the epoch key, so
 * the library list boots fresh for the person who just arrived, exactly
 * like the switcher's own remount rule.
 */
import {
  Fragment,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { replaceHash, useHash } from '@booksnap/ui'

import {
  SIGNED_OUT_EVENT,
  listLibraries,
  redeemLoginToken,
  signOut as apiSignOut,
} from '../api/client'
import { LoginScreen } from './LoginScreen'
import { LIBRARY_HASH, parseHash } from './route'

/** Where an invite token waits out the sign-in detour (P4.3). Reset by
 *  `src/test/setup.ts` like every other storage key. */
export const PENDING_INVITE_KEY = 'booksnap.invite'

interface AuthApi {
  /** Revoke the session server-side, then show the login screen. */
  signOutNow: () => void
}

const AuthContext = createContext<AuthApi | null>(null)

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside <AuthProvider>')
  return ctx
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<'in' | 'out'>('in')
  // Bumped on every successful sign-in: the subtree below remounts and
  // boots fresh, the same rule as the switcher's library remount.
  const [epoch, setEpoch] = useState(0)
  // A failed redemption's message, shown on the login screen it lands on.
  const [linkError, setLinkError] = useState(false)
  const hash = useHash()

  useEffect(() => {
    const onSignedOut = () => setState('out')
    globalThis.addEventListener(SIGNED_OUT_EVENT, onSignedOut)
    return () => globalThis.removeEventListener(SIGNED_OUT_EVENT, onSignedOut)
  }, [])

  // An invite link opened by someone SIGNED OUT: the token must survive
  // the sign-in detour (the redeem below navigates away). Stashed under
  // its own storage key; `InviteGate` consumes it once inside the app.
  useEffect(() => {
    const route = parseHash(hash)
    if (route.name === 'invite' && route.token) {
      localStorage.setItem(PENDING_INVITE_KEY, route.token)
    }
  }, [hash])

  // The emailed link lands here. THREE guards, each measured necessary
  // (P4.1b's UX review, CRITICALs 1 and 2):
  //   - `replaceHash`, never navigate: the token URL must not stay one
  //     Back-press behind the app, where it re-fires consumed;
  //   - `attempted` remembers the token this mount already traded, so
  //     StrictMode's double effect run (dev) cannot redeem-then-401 the
  //     same token and paint "expired" over a fresh session;
  //   - a 401 probes /libraries before believing itself: a mail scanner
  //     prefetching the link consumes it, and the human who then taps IS
  //     signed in — the cookie their browser holds is the truth, not the
  //     token's second-use refusal.
  const attempted = useRef<string | null>(null)
  useEffect(() => {
    const route = parseHash(hash)
    if (route.name !== 'login' || !route.token) return
    if (attempted.current === route.token) return
    attempted.current = route.token
    let live = true
    const arrive = () => {
      setLinkError(false)
      replaceHash(LIBRARY_HASH)
      setState('in')
      setEpoch((e) => e + 1)
    }
    redeemLoginToken(route.token)
      .then(() => live && arrive())
      .catch(() =>
        listLibraries()
          .then(() => live && arrive())
          .catch(() => {
            if (!live) return
            // Expired, consumed, invented — one sentence, one remedy.
            setLinkError(true)
            replaceHash(LIBRARY_HASH)
            setState('out')
          }),
      )
    return () => {
      live = false
    }
  }, [hash])

  const signOutNow = useCallback(() => {
    // The server answer decides nothing: sign-out is a state to arrive
    // at, and a dropped connection must not leave the screen signed in
    // with a cookie the next request will 401 on anyway.
    void apiSignOut().catch(() => undefined)
    setLinkError(false)
    setState('out')
  }, [])

  if (state === 'out') {
    return <LoginScreen linkError={linkError} />
  }
  return (
    <AuthContext.Provider value={{ signOutNow }}>
      <Fragment key={epoch}>{children}</Fragment>
    </AuthContext.Provider>
  )
}
