/**
 * Client ring for the shelf-detail screen (P2.8). Same standard as every
 * other client ring: test what encodes a DECISION, not layout — the depth
 * bar's always-on visibility (§5.7), the not-seen badge staying purely
 * informational, the staleness line, mixed-script alignment (§7.2). The
 * fake server (`shelfHarness.ts`) hands back exactly the overview/books/
 * history each test needs, the same "inject, don't reimplement the rule
 * engine" idiom `captureHarness.ts` already uses.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nProvider } from '../lib/i18n'
import { ShelfPage } from './ShelfPage'
import { fakeBook, fakeShelf, fakeShelfServer } from './shelfHarness'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  // jsdom keeps localStorage across tests in a file — the language choice
  // persists on purpose (CLAUDE.md), so without this every test after one
  // that switches language starts in English.
  globalThis.localStorage.clear()
})

function renderShelf(onOpen: (id: string) => void = () => undefined) {
  return render(
    <I18nProvider>
      <ShelfPage shelfId="sh1" onBack={() => undefined} onOpen={onOpen} />
    </I18nProvider>,
  )
}

describe('shelf detail — the depth bar', () => {
  it('is visible even at depth_count 1, for discovery (§5.7)', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ depth_count: 1 }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    renderShelf()

    expect(await screen.findByRole('button', { name: 'שורה 1' })).toBeInTheDocument()
    // The "add a row behind" affordance sits right there too, same reasoning.
    expect(screen.getByText('+ הוספת שורה מאחור')).toBeInTheDocument()
  })

  it('switching rows reloads the books list for that row, not both mixed (§5.7 #1)', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ depth_count: 2 }),
      depths: [
        { depth: 1, last_read_at: '2026-08-01T00:00:00Z', is_stale: false },
        { depth: 2, last_read_at: null, is_stale: true },
      ],
      books: {
        1: [fakeBook({ id: 'b-front', title: 'ספר קדמי' })],
        2: [fakeBook({ id: 'b-back', title: 'ספר אחורי' })],
      },
    })
    renderShelf()

    expect(await screen.findByText('ספר קדמי')).toBeInTheDocument()
    expect(screen.queryByText('ספר אחורי')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'שורה 2' }))

    await waitFor(() => expect(screen.getByText('ספר אחורי')).toBeInTheDocument())
    expect(screen.queryByText('ספר קדמי')).not.toBeInTheDocument()
  })
})

describe('shelf detail — the not-seen badge (§5.6, never a removal)', () => {
  it('shows the streak softly and still lists the book', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ depth_count: 1 }),
      depths: [{ depth: 1, last_read_at: '2026-08-05T00:00:00Z', is_stale: false }],
      books: {
        1: [fakeBook({
          id: 'b1', title: 'ספר שלא נראה',
          copies: [{
            id: 'b1c1', status: 'auto', label: '', shelf_id: 'sh1', depth: 1,
            tags: [], condition: '', acquired_at: null, lending: null,
            last_seen: null, sighting_count: 1, not_seen_streak: 2,
          }],
        })],
      },
    })
    renderShelf()

    expect(await screen.findByText('ספר שלא נראה')).toBeInTheDocument()
    expect(screen.getByText('לא נראה ב-2 הקריאות האחרונות — עדיין שם?'))
      .toBeInTheDocument()
  })

  it('shows no badge at all when the streak is zero', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ depth_count: 1 }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
      books: {
        1: [fakeBook({
          id: 'b1', title: 'ספר שנראה',
          copies: [{
            id: 'b1c1', status: 'auto', label: '', shelf_id: 'sh1', depth: 1,
            tags: [], condition: '', acquired_at: null, lending: null,
            last_seen: null, sighting_count: 1, not_seen_streak: 0,
          }],
        })],
      },
    })
    renderShelf()

    expect(await screen.findByText('ספר שנראה')).toBeInTheDocument()
    expect(screen.queryByText(/לא נראה/)).not.toBeInTheDocument()
  })
})

describe('shelf detail — staleness', () => {
  it('flags a row read less recently than its sibling, in the shelf-level line', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ depth_count: 2 }),
      depths: [
        { depth: 1, last_read_at: '2026-08-05T00:00:00Z', is_stale: false },
        { depth: 2, last_read_at: null, is_stale: true },
      ],
      lastReadAt: '2026-08-05T00:00:00Z',
    })
    renderShelf()

    await screen.findByRole('button', { name: 'שורה 1' })
    expect(screen.getByText(/שורה 2.*מעולם לא נקרא/)).toBeInTheDocument()
  })

  it('shows no staleness line at all when nothing is stale', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ depth_count: 1 }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    const { container } = renderShelf()

    await screen.findByRole('button', { name: 'שורה 1' })
    // "never read yet" (the header's own line) legitimately contains the
    // substring "לא נקרא" too -- the staleness NOTE is its own element.
    expect(container.querySelector('.stalenote')).not.toBeInTheDocument()
  })
})

describe('shelf detail — read history as diffs (§5.5/§5.6)', () => {
  it('renders the headline counts from the archived diff summary', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ depth_count: 1 }),
      depths: [{ depth: 1, last_read_at: '2026-08-05T00:00:00Z', is_stale: false }],
      history: {
        1: [{
          id: 'rd1', shelf_id: 'sh1', depth: 1, mode: 'spines', status: 'done',
          claim_count: 16, started_at: '2026-08-05T00:00:00Z',
          finished_at: '2026-08-05T00:05:00Z', error: null,
          diff_summary: { added: 3, corrected: 1, unchanged: 12, needs_decision: 0,
                         not_seen: 1, rejected: 0, ignored: 0 },
        }],
      },
    })
    renderShelf()

    expect(await screen.findByText('+3 נוספו')).toBeInTheDocument()
    expect(screen.getByText('1 תוקנו')).toBeInTheDocument()
    expect(screen.getByText('12 ללא שינוי')).toBeInTheDocument()
    expect(screen.getByText('1 לא נראו')).toBeInTheDocument()
    // No "run 17"-style handle anywhere (§5.5: runs are not user-facing).
    expect(screen.queryByText(/run/i)).not.toBeInTheDocument()
  })

  it('shows the empty state before the shelf has ever been read', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ depth_count: 1 }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
      history: { 1: [] },
    })
    renderShelf()

    expect(await screen.findByText('אין עדיין קריאות למדף הזה')).toBeInTheDocument()
  })
})

describe('shelf detail — mixed-script alignment (UI_PLAN §7.2)', () => {
  it('marks the shelf label and a book title/author rtl-safe', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ label: 'Living room', depth_count: 1 }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
      books: { 1: [fakeBook({ id: 'b1', title: 'Sapiens', author: 'Yuval Noah Harari' })] },
    })
    renderShelf()

    expect(await screen.findByText('Living room')).toHaveClass('rtl-safe')
    expect(screen.getByText('Sapiens')).toHaveClass('rtl-safe')
    expect(screen.getByText('Yuval Noah Harari')).toHaveClass('rtl-safe')
  })
})

describe('shelf detail — opening a book', () => {
  it('calls onOpen with the book id when a row is clicked', async () => {
    fakeShelfServer({
      shelf: fakeShelf({ depth_count: 1 }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
      books: { 1: [fakeBook({ id: 'b1', title: 'ספר לדוגמה' })] },
    })
    const onOpen = vi.fn()
    renderShelf(onOpen)

    await userEvent.click(await screen.findByText('ספר לדוגמה'))
    expect(onOpen).toHaveBeenCalledWith('b1')
  })
})

describe('shelf detail — an absent shelf', () => {
  it('shows a not-found state rather than an empty page', async () => {
    fakeShelfServer({ shelf: null })
    renderShelf()

    expect(await screen.findByText('המדף לא נמצא')).toBeInTheDocument()
  })
})
