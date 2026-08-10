/**
 * The staff credential — the only thing standing between a LAN and every
 * tenant's data.
 *
 * ⚠ The product's "no login until pillar 4" trade is deliberate and does NOT
 * extend here: a service returning every account and every household's books
 * is a different exposure from one returning your own. These tests pin both
 * halves — that a configured token is actually presented, and that an
 * unconfigured one is said out loud rather than enjoyed in silence.
 */
import { screen } from '@testing-library/react'
import { userEvent } from '@booksnap/ui/testing/user'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '../App'
import { setStaffToken } from '../api/staff'
import { makeOverview, renderApp } from '../test/harness'
import { bothServices } from '../test/servers'

beforeEach(() => {
  vi.unstubAllGlobals()
  setStaffToken(undefined)
})

afterEach(() => {
  // The token is module state AND persisted, so one test's value would
  // otherwise decide the next one's requests.
  setStaffToken(undefined)
})

describe('the staff token', () => {
  it('is presented on every staff request once set', async () => {
    setStaffToken('s3cret')
    const s = bothServices()
    renderApp(<App />)
    await screen.findByText(/סקירת המערכת|System overview/)

    const staffCalls = s.calls.filter((c) => c.url.startsWith('/api/staff/'))
    expect(staffCalls.length).toBeGreaterThan(0)
    expect(staffCalls.every((c) => c.staffToken === 's3cret')).toBe(true)
  })

  /** ⚠ It is the staff service's secret, not the product's. Sending it to
   *  `/api/v1` would leak a cross-tenant credential into a service that has no
   *  idea what it is. */
  it('is never sent to the product API', async () => {
    setStaffToken('s3cret')
    const s = bothServices()
    renderApp(<App />)
    await screen.findByText(/סקירת המערכת|System overview/)

    expect(s.calls.filter((c) => c.url.startsWith('/api/v1/'))
            .every((c) => c.staffToken === undefined)).toBe(true)
  })

  /**
   * ⚠ A 401 blocks EVERY screen, so the form replaces the whole app rather
   * than sitting on one tab. Anything else shows four screens of empty tables
   * and lets the operator conclude the system is empty.
   */
  it('a refused token replaces the console with the form', async () => {
    const s = bothServices()
    for (const route of ['GET /api/staff/v1/overview', 'GET /api/staff/v1/libraries',
                         'GET /api/staff/v1/accounts']) {
      s.route(route, () => new Response(JSON.stringify({ detail: 'a staff token is required' }),
                                        { status: 401 }))
    }
    renderApp(<App />)

    expect(await screen.findByLabelText(/אסימון ניהול|Staff token/)).toBeInTheDocument()
    // Not merely an error banner over an empty dashboard.
    expect(screen.queryByText(/לפי ספרייה|By library/)).not.toBeInTheDocument()
  })

  it('entering a token retries and lets the console through', async () => {
    const s = bothServices()
    let refuse = true
    s.route('GET /api/staff/v1/overview', () =>
      refuse
        ? new Response(JSON.stringify({ detail: 'nope' }), { status: 401 })
        : makeOverview())
    renderApp(<App />)

    const field = await screen.findByLabelText(/אסימון ניהול|Staff token/)
    refuse = false
    const user = userEvent.setup()
    await user.type(field, 's3cret')
    await user.click(screen.getByRole('button', { name: /^שמירה$|^Save$/ }))

    expect(await screen.findByText(/סקירת המערכת|System overview/)).toBeInTheDocument()
  })

  /**
   * ⚠⚠ The dangerous SUCCESS case: everything works, and so would anyone
   * else's browser on the LAN. It must be loud, because nothing about a
   * working console suggests it.
   */
  it('warns when the service runs with no token configured at all', async () => {
    bothServices({ overview: makeOverview({ authenticated: false }) })
    renderApp(<App />)
    expect(await screen.findByText(/BOOKSNAP_STAFF_TOKEN/)).toBeInTheDocument()
  })

  it('a token field is a password field, not plain text', async () => {
    const s = bothServices()
    s.route('GET /api/staff/v1/overview', () =>
      new Response(JSON.stringify({ detail: 'nope' }), { status: 401 }))
    renderApp(<App />)

    // An admin console is exactly the screen someone screen-shares while
    // debugging.
    expect(await screen.findByLabelText(/אסימון ניהול|Staff token/))
      .toHaveAttribute('type', 'password')
  })
})
