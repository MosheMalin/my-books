/**
 * The string table, kept honest about what it still says.
 *
 * ⚠ `Strings = typeof HE` already makes a MISSING English translation a
 * compile error — that direction is covered and needs no test. The direction
 * TypeScript cannot see is the other one: a key nothing renders any more.
 *
 * Revision 4 replaced three screens, and a review counted **54 keys** left
 * behind by that and earlier rounds — three whole vocabularies (`ld_*` for a
 * detail page that became a drawer, `users_*` for a tab that became a section,
 * `bp_*` for a panel that became another). Dead strings are not inert: they
 * are what a translator translates, what a reader greps for and finds, and
 * what makes a table look like it describes a screen that no longer exists.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sources(path)
    if (!/\.tsx?$/.test(name) || name === 'i18n.tsx') return []
    return [readFileSync(path, 'utf8')]
  })
}

describe('the string table', () => {
  it('has no key that nothing renders', () => {
    const table = readFileSync(join(SRC, 'lib', 'i18n.tsx'), 'utf8')
    const he = table.slice(table.indexOf('const HE = {'),
                           table.indexOf('export type Strings'))
    const keys = [...he.matchAll(/^ {2}([a-z_0-9]+):/gm)].map((m) => m[1]!)
    expect(keys.length).toBeGreaterThan(100)

    // Read through `t.` / `ui.` on a screen, or named as a `keyof Strings`
    // literal by a control's option table (the sort keys do this).
    const code = sources(SRC).join('\n')
    const dead = keys.filter((k) =>
      !code.includes(`t.${k}`) && !code.includes(`ui.${k}`)
      && !code.includes(`'${k}'`))

    expect(dead).toEqual([])
  })
})
