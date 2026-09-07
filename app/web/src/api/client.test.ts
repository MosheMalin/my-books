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
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
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

describe('every funnel in the module goes through the prefix', () => {
  // Enumerated from the SOURCE, not from the import list above: with
  // BASE_URL '/' the prefix is the identity, so no behavioural test can
  // see a funnel that skipped it — measured: un-prefixing all four
  // `doFetch(path)` sites turned exactly ONE test red. The rule is the
  // module's own, and this is the assertion that reads the module.
  const source = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), 'client.ts'), 'utf8')

  it('every fetch call is doFetch(apiUrl(…))', () => {
    const calls = source.match(/doFetch\(/g) ?? []
    const prefixed = source.match(/doFetch\(apiUrl\(/g) ?? []
    expect(calls.length).toBeGreaterThanOrEqual(5)   // non-vacuous
    expect(prefixed.length).toBe(calls.length)
  })

  it('every URL built on location.origin adds basePath() right after it', () => {
    const origins = source.match(/globalThis\.location\.origin\}/g) ?? []
    const prefixed = source.match(/globalThis\.location\.origin\}\$\{basePath\(\)\}/g) ?? []
    expect(origins.length).toBeGreaterThanOrEqual(1)
    expect(prefixed.length).toBe(origins.length)
  })

  it('no component shows a person an address built on location.host without the prefix', () => {
    // A URL handed to a HUMAN to retype (the capture tab's phone hint)
    // is one no fetch-watching test can see — it named the domain root
    // in the first prefixed build (UX review). Enumerated from the whole
    // source tree, not from a list of known callers.
    const root = join(dirname(fileURLToPath(import.meta.url)), '..')
    const offenders: string[] = []
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name)
        if (entry.isDirectory()) { if (entry.name !== 'test') walk(path); continue }
        if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) continue
        const text = readFileSync(path, 'utf8')
        for (const line of text.split('\n')) {
          const code = line.trim()
          if (/^(\/\/|\*|\/\*)/.test(code)) continue      // a comment, not a URL
          if (!/location\.(host|origin)\b/.test(code)) continue
          if (!code.includes('basePath()')) offenders.push(`${entry.name}: ${code}`)
        }
      }
    }
    walk(root)
    expect(offenders).toEqual([])
  })

  it('no request path is handed to fetch by a name other than doFetch', () => {
    // A `globalThis.fetch(` or bare `fetch(` call would be a funnel the
    // first assertion cannot see.
    const bare = source.match(/(?<![.\w])fetch\(/g) ?? []
    const viaGlobal = source.match(/globalThis\.fetch\(/g) ?? []
    expect(bare.length + viaGlobal.length).toBe(0)
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

  it('rejects a spelling that is not a URL path rather than mangling it', () => {
    // `/\evil.com` survives a slash strip; a browser then resolves the
    // backslash as a slash entering the authority and every request
    // leaves the origin. The MSYS-rewritten Windows path is the same rule.
    for (const bad of ['/\\evil.com', '/C:/Program Files/Git/booksnap', '/a b', '/x?y']) {
      expect(() => basePathFromEnv(bad)).toThrow(/not a URL path/)
    }
  })
})
