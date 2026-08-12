/**
 * One customer, in four sections — the owner's own shape for it, with the
 * level P3.7e put back:
 *
 *   > Upon clicking on an account we can see a drawer with more info: users
 *   > section, books section, images section.
 *
 * **account → its libraries → users / books / images.** The libraries section
 * is the one this drawer did not have, because until P3.7b the account WAS a
 * library and there was nothing to list. It replaces `t.acct_library_id` — the
 * label that used to sit under the name reading *"library id"*, whose whole
 * job was to admit that the console said "account" and the storage said
 * something else. That admission is not relabelled, it is **deleted**: the
 * mapping is data now, and every collection has its own row carrying its own
 * id.
 *
 * ⚠ A DRAWER, not a page. It was a page (`LibraryDetail`) and the route is
 * still deep-linkable (`#/accounts/<id>`), but the list stays behind it: an
 * operator comparing customers loses their place every time they open one, and
 * "back to accounts" is a worse answer than never leaving.
 *
 * ⚠ **Read-only about PEOPLE, and not because nobody got to it.** Member
 * management — invite, remove, re-role — has no route in EITHER service: it
 * needs P4.1's login to have anyone to invite and P4.3's flow to invite them
 * with. Absent, not mocked as a dead control. What IS writable is a library's
 * name and its exports, through the product API, where membership resolves
 * them — so those controls sit on the library rows and only where the operator
 * is a member.
 *
 * ⚠ **Reported, not profiled.** The Users section shows identity, role and
 * join date, never a per-person feed of what somebody has been photographing
 * in their own home. That is a much larger power than counting, and this
 * product has no login, audit trail or consent story to justify it. The
 * aggregate figures describe a collection, not a person.
 */
import { useEffect, useRef, useState } from 'react'

import { renameLibrary, exportUrl } from '../api/client'
import { listImages, listAllBooks } from '../api/staff'
import { useI18n } from '../lib/i18n'
import { href } from '../lib/route'
import { useSystem } from '../lib/system'
import { formatBytes, StatCard } from '../lib/ui'
import type { StaffAccount, StaffBook, StaffImage, StaffLibrary } from '../api/staff'
import {
  Empty, ErrorBox, Loading, StatusBadge, formatDate, formatDateTime,
  formatNumber, libraryName, useAsync,
} from '@booksnap/ui'

/** How much of each section the drawer shows before handing over to its tab.
 *  A drawer is for "what is this account like", not for browsing. */
const PREVIEW = 5

/**
 * Newest first, over rows gathered from SEVERAL libraries of one account.
 *
 * ⚠ This is not the browser-side merge revision 2 retired. That one PAGED and
 * RANKED a whole catalogue with `localeCompare`, which is a different key from
 * the server's normalized one, so the merged order genuinely differed from a
 * single library's and the screen had to apologise for it. This orders ≤5 rows
 * per library on an ISO-8601 timestamp — a total order the server would
 * produce identically. What it cannot do is page, which is why there is no
 * pager here and the browse links below are per library.
 *
 * Undated rows sort LAST rather than first: `null` means the field was never
 * recorded, and letting "unknown" win a "most recent" list would put the
 * oldest imports at the top of every customer's drawer.
 */
export function newestFirst<T>(rows: T[], at: (row: T) => string | null | undefined): T[] {
  return [...rows].sort((a, b) => {
    const x = at(a) ?? ''
    const y = at(b) ?? ''
    if (x === y) return 0
    if (!x) return 1
    if (!y) return -1
    return x < y ? 1 : -1
  })
}

/**
 * ⚠ Holds the text being typed and NOT an "am I editing" flag — the section
 * owns that, one row at a time. An earlier version kept both and they
 * disagreed: the page opened the editor while the cell, still `false`,
 * rendered the read view, so rename silently did nothing.
 */
