/**
 * The sign-in flow (P4.1b): the login screen replaces the whole tree on a
 * 401, the emailed link redeems on #/login?token=…, sign-out returns to
 * the screen. Each test drives the REAL fetch layer against the fake
 * server — never a mocked hook (the harness rule).
 */
import { cleanup, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { SIGNED_OUT_EVENT } from '../api/client'
import { App } from '../App'
import { fakeServer, renderApp } from '../test/harness'
import userEvent from '../test/user'
import { parseHash } from './route'

afterEach(cleanup)

describe('sign-in (P4.1b)', () => {
  it('boots straight to the login screen when the server answers 401', async () => {
    const server = fakeServer()
    server.signedOut = true
    renderApp(<App />)
    // The first request (the library list) 401s; the login screen replaces
    // the tree rather than rendering a broken app over an error state.
    expect(
      await screen.findByRole('form', { name: 'כניסה' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Switch to English' })).toBeNull()
  })

  it('asks for a link and says it may be on its way', async () => {
    const server = fakeServer()
    server.signedOut = true
    renderApp(<App />)
    const input = await screen.findByLabelText('אימייל')
    // An email is a Latin-script string: the input is LTR inside the RTL
    // page — direction per string, the .rtl-safe rule's other half.
    expect(input).toHaveAttribute('dir', 'ltr')
    await userEvent.type(input, ' Moshe@Example.COM ')
    await userEvent.click(screen.getByRole('button', { name: 'שליחת קישור' }))

    await screen.findByText(
      'אם הכתובת יכולה להיכנס לכאן, קישור בדרך אליה. פתחו אותו מהמכשיר הזה.',
    )
    // The address goes out as typed; normalization is the SERVER's rule
    // (one copy), and the fake recorded what the wire carried.
    expect(server.linkRequests).toHaveLength(1)
  })

  it('redeems the emailed link and boots the app', async () => {
    const server = fakeServer()
    server.signedOut = true
    // The shape the ConsoleMailer emits (LINK_PATH in console_mailer.py):
    // this hash IS the contract between the mail and this client.
    location.hash = `#/login?token=${server.validToken}`
    renderApp(<App />)
    expect(
      await screen.findByRole('button', { name: 'Switch to English' }),
    ).toBeInTheDocument()
    expect(location.hash).toBe('#/library')
  })

  it('shows the one honest sentence when the link is dead', async () => {
    const server = fakeServer()
    server.signedOut = true
    location.hash = '#/login?token=already-used'
    renderApp(<App />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(
      'הקישור פג תוקף או שכבר נוצל — בקשו קישור חדש.',
    )
  })

  it('signs out to the login screen and revokes server-side', async () => {
    const server = fakeServer()
    renderApp(<App />)
    await screen.findByRole('button', { name: 'Switch to English' })
    await userEvent.click(screen.getByRole('button', { name: 'התנתקות' }))

    expect(
      await screen.findByRole('form', { name: 'כניסה' }),
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(
        server.calls.some((c) => c.includes('/api/v1/auth/session')),
      ).toBe(true),
    )
    expect(server.signedOut).toBe(true)
  })

  it('a 401 mid-session replaces the app with the login screen', async () => {
    fakeServer()
    renderApp(<App />)
    await screen.findByRole('button', { name: 'Switch to English' })
    // The fetch layer fires this on ANY 401 — the provider's contract is
    // with the event, and the boot test above covers the wire end of it.
    globalThis.dispatchEvent(new Event(SIGNED_OUT_EVENT))
    expect(
      await screen.findByRole('form', { name: 'כניסה' }),
    ).toBeInTheDocument()
  })
})

describe('the login route', () => {
  it('keeps its token where every other route strips the query', () => {
    // The mail's link shape (console_mailer.LINK_PATH + token). The
    // general parse rule eats `?…`; the login route must not.
    expect(parseHash('#/login?token=abc')).toEqual({
      name: 'login',
      token: 'abc',
    })
    expect(parseHash('#/login')).toEqual({ name: 'login', token: null })
    expect(parseHash('#/library?token=abc')).toEqual({ name: 'library' })
  })
})
