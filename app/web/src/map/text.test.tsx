/**
 * The editor speaks the reader's language — checked two ways, because either
 * one alone passes on a half-translated screen.
 *
 * The port shipped `text.ts` with 17 keys defined and never read: the table
 * looked complete, every component that consulted it was in Hebrew, and the
 * floor menu, the whole settings panel, every toast and the empty state were
 * still the lab's English. A key-parity test would have passed. So:
 *
 *   - a DEAD-KEY scan, because an unread key is the shape a missed screen
 *     takes — and gated on a synthetic corpus, since against the real table
 *     the rule is unobservable once the dead keys are gone (CLAUDE.md);
 *   - a RENDER of the editor in Hebrew, because the other half of the failure
 *     is a string that was never a key at all.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import { userEvent } from '../test/user'
import { I18nProvider } from '../lib/i18n'
import MapScreen from './MapScreen'
import { newBookcase, emptyPlan } from './core/model'
import type { Plan } from './core/model'
import { TABLES, mapText } from './text'

const HERE = dirname(fileURLToPath(import.meta.url))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  globalThis.localStorage.clear()
})

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return sources(full)
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [full] : []
  })
}

/**
 * Is `key` read anywhere in `corpus`?
 *
 * ⚠ Anchored at BOTH ends. CLAUDE.md's own record of this trap: a check
 * matching `includes('t.' + key)` lets every key that is a PREFIX of another
 * ride on its longer sibling, and `lib_export` sat dead behind
 * `lib_export_csv` for months. `\b` after the name does it, because `_` is a
 * word character and `T.copy` therefore does not match inside `T.copy_edit`.
 */
const isRead = (key: string, corpus: string): boolean =>
  new RegExp(`\\bT\\.${key}\\b`).test(corpus)

describe('the map editor\'s vocabulary', () => {
  const keys = Object.keys(TABLES.he) as (keyof typeof TABLES.he)[]

  it('says the same things in both languages', () => {
    expect(Object.keys(TABLES.en).sort()).toEqual([...keys].sort())
    for (const key of keys)
      expect(typeof TABLES.en[key], key).toBe(typeof TABLES.he[key])
  })

  it('has no key nothing reads', () => {
    const corpus = sources(HERE).map((f) => readFileSync(f, 'utf8')).join('\n')
    const dead = keys.filter((key) => !isRead(key, corpus))
    expect(dead, `defined and never read: ${dead.join(', ')}`).toEqual([])
  })

  it('would notice a dead key, and would not be fooled by a longer sibling', () => {
    // The detector IS the test, so it is probed rather than trusted.
    expect(isRead('trace', 'title={T.trace_upload}')).toBe(false)
    expect(isRead('trace', 'onSelect={T.trace}')).toBe(true)
    expect(isRead('copy', 'label={T.copy_edit}')).toBe(false)
    expect(isRead('floor', 'const x = T.floor_n(2)')).toBe(false)
  })
})

// --- the screens the port left in English ---------------------------------

const HE = mapText('he')

const FLOOR = 'קומת קרקע'

const drawn = (): Plan => ({
  ...emptyPlan(),
  // As the SERVER hands it over: `PlanScreen.ensureHome` names the first
  // storey in the reader's language, and `toPlan` carries the name through.
  floors: [{ id: 'f1', name: FLOOR }],
  rooms: [{ id: 'r1', name: 'סלון', rect: { x: 0, y: 0, w: 10, h: 8 }, floorId: 'f1' }],
  cases: [newBookcase('c1', 'ארון', { x: 1, y: 0, w: 4, h: 1 }, 'S', 'r1', 'f1', 2)],
})

const openEditor = () =>
  render(
    <I18nProvider>
      <MapScreen
        initialPlan={drawn()}
        onChange={() => {}}
        saved="saved"
        onReload={() => {}}
      />
    </I18nProvider>,
  )

describe('the editor in Hebrew', () => {
  it('names its tools, its hint and its empty panel', () => {
    openEditor()
    expect(screen.getByRole('radio', { name: HE.draw_room })).toBeInTheDocument()
    expect(screen.getByText(HE.hint_arrow)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: HE.nothing_selected }))
      .toBeInTheDocument()
    // The empty state used to teach the tools in English, naming buttons that
    // are labelled in Hebrew — an instruction for a control that is not there.
    expect(screen.getByText(HE.step_room, { exact: false })).toBeInTheDocument()
  })

  it('opens the floor menu in Hebrew, and the menu has a name of its own', async () => {
    const user = userEvent.setup()
    openEditor()
    const menu = screen.getByRole('button', { name: HE.floor_menu })
    await user.click(menu)
    expect(screen.getByRole('menuitem', { name: HE.add_floor })).toBeInTheDocument()
    // ⚠ Named for THIS floor. Two controls announcing one accessible name
    // collide, and the pair left colliding last time included rename.
    expect(screen.getByRole('menuitem', { name: HE.rename_floor(FLOOR) }))
      .toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: HE.remove_floor(FLOOR) }))
      .toBeInTheDocument()
  })

  it('names a new storey in the reader\'s language, because the name is DATA', async () => {
    // ⚠ Not chrome: `addFloor` writes this string into the document, the next
    // push sends it to the server, and it stays there. The lab wrote "Floor 2"
    // and the port kept it, so a Hebrew library grew English storeys.
    const user = userEvent.setup()
    openEditor()
    await user.click(screen.getByRole('button', { name: HE.floor_menu }))
    await user.click(screen.getByRole('menuitem', { name: HE.add_floor }))
    expect(screen.getByText(HE.floor_n(2))).toBeInTheDocument()
    expect(screen.queryByText(/^Floor \d/)).not.toBeInTheDocument()
  })

  it('does not offer to throw the household\'s map away', async () => {
    // ⚠ In the lab *Clear the plan* emptied `localStorage`. Here it diffs to
    // removing every room, every bookcase and every storey — and clearing a
    // case's slots detaches the shelves books stand on. Gone, not disabled.
    const user = userEvent.setup()
    openEditor()
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    const items = screen.getAllByRole('menuitem').map((el) => el.textContent)
    expect(items).toEqual([HE.reload, HE.trace])
  })

  it('offers each drawing tool ONCE, as the button it already is', async () => {
    // The *Apartment* menu repeated *Draw room* and *Draw bookcase* under the
    // names the permanent radios already announce — two controls, one
    // accessible name, and a contradiction of the rule that shrank this
    // toolbar: a command lives in a menu, and only the tools get a button.
    const user = userEvent.setup()
    openEditor()
    for (const name of [HE.draw_room, HE.draw_case]) {
      expect(screen.getAllByRole('radio', { name })).toHaveLength(1)
      expect(screen.queryByRole('menuitem', { name })).not.toBeInTheDocument()
    }
    await user.click(screen.getByRole('button', { name: HE.menu_plan }))
    for (const name of [HE.draw_room, HE.draw_case])
      expect(screen.queryByRole('menuitem', { name })).not.toBeInTheDocument()
  })

  it('tells the truth about saving, and names no menu that is gone', () => {
    openEditor()
    const saved = screen.getByRole('status')
    expect(saved).toHaveTextContent(HE.saved)
    expect(saved.getAttribute('title')).toBe(HE.saved_hint)
    expect(saved.getAttribute('title')).not.toMatch(/Save to file/)
  })
})
