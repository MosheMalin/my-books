/**
 * One photograph: what it is, where it is currently filed, and what the engine
 * made of it.
 *
 * ⚠ **Read-only, and not because nobody got to it.** The staff service does
 * not write, and the two things an operator might want here — delete a
 * photograph, re-file it — are the household's own job in the product client,
 * by somebody who is a member. Deleting a photograph also needs P3.5's blob
 * lifecycle to agree, and re-filing is pillar 6's map. Absent, not disabled.
 *
 * ⚠ **The picture only appears for a library the operator belongs to.** The
 * metadata crossed tenants; the bytes do not. See `ImagesPage`'s note — this
 * component is handed a URL or nothing, and never builds one itself, so there
 * is exactly one place that decision is made.
 */
import { useEffect, useRef } from 'react'

import type { StaffImage } from '../api/staff'
import { useI18n } from '../lib/i18n'
import { formatBytes, LibraryName } from '../lib/ui'
import { formatDateTime, formatNumber } from '@booksnap/ui'

export function ImagePanel({ image, libraryId, thumb, blind, onClose }: {
  image: StaffImage
  /** ⚠ The ID, not a pre-formatted label: the panel names the collection
   *  AND the customer that owns it, and only the provider knows the
   *  second. Passing a string made the caller decide how much to say. */
  libraryId: string
  /** Undefined when the operator is not a member, or the bytes are gone. */
  thumb: string | undefined
  /** The service cannot see the blob tree at all — so `present: false` here
   *  means "nobody looked", and saying "lost" would be a false alarm. */
  blind: boolean
  onClose: () => void
}) {
  const { t, lang } = useI18n()
  const closeRef = useRef<HTMLButtonElement>(null)

  // ⚠ Held in a ref rather than depended on: `onClose` is a fresh closure every
  // parent render, and an effect that depended on it would re-install the
  // listener — and steal focus — on every repaint. Same rule as `WorkPanel`.
  const closeApi = useRef(onClose)
  closeApi.current = onClose

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeApi.current() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const num = (n: number) => formatNumber(n, lang)

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="panel" role="dialog" aria-label={t.img_panel}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <strong>{t.img_panel}</strong>
          <button type="button" className="btn small" ref={closeRef} onClick={onClose}>
            {t.close}
          </button>
        </div>

        {thumb
          ? <img src={thumb} alt={t.img_alt} style={{
              maxWidth: '100%', marginTop: 12, borderRadius: 6,
            }} />
          : (
            <p className={`note${!image.present && !blind ? ' warn' : ''}`}
               style={{ marginTop: 12 }}>
              {blind ? t.img_blind
                : image.present ? t.img_no_preview : t.img_missing_long}
            </p>
          )}

        <div style={{ marginTop: 14 }}>
          <div className="kv">
            <span className="k">{t.img_taken}</span>
            <span>{formatDateTime(image.captured_at, lang) || t.img_undated}</span>
          </div>
          <div className="kv">
            {/* ⚠ `th_library`, and the value names the collection AND the
                customer that owns it. A photograph belongs to a collection;
                one customer may own several, so the collection alone does not
                answer "whose picture is this?". */}
            <span className="k">{t.th_library}</span>
            <span><LibraryName libraryId={libraryId} /></span>
          </div>
          {/* ⚠ "Filed at", not "shelf". The pair below is a placeholder
              binding (VISION §4.1a) and pillar 6 replaces it with a real
              address; naming it as the image's location would teach the
              operator a relationship that is about to change. */}
          <div className="kv">
            <span className="k">{t.img_filed_at}</span>
            <span className="rtl-safe">
              {image.shelf_label.trim() || t.shelf_unnamed}
              {' · '}{t.img_depth_n(image.depth)}
              {' · '}{t.img_order_n(image.order)}
            </span>
          </div>
          <div className="kv">
            <span className="k">{t.th_storage}</span>
            <span>
              {blind ? '—' : formatBytes(image.bytes, lang)}
              {image.width > 0 && <> · {num(image.width)}×{num(image.height)}</>}
              {image.content_type && <> · {image.content_type}</>}
            </span>
          </div>
          {image.filename && (
            <div className="kv">
              <span className="k">{t.img_filename}</span>
              <span className="rtl-safe">{image.filename}</span>
            </div>
          )}
          <div className="kv">
            <span className="k">{t.img_runs}</span>
            <span>{num(image.reads)}</span>
          </div>
          <div className="kv">
            <span className="k">{t.th_findings}</span>
            <span>
              {image.findings === 0
                ? t.none
                : t.img_tiers(image.auto, image.review, image.unmatched)}
            </span>
          </div>
          <div className="kv">
            <span className="k">{t.lib_id}</span>
            <span className="mono">{image.id}</span>
          </div>
          {image.image_key && (
            <div className="kv">
              {/* The content address. Worth showing on a console: it is how a
                  blob is found on disk, and how two captures are told apart
                  when they are the same photograph. */}
              <span className="k">{t.img_key}</span>
              <span className="mono">{image.image_key}</span>
            </div>
          )}
        </div>

        {/* ⚠ A run that consumed the photograph and found nothing is not an
            error state — it is the row an operator debugging the reader came
            here for, so it gets a sentence rather than an empty cell. */}
        {image.reads > 0 && image.findings === 0 && (
          <p className="note warn" style={{ marginTop: 12 }}>{t.img_read_nothing}</p>
        )}

        <p className="note" style={{ marginTop: 12 }}>{t.img_readonly}</p>
      </aside>
    </>
  )
}
