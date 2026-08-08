/**
 * The client test ring for the Capture tab (P2.7).
 *
 * Same standard as the Python rings and the Books tab's own ring: test what
 * encodes a DECISION, not layout and not DTO plumbing. The fake server
 * (`captureHarness.ts`) does not reimplement `reconcile()`/`apply_diff` —
 * each test hands it the exact diff a `POST .../apply` call should answer
 * with, the way the Python API ring injects a `StubReader`.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nProvider } from '../lib/i18n'
import { CaptureTab } from './CaptureTab'
import {
  claim,
  emptyDiff,
  fakeBook,
  fakeCaptureServer,
  outcome,
  readSummary,
} from './captureHarness'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  // jsdom keeps localStorage across tests in a file — the language choice
  // persists on purpose (CLAUDE.md), so without this every test after one
  // that switches language starts in English.
  globalThis.localStorage.clear()
})

function renderCapture() {
  return render(
    <I18nProvider>
      <CaptureTab />
    </I18nProvider>,
  )
}

async function dropOnePhoto(container: HTMLElement, filename = 'shelf.jpg') {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement
  const file = new File(['x'], filename, { type: 'image/jpeg' })
  await userEvent.upload(input, file)
}

describe('Capture tab — intake', () => {
  it('files a dropped photo onto a freshly auto-created shelf, shown as Unassigned', async () => {
    const server = fakeCaptureServer()
    const { container } = renderCapture()
    await dropOnePhoto(container, 'living-room.jpg')

    expect(await screen.findByText('living-room.jpg')).toBeInTheDocument()
    // The auto-created shelf has no label — "Unassigned" means not yet
    // NAMED, never not yet filed (P2.1/P2.2).
    expect(await screen.findByText('לא משויך')).toBeInTheDocument()
    expect(server.shelves).toHaveLength(1)
    expect(server.shelves[0]!.label).toBe('')
  })

  it('marks a user-generated filename rtl-safe (UI_PLAN §7.2)', async () => {
    fakeCaptureServer()
    const { container } = renderCapture()
    await dropOnePhoto(container, 'מדף הסלון.jpg')
    expect(await screen.findByText('מדף הסלון.jpg')).toHaveClass('rtl-safe')
  })

  // REMOVED 2026-08-09 (owner): "add a row behind" is gone from this tab.
  // P2.7 surfaced it here on §5.7's argument that nobody discovers depth
  // unless it is offered early; the owner's call is that Capture is about
  // IMAGES and declaring the shape of a piece of furniture belongs to the Map
  // tab. The test went with the control — a test for a button that must not
  // exist is a test that stops the next person from reading the reason.

  it('enables Run only once a photo is both uploaded and selected', async () => {
    fakeCaptureServer()
    const { container } = renderCapture()
    const runBtn = () => screen.getByRole('button', { name: /הרצה על הנבחרים/ })
    expect(runBtn()).toBeDisabled()

    await dropOnePhoto(container)
    await screen.findByText('לא משויך')
    // Freshly uploaded photos start selected (the common case: read what I
    // just dropped) — so Run is enabled without an extra click.
    await waitFor(() => expect(runBtn()).toBeEnabled())
  })
})

describe('Capture tab — review', () => {
  /** Drops a photo, starts a read, and waits for its review panel. Every
   *  test sets `server.diffFor` itself BEFORE calling this. */
  async function startRun() {
    const { container } = renderCapture()
    await dropOnePhoto(container)
    await screen.findByText('לא משויך')
    await userEvent.click(screen.getByRole('button', { name: /הרצה על הנבחרים/ }))
    // The empty-state "what we found" placeholder only shows before any run
    // exists; once one does, its own hint line is the thing to wait for.
    return screen.findByText(
      'אישור כאן הוא רק קיצור דרך. המדף הוא הבית של הספרים והיסטוריית הקריאות.',
    )
  }

  it('shows an AUTO "added" claim with no action buttons — reconcile() already decided it', async () => {
    const server = fakeCaptureServer()
    const diff = {
      ...emptyDiff('sh1', 1, 'rd1'),
      added: [outcome({
        kind: 'added', reason: 'new_book_auto',
        claim: claim({ id: 'c1', title: 'מלכי הכופרים', author: 'פול קארני',
                       tier: 'auto', score: 91 }),
      })],
    }
    server.diffFor = () => diff
    await startRun()

    expect(await screen.findByText('מלכי הכופרים')).toBeInTheDocument()
    expect(screen.getByText('חדש')).toBeInTheDocument()      // diff badge: new
    // No confirm/reject and no duplicate prompt for a plain 'added' claim.
    // (Not `queryByText('✓')`: the intake row's own "this shelf was read"
    // badge also renders a bare ✓, as a <span> rather than a button.)
    expect(screen.queryByRole('button', { name: '✓' })).not.toBeInTheDocument()
    expect(screen.queryByText('אותו עותק')).not.toBeInTheDocument()
  })

  it('approving a pending finding is what puts it in the library', async () => {
    // REVERSED 2026-08-09 (owner). This used to be a REVIEW-tier-only test,
    // because an AUTO claim entered the library on its own. Both tiers wait
    // for a human now, and both wear the same controls (the owner's item 7)
    // — so this covers an AUTO claim, the case that used to skip the
    // question entirely.
    const server = fakeCaptureServer()
    const c1 = claim({ id: 'c1', title: 'ספר חדש', tier: 'auto', score: 91 })
    let answered = false
    server.diffFor = (_readId, answers) => {
      if (answers.some((a) => a.claim_id === 'c1' && a.kind === 'confirm')) answered = true
      return answered
        ? { ...emptyDiff('sh1', 1, 'rd1'),
            unchanged: [outcome({
              kind: 'unchanged', reason: 'same_location', claim: c1,
              existing_book: fakeBook('bk1', { title: 'ספר חדש',
                                               status: 'approved' }),
            })] }
        : { ...emptyDiff('sh1', 1, 'rd1'),
            needs_decision: [outcome({
              kind: 'needs_decision', reason: 'new_book_unconfirmed', claim: c1,
            })] }
    }
    await startRun()
    await screen.findByText('ספר חדש')
    expect(screen.getByText('ממתין לאישור')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'אישור הספר' }))

    await waitFor(() => expect(screen.getByText('היה כאן')).toBeInTheDocument())
    expect(screen.queryByText('ממתין לאישור')).not.toBeInTheDocument()
  })

  it('an ambiguous-location claim shows the §5.4 three-way prompt with its default stated on screen', async () => {
    const server = fakeCaptureServer()
    const c1 = claim({ id: 'c1', title: 'ציפור הנפש', tier: 'auto', score: 80 })
    const diff = {
      ...emptyDiff('sh1', 1, 'rd1'),
      needs_decision: [outcome({
        kind: 'needs_decision', reason: 'ambiguous_location', claim: c1,
        existing_book: {
          id: 'bk1', title: 'ציפור הנפש', author: '', author_key: '',
          status: 'approved', copy_count: 1, added_at: null,
          shared_book_id: null, work: { rating: null, notes: '', read_status: null },
          copies: [{
            id: 'cp1', status: 'approved', label: '', shelf_id: null, depth: null,
            tags: [], condition: '', acquired_at: null, lending: null,
            last_seen: null, sighting_count: 1,
          }],
        },
      })],
    }
    server.diffFor = () => diff
    await startRun()

    expect(await screen.findByText('כפילות?')).toBeInTheDocument()
    expect(screen.getByText('אותו עותק')).toBeInTheDocument()
    expect(screen.getByText('עותק נוסף')).toBeInTheDocument()
    expect(screen.getByText('ספר שגוי')).toBeInTheDocument()
    // §5.4: the default answer is stated on screen, not just implied.
    expect(screen.getByText('ברירת המחדל: אותו עותק')).toBeInTheDocument()
    // Not a confirm/reject question — that vocabulary belongs to a
    // review-tier new-book claim, a different reason entirely.
    expect(screen.queryByRole('button', { name: '✓' })).not.toBeInTheDocument()
  })

  it('"try a better match" reveals the ranked runners-up with their rejection reason', async () => {
    const server = fakeCaptureServer()
    const diff = {
      ...emptyDiff('sh1', 1, 'rd1'),
      unchanged: [outcome({
        kind: 'unchanged', reason: 'same_location', book_key: 'k1',
        existing_book: fakeBook('bk1', { title: 'מלכי הכופרים' }),
        claim: claim({
          id: 'c1', title: 'מלכי הכופרים', tier: 'auto', score: 91,
          text: 'מלכי הכופרים פול קארני',
          alternatives: [
            { title: 'ספינות מן המערב', author: 'פול קארני', score: 61.2, reason: '' },
            { title: 'הכופרים', author: '', score: 40,
              reason: 'title similarity 40 < 47' },
          ],
        }),
      })],
    }
    server.diffFor = () => diff
    await startRun()
    await screen.findByText('מלכי הכופרים')

    await userEvent.click(screen.getByRole('button', { name: 'התאמה אחרת?' }))

    expect(await screen.findByText('ספינות מן המערב')).toBeInTheDocument()
    expect(screen.getByText('title similarity 40 < 47')).toBeInTheDocument()
    // The raw read lives HERE, not on the row: it explains the finding, it
    // does not identify it (owner, 2026-08-09).
    expect(screen.getByText(/מלכי הכופרים פול קארני/)).toBeInTheDocument()
  })

  it('picking a runner-up re-titles the book behind a settled finding', async () => {
    // REVERSED 2026-08-09 (owner). P2.7 deliberately shipped this list
    // read-only because no domain op could re-point a claim; the operation
    // arrived from the approval reversal (confirm-as-corrected / patch), so
    // UI_PLAN §4's "one-click acceptable" is finally honest.
    const server = fakeCaptureServer()
    server.diffFor = () => ({
      ...emptyDiff('sh1', 1, 'rd1'),
      unchanged: [outcome({
        kind: 'unchanged', reason: 'same_location', book_key: 'k1',
        existing_book: fakeBook('bk1', { title: 'מלכי הכופריט' }),
        claim: claim({
          id: 'c1', title: 'מלכי הכופריט', tier: 'auto', score: 91,
          alternatives: [{ title: 'מלכי הכופרים', author: 'פול קארני',
                           score: 88, reason: '' }],
        }),
      })],
    })
    await startRun()
    await userEvent.click(screen.getByRole('button', { name: 'התאמה אחרת?' }))
    await userEvent.click(await screen.findByRole('button', { name: 'בחירה' }))

    await waitFor(() => {
      const patch = server.bodies.find((b) => 'title' in (b ?? {}))
      expect(patch?.title).toBe('מלכי הכופרים')
      expect(patch?.author).toBe('פול קארני')
    })
    expect(server.calls.some((c) => c.includes('/books/bk1'))).toBe(true)
  })

  it('picking a runner-up on a PENDING finding approves it as that book', async () => {
    // Same click, a different write — there is no book to patch yet, so it
    // is confirm-as-corrected. One act, one request, either way.
    const server = fakeCaptureServer()
    server.diffFor = () => ({
      ...emptyDiff('sh1', 1, 'rd1'),
      needs_decision: [outcome({
        kind: 'needs_decision', reason: 'new_book_unconfirmed', book_key: 'k1',
        claim: claim({
          id: 'c1', title: 'מלכי הכופריט', tier: 'auto', score: 70,
          alternatives: [{ title: 'מלכי הכופרים', author: 'פול קארני',
                           score: 88, reason: '' }],
        }),
      })],
    })
    await startRun()
    await userEvent.click(screen.getByRole('button', { name: 'התאמה אחרת?' }))
    await userEvent.click(await screen.findByRole('button', { name: 'בחירה' }))

    await waitFor(() => {
      const body = server.bodies.find(
        (b) => (b as { answers?: { title?: string }[] }).answers?.[0]?.title)
      const answer = (body as { answers: { kind: string; title: string }[] }).answers[0]!
      expect(answer.kind).toBe('confirm')
      expect(answer.title).toBe('מלכי הכופרים')
    })
  })

  it('shows the author beside the title, and never the raw read on the row', async () => {
    // The claim and the book deliberately DISAGREE: the engine read a typo
    // and a human has since fixed the record. A settled row must show what
    // the book says now — the claim is frozen evidence and would keep
    // displaying the typo forever.
    const server = fakeCaptureServer()
    server.diffFor = () => ({
      ...emptyDiff('sh1', 1, 'rd1'),
      unchanged: [outcome({
        kind: 'unchanged', reason: 'same_location', book_key: 'k1',
        existing_book: fakeBook('bk1', { title: 'מלכי הכופרים',
                                         author: 'פול קארני' }),
        claim: claim({ id: 'c1', title: 'מלכי הכופריט', author: 'פ. קארני',
                       tier: 'auto', score: 91, text: 'מלכי הכופריט פ קארני' }),
      })],
    })
    await startRun()

    const title = await screen.findByText('מלכי הכופרים')
    const row = title.closest('.rrow') as HTMLElement
    expect(within(row).getByText('פול קארני')).toHaveClass('a')
    expect(within(row).queryByText('מלכי הכופריט')).not.toBeInTheDocument()
    // The guillemets line is gone from the row (it is in the panel now).
    expect(within(row).queryByText(/«/)).not.toBeInTheDocument()
    expect(server.calls.length).toBeGreaterThan(0)
  })

  it('a running read offers Stop, and Stop calls the stop endpoint', async () => {
    const server = fakeCaptureServer()
    server.nextReadStatus = 'running'
    const { container } = renderCapture()
    await dropOnePhoto(container)
    await screen.findByText('לא משויך')
    await userEvent.click(screen.getByRole('button', { name: /הרצה על הנבחרים/ }))

    const stopBtn = await screen.findByRole('button', { name: 'עצירה' })
    await userEvent.click(stopBtn)

    await waitFor(() => expect(server.calls.some((c) => c.includes('/stop'))).toBe(true))
  })
})

