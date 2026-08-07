import '@testing-library/jest-dom/vitest'

/**
 * jsdom has no IntersectionObserver, and the feed uses one for endless scroll.
 *
 * Deliberately a stub that never fires: paging behaviour is asserted through
 * the store (query changes reset the offset), not by faking a scroll. A stub
 * that DID fire would make every list test load every page, which is slower
 * and tests the observer rather than the code that uses it.
 */
class NoopIntersectionObserver implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly thresholds: readonly number[] = []
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}

globalThis.IntersectionObserver =
  NoopIntersectionObserver as unknown as typeof IntersectionObserver

/**
 * jsdom has no object URL machinery, and the Capture tab (P2.7) previews each
 * dropped file with `URL.createObjectURL` before it has finished uploading.
 * A no-op stub is enough — no test inspects the resulting string, only that
 * calling it (and its `revoke` counterpart, on unmount) does not throw.
 */
if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = () => 'blob:mock'
}
if (typeof URL.revokeObjectURL !== 'function') {
  URL.revokeObjectURL = () => undefined
}
