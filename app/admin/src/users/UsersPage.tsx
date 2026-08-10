/**
 * Every account in the system, and what each one may reach.
 *
 * ⚠⚠ This screen has no equivalent in `/api/v1` and could not have one: the
 * product API answers *"which libraries may **I** name"*, never *"who is in
 * the system"*. It is the clearest example of why a system administrator is a
 * separate service rather than a bigger role.
 *
 * ⚠ **It reports identity and membership, deliberately not activity.**
 * "Statistics about the users" is a fair thing for an operator to want, and a
 * per-person feed of what someone has been photographing and reading in their
 * own home is a different and much larger power — one this product has no
 * reason to hand out before it has even a login. Aggregate figures live on the
 * library rows, where they describe a collection rather than a person.
 *
 * ⚠ **Nothing here is editable, because nothing CAN be.** There is no route to
 * invite, remove or re-role anybody, in either service. That is a real gap
 * (P4.1's login, P4.3's invite flow), and it is stated on the Access screen
 * rather than mocked up here as a control that would do nothing.
 */
import { formatDate, libraryName } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { href } from '../lib/route'
import { OpenServiceWarning } from '../lib/StaffToken'
import { useSystem } from '../lib/system'
import { Empty, ErrorBox, Loading } from '../lib/ui'

export function UsersPage() {
  const { t, lang } = useI18n()
  const { accounts, overview, loading, error, reload, labelOf } = useSystem()

  if (loading) return <Loading />
  if (!overview && error) return <ErrorBox message={error} onRetry={reload} />

  return (
    <>
      <h1>{t.users_title}</h1>
      <p className="sub">{t.users_sub}</p>

      {overview && !overview.authenticated && <OpenServiceWarning />}
      <p className="note">{t.acc_two_admins}</p>

      {accounts.length === 0 ? (
        <Empty>{t.users_empty}</Empty>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.th_account}</th>
                <th>{t.th_email}</th>
                <th>{t.th_memberships}</th>
                <th>{t.th_created}</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => (
                <tr key={account.id}>
                  <td className="rtl-safe">
                    <div className="t">
                      {account.display_name.trim()
                        || <span className="a">{t.users_unnamed}</span>}
                    </div>
                    <div className="mono">{account.id}</div>
                  </td>
                  {/* Optional and unused until P4.1 — there is no login yet, so
                      a dev-trusted principal has no address to give. Blank is
                      the normal state, not a missing value. */}
                  <td className="mono">{account.email || '—'}</td>
                  <td className="rtl-safe">
                    {account.memberships.length === 0 ? (
                      <span className="a">{t.users_no_memberships}</span>
                    ) : (
                      account.memberships.map((m) => (
                        <div key={m.library_id}>
                          <a href={href({ name: 'library', id: m.library_id })}>
                            {libraryName(labelOf(m.library_id), t.lib_unnamed)}
                          </a>{' '}
                          <span className="badge role">{m.role}</span>
                        </div>
                      ))
                    )}
                  </td>
                  <td>{formatDate(account.created_at, lang) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