function RenameCell({ library, onRenamed, onCancel }: {
  library: StaffLibrary
  onRenamed: () => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const [label, setLabel] = useState(library.label)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)

  const save = async () => {
    setBusy(true)
    setError(undefined)
    try {
      await renameLibrary(library.id, label)
      onRenamed()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <input type="text" value={label} autoFocus className="rtl-safe"
             aria-label={t.lib_name}
             onChange={(e) => setLabel(e.target.value)} />
      <div className="row" style={{ marginTop: 6 }}>
        <button type="button" className="btn small primary"
                disabled={busy || !label.trim()} onClick={save}>
          {t.save}
        </button>
        <button type="button" className="btn small" onClick={onCancel}>
          {t.cancel}
        </button>
      </div>
      {error && <ErrorBox message={error} />}
    </div>
  )
}

export function AccountDrawer({ account, libraries, onChanged, onClose }: {
  account: StaffAccount
  /** The collections this customer owns. Passed in rather than looked up so
   *  the drawer cannot disagree with the row that opened it. */
  libraries: StaffLibrary[]
  /** Refetch the system lists. ⚠ It must reload the PROVIDER, not just this
   *  drawer: a rename changes a label the account row renders too, and an A3
   *  review already caught a version of this screen refetching the list while
   *  leaving the open drawer stale. Both read the same provider state, so one
   *  reload settles both. */
  onChanged: () => void
  onClose: () => void
}) {
  const { t, lang } = useI18n()
  const { canWrite, membersOf, peopleKnown } = useSystem()
  const [editingId, setEditingId] = useState<string | undefined>(undefined)

  // ⚠ Escape closes it, like `WorkPanel` and `ImagePanel`. This drawer carries
  // `role="dialog"`, so announcing itself as one and then not behaving like
  // the console's other two is a promise it breaks — and P3.7e made it the
  // primary surface. Installed ONCE behind a ref: an effect depending on
  // `onClose` re-runs every commit (a fresh closure each render), which is
  // exactly how a sibling panel's reset effect was silently defeated.
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // ⚠ Keyed by the library IDS, not by the array: `librariesOf` builds a fresh
  // array every render, so an array in the dep list would refetch forever.
  const scope = libraries.map((l) => l.id).join(',')

  const books = useAsync(
    async (signal) => {
      const pages = await Promise.all(libraries.map((lib) =>
        listAllBooks({ libraryId: lib.id, sort: 'recently_added',
                       ascending: false, limit: PREVIEW }, { signal })))
      return newestFirst(pages.flatMap((p) => p.items), (b) => b.added_at)
        .slice(0, PREVIEW)
    },
    [scope],
  )
  const images = useAsync(
    // ⚠⚠ `/images` takes NO sort parameter, so unlike the books call above
    // this one cannot ask for the order it depends on. Taking the newest five
    // of a union is correct only if each page is that library's newest first,
    // which is `app/staff_api/queries.py`'s constant `ORDER BY
    // COALESCE(captured_at,'') DESC, id DESC`. That used to be a client
    // argument resting on a server constant nothing named — the shape of
    // `MAX_SCORE` tracking `match.py` — so
    // `test_staff_api.py:test_images_come_back_newest_first_with_undated_last`
    // now pins it. Change the ORDER BY and that test says so.
    async (signal) => {
      const pages = await Promise.all(libraries.map((lib) =>
        listImages({ libraryId: lib.id, limit: PREVIEW }, { signal })))
      return newestFirst(pages.flatMap((p) => p.items), (i) => i.captured_at)
        .slice(0, PREVIEW)
    },
    [scope],
  )

  const num = (n: number) => formatNumber(n, lang)
  const labelOfLib = (id: string) => {
    const lib = libraries.find((l) => l.id === id)
    return libraryName(lib?.label, t.lib_unnamed)
  }
  // Everyone who belongs to this CUSTOMER, folded by the provider — one copy
  // of the rule, shared with the accounts table's admin column.
  const members = membersOf(account.id)

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
          {libraryName(account.label, t.acct_unnamed)}
        </h2>
        {/* The account's own id, unlabelled — an id in mono under a name needs
            no label. What needed one was the MAPPING, and there is no longer a
            mapping to explain: the libraries below carry their own ids. */}
        <div className="sub mono">{account.id}</div>
        <div className="sub">
          {t.th_created_m}: {formatDate(account.created_at, lang) || '—'}
        </div>

        <div className="stats" style={{ marginTop: 12 }}>
          <StatCard label={t.th_users} value={num(account.members)} />
          <StatCard label={t.th_libraries} value={num(account.libraries)} />
          <StatCard label={t.stat_books} value={num(account.books)} />
          <StatCard label={t.stat_unapproved} warn value={num(account.auto)} />
          <StatCard label={t.th_images} value={num(account.captures)} />
          <StatCard label={t.th_storage} value={formatBytes(account.image_bytes, lang)} />
          <StatCard label={t.stat_reads} value={num(account.reads)} />
          <StatCard label={t.stat_duplicates} warn={account.duplicates > 0}
                    value={num(account.duplicates)} />
          <StatCard label={t.stat_lent} value={num(account.lent_out)} />
        </div>

        <h3>{t.th_libraries}</h3>
        <p className="sub">{t.acct_lib_sub}</p>
        {libraries.length === 0 ? (
          // ⚠⚠ TWO different states, and conflating them printed a flat
          // contradiction: with `/libraries` down the drawer said "this
          // account keeps no library" three lines under a stat card reading
          // 2. `account.libraries` comes from the SAME row that opened the
          // drawer, so it is the one figure that cannot be missing here.
          // Zero is a real state — `/accounts` lists a customer created
          // before its first collection as a row of zeroes, P4.3's normal
          // onboarding path. Silence from a failed request is not.
          account.libraries === 0
            ? <Empty>{t.acct_lib_none}</Empty>
            : <p className="note warn">{t.acct_libs_unknown}</p>
        ) : (
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  {/* ⚠ `th_library`. These rows ARE libraries — the entity the
                      account owns — and no column here reports `members` or
                      `admins`: both belong to the account above, and printing
                      them per collection would show one household once per
                      shelf it keeps. */}
                  <th>{t.th_library}</th>
                  <th className="num">{t.th_books}</th>
                  <th className="num">{t.th_images}</th>
                  <th className="num">{t.th_storage}</th>
                  <th>{t.th_created}</th>
                </tr>
              </thead>
              <tbody>
                {libraries.map((lib) => {
                  const writable = canWrite(lib.id)
                  return (
                    <tr key={lib.id}>
                      {/* ⚠⚠ The actions live INSIDE the name cell, on their
                          own line, rather than in a trailing column. A drawer
                          is capped at `min(720px, 100%)` and the six-column
                          version measured 834px wide, which put rename and
                          both exports outside the box at `scrollLeft: 0` —
                          absent from the accessibility tree until the table
                          was scrolled sideways. That is worse than where they
                          came from: this item MOVED them here from a
                          full-width table, so the fix cannot be "scroll to
                          find them". Stacking under the name is the shape the
                          rename editor already uses. */}
                      <td className="rtl-safe">
                        {editingId === lib.id && writable ? (
                          <RenameCell
                            library={lib}
                            onCancel={() => setEditingId(undefined)}
                            onRenamed={() => { setEditingId(undefined); onChanged() }}
                          />
                        ) : (
                          <>
                            {libraryName(lib.label, t.lib_unnamed)}
                            {writable && <> <span className="badge role">{t.lib_mine}</span></>}
                            <div className="mono">{lib.id}</div>
                            <div className="row" style={{ marginTop: 6 }}>
                              <a className="btn small"
                                 aria-label={t.acct_books_of(labelOfLib(lib.id))}
                                 href={href({ name: 'books', libraryId: lib.id })}>
                                {t.nav_books}
                              </a>
                              <a className="btn small"
                                 aria-label={t.acct_images_of(labelOfLib(lib.id))}
                                 href={href({ name: 'images', libraryId: lib.id })}>
                                {t.nav_images}
                              </a>
                              {writable ? (
                                <>
                                  <button type="button" className="btn small"
                                          aria-label={t.lib_rename_of(labelOfLib(lib.id))}
                                          onClick={() => setEditingId(lib.id)}>
                                    {t.lib_rename}
                                  </button>
                                  {/* Downloads, so real links: letting the
                                      browser handle Content-Disposition is
                                      what makes "Save as…" work. The library
                                      rides in the QUERY string because an
                                      <a href> cannot carry a header. */}
                                  <a className="btn small"
                                     aria-label={t.lib_csv_of(labelOfLib(lib.id))}
                                     href={exportUrl(lib.id, 'csv')}>
                                    {t.lib_export_csv}
                                  </a>
                                  <a className="btn small"
                                     aria-label={t.lib_json_of(labelOfLib(lib.id))}
                                     href={exportUrl(lib.id, 'json')}>
                                    {t.lib_export_json}
                                  </a>
                                </>
                              ) : (
                                <span className="a">{t.lib_readonly}</span>
                              )}
                            </div>
                          </>
                        )}
                      </td>
                      <td className="num">{num(lib.books)}</td>
                      <td className="num">{num(lib.captures)}</td>
                      <td className="num">{formatBytes(lib.image_bytes, lang)}</td>
                      <td>{formatDate(lib.created_at, lang) || '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* ⚠ Follows its subject. This note sat at the bottom of the
            accounts table, which no longer has a library on it. */}
        <p className="note">{t.lib_no_delete}</p>

        <h3>{t.acct_users}</h3>
        {members.length === 0 ? (
          // ⚠⚠ The alarm is gated on `account.members`, not on the fold being
          // empty. "Nobody can see or administer this account" is a state
          // `new_account` and `NoAdminLeft` make unreachable, so saying it is
          // an accusation — and a failed `/users` produces exactly the same
          // empty fold. One is a bug that already happened; the other is a
          // request that did not arrive.
          !peopleKnown && account.members > 0
            ? <p className="note warn">{t.acct_people_unknown}</p>
            : <p className="note warn">{t.ld_no_members}</p>
        ) : (
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  {/* ⚠ `th_user`. This table lists PEOPLE, and one header
                      string over people and customers alike is how the
                      console kept saying "account" for both. */}
                  <th>{t.th_user}</th>
                  <th>{t.th_role}</th>
                  <th>{t.acct_joined}</th>
                </tr>
              </thead>
              <tbody>
                {members.map(({ user, role, joinedAt }) => (
                  <tr key={user.id}>
                    <td className="rtl-safe">
                      {user.display_name.trim()
                        || <span className="a">{t.users_unnamed}</span>}
                      <div className="mono">{user.id}</div>
                    </td>
                    {/* ⚠ One badge, no per-library breakdown: since P3.7b a
                        role is held at the ACCOUNT and covers every library
                        it owns. A role restricted to one collection is not
                        expressible, deliberately (VISION §4.1). */}
                    <td><span className="badge role">{role}</span></td>
                    <td>{formatDate(joinedAt, lang) || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="note">{t.acct_no_member_management}</p>

        <h3>{t.acct_books}</h3>
        <p className="sub">{t.acct_recent}</p>
        {books.error && <ErrorBox message={books.error} onRetry={books.reload} />}
        {books.loading && <Loading />}
        {books.data && (books.data.length === 0 ? (
          <Empty>{t.books_empty}</Empty>
        ) : (
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>{t.th_title}</th>
                  {/* ⚠ Which collection each book sits in. An account may keep
                      several, so a bare title list would answer "how many"
                      and not "where" — and the whole point of this level is
                      that the customer is not the collection. */}
                  <th>{t.th_library}</th>
                  <th>{t.th_status}</th>
                  <th>{t.th_added}</th>
                </tr>
              </thead>
              <tbody>
                {books.data.map((book: StaffBook) => (
                  <tr key={book.id}>
                    <td className="rtl-safe">
                      <div className="t">{book.title}</div>
                      <div className="a">{book.author}</div>
                    </td>
                    <td className="rtl-safe a">{labelOfLib(book.library_id)}</td>
                    <td><StatusBadge status={book.status} /></td>
                    <td>{formatDate(book.added_at, lang) || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

        <h3>{t.acct_images}</h3>
        <p className="sub">{t.acct_recent}</p>
        {images.error && <ErrorBox message={images.error} onRetry={images.reload} />}
        {images.loading && <Loading />}
        {images.data && (images.data.length === 0 ? (
          <Empty>{t.img_empty}</Empty>
        ) : (
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>{t.img_taken}</th>
                  <th>{t.th_library}</th>
                  <th>{t.img_filed_at}</th>
                  <th className="num">{t.th_findings}</th>
                </tr>
              </thead>
              <tbody>
                {images.data.map((image: StaffImage) => (
                  <tr key={image.id}>
                    <td>{formatDateTime(image.captured_at, lang) || t.img_undated}</td>
                    <td className="rtl-safe a">{labelOfLib(image.library_id)}</td>
                    <td className="rtl-safe a">
                      {image.shelf_label.trim() || t.shelf_unnamed}
                      {' · '}{t.img_depth_n(image.depth)}
                    </td>
                    <td className="num">{num(image.findings)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </aside>
    </>
  )
}
