/**
 * The rules every string table in this client obeys, read from the TYPE.
 *
 * ⚠ Two guards already exist for exactly these rules — in `src/map/text.test.tsx`
 * — and both read `src/map/text.ts` and nothing else. That is the
 * enumerate-from-a-narrower-set shape CLAUDE.md records failing four times,
 * one scope up: the rule was enforced over the map's table while the app's
 * own table, the one every screen reads, had neither guard. It cost `1 books`
 * / `1 ספרים` in the most-read sentence in the product, live in both
 * languages, found by a review walking a real browser.
 *
 * This file is the same two checks over `src/lib/i18n.tsx`. It reads the
 * source rather than probing the functions, for the reason `text.test.tsx`
 * records in full: a sentinel handed to a template comes back out of EVERY
 * template, so a probe silently skips the broken ones. A parameter DECLARED
 * `number` is the declaration that it counts something.
 *
 * ⚠ This table has no separate interface — `Strings` is `typeof HE`, so the
 * types are spelled out on the Hebrew entries themselves and inferred for the
 * English ones. So the scan reads the whole file and takes a key as counted
 * if EITHER table declares it, which is also what makes a missing English
 * plural visible: the key is collected from `HE` and then applied to both.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { STRINGS } from './i18n'

const HERE = dirname(fileURLToPath(import.meta.url))
const SOURCE = readFileSync(join(HERE, 'i18n.tsx'), 'utf8')

/** Both tables, keyed by language, exactly as `useI18n` hands them out. */
const TABLES = STRINGS as unknown as Record<string, Record<string, unknown>>

describe('every counted string says ONE, in both languages', () => {
  it('never renders a bare `1 <plural>`', () => {
    // The interface is where the types are spelled out; the tables write
    // `key: (n) => …` with none.
    const counted = new Map<string, { types: string[]; names: string[]; at: number[] }>()
    for (const m of SOURCE.matchAll(/^ {4}(\w+): \(([^)]*)\) =>/gm)) {
      const parts = m[2]!.split(',').map((p) => p.trim()).filter(Boolean)
      const types = parts.map((p) => p.split(':')[1]?.trim() ?? '')
      const names = parts.map((p) => p.split(':')[0]!.trim())
      const at = types.flatMap((t, i) => (t === 'number' ? [i] : []))
      if (at.length) counted.set(m[1]!, { types, names, at })
    }
    expect(counted.size, 'no counted keys found — the interface shape moved')
      .toBeGreaterThan(2)

    // Opt-OUT, keyed `key` or `key.parameter`, one at a time and by name:
    // a number that NAMES A VALUE — an ordinal, a bound, a dimension — has no
    // noun after it to agree with. The default is CHECKED, so this list going
    // stale can only ever skip a check that would have passed.
    const nounless = new Set<string>([
      // «column 1 · level 3» — an address, not a count.
      'shelf_formerly_at.col', 'shelf_formerly_at.level',
      // «3 of 12 books»: the noun agrees with the TOTAL, not with how many
      // of them are on screen.
      'count.shown',
      // «1 not seen» / «3 not seen» — an English past participle does not
      // agree with number, so the noun this rule looks for is not there. The
      // Hebrew VERB does agree, which is why its own branch exists.
      // ⚠ A past participle does not agree with number in English — «1
      // added», «1 corrected», «1 not seen» are all correct — so there is
      // no noun for this rule to find. The HEBREW verbs DO agree, and each
      // of these keys carries its own singular branch for that reason; the
      // opt-out is per key, so that half is held by the sentences asserted
      // in `ShelfPage.test.tsx`.
      'read_unseen.n', 'read_added.n', 'read_corrected.n',
      'read_unchanged.n',
      // A parenthesised tally with no noun after it: «(3)».
      'run.n', 'approve_all.n',
      // Progress, «3/12» — both halves name a position in a run.
      'stage_reading.done', 'stage_reading.total',
      'stage_ocr.done', 'stage_ocr.total',
      'stage_matching.done', 'stage_matching.total',
    ])
    const bare: string[] = []

    for (const [lang, table] of Object.entries(TABLES)) {
      for (const [key, { types, names, at }] of counted) {
        if (nounless.has(key)) continue
        const fn = table[key] as ((...a: unknown[]) => string) | undefined
        if (typeof fn !== 'function') continue
        // ⚠ Other arguments held at 7 — the comparison below rewrites every 2
        // into a 1, so a second count sitting at 2 would be rewritten too and
        // the two strings would match whatever the singular does.
        const args = (n: number, target: number) =>
          types.map((t, i) => (t === 'number' ? (i === target ? n : 7) : 'X'))
        for (const target of at) {
          const one = fn(...args(1, target))
          const two = fn(...args(2, target))
          if (one.trim().endsWith('1')) continue
          if (nounless.has(`${key}.${names[target]}`)) continue
          if (one === two.replace(/2/g, '1'))
            bare.push(`${lang}.${key}(${names[target]}) = "${one}"`)
        }
      }
    }
    expect(bare, 'a plural with a 1 in it').toEqual([])
  })
})

describe('a sentence carrying a NAME the owner typed', () => {
  it('never begins with it, in either language', () => {
    // `unicode-bidi: plaintext` resolves a paragraph from its first strong
    // character, so a label starting with a Latin letter flips the whole
    // announcement to LTR: the Hebrew runs backwards relative to the sentence
    // and its full stop lands at the visual start.
    const named = [...new Set([...SOURCE.matchAll(
      /^ {4}(\w+): \((?:name|label|title|author): string\) =>/gm)]
      .map((m) => m[1]!))]
    expect(named.length, 'no name-carrying sentences found')
      .toBeGreaterThan(0)

    const NAME = 'ZZlatin shelf'
    for (const [lang, table] of Object.entries(TABLES)) {
      for (const key of named) {
        const fn = table[key] as ((s: string) => string) | undefined
        if (typeof fn !== 'function') continue
        const said = fn(NAME)
        expect(said.startsWith(NAME), `${lang}.${key} starts with the name`)
          .toBe(false)
        expect(said, `${lang}.${key} dropped the name`).toContain(NAME)
      }
    }
  })
})
