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
import { FindingList } from './FindingList'
import { RunProgress } from './RunProgress'
import type { Approvable, FindingOp } from './findingOps'
import type { RunState } from './useCapture'

export interface ReviewPanelProps {
  run: RunState
  shelves: Shelf[]
  onStop: () => void
  onAnswer: (claimId: string, kind: string, copyId?: string | null) => void
  /** P2.10 — approve / fix / remove, on the same rows, right after the read.
   *  The workspace offers the identical loop days later. */
  onFinding: (claimId: string, op: FindingOp) => void
  onApproveAll: (what: Approvable) => void
}

export function ReviewPanel({
  run, shelves, onStop, onAnswer, onFinding, onApproveAll,
}: ReviewPanelProps) {
  const { t } = useI18n()
  const shelf = shelves.find((s) => s.id === run.shelfId)
  const shelfLabel = shelf?.label || t.unassigned
  const target = shelf && shelf.depth_count > 1
    ? `${shelfLabel} · ${t.depth_n(run.depth)}` : shelfLabel

  return (
    <div className="panel reviewpanel">
      <h3>
        <span className="rtl-safe">{target}</span>
        {/* The *"open the shelf"* chip P2.8 put here is gone (owner,
            2026-08-09): this tab is about the image, and the shelf binding
            belongs to the Map tab. */}
        <span className="chiprow">
          {run.status === 'running' && (
            <button type="button" className="btn sm danger" onClick={onStop}>
              {t.stop_run}
            </button>
          )}
        </span>
      </h3>
      <div className="body">
        {run.status === 'running' && <RunProgress progress={run.progress} />}

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
                {run.answerError && (
                  <p className="errorbox" role="alert">{run.answerError}</p>
                )}

                <FindingList
                  diff={run.diff}
                  busy={run.answeringClaimIds}
                  onAnswer={onAnswer}
                  onFinding={onFinding}
                  onApproveAll={onApproveAll}
                  emptyText={t.workspace_no_findings}
                />
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
