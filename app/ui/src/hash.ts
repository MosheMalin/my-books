/**
 * The hash-router PRIMITIVE — the subscription, not the routes.
 *
 * Both apps hand-rolled a hash router and both gave the same reason: a handful
 * of screens do not earn a router dependency, and a hash route needs no server
 * rewrite rule (the product is served by FastAPI from one index.html; the
 * console by `vite preview` with nothing in front of it at all).
 *
 * What is genuinely common is only this: subscribe to `hashchange`, hold the
 * current string, set it, and go back. **Route TABLES are deliberately not
 * shared** — `#/book/<id>` and `#/libraries/<id>` are two apps' vocabularies,
 * and a union of both would let one app link to a screen it does not have.
 * Each app keeps its own `parseHash` over the string this hook returns.
 */
import { useEffect, useState } from 'react'

/** The current `location.hash`, kept in sync with the browser. */
export function useHash(): string {
  const [hash, setHash] = useState(() => globalThis.location?.hash ?? '')

  useEffect(() => {
    const onChange = () => setHash(globalThis.location.hash)
    globalThis.addEventListener('hashchange', onChange)
    // ⚠ Read once on mount as well as on the event. A hash set between the
    // initial render and this effect (a redirect during startup, or a test
    // that navigates before the component mounts) fires no `hashchange` this
    // listener can hear, and the screen would render the old route forever.
    onChange()
    return () => globalThis.removeEventListener('hashchange', onChange)
  }, [])

  return hash
}

/** Navigate, skipping a no-op assignment — writing the identical hash back
 *  pushes nothing but does re-fire listeners in some browsers. */
export function navigateHash(next: string): void {
  if (globalThis.location.hash === next) return
  globalThis.location.hash = next
}

/**
 * Navigate WITHOUT leaving the old hash in history.
 *
 * For routes that must not be returnable: a redeemed sign-in token
 * (`#/login?token=…`) one Back-press behind the app re-fires a consumed
 * credential and throws a live session onto a false "link expired" screen
 * — measured, P4.1b's UX review, CRITICAL 1. `location.replace` swaps the
 * current history entry and still fires `hashchange`, which
 * `history.replaceState` would not.
 */
export function replaceHash(next: string): void {
  if (globalThis.location.hash === next) return
  globalThis.location.replace(next)
}

/**
 * Go back, or to `fallback` when there is nowhere to go.
 *
 * `history.back()` rather than navigating to the list, so returning from a
 * detail screen restores the list's scroll position instead of jumping to the
 * top. The fallback is for a deep link opened directly, where this tab has no
 * history of its own.
 */
export function backOr(fallback: string): void {
  if (globalThis.history.length > 1) globalThis.history.back()
  else globalThis.location.hash = fallback
}
