/**
 * The operator's customers — the console's primary list since revision 4.
 *
 * ⚠⚠ **"Account" here is the TENANT, and today the tenant record is a
 * `Library`.** This is the one place the console deliberately diverges from the
 * domain's vocabulary, and the reason is the owner's own list for a row:
 *
 *   > in the tab users. It should be account. and per each account we can see
 *   > main data: when it was created, who are the admins, how many users, how
 *   > many books, images storage.
 *
 * A person has no admins and no users. That list describes a customer. So:
 *
 *   - **the wire keeps `library`** — VISION §4.1 settled twice that an Account
 *     is a person and a Library is the isolation boundary, and that there is
 *     ONE tenancy layer. Renaming the entity would re-decide a settled thing
 *     and break every `library_id` on every row;
 *   - **the console says "account"**, because that is the operator's word for
 *     the thing they administer — VISION §4.2 itself writes "an admin inside
 *     one account's library", and §4.1 records that one library per account is
 *     the default and the normal case;
 *   - **the drawer shows the library id, labelled as such**, so the mapping is
 *     visible rather than hidden.
 *
 * ⚠ **This merged the Libraries and Users tabs**, which were two names for one
 * entity — the incoherence revision 4 exists to fix. The people are a section
 * inside the account, where "how many users" has an answer.
 *
 * ⚠⚠ **A person with no membership would otherwise become invisible.** The
 * Users tab was the only screen that listed people directly, and a
 * tenant-shaped list cannot show somebody who belongs to no tenant. That is a
 * real regression and it is answered rather than accepted: the unaffiliated
 * section below is the mirror of the orphan-library warning (a library with no
 * member ↔ a member with no library).
 *
 * ⚠ Reading spans every tenant; WRITING does not. Rename and export go through
 * the product API, which resolves the operator's own membership — so a row
 * outside `mine` shows its numbers and says it is read-only rather than
 * offering a button that would 404.
 */
import { useState } from 'react'

import { createLibrary, exportUrl, renameLibrary } from '../api/client'
import type { LibraryDTO } from '../api/schema'
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
          one for somebody else. */}
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

/**
 * ⚠ Holds the text being typed and NOT an "am I editing" flag — the page owns
 * that, one row at a time. An earlier version kept both and they disagreed:
 * the page opened the editor while the cell, still `false`, rendered the read
 * view, so rename silently did nothing.
 */
