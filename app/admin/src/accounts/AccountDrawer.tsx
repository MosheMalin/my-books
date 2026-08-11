/**
 * One account, in three sections — the owner's own shape for it:
 *
 *   > Upon clicking on an account we can see a drawer with more info: users
 *   > section, books section, images section.
 *
 * ⚠ A DRAWER, not a page. It was a page (`LibraryDetail`) and the route is
 * still deep-linkable (`#/accounts/<id>`), but the list stays behind it: an
 * operator comparing customers loses their place every time they open one, and
 * "back to accounts" is a worse answer than never leaving.
 *
 * ⚠ **Read-only, and not because nobody got to it.** The staff service does not
 * write; renaming and exporting live on the row, through the product API, where
 * membership resolves them. Member management — invite, remove, re-role — has
 * no route in EITHER service: it needs P4.1's login to have anyone to invite
 * and P4.3's flow to invite them with. Absent, not mocked as a dead control.
 *
 * ⚠ **Reported, not profiled.** The Users section shows identity, role and
 * join date, never a per-person feed of what somebody has been photographing
 * in their own home. That is a much larger power than counting, and this
 * product has no login, audit trail or consent story to justify it. The
 * aggregate figures describe a collection, not a person.
 */
import { listImages, listAllBooks } from '../api/staff'
import { useI18n } from '../lib/i18n'
import { href } from '../lib/route'
import { useSystem } from '../lib/system'
import { formatBytes, StatCard } from '../lib/ui'
import type { StaffLibrary } from '../api/staff'
import {
  Empty, ErrorBox, Loading, StatusBadge, formatDate, formatDateTime,
  formatNumber, libraryName, useAsync,
} from '@booksnap/ui'

/** How much of each section the drawer shows before handing over to its tab.
 *  A drawer is for "what is this account like", not for browsing. */
const PREVIEW = 5

export function AccountDrawer({ library, onClose }: {
  library: StaffLibrary
  onClose: () => void
}) {
  const { t, lang } = useI18n()
  const { accounts } = useSystem()

  const books = useAsync(
    (signal) => listAllBooks({ libraryId: library.id, sort: 'recently_added',
                               ascending: false, limit: PREVIEW }, { signal }),
    [library.id],
  )
  const images = useAsync(
    (signal) => listImages({ libraryId: library.id, limit: PREVIEW }, { signal }),
    [library.id],
  )

  const num = (n: number) => formatNumber(n, lang)
  const members = accounts.flatMap((account) => {
    const m = account.memberships.find((x) => x.library_id === library.id)
    return m ? [{ account, membership: m }] : []
  })

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="panel wide" role="dialog" aria-label={t.acct_panel}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <strong>{t.acct_panel}</strong>
          <button type="button" className="btn small" autoFocus onClick={onClose}>
            {t.close}
          </button>
        </div>

        <h2 className="rtl-safe" style={{ margin: '12px 0 2px' }}>
          {libraryName(library.label, t.lib_unnamed)}
        </h2>
        {/* ⚠ The library id, LABELLED as such. The console calls this row an
            account; the storage calls it a library. Showing the mapping is
            what keeps that a naming choice rather than a lie — see
            `AccountsPage`'s note. */}
        <div className="sub">
          {t.acct_library_id}: <span className="mono">{library.id}</span>
        </div>
        <div className="sub">
          {t.th_created}: {formatDate(library.created_at, lang) || '—'}
        </div>

        <div className="stats" style={{ marginTop: 12 }}>
          <StatCard label={t.th_users} value={num(library.members)} />
          <StatCard label={t.stat_books} value={num(library.books)} />
          <StatCard label={t.stat_unapproved} warn value={num(library.auto)} />
          <StatCard label={t.th_images} value={num(library.captures)} />
          <StatCard label={t.th_storage} value={formatBytes(library.image_bytes, lang)} />
          <StatCard label={t.stat_reads} value={num(library.reads)} />
          <StatCard label={t.stat_duplicates} warn={library.duplicates > 0}
                    value={num(library.duplicates)} />
          <StatCard label={t.stat_lent} value={num(library.lent_out)} />
        </div>

        <h3>{t.acct_users}</h3>
        {members.length === 0 ? (
          // ⚠ Not merely empty: `new_library` mints an admin membership in the
          // same call precisely so this cannot happen. An account with no
          // member is one nobody can see or administer.
          <p className="note warn">{t.ld_no_members}</p>
        ) : (
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>{t.th_account}</th>
                  <th>{t.th_role}</th>
                  <th>{t.acct_joined}</th>
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
        <p className="note">{t.acct_no_member_management}</p>

        <h3>{t.acct_books}</h3>
        {books.error && <ErrorBox message={books.error} onRetry={books.reload} />}
        {books.loading && <Loading />}
        {books.data && (books.data.items.length === 0 ? (
          <Empty>{t.books_empty}</Empty>
        ) : (
          <>
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>{t.th_title}</th>
                    <th>{t.th_status}</th>
                    <th>{t.th_added}</th>
                  </tr>
                </thead>
                <tbody>
                  {books.data.items.map((book) => (
                    <tr key={book.id}>
                      <td className="rtl-safe">
                        <div className="t">{book.title}</div>
                        <div className="a">{book.author}</div>
                      </td>
                      <td><StatusBadge status={book.status} /></td>
                      <td>{formatDate(book.added_at, lang) || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* ⚠ The books TAB is the catalogue — one row per work, across
                every tenant. This link narrows it to the account, which is a
                filter and not a different screen. */}
            <p className="row">
              <a className="btn small" href={href({ name: 'books', libraryId: library.id })}>
                {t.acct_all_books(library.books)}
              </a>
            </p>
          </>
        ))}

        <h3>{t.acct_images}</h3>
        {images.error && <ErrorBox message={images.error} onRetry={images.reload} />}
        {images.loading && <Loading />}
        {images.data && (images.data.items.length === 0 ? (
          <Empty>{t.img_empty}</Empty>
        ) : (
          <>
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>{t.img_taken}</th>
                    <th>{t.img_filed_at}</th>
                    <th className="num">{t.th_findings}</th>
                  </tr>
                </thead>
                <tbody>
                  {images.data.items.map((image) => (
                    <tr key={image.id}>
                      <td>{formatDateTime(image.captured_at, lang) || t.img_undated}</td>
                      <td className="rtl-safe a">
                        {image.shelf_label.trim() || t.lib_unnamed}
                        {' · '}{t.img_depth_n(image.depth)}
                      </td>
                      <td className="num">{num(image.findings)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="row">
              <a className="btn small" href={href({ name: 'images', libraryId: library.id })}>
                {t.acct_all_images(library.captures)}
              </a>
            </p>
          </>
        ))}
      </aside>
    </>
  )
}