describe('Capture tab — the default reading mode', () => {
  it('preselects LLM reading, not the free Tesseract path', async () => {
    // Owner's call (2026-08-08). The measured gap is not close: the spine
    // path is ~10s/spine and tops out near 76% title-correct, and CLAUDE.md
    // already records llmpage as the engine's own default. Pinned because
    // "restore the deterministic default" is exactly the kind of tidy-looking
    // change that would silently hand every new user the worse reader.
    fakeCaptureServer()
    renderCapture()

    const llm = await screen.findByRole('radio', { name: /קריאת LLM/ })
    expect((llm as HTMLInputElement).checked).toBe(true)

    const spines = screen.getByRole('radio', { name: /פיצול לשדרות/ })
    expect((spines as HTMLInputElement).checked).toBe(false)
  })

  it('sends that mode when a read starts', async () => {
    // The selection has to reach the wire. A default that looks right on
    // screen and posts something else is the failure this catches.
    const server = fakeCaptureServer()
    const { container } = renderCapture()
    await dropOnePhoto(container)

    await userEvent.click(await screen.findByRole('button', { name: /הרצה/ }))
    await waitFor(() => {
      const started = server.bodies.find((b) => 'mode' in (b ?? {}))
      expect(started?.mode).toBe('llmpage')
    })
  })
})