function RenameCell({ library, onRenamed, onCancel }: {
  library: LibraryDTO
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

export function AccountsPage({ openId }: { openId: string | undefined }) {
  const {
    libraries, users, mine, overview, loading, error, reload, canWrite,
  } = useSystem()
  const { t, lang } = useI18n()
  const [editingId, setEditingId] = useState<string | undefined>(undefined)

  if (loading) return <Loading />
  if (libraries.length === 0 && error) {
    return <ErrorBox message={error} onRetry={reload} />
  }

  const mineById = new Map(mine.map((l) => [l.id, l]))
  const num = (n: number) => formatNumber(n, lang)
  const open = libraries.find((l) => l.id === openId)

  /** Who administers this account. Derived from the account list the provider
   *  already holds — the server has no `admin_names` field and does not need
   *  one; deriving it here keeps membership described in exactly one place. */
  const adminsOf = (accountId: string) =>
    users.filter((a) => a.memberships.some(
      (m) => m.account_id === accountId && m.role === 'admin'))

  // ⚠ The mirror of `orphan_libraries`. A tenant-shaped list cannot show a
  // person who belongs to no tenant, and the Users tab was the only place they
  // appeared. Derived, not fetched: the provider already has every account.
  const unaffiliated = users.filter((a) => a.memberships.length === 0)

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

      {libraries.length === 0 ? (
        <Empty>{t.lib_empty}</Empty>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.th_account}</th>
                <th>{t.th_admins}</th>
                <th className="num">{t.th_users}</th>
                <th className="num">{t.th_books}</th>
                <th className="num">{t.th_images}</th>
                <th className="num">{t.th_storage}</th>
                <th>{t.th_created}</th>
                <th>{t.th_actions}</th>
              </tr>
            </thead>
            <tbody>
              {libraries.map((lib) => {
                const writable = canWrite(lib.id)
                const own = mineById.get(lib.id)
                // By the OWNING account, not the library: people join a
                // customer, and two libraries of one share every member.
                const admins = adminsOf(lib.account_id)
                return (
                  <tr key={lib.id}>
                    <td className="rtl-safe">
                      {editingId === lib.id && own ? (
                        <RenameCell
                          library={own}
                          onCancel={() => setEditingId(undefined)}
                          onRenamed={() => { setEditingId(undefined); reload() }}
                        />
                      ) : (
                        <>
                          <a href={href({ name: 'account', id: lib.id })}>
                            {libraryName(lib.label, t.lib_unnamed)}
                          </a>
                          {writable && <> <span className="badge role">{t.lib_mine}</span></>}
                          <div className="mono">{lib.id}</div>
                        </>
                      )}
                    </td>
                    <td className="rtl-safe">
                      {/* ⚠ An account with no admin is the one anomaly this
                          table can surface that no household screen can:
                          `new_library` mints an admin membership in the same
                          call precisely so it cannot happen. */}
                      {admins.length === 0
                        ? <span className="badge warn">{t.acct_no_admin}</span>
                        : admins.map((a) => (
                            // ⚠ Falls back to the ID, not to the word
                            // "unnamed". Until P4.1 an account has no login and
                            // usually no display name, so a column of
                            // "unnamed" rows identifies nobody — which is
                            // exactly what this column exists to do.
                            <div key={a.id}>
                              {a.display_name.trim()
                                || <span className="mono">{a.id}</span>}
                            </div>
                          ))}
                    </td>
                    <td className="num">
                      {num(lib.members)}
                      {lib.members === 0 && <> <span className="badge">!</span></>}
                    </td>
                    <td className="num">{num(lib.books)}</td>
                    <td className="num">{num(lib.captures)}</td>
                    <td className="num">{formatBytes(lib.image_bytes, lang)}</td>
                    <td>{formatDate(lib.created_at, lang) || '—'}</td>
                    <td className="actions">
                      {writable ? (
                        <>
                          <button type="button" className="btn small"
                                  onClick={() => setEditingId(lib.id)}>
                            {t.lib_rename}
                          </button>{' '}
                          {/* Downloads, so real links: letting the browser
                              handle Content-Disposition is what makes "Save
                              as…" work. The library rides in the QUERY string
                              because an <a href> cannot carry a header. */}
                          <a className="btn small" href={exportUrl(lib.id, 'csv')}>
                            {t.lib_export_csv}
                          </a>{' '}
                          <a className="btn small" href={exportUrl(lib.id, 'json')}>
                            {t.lib_export_json}
                          </a>{' '}
                        </>
                      ) : (
                        <span className="a">{t.lib_readonly}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ⚠ Not a curiosity: until P4.1 an account cannot log in, so a person
          with no membership is somebody the system knows about and nobody can
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
                  <th>{t.th_account}</th>
                  <th>{t.th_email}</th>
                  <th>{t.th_created}</th>
                </tr>
              </thead>
              <tbody>
                {unaffiliated.map((account) => (
                  <tr key={account.id}>
                    <td className="rtl-safe">
                      <div className="t">
                        {account.display_name.trim()
                          || <span className="a">{t.users_unnamed}</span>}
                      </div>
                      <div className="mono">{account.id}</div>
                    </td>
                    <td className="mono">{account.email || '—'}</td>
                    <td>{formatDate(account.created_at, lang) || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="note" style={{ marginTop: 16 }}>{t.lib_no_delete}</p>

      {open && (
        <AccountDrawer key={open.id} library={open}
                       onClose={() => navigate({ name: 'accounts' })} />
      )}
    </>
  )
}
