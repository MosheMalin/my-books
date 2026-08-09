/**
 * What a running read is actually doing, in words and a bar.
 *
 * The engine has reported this all along — `booksnap/pipeline.py` and
 * `llmreader.py` emit a progress dict per tile, per block and per spine, the
 * job runner keeps the latest one, and `ReadDTO.progress` carries it on every
 * poll (P2.4). The product simply never rendered it: a read that takes minutes
 * showed one static *"reading…"*, which is indistinguishable from a hung job.
 * The owner reported it as exactly that, in live use.
 *
 * ⚠ Nothing here is persisted, and nothing here should be. `progress` is
 * live-only by design (`app/ports/jobs.py`) — a second stored copy could
 * disagree with the job runner about whether a read is still going, which is
 * the drift `ReadDTO.progress`'s own docstring refuses.
 *
 * Unknown stages fall back to the plain "reading…" line rather than rendering
 * a raw key: the engine may grow a stage this file has never heard of, and a
 * new event should read as *less* detail, never as a broken screen.
 */
import { useI18n } from '../lib/i18n'

export interface RunProgressProps {
  progress: Record<string, unknown> | null
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

export function RunProgress({ progress }: RunProgressProps) {
  const { t } = useI18n()
  const stage = typeof progress?.['stage'] === 'string'
    ? (progress['stage'] as string) : ''
  const done = num(progress?.['done'])
  const total = num(progress?.['total'])
  const spines = num(progress?.['spines'])

  let line = t.reading_now
  if (stage === 'reading' && done !== null && total !== null) {
    line = t.stage_reading(done, total)
  } else if (stage === 'page_read' && spines !== null) {
    line = t.stage_page_read(spines)
  } else if (stage === 'segmented' && spines !== null) {
    line = t.stage_segmented(spines)
  } else if (stage === 'ocr' && done !== null && total !== null) {
    line = t.stage_ocr(done, total)
  } else if (stage === 'matching' && done !== null && total !== null) {
    line = t.stage_matching(done, total)
  } else if (stage === 'stopped') {
    line = t.stage_stopping
  }

  // Only when the engine gave a real denominator. A bar with a made-up
  // fraction is worse than no bar: it says "we know how far along this is"
  // when nobody does.
  const pct = done !== null && total !== null && total > 0
    ? Math.min(100, Math.round((done / total) * 100))
    : null

  return (
    <div className="runprogress">
      <p className="loading">{line}</p>
      {pct !== null && (
        <div
          className="progbar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label={line}
        >
          <span style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  )
}
