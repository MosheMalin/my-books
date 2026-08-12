/**
 * The accounts screen — the console's CUSTOMER list since P3.7e, and the two
 * tabs it replaced before that.
 *
 * ⚠⚠ Every test here that names a number leans on one fixture fact: in
 * `DEFAULT_WORLD`, **`משפחת מלין` (acc-1) owns two libraries** — `הבית` and
 * `המשרד` — and `ההורים` (acc-2) owns one. That is the shape of the owner's
 * real database, and it is the shape that tells a customer list apart from a
 * library list. A world with one library per account cannot.
 */
import { screen, waitFor, within } from '@testing-library/react'
import { userEvent } from '@booksnap/ui/testing/user'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AccountsPage } from './AccountsPage'
import {
  makeUser, makeLibrary, makeStaffAccount, makeStaffBook, makeStaffLibrary,
  renderApp,
} from '../test/harness'
import { bothServices, DEFAULT_WORLD } from '../test/servers'

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('AccountsPage', () => {
  /**
   * ⚠⚠ The owner's list for a row: *"when it was created, who are the admins,
   * how many users, how many books, images storage"*. A person has no admins
   * and no users — that list describes a CUSTOMER, and since P3.7b a customer
   * is a real record rather than the console's word for a `Library`.
   */
  it('reports each customer by admins, users, libraries, books and storage', async () => {
    bothServices()
    renderApp(<AccountsPage openId={undefined} />)

    const table = await screen.findByRole('table')
    const row = within(table).getByText('משפחת מלין').closest('tr')!
    // usr-1 admins acc-1; usr-2 is a viewer there.
    expect(within(row).getByText('משה')).toBeInTheDocument()
    expect(within(row).queryByText('שכן')).not.toBeInTheDocument()
    // users, libraries, books, images, storage — by COLUMN rather than by
    // value, since several of the figures legitimately read the same number.
    const cells = within(row).getAllByRole('cell').map((c) => c.textContent)
    expect(cells[2]).toBe('2')      // users
    expect(cells[3]).toBe('2')      // libraries
    expect(cells[4]).toBe('3')      // books, summed over both collections
    expect(cells[5]).toBe('5')      // images
    expect(cells[6]).toMatch(/\d+ (B|KB|MB)/)  // storage, from the blob tree
  })

  /**
   * ⚠⚠ **The item, in one assertion.** Until P3.7e this table listed
   * `Library` rows under the word "account", so a customer with two
   * collections appeared as two customers. The rows come from
   * `/api/staff/v1/accounts` now, and the libraries are a level down.
   */
  it('lists customers, so one account with two libraries is ONE row', async () => {
    const s = bothServices()
    renderApp(<AccountsPage openId={undefined} />)

    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)  // drop the header
    expect(rows).toHaveLength(2)
    expect(within(table).getByText('משפחת מלין')).toBeInTheDocument()
    expect(within(table).getByText('ההורים')).toBeInTheDocument()
    // Its two collections are NOT rows of this table.
    expect(within(table).queryByText('הבית')).not.toBeInTheDocument()
    expect(within(table).queryByText('המשרד')).not.toBeInTheDocument()

    expect(s.calls.some((c) => c.url === '/api/staff/v1/accounts')).toBe(true)
  })

  it('lists every account in the system, not only the operator\'s own', async () => {
    bothServices()
    renderApp(<AccountsPage openId={undefined} />)

    expect(await screen.findByText('משפחת מלין')).toBeInTheDocument()
    expect(screen.getByText('ההורים')).toBeInTheDocument()
  })

  /**
   * ⚠ Rename and export act on a LIBRARY, and a row is no longer one. An
   * account row carrying *rename* could not say which of its collections it
   * renamed, so both controls moved into the drawer, onto the library rows.
   */
  it('offers no library control on a customer row', async () => {
    bothServices()
    renderApp(<AccountsPage openId={undefined} />)
    await screen.findByText('משפחת מלין')

    const table = screen.getByRole('table')
    expect(within(table).queryByRole('button', { name: /שינוי שם|Rename/ }))
      .not.toBeInTheDocument()
    expect(within(table).queryByRole('link', { name: /^CSV$/ }))
      .not.toBeInTheDocument()
  })

  /**
   * ⚠⚠ A person with no membership would otherwise be invisible: the Users tab
   * was the only screen that listed people directly, and a customer-shaped
   * list cannot show somebody who belongs to no customer. The mirror of the
   * orphan-library warning.
   */
  it('names the people who belong to no account at all', async () => {
    bothServices({
      users: [...DEFAULT_WORLD.users,
                 makeUser({ id: 'usr-9', display_name: 'נשכח',
                               memberships: [] })],
    })
    renderApp(<AccountsPage openId={undefined} />)

    expect(await screen.findByText(/ללא שיוך|Unaffiliated/)).toBeInTheDocument()
    expect(screen.getByText('נשכח')).toBeInTheDocument()
  })

  /**
   * ⚠⚠ `th_account` was rendered over THREE entities before P3.7e — customers,
   * people and libraries — which is how the console said "account" about a
   * person. The people table says "user".
   */
  it('heads the people table with user, not with account', async () => {
    bothServices({
      users: [...DEFAULT_WORLD.users,
                 makeUser({ id: 'usr-9', display_name: 'נשכח',
                               memberships: [] })],
    })
    renderApp(<AccountsPage openId={undefined} />)
    await screen.findByText(/ללא שיוך|Unaffiliated/)

    const people = screen.getByText('נשכח').closest('table')!
    expect(within(people).getByRole('columnheader', { name: /^משתמש$|^User$/ }))
      .toBeInTheDocument()
    expect(within(people).queryByRole('columnheader', { name: /^חשבון$|^Account$/ }))
      .not.toBeInTheDocument()
  })

  it('says nothing about unaffiliated people when there are none', async () => {
    bothServices()
    renderApp(<AccountsPage openId={undefined} />)
    await screen.findByText('משפחת מלין')
    expect(screen.queryByText(/ללא שיוך|Unaffiliated/)).not.toBeInTheDocument()
  })

  /** ⚠ `new_account` mints an admin membership in the same call precisely so
   *  this cannot happen, and `NoAdminLeft` keeps it so — a customer nobody can
   *  administer is the anomaly only a system console can surface. */
  it('flags an account with no administrator', async () => {
    bothServices({
      accounts: [makeStaffAccount({ id: 'acc-9', label: 'יתומה', members: 0,
                                    admins: 0, libraries: 0 })],
      libraries: [],
      users: [],
    })
    renderApp(<AccountsPage openId={undefined} />)

    expect(await screen.findByText(/אין מנהל|no admin/)).toBeInTheDocument()
  })

  it('creates a library and refreshes the system list', async () => {
    const s = bothServices()
    s.route('POST /api/v1/libraries', () => makeLibrary({ id: 'lib-9' }))
    const user = userEvent.setup()
    renderApp(<AccountsPage openId={undefined} />)
    await screen.findByText('משפחת מלין')

    await user.click(screen.getByRole('button', { name: /ספרייה חדשה|New library/ }))
    await user.type(screen.getByLabelText(/שם הספרייה|Library name/), 'חדשה')
    await user.click(screen.getByRole('button', { name: /^יצירה$|^Create$/ }))

    await waitFor(() => {
      expect(s.calls.filter((c) => c.method === 'POST')).toHaveLength(1)
      // The system list is refetched, not patched: the new row's figures come
      // from the staff service, which is the only thing that knows them.
      expect(s.calls.filter((c) => c.url === '/api/staff/v1/accounts').length)
        .toBeGreaterThan(1)
    })
  })

  it('offers no way to delete an account or a library', async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    expect(screen.queryByRole('button', { name: /מחיקה|Delete/ }))
      .not.toBeInTheDocument()
    // ⚠ The note followed its subject. It sat under the accounts table until
    // P3.7e moved the library rows into the drawer, leaving a sentence about
    // deleting a library on a screen with no library on it.
    expect(within(panel).getByText(/אין מחיקת ספרייה|No library delete/i))
      .toBeInTheDocument()
  })

  /**
   * ⚠ The drawer's sections are the owner's own shape — *"users section, books
   * section, images section"* — plus the level P3.7e put back: the customer's
   * LIBRARIES.
   */
  it('opens one account in a drawer with libraries, users, books and images', async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)

    const panel = await screen.findByRole('dialog')
    for (const name of [/^ספריות$|^Libraries$/, /משתמשים|Users/,
                        /^ספרים$|^Books$/, /^תמונות$|^Images$/]) {
      expect(within(panel).getByRole('heading', { name })).toBeInTheDocument()
    }
    // The list is still behind it — that is what makes it a drawer.
    expect(screen.getByText('ההורים')).toBeInTheDocument()
  })

  /**
   * ⚠⚠ **An operator's bookmark from before P3.7e carries a LIBRARY id.**
   * `#/accounts/<id>` meant a library until this item and means a customer
   * now, and `parseHash` cannot tell them apart because an id is opaque. So
   * the screen resolves, and a stale link lands on the customer that OWNS the
   * collection it named — not on a 404 teaching the operator their link
   * rotted.
   */
  it('lands a stale library-id bookmark on the owning account', async () => {
    bothServices()
    renderApp(<AccountsPage openId="lib-3" />)

    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByRole('heading', { name: 'משפחת מלין' }))
      .toBeInTheDocument()
    // …and the collection that was bookmarked is one of the rows inside it.
    // By ID: the name also appears in the async previews' "which collection"
    // column, so a by-name lookup here would race the fetch.
    expect(within(panel).getByText('lib-3')).toBeInTheDocument()
  })

  /**
   * ⚠⚠ The gloss, gone. `t.acct_library_id` used to sit under the account name
   * reading *"library id"* — a label whose whole job was to admit that the
   * console said "account" and the storage said `Library`. It is DELETED, not
   * relabelled: the mapping is data now, one row per collection.
   */
  it('shows the account id, and the library ids on the libraries it owns', async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)

    const panel = await screen.findByRole('dialog')
    expect(within(panel).queryByText(/מזהה ספרייה|Library id/))
      .not.toBeInTheDocument()
    expect(within(panel).getByText('acc-1')).toBeInTheDocument()
    expect(within(panel).getByText('lib-1')).toBeInTheDocument()
    expect(within(panel).getByText('lib-3')).toBeInTheDocument()
  })

  /**
   * ⚠ Reading spans every tenant; writing does not. A collection outside
   * `mine` shows its numbers and says it is read-only rather than offering a
   * button that would 404 on click.
   */
  it('offers rename and export only in libraries the operator belongs to', async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)
    const ours = await screen.findByRole('dialog')

    // ⚠ Located by ID. A library's NAME appears in more than one place in this
    // drawer — its own row, and the "which collection" column of the books and
    // images previews — and those previews are async, so a by-name lookup
    // passes or fails depending on whether the fetch has resolved. Measured:
    // it passed alone and collided under the full ring.
    const home = within(ours).getByText('lib-1').closest('tr')!
    expect(within(home).getByRole('button', { name: /שינוי השם של הבית|Rename הבית/ }))
      .toBeInTheDocument()
    expect(within(home).getByRole('link', { name: /הבית.*CSV|CSV.*הבית/ }))
      .toBeInTheDocument()
  })

  /**
   * ⚠⚠ EVERY per-row control names its library, not just the two links that
   * got it first. A review measured the gap and found the duplicated
   * accessible names included *rename* — the only control here that WRITES.
   * Two buttons both announcing "שינוי שם" leave a screen-reader user unable
   * to tell which collection they are about to rename, which is the collision
   * class this project has already been bitten by twice.
   */
  it('gives every per-library control an accessible name of its own', async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    const names = [...panel.querySelectorAll('button, a')]
      .map((el) => el.getAttribute('aria-label') ?? el.textContent?.trim())
      .filter((n): n is string => !!n)
    const duplicated = names.filter((n, i) => names.indexOf(n) !== i)
    expect(duplicated).toEqual([])
  })

  /**
   * ⚠⚠ A drawer is capped at `min(720px, 100%)`. The first version put the
   * five per-row controls in a trailing ACTIONS column, which measured 834px
   * wide and left rename and both exports outside the box at `scrollLeft: 0`
   * — absent from the accessibility tree until the table was scrolled
   * sideways. This item MOVED those controls here from a full-width table, so
   * "scroll to find them" is a regression of its own goal. They stack under
   * the library name instead, in the same cell.
   */
  it('keeps every library control inside the name cell, not a trailing column', async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    const libs = within(panel).getByText('lib-1').closest('table')!
    expect(within(libs).queryByRole('columnheader', { name: /פעולות|Actions/ }))
      .not.toBeInTheDocument()
    const nameCell = within(panel).getByText('lib-1').closest('td')!
    expect(within(nameCell).getByRole('button',
      { name: /שינוי השם של הבית|Rename הבית/ })).toBeInTheDocument()
    expect(within(nameCell).getByRole('link', { name: /CSV/ })).toBeInTheDocument()
    expect(within(nameCell).getByRole('link', { name: /JSON/ })).toBeInTheDocument()
  })

  it('says read-only on a library of a customer the operator does not belong to',
     async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-2" />)
    const theirs = await screen.findByRole('dialog')

    // ⚠ Located by the library's ID, not its label: acc-2 and its only
    // collection are both called 'ההורים' — which is realistic, and exactly
    // why a customer and a collection must be distinguishable on screen.
    const row = within(theirs).getByText('lib-2').closest('tr')!
    expect(within(row).queryByRole('button', { name: /שינוי שם|Rename/ }))
      .not.toBeInTheDocument()
    expect(within(row).getByText(/אינכם חברים|not a member/)).toBeInTheDocument()
  })

  /**
   * ⚠⚠ `LibraryDTO.members` and `.admins` mean the OWNING ACCOUNT's people
   * since P3.7b — the fixture gives `המשרד` the same `members: 2` its sibling
   * has, because that is what the wire reports. Printing them per collection
   * would show one household once per shelf it keeps, so the headcount appears
   * exactly once, on the account.
   */
  it('reports the headcount on the account and never on its libraries', async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    // By ID, for the reason above: the name also appears in the async previews.
    const libs = within(panel).getByText('lib-1').closest('table')!
    for (const name of [/^משתמשים$|^Users$/, /^מנהלים$|^Admins$/]) {
      expect(within(libs).queryByRole('columnheader', { name }))
        .not.toBeInTheDocument()
    }
    // It IS reported, on the customer above — the stat block, not a column.
    const stats = panel.querySelector('.stats') as HTMLElement
    const card = within(stats).getByText(/^משתמשים$|^Users$/).closest('.stat')!
    expect(within(card as HTMLElement).getByText('2')).toBeInTheDocument()
  })

  /**
   * ⚠ The preview merges the account's collections. A merge that kept only the
   * first library's page would drop `דדא`, which lives in `המשרד` and is the
   * newest book the customer has.
   */
  it('previews books from every library of the account, newest first', async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    expect(await within(panel).findByText('דדא')).toBeInTheDocument()
    expect(within(panel).getByText('אבא')).toBeInTheDocument()

    // ⚠ NEWEST FIRST, asserted by position. `דדא` (2026-02-01) is the only
    // row from the second collection and the most recent the customer has, so
    // a merge that concatenated the pages in library order would put it last
    // and still contain it — which is why presence alone is not the test.
    const books = within(panel).getByText('דדא').closest('table')!
    const titles = within(books).getAllByRole('row').slice(1)
      .map((r) => within(r).getAllByRole('cell')[0]!.textContent)
    expect(titles[0]).toContain('דדא')

    // …and each row says which collection it came from, because the customer
    // is not the collection.
    const row = within(panel).getByText('דדא').closest('tr')!
    expect(within(row).getByText('המשרד')).toBeInTheDocument()
  })

  /**
   * ⚠ Reported, not profiled. The drawer shows identity, role and join date —
   * never a per-person feed of what somebody has been photographing at home.
   * And there is no invite/remove/re-role control, because there is no route
   * for one in either service.
   */
  it('reports membership without offering to change it, and without activity',
     async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    expect(within(panel).getByText('usr-2')).toBeInTheDocument()
    expect(within(panel).getByText('viewer')).toBeInTheDocument()
    for (const name of [/הזמנה|Invite/, /הסרה|Remove/, /שינוי תפקיד|Change role/]) {
      expect(within(panel).queryByRole('button', { name })).not.toBeInTheDocument()
    }
    expect(within(panel).getByText(/מחכים להתחברות|wait on the login/))
      .toBeInTheDocument()
  })

  /**
   * ⚠⚠ **The member list is scoped to the OPEN account.** A version reaching
   * for `memberships[0]` instead of the entry naming this customer passed the
   * whole ring, because the only drawer any test opened was acc-1, where the
   * right answer and the wrong one coincide. `usr-2` belongs to BOTH
   * customers with a DIFFERENT role in each — viewer at acc-1, admin at
   * acc-2 — so opening acc-2 makes the two answers disagree: the wrong fold
   * lists משה, who belongs only to acc-1, and badges שכן `viewer`.
   *
   * A cross-customer people leak, on the screen whose whole premise is that
   * the customer is not the collection.
   */
  it('lists only the people of the OPEN account, with the role they hold there',
     async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-2" />)
    const panel = await screen.findByRole('dialog')

    const shachen = within(panel).getByText('usr-2').closest('tr')!
    expect(within(shachen).getByText('admin')).toBeInTheDocument()
    expect(within(shachen).queryByText('viewer')).not.toBeInTheDocument()
    // משה holds no membership at acc-2 and must not appear at all.
    expect(within(panel).queryByText('משה')).not.toBeInTheDocument()
    expect(within(panel).queryByText('usr-1')).not.toBeInTheDocument()
    // …and the two who DO belong here are both listed.
    expect(within(panel).getByText('סבתא')).toBeInTheDocument()
    expect(within(panel).getByText('סבא')).toBeInTheDocument()
  })

  /**
   * ⚠ The images preview fans out too. The books equivalent was pinned and
   * this one was not — the fixture was even extended for it (`cap-3` in
   * `lib-3`, with distinct tier figures so a by-text assertion is
   * unambiguous) and the test was never written.
   */
  it('previews images from every library of the account, newest first', async () => {
    bothServices()
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    // 'ארון' is cap-3's shelf, and cap-3 lives only in the second collection.
    expect(await within(panel).findByText(/ארון/)).toBeInTheDocument()
    const images = within(panel).getByText(/ארון/).closest('table')!
    const first = within(images).getAllByRole('row')[1]!
    // cap-3 is 2026-02-02, cap-1 is 2026-01-03 — newest first.
    expect(within(first).getByText(/ארון/)).toBeInTheDocument()
    expect(within(first).getByText('המשרד')).toBeInTheDocument()
  })

  /**
   * ⚠⚠ **A failed people request must not read as a customer anomaly.**
   * "No admin" and "nobody can administer this account" are states
   * `new_account` and `NoAdminLeft` make unreachable — the console renders
   * them in warning tone precisely because any occurrence is a bug that
   * already happened. Derived from an empty `users` list they are ALSO what a
   * 500 on `/users` looks like, and the screen said nothing else at all.
   * Measured: two customers, both flagged, beside a stat card reading 2 users.
   */
  it('reports a failed people request as a failure, not as a customer with no admin',
     async () => {
    const s = bothServices()
    s.route('GET /api/staff/v1/users', () =>
      new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }))
    renderApp(<AccountsPage openId={undefined} />)
    await screen.findByText('משפחת מלין')

    // The alarm is NOT raised…
    expect(screen.queryByText(/אין מנהל|no admin/)).not.toBeInTheDocument()
    // …the operator is told why the names are missing…
    expect(screen.getByText(/רשימת האנשים אינה זמינה|people list is unavailable/))
      .toBeInTheDocument()
    // …and the failure itself is on screen. ⚠ Both halves matter: the note
    // explains the gap, the error box says something BROKE. Asserting only
    // the note let the old `accounts.length === 0 && error` guard survive.
    expect(screen.getByRole('button', { name: /נסו שוב|Try again/ }))
      .toBeInTheDocument()
  })

  /**
   * ⚠ The mirror of the above, one list along: with `/libraries` down the
   * drawer said "this account keeps no library" three lines under a stat card
   * reading 2. Two contradictory sentences, no error.
   */
  it('says the library list is unavailable rather than that there are none',
     async () => {
    const s = bothServices()
    s.route('GET /api/staff/v1/libraries', () =>
      new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }))
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    expect(within(panel).queryByText(/אינו מחזיק אף ספרייה|keeps no library/))
      .not.toBeInTheDocument()
    expect(within(panel).getByText(/רשימת הספריות אינה זמינה|library list is unavailable/))
      .toBeInTheDocument()
  })

  /**
   * ⚠ The preview is capped per library, and nothing exercised the cap: no
   * fixture library held more than two books and the fake ignored `limit`
   * entirely, so a drawer for a 286-book customer would have rendered 286
   * rows with the ring green.
   */
  it('caps the book preview instead of rendering a whole catalogue', async () => {
    const many = Array.from({ length: 9 }, (_, i) =>
      makeStaffBook({ id: `bulk-${i}`, library_id: 'lib-1', title: `כרך ${i}`,
                      added_at: `2026-03-0${i + 1}T00:00:00Z` }))
    const s = bothServices({ books: [...DEFAULT_WORLD.books, ...many] })
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    expect(await within(panel).findByText('כרך 8')).toBeInTheDocument()
    const books = within(panel).getByText('כרך 8').closest('table')!
    expect(within(books).getAllByRole('row').slice(1)).toHaveLength(5)

    // ⚠⚠ And the cap is on the REQUEST, not only on what is rendered. The
    // trailing `.slice()` alone keeps the table five rows long while the
    // browser downloads the customer's entire catalogue — 286 books for the
    // owner's own account — so a row count cannot see the defect. Asking for
    // five IS the behaviour here.
    const asked = s.calls.filter((c) => c.url.startsWith('/api/staff/v1/books'))
    expect(asked).not.toHaveLength(0)
    for (const call of asked) expect(call.url).toContain('limit=5')
  })

  /** ⚠ An id naming neither a customer nor a collection opens nothing AND
   *  says so — silence is what teaches an operator their bookmark rotted. */
  it('says plainly when the id in the link names nothing', async () => {
    bothServices()
    renderApp(<AccountsPage openId="nope" />)
    await screen.findByText('משפחת מלין')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByText(/אינו מתאים לאף חשבון|matches no account/))
      .toBeInTheDocument()
  })

  /**
   * ⚠⚠ **A refresh is not a first load.** `loading` blanks every screen to a
   * spinner, so raising it on a reload unmounted the accounts list AND the
   * open drawer: renaming a library from inside the drawer threw the screen
   * away and brought it back scrolled to the top, re-issuing all four preview
   * fetches. Measured in a real browser with a MutationObserver across a
   * rename — the only two states recorded were "the screen" and "טוען…".
   */
  it('keeps the drawer open across a rename instead of blanking to a spinner',
     async () => {
    const s = bothServices()
    s.route('PATCH /api/v1/libraries', () => makeLibrary({ id: 'lib-1' }))
    const user = userEvent.setup()
    renderApp(<AccountsPage openId="acc-1" />)
    const panel = await screen.findByRole('dialog')

    // ⚠ The reload is held OPEN. The screen is only wrong WHILE the refetch
    // is in flight — let it settle first and the drawer is back, so a test
    // that only looks afterwards cannot see the blanking at all (measured:
    // the mutation survived that version).
    // ⚠ Installed AFTER the first load has already settled (the drawer is on
    // screen above), so every call this handler sees is a reload and it holds
    // all of them. An earlier version let the first one through on a flag —
    // and the first one WAS the reload, so nothing was ever held and the
    // mutation survived.
    let release = () => {}
    const held = new Promise<void>((r) => { release = r })
    s.route('GET /api/staff/v1/accounts', async () => {
      await held
      return DEFAULT_WORLD.accounts
    })

    await user.click(within(panel).getByRole('button',
      { name: /שינוי השם של הבית|Rename הבית/ }))
    await user.click(within(panel).getByRole('button', { name: /^שמירה$|^Save$/ }))

    // ⚠⚠ Wait for the RELOAD to have been issued, not merely for the PATCH.
    // `s.calls` records a request when it is made, so the PATCH appears
    // before its own promise resolves — i.e. before `onRenamed` fires the
    // reload at all. A version that waited on the PATCH asserted against a
    // screen the refetch had not touched yet and passed under the mutation
    // too (measured).
    const accountCalls = () =>
      s.calls.filter((c) => c.url === '/api/staff/v1/accounts').length
    const before = accountCalls()
    await waitFor(() => { expect(accountCalls()).toBeGreaterThan(before) })

    // Mid-refetch — the handler above is still held — the list and the open
    // drawer are both still on screen.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // The list behind it too — by ROLE, since the drawer heading repeats the
    // customer's name.
    expect(screen.getByRole('link', { name: 'משפחת מלין' })).toBeInTheDocument()
    release()
  })

  /** ⚠ It carries `role="dialog"`, and the console's other two panels close on
   *  Escape. Announcing itself as a dialog and then not behaving like one is a
   *  promise broken — and P3.7e made this the primary surface. */
  it('closes on Escape, like the console’s other panels', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<AccountsPage openId="acc-1" />)
    await screen.findByRole('dialog')

    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(window.location.hash).toBe('#/accounts')
    })
  })

  /** A customer created before its first collection is a real state — P4.3's
   *  normal onboarding path — and `/accounts` lists it as a row of zeroes. */
  it('says plainly when an account keeps no library', async () => {
    bothServices({
      accounts: [makeStaffAccount({ id: 'acc-3', label: 'חדש', libraries: 0 })],
      libraries: [makeStaffLibrary({ id: 'lib-1', account_id: 'acc-other' })],
    })
    renderApp(<AccountsPage openId="acc-3" />)

    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByText(/אינו מחזיק אף ספרייה|keeps no library/))
      .toBeInTheDocument()
  })
})
