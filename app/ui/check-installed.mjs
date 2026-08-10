/**
 * Refuse to typecheck or build a client while this package is uninstalled,
 * and say so in one sentence.
 *
 * `postinstall` in each client makes this unreachable on the normal path. It
 * is here for the paths that skip lifecycle scripts — `npm ci --ignore-scripts`
 * is the usual one, and some CI images default to it — where the symptom is
 * otherwise a wall of type errors inside a component:
 *
 *     src/capture/ClaimRow.tsx(368,19): error TS2322:
 *       Property 'value' does not exist on type 'SelectProps'
 *
 * Nothing about that names the cause. This package is consumed as SOURCE, so
 * TypeScript resolves `@types/react` for its files from HERE, not from the
 * app; with no `node_modules` beside them, every `SelectHTMLAttributes` in
 * this package silently becomes an empty type and every forwarded prop is an
 * error in the app that imported it.
 *
 * ⚠ Deliberately not a fix-it-for-you: a build script that quietly runs an
 * install is a build script that runs an install on a machine that was
 * offline on purpose. It names the command; a human runs it.
 */
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))

if (!existsSync(join(here, 'node_modules'))) {
  process.stderr.write(
    '\n@booksnap/ui is not installed, and this client compiles its sources.\n' +
    'Without it, TypeScript resolves no React types for them and the errors\n' +
    'surface inside your own components. Run:\n\n' +
    '    npm install --prefix app/ui\n\n' +
    "(each client's postinstall normally does this for you — you are seeing\n" +
    'this because lifecycle scripts were skipped.)\n\n',
  )
  process.exit(1)
}
