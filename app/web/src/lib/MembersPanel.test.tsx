/**
 * Member management and the invite flow (P4.3). The fake server enforces
 * the same NoAdminLeft answer as the real one, so the 409 path is real.
 */
import { cleanup, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { App } from '../App'
import { fakeServer, renderApp } from '../test/harness'
import userEvent from '../test/user'

afterEach(cleanup)

async function openPanel() {
  await userEvent.click(await screen.findByRole('button', { name: 'חשבון' }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'משתתפים' }))
  return await screen.findByRole('dialog', { name: 'משתתפי החשבון' })
}

describe('the members panel (P4.3)', () => {
  it('mints an invite link and shows it exactly once, with its metadata listed', async () => {
    const server = fakeServer()
    renderApp(<App />)
    await openPanel()

    await userEvent.click(
      screen.getByRole('button', { name: 'יצירת קישור הזמנה' }),
    )
    const link = await screen.findByLabelText('קישור ההזמנה')
    // The link carries the RAW token (shown once) on this client's own
    // origin, at the invite route the router parses.
    expect((link as HTMLInputElement).value).toContain('#/invite?token=tok-invite-1')
    await screen.findByText(/לא יוצג שוב/)
    // The open-invites list shows metadata, never the token.
    expect(server.invites).toHaveLength(1)
    expect(screen.queryAllByText(/tok-invite-1/)).toHaveLength(0)

    // Revoke closes it.
    await userEvent.click(
      screen.getByRole('button', { name: /ביטול hash-1/ }),
    )
    await waitFor(() => expect(server.invites).toHaveLength(0))
  })

  it('surfaces NoAdminLeft as the server said it', async () => {
    const server = fakeServer()
    server.members.push({ user_id: 'u2', display_name: 'דנה',
                          role: 'viewer', joined_at: null })
    renderApp(<App />)
    await openPanel()

    // Demoting the only admin: the server's 409 sentence lands verbatim,
    // and the list stays as it was.
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'תפקיד של משה' }), 'viewer',
    )
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('admin')
    expect(server.members[0]!.role).toBe('admin')

    // Removing the other member works, with its own labelled control.
    await userEvent.click(
      screen.getByRole('button', { name: 'הסרה דנה' }),
    )
    await waitFor(() => expect(server.members).toHaveLength(1))
  })
})

describe('accepting an invite (P4.3)', () => {
  it('joins mid-session: the new library is absorbed and selected', async () => {
    const server = fakeServer()
    renderApp(<App />)
    await screen.findByRole('button', { name: 'חשבון' })

    location.hash = `#/invite?token=${server.validInvite}`
    globalThis.dispatchEvent(new HashChangeEvent('hashchange'))

    // The switcher now exists (two libraries) and shows the JOINED one —
    // absorb() selects what just opened up.
    expect(
      await screen.findByRole('button', { name: 'החלפת ספרייה' }),
    ).toBeInTheDocument()
    await screen.findByText('של ההורים')
    expect(location.hash).toBe('#/library')
  })

  it('a dead invite shows the one honest sentence', async () => {
    fakeServer()
    renderApp(<App />)
    await screen.findByRole('button', { name: 'חשבון' })

    location.hash = '#/invite?token=already-used'
    globalThis.dispatchEvent(new HashChangeEvent('hashchange'))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('ההזמנה פגה, נוצלה או בוטלה')
  })

  it('survives the sign-in detour: stashed while signed out, consumed after', async () => {
    const server = fakeServer()
    server.signedOut = true
    location.hash = `#/invite?token=${server.validInvite}`
    renderApp(<App />)

    // Signed out: the login screen shows; the token waits in the stash.
    await screen.findByRole('form', { name: 'כניסה' })
    expect(localStorage.getItem('booksnap.invite')).toBe(server.validInvite)

    // Sign in via a fresh link; the invite is consumed on arrival.
    await userEvent.type(await screen.findByLabelText('אימייל'), 'a@b.co')
    await userEvent.click(screen.getByRole('button', { name: 'שליחת קישור' }))
    location.hash = `#/login?token=${server.validToken}`
    globalThis.dispatchEvent(new HashChangeEvent('hashchange'))

    await screen.findByText('של ההורים')
    expect(localStorage.getItem('booksnap.invite')).toBeNull()
  })
})
