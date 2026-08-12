/**
 * The access screen — the credential, the two admin jobs, and the gaps.
 *
 * ⚠ It had no ring of its own until P3.7e, which is how a line reading
 * *"Right now: N accounts, M libraries"* kept passing `users.length` into the
 * accounts slot: nothing rendered it in a test. Two of its sentences are now
 * load-bearing statements about the tenancy model, so both are pinned.
 */
import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AccessPage } from './AccessPage'
import { makeOverview, renderApp } from '../test/harness'
import { bothServices, DEFAULT_WORLD } from '../test/servers'

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('AccessPage', () => {
  /**
   * ⚠⚠ **Three numbers, from the overview, all different.** The old call read
   * `users.length` under the label "accounts" and `overview.libraries` under
   * "libraries" — two names for what was then one entity. Since P3.7b they are
   * three entities, and the fixture keeps 2 / 4 / 3 — pairwise different — so
   * that reading the wrong field cannot pass unnoticed. ⚠ The first version
   * used 2 / 2 / 3, and a review measured what that hid: `users.length` was
   * also 2, so the ORIGINAL defect (customers counted by the length of the
   * user list) survived both tests.
   */
  it('counts accounts, users and libraries as three different figures', async () => {
    bothServices()
    renderApp(<AccessPage />)

    const line = await screen.findByText(/כרגע:|Right now:/)
    expect(line.textContent).toMatch(/\b2\b.*\b4\b.*\b3\b/)
  })

  it('reads those figures from the overview, not from the lists it holds', async () => {
    // ⚠ Six people in the system, two of them customers. A screen measuring
    // "accounts" by the length of its user list would say six.
    bothServices({
      overview: makeOverview({ ...DEFAULT_WORLD.overview,
                               accounts: 2, users: 6, libraries: 3 }),
    })
    renderApp(<AccessPage />)

    const line = await screen.findByText(/כרגע:|Right now:/)
    expect(line.textContent).toMatch(/\b2\b.*\b6\b.*\b3\b/)
  })

  /**
   * ⚠⚠ A role is held per ACCOUNT since P3.7b and covers every library that
   * account owns. The sentence naming the two admin jobs said it lived "inside
   * one library", which stopped being true — and a wrong stated reason is what
   * makes the next reader delete the guard.
   */
  it('says an account admin covers every library the account keeps', async () => {
    bothServices()
    renderApp(<AccessPage />)

    const note = await screen.findByText(/שני תפקידים שונים|two different jobs/)
    expect(note.textContent)
      .toMatch(/כל הספריות שהחשבון מחזיק|every library that account keeps/)
  })

  /**
   * ⚠ The membership rows link to the OWNING ACCOUNT. The operator holds one
   * role over acc-1, so both of its collections link to the same drawer —
   * which is what a role covering every library of a customer means.
   */
  it('links each membership to the account that holds the role', async () => {
    bothServices()
    renderApp(<AccessPage />)

    // ⚠ The link's accessible name now carries the collection AND its owning
    // customer, because a library name alone does not say whose it is.
    const home = await screen.findByRole('link', { name: /הבית.*משפחת מלין/ })
    const office = screen.getByRole('link', { name: /המשרד.*משפחת מלין/ })
    expect(home.getAttribute('href')).toBe('#/accounts/acc-1')
    expect(office.getAttribute('href')).toBe('#/accounts/acc-1')
  })

  /** The gaps are listed, never mocked up: a greyed-out invite button that
   *  never becomes clickable reads as a bug. */
  it('names what is missing instead of offering a dead control', async () => {
    bothServices()
    renderApp(<AccessPage />)

    const gaps = await screen.findByText(/מה שאין עדיין|What is not here yet/)
    const box = gaps.closest('section') ?? gaps.parentElement!
    expect(within(box).queryByRole('button', { name: /הזמנה|Invite/ }))
      .not.toBeInTheDocument()
    expect(screen.getByText(/P4\.3/)).toBeInTheDocument()
  })
})
