/**
 * One library: its numbers, who belongs to it, its shelves, and what has been
 * read lately — all cross-tenant, so all from the staff service.
 *
 * ⚠ The earlier version of this screen fetched shelves and reads through
 * `/api/v1`, which meant it worked for the operator's OWN libraries and
 * silently 404'd for anybody else's. A system console that can only open one
 * household's shelf list is an account console with a misleading title.
 *
 * ⚠ It is also read-only, and that is not an oversight: the staff service does
 * not write. Acting on a shelf or a read is the household's own job, in the
 * product client, by someone who is a member.
 */
import { listLibraryShelves, listRecentReads } from '../api/staff'
import { formatDate, formatDateTime, formatNumber, libraryName } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { href } from '../lib/route'
import { useSystem } from '../lib/system'
import { useAsync } from '../lib/useAsync'
import { Empty, ErrorBox, Loading, StatCard } from '../lib/ui'

/** A shelf photographed weekly for a year is 50+ reads; this table answers
 *  "what has been happening lately", not "everything that ever happened". */
const RECENT_READS = 20

export function LibraryDetail({ libraryId }: { libraryId: string }) {
  const { t, lang } = useI18n()
  const { libraries, accounts, loading, error, reload } = useSystem()
  const library = libraries.find((l) => l.id === libraryId)

  const shelves = useAsync(
    (signal) => listLibraryShelves(libraryId, { signal }), [libraryId])
  const reads = useAsync(
    (signal) => listRecentReads(RECENT_READS, libraryId, { signal }), [libraryId])

  if (loading) return <Loading />
  if (!library) {
    return <ErrorBox message={error ?? t.staff_unreachable} onRetry={reload} />
  }

  const num = (n: number) => formatNumber(n, lang)
  const members = accounts.flatMap((account) => {
    const m = account.memberships.find((x) => x.library_id === libraryId)
    return m ? [{ account, membership: m }] : []
  })

  return (
    <>
      <p className="sub" style={{ marginBottom: 4 }}>
        <a href={href({ name: 'libraries' })}>← {t.ld_back}</a>
      </p>
      <h1 className="rtl-safe">{libraryName(library.label, t.lib_unnamed)}</h1>
      <p className="sub mono">{libraryId}</p>

      <div className="stats">
        <StatCard label={t.stat_books} value={num(library.books)} />
        <StatCard label={t.stat_unapproved} warn value={num(library.auto)} />
        <StatCard label={t.stat_approved} value={num(library.approved)} />
        <StatCard label={t.stat_manual} value={num(library.manual)} />
        <StatCard label={t.stat_copies} value={num(library.copies)} />
        <StatCard label={t.stat_shelves} value={num(library.shelves)} />
        <StatCard label={t.stat_photos} value={num(library.captures)} />
        <StatCard label={t.stat_reads} value={num(library.reads)} />
        <StatCard label={t.stat_duplicates} warn={library.duplicates > 0}
                  value={num(library.duplicates)} />
        <StatCard label={t.stat_lent} value={num(library.lent_out)} />
      </div>

      <p className="row" style={{ marginTop: 12 }}>
        <a className="btn small" href={href({ name: 'books', libraryId })}>
          {t.nav_books}
        </a>
      </p>

      <h2>{t.ld_members}</h2>
      {members.length === 0 ? (
        // ⚠ Not merely empty: `new_library` mints an admin membership in the
        // same call precisely so this cannot happen. A library with no members
        // is one nobody can see or administer.
        <p className="note warn">{t.ld_no_members}</p>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.th_account}</th>
                <th>{t.th_role}</th>
                <th>{t.th_created}</th>
              </tr>
            </thead>
            <tbody>
              {members.map(({ account, membership }) => (
                <tr key={account.id}>
                  <td className="rtl-safe">
                    {account.display_name.trim()
                      || <span className="a">{t.users_unnamed}</span>}
                    <div className="mono">{account.id}</div>
                  </td>
                  <td><span className="badge role">{membership.role}</span></td>
                  <td>{formatDate(membership.joined_at, lang) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>{t.ld_shelves}</h2>
      {shelves.error && <ErrorBox message={shelves.error} onRetry={shelves.reload} />}
      {shelves.loading && <Loading />}
      {shelves.data && (shelves.data.length === 0 ? (
        <Empty>{t.ld_no_shelves}</Empty>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.th_shelf}</th>
                <th className="num">{t.ld_depth}</th>
                <th className="num">{t.ld_captures}</th>
                <th className="num">{t.ld_books_here}</th>
                <th>{t.ld_last_read}</th>
              </tr>
            </thead>
            <tbody>
              {shelves.data.map((shelf) => (
                <tr key={shelf.id}>
                  <td className="rtl-safe">
                    {/* An unnamed shelf is NORMAL (P2.1: identity is free, and
                        one is usually recognised by its own photograph). It
                        still needs a word here — this is a table, and there is
                        no photograph. */}
                    {shelf.label.trim() || <span className="a">{t.lib_unnamed}</span>}
                    {shelf.virtual && <> <span className="badge">{t.ld_wishlist}</span></>}
                    <div className="mono">{shelf.id}</div>
                  </td>
                  <td className="num">{shelf.depth_count}</td>
                  <td className="num">{shelf.captures}</td>
                  <td className="num">{shelf.books}</td>
                  <td>
                    {shelf.last_read
                      ? formatDate(shelf.last_read, lang)
                      : <span className="a">{t.ld_never_read}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      <h2>{t.ld_reads}</h2>
      {reads.error && <ErrorBox message={reads.error} onRetry={reads.reload} />}
      {reads.data && (reads.data.length === 0 ? (
        <Empty>{t.ld_no_reads}</Empty>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.th_created}</th>
                <th>{t.th_shelf}</th>
                <th className="num">{t.ld_depth}</th>
                <th>{t.th_status}</th>
                <th className="num">{t.th_findings}</th>
              </tr>
            </thead>
            <tbody>
              {reads.data.map((read) => (
                <tr key={read.id}>
                  <td>{formatDateTime(read.started_at, lang) || '—'}</td>
                  <td className="rtl-safe">
                    {read.shelf_label.trim()
                      || <span className="a">{t.lib_unnamed}</span>}
                    {/* The engine mode, never a run number: §5.5 is explicit
                        that a run is not a user-facing concept, and
                        `app.domain.read.Read` has no human handle to show. */}
                    <div className="a">{read.mode}</div>
                  </td>
                  <td className="num">{read.depth}</td>
                  <td><span className="badge">{read.status}</span></td>
                  <td className="num">{read.claims}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </>
  )
}
