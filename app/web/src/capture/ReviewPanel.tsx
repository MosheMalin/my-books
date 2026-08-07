/**
 * One run's review panel — header stating the target shelf · row and the
 * running diff, then a row per claim (P2.7, UI_PLAN §4).
 *
 * The copy under the header says plainly that confirming here is a
 * shortcut and the shelf is the durable home (UI_PLAN §4's hybrid
 * contract). UI_PLAN also asks for a *"פתחו את המדף →"* chip beside it —
 * P2.7 left it out because neither the map tab nor a shelf-detail route
 * existed yet; P2.8 built the route (`#/map/<shelfId>`, `shelf/ShelfPage`),
 * so the chip lands here now. Setting `location.hash` directly (rather than
 * threading `useRoute`'s `navigate` down through `CaptureTab`) is the same
 * mechanism `useRoute` itself uses — a hash write IS the navigation.
 */
import type { Shelf } from '../api/client'
import { useI18n } from '../lib/i18n'
import { shelfHash } from '../lib/route'
import { ClaimRow } from './ClaimRow'
import type { RunState } from './useCapture'

export interface ReviewPanelProps {
  run: RunState
  shelves: Shelf[]
  onStop: () => void
  onAnswer: (claimId: string, kind: string, copyId?: string | null) => void
}

export function ReviewPanel({ run, shelves, onStop, onAnswer }: ReviewPanelProps) {
  const { t } = useI18n()
  const shelf = shelves.find((s) => s.id === run.shelfId)
  const shelfLabel = shelf?.label || t.unassigned
  const target = shelf && shelf.depth_count > 1
    ? `${shelfLabel} · ${t.depth_n(run.depth)}` : shelfLabel

  return (
    <div className="panel reviewpanel">
      <h3>
        <span className="rtl-safe">{target}</span>
        <span className="chiprow">
          <button
            type="button"
            className="linkish"
            onClick={() => {
              globalThis.location.hash = shelfHash(run.shelfId)
            }}
          >
            {t.open_shelf}
          </button>
          {run.status === 'running' && (
            <button type="button" className="btn sm danger" onClick={onStop}>
              {t.stop_run}
            </button>
          )}
        </span>
      </h3>
      <div className="body">
        {run.status === 'running' && (
          <p className="loading">{t.reading_now}</p>
        )}

        {run.status === 'failed' && !run.diff && (
          <p className="errorbox" role="alert">
            {t.run_failed}{run.error ? ` — ${run.error}` : ''}
          </p>
        )}

        {run.status !== 'running' && (
          <>
            <p className="tiny muted reviewhint">{t.review_hint}</p>

            {run.diffLoading && !run.diff && <p className="loading">{t.loading}</p>}
            {run.diffError && <p className="errorbox" role="alert">{run.diffError}</p>}

            {run.diff && (
              <>
                <div className="chiprow diffbits">
                  <span className="g">+{run.diff.added.length} {t.read_added}</span>
                  {run.diff.corrected.length > 0 && (
                    <span className="m">{run.diff.corrected.length} {t.read_corrected}</span>
                  )}
                  <span className="m">{run.diff.unchanged.length} {t.read_unchanged}</span>
                  {run.diff.not_seen.length > 0 && (
                    <span className="r">{t.read_unseen(run.diff.not_seen.length)}</span>
                  )}
                </div>

                {run.answerError && (
                  <p className="errorbox" role="alert">{run.answerError}</p>
                )}

                {[
                  ...run.diff.added,
                  ...run.diff.corrected,
                  ...run.diff.needs_decision,
                  ...run.diff.unchanged,
                ].map((outcome) => (
                  <ClaimRow
                    key={outcome.claim.id}
                    outcome={outcome}
                    answering={run.answeringClaimIds.has(outcome.claim.id)}
                    onAnswer={(kind, copyId) => onAnswer(outcome.claim.id, kind, copyId)}
                  />
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
