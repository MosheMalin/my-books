/**
 * Tab 3 — Capture (P2.7, UI_PLAN §4): drop zone -> per-photo shelf/depth
 * assignment -> mode selector -> run/stop with live progress -> inline
 * review of every claim. Left column intake, right column review, per
 * UI_PLAN's layout.
 *
 * State lives in `useCapture`, a page-local hook — this is one screen, not
 * a cache several screens share (see its module docstring / CLAUDE.md's
 * note on why `lib/books.tsx` is hand-rolled for the same reason).
 */
import { useRef } from 'react'
import { useI18n } from '../lib/i18n'
import { CaptureRow } from './CaptureRow'
import { ImageWorkspace } from './ImageWorkspace'
import { ReviewPanel } from './ReviewPanel'
import { useCapture, type Mode } from './useCapture'
import { useImageWorkspace } from './useImageWorkspace'

// Ordered best-first, which is also default-first: llmpage is what
// `useCapture` selects, and a default sitting third down the list reads as an
// afterthought rather than as the recommendation. Tesseract stays last and
// stays free — it is the answer when there is no key, not a lesser option
// hidden away.
const MODES: { value: Mode; nameKey: 'mode_spines' | 'mode_full' | 'mode_llm';
              descKey: 'mode_spines_d' | 'mode_full_d' | 'mode_llm_d' }[] = [
  { value: 'llmpage', nameKey: 'mode_llm', descKey: 'mode_llm_d' },
  { value: 'fullpage', nameKey: 'mode_full', descKey: 'mode_full_d' },
  { value: 'spines', nameKey: 'mode_spines', descKey: 'mode_spines_d' },
]

export function CaptureTab() {
  const { t } = useI18n()
  const cap = useCapture()
  const fileInput = useRef<HTMLInputElement | null>(null)

  // The photo whose workspace is open, and its state (P2.10). The hook is
  // mounted unconditionally with a nullable capture id — mounting it only
  // when a photo is open would remount it on every switch anyway, and a hook
  // behind a condition is not a hook.
  const openItem = cap.items.find((it) => it.localId === cap.openImageId)
  const ws = useImageWorkspace(openItem?.captureId ?? null)

  const onFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return
    cap.addFiles([...files].filter((f) => f.type.startsWith('image/')))
  }

  return (
    <div className="capturelayout">
      <div className="intakecol">
        <div className="panel">
          <h3>
            <span>{t.capture_tab}</span>
            <span className="muted tiny">{cap.items.length}</span>
          </h3>
          <div className="body">
            <div
              className="dropzone"
              role="button"
              tabIndex={0}
              onClick={() => fileInput.current?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  fileInput.current?.click()
                }
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault()
                onFiles(e.dataTransfer.files)
              }}
            >
              <strong>{t.drop_here}</strong>
              <br />
              <span className="tiny muted">{t.drop_or_click}</span>
            </div>
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              multiple
              className="visually-hidden"
              aria-hidden="true"
              tabIndex={-1}
              onChange={(e) => {
                onFiles(e.target.files)
                e.target.value = ''
              }}
            />
            <p className="tiny muted phonehint">
              📱 {t.phone_hint(typeof window !== 'undefined' ? window.location.host : '')}
            </p>

            {cap.items.length > 0 && (
              <>
                <div className="chiprow intakeactions">
                  <button type="button" className="linkish" onClick={cap.selectAll}>
                    {t.select_all}
                  </button>
                  <button type="button" className="linkish" onClick={cap.selectNone}>
                    {t.select_none}
                  </button>
                  <button type="button" className="linkish" onClick={cap.selectUnread}>
                    {t.select_unread}
                  </button>
                </div>
                <div className="caplist">
                  {cap.items.map((it) => (
                    <CaptureRow
                      key={it.localId}
                      item={it}
                      selected={cap.selected.has(it.localId)}
                      open={cap.openImageId === it.localId}
                      shelves={cap.shelves}
                      onToggle={() => cap.toggleSelect(it.localId)}
                      onOpen={() => cap.openImage(
                        cap.openImageId === it.localId ? null : it.localId,
                      )}
                      onShelf={(shelfId) => void cap.assignShelf(it.localId, shelfId)}
                      onDepth={(depth) => void cap.assignDepth(it.localId, depth)}
                      onRetry={() => cap.retryItem(it.localId)}
                    />
                  ))}
                </div>
              </>
            )}
            {cap.items.length === 0 && <p className="empty">{t.intake_empty}</p>}

            <div className="runblock">
              <div className="tiny muted" style={{ marginBottom: 5 }}>{t.mode_label}</div>
              <div className="modeopts">
                {MODES.map((m) => (
                  <label key={m.value} className="modeopt">
                    <input
                      type="radio"
                      name="mode"
                      value={m.value}
                      checked={cap.mode === m.value}
                      onChange={() => cap.setMode(m.value)}
                    />
                    <span>
                      <b>{t[m.nameKey]}</b>
                      {t[m.descKey]}
                    </span>
                  </label>
                ))}
              </div>
              <div className="runactions">
                {/* Disabled when there is nothing STARTABLE. The owner's
                    live-use rule ("Run is disabled while a read is running")
                    was about re-reading the SAME (shelf, depth) — money,
                    minutes, and it replaces the panel being watched. That
                    half still holds: a running group is excluded from
                    `pendingGroups`, so it cannot be double-started. The
                    global half was retired with P3.4 — new shelves queue
                    fairly server-side, so refusing them while a batch runs
                    protected nothing and froze the owner who had just
                    photographed one more shelf. The hint appears exactly
                    when the disable is BECAUSE of a running read. */}
                <button
                  type="button"
                  className="btn primary"
                  disabled={cap.pendingGroupCount === 0}
                  onClick={() => void cap.start()}
                >
                  {t.run(cap.selectedReadyCount)}
                </button>
                {cap.running && cap.pendingGroupCount === 0
                  && cap.selectedReadyCount > 0 && (
                  <span className="tiny muted">{t.run_busy}</span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* The right column answers ONE question at a time: "what is happening
          now" (live panels) or "what did this photo find" (the workspace).
          Stacking both would put two answers to two different questions on
          one screen, and the workspace is opened deliberately — starting a
          read closes it (see `useCapture.start`). */}
      <div className="reviewcol">
        {openItem ? (
          <ImageWorkspace
            item={openItem}
            shelves={cap.shelves}
            ws={ws}
            onClose={() => cap.openImage(null)}
          />
        ) : cap.runs.length === 0 ? (
          <div className="empty">{t.review_now}</div>
        ) : (
          cap.runs.map((run) => (
            <ReviewPanel
              key={run.key}
              run={run}
              shelves={cap.shelves}
              onStop={() => void cap.stopRun(run.key)}
              onAnswer={(claimId, kind, copyId) =>
                void cap.answerClaim(run.key, claimId, kind, copyId)}
              onFinding={(claimId, op) =>
                void cap.findingOnRun(run.key, claimId, op)}
              onApproveAll={(what) => void cap.approveAllOnRun(run.key, what)}
            />
          ))
        )}
      </div>
    </div>
  )
}
