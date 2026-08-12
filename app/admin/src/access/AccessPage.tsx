/**
 * What this console is, what protects it, and — precisely — what it cannot do.
 *
 * ⚠⚠ **There are TWO admin jobs and this tool is only one of them.** Naming
 * them apart is the whole point of this screen:
 *
 *   - **system admin** — this tool. Sees every tenant, is a member of none.
 *     Not a `Role`: `app.domain.tenancy.Role` says who you are *within one
 *     account*, so putting `SYSTEM_ADMIN` in that enum would make every
 *     membership row a place someone could grant themselves the world. It is a
 *     property of the operator, carried today by a shared token on a separate
 *     service;
 *   - **account admin** — `Role.ADMIN` on a membership. Held per ACCOUNT
 *     since P3.7b, so it covers every library that customer owns, and the
 *     one who invites family members. That job has no UI anywhere yet,
 *     because the server has no invite route (P4.1's login, P4.3's flow).
 *
 * ⚠ The gaps below are listed rather than mocked up. A greyed-out invite
 * button that never becomes clickable reads as a bug; a sentence naming what
 * would unblock it reads as a product that has not grown that far — which is
 * the truth.
 */
import { getStaffToken } from '../api/staff'
import { formatDate } from '@booksnap/ui'
import { useI18n } from '../lib/i18n'
import { href } from '../lib/route'
import { StaffTokenForm } from '../lib/StaffToken'
import { useSystem } from '../lib/system'
import { LibraryName } from '../lib/ui'
import { Empty, ErrorBox, Loading } from '@booksnap/ui'

export function AccessPage() {
  const { t, lang } = useI18n()
  const { overview, mine, loading, error, reload } = useSystem()

  if (loading) return <Loading />

  return (
    <>
      <h1>{t.acc_title}</h1>

      {error && <ErrorBox message={error} onRetry={reload} />}

      <h2>{t.token_title}</h2>
      {overview?.authenticated ? (
        <p className="note">✓ {t.token_ok}</p>
      ) : overview ? (
        // Serving with no token configured is the DANGEROUS success case: the
        // console works, and so would anyone else's browser on the LAN.
        <p className="note warn">{t.token_open_warning}</p>
      ) : null}
      <StaffTokenForm onSaved={reload} />
      {getStaffToken() && <p className="sub">✓ {t.token_ok}</p>}

      <h2>{t.acc_system_admin} · {t.acc_account_admin}</h2>
      <p className="note">{t.acc_two_admins}</p>

      <h2>{t.acc_memberships}</h2>
      <p className="sub">{t.lib_mine}</p>
      {mine.length === 0 ? (
        <Empty>{t.lib_empty}</Empty>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.th_library}</th>
                <th>{t.th_role}</th>
                <th>{t.th_created}</th>
              </tr>
            </thead>
            <tbody>
              {mine.map((lib) => (
                <tr key={lib.id}>
                  <td className="rtl-safe">
                    {/* ⚠ Links by `account_id`, not by the library's own id.
                        The drawer behind that route is a CUSTOMER's, and the
                        operator's membership is held there — one link per
                        collection all landing on the same account is correct,
                        because that is precisely what a role covering every
                        library of an account means. */}
                    <a href={href({ name: 'account', id: lib.account_id })}>
                      <LibraryName libraryId={lib.id} />
                    </a>
                    <div className="mono">{lib.id}</div>
                  </td>
                  {/* REPORTED, never edited: §4.2's matrix is not enforced
                      anywhere yet (P3.2), so a control that changed a role
                      would be changing a label, not a permission. And the role
                      is the ACCOUNT's since P3.7b — two libraries of one
                      customer always show the same badge. */}
                  <td><span className="badge role">{lib.role}</span></td>
                  <td>{formatDate(lib.created_at, lang) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>{t.acc_gap_title}</h2>
      <div className="note">
        <p style={{ marginTop: 0 }}>{t.acc_gap_intro}</p>
        <ul>
          <li>{t.acc_gap_invite}</li>
          <li>{t.acc_gap_roles}</li>
          <li>{t.acc_gap_list}</li>
          <li>{t.acc_gap_delete}</li>
        </ul>
        {/* ⚠ Read off the OVERVIEW, all three, rather than measuring one of
            them by the length of a list this screen happens to hold. The old
            call passed `users.length` into a slot labelled "accounts" and
            `overview.libraries` into one labelled "libraries" — two names for
            what was then one entity, and since P3.7b they are three. */}
        <p>{t.acc_gap_counts(overview?.accounts ?? 0, overview?.users ?? 0,
                             overview?.libraries ?? 0)}</p>
      </div>

      <p className="note warn">{t.acc_no_auth}</p>
    </>
  )
}