describe('Capture tab — hydration on mount (P2.9)', () => {
  // The bug this section guards: upload -> run -> background the tab (or
  // just refresh) -> come back, and the photo and the read's progress had
  // both vanished, because `useCapture`'s state was session-only. Fixed by
  // rebuilding both from the server on mount (`useCapture.ts`'s `hydrate`).

  function shelf(over: Partial<import('../api/client').Shelf> = {}) {
    return {
      id: 'sh1', label: '', depth_count: 1, virtual: false,
      created_at: null, capture_count: 1, ...over,
    }
  }

  it('rebuilds the intake list from the server, surviving a refresh', async () => {
    const server = fakeCaptureServer([shelf()])
    server.captures.cap1 = {
      id: 'cap1', shelf_id: 'sh1', depth: 1, order: 0, image_id: 'img1',
      captured_at: '2026-08-01T00:00:00Z',
    }

    renderCapture()

    // No upload happened in THIS render — the row came back purely from
    // GET /shelves + GET .../captures, the same as after a real refresh.
    expect(await screen.findByText('img1')).toBeInTheDocument()
  })

  it('re-attaches an in-flight read instead of restarting it', async () => {
    const server = fakeCaptureServer([shelf()])
    server.captures.cap1 = {
      id: 'cap1', shelf_id: 'sh1', depth: 1, order: 0, image_id: 'img1',
      captured_at: null,
    }
    server.reads.push(readSummary({ id: 'rd1', shelf_id: 'sh1', depth: 1, status: 'running' }))
    // The poll that follows hydration reports the read has since settled —
    // exactly the "it finished while I was away" case.
    server.nextReadStatus = 'done'
    server.diffFor = (readId) => emptyDiff('sh1', 1, readId)

    renderCapture()
    await screen.findByText('img1')

    // The review panel appears once the (re-attached) poll notices 'done' —
    // proof the read is being watched, not that a fresh one was started.
    await screen.findByText(
      'אישור כאן הוא רק קיצור דרך. המדף הוא הבית של הספרים והיסטוריית הקריאות.',
      {}, { timeout: 3000 },
    )

    // No `POST .../reads` (start) ever fired — that body always carries
    // `mode`; only `GET` (poll) and `POST .../apply` did.
    expect(server.bodies.some((b) => 'mode' in b)).toBe(false)
    expect(server.calls.some((c) => c.includes('/reads/rd1'))).toBe(true)
  })

  it('polls an in-flight read immediately on visibilitychange, not only from the timer', async () => {
    const server = fakeCaptureServer([shelf()])
    server.captures.cap1 = {
      id: 'cap1', shelf_id: 'sh1', depth: 1, order: 0, image_id: 'img1',
      captured_at: null,
    }
    server.reads.push(readSummary({ id: 'rd1', shelf_id: 'sh1', depth: 1, status: 'running' }))
    server.nextReadStatus = 'running' // stays running until this test says otherwise

    renderCapture()
    await screen.findByText('img1')
    const before = server.calls.filter((c) => c.includes('/reads/rd1')).length

    Object.defineProperty(document, 'visibilityState', {
      value: 'visible', configurable: true,
    })
    document.dispatchEvent(new Event('visibilitychange'))

    // The polling interval is 1000ms — a poll landing comfortably inside
    // that window can only be the visibilitychange handler, not the timer.
    // (700ms, not a tighter margin: under a loaded test run the assertion
    // itself can be scheduled late, and this only needs to beat the OTHER
    // side's 1000ms, not race it to the millisecond.)
    await waitFor(() => {
      expect(server.calls.filter((c) => c.includes('/reads/rd1')).length)
        .toBeGreaterThan(before)
    }, { timeout: 700 })
  })
})

