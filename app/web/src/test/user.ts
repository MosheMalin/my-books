/**
 * Re-exported from `@booksnap/ui/testing/user`, where the measurement and the
 * ⚠ about `delay: null` now live — both client rings needed it, and the
 * console's was still paying the 4× toll.
 *
 * Kept as a file rather than rewriting ~120 import sites: the path is what
 * every test in this ring already reaches for, and a re-export is a one-line
 * indirection where the alternative is a large mechanical diff across the
 * app the owner has tested most.
 */
export { userEvent, default } from '@booksnap/ui/testing/user'
