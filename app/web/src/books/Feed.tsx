/**
 * The books feed, in both shapes.
 *
 * **Both are image-free.** Owner's call, UI_PLAN §2: *"the spine crop is a
 * slice of the shelf a book happened to sit on, not a cover; a column of them
 * is noise."* The crop stays evidence — it belongs in book detail and review
 * rows, not in a browsing list. So the grid is a denser text layout, not a
 * gallery, and there is nothing here waiting on a BlobStore.
 *
 * There is no location column: a book's physical location comes from the map
 * (VISION §1.1) and is null until pillar 6. It renders when it is non-null,
 * which today is never — an empty column would just be a promise the product
 * cannot keep.
 */
import { useEffect, useRef } from 'react'
import type { Book } from '../api/client'
import { useI18n, type Strings } from '../lib/i18n'

export type View = 'list' | 'grid'

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n()
  const label: Record<string, string> = {
    auto: t.st_auto,
    approved: t.st_approved,
    manual: t.st_manual,
  }
  return (
    <span className={`badge b-${status}`}>{label[status] ?? status}</span>
  )
}

function subtitle(book: Book, t: Strings): string {
  return book.author || `— ${t.author_label} —`
}

/** The borrower of whichever copy is currently out, or null. VISION §5.2:
 *  lending state is "visible in list and detail" — not detail alone. */
function lentTo(book: Book): string | null {
  return book.copies.find((c) => c.lending?.is_out)?.lending?.lent_to ?? null
}

export function CopyBadges({ book }: { book: Book }) {
  const { t } = useI18n()
  const borrower = lentTo(book)
  return (
    <>
      {borrower && <span className="badge b-lent">{t.lent_to(borrower)}</span>}
      {book.copy_count > 1 && (
        <span className="badge b-copies">×{book.copy_count}</span>
      )}
    </>
  )
}

function BookRow({ book, onOpen }: { book: Book; onOpen: (id: string) => void }) {
  const { t } = useI18n()
  return (
    <button type="button" className="brow" onClick={() => onOpen(book.id)}>
      <span className="meta">
        <span className="t rtl-safe">{book.title}</span>
        <span className="a rtl-safe">{subtitle(book, t)}</span>
      </span>
      <span className="chiprow">
        <StatusBadge status={book.status} />
        <CopyBadges book={book} />
      </span>
    </button>
  )
}

function BookCard({ book, onOpen }: { book: Book; onOpen: (id: string) => void }) {
  const { t } = useI18n()
  return (
    <button type="button" className="card" onClick={() => onOpen(book.id)}>
      <span className="meta">
        <span className="t rtl-safe">{book.title}</span>
        <span className="a rtl-safe">{subtitle(book, t)}</span>
        <span className="foot">
          <StatusBadge status={book.status} />
          <CopyBadges book={book} />
        </span>
      </span>
    </button>
  )
}

export interface FeedProps {
  items: Book[]
  view: View
  hasMore: boolean
  loadingMore: boolean
  onLoadMore: () => void
  onOpen: (id: string) => void
}

export function Feed({
  items,
  view,
  hasMore,
  loadingMore,
  onLoadMore,
  onOpen,
}: FeedProps) {
  const { t } = useI18n()
  const sentinel = useRef<HTMLDivElement | null>(null)

  // Endless scroll against a REAL paginated server, which the mock never had
  // to do — it sliced a fully-loaded array. rootMargin prefetches before the
  // user reaches the bottom, so the next page is usually already there.
  useEffect(() => {
    const node = sentinel.current
    if (!node || !hasMore) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) onLoadMore()
      },
      { rootMargin: '400px' },
    )
    io.observe(node)
    return () => io.disconnect()
  }, [hasMore, onLoadMore, items.length])

  if (items.length === 0) return null

  const Item = view === 'list' ? BookRow : BookCard
  return (
    <>
      <div className={view === 'list' ? 'booklist' : 'bookgrid'}>
        {items.map((b) => (
          <Item key={b.id} book={b} onOpen={onOpen} />
        ))}
      </div>
      {hasMore && (
        <div className="sentinel" ref={sentinel} aria-hidden="true">
          {loadingMore ? <span className="loading">{t.loading}</span> : null}
        </div>
      )}
    </>
  )
}
