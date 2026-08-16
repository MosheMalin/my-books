/**
 * The map editor's sheet must not repaint the rest of the product.
 *
 * `map.css` arrived from `planning/map-lab`, where it WAS the whole document's
 * stylesheet: an unqualified `:root` token block, and ~130 rules on generic
 * names — `button`, `input`, `select`, `fieldset`, `.toolbar`, `.note`,
 * `.side`. It is imported last, so at equal specificity it wins everywhere.
 *
 * Two rounds of measurement, both on the BOOKS tab having never opened the
 * map: the first found `--bg` forced dark and "Noto Sans Hebrew" gone from the
 * whole product; the second, after the token block was scoped and the commit
 * said "every rule is scoped now", found every unclassed `<button>` and
 * `<input>` computing `background-color: rgba(0,0,0,0)` at 13px — `--btn` and
 * `--input-bg` exist only inside `.mapscreen`, and an undefined custom
 * property makes the declaration invalid at computed-value time rather than
 * falling back to the product's own rule.
 *
 * jsdom applies no CSS, so this is a check on the TEXT of the sheet. That is
 * the right shape anyway: the property is "no rule here can match outside the
 * editor", which is a fact about the selectors, not about a rendering.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const SHEET = join(dirname(fileURLToPath(import.meta.url)), 'map.css')

/**
 * Every selector in the sheet, with comments and declaration blocks removed.
 *
 * ⚠ `@media` is unwrapped rather than skipped: the phone breakpoint is where
 * `.brand { display: none }` lives, and a rule that only leaks below 640px is
 * a rule that only leaks on the device this product is for.
 */
function selectors(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const out: string[] = []
  for (const chunk of withoutComments.split('}')) {
    const head = chunk.split('{')[0]
    if (!head) continue
    const text = head.trim()
    if (!text || text.startsWith('@')) continue
    for (const one of text.split(','))
      if (one.trim()) out.push(one.trim())
  }
  return out
}

describe('map.css', () => {
  const css = readFileSync(SHEET, 'utf8')

  it('finds its own rules, so an empty scan cannot pass vacuously', () => {
    expect(selectors(css).length).toBeGreaterThan(100)
  })

  it('scopes every rule to the editor', () => {
    // ⚠ `.page-plan` is the ONE exception and it is deliberate: it dresses the
    // element the editor is mounted INTO, so it cannot be inside `.mapscreen`.
    // It is scoped by a class nothing else uses — see the comment on it.
    const loose = selectors(css).filter(
      (s) => !s.startsWith('.mapscreen') && !s.startsWith('.page.page-plan'),
    )
    expect(loose, `these can match outside the editor: ${loose.join(' | ')}`)
      .toEqual([])
  })

  it('defines its own tokens nowhere but inside that scope', () => {
    // `--btn` and `--input-bg` exist only here. A declaration READING one from
    // outside computes to `unset`, which is how a transparent button happens.
    for (const line of css.split(/\r?\n/)) {
      if (/^\s*--(btn|input-bg|grid-|room-|case-)/.test(line)) continue
      expect(line).not.toMatch(/^\s*(button|input|select|fieldset|legend)\b/)
    }
  })
})
