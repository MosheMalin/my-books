/**
 * One intake row: thumbnail, filename, and the inline shelf + depth
 * assignment (P2.7, UI_PLAN §4 — "each photo carries a shelf and, when the
 * shelf is stacked, a depth, chosen inline").
 *
 * *"Unassigned"* means NOT YET NAMED, never not-yet-filed (P2.2/P2.1): the
 * moment a photo uploads it already has a real shelf — auto-created if none
 * was picked — so the select always has a value, it just may say
 * `t.unassigned` for one with no label yet.
 */
import type { Shelf } from '../api/client'
import { useI18n } from '../lib/i18n'
import type { IntakeItem } from './useCapture'

export interface CaptureRowProps {
  item: IntakeItem
  selected: boolean
  shelves: Shelf[]
  onToggle: () => void
  onShelf: (shelfId: string) => void
  onDepth: (depth: number) => void
  onAddRowBehind: () => void
  onRetry: () => void
}

export function CaptureRow({
  item,
  selected,
  shelves,
  onToggle,
  onShelf,
  onDepth,
  onAddRowBehind,
  onRetry,
}: CaptureRowProps) {
  const { t } = useI18n()
  const shelf = shelves.find((s) => s.id === item.shelfId)

  return (
    <div className={`caprow${selected ? ' sel' : ''}`}>
      <input
        type="checkbox"
        checked={selected}
        disabled={item.status !== 'ready'}
        onChange={onToggle}
        aria-label={item.filename}
      />
      <img src={item.previewUrl} alt="" />
      <div className="m">
        <div className="fn rtl-safe">{item.filename}</div>

        {item.status === 'uploading' && (
          <span className="tiny muted">{t.uploading}</span>
        )}

        {item.status === 'error' && (
          <span className="tiny warn">
            {t.upload_failed}
            {item.error ? ` — ${item.error}` : ''}{' '}
            <button type="button" className="linkish" onClick={onRetry}>
              {t.retry}
            </button>
          </span>
        )}

        {item.status === 'ready' && (
          <div className="caprow-assign">
            <select
              aria-label={t.assign_shelf_label}
              value={item.shelfId ?? ''}
              onChange={(e) => onShelf(e.target.value)}
            >
              {shelves.map((s) => (
                <option key={s.id} value={s.id} className="rtl-safe">
                  {s.label || t.unassigned}
                </option>
              ))}
            </select>
            {shelf && shelf.depth_count > 1 && (
              <select
                aria-label={t.depth_n(item.depth)}
                value={item.depth}
                onChange={(e) => onDepth(Number(e.target.value))}
              >
                {Array.from({ length: shelf.depth_count }, (_, i) => i + 1).map((d) => (
                  <option key={d} value={d}>{t.depth_n(d)}</option>
                ))}
              </select>
            )}
            {/* Surfaced even at depth_count 1 — §5.7 is explicit that most
                owners never discover the feature unless it is offered before
                they need it. */}
            <button type="button" className="linkish" onClick={onAddRowBehind}>
              {t.add_row_behind}
            </button>
          </div>
        )}
      </div>

      {item.readStage === 'done' && <span className="badge b-approved">✓</span>}
    </div>
  )
}
