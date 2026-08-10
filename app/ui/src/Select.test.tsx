/**
 * One dropdown treatment, in both applications — the owner's ask on
 * 2026-08-11, after seeing the sort control's drawn chevron next to six
 * browser-default ones.
 *
 * ⚠ The meta-test at the bottom is the one that matters. A component test only
 * proves the component; the RULE is "every `<select>` in either app goes
 * through it", and that is broken by writing a bare `<select>` in a screen
 * nobody re-reads. jsdom cannot see the chevron either way, so structure is
 * what there is to check.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Select } from './Select'
import { userEvent } from './testing/user'

const HERE = dirname(fileURLToPath(import.meta.url))

describe('Select', () => {
  it('wraps the native control, so the chevron has something to sit on', () => {
    const { container } = render(
      <Select aria-label="מיון"><option value="a">A</option></Select>,
    )
    // `.uisel` is `position: relative` and draws the chevron in `::after`;
    // without the wrapper the arrow would position against the page.
    const wrap = container.querySelector('.uisel')
    expect(wrap).toBeTruthy()
    expect(wrap?.querySelector('select')).toBe(screen.getByRole('combobox'))
  })

  it('forwards every select prop, so it is a drop-in', async () => {
    const onChange = vi.fn()
    render(
      <Select aria-label="סטטוס" value="b" onChange={onChange}>
        <option value="a">A</option>
        <option value="b">B</option>
      </Select>,
    )
    const select = screen.getByRole('combobox', { name: 'סטטוס' })
    expect(select).toHaveValue('b')
    await userEvent.selectOptions(select, 'a')
    expect(onChange).toHaveBeenCalled()
  })

  it('only fills its container when asked', () => {
    const { container, rerender } = render(
      <Select aria-label="x"><option value="a">A</option></Select>,
    )
    expect(container.querySelector('.uisel')?.className).toBe('uisel')
    rerender(<Select wide aria-label="x"><option value="a">A</option></Select>)
    // The product's base sheet says `select { width: 100% }`, so an intake row
    // needs the wrapper to stretch too or the control shrinks to its content.
    expect(container.querySelector('.uisel')?.className).toBe('uisel wide')
  })
})

/** Every `.tsx` under a client's `src`, skipping tests. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return sources(full)
    return /\.tsx$/.test(name) && !/\.test\.tsx$/.test(name) ? [full] : []
  })
}

/**
 * ⚠ Comments stripped BEFORE scanning, and this is not defensive tidiness —
 * it fired immediately. `LibrarySwitcher.tsx` opens with *"⚠ A button and a
 * panel, not a `<select>`"*, which is a note explaining why that screen
 * deliberately has no dropdown. Flagging it would have been the boundary
 * test's own lesson repeated: a scan over source text must look at CODE, or
 * the most carefully documented file in the repo is the first false positive.
 */
function code(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')  // block and JSDoc comments
    .replace(/^[ \t]*\/\/.*$/gm, '')   // whole-line // comments
}

const BARE_SELECT = /<select[\s>]/

describe('every dropdown in both apps goes through it', () => {
  for (const app of ['web', 'admin'] as const) {
    const src = join(HERE, '..', '..', app, 'src')

    it(`app/${app} writes no bare <select>`, () => {
      const bare = sources(src).filter((file) =>
        BARE_SELECT.test(code(readFileSync(file, 'utf8'))),
      )
      expect(
        bare,
        `these render a browser-default dropdown instead of <Select>: ${bare.join(', ')}`,
      ).toEqual([])
    })

    it(`app/${app} actually renders dropdowns, so the scan is not vacuous`, () => {
      const withSelect = sources(src).filter((file) =>
        /<Select[\s>]/.test(code(readFileSync(file, 'utf8'))),
      )
      expect(withSelect.length).toBeGreaterThan(0)
    })
  }

  it('would notice a bare one — the pattern is probed, not trusted', () => {
    expect(BARE_SELECT.test(code('  <select value={x}>'))).toBe(true)
    expect(BARE_SELECT.test(code('  <select>'))).toBe(true)
    expect(BARE_SELECT.test(code('  <Select value={x}>'))).toBe(false)
    // The two shapes that had to stop being false positives. ⚠ Written as
    // WHOLE comments, because that is what `code()` strips — a lone ` * …`
    // line is not a comment to a parser, and probing one would assert a
    // property the function does not have (the first version did, and failed
    // honestly rather than passing on a technicality).
    expect(BARE_SELECT.test(code('/**\n * not a `<select>` here\n */'))).toBe(false)
    expect(BARE_SELECT.test(code('  // not a <select>'))).toBe(false)
  })
})
