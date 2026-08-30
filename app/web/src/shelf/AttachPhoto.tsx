/**
 * File a photograph against a shelf — **without reading it** (P6.7d).
 *
 * The owner: *"How do I attach an image to a shelf? I want to be able to do it
 * both on the shelf itself and also in the bookcase (when a shelf is
 * selected)."* Until this, the only path was the Capture tab's shelf dropdown,
 * which starts a READ — Vision or Tesseract, money per photo, and a queue of
 * findings needing a ✓. Filing a picture and reading it are different
 * intentions, and one of them is free.
 *
 * ⚠ **Nothing here is new on the server.** `POST /images` + `POST /captures`
 * have filed a photo onto a shelf since P2.2 — a `Capture` names a shelf and a
 * declared depth and knows nothing about reads; a read CONSUMES captures. So
 * this is one population, not a second kind of picture, and everything already
 * built on captures (the shelf photo, the count in the map panel, blob GC's
 * refs, *read this shelf* later) sees it without being told.
 *
 * ⚠ **The plumbing is the HOST's, not this component's.** It takes an
 * `onAttach` and owns only the control and its three states, because the two
 * hosts refresh differently and for good reasons: the shelf screen reloads
 * itself, and the map re-derives its whole document the way every other
 * server-only write there does. A component that reached for `client.ts`
 * would have had to pick one of those and be wrong somewhere.
 */
import { useState } from 'react'

import { useI18n } from '../lib/i18n'

export function AttachPhoto({ onAttach, depth, depthCount }: {
  /** Store the file and file it against this shelf. Rejects on failure; the
   *  refusal's own words are not shown, because every failure here means the
   *  same thing to the person holding the phone. */
  onAttach: (photo: File) => Promise<void>
  /** The row front-to-back the photo is OF. Declared, never detected (§5.7). */
  depth: number
  /** How many rows this shelf has. The depth is only WORTH naming when there
   *  is more than one — the front row is never called a row (UI_PLAN §1.1). */
  depthCount: number
}) {
  const { t } = useI18n()
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'failed'>('idle')
  const deep = depthCount > 1
  const label = deep ? t.attach_photo_at(depth) : t.attach_photo
  return (
    <div className="attach-photo">
      {/* A file input cannot be styled, so the LABEL is the control and the
          input inside it is hidden — the idiom the capture drop zone and the
          level proposal both already use. */}
      <label className="btn-like">
        <span>{label}</span>
        <input
          type="file"
          accept="image/*"
          aria-label={label}
          disabled={state === 'busy'}
          onChange={(e) => {
            const photo = e.target.files?.[0]
            // ⚠ Cleared straight away, so choosing the SAME file twice fires
            // again. A file input raises no `change` for an unchanged value,
            // and "nothing happened" after a retry reads as a dead control.
            e.target.value = ''
            if (!photo) return
            setState('busy')
            void onAttach(photo)
              .then(() => setState('done'))
              .catch(() => setState('failed'))
          }}
        />
      </label>
      {/* ⚠ On SCREEN, never in a `title`: a phone shows no tooltip, and the
          phone is the device this catalogue is made from. The idle sentence
          is the one that matters — it promises the thing the Capture tab
          cannot, which is that this spends nothing. */}
      <p className="note rtl-safe" role="status">
        {state === 'busy' ? t.attaching_photo
          : state === 'failed' ? t.attach_photo_failed
            : state === 'done' ? t.photo_attached
              : t.attach_photo_hint}
      </p>
    </div>
  )
}
