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
    // ⚠ Comments stripped first, like `selectors()` above already does. This
    // one did not, and it fired on a PROSE line whose wrapped text happened to
    // begin with the word "select" — a guard reporting a defect in an
    // explanation of a rule. Nothing real can hide inside `/* */`, so the
    // strip costs it no reach; the crudeness that makes it valuable is the
    // indentation-blindness, not the comment-blindness.
    const bare = css.replace(/\/\*[\s\S]*?\*\//g, '')
    for (const line of bare.split(/\r?\n/))
      expect(line).not.toMatch(/^\s*(button|input|select|fieldset|legend)[\s.:[{]/)
  })
})

describe('the plan is a workspace, and a workspace needs a definite height', () => {
  // jsdom applies no CSS, so this is a check on the TEXT — the same shape the
  // scoping checks above use, and the right one: the property is "these four
  // declarations exist", which is a fact about the sheet.
  //
  // ⚠ It exists because a UX review measured the plan canvas at 375x0 on a
  // phone. `#root` had `min-height: 100%` — a MINIMUM is not a definite
  // height, so the phone block's `flex: 0 0 38%` on `.map-side` resolved
  // against `auto` and became the panel's CONTENT height (1155px for a
  // 52-cell elevation). The settings panel was the entire page, and
  // `elementFromPoint` over a bookcase returned a fold header. Nothing in
  // pillar 6 had ever been walked on a phone, including the verification of
  // the item that shipped just before this one.
  const books = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'books.css'), 'utf8')
  const map = readFileSync(SHEET, 'utf8')

  it('gives the plan shell a definite height, not a minimum', () => {
    // ⚠ Asserted on the whole sheet, not on a slice of the rule. The first
    // cut sliced from the selector to the next closing brace — and a brace
    // inside a COMMENT ended the slice early, so the assertion read a
    // fragment that could not contain the declaration either way: it passed
    // clean AND it passed mutated, which is the definition of not a gate.
    // `books.css` declares this height exactly once, so the file is the
    // honest scope.
    expect(books.match(/^ {2}(?:min-)?height: 100%;/gm),
      'the plan shell declares its height exactly once, and not as a minimum')
      .toEqual(['  height: 100%;'])
  })

  it('lets both panes shrink below their content, on both axes', () => {
    // A flex item defaults to `min-*: auto` — min-CONTENT — so without these
    // the canvas cannot shrink and the panel cannot scroll; it grows instead.
    expect(map).toMatch(/\.canvas-wrap \{[^}]*min-height: 0/)
    expect(map).toMatch(/\.map-side \{[^}]*min-width: 0/)
    const phone = map.slice(map.indexOf('@media (max-width: 640px)'))
    // Bounded by the NEXT media query rather than by a closing brace, so the
    // assertion cannot be satisfied by a `min-height: 0` somewhere else in
    // the sheet — and so this file needs no newline literal, which is what
    // broke its first cut.
    const next = phone.indexOf('@media', 1)
    expect(next > 0 ? phone.slice(0, next) : phone, 'the stacked panel must scroll')
      .toMatch(/min-height: 0/)
  })

  it('makes the thumb-sized rules actually win', () => {
    // ⚠ They did not: equal specificity, and the base `.mapscreen .elev-cell`
    // comes LATER in the sheet, so the phone block's 40px lost to 30px while
    // a comment above it recorded the review that added it. The doubled class
    // is what makes it a real override — and the elevation cell is the hole,
    // which is the only way back from a gap.
    const phone = map.slice(map.indexOf('@media (max-width: 640px)'))
    expect(phone).toContain('.elev-cell.elev-cell')
  })

  it('puts the panel-wide touch floor after every rule it has to beat', () => {
    // ⚠ P6.5a replaced three named 40px rules with ONE 44px floor over the
    // whole panel, and the first cut wrote it inside the layout breakpoint
    // two thirds up the sheet — where it lost, at equal specificity, to eight
    // later rules that size the very controls it was added for
    // (`.section-head button` 26px, `.elev-col-foot button` 26px,
    // `.section-defaults` 28px). Same lesson as the test above, one rule
    // along, which is why this one asserts the ORDER rather than a string:
    // a floor is only a floor if nothing after it says otherwise.
    // ⚠ ONE string for both sides of the comparison. The first cut took
    // `floor` from the raw sheet and each rule's position from
    // `map.indexOf(rule[0])` on the comment-STRIPPED text — and `[^{}]+`
    // starts a selector immediately after the previous `}`, so any rule with
    // a comment in that gap does not occur verbatim in the raw sheet,
    // `indexOf` answers -1, and `-1 > floor` silently drops it. A review
    // measured it: the misordering this test exists for reports 6 offenders,
    // and reports ONE once a single comment line sits above each. `map.css`
    // is 45% comment by byte and prose above a rule is this sheet's house
    // style, so the guard was passing on luck. `matchAll` already hands back
    // the index, in the coordinates of the string it scanned.
    const bare = map.replace(/\/\*[\s\S]*?\*\//g, '')
    const floor = bare.lastIndexOf('.map-side.map-side')
    expect(floor, 'no doubled panel-wide floor in map.css')
      .toBeGreaterThan(0)

    // Every pixel min-height the sheet sets on a control INSIDE the panel.
    // Anything below the floor that is declared after it wins over it.
    const later: string[] = []
    for (const rule of bare.matchAll(
      /([^{}]+)\{([^{}]*min-height:\s*(\d+)px[^{}]*)\}/g)) {
      const at = rule[1]!.trim().replace(/\s+/g, ' ')
      if (at.includes('.map-side.map-side')) continue
      if (!/(button|input|select)\b/.test(at)) continue
      if (Number(rule[3]) >= 44) continue
      // `.floor-badge` sits over the CANVAS, not in the panel, and has its
      // own 44px phone override; `.readonly-bar` likewise.
      if (/floor-badge|readonly-bar/.test(at)) continue
      if (rule.index > floor) later.push(`${at} — ${rule[3]}px`)
    }
    expect(later, 'declared after the floor, so they beat it').toEqual([])
  })
})
