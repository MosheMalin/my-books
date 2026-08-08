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
import { ReviewPanel } from './ReviewPanel'
import { useCapture, type Mode } from './useCapture'

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
                      shelves={cap.shelves}
                      onToggle={() => cap.toggleSelect(it.localId)}
                      onShelf={(shelfId) => void cap.assignShelf(it.localId, shelfId)}
                      onDepth={(depth) => void cap.assignDepth(it.localId, depth)}
                      onAddRowBehind={() => {
                        if (it.shelfId) void cap.addRowBehind(it.shelfId)
                      }}
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
                <button
                  type="button"
                  className="btn primary"
                  disabled={cap.pendingGroupCount === 0}
                  onClick={() => void cap.start()}
                >
                  {t.run(cap.selectedReadyCount)}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="reviewcol">
        {cap.runs.length === 0 ? (
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
            />
          ))
        )}
      </div>
    </div>
  )
}
