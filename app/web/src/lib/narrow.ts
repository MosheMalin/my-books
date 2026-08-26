/**
 * "Too narrow for the app bar to hold the tabs" — ONE breakpoint, spelled
 * once.
 *
 * The bar carries a brand, a library switcher, three tabs, a language toggle
 * and an account menu. Measured at 375x812 on the owner's library: 472px of
 * content in a 375px bar, so `documentElement.scrollWidth` was **484 against a
 * clientWidth of 375** and the whole DOCUMENT scrolled sideways. That is not a
 * cosmetic overflow — every fixed-position and percentage-sized surface then
 * lays itself out in a 484px page. The plan canvas rendered 109px of furniture
 * off-screen at rest, and the bookcase panel's own *select this bookcase*
 * button sat at x=412: a control a finger could not reach on the device this
 * catalogue is used from.
 *
 * `books.css` has carried the answer as a COMMENT since P1.0 — *"the mock
 * hides this at mobile width in favour of a `.botnav` bottom bar — not built
 * here"* — and a second rule downstream (`.toolbar { top: 0 }` inside the same
 * breakpoint) was written as though it HAD been built. It had not, so the
 * Books tab's sticky toolbar docked at 0 underneath a sticky app bar: measured
 * 52 of its 153px hidden behind the bar while scrolled. A comment describing
 * an unbuilt mechanism is the CLAUDE.md failure that ships a wrong rule beside
 * it (P6.4d's `apply_diff`, and the docstring asserting a test exists).
 *
 * ⚠ The breakpoint is 760px because that is the one `books.css` already spells
 * and the one those two rules were written against — not because a tablet
 * cannot hold six controls. `narrow.test.ts` reads the sheet and fails if the
 * two ever disagree, which is the enumerate-from-the-source rule applied to
 * the one number a media query and a hook must never differ on.
 */
import { useCallback, useSyncExternalStore } from 'react'

export const NARROW_QUERY = '(max-width: 760px)'

/** Guarded, like `Inspector.tsx`'s own `onPhone`: jsdom has no `matchMedia`,
 *  and a missing one must mean "not narrow", never a crash. */
function query(): MediaQueryList | null {
  try {
    return globalThis.matchMedia?.(NARROW_QUERY) ?? null
  } catch {
    return null
  }
}

/**
 * Whether the viewport is narrow, RE-READ on resize.
 *
 * ⚠ Reactive on purpose, and it is the accessibility half of the fix rather
 * than a nicety: exactly ONE navigation is in the document at a time. Keeping
 * both and hiding one in CSS would put two buttons named "ספרים" in the
 * accessibility tree — the collision CLAUDE.md records costing a *rename*
 * control its only label — and `display: none` is invisible to a `getByRole`
 * query, so the client ring could not have seen it either.
 */
export function useNarrow(): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const mql = query()
    mql?.addEventListener?.('change', onChange)
    return () => mql?.removeEventListener?.('change', onChange)
  }, [])
  return useSyncExternalStore(
    subscribe,
    () => query()?.matches ?? false,
    () => false,
  )
}
