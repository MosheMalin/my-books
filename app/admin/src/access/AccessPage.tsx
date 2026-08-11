/**
 * What this console is, what protects it, and — precisely — what it cannot do.
 *
 * ⚠⚠ **There are TWO admin jobs and this tool is only one of them.** Naming
 * them apart is the whole point of this screen:
 *
 *   - **system admin** — this tool. Sees every tenant, is a member of none.
 *     Not a `Role`: `app.domain.tenancy.Role` says who you are *within one
 *     library*, so putting `SYSTEM_ADMIN` in that enum would make every
 *     membership row a place someone could grant themselves the world. It is a
 *     property of the operator, carried today by a shared token on a separate
 *     service;
 *   - **account admin** — `Role.ADMIN` on a membership. Scoped to one library,
 *     and the one who invites family members. That job has no UI anywhere yet,
 *     because the server has no invite route (P4.1's login, P4.3's flow).
 *
 * ⚠ The gaps below are listed rather than mocked up. A greyed-out invite
 * button that never becomes clickable reads as a bug; a sentence naming what
 * would unblock it reads as a product that has not grown that far — which is
 * the truth.
 */
import { getStaffToken } from '../api/staff'
import { formatDate, libraryName } from '@booksnap/ui'
import { useI18n } from '../lib/i18n'
import { href } from '../lib/route'
import { StaffTokenForm } from '../lib/StaffToken'
import { useSystem } from '../lib/system'
import { Empty, ErrorBox, Loading } from '@booksnap/ui'

export function AccessPage() {
  const { t, lang } = useI18n()
  const { overview, mine, accounts, loading, error, reload } = useSystem()

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
                    <a href={href({ name: 'account', id: lib.id })}>
                      {libraryName(lib.label, t.lib_unnamed)}
                    </a>
                    <div className="mono">{lib.id}</div>
                  </td>
                  {/* REPORTED, never edited: §4.2's matrix is not enforced
                      anywhere yet (P3.2), so a control that changed a role
                      would be changing a label, not a permission. */}
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
        <p>{t.acc_gap_counts(accounts.length, overview?.libraries ?? 0)}</p>
      </div>

      <p className="note warn">{t.acc_no_auth}</p>
    </>
  )
}
