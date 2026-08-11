/**
 * System-wide totals, and the same numbers per library.
 *
 * ⚠ Every figure now comes from ONE cross-tenant request
 * (`GET /api/staff/v1/overview` + `/libraries`), not from a fan-out over the
 * libraries the operator happens to belong to. That is the difference between
 * an account console and a system one: the earlier version could only ever add
 * up its own memberships and called the result "the system", which was true
 * for exactly one account and quietly wrong for any other.
 */
import { formatDate, formatNumber, libraryName } from '@booksnap/ui'
import { useI18n } from '../lib/i18n'
import { href } from '../lib/route'
import { OpenServiceWarning } from '../lib/StaffToken'
import { useSystem } from '../lib/system'
import { Empty, ErrorBox, Loading } from '@booksnap/ui'
import { formatBytes, StatCard } from '../lib/ui'


export function Dashboard() {
  const { t, lang } = useI18n()
  const { overview, libraries, loading, error, reload } = useSystem()

  if (loading) return <Loading />
  if (!overview) {
    return <ErrorBox message={error ?? t.staff_unreachable} onRetry={reload} />
  }

  const num = (n: number) => formatNumber(n, lang)

  return (
    <>
      <h1>{t.dash_title}</h1>
      <p className="sub">{t.sys_scope}</p>

      {!overview.authenticated && <OpenServiceWarning />}
      {overview.orphan_libraries.length > 0 && (
        <p className="note warn">{t.sys_orphans(overview.orphan_libraries.length)}</p>
      )}

      <div className="stats">
        {/* ⚠ `users` is the PEOPLE count and `libraries` is the account
            count, because the console renamed the tenant and the wire did
            not — see `AccountsPage`. Labelled so the two cannot be read as
            one number reported twice. */}
        <StatCard label={t.stat_accounts_tenants} value={num(overview.libraries)} />
        <StatCard label={t.stat_people} value={num(overview.users)} />
        <StatCard label={t.stat_memberships} value={num(overview.memberships)} />
        <StatCard label={t.stat_books} value={num(overview.books)} />
        <StatCard label={t.stat_copies} value={num(overview.copies)} />
        {/* Warning tone: an unapproved book is a claim nobody has said yes to,
            which is the one number here that asks someone to act. §5.1's
            ladder puts `manual` ABOVE approved, so this is `auto` alone. */}
        <StatCard label={t.stat_unapproved} warn value={num(overview.auto)} />
        <StatCard label={t.stat_approved} value={num(overview.approved)} />
        <StatCard label={t.stat_manual} value={num(overview.manual)} />
        {/* ⚠ Images, not shelves. A shelf today is an identity minted per
            photograph (VISION §4.1a), so a shelf count on a system dashboard
            was a photograph count wearing the wrong noun — and the storage
            figure beside it is the one an operator actually acts on. */}
        <StatCard label={t.th_images} value={num(overview.captures)} />
        <StatCard label={t.th_storage}
                  value={overview.blobs_visible
                    ? formatBytes(overview.image_bytes, lang) : '—'} />
        <StatCard label={t.stat_reads} value={num(overview.reads)} />
        <StatCard label={t.stat_duplicates} warn={overview.duplicates > 0}
                  value={num(overview.duplicates)} />
        <StatCard label={t.stat_lent} value={num(overview.lent_out)} />
      </div>

      {!overview.blobs_visible && <p className="note warn">{t.img_blind}</p>}

      <h2>{t.dash_per_account}</h2>
      {libraries.length === 0 ? (
        <Empty>{t.lib_empty}</Empty>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.th_account}</th>
                <th className="num">{t.th_users}</th>
                <th className="num">{t.th_books}</th>
                <th className="num">{t.stat_unapproved}</th>
                <th className="num">{t.th_images}</th>
                <th className="num">{t.th_storage}</th>
                <th className="num">{t.th_duplicates}</th>
                <th className="num">{t.th_lent}</th>
                <th>{t.th_activity}</th>
              </tr>
            </thead>
            <tbody>
              {libraries.map((lib) => (
                <tr key={lib.id}>
                  <td className="rtl-safe">
                    <a href={href({ name: 'account', id: lib.id })}>
                      {libraryName(lib.label, t.lib_unnamed)}
                    </a>
                    {/* An account with no members is the one anomaly this
                        table can surface that no household screen can. */}
                    {lib.members === 0 && <> <span className="badge">!</span></>}
                  </td>
                  <td className="num">{num(lib.members)}</td>
                  <td className="num">{num(lib.books)}</td>
                  <td className="num">{num(lib.auto)}</td>
                  <td className="num">{num(lib.captures)}</td>
                  <td className="num">{formatBytes(lib.image_bytes, lang)}</td>
                  <td className="num">{num(lib.duplicates)}</td>
                  <td className="num">{num(lib.lent_out)}</td>
                  <td>{formatDate(lib.last_activity, lang) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
