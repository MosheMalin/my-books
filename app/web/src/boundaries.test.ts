/**
 * The household's client must not depend on the operator's console.
 *
 * The mirror of `app/admin/src/boundaries.test.ts`, and the more important
 * direction of the two: the console is a cross-tenant surface with its own
 * credential, and this app is the one every family member runs. An import that
 * way round would put an operator's screen one refactor away from a household
 * build — and the Python ring already forbids the same thing on the server
 * (`tests/test_layering.py:test_the_product_never_imports_the_staff_service`).
 *
 * Shared code goes through `@booksnap/ui` — resolved by a `tsconfig` path and
 * a vite alias this app declares itself, not by reaching into a sibling tree.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const SRC = dirname(fileURLToPath(import.meta.url))

/**
 * An import of the sibling app, however it is spelled.
 *
 * ⚠ Three properties, each of which a review had to prove was missing:
 *
 *   - **either quote style.** The first version matched single quotes only,
 *     and the identical violation written with double quotes passed. There is
 *     no ESLint, Prettier or `.editorconfig` anywhere in this repo to make one
 *     style a safe assumption;
 *   - **`import` as well as `from`.** A bare side-effect import of a
 *     stylesheet has no `from` at all, and evaded it;
 *   - **anchored to the start of a line.** An import is a statement; a comment
 *     is not. Without the anchor this file flagged ITSELF, because the note
 *     you are reading quotes the very spellings it exists to catch.
 */
const REACHES_INTO_THE_CONSOLE =
  /^\s*(?:import|export)\b[^\r\n]*?['"][^'"]*(?:(?:\.\.\/)+admin\/|app\/admin)/m

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return sources(full)
    return /\.tsx?$/.test(name) ? [full] : []
  })
}

describe('the product client does not reach into the console', () => {
  it('finds its own sources, so an empty scan cannot pass vacuously', () => {
    expect(sources(SRC).length).toBeGreaterThan(10)
  })

  it('recognises every spelling of the violation', () => {
    // The pattern IS the test, so it is probed against its own known evasions
    // rather than trusted. A pattern nobody probes is a comment.
    for (const line of [
      "import { x } from '../../admin/src/lib/ui'",
      'import { x } from "../../admin/src/lib/ui"',
      "import '../../admin/src/styles/base.css'",
      "export { x } from '../../admin/src/lib/ui'",
    ]) {
      expect(REACHES_INTO_THE_CONSOLE.test(line), line).toBe(true)
    }
    for (const line of [
      "import { SortControl } from '@booksnap/ui'",
      "// `import '../../admin/src/styles/base.css'` — prose, not a statement",
      ' * a comment mentioning app/admin in passing',
    ]) {
      expect(REACHES_INTO_THE_CONSOLE.test(line), line).toBe(false)
    }
  })

  it('imports nothing from app/admin', () => {
    const bad = sources(SRC).filter((file) =>
      REACHES_INTO_THE_CONSOLE.test(readFileSync(file, 'utf8')),
    )
    expect(bad, `these reach into app/admin: ${bad.join(', ')}`).toEqual([])
  })
})
