/**
 * Every library in the system — listed by the staff service, and writable only
 * where the operator is actually a member.
 *
 * ⚠ **The two scopes are visible on the row, not merged.** The list spans every
 * tenant; *rename* and the export links go through the product API, which
 * resolves the caller's membership and answers 404 for anything else (§4.2).
 * So a row outside `mine` shows its numbers and says it is read-only, rather
 * than offering a button that would 404. Conflating them would produce a
 * console that looks omnipotent and fails on click.
 *
 * ⚠ **No delete**, in either service. It means deleting every book, shelf,
 * read and photo inside — a cascade across six aggregates — and it needs
 * P3.2's policy and P3.5's blob purge. The screen says so instead of showing
 * a disabled control.
 */
import { useState } from 'react'

import { createLibrary, exportUrl, renameLibrary } from '../api/client'
import type { LibraryDTO } from '../api/schema'
import { formatDate, formatNumber, libraryName } from '@booksnap/ui'
import { useI18n } from '../lib/i18n'
import { href } from '../lib/route'
import { OpenServiceWarning } from '../lib/StaffToken'
import { useSystem } from '../lib/system'
import { Empty, ErrorBox, Loading } from '@booksnap/ui'

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

export function LibrariesPage() {
  const {
    libraries, mine, overview, loading, error, reload, canWrite,
  } = useSystem()
  const { t, lang } = useI18n()
  const [editingId, setEditingId] = useState<string | undefined>(undefined)

  if (loading) return <Loading />
  if (libraries.length === 0 && error) {
    return <ErrorBox message={error} onRetry={reload} />
  }

  const mineById = new Map(mine.map((l) => [l.id, l]))
  const num = (n: number) => formatNumber(n, lang)

  return (
    <>
      <h1>{t.lib_title}</h1>
      <p className="sub">{t.lib_sub}</p>

      {overview && !overview.authenticated && <OpenServiceWarning />}

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
                <th>{t.th_library}</th>
                <th className="num">{t.th_members}</th>
                <th className="num">{t.th_books}</th>
                <th>{t.th_created}</th>
                <th>{t.th_actions}</th>
              </tr>
            </thead>
            <tbody>
              {libraries.map((lib) => {
                const writable = canWrite(lib.id)
                const own = mineById.get(lib.id)
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
                          <a href={href({ name: 'library', id: lib.id })}>
                            {libraryName(lib.label, t.lib_unnamed)}
                          </a>
                          {writable && <> <span className="badge role">{t.lib_mine}</span></>}
                          <div className="mono">{lib.id}</div>
                        </>
                      )}
                    </td>
                    <td className="num">
                      {num(lib.members)}
                      {lib.members === 0 && <> <span className="badge">!</span></>}
                    </td>
                    <td className="num">{num(lib.books)}</td>
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
                      <a className="btn small" href={href({ name: 'books', libraryId: lib.id })}>
                        {t.nav_books}
                      </a>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="note" style={{ marginTop: 16 }}>{t.lib_no_delete}</p>
    </>
  )
}
