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
  open: boolean
  shelves: Shelf[]
  onToggle: () => void
  onOpen: () => void
  onShelf: (shelfId: string) => void
  onDepth: (depth: number) => void
  onRetry: () => void
}

export function CaptureRow({
  item,
  selected,
  open,
  shelves,
  onToggle,
  onOpen,
  onShelf,
  onDepth,
  onRetry,
}: CaptureRowProps) {
  const { t } = useI18n()
  const shelf = shelves.find((s) => s.id === item.shelfId)

  return (
    <div className={`caprow${selected ? ' sel' : ''}${open ? ' open' : ''}`}>
      <input
        type="checkbox"
        checked={selected}
        disabled={item.status !== 'ready'}
        onChange={onToggle}
        aria-label={item.filename}
      />
      {/* The photo IS the way into its own history (P2.10, §12.2 #10) — the
          thumbnail is the button, which is why the row's picture is not a
          bare <img>. Only once it exists server-side: an upload still in
          flight has no runs to show. */}
      {item.status === 'ready' ? (
        <button type="button" className="thumbbtn" onClick={onOpen}
                aria-label={t.open_image}>
          <img src={item.previewUrl} alt="" />
        </button>
      ) : (
        <img src={item.previewUrl} alt="" />
      )}
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
            {/* No "add a row behind" (owner, 2026-08-09). P2.7 surfaced it
                here on §5.7's reasoning that nobody discovers depth unless it
                is offered early — but the owner's call is that this tab is
                about IMAGES, and declaring the shape of a piece of furniture
                belongs to the Map tab with the rest of the shelf model. The
                depth PICKER above stays: a shelf that is already stacked still
                has to say which row a photo shows. */}
          </div>
        )}

        {item.status === 'ready' && item.readStage !== 'unread' && (
          <button type="button" className="linkish" onClick={onOpen}>
            {t.open_image}
          </button>
        )}
      </div>

      {item.readStage === 'done' && <span className="badge b-approved">✓</span>}
    </div>
  )
}