describe('Capture tab — the image workspace (P2.10, §12.2 #10)', () => {
  // The bug this section guards is the one §12.2 #10 names: the tab was a
  // one-way pipeline — drop, run, and the result scrolled away with no route
  // back, leaving *re-run on selected* as the only visible action on a photo
  // that had already been processed.

  function shelf(over: Partial<import('../api/client').Shelf> = {}) {
    return {
      id: 'sh1', label: '', depth_count: 1, virtual: false,
      created_at: null, capture_count: 1, ...over,
    }
  }

  const settled = (over = {}): import('../api/client').DiffDTO => ({
    ...emptyDiff('sh1', 1, 'rd1'),
    unchanged: [outcome({
      kind: 'unchanged', reason: 'same_location', book_key: 'k1',
      existing_book: fakeBook('bk1', { title: 'מלכי הכופרים' }),
      claim: claim({ id: 'c1', capture_id: 'cap1', title: 'מלכי הכופרים',
                     author: 'פול קארני', tier: 'auto', score: 91 }),
    })],
    ...over,
  })

  /** A hydrated photo that has already been read once — the state the
   *  workspace exists for. */
  function processedPhoto(diff?: import('../api/client').DiffDTO) {
    const server = fakeCaptureServer([shelf()])
    server.captures.cap1 = {
      id: 'cap1', shelf_id: 'sh1', depth: 1, order: 0, image_id: 'img1',
      captured_at: '2026-08-01T00:00:00Z',
    }
    const run = readSummary({
      id: 'rd1', shelf_id: 'sh1', depth: 1, status: 'done',
      finished_at: '2026-08-09T10:00:00Z',
      diff_summary: { added: 2, corrected: 0, unchanged: 1, needs_decision: 0,
                      not_seen: 0, rejected: 0, ignored: 0 },
    })
    server.reads.push(run)
    server.readsForCapture.cap1 = [run]
    if (diff) server.diffFor = () => diff
    return server
  }

  async function openWorkspace() {
    renderCapture()
    await screen.findByText('img1')
    await userEvent.click(screen.getAllByRole(
      'button', { name: 'מה נמצא בתמונה' })[0]!)
  }

  it('opens a processed photo onto its runs and their findings — without re-reading it', async () => {
    const server = processedPhoto(settled())
    await openWorkspace()

    expect(await screen.findByText('מלכי הכופרים')).toBeInTheDocument()
    // The whole point (§12.2 #10): looking costs nothing. No read was
    // started — a start always carries `mode` in its body.
    expect(server.bodies.some((b) => 'mode' in b)).toBe(false)
    expect(server.calls.some((c) => c.includes('/captures/cap1/reads'))).toBe(true)
    // ...and it is the read-only diff, not an apply, that fetched them.
    expect(server.calls.some((c) => c.includes('/reads/rd1/diff'))).toBe(true)
  })

  it('shows only the findings that came from THIS photo', async () => {
    // A read covers every capture at its (shelf, depth) — §5.7 #1 forbids a
    // partial read of a row — but the workspace was opened from one image.
    const server = processedPhoto(settled({
      added: [outcome({
        kind: 'added', reason: 'new_book_auto', book_key: 'k2',
        claim: claim({ id: 'c2', capture_id: 'cap-other',
                       title: 'ספר של תמונה אחרת' }),
      })],
    }))
    await openWorkspace()

    expect(await screen.findByText('מלכי הכופרים')).toBeInTheDocument()
    expect(screen.queryByText('ספר של תמונה אחרת')).not.toBeInTheDocument()
    expect(server.calls.length).toBeGreaterThan(0)
  })

  it('approves a finding, and stops offering it once the book is approved', async () => {
    const server = processedPhoto(settled())
    await openWorkspace()
    await screen.findByText('מלכי הכופרים')

    server.diffFor = () => settled({
      unchanged: [outcome({
        kind: 'unchanged', reason: 'same_location', book_key: 'k1',
        existing_book: fakeBook('bk1', { title: 'מלכי הכופרים',
                                         status: 'approved' }),
        claim: claim({ id: 'c1', capture_id: 'cap1', title: 'מלכי הכופרים' }),
      })],
    })
    await userEvent.click(screen.getByRole('button', { name: 'אישור הספר' }))

    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('/books/bk1/approve'))).toBe(true))
    // An approved book has nothing left to approve — the row must not keep
    // offering it (the ladder only goes up, `Status.merge`).
    await waitFor(() => expect(
      screen.queryByRole('button', { name: 'אישור הספר' })).not.toBeInTheDocument())
  })

  it('sends the corrected title when a finding is fixed by hand', async () => {
    const server = processedPhoto(settled())
    await openWorkspace()
    await screen.findByText('מלכי הכופרים')

    await userEvent.click(screen.getByRole('button', { name: 'תיקון פרטים' }))
    const title = screen.getByLabelText('כותרת')
    await userEvent.clear(title)
    await userEvent.type(title, 'מלכי הכופרים המתוקן')
    await userEvent.click(screen.getByRole('button', { name: 'שמירה' }))

    await waitFor(() => {
      const patch = server.bodies.find((b) => 'title' in (b ?? {}))
      expect(patch?.title).toBe('מלכי הכופרים המתוקן')
    })
  })

  it('retracts a finding and offers the undo, never leaving it silently gone', async () => {
    const server = processedPhoto(settled())
    const rejected: import('../api/client').DiffDTO = {
      ...emptyDiff('sh1', 1, 'rd1'),
      rejected: [outcome({
        kind: 'rejected', reason: 'rejected', book_key: 'k1',
        claim: claim({ id: 'c1', capture_id: 'cap1', title: 'מלכי הכופרים' }),
      })],
    }
    server.findingResult = (action) => (action === 'retract' ? rejected : settled())
    await openWorkspace()
    await screen.findByText('מלכי הכופרים')

    await userEvent.click(screen.getByRole('button', { name: 'הסרה' }))

    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('/findings/c1/retract'))).toBe(true))
    // A retracted finding stays on screen WITH its reason — "why isn't my
    // book showing up" has an answer, and the undo has somewhere to live.
    expect(await screen.findByText('נדחה')).toBeInTheDocument()
    expect(screen.getByText(
      'הוסר מכאן. קריאה נוספת של המדף לא תוסיף אותו שוב.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'ביטול ההסרה' }))
    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('/findings/c1/restore'))).toBe(true))
  })

  it('a photo that has never been read says so rather than showing nothing', async () => {
    const server = fakeCaptureServer([shelf()])
    server.captures.cap1 = {
      id: 'cap1', shelf_id: 'sh1', depth: 1, order: 0, image_id: 'img1',
      captured_at: null,
    }
    renderCapture()
    await screen.findByText('img1')
    await userEvent.click(screen.getAllByRole(
      'button', { name: 'מה נמצא בתמונה' })[0]!)

    expect(await screen.findByText('התמונה הזו עדיין לא נקראה')).toBeInTheDocument()
  })

  it('shows a pending finding of EITHER tier the same three controls', async () => {
    // The owner's item 7, and the reason it is one line of code: after
    // "nothing enters the library unapproved" an AUTO and a REVIEW finding
    // are the same STATE, so the controls follow the state, not the tier.
    const server = processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      needs_decision: [
        outcome({ kind: 'needs_decision', reason: 'new_book_unconfirmed',
                  claim: claim({ id: 'c1', capture_id: 'cap1', title: 'זוהה',
                                 tier: 'auto', score: 120 }) }),
        outcome({ kind: 'needs_decision', reason: 'new_book_unconfirmed',
                  claim: claim({ id: 'c2', capture_id: 'cap1', title: 'לבדיקה',
                                 tier: 'review', score: 61 }) }),
      ],
    })
    await openWorkspace()
    await screen.findByText('זוהה')

    for (const label of ['אישור הספר', 'תיקון פרטים', 'הסרה']) {
      expect(screen.getAllByRole('button', { name: label })).toHaveLength(2)
    }
    expect(server.calls.length).toBeGreaterThan(0)
  })

  it('shows the match score against its real maximum, not as a percentage', async () => {
    // `booksnap/match.py` scores 60·tcov_c + 25·tcov + 15·acov + 0.30·sim, so
    // 130 is a perfect match. A bare "130" beside a tier reads as a broken
    // percentage — which is exactly what the owner asked about.
    processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      unchanged: [outcome({
        kind: 'unchanged', reason: 'same_location', book_key: 'k1',
        existing_book: fakeBook('bk1'),
        claim: claim({ id: 'c1', capture_id: 'cap1', title: 'ספר',
                       tier: 'auto', score: 130 }),
      })],
    })
    await openWorkspace()
    expect(await screen.findByText(/130\/130/)).toBeInTheDocument()
  })

  it('approves every pending finding in one call, and only the pending ones', async () => {
    const server = processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      needs_decision: [
        outcome({ kind: 'needs_decision', reason: 'new_book_unconfirmed',
                  claim: claim({ id: 'c1', capture_id: 'cap1', title: 'א' }) }),
        outcome({ kind: 'needs_decision', reason: 'new_book_unconfirmed',
                  claim: claim({ id: 'c2', capture_id: 'cap1', title: 'ב' }) }),
        // §5.4's duplicate question is a DIFFERENT question — "approve all"
        // must never sweep it up, which is the POC's own hard-won rule.
        outcome({ kind: 'needs_decision', reason: 'ambiguous_location',
                  existing_book: fakeBook('bk9'),
                  claim: claim({ id: 'c3', capture_id: 'cap1', title: 'ג' }) }),
      ],
    })
    await openWorkspace()

    const bulk = await screen.findByRole('button', { name: 'אישור הכל (2)' })
    await userEvent.click(bulk)

    await waitFor(() => {
      const body = server.bodies.find(
        (b) => Array.isArray((b as { answers?: unknown[] }).answers)
          && ((b as { answers: unknown[] }).answers.length ?? 0) > 1)
      expect(body).toBeTruthy()
      const answers = (body as { answers: { claim_id: string; kind: string }[] }).answers
      expect(answers.map((a) => a.claim_id).sort()).toEqual(['c1', 'c2'])
      expect(answers.every((a) => a.kind === 'confirm')).toBe(true)
    })
  })

  it('fixing a pending finding approves it as corrected, in one call', async () => {
    const server = processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      needs_decision: [outcome({
        kind: 'needs_decision', reason: 'new_book_unconfirmed',
        claim: claim({ id: 'c1', capture_id: 'cap1', title: 'מלכי הכופריט' }),
      })],
    })
    await openWorkspace()
    await screen.findByText('מלכי הכופריט')

    await userEvent.click(screen.getByRole('button', { name: 'תיקון פרטים' }))
    const title = screen.getByLabelText('כותרת')
    await userEvent.clear(title)
    await userEvent.type(title, 'מלכי הכופרים')
    await userEvent.click(screen.getByRole('button', { name: 'תיקון ואישור' }))

    await waitFor(() => {
      const body = server.bodies.find(
        (b) => (b as { answers?: { title?: string }[] }).answers?.[0]?.title)
      const answer = (body as { answers: { kind: string; title: string }[] }).answers[0]!
      expect(answer.kind).toBe('confirm')
      expect(answer.title).toBe('מלכי הכופרים')
    })
  })

  it('adds a book the engine missed, to this photo', async () => {
    const server = processedPhoto(settled())
    await openWorkspace()
    await screen.findByText('מלכי הכופרים')

    await userEvent.click(screen.getByRole('button', { name: '+ הוספת ספר שהמנוע פספס' }))
    await userEvent.type(screen.getByLabelText('כותרת'), 'ספר שהמנוע פספס')
    await userEvent.click(screen.getByRole('button', { name: 'הוספה' }))

    await waitFor(() => {
      expect(server.calls.some((c) => c.endsWith('/reads/rd1/findings'))).toBe(true)
      const body = server.bodies.find((b) => 'title' in (b ?? {}) && !('answers' in (b ?? {})))
      expect((body as { title: string }).title).toBe('ספר שהמנוע פספס')
    })
  })

  it('offers the same approve / fix / remove loop on a LIVE run, not only in the workspace', async () => {
    // §12.2 #10's real content: "right after the read" and "a week later" are
    // the same act. If the live panel lost these, the tab would still be a
    // pipeline for the first minutes of a photo's life.
    const server = fakeCaptureServer()
    server.diffFor = () => settled()
    const { container } = renderCapture()
    await dropOnePhoto(container)
    await screen.findByText('לא משויך')
    await userEvent.click(screen.getByRole('button', { name: /הרצה על הנבחרים/ }))

    await screen.findByText('מלכי הכופרים')
    expect(screen.getByRole('button', { name: 'אישור הספר' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'תיקון פרטים' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'הסרה' })).toBeInTheDocument()
  })
})
