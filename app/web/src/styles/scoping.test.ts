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
 *
 * ⚠⚠ The first version of this function CLAIMED that and did not do it. It
 * split on `}` and dropped any chunk whose head began with `@` — which is the
 * chunk carrying the FIRST rule inside the block, because `@media … { .toolbar
 * {` is one chunk. A review measured it: an unscoped `.toolbar` inserted as
 * the first rule of the phone breakpoint passed. Stripping the prelude first
 * is what makes the docstring true.
 */
function selectors(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '')
  // Drop `@media (...) {` and friends, keeping what is inside them.
  const flat = withoutComments.replace(/@[a-zA-Z-]+[^{;]*\{/g, '')
  const out: string[] = []
  for (const chunk of flat.split('}')) {
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

  it('sees INSIDE a breakpoint, including its first rule', () => {
    // The scanner IS the test, so it is probed against the evasion a review
    // measured rather than trusted.
    const block = [
      '@media (max-width: 640px) {',
      '  .toolbar { gap: 5px; }',
      '  .mapscreen .brand { display: none; }',
      '}',
    ].join('\n')
    expect(selectors(block)).toEqual(['.toolbar', '.mapscreen .brand'])
    expect(selectors('@supports (a: b) { .leaky { color: red; } }'))
      .toEqual(['.leaky'])
  })

  it('counts a bare `.page` as loose, since every tab carries it', () => {
    // The exception is the PLAN tab's own class, not the page shell. Probed,
    // because a prefix test is exactly the shape that silently widens.
    const loose = (css: string) => selectors(css).filter(
      (s) => !s.startsWith('.mapscreen') && !s.startsWith('.page-plan') &&
             !s.startsWith('.page.page-plan'))
    expect(loose('.page { padding: 0; }')).toEqual(['.page'])
    expect(loose('.page-plan .mapbanner { color: red; }')).toEqual([])
    expect(loose('.page.page-plan { padding: 0; }')).toEqual([])
  })

  it('scopes every rule to the editor', () => {
    // ⚠ `.page-plan` is the ONE exception and it is deliberate: it dresses the
    // element the editor is mounted INTO — and the two surfaces that REPLACE
    // the editor, the refusal banner and the load screen — so none of them can
    // live inside `.mapscreen`. `page-plan` is a class no other screen carries
    // (`App.tsx` puts it on `<main>` for this tab only), which is what makes
    // it a scope rather than a loophole.
    const scoped = (s: string) =>
      s.startsWith('.mapscreen') ||
      s.startsWith('.page-plan') ||
      s.startsWith('.page.page-plan')
    const loose = selectors(css).filter((s) => !scoped(s))
    expect(loose, `these can match outside the editor: ${loose.join(' | ')}`)
      .toEqual([])
  })

  it('gives the drawing surface a size that fills its board rather than assuming a height', () => {
    // ⚠ jsdom lays nothing out, so this is a check on the DECLARATION — and
    // that is the right shape, because the defect was a declaration that looks
    // correct and silently does not apply: a percentage height on a REPLACED
    // element resolves against a parent with a DEFINITE height, and a flex
    // item that is merely stretched has an automatic one. `height: 100%` on
    // the `<svg>` therefore fell back to its intrinsic 150px, and the owner
    // drew on 150 of the 470px the board had given it. Measured on a phone,
    // twice — the second time because I had measured the WRAPPER and reported
    // the canvas fixed.
    const rule = css.slice(css.indexOf('.mapscreen svg.plan {'))
      .slice(0, css.slice(css.indexOf('.mapscreen svg.plan {')).indexOf('}'))
    expect(rule).toContain('position: absolute')
    expect(rule).toContain('inset: 0')
  })

  it('opens no rule on a bare element name, at any indentation', () => {
    // A second, cruder net for the same hazard, kept because it is the one
    // that catches an element selector wherever it hides: `--btn` and
    // `--input-bg` exist ONLY inside this scope, so a bare `button { … }` here
    // does not merely restyle the product's buttons — reading an undefined
    // custom property is invalid at computed-value time, and the declaration
    // resolves to `unset` rather than to the product's own rule.
    for (const line of css.split(/\r?\n/))
      expect(line).not.toMatch(/^\s*(button|input|select|fieldset|legend)[\s.:[{]/)
  })
})
