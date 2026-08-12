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

/**
 * Which of `keys` nothing in `code` renders.
 *
 * A key counts as rendered when it is read through `t.` / `ui.` on a screen,
 * or named as a `keyof Strings` literal by a control's option table (the sort
 * keys do this).
 *
 * ⚠⚠ **ANCHORED AT BOTH ENDS, and that is the whole rule.** This was
 * `code.includes('t.' + k)`, a bare substring test, so every key that is a
 * PREFIX of another key passed on its longer sibling's back. Two were dead
 * that way and this test — whose entire job is finding dead keys — reported
 * both as rendered: `acc_account` rode on `t.acc_account_admin` from the day
 * that key was added, and `lib_export` rode on `t.lib_export_csv`. Tightening
 * the boundary at P3.7e is what surfaced them.
 *
 * Extracted from the test below so the boundary itself can be exercised
 * against a corpus that HAS a shadowed key. Against the real table it cannot
 * be: once the two dead keys are deleted, loosening the check back to a
 * substring passes — measured. A rule only observable when it is already
 * broken is a rule with no gate on it.
 */
export function deadKeys(keys: string[], code: string): string[] {
  const rendered = (k: string) =>
    new RegExp(`(?:\\bt|\\bui)\\.${k}\\b|'${k}'`).test(code)
  return keys.filter((k) => !rendered(k))
}

describe('the dead-key detector', () => {
  it('does not let a key ride on a longer key that starts with it', () => {
    // The exact shape that hid `acc_account` behind `acc_account_admin`.
    expect(deadKeys(['acc_account', 'acc_account_admin'],
                    'const x = t.acc_account_admin'))
      .toEqual(['acc_account'])
  })

  it('counts a key read through t., ui., or a keyof literal', () => {
    expect(deadKeys(['a', 'b', 'c'], 't.a; ui.b; const s: keyof Strings = \'c\''))
      .toEqual([])
  })

  /** ⚠ `t.foo` must not be satisfied by `notT.foo`: the boundary goes on BOTH
   *  sides, or a member of some other object named the same thing counts. */
  it('does not count a lookalike on another object', () => {
    expect(deadKeys(['foo'], 'const x = other.foo')).toEqual(['foo'])
  })
})

describe('the string table', () => {
  it('has no key that nothing renders', () => {
    const table = readFileSync(join(SRC, 'lib', 'i18n.tsx'), 'utf8')
    const he = table.slice(table.indexOf('const HE = {'),
                           table.indexOf('export type Strings'))
    const keys = [...he.matchAll(/^ {2}([a-z_0-9]+):/gm)].map((m) => m[1]!)
    expect(keys.length).toBeGreaterThan(100)

    expect(deadKeys(keys, sources(SRC).join('\n'))).toEqual([])
  })
})
