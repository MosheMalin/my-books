/**
 * The bridge is a CONTRACT, so it is checked mechanically.
 *
 * Shared CSS draws only from `--ui-*` custom properties, and each app maps its
 * own palette onto them. Nothing in either client ring can catch a missing
 * mapping — **jsdom computes no cascade**, so a control whose colour resolves
 * to nothing renders invisibly through a completely green suite, and the first
 * person to find out is whoever opens the screen. This test is the substitute:
 * it reads the shared sheet, collects every `--ui-*` it references, and fails
 * if an app does not define it.
 *
 * ⚠ It reaches into sibling directories, which nothing else here does. That is
 * deliberate and is the narrow exception: the contract has two ends, and a
 * test that could only see one end would be checking nothing. It SKIPS rather
 * than fails when an app is absent, the same rule the repo's spotchecks and
 * client half already follow — a gate that blocks on a missing sibling is a
 * gate people delete.
 */
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// ⚠ `fileURLToPath`, not `new URL(...).pathname`. On Windows the latter yields
// `/D:/…`, and stripping the slash by hand is how this first ran looking for
// `D:\src\index.ts\styles\ui.css`.
const HERE = dirname(fileURLToPath(import.meta.url))
const SHARED_CSS = join(HERE, 'styles', 'ui.css')
const APPS = ['web', 'admin'] as const

/** Every `var(--ui-…)` the shared sheet reads.
 *
 *  ⚠ `\s*` after the paren and `A-Z` in the name: `var( --ui-x )` is legal CSS
 *  and so is a capitalised token. The first version of this regex required
 *  neither, and a review proved it — `var( --ui-danger )`, an undeclared token
 *  that would make its whole rule invalid in both apps, passed 25/25. */
function required(): string[] {
  const css = readFileSync(SHARED_CSS, 'utf8')
  const names = new Set<string>()
  for (const match of css.matchAll(/var\(\s*(--ui-[a-zA-Z0-9-]+)/g)) names.add(match[1]!)
  return [...names].sort()
}

/** Every custom property an app's stylesheets DECLARE.
 *
 *  ⚠ Honest limit: this scans whole files, so a bridge that mapped a token
 *  ONLY inside `@media (prefers-color-scheme: dark)` would satisfy the gate
 *  while light mode rendered unstyled. Catching that needs a real CSS parser
 *  and a cascade, which is the thing no test in this repo has. Recorded
 *  rather than papered over — the bridges are one flat `:root` block each,
 *  and that shape is what makes this scan sufficient. */
function declared(app: string): Set<string> {
  const dir = join(HERE, '..', '..', app, 'src', 'styles')
  const names = new Set<string>()
  if (!existsSync(dir)) return names
  for (const file of readdirSync(dir).filter((f) => f.endsWith('.css'))) {
    const css = readFileSync(join(dir, file), 'utf8')
    for (const match of css.matchAll(/(--ui-[a-zA-Z0-9-]+)\s*:/g)) names.add(match[1]!)
  }
  return names
}

/** Where an app mounts its stylesheets. */
function entryPoint(app: string): string {
  return readFileSync(join(HERE, '..', '..', app, 'src', 'main.tsx'), 'utf8')
}

describe('the @booksnap/ui token contract', () => {
  it('names at least one token, so an empty regex cannot pass vacuously', () => {
    expect(required().length).toBeGreaterThan(0)
  })

  for (const app of APPS) {
    const dir = join(HERE, '..', '..', app)
    const present = existsSync(dir)

    it.skipIf(!present)(`app/${app} defines every --ui-* the shared sheet reads`, () => {
      const missing = required().filter((name) => !declared(app).has(name))
      expect(missing, `app/${app}/src/styles is missing: ${missing.join(', ')}`).toEqual([])
    })

    /**
     * ⚠⚠ The hole the token check left open, found by a review that executed
     * it: deleting `import '@booksnap/ui/styles/ui.css'` from the product's
     * `main.tsx` turned OFF `.rtl-safe` across the entire app — the rule
     * CLAUDE.md calls the most load-bearing in this repo's CSS — and left the
     * sort control's direction toggle falling out of its box. **Every ring
     * stayed green.** 25/25 here, 102/102 there, 9/9 for the whole gate.
     *
     * Checking the tokens and not the sheet is checking that the wiring has
     * power while nobody plugged anything in.
     */
    it.skipIf(!present)(`app/${app} actually imports the shared sheet`, () => {
      expect(entryPoint(app)).toContain('@booksnap/ui/styles/ui.css')
    })

    /**
     * Order matters and is not decoration: the sheet reads the app's `--ui-*`
     * bridge (declared in tokens.css), and an app must still be able to
     * override a rule it owns — so the shared sheet sits between the tokens
     * and the app's own components.
     */
    it.skipIf(!present)(`app/${app} imports it after its tokens`, () => {
      const source = entryPoint(app)
      const tokens = source.indexOf('styles/tokens.css')
      const shared = source.indexOf('@booksnap/ui/styles/ui.css')
      const base = source.indexOf('styles/base.css')
      expect(tokens).toBeGreaterThanOrEqual(0)
      expect(shared).toBeGreaterThan(tokens)
      expect(base).toBeGreaterThan(shared)
    })
  }
})
