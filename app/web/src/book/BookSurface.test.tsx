/**
 * The book surface: one renderer, two mounts (UI_PLAN §5).
 *
 * The tests that matter here are the ones that would let the two mounts drift
 * apart, or that would let a destructive action do the wrong thing.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from '../App'
import { book, fakeServer, renderApp } from '../test/harness'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  globalThis.location.hash = ''
  // The language choice persists (that is the point of it), and jsdom keeps
  // localStorage across tests in a file — so without this, every test after
  // the mirroring one starts in English and looks for the wrong strings.
  globalThis.localStorage.clear()
  document.documentElement.dir = 'rtl'
})

const DURRELL = book({ id: 'b1', title: 'היער השיכור', author: "ג'ראלד דארל" })
const SAPIENS = book({ id: 'b2', title: 'Sapiens', author: 'Yuval Noah Harari' })

async function openDrawer(title = 'היער השיכור') {
  await userEvent.click(await screen.findByText(title))
  return screen.getByRole('dialog', { name: 'פרטי הספר' })
}

describe('the drawer', () => {
  it('opens over the list without navigating', async () => {
    fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    const drawer = await openDrawer()

    expect(within(drawer).getByRole('heading', { name: 'היער השיכור' }))
      .toBeInTheDocument()
    // The list is still there behind it — the drawer is an overlay, and it is
    // deliberately not a route, so Back leaves the tab rather than closing it.
    expect(screen.getByText('Sapiens')).toBeInTheDocument()
    expect(globalThis.location.hash).not.toContain('book')
  })

  it('closes on Escape and returns focus to the row that opened it', async () => {
    // The mock has no focus handling at all. Losing focus to <body> means a
    // keyboard user starts the whole page again.
    fakeServer([DURRELL])
    renderApp(<App />)
    const row = await screen.findByText('היער השיכור')
    await userEvent.click(row)
    await screen.findByRole('dialog')

    await userEvent.keyboard('{Escape}')
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(document.activeElement).toBe(row.closest('button'))
  })

  it('promotes to the deep-linkable full page and closes itself doing it', async () => {
    fakeServer([DURRELL])
    renderApp(<App />)
    const drawer = await openDrawer()

    await userEvent.click(within(drawer).getByRole('button', { name: /פתיחה/ }))
    await waitFor(() => expect(globalThis.location.hash).toBe('#/book/b1'))
    // Two live copies of one surface would be two focus traps over one page.
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'היער השיכור' }))
      .toBeInTheDocument()
  })

  it('does not pop back open when the user returns from the full page', async () => {
    // Promoting must CLEAR the drawer, not just hide it behind the route.
    // Otherwise Back lands on the list with the drawer still over it — the
    // user asked to leave the book, and got it back.
    fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    const drawer = await openDrawer()
    await userEvent.click(within(drawer).getByRole('button', { name: /פתיחה/ }))
    await waitFor(() => expect(globalThis.location.hash).toBe('#/book/b1'))

    await userEvent.click(screen.getByRole('button', { name: /חזרה/ }))
    await waitFor(() => expect(screen.getByText('Sapiens')).toBeInTheDocument())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('one renderer, two mounts', () => {
  it('offers the same actions on the full page as in the drawer', async () => {
    // If these ever diverge it is invisible until someone reports that editing
    // works in one place and not the other.
    fakeServer([DURRELL])
    renderApp(<App />)
    const drawer = await openDrawer()
    const inDrawer = within(drawer).getAllByRole('button').map((b) => b.textContent)

    globalThis.location.hash = '#/book/b1'
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await screen.findByRole('heading', { name: 'היער השיכור' })
    const onPage = screen.getAllByRole('button').map((b) => b.textContent)

    for (const label of ['עריכה', 'מחיקה מהספרייה']) {
      expect(inDrawer.some((x) => x?.includes(label))).toBe(true)
      expect(onPage.some((x) => x?.includes(label))).toBe(true)
    }
  })

  it('reaches a book by deep link that was never in the loaded list', async () => {
    fakeServer([DURRELL])
    globalThis.location.hash = '#/book/b1'
    renderApp(<App />)
    expect(await screen.findByRole('heading', { name: 'היער השיכור' }))
      .toBeInTheDocument()
  })

  it('says so when a deep link names no book', async () => {
    fakeServer([DURRELL])
    globalThis.location.hash = '#/book/nope'
    renderApp(<App />)
    expect(await screen.findByText('הספר לא נמצא')).toBeInTheDocument()
  })
})

describe('editing', () => {
  it('marks the book manual and repaints the list behind it', async () => {
    // "Edit it anywhere, it changes everywhere" (§5): one record, two mounts,
    // and the list behind them reading the same thing.
    fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    const drawer = await openDrawer()

    await userEvent.click(within(drawer).getByRole('button', { name: 'עריכה' }))
    const title = within(drawer).getByLabelText('כותרת')
    await userEvent.clear(title)
    await userEvent.type(title, 'היער השיכור (מתוקן)')
    await userEvent.click(within(drawer).getByRole('button', { name: 'שמירה' }))

    expect(await within(drawer).findByText('נשמר')).toBeInTheDocument()
    expect(within(drawer).getByText('ידני')).toBeInTheDocument()
    // The row behind the drawer, not just the drawer.
    await waitFor(() =>
      expect(screen.getAllByText('היער השיכור (מתוקן)').length)
        .toBeGreaterThan(1))
  })

  it('keeps the text on screen when a rename collides with a book you own', async () => {
    // 409 is a normal answer, not a crash: resolving it (merge? keep both?)
    // is a decision nobody has made, so the edit is refused and nothing is
    // silently thrown away.
    const server = fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    const drawer = await openDrawer()

    await userEvent.click(within(drawer).getByRole('button', { name: 'עריכה' }))
    const title = within(drawer).getByLabelText('כותרת')
    await userEvent.clear(title)
    await userEvent.type(title, 'Sapiens')
    server.failNextWith = 409
    await userEvent.click(within(drawer).getByRole('button', { name: 'שמירה' }))

    expect(await within(drawer).findByRole('alert'))
      .toHaveTextContent('כבר יש ספר כזה בספרייה')
    expect(within(drawer).getByLabelText('כותרת')).toHaveValue('Sapiens')
  })

  it('abandons a half-finished edit when another book takes the mount', async () => {
    fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    const drawer = await openDrawer()
    await userEvent.click(within(drawer).getByRole('button', { name: 'עריכה' }))
    await userEvent.type(within(drawer).getByLabelText('כותרת'), 'xxx')

    await userEvent.click(screen.getByText('Sapiens'))
    // Carrying one book's typing onto another is how you rename the wrong book.
    await waitFor(() =>
      expect(within(drawer).getByRole('heading', { name: 'Sapiens' }))
        .toBeInTheDocument())
    expect(within(drawer).queryByLabelText('כותרת')).not.toBeInTheDocument()
  })
})

describe('the destructive actions', () => {
  it('confirms before deleting from the library', async () => {
    const server = fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    const drawer = await openDrawer()

    await userEvent.click(
      within(drawer).getByRole('button', { name: 'מחיקה מהספרייה' }))
    expect(within(drawer).getByText(/למחוק את הספר/)).toBeInTheDocument()
    expect(server.books).toHaveLength(2) // nothing yet

    await userEvent.click(within(drawer).getByRole('button', { name: 'מחקו' }))
    await waitFor(() => expect(server.books).toHaveLength(1))
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() =>
      expect(screen.queryByText('היער השיכור')).not.toBeInTheDocument())
  })

  it('offers no "remove from shelf" while there are no shelves', async () => {
    // UI_PLAN §5 keeps the two destructive actions deliberately separate.
    // Until P2.1 there is no shelf to remove from, so the control is ABSENT —
    // a greyed-out button that never becomes clickable reads as a bug.
    fakeServer([DURRELL])
    renderApp(<App />)
    const drawer = await openDrawer()
    expect(within(drawer).queryByText(/מדף/)).not.toBeInTheDocument()
  })
})

describe('the author chip', () => {
  it('filters the list to that author and shows their real name', async () => {
    // §5.1: authors are strings, not entities. The chip filters on the
    // NORMALIZED key but must never show it — that would read as a typo.
    const server = fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    const drawer = await openDrawer()

    await userEvent.click(within(drawer).getByRole('button', { name: "ג'ראלד דארל" }))
    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('author_key='))).toBe(true))
    await waitFor(() =>
      expect(screen.queryByText('Sapiens')).not.toBeInTheDocument())
    // The chip in the filter bar, not the author link inside the drawer.
    const bar = document.querySelector('.filterbar') as HTMLElement
    expect(within(bar).getByRole('button', { name: /ג'ראלד דארל/ }))
      .toBeInTheDocument()
  })
})
