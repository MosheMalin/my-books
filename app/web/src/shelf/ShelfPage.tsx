/**
 * The shelf-detail screen (P2.8, UI_PLAN §3 level 3) — mounted at
 * `#/map/<shelfId>`. Reachable today from the Capture tab's *"open the
 * shelf →"* chip and by direct URL; there is no Map tab yet to drill down
 * from (pillar 6), so this is the WHOLE of "level 3" standing alone until
 * levels 1-2 exist to lead into it (see `lib/route.ts`'s own note).
 *
 * Photo · last-read date and declared depth · a soft staleness line · the
 * ALWAYS-visible depth bar (§5.7 — even at `depth_count` 1, for discovery)
 * · the books at the selected depth (the durable §5.6 list, never
 * auto-pruned) · read history as diffs. This IS the history UI; there is no
 * run list anywhere else (§5.5).
 */
import { useI18n } from '../lib/i18n'
import { formatDate, type Lang } from '@booksnap/ui'
import { CopyBadges, StatusBadge } from '../books/Feed'
import { ReadHistory } from './ReadHistory'
import { useShelfDetail } from './useShelfDetail'
import { imageUrl, type Book, type DepthStatusDTO } from '../api/client'

export interface ShelfPageProps {
  shelfId: string
  onBack: () => void
  onOpen: (bookId: string) => void
}

function stalenessLine(
  depths: DepthStatusDTO[],
  t: ReturnType<typeof useI18n>['t'],
  // `Lang`, not `string`: the shared formatter takes the union, so a locale
  // this app has no strings for cannot reach the date formatting either.
  lang: Lang,
): string | null {
  const stale = depths.filter((d) => d.is_stale)
  if (stale.length === 0) return null
  return stale
    .map((d) => {
      const row = t.depth_n(d.depth)
      return d.last_read_at
        ? t.stale_since(row, formatDate(d.last_read_at, lang))
        : t.stale_never(row)
    })
    .join(' · ')
}

function BookRow({ book, onOpen }: { book: Book; onOpen: (id: string) => void }) {
  const { t } = useI18n()
  const streak = book.copies[0]?.not_seen_streak ?? null
  return (
    <button type="button" className="brow" onClick={() => onOpen(book.id)}>
      <span className="meta">
        <span className="t rtl-safe">{book.title}</span>
        <span className="a rtl-safe">{book.author || `— ${t.author_label} —`}</span>
      </span>
      <span className="chiprow">
        <StatusBadge status={book.status} />
        <CopyBadges book={book} />
        {streak !== null && streak > 0 && (
          <span className="badge b-review" title={
            streak === 1 ? t.not_seen_streak_one : t.not_seen_streak_n(streak)
          }>
            {streak === 1 ? t.not_seen_streak_one : t.not_seen_streak_n(streak)}
          </span>
        )}
      </span>
    </button>
  )
}

export function ShelfPage({ shelfId, onBack, onOpen }: ShelfPageProps) {
  const { t, lang } = useI18n()
  const shelfDetail = useShelfDetail(shelfId)
  const { state } = shelfDetail
  const stale = state.kind === 'ready' ? stalenessLine(state.depths, t, lang) : null

  return (
    <div className="bookpage shelfpage">
      <button type="button" className="btn ghost" onClick={onBack}>
        ← {t.back}
      </button>

      {state.kind === 'loading' && <p className="loading">{t.loading}</p>}
      {state.kind === 'missing' && <p className="empty">{t.shelf_not_found}</p>}

      {state.kind === 'ready' && (
        <>
          <div className="panel shelfhero">
            <div className="body">
              <div className="shelfheroTop">
                {shelfDetail.photoImageId ? (
                  <img
                    className="shelfphoto"
                    src={imageUrl(shelfDetail.photoImageId)}
                    alt={t.shelf_untitled_photo_alt}
                  />
                ) : (
                  <div className="shelfphoto shelfphoto-empty" aria-hidden="true" />
                )}
                <div className="shelfheroMeta">
                  <h2 className="rtl-safe">{state.shelf.label || t.unassigned}</h2>
                  <p className="muted">
                    {state.lastReadAt
                      ? t.shelf_last_read(formatDate(state.lastReadAt, lang))
                      : t.shelf_never_read}
                  </p>
                  {stale && <p className="tiny stalenote">{stale}</p>}
                </div>
              </div>

              {/* Always visible, even at depth_count 1 (§5.7) — most owners
                  never learn depth exists unless it's offered before they
                  need it, same reasoning as the Capture tab's own row. */}
              <div className="depthbar" role="group" aria-label={t.depth_bar_label}>
                {state.depths.map((d) => (
                  <button
                    key={d.depth}
                    type="button"
                    className={`depthbtn${shelfDetail.depth === d.depth ? ' on' : ''}`}
                    aria-pressed={shelfDetail.depth === d.depth}
                    onClick={() => shelfDetail.setDepth(d.depth)}
                  >
                    {t.depth_n(d.depth)}
                    {d.is_stale && <span className="dot" aria-hidden="true" />}
                  </button>
                ))}
                <button
                  type="button"
                  className="linkish"
                  disabled={shelfDetail.addingRow}
                  onClick={() => void shelfDetail.addRowBehind()}
                >
                  {t.add_row_behind}
                </button>
              </div>
            </div>
          </div>

          <div className="panel shelfbooks">
            <h3>
              <span>{t.shelf_books_title}</span>
              <span className="muted tiny">{shelfDetail.books.length}</span>
            </h3>
            <div className="body">
              {shelfDetail.booksLoading && <p className="loading">{t.loading}</p>}
              {shelfDetail.booksError && (
                <p className="errorbox" role="alert">{shelfDetail.booksError}</p>
              )}
              {!shelfDetail.booksLoading && shelfDetail.books.length === 0 && (
                <p className="empty">{t.shelf_books_empty}</p>
              )}
              {!shelfDetail.booksLoading && shelfDetail.books.length > 0 && (
                <div className="booklist">
                  {shelfDetail.books.map((b) => (
                    <BookRow key={`${b.id}:${b.copies[0]?.id ?? ''}`} book={b}
                            onOpen={onOpen} />
                  ))}
                </div>
              )}
            </div>
          </div>

          <ReadHistory reads={shelfDetail.history} loading={shelfDetail.historyLoading} />
        </>
      )}
    </div>
  )
}
