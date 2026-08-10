/**
 * The image workspace (P2.10, §12.2 #10) — the screen that turns the Capture
 * tab from a pipeline into a place you can come back to.
 *
 * Three levels, in the order §12.2 #10 states them: **the image** (header),
 * **its runs** (a row each, newest first), **that run's findings** (approve /
 * fix / remove, and *why?*). Nothing here starts a read — that is the point,
 * and the hint under the header says so out loud, because the previous build
 * left *re-run on selected* as the only visible action on a processed photo.
 *
 * The runs list deliberately shows a DATE and a mode, never an id or a number
 * (§5.5: a run is not a user-facing concept). §12.2 #10 settles that the
 * split is by surface, not a reversal: this is the one screen where the unit
 * of work IS the photograph, so its history is visible here — and still
 * nowhere else.
 */
import type { ReadSummaryDTO, Shelf } from '../api/client'
import { formatDate } from '@booksnap/ui'
import { useI18n, type Strings } from '../lib/i18n'
import { FindingList } from './FindingList'
import type { ImageWorkspaceApi } from './useImageWorkspace'
import type { IntakeItem } from './useCapture'

function modeLabel(mode: string, t: Strings): string {
  if (mode === 'fullpage') return t.mode_full
  if (mode === 'llmpage') return t.mode_llm
  return t.mode_spines
}

export interface ImageWorkspaceProps {
  item: IntakeItem
  shelves: Shelf[]
  ws: ImageWorkspaceApi
  onClose: () => void
}

export function ImageWorkspace({ item, shelves, ws, onClose }: ImageWorkspaceProps) {
  const { t } = useI18n()
  const shelf = shelves.find((s) => s.id === item.shelfId)
  const shelfLabel = shelf?.label || t.unassigned
  const target = shelf && shelf.depth_count > 1
    ? `${shelfLabel} · ${t.depth_n(item.depth)}` : shelfLabel

  return (
    <div className="panel workspace">
      <h3>
        <span className="rtl-safe">{t.workspace_title}</span>
        {/* No "open the shelf" chip (owner, 2026-08-09): this tab is about
            the IMAGE. A photo is a shelf, or part of one, or two of them —
            binding it to a place in the house is the Map tab's job, and a
            link out of here invited the opposite reading. */}
        <button type="button" className="btn sm" onClick={onClose}>
          {t.workspace_close}
        </button>
      </h3>
      <div className="body">
        <div className="wshead">
          <img src={item.previewUrl} alt="" />
          <div className="m">
            <div className="fn rtl-safe">{item.filename}</div>
            <div className="tiny muted rtl-safe">{target}</div>
          </div>
        </div>
        <p className="tiny muted reviewhint">
          {t.workspace_hint} {t.workspace_pending_note}
        </p>

        <h4 className="wssection">{t.workspace_runs}</h4>
        {ws.runsLoading && <p className="loading">{t.loading}</p>}
        {ws.error && <p className="errorbox" role="alert">{ws.error}</p>}
        {!ws.runsLoading && ws.runs.length === 0 && (
          <p className="empty">{t.workspace_no_runs}</p>
        )}
        {ws.runs.length > 0 && (
          <ul className="runlist">
            {ws.runs.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className={`runrow${r.id === ws.openRunId ? ' on' : ''}`}
                  onClick={() => void ws.openRun(r)}
                >
                  <RunLine run={r} />
                </button>
              </li>
            ))}
          </ul>
        )}

        {ws.openRunId && (
          <>
            <h4 className="wssection">{t.workspace_findings}</h4>
            {ws.runInFlight && <p className="loading">{t.reading_now}</p>}
            {ws.diffLoading && <p className="loading">{t.loading}</p>}
            {ws.diffError && <p className="errorbox" role="alert">{ws.diffError}</p>}
            {ws.diff && (
              <FindingList
                diff={ws.diff}
                {...(item.captureId ? { captureId: item.captureId } : {})}
                busy={ws.busy}
                onAnswer={ws.answer}
                onFinding={ws.finding}
                onApproveAll={ws.approveAll}
                onAddByHand={ws.addByHand}
                onLookup={ws.lookup}
                onAuthors={ws.authors}
                onSplit={ws.split}
                emptyText={t.workspace_no_findings}
              />
            )}
          </>
        )}
        {!ws.openRunId && ws.runs.length > 0 && (
          <p className="empty">{t.workspace_pick_run}</p>
        )}
      </div>
    </div>
  )
}

function RunLine({ run }: { run: ReadSummaryDTO }) {
  const { t, lang } = useI18n()
  return (
    <>
      <span className="date">{formatDate(run.finished_at ?? run.started_at, lang)}</span>
      <span className="tiny muted">{modeLabel(run.mode, t)}</span>
      {run.status === 'running' && (
        <span className="tiny muted">{t.workspace_run_running}</span>
      )}
      {run.status === 'failed' && (
        <span className="badge b-none">{t.read_failed_short}</span>
      )}
      {run.status === 'stopped' && (
        <span className="badge b-none">{t.read_stopped_short}</span>
      )}
      {/* How MANY findings, not what became of them (owner, 2026-08-09).
          This used to render `Read.diff_summary`, P2.8's archived snapshot —
          which is a true record of what the read DID and a bad status line:
          remove a book and the row still read "1 awaiting approval", because
          a snapshot cannot know about something that happened after it was
          taken. The count of claims is a fact that never goes stale, and the
          findings list below carries the live state (including removals),
          which is where a reader looks anyway once a run is open.

          The snapshot is NOT gone — the shelf's own read history
          (`shelf/ReadHistory.tsx`) still shows it, which is the surface P2.8
          built it for: there the question really is "what did this read
          change", asked long afterwards. */}
      <span className="tiny muted">{t.run_findings(run.claim_count)}</span>
    </>
  )
}
