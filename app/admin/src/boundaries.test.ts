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
