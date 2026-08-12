/**
 * Every photograph in the system — the console's third noun, and the one the
 * owner corrected by name:
 *
 *   > And indeed rather than Shelf, the images are images. they will later be
 *   > bound to shelves/bookcase. but on their own they are images … the runs
 *   > and result are bound to the image.
 *
 * ⚠⚠ **This replaced a shelves table, and the replacement is the item.** A
 * shelf today is an identity minted per photograph — VISION §4.1a records
 * "one image = one shelf" as a PLACEHOLDER with a recorded exit at P6.1b — so
 * a console listing shelves was listing photographs under a noun they have not
 * earned, and would keep doing so until pillar 6's map arrives. The image
 * leads; the shelf it is filed at is shown as a BINDING, secondary and
 * labelled, which is exactly what pillar 6 will replace.
 *
 * ⚠ **The engine figures come from the image side of the data, not the shelf
 * side**: `claims.capture_id` names the photograph a finding came from and
 * `reads.capture_ids` names the photographs a run consumed. So "1 run, 0
 * findings" is a row this screen can show — and it is the row an operator
 * debugging the reader is looking for.
 *
 * ⚠⚠ **A thumbnail appears only for a library the operator is a member of.**
 * The metadata crosses tenants; the picture does not. The staff service serves
 * no bytes at all (structurally — a test refuses the file-response classes), so
 * a thumbnail here is an ordinary product-API fetch, and for a household the
 * operator does not belong to there simply is no picture to show.
 */
import { useEffect, useState } from 'react'

import { thumbUrl } from '../api/client'
import { listImages, type StaffImage } from '../api/staff'
import { useI18n } from '../lib/i18n'
import { navigate } from '../lib/route'
import { useSystem } from '../lib/system'
import { formatBytes, LibraryName, LibraryPicker } from '../lib/ui'
import {
  Empty, ErrorBox, Loading, formatDate, formatDateTime, formatNumber, useAsync,
} from '@booksnap/ui'
import { ImagePanel } from './ImagePanel'

const PAGE = 25

export function ImagesPage({ initialLibraryId }: { initialLibraryId: string | undefined }) {
  const { t, lang } = useI18n()
  const { loading: sysLoading, canWrite } = useSystem()

  const [libraryId, setLibraryId] = useState<string | undefined>(initialLibraryId)
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<StaffImage | undefined>(undefined)

  useEffect(() => { setPage(0) }, [libraryId])

  const result = useAsync(
    (signal) => listImages({ libraryId, limit: PAGE, offset: page * PAGE },
                           { signal }),
    [libraryId, page],
  )

  if (sysLoading) return <Loading />

  const rows = result.data?.items ?? []
  const total = result.data?.total ?? 0
  // ⚠ Read this BEFORE `present`. With no blob tree in sight every row says
  // "bytes gone", which is "we did not look" and not "they are lost" — and a
  // console that conflated the two would announce that every photograph in
  // every tenant had vanished, hiding a real loss in the noise.
  const blind = result.data ? !result.data.blobs_visible : false
  const lastPage = Math.max(0, Math.ceil(total / PAGE) - 1)
  const num = (n: number) => formatNumber(n, lang)

  return (
    <>
      <h1>{t.img_title}</h1>
      <p className="sub">{t.img_sub}</p>

      <div className="row" style={{ marginBottom: 12 }}>
        <LibraryPicker value={libraryId} onChange={(next) => {
          setLibraryId(next)
          navigate({ name: 'images', libraryId: next })
        }} />
        <button type="button" className="btn small" onClick={result.reload}>
          {t.refresh}
        </button>
      </div>

      {blind && <p className="note warn">{t.img_blind}</p>}
      {result.error && <ErrorBox message={result.error} onRetry={result.reload} />}
      {result.loading && <Loading />}
      {!result.loading && rows.length === 0 && <Empty>{t.img_empty}</Empty>}

      {rows.length > 0 && (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>{t.img_taken}</th>
                {/* ⚠ `th_library` over a cell that names the collection AND
                    its owning customer. It said "account" over a library
                    label while a library WAS the tenant; since P3.7b those are
                    two records and the cell shows both. */}
                <th>{t.th_library}</th>
                {/* ⚠ Named "filed at", never "shelf": the column is the
                    binding, and pillar 6 replaces it with a real address. */}
                <th>{t.img_filed_at}</th>
                <th className="num">{t.th_storage}</th>
                <th className="num">{t.img_runs}</th>
                <th>{t.th_findings}</th>
                <th>{t.img_last_read}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((image) => (
                <tr key={image.id} onClick={() => setSelected(image)}
                    style={{ cursor: 'pointer' }}>
                  <td>
                    <button type="button" className="btn link"
                            onClick={(e) => { e.stopPropagation(); setSelected(image) }}>
                      {formatDateTime(image.captured_at, lang) || t.img_undated}
                    </button>
                    {!image.present && !blind && (
                      <> <span className="badge warn">{t.img_missing}</span></>
                    )}
                  </td>
                  {/* ⚠ The collection AND the customer that owns it. A
                      library name alone does not answer "whose photograph is
                      this?", which is the question a cross-tenant list is
                      for — and one account may own several. */}
                  <td className="a"><LibraryName libraryId={image.library_id} /></td>
                  <td className="rtl-safe a">
                    {image.shelf_label.trim() || <span className="a">{t.shelf_unnamed}</span>}
                    {' · '}
                    {t.img_depth_n(image.depth)}
                  </td>
                  <td className="num">
                    {blind ? '—' : formatBytes(image.bytes, lang)}
                  </td>
                  <td className="num">{num(image.reads)}</td>
                  <td>
                    {image.findings === 0
                      ? <span className="a">{t.none}</span>
                      : t.img_tiers(image.auto, image.review, image.unmatched)}
                  </td>
                  <td>{formatDate(image.last_read, lang) || <span className="a">{t.ld_never_read}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="row" style={{ marginTop: 12 }}>
        <span className="sub" style={{ margin: 0 }}>
          {t.img_count(Math.min((page + 1) * PAGE, total), total)}
        </span>
        <button type="button" className="btn small" disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}>
          {t.books_prev}
        </button>
        <button type="button" className="btn small" disabled={page >= lastPage}
                onClick={() => setPage((p) => p + 1)}>
          {t.books_next}
        </button>
        <span className="sub" style={{ margin: 0 }}>
          {num(page + 1)} / {num(lastPage + 1)}
        </span>
      </div>

      {selected && (
        <ImagePanel key={selected.id} image={selected}
                    libraryId={selected.library_id}
                    // ⚠ The picture, only where the operator is a member. See
                    // the module note: the staff service serves no bytes, so
                    // this URL is the product API's and it answers 404 for a
                    // household the operator does not belong to.
                    blind={blind}
                    thumb={canWrite(selected.library_id) && selected.present
                        && selected.image_key
                      ? thumbUrl(selected.library_id, selected.image_key)
                      : undefined}
                    onClose={() => setSelected(undefined)} />
      )}
    </>
  )
}
