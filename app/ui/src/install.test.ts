/**
 * A client that installs itself must end up able to BUILD.
 *
 * ⚠ This package is consumed as SOURCE through a path alias, which means the
 * consuming app compiles files that live over here — and TypeScript resolves
 * `@types/react` for them from THIS directory upward, not from the app's. So
 * `app/ui/node_modules` is not only this package's own test-time concern: a
 * fresh clone that ran `npm install --prefix app/web` and nothing else got a
 * client whose ring passed 103/103 and whose `npm run build` failed with
 * `Property 'value' does not exist on type 'SelectProps'` — because
 * `SelectHTMLAttributes` had quietly resolved to nothing.
 *
 * Measured, not assumed: `dev` and the tests survive it (vite resolves React
 * through `resolve.dedupe`), and only the typecheck breaks. That is the worse
 * failure of the two — it arrives later, at the build, and points at a
 * component rather than at a missing install.
 *
 * The fix is one `postinstall` per client. This test is what stops it being
 * removed as noise by someone who has all three installed already and
 * therefore cannot reproduce the problem.
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const HERE = dirname(fileURLToPath(import.meta.url))
const APPS = ['web', 'admin'] as const

function packageJson(app: string): { scripts?: Record<string, string> } {
  return JSON.parse(readFileSync(join(HERE, '..', '..', app, 'package.json'), 'utf8'))
}

describe('installing a client installs what it compiles', () => {
  for (const app of APPS) {
    const present = existsSync(join(HERE, '..', '..', app))

    it.skipIf(!present)(`app/${app} installs @booksnap/ui after itself`, () => {
      const postinstall = packageJson(app).scripts?.postinstall ?? ''
      // Not an exact-string match: the flags are free to change. What must
      // hold is that installing this client also installs the package whose
      // sources it typechecks.
      expect(postinstall, `app/${app} has no postinstall`).toContain('../ui')
      expect(postinstall).toMatch(/npm\b.*\binstall\b/)
    })
  }
})
