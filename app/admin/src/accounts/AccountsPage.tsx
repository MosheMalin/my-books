/**
 * The operator's customers — one row per **Account**, since P3.7e.
 *
 * ⚠⚠ **This screen used to list `Library` rows and call them accounts.** That
 * was a deliberate, documented gloss (ADMIN_CONSOLE_PLAN revision 4): the
 * operator's word for the thing they administer was "account", the tenant
 * record was a `Library`, and the drawer showed the library id under the name
 * so the mapping stayed visible rather than hidden.
 *
 * The gloss is retired because the domain moved under it. VISION §4.1
 * **[REVISED 2026-08-11]** made the **Account** the tenancy boundary and a
 * Library a logical partition inside it; P3.7b made that a real record with a
 * real table. A customer owning two collections — which is exactly what the
 * owner's own database holds — was a shape this screen could not draw: it
 * showed two rows and called them two accounts.
 *
 * So the rows come from `/api/staff/v1/accounts` (customers, with their
 * libraries' figures summed server-side) and the LIBRARIES live one level
 * down, inside the drawer. Three consequences, each a decision:
 *
 *   - **rename and export left this table.** They act on a library, and a
 *     library is no longer what a row is. An account row carrying *rename*
 *     could not say which collection it renamed. They are on the library rows
 *     in the drawer;
 *   - **`members`/`admins` are read off the ACCOUNT**, never off a library.
 *     `LibraryDTO` carries both since P3.7b and both mean *the owning
 *     account's people* — rendering them per library would show one household
 *     once per shelf it keeps;
 *   - **creating a library still lives here**, because `POST /api/v1/libraries`
 *     creates one under the CALLER's own account and there is no route that
 *     creates one for somebody else. The form says so.
 *
 * ⚠ Reading spans every tenant; WRITING does not. Rename and export go through
 * the product API, which resolves the operator's own membership — so a library
 * outside `mine` shows its numbers and says it is read-only rather than
 * offering a button that would 404.
 */
import { useState } from 'react'

import { createLibrary } from '../api/client'
import { formatDate, formatNumber, libraryName } from '@booksnap/ui'
import { useI18n } from '../lib/i18n'
import { href, navigate } from '../lib/route'
import { OpenServiceWarning } from '../lib/StaffToken'
import { useSystem } from '../lib/system'
import { formatBytes } from '../lib/ui'
import { Empty, ErrorBox, Loading } from '@booksnap/ui'
import { AccountDrawer } from './AccountDrawer'

function CreateForm({ onCreated }: { onCreated: () => void }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)

  if (!open) {
    return (
      <button type="button" className="btn primary" onClick={() => setOpen(true)}>
        + {t.lib_new}
      </button>
    )
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      await createLibrary(label)
      onCreated()
      // Only closed on SUCCESS. A refusal that cleared the form would make the
      // operator retype what they had, which reads as the app losing input.
      setOpen(false)
      setLabel('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit} style={{ maxWidth: 460 }}>
      <label className="field">
        {t.lib_name}
        <input type="text" value={label} autoFocus className="rtl-safe"
               onChange={(e) => setLabel(e.target.value)} />
      </label>
      <p className="sub" style={{ margin: '6px 0 4px' }}>{t.lib_name_hint}</p>
      {/* ⚠ Stated, because it is the one thing about this form that is not
          obvious on a SYSTEM console: `POST /api/v1/libraries` creates the
          library under the CALLER's account. There is no route that creates
          one for somebody else — and since P3.7b creating one grants nobody
          anything, it inherits the account's standing. */}
      <p className="note" style={{ margin: '0 0 10px' }}>{t.lib_create_note}</p>
      {error && <ErrorBox message={error} />}
      <div className="row">
        <button type="submit" className="btn primary" disabled={busy || !label.trim()}>
          {t.lib_create}
        </button>
        <button type="button" className="btn"
                onClick={() => { setOpen(false); setError(undefined) }}>
          {t.cancel}
        </button>
      </div>
    </form>
  )
}

