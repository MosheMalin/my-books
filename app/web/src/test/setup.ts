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
