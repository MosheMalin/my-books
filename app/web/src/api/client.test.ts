/**
 * The client under a URL prefix (malinvishne.com/booksnap).
 *
 * Every URL this module hands the browser carries the build's base path —
 * the `fetch`es, and the three it builds for the browser to follow on its
 * own (`<img>` and export URLs, the provider sign-in redirect, the invite
 * link, which `location.origin` alone cannot carry). A request built without
 * the prefix works on a laptop and 404s in the one deployment nobody tests
 * there, which is why the rule is one function and this file enumerates its
 * callers.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  apiGet,
  basePath,
  exportUrl,
  imageUrl,
  inviteLink,
  providerStartUrl,
  setCurrentLibrary,
  uploadImage,
} from './client'
import { basePathFromEnv } from '../../basePath'

afterEach(() => {
  vi.unstubAllEnvs()
  setCurrentLibrary(undefined)
})

/** A fetch that records the URL it was given and answers an empty 200. */
function recorder() {
  const urls: string[] = []
  const fetchImpl = (async (input: RequestInfo | URL) => {
    urls.push(String(input))
    return new Response('{}', {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }) as typeof fetch
  return { urls, fetchImpl }
}

describe('basePath', () => {
  it('is empty at a domain root — the laptop case, and every existing test', () => {
    vi.stubEnv('BASE_URL', '/')
    expect(basePath()).toBe('')
  })

  it('drops the trailing slash Vite always adds, so paths join cleanly', () => {
    vi.stubEnv('BASE_URL', '/booksnap/')
    expect(basePath()).toBe('/booksnap')
  })

  it('is read per call: a stub after import is still seen', () => {
    vi.stubEnv('BASE_URL', '/a/')
    expect(basePath()).toBe('/a')
    vi.stubEnv('BASE_URL', '/b/')
    expect(basePath()).toBe('/b')
  })
})

describe('under /booksnap', () => {
  it('every fetch goes out prefixed, and the schema key stays unprefixed', async () => {
    vi.stubEnv('BASE_URL', '/booksnap/')
    const { urls, fetchImpl } = recorder()
    await apiGet('/api/v1/meta', { fetchImpl })
    await uploadImage(new Blob(['x']), 'shelf.jpg', { fetchImpl })
    expect(urls).toEqual(['/booksnap/api/v1/meta', '/booksnap/api/v1/images'])
  })

  it('the URLs the browser follows on its own carry it too', () => {
    vi.stubEnv('BASE_URL', '/booksnap/')
    setCurrentLibrary('lib-2')
    expect(imageUrl('k1')).toBe('/booksnap/api/v1/images/k1/thumb?library=lib-2')
    expect(exportUrl('csv')).toBe('/booksnap/api/v1/books/export?format=csv&library=lib-2')
    expect(providerStartUrl('google', '#/books'))
      .toBe('/booksnap/api/v1/auth/oauth/google/start?next=%23%2Fbooks')
    // `location.origin` is the host; the prefix is the build's to add.
    expect(inviteLink('tok')).toBe(
      `${globalThis.location.origin}/booksnap/#/invite?token=tok`)
  })
})

describe('at a domain root', () => {
  it('nothing changes — the prefix is absent, not "/"', async () => {
    vi.stubEnv('BASE_URL', '/')
    const { urls, fetchImpl } = recorder()
    await apiGet('/api/v1/meta', { fetchImpl })
    expect(urls).toEqual(['/api/v1/meta'])
    expect(imageUrl('k1')).toBe('/api/v1/images/k1/thumb')
    expect(inviteLink('tok')).toBe(`${globalThis.location.origin}/#/invite?token=tok`)
  })
})

describe('the build reads the same variable the server does', () => {
  it('normalises every spelling an operator types to Vite\'s "/x/"', () => {
    for (const root of [undefined, '', '/', '//', '  ']) {
      expect(basePathFromEnv(root)).toBe('/')
    }
    for (const spelled of ['/booksnap', '/booksnap/', 'booksnap', ' /booksnap/ ']) {
      expect(basePathFromEnv(spelled)).toBe('/booksnap/')
    }
  })
})