export function AccountsPage({ openId }: { openId: string | undefined }) {
  const {
    accounts, users, overview, loading, error, reload, librariesOf,
    accountOfLibrary,
  } = useSystem()
  const { t, lang } = useI18n()

  if (loading) return <Loading />
  if (accounts.length === 0 && error) {
    return <ErrorBox message={error} onRetry={reload} />
  }

  const num = (n: number) => formatNumber(n, lang)

  /**
   * ⚠⚠ **An operator's bookmark from before P3.7e carries a LIBRARY id.**
   * `#/accounts/<id>` meant a library until this item and means a customer
   * now, and `parseHash` cannot tell them apart — an id is opaque, which is
   * why it is decoded rather than pattern-matched. So the resolution happens
   * HERE, where the data is: an account id opens that account; a library id
   * opens the account that OWNS it. Either way the operator lands on the
   * customer their link was about, which beats a 404 teaching them the link
   * rotted.
   */
  const open = openId
    ? accounts.find((a) => a.id === openId) ?? accountOfLibrary(openId)
    : undefined

  /** Who administers this customer. Derived from the user list the provider
   *  already holds — the server reports an admin COUNT and no names, and
   *  deriving them here keeps membership described in exactly one place. */
  const adminsOf = (accountId: string) =>
    users.filter((u) => u.memberships.some(
      (m) => m.account_id === accountId && m.role === 'admin'))

  // ⚠ The mirror of `orphan_libraries`. A customer-shaped list cannot show a
  // person who belongs to no customer, and the Users tab was the only place
  // they appeared. Derived, not fetched: the provider already has every user.
  const unaffiliated = users.filter((u) => u.memberships.length === 0)

  return (
    <>
      <h1>{t.acct_title}</h1>
      <p className="sub">{t.acct_sub}</p>

      {overview && !overview.authenticated && <OpenServiceWarning />}
      {overview && overview.orphan_libraries.length > 0 && (
        <p className="note warn">{t.sys_orphans(overview.orphan_libraries.length)}</p>
      )}
      <p className="note">{t.acc_two_admins}</p>

      <div style={{ marginBottom: 16 }}>
        <CreateForm onCreated={reload} />
      </div>

      {accounts.length === 0 ? (
        <Empty>{t.lib_empty}</Empty>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.th_account}</th>
                <th>{t.th_admins}</th>
                <th className="num">{t.th_users}</th>
                <th className="num">{t.th_libraries}</th>
                <th className="num">{t.th_books}</th>
                <th className="num">{t.th_images}</th>
                <th className="num">{t.th_storage}</th>
                <th>{t.th_created}</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => {
                const admins = adminsOf(account.id)
                return (
                  <tr key={account.id}>
                    <td className="rtl-safe">
                      <a href={href({ name: 'account', id: account.id })}>
                        {libraryName(account.label, t.acct_unnamed)}
                      </a>
                      <div className="mono">{account.id}</div>
                    </td>
                    <td className="rtl-safe">
                      {/* ⚠ A customer with no admin is the one anomaly this
                          table can surface that no household screen can:
                          `new_account` mints an admin membership in the same
                          call precisely so it cannot happen, and `NoAdminLeft`
                          keeps it so. Any row here is a bug that already
                          happened. */}
                      {admins.length === 0
                        ? <span className="badge warn">{t.acct_no_admin}</span>
                        : admins.map((u) => (
                            // ⚠ Falls back to the ID, not to the word
                            // "unnamed". Until P4.1 a user has no login and
                            // usually no display name, so a column of
                            // "unnamed" rows identifies nobody — which is
                            // exactly what this column exists to do.
                            <div key={u.id}>
                              {u.display_name.trim()
                                || <span className="mono">{u.id}</span>}
                            </div>
                          ))}
                    </td>
                    <td className="num">
                      {num(account.members)}
                      {account.members === 0 && <> <span className="badge">!</span></>}
                    </td>
                    {/* ⚠ The number this screen could not previously show. One
                        customer with two collections was two rows called two
                        accounts — the shape the owner's own database has. */}
                    <td className="num">{num(account.libraries)}</td>
                    <td className="num">{num(account.books)}</td>
                    <td className="num">{num(account.captures)}</td>
                    <td className="num">{formatBytes(account.image_bytes, lang)}</td>
                    <td>{formatDate(account.created_at, lang) || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ⚠ Not a curiosity: until P4.1 a user cannot log in, so a person with
          no membership is somebody the system knows about and nobody can
          reach. It is also the only way they appear anywhere now that the
          people list is a section inside an account. */}
      {unaffiliated.length > 0 && (
        <>
          <h2>{t.acct_unaffiliated}</h2>
          <p className="sub">{t.acct_unaffiliated_why}</p>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  {/* ⚠ `th_user`, not `th_account`. This table lists PEOPLE.
                      One header string over both was how the console said
                      "account" over a person and a customer alike. */}
                  <th>{t.th_user}</th>
                  <th>{t.th_email}</th>
                  <th>{t.th_created}</th>
                </tr>
              </thead>
              <tbody>
                {unaffiliated.map((user) => (
                  <tr key={user.id}>
                    <td className="rtl-safe">
                      <div className="t">
                        {user.display_name.trim()
                          || <span className="a">{t.users_unnamed}</span>}
                      </div>
                      <div className="mono">{user.id}</div>
                    </td>
                    <td className="mono">{user.email || '—'}</td>
                    <td>{formatDate(user.created_at, lang) || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="note" style={{ marginTop: 16 }}>{t.lib_no_delete}</p>

      {open && (
        <AccountDrawer key={open.id} account={open}
                       libraries={librariesOf(open.id)}
                       onChanged={reload}
                       onClose={() => navigate({ name: 'accounts' })} />
      )}
    </>
  )
}
