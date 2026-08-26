/**
 * The 44px touch floor, read from the SHEETS rather than from a list.
 *
 * ⚠ This guard exists because the previous answer to "37 of 96 controls are
 * under the floor" was three named rules at **40px** — a number chosen once,
 * per control, as each was noticed. Forty looks like a fix and is not the
 * floor, and nothing in the ring could tell the difference: jsdom applies no
 * CSS, so the only other evidence is a browser somebody remembers to open.
 *
 * The rule enumerated here is the CLASS — *every* pixel height a phone
 * breakpoint puts on anything, minus a named list of things nobody presses —
 * not the handful that were measured. That is the same correction CLAUDE.md
 * records for the dead-key scan, the counted strings and the 404 meta-test: a
 * guard that enumerates from a list stops watching the moment the source
 * grows. Both halves of that were got wrong here first and fixed by mutating
 * the sheet, which is written down beside each one.
 *
 * What it CANNOT see, stated so nobody reads a green board as proof: a control
 * with no pixel height at all, sized by padding and a font — most of them.
 * Those are found by measuring a real browser at 375x812, which is what every
 * item in pillar 6 does before it claims a flow works.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const HERE = dirname(fileURLToPath(import.meta.url))
/**
 * Every sheet that can size a control this client renders — including the
 * SHARED one, which is consumed as source and whose `.sortdir` is the
 * smallest control in the product. A guard that stopped at this package's own
 * directory would be the enumerate-from-a-narrower-set failure one scope up,
 * which is exactly how `1 books` reached both languages.
 */
const SHEETS = [
  ...['map.css', 'books.css', 'shelf.css', 'capture.css'].map(
    (name) => [name, join(HERE, name)] as const),
  ['@booksnap/ui — ui.css', join(HERE, '../../../ui/src/styles/ui.css')] as const,
].map(([name, path]) => [name, readFileSync(path, 'utf8')] as const)

/** The floor itself. A phone's finger does not care which sheet it lands in. */
const FLOOR = 44

/**
 * Selectors that are NOT pressed, and may therefore be any height.
 *
 * ⚠ The polarity is the whole design. The first version asked "does this
 * selector look like a control?" and matched `button`, `input`, `select` and
 * a handful of class names — so `.sortdir`, which IS a `<button>` but whose
 * selector never says so, was invisible, and dropping the smallest control in
 * the product to 43px passed. Enumerating the watched set from a LIST is the
 * failure CLAUDE.md records four times over; here the list is the EXEMPTIONS,
 * so anything new is watched by default and the worst a stale entry can do is
 * skip a check that would have passed.
 */
const NOT_PRESSED = [
  // The panel itself, the scroll boxes and the plan workspace: containers.
  /^\.(map-side|body|canvas-wrap|elev-scroll|page|mapscreen)$/,
  // Overlays and labels — a toast, a hint, the storey caption, a note.
  /^\.(toast|hint|floor-badge|saved|brand|note)$/,
]

/**
 * Whether a rule sizes something a finger presses.
 *
 * ⚠ The exemption is matched against the LAST SIMPLE SELECTOR, anchored at
 * both ends, and every comma-part has to be exempt for the rule to be. The
 * first version tested the whole selector with unanchored patterns, and a
 * review measured what that let through: `.floor-badge` in the list exempted
 * `.mapscreen .floor-badge .menu > button` — the storey chevron, which
 * `map.css`'s own comment calls *"two bare chevrons 47px apart, one of which
 * changes the whole board"*, and which THIS commit had just raised from 40 to
 * 44. Reverting it stayed green. `\b` ends a word at a hyphen too, so
 * `.note-field` and `.brand-btn` were exempt as well, and `.note button` — a
 * container in the list swallowing every control inside it.
 *
 * Same shape as the dead-key scan CLAUDE.md records: anchor both ends, or
 * every name that CONTAINS an exempt one rides along.
 */
function isPressed(selector: string): boolean {
  const parts = selector.split(',').map((p) => p.trim()).filter(Boolean)
  if (parts.length === 0) return false
  return !parts.every((one) => {
    const last = one.split(/[\s>+~]+/).filter(Boolean).pop() ?? ''
    return NOT_PRESSED.some((skip) => skip.test(last))
  })
}

/**
 * Every pixel HEIGHT a max-width media block gives a selector — `height` and
 * `min-height` alike, with the selector that carries it.
 *
 * ⚠ `min-height` alone was the first version, and it was measurably blind:
 * the shared sort toggle is absolutely positioned and sizes itself with a
 * plain `height`, so dropping it to 43px passed. The docstring above already
 * claimed this file watched that sheet — the CLAUDE.md failure of a comment
 * promising a guard — which is how the hole was found, by mutating the sheet
 * the comment named.
 */
function floorsInPhoneBlocks(css: string): { at: string; px: number }[] {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const found: { at: string; px: number }[] = []
  const media = /@media[^{]*max-width[^{]*\{/g
  let opener: RegExpExecArray | null
  while ((opener = media.exec(clean)) !== null) {
    // Walk to this block's matching brace; a media block contains rule blocks,
    // so counting is the only way to find its end.
    let depth = 1
    let i = opener.index + opener[0].length
    const from = i
    while (i < clean.length && depth > 0) {
      if (clean[i] === '{') depth += 1
      else if (clean[i] === '}') depth -= 1
      i += 1
    }
    const inner = clean.slice(from, i - 1)
    for (const rule of inner.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const at = rule[1]!.trim().replace(/\s+/g, ' ')
      for (const decl of rule[2]!.matchAll(
        /(?:^|[;{\s])(?:min-)?(?:block-size|height):\s*(\d+(?:\.\d+)?)(px|rem)/g)) {
        // ⚠ `rem` as well as `px`, and `block-size` as well as `height`. Both
        // were holes a review found by injection: `min-height: 2rem` (32px)
        // and `min-block-size: 20px` both passed, and this repo is already
        // writing logical properties (`inset-inline`, `padding-inline-start`)
        // in these very sheets. 16px is the root size these apps never change.
        found.push({ at, px: Number(decl[1]) * (decl[2] === 'rem' ? 16 : 1) })
      }
    }
  }
  return found
}

/**
 * Sheets that MUST contribute at least one watched declaration.
 *
 * ⚠ A per-sheet floor rather than one total, because a total hides a sheet
 * going dark. A review instrumented the first version: it watched six
 * declarations against a threshold of `> 2`, so `map.css` could have gone
 * entirely blind and the test would still have passed — and deleting the
 * whole shared-sheet phone block left it green. These three are the sheets
 * that carry a phone floor today; a sheet that stops carrying one is a
 * deliberate change and belongs in this list's diff.
 */
const MUST_WATCH = ['map.css', 'books.css', '@booksnap/ui — ui.css']

describe('a control a phone has to press', () => {
  it('is never given a min-height below the touch floor', () => {
    const offenders: string[] = []
    const watched = new Map<string, number>()
    for (const [name, css] of SHEETS) {
      for (const { at, px } of floorsInPhoneBlocks(css)) {
        if (!isPressed(at)) continue
        watched.set(name, (watched.get(name) ?? 0) + 1)
        if (px < FLOOR) offenders.push(`${name}: ${at} — ${px}px`)
      }
    }
    // A parser that quietly matches nothing reports every sheet as perfect.
    for (const name of MUST_WATCH)
      expect(watched.get(name) ?? 0,
             `${name}: nothing watched — the parser stopped seeing it`)
        .toBeGreaterThan(0)
    expect(offenders, `under ${FLOOR}px`).toEqual([])
  })
})
