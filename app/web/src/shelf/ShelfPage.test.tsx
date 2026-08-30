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
import { userEvent } from '../test/user'
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
    // ⚠ The SINGULAR, in both. This test asserted `1 תוקנו` and `1 לא נראו`
    // — plural verbs with a 1 in front — for two years, because a number
    // joined to a bare noun in JSX is invisible to the counted-string guard.
    // The three nouns are functions now, where the rule can reach them.
    expect(screen.getByText('תוקן אחד')).toBeInTheDocument()
    expect(screen.getByText('12 ללא שינוי')).toBeInTheDocument()
    expect(screen.getByText('אחד לא נראה')).toBeInTheDocument()
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

describe('a shelf that answers for another identity (P6.4e, §3.11)', () => {
  it('says what it was, so the household name survives the merge', async () => {
    // ⚠ A merge destroys the absorbed shelf's row, and with it the name the
    // household calls it by — *"the one with the cookbooks"* long after the
    // drawing has been rearranged. §3.11 records the label and the former
    // ADDRESS precisely so the library can still answer, and this is the one
    // screen that says it out loud.
    fakeShelfServer({
      shelf: fakeShelf({
        formerly: [{ id: 'sh-old', label: 'ספרי בישול',
                     merged_at: '2026-08-26T10:00:00Z',
                     address: { section_id: 'se', col: 1, level: 3 } }],
      }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    renderShelf()

    expect(await screen.findByText('היה גם: ספרי בישול')).toBeInTheDocument()
  })

  it('falls back to the ADDRESS when the absorbed shelf had no name', async () => {
    // ⚠ Measured on the owner's library: **0 of 154 shelves carry a label**,
    // so `label || t.unassigned` rendered *"היה גם: לא משויך"* — one identical
    // panel per merge, saying nothing anybody can act on. The former address
    // is what §3.11 records rather than derives, for exactly this moment: it
    // is what a person reads off the drawing.
    fakeShelfServer({
      shelf: fakeShelf({
        formerly: [{ id: 'sh-old', label: '', merged_at: '2026-08-26T10:00:00Z',
                     address: { section_id: 'se', col: 2, level: 4 } }],
      }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    renderShelf()

    expect(await screen.findByText(/עמודה 2 · גובה 4/)).toBeInTheDocument()
    expect(screen.queryByText(/לא משויך/)).toBeNull()
  })

  it('says nothing when the absorbed shelf had neither name nor address', async () => {
    // The commonest case on a real library, and silence beats a line that
    // says *"formerly also: unassigned"*.
    fakeShelfServer({
      shelf: fakeShelf({
        formerly: [{ id: 'sh-old', label: '', merged_at: '2026-08-26T10:00:00Z',
                     address: null }],
      }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    renderShelf()

    await screen.findByRole('button', { name: 'שורה 1' })
    expect(screen.queryByText(/היה גם/)).toBeNull()
  })

  it('puts the most recent identity first', async () => {
    // `list_aliases` orders by `alias_id`, which is uuid4 — random to a person
    // reading a list of *what this shelf was*.
    fakeShelfServer({
      shelf: fakeShelf({
        formerly: [
          { id: 'a', label: 'הישן', merged_at: '2026-01-01T00:00:00Z',
            address: null },
          { id: 'b', label: 'החדש', merged_at: '2026-08-01T00:00:00Z',
            address: null },
        ],
      }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    renderShelf()

    await screen.findByText('היה גם: החדש')
    const said = [...document.querySelectorAll('p')]
      .map((p) => p.textContent).filter((t) => t && t.startsWith('היה גם'))
    expect(said).toEqual(['היה גם: החדש', 'היה גם: הישן'])
  })

  it('says nothing at all for a shelf nothing was merged into', async () => {
    // Which is almost every shelf. An empty `formerly` renders nothing — not
    // a heading with no rows under it.
    fakeShelfServer({
      shelf: fakeShelf(),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    renderShelf()

    await screen.findByRole('button', { name: 'שורה 1' })
    expect(screen.queryByText(/היה גם/)).toBeNull()
  })
})

describe('filing a photo against a shelf, with no read (P6.7d)', () => {
  /**
   * The owner: *"How do I attach an image to a shelf?"* Until this, the only
   * path was the Capture tab's shelf dropdown, which starts a READ — money
   * per photo and a queue of findings needing a ✓. Filing a picture and
   * reading it are different intentions, and one of them is free.
   */
  const file = (name = 'shelf.jpg') =>
    new File([new Uint8Array([1, 2, 3])], name, { type: 'image/jpeg' })

  it('stores the photo and files it, and starts NO read', async () => {
    // ⚠⚠ The whole item is the last clause. Two calls in order — the bytes,
    // then the binding — and nothing that would spend money. Asserted on the
    // METHOD as well as the path, because `GET .../reads` is what this screen
    // legitimately does on every load and `POST .../reads` is what it must
    // never do.
    const server = fakeShelfServer({
      shelf: fakeShelf(),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    renderShelf()
    const control = await screen.findByLabelText('הוספת תמונה')

    await userEvent.upload(control, file())

    await waitFor(() => expect(
      server.writes.map((w) => `${w.method} ${w.path}`)).toEqual([
        'POST /api/v1/images',
        'POST /api/v1/captures',
      ]))
    expect(server.writes[1]!.body)
      .toEqual({ image_id: 'img-key', shelf_id: 'sh1', depth: 1 })
    expect(server.writes.some((w) => w.path.endsWith('/reads')))
      .toBe(false)
  })

  it('files it at the depth the owner is LOOKING at', async () => {
    // §5.7: depth is declared, never detected. A photo of row 2 filed against
    // row 1 is a photograph of the wrong scene — which is the reason captures
    // are keyed by (shelf, depth) at all.
    const server = fakeShelfServer({
      shelf: fakeShelf({ depth_count: 2 }),
      depths: [{ depth: 1, last_read_at: null, is_stale: false },
               { depth: 2, last_read_at: null, is_stale: false }],
    })
    renderShelf()
    await userEvent.click(await screen.findByRole('button', { name: 'שורה 2' }))

    // And the label SAYS which row, once there is more than one — the front
    // row is never called a row when it is the only one (UI_PLAN §1.1).
    const control = await screen.findByLabelText('הוספת תמונה לשורה 2')
    await userEvent.upload(control, file())

    await waitFor(() => expect(
      server.writes.find((w) => w.path === '/api/v1/captures')?.body)
      .toEqual({ image_id: 'img-key', shelf_id: 'sh1', depth: 2 }))
  })

  it('says it failed rather than claiming a photo it never stored', async () => {
    const server = fakeShelfServer({
      shelf: fakeShelf(),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    server.refuseCapture = 500
    renderShelf()

    await userEvent.upload(await screen.findByLabelText('הוספת תמונה'), file())

    expect(await screen.findByText('לא הצלחנו לשמור את התמונה'))
      .toBeInTheDocument()
  })

  it('files the SAME photo twice when it is chosen twice', async () => {
    // ⚠ A file input raises no `change` for an unchanged value, so the
    // control clears itself after every pick. Without that, choosing the same
    // picture again does nothing at all — and "nothing happened" after a
    // retry reads as a dead control rather than as a duplicate refused.
    //
    // It is a real gesture here, not a hypothetical: two photos of one shelf
    // taken seconds apart can be byte-identical, and the server's key IS the
    // content hash, so the second upload is free and the second capture is
    // the one that carries the intent.
    const server = fakeShelfServer({
      shelf: fakeShelf(),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    renderShelf()
    const same = file()

    const control = await screen.findByLabelText('הוספת תמונה')
    await userEvent.upload(control, same)
    await waitFor(() => expect(
      server.writes.filter((w) => w.path === '/api/v1/captures')).toHaveLength(1))

    // ⚠ The element is re-read: the screen reloads after the first file, so
    // the control the test is holding may be a different node.
    await userEvent.upload(
      await screen.findByLabelText('הוספת תמונה'), same)
    await waitFor(() => expect(
      server.writes.filter((w) => w.path === '/api/v1/captures')).toHaveLength(2))
  })

  it('promises, in the idle state, that this costs nothing', async () => {
    // The sentence is the feature's whole argument for existing beside the
    // Capture tab. Without it the control is indistinguishable from the one
    // that spends money.
    fakeShelfServer({
      shelf: fakeShelf(),
      depths: [{ depth: 1, last_read_at: null, is_stale: false }],
    })
    renderShelf()

    expect(await screen.findByText(
      'התמונה נשמרת למדף בלבד. לא נקראת, לא עולה כלום, ולא מוסיפה ספרים.'))
      .toBeInTheDocument()
  })
})

