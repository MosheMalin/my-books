/**
 * The client ring for tenancy (P3.1, §1.3/§4.1).
 *
 * The decisions worth a test here are all about the SELECTION, never about
 * how the menu looks: does the library reach the wire on every request, does
 * a switch actually reload the library's data, does a stale stored id recover
 * on its own. Each one is mutation-checked.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, screen, waitFor } from '@testing-library/react'
import { userEvent } from '../test/user'
import { App } from '../App'
import { book, fakeServer, renderApp } from '../test/harness'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  globalThis.location.hash = ''
  globalThis.localStorage.clear()
  document.documentElement.dir = 'rtl'
})

const HOME = { id: 'lib-test', label: 'משפחת מלין', role: 'admin',
               created_at: null }
const OFFICE = { id: 'lib-2', label: 'המשרד', role: 'editor',
                 created_at: null }

const A_BOOK = book({ id: 'b1', title: 'היער השיכור', author: "ג'ראלד דארל" })

describe('the library switcher', () => {
  it('names the library in the app bar', async () => {
    const server = fakeServer([A_BOOK])
    server.libraries = [HOME]
    renderApp(<App />)
    // Waited for, not read off the first render: the button exists before
    // `GET /libraries` answers, and at that point it honestly has no name yet.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'החלפת ספרייה' }))
        .toHaveTextContent('משפחת מלין'))
  })

  it('lists this account\'s libraries with their roles', async () => {
    const server = fakeServer([A_BOOK])
    server.libraries = [HOME, OFFICE]
    renderApp(<App />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'החלפת ספרייה' }))
        .toHaveTextContent('משפחת מלין'))
    await userEvent.click(screen.getByRole('button', { name: 'החלפת ספרייה' }))
    const items = await screen.findAllByRole('menuitemradio')
    expect(items.map((i) => i.textContent)).toEqual(
      ['משפחת מלין' + 'ניהול', 'המשרד' + 'עריכה'])
  })

  it('sends the selected library on EVERY request, not only some of them', async () => {
    // The bug this pins: before P3.1 `apiGet`/`send` set the header and
    // `getJson`/`getBook` did not, so a book opened in the drawer went out
    // with no tenant at all. One `headersFor` is the fix; this fails if a new
    // request helper skips it.
    //
    // Literally every one: `LibraryProvider` renders nothing until the
    // library is known, so there is no cold-start window where a screen's
    // first fetch goes out untenanted. The one exception is the tenancy
    // route itself, which is how the library becomes known.
    const server = fakeServer([A_BOOK])
    server.libraries = [HOME, OFFICE]
    renderApp(<App />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'החלפת ספרייה' }))
        .toHaveTextContent('משפחת מלין'))

    // A book the loaded list does not contain, so `useBookRecord` really goes
    // to the server — through `getBook`, the helper that used to omit it.
    globalThis.location.hash = '#/book/b404'
    await waitFor(() =>
      expect(server.tenantsFor('/books/b404').length).toBeGreaterThan(0))
    expect(server.tenantsFor('/books/b404')).toEqual(['lib-test'])

    const untenanted = server.calls.filter(
      (url, i) => !url.includes('/api/v1/libraries')
        && server.libraryHeaders[i] === null)
    expect(untenanted).toEqual([])
  })

  it('switching reloads the books under the newly chosen library', async () => {
    const server = fakeServer([A_BOOK])
    server.libraries = [HOME, OFFICE]
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    server.books = [book({ id: 'b9', title: 'ספר של המשרד' })]
    await userEvent.click(screen.getByRole('button', { name: 'החלפת ספרייה' }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /המשרד/ }))

    expect(await screen.findByText('ספר של המשרד')).toBeInTheDocument()
    expect(screen.queryByText('היער השיכור')).not.toBeInTheDocument()
    expect(server.libraryHeaders.at(-1)).toBe('lib-2')
  })

  it('remembers the choice across a reload', async () => {
    const server = fakeServer([A_BOOK])
    server.libraries = [HOME, OFFICE]
    const first = renderApp(<App />)
    await screen.findByText('היער השיכור')
    await userEvent.click(screen.getByRole('button', { name: 'החלפת ספרייה' }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /המשרד/ }))
    await waitFor(() => expect(server.libraryHeaders.at(-1)).toBe('lib-2'))
    first.unmount()

    const reopened = fakeServer([A_BOOK])
    reopened.libraries = [HOME, OFFICE]
    renderApp(<App />)
    await screen.findByText('היער השיכור')
    expect(reopened.libraryHeaders.at(-1)).toBe('lib-2')
  })

  it('recovers on its own from a stored library the account no longer has', async () => {
    // A library someone left, or a browser carrying another install's key.
    // Left selected, every request 404s and the app looks broken rather than
    // simply pointing somewhere it should not.
    globalThis.localStorage.setItem('booksnap.library', 'lib-gone')
    const server = fakeServer([A_BOOK])
    server.libraries = [HOME]
    renderApp(<App />)
    await screen.findByText('היער השיכור')
    await waitFor(() => expect(server.libraryHeaders.at(-1)).toBe('lib-test'))
    expect(globalThis.localStorage.getItem('booksnap.library')).toBe('lib-test')
  })

  it('creates a library and switches to it, because that is why you made it',
     async () => {
    const server = fakeServer([A_BOOK])
    server.libraries = [HOME]
    renderApp(<App />)
    await screen.findByText('היער השיכור')

    server.books = []
    await userEvent.click(screen.getByRole('button', { name: 'החלפת ספרייה' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '+ ספרייה חדשה' }))
    await userEvent.type(screen.getByLabelText('שם הספרייה'), 'הורים')
    await userEvent.click(screen.getByRole('button', { name: 'יצירה' }))

    await waitFor(() => expect(server.libraryHeaders.at(-1)).toBe('lib-2'))
    expect(await screen.findByRole('button', { name: 'החלפת ספרייה' }))
      .toHaveTextContent('הורים')
  })

  it('leaves a deep link behind when the library changes', async () => {
    // `#/book/<id>` names a record of the library being LEFT, so following it
    // into the new one is a guaranteed 404 — and a 404 the user did not ask
    // for reads as the switch having broken something.
    const server = fakeServer([A_BOOK])
    server.libraries = [HOME, OFFICE]
    globalThis.location.hash = '#/book/b1'
    renderApp(<App />)
    await screen.findByRole('button', { name: 'החלפת ספרייה' })
    await userEvent.click(screen.getByRole('button', { name: 'החלפת ספרייה' }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /המשרד/ }))
    expect(globalThis.location.hash).toBe('#/library')
  })

  it('puts the library in URLs the BROWSER fetches, which cannot send a header',
     async () => {
    // ⚠ The bug the switcher shipped with, found in live use the same day: an
    // `<img src>` and a download `<a href>` are built by the browser, so they
    // resolved against the DEFAULT library — and in a second library the
    // photo that had just been read rendered as an empty box.
    const server = fakeServer([A_BOOK])
    server.libraries = [HOME, OFFICE]
    renderApp(<App />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'החלפת ספרייה' }))
        .toHaveTextContent('משפחת מלין'))

    const csv = screen.getByRole('link', { name: /CSV/ })
    expect(csv).toHaveAttribute('href', expect.stringContaining('library=lib-test'))

    await userEvent.click(screen.getByRole('button', { name: 'החלפת ספרייה' }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /המשרד/ }))
    await waitFor(() =>
      expect(screen.getByRole('link', { name: /CSV/ }))
        .toHaveAttribute('href', expect.stringContaining('library=lib-2')))
  })

  it('still shows the books when the library list cannot be loaded', async () => {
    // Chrome, not content: one household with one library must not lose its
    // books because the switcher's own request failed.
    const server = fakeServer([A_BOOK])
    const realFetch = globalThis.fetch
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/api/v1/libraries')) throw new Error('offline')
      return realFetch(input, init)
    })
    renderApp(<App />)
    expect(await screen.findByText('היער השיכור')).toBeInTheDocument()
    expect(server.calls.some((c) => c.includes('/books'))).toBe(true)
  })
})
