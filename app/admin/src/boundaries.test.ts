/**
 * The console is a SEPARATE application from the product client, and this is
 * the mechanical half of that claim.
 *
 * It had exactly one crossing until 2026-08-10: a type-only import of
 * `app/web/src/api/schema.d.ts`, well argued at the time (a copy would be a
 * second generated artefact the contract check does not police). The generated
 * contract now lives in the shared package instead, so the crossing is gone —
 * and a test is what stops the next convenient one from arriving unargued.
 *
 * Sharing goes through `@booksnap/ui`. ⚠ Which is NOT an npm dependency of
 * either app — it resolves through a `tsconfig` path and a vite alias, both
 * declared in this app's own config. That is the distinction the rule rests
 * on: a package this app opts into by name, versus reaching into a sibling's
 * source tree by relative path.
 *
 * Reaching into a sibling app is different in kind: it makes one client's
 * refactor break another client's build, and it would eventually make the
 * console undeployable without the household's app beside it — which is the
 * whole point of the split (phase 2 puts a login in front of this one).
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const SRC = dirname(fileURLToPath(import.meta.url))

/**
 * An import of the sibling app, however it is spelled — see the product's
 * copy of this file for the three evasions a review had to prove: either
 * quote style, a bare side-effect `import` with no `from`, and the line
 * anchor without which this file flags its own prose.
 */
const REACHES_INTO_THE_PRODUCT =
  /^\s*(?:import|export)\b[^\r\n]*?['"][^'"]*(?:(?:\.\.\/)+web\/|app\/web)/m

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return sources(full)
    return /\.tsx?$/.test(name) ? [full] : []
  })
}

describe('the console does not reach into the product client', () => {
  it('finds its own sources, so an empty scan cannot pass vacuously', () => {
    expect(sources(SRC).length).toBeGreaterThan(10)
  })

  it('recognises every spelling of the violation', () => {
    // The pattern IS the test, so it is probed against its own known evasions
    // rather than trusted. A pattern nobody probes is a comment.
    for (const line of [
      "import type { components } from '../../web/src/api/schema'",
      'import { x } from "../../web/src/lib/books"',
      "import '../../web/src/styles/books.css'",
      "export { x } from '../../web/src/lib/books'",
    ]) {
      expect(REACHES_INTO_THE_PRODUCT.test(line), line).toBe(true)
    }
    for (const line of [
      "import { SortControl } from '@booksnap/ui'",
      "import type { components } from '@booksnap/ui/api/schema'",
      '// this used to reach into `app/web/src/api/schema.d.ts`',
    ]) {
      expect(REACHES_INTO_THE_PRODUCT.test(line), line).toBe(false)
    }
  })

  it('imports nothing from app/web', () => {
    const bad = sources(SRC).filter((file) =>
      REACHES_INTO_THE_PRODUCT.test(readFileSync(file, 'utf8')),
    )
    expect(bad, `these reach into app/web: ${bad.join(', ')}`).toEqual([])
  })
})

/**
 * ⚠⚠ **The console reports; it does not moderate a household's catalogue.**
 *
 * The owner's rule, 2026-08-13:
 *
 *   > in the list of libraries — I should not be able to approve it or remove
 *   > it or edit it. this is not mine to do so. I can only see info about it
 *   > and about the libraries.
 *
 * Revision 2's split was "read across tenants, write where you are a member",
 * which answers *may this request succeed?*. This answers *whose job is it?* —
 * and the two differ exactly where the operator happens to hold a membership,
 * which on the owner's own machine is everywhere.
 *
 * STRUCTURAL, not a screen test. "No button is rendered today" is a fact about
 * one render; this is a fact about the app. `api/client.ts` no longer exports
 * the three calls at all, and this fails if any file names a book-mutating
 * product route again — including one written straight into a component with
 * `fetch`, which is the shortcut a hidden-button rule would never catch.
 *
 * ⚠ Scoped to books. `POST /libraries` and `PATCH /libraries/{id}` are the
 * writes the console KEEPS: administering a customer's tenancy is its job,
 * editing their catalogue is not. That distinction IS the rule, so this must
 * not be widened to "any mutation".
 */
const BOOK_WRITE_CALLS = ['approveBook', 'patchBook', 'deleteBook']

/**
 * ⚠ Substring checks and one tiny regex, rather than one dense pattern. Three
 * scripted attempts at a denser literal put a real newline and two BACKSPACE
 * characters into this file — `\n` and `\b` surviving as escapes through the
 * edit — after which the pattern matched nothing and the test still reported
 * ok. A guard that can be silently disarmed by its own delivery is not a
 * guard. Plain needles cannot be mangled that way, and they read better.
 */
function mutatesABook(source: string): boolean {
  // ⚠ CODE lines only. The rule's own explanation names the three calls, and
  // so does the client's note about why they are gone — a scan that read
  // comments flagged both files and made the honest thing (writing down what
  // was removed and why) the thing that broke the build. The import rule above
  // solves the same problem with its `^\s*import` anchor.
  const code = source.split('\n')
    .filter((line) => !/^\s*(?:\/\/|\/?\*)/.test(line))
  if (code.some((line) => BOOK_WRITE_CALLS.some((n) => line.includes(n)))) {
    return true
  }
  return code.some((line) => {
    if (!line.includes('books')) return false
    // A mutating verb aimed at the books route, however it is spelled —
    // through the client's `request(...)` helper or a bare `fetch`.
    return /PATCH|DELETE/.test(line) || line.includes('/approve')
  })
}

describe('the console never writes to a household catalogue', () => {
  it('recognises every spelling of the violation', () => {
    // Probed against its own evasions, exactly like the import rule above.
    for (const line of [
      "import { approveBook } from '../api/client'",
      'await patchBook(libraryId, id, { title })',
      'deleteBook(libraryId, id)',
      "request('DELETE', `/api/v1/books/${id}`, { libraryId })",
      "request('PATCH', `/api/v1/books/${id}`, { libraryId }, payload)",
      "fetch('/api/v1/books/x/approve', { method: 'POST' })",
    ]) {
      expect(mutatesABook(line), line).toBe(true)
    }
    // …and does NOT flag the reads, nor the tenancy writes the console keeps.
    for (const line of [
      "get<StaffBookPage>('/books', opts, { q })",
      "request('POST', '/api/v1/libraries', opts, { label })",
      "request('PATCH', `/api/v1/libraries/${id}`, opts, { label })",
      "export const exportUrl = (libraryId: string, format: 'csv' | 'json')",
    ]) {
      expect(mutatesABook(line), line).toBe(false)
    }
  })

  it('has no file that can approve, edit or delete a book', () => {
    const bad = sources(SRC)
      // This file NAMES the forbidden calls, in its prose and in its probes.
      .filter((file) => !/boundaries\.test\.tsx?$/.test(file))
      .filter((file) => mutatesABook(readFileSync(file, 'utf8')))
    expect(bad, `these can mutate a book: ${bad.join(', ')}`).toEqual([])
  })
})
