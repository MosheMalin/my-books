/**
 * The client test ring for the Books tab.
 *
 * Same standard as the Python rings: test what encodes a DECISION, not layout
 * and not DTO plumbing. Nothing here asserts a CSS value or a class name for
 * its own sake — only where the class IS the decision (the mixed-script rule).
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
const SAPIENS = book({ id: 'b2', title: 'Sapiens', author: 'Yuval Noah Harari',
                       status: 'approved' })
const THRONES = book({ id: 'b3', title: 'משחקי הכס', author: "ג'ורג' מרטין",
                       status: 'manual' })

describe('Books tab', () => {
  it('renders the books the server returned, with their status', async () => {
    fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    expect(await screen.findByText('היער השיכור')).toBeInTheDocument()
    expect(screen.getByText('Sapiens')).toBeInTheDocument()
  })

  it('shows how many of the total are on screen, not just the page size', async () => {
    fakeServer(Array.from({ length: 45 }, (_, i) =>
      book({ id: `b${i}`, title: `ספר ${i}` })))
    renderApp(<App />)
    // 30 loaded of 45 — a count line that said "30 books" would be a lie.
    expect(await screen.findByText(/30.*45/)).toBeInTheDocument()
  })

  it('searches on the server rather than filtering what is already loaded', async () => {
    const server = fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    await userEvent.type(screen.getByRole('searchbox'), 'Sapiens')
    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('q=Sapiens'))).toBe(true))
    // The client must not re-implement normalize(); the server owns matching.
    await waitFor(() =>
      expect(screen.queryByText('היער השיכור')).not.toBeInTheDocument())
  })

  it('disables the sort control while searching, because relevance is the order', async () => {
    fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    const sort = screen.getByRole('combobox')
    expect(sort).toBeEnabled()
    await userEvent.type(screen.getByRole('searchbox'), 'Sap')
    await waitFor(() => expect(sort).toBeDisabled())
    // Relevance has no direction to reverse either.
    expect(screen.getByRole('button', { name: 'סדר עולה' })).toBeDisabled()
  })

  it('asks the server to reverse the order, and says which way it is', async () => {
    const server = fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    await screen.findByText('היער השיכור')
    expect(server.calls.some((c) => c.includes('ascending=true'))).toBe(true)

    await userEvent.click(screen.getByRole('button', { name: 'סדר עולה' }))
    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('ascending=false'))).toBe(true))
    // The direction is only "indicated" if the control changes with it.
    expect(await screen.findByRole('button', { name: 'סדר יורד' }))
      .toBeInTheDocument()
  })

  it('gives a new sort key its own natural direction', async () => {
    // Carrying A-Z's "ascending" onto a date key answers a question nobody
    // asked: recently added, oldest first.
    const server = fakeServer([DURRELL, SAPIENS])
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    await userEvent.selectOptions(screen.getByRole('combobox'), 'recently_added')
    await waitFor(() =>
      expect(server.calls.some(
        (c) => c.includes('sort=recently_added') && c.includes('ascending=false'),
      )).toBe(true))
    expect(server.calls.some(
      (c) => c.includes('sort=recently_added') && c.includes('ascending=true'),
    )).toBe(false)
  })

  it('drops a response that arrives after its query was superseded', async () => {
    // The one race a query library would have handled for us. The unfiltered
    // list is held so it lands AFTER the search that replaced it — without the
    // request-id guard it would repaint books the user has already filtered
    // away, and they would sit there until the next keystroke.
    const server = fakeServer([DURRELL, SAPIENS])
    server.holdWhen = (url) => !url.includes('q=')
    renderApp(<App />)

    await userEvent.type(screen.getByRole('searchbox'), 'Sapiens')
    expect(await screen.findByText('Sapiens')).toBeInTheDocument()
    expect(screen.queryByText('היער השיכור')).not.toBeInTheDocument()

    server.release() // the stale, unfiltered response lands now
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByText('היער השיכור')).not.toBeInTheDocument()
    expect(screen.getByText('Sapiens')).toBeInTheDocument()
  })

  it('filters by status and lets the same chip clear itself', async () => {
    const server = fakeServer([DURRELL, SAPIENS, THRONES])
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    const chip = screen.getByRole('button', { name: 'אושר' })
    await userEvent.click(chip)
    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('status=approved'))).toBe(true))
    await waitFor(() =>
      expect(screen.queryByText('היער השיכור')).not.toBeInTheDocument())

    // A single-select filter with no way back to "all" is a trap.
    await userEvent.click(chip)
    expect(await screen.findByText('היער השיכור')).toBeInTheDocument()
  })

  it('filters to "who has my books" and back, same as any other chip', async () => {
    const lent = book({ id: 'b4', title: 'מושאל כרגע', author: 'מחבר' })
    lent.copies[0]!.lending = {
      lent_to: 'דנה', lent_at: '2026-08-01T00:00:00Z',
      due_at: null, returned_at: null, is_out: true,
    }
    const server = fakeServer([DURRELL, lent])
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    await userEvent.click(screen.getByRole('button', { name: 'מושאלים בלבד' }))
    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('lent_out=true'))).toBe(true))
    await waitFor(() =>
      expect(screen.queryByText('היער השיכור')).not.toBeInTheDocument())
    expect(screen.getByText('מושאל כרגע')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'מושאלים בלבד' }))
    expect(await screen.findByText('היער השיכור')).toBeInTheDocument()
  })

  it('filters to the duplicates-to-resolve queue and back (§5.4, P2.6)', async () => {
    const ambiguous = book({ id: 'b5', title: 'ספר שנוי במחלוקת', author: 'מחבר' })
    const server = fakeServer([DURRELL, ambiguous])
    server.openDuplicateIds.add('b5')
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    await userEvent.click(screen.getByRole('button', { name: 'כפילויות לבירור' }))
    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('duplicates=true'))).toBe(true))
    await waitFor(() =>
      expect(screen.queryByText('היער השיכור')).not.toBeInTheDocument())
    expect(screen.getByText('ספר שנוי במחלוקת')).toBeInTheDocument()

    // A single-select-feeling filter with no way back to "all" is a trap,
    // same rule as every other chip on this bar.
    await userEvent.click(screen.getByRole('button', { name: 'כפילויות לבירור' }))
    expect(await screen.findByText('היער השיכור')).toBeInTheDocument()
  })

  it('resets paging when the query changes', async () => {
    const server = fakeServer(Array.from({ length: 45 }, (_, i) =>
      book({ id: `b${i}`, title: `ספר ${i}` })))
    renderApp(<App />)
    await screen.findByText('ספר 0')

    await userEvent.type(screen.getByRole('searchbox'), 'ספר 1')
    await waitFor(() => {
      const searchCalls = server.calls.filter((c) => c.includes('q='))
      expect(searchCalls.length).toBeGreaterThan(0)
      // Every search request starts at the top; a search that inherited
      // offset=30 would silently hide its own best results.
      expect(searchCalls.every((c) => c.includes('offset=0'))).toBe(true)
    })
  })

  it('offers to clear filters from the empty state, not just a dead end', async () => {
    fakeServer([DURRELL])
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    await userEvent.type(screen.getByRole('searchbox'), 'זזזזז')
    expect(await screen.findByText('לא נמצאו ספרים')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'נסו לנקות את הסינון' }))
    expect(await screen.findByText('היער השיכור')).toBeInTheDocument()
  })
})

describe('mixed-script alignment (UI_PLAN §7.2)', () => {
  it('marks every user-generated string rtl-safe, in both views', async () => {
    // The rule that makes `Sapiens` and `משחקי הכס` share one clean edge:
    // `unicode-bidi: plaintext` for glyph order, `text-align` keyed on the
    // CONTAINER's dir. It only works if the class is actually on the strings —
    // which is what this asserts, since a missing class is invisible until
    // someone looks at a mixed-script list.
    fakeServer([SAPIENS, THRONES])
    const { container } = renderApp(<App />)
    await screen.findByText('Sapiens')

    for (const title of ['Sapiens', 'משחקי הכס']) {
      expect(screen.getByText(title)).toHaveClass('rtl-safe')
    }
    await userEvent.click(screen.getByRole('button', { name: 'רשת' }))
    await waitFor(() =>
      expect(container.querySelector('.bookgrid')).toBeInTheDocument())
    expect(screen.getByText('Sapiens')).toHaveClass('rtl-safe')
  })

  it('mirrors the document when the language switches', async () => {
    fakeServer([SAPIENS])
    renderApp(<App />)
    await screen.findByText('Sapiens')

    expect(document.documentElement.dir).toBe('rtl')
    await userEvent.click(screen.getByRole('button', { name: /English/ }))
    // The whole layout mirrors off this one attribute, because every rule
    // uses logical properties (§7.1).
    await waitFor(() => expect(document.documentElement.dir).toBe('ltr'))
    expect(screen.getByText('List')).toBeInTheDocument()
  })
})

describe('adding a book', () => {
  it('warns that a book is already there before it is submitted', async () => {
    fakeServer([DURRELL])
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    await userEvent.click(screen.getByRole('button', { name: 'הוספת ספר' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('כותרת'), 'היער השיכור')
    expect(await within(dialog).findByText('הספר כבר קיים בספרייה'))
      .toBeInTheDocument()
  })

  it('reports a 409 as "you already own it", not as a crash', async () => {
    const server = fakeServer([DURRELL])
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    await userEvent.click(screen.getByRole('button', { name: 'הוספת ספר' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('כותרת'), 'ספר חדש')
    server.failNextWith = 409
    await userEvent.click(within(dialog).getByRole('button', { name: 'הוספה' }))

    expect(await within(dialog).findByRole('alert'))
      .toHaveTextContent('הספר כבר קיים בספרייה')
  })
})
