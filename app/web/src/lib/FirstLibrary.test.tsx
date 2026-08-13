/**
 * The first-library screen (P4.1c): a signed-in user with no library
 * names their first one — which is sign-up's second half — and the tabs
 * take over the moment it exists.
 */
import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { App } from '../App'
import { fakeServer, renderApp } from '../test/harness'
import userEvent from '../test/user'

afterEach(cleanup)

describe('the first library (P4.1c)', () => {
  it('replaces the tabs until a library exists, then hands over', async () => {
    const server = fakeServer()
    server.libraries.length = 0
    renderApp(<App />)

    const form = await screen.findByRole('form', {
      name: 'הספרייה הראשונה שלך',
    })
    expect(form).toBeInTheDocument()
    // No tabs and no book screen behind it — the screens can only 404
    // with no library to name.
    expect(screen.queryByRole('button', { name: 'ספרים' })).toBeNull()

    const create = screen.getByRole('button', { name: 'יצירת הספרייה' })
    expect(create).toBeDisabled()
    await userEvent.type(screen.getByLabelText('שם הספרייה'), 'משפחת מלין')
    await userEvent.click(create)

    // The provider created, switched, and the tabs took over.
    expect(
      await screen.findByRole('button', { name: 'ספרים' }),
    ).toBeInTheDocument()
    expect(
      server.calls.some((c) => c.includes('/api/v1/libraries')),
    ).toBe(true)
    expect(server.libraries).toHaveLength(1)
    expect(server.libraries[0]!.label).toBe('משפחת מלין')
  })

  it('keeps the name on screen when the server refuses', async () => {
    const server = fakeServer()
    server.libraries.length = 0
    server.failNextWith = 400
    renderApp(<App />)

    await userEvent.type(
      await screen.findByLabelText('שם הספרייה'),
      'משפחת מלין',
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'יצירת הספרייה' }),
    )
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByLabelText('שם הספרייה')).toHaveValue('משפחת מלין')
  })
})
