/**
 * A shelf's read history, as diffs (P2.8, §5.5/§5.6) — the ONLY place a read
 * surfaces in normal use, and it surfaces as an event on the shelf, never as
 * an entity with a number. `run_no`-style developer handles belong to the
 * audit surface (booksnap's own tuning server), not this screen — this
 * product's `Read` deliberately carries no such label (§5.5: "not a
 * user-facing concept").
 *
 * Counts come from `Read.diff_summary` (P2.8's snapshot, captured once when
 * the read settled) — see `app.domain.read.DiffSummary`'s own docstring for
 * why this is never recomputed. A read that predates that column, or one
 * still running/failed, renders without the diff line rather than a guess.
 */
import type { ReadSummaryDTO } from '../api/client'
import { formatDate } from '@booksnap/ui'
import { useI18n, type Strings } from '../lib/i18n'

function modeLabel(mode: string, t: Strings): string {
  if (mode === 'fullpage') return t.mode_full
  if (mode === 'llmpage') return t.mode_llm
  return t.mode_spines
}

export interface ReadHistoryProps {
  reads: ReadSummaryDTO[]
  loading: boolean
}

export function ReadHistory({ reads, loading }: ReadHistoryProps) {
  const { t, lang } = useI18n()

  return (
    <div className="panel shelfhistory">
      <h3>
        <span>{t.shelf_history_title}</span>
      </h3>
      <div className="body">
        {loading && <p className="loading">{t.loading}</p>}
        {!loading && reads.length === 0 && (
          <p className="empty">{t.shelf_history_empty}</p>
        )}
        {!loading && reads.length > 0 && (
          <ul className="historylist">
            {reads.map((r) => (
              <li key={r.id} className="historyrow">
                <div className="top">
                  <span className="date">
                    {formatDate(r.finished_at ?? r.started_at, lang)}
                  </span>
                  <span className="tiny muted">{modeLabel(r.mode, t)}</span>
                  {r.status === 'failed' && (
                    <span className="badge b-none">{t.read_failed_short}</span>
                  )}
                  {r.status === 'stopped' && (
                    <span className="badge b-none">{t.read_stopped_short}</span>
                  )}
                </div>
                {r.diff_summary && (
                  <div className="chiprow diffbits">
                    <span className="g">+{r.diff_summary.added} {t.read_added}</span>
                    {r.diff_summary.corrected > 0 && (
                      <span className="m">
                        {r.diff_summary.corrected} {t.read_corrected}
                      </span>
                    )}
                    <span className="m">
                      {r.diff_summary.unchanged} {t.read_unchanged}
                    </span>
                    {r.diff_summary.not_seen > 0 && (
                      <span className="r">{t.read_unseen(r.diff_summary.not_seen)}</span>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
