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
import { userEvent } from '../test/user'
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

  it('refuses to start a second read while one is running', async () => {
    // Owner, live use. Pressing Run again starts another read of the same
    // (shelf, depth) — legal server-side, and a waste of money and minutes
    // that also replaces the panel you were watching.
    const server = fakeCaptureServer()
    server.nextReadStatus = 'running'
    const { container } = renderCapture()
    await dropOnePhoto(container)
    await screen.findByText('לא משויך')

    const run = screen.getByRole('button', { name: /הרצה על הנבחרים/ })
    await userEvent.click(run)

    await waitFor(() => expect(run).toBeDisabled())
    expect(screen.getByText('קריאה כבר רצה')).toBeInTheDocument()
    const started = server.calls.filter(
      (c) => c.includes('/reads') && !c.includes('/reads/')).length
    await userEvent.click(run)
    expect(server.calls.filter(
      (c) => c.includes('/reads') && !c.includes('/reads/')).length).toBe(started)
  })

  it('says what a running read is DOING, not just that it is reading', async () => {
    // The engine has reported per-tile progress all along (`llmreader.py`,
    // `pipeline.py`); the panel threw it away and showed one static line for
    // minutes, which is indistinguishable from a hung job.
    const server = fakeCaptureServer()
    server.nextReadStatus = 'running'
    server.nextProgress = { stage: 'reading', done: 3, total: 12 }
    const { container } = renderCapture()
    await dropOnePhoto(container)
    await screen.findByText('לא משויך')
    await userEvent.click(screen.getByRole('button', { name: /הרצה על הנבחרים/ }))

    expect(await screen.findByText('קורא את התמונה… 3/12')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '25')
  })

  it('falls back to the plain line for a stage it has never heard of', async () => {
    // The engine may grow a stage this client does not know. A new event must
    // read as LESS detail, never as a broken screen or a raw key.
    const server = fakeCaptureServer()
    server.nextReadStatus = 'running'
    server.nextProgress = { stage: 'quantum_reticulation', done: 1 }
    const { container } = renderCapture()
    await dropOnePhoto(container)
    await screen.findByText('לא משויך')
    await userEvent.click(screen.getByRole('button', { name: /הרצה על הנבחרים/ }))

    expect(await screen.findByText('קורא…')).toBeInTheDocument()
    expect(screen.queryByText(/quantum/)).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
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
      id: 'rd1', shelf_id: 'sh1', depth: 1, status: 'done', claim_count: 3,
      finished_at: '2026-08-09T10:00:00Z',
      // An archived summary that DISAGREES with the live state on purpose:
      // it says one finding is awaiting approval, and the run row must not
      // repeat that as if it were current (owner, 2026-08-09).
      diff_summary: { added: 2, corrected: 0, unchanged: 1, needs_decision: 1,
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

  it('never sweeps a duplicate question into a bulk approval', async () => {
    // The POC's own hard-won rule. A duplicate question is a DIFFERENT
    // question — "which copy is this?" — and answering it by bulk-approving
    // would invent a second copy of a book that never moved.
    const server = processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      needs_decision: [
        outcome({ kind: 'needs_decision', reason: 'new_book_unconfirmed',
                  claim: claim({ id: 'c1', capture_id: 'cap1', title: 'A',
                                 tier: 'auto' }) }),
        outcome({ kind: 'needs_decision', reason: 'ambiguous_location',
                  existing_book: fakeBook('bk9'),
                  claim: claim({ id: 'c3', capture_id: 'cap1', title: 'C',
                                 tier: 'auto' }) }),
      ],
    })
    await openWorkspace()

    await userEvent.click(await screen.findByRole(
      'button', { name: '\u05d0\u05d9\u05e9\u05d5\u05e8 \u05db\u05dc \u05d4\u05d6\u05d9\u05d4\u05d5\u05d9\u05d9\u05dd \u05d4\u05d0\u05d5\u05d8\u05d5\u05de\u05d8\u05d9\u05d9\u05dd (1)' }))

    await waitFor(() => {
      const body = server.bodies.find(
        (b) => (b as { answers?: { claim_id: string }[] }).answers?.length)
      const answers = (body as { answers: { claim_id: string }[] }).answers
      expect(answers.map((a) => a.claim_id)).toEqual(['c1'])
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

  it('warns that this read already found a book you are typing in by hand', async () => {
    // `booksnap/server.py:lookup`'s own error: adding by hand a book the run
    // DID find and the eye skipped. Shown, never enforced.
    const server = processedPhoto(settled())
    server.lookupFor = () => [{ claim_id: 'c1', title: 'מלכי הכופרים',
                                author: 'פול קארני', tier: 'auto' }]
    await openWorkspace()
    await screen.findByText('מלכי הכופרים')

    await userEvent.click(screen.getByRole('button', { name: '+ הוספת ספר שהמנוע פספס' }))
    await userEvent.type(screen.getByLabelText('כותרת'), 'מלכי')

    expect(await screen.findByText('הקריאה הזו כבר מצאה:', {}, { timeout: 2000 }))
      .toBeInTheDocument()
    // The MATCHING is the server's (P1.5's Hebrew rules) — the client only
    // asks. Anything else would be the second, subtly different
    // implementation the engine refused to grow.
    await waitFor(() =>
      expect(server.calls.some((c) => c.includes('/findings/lookup?q='))).toBe(true))
    // ...and it never blocks: the add button stays live.
    expect(screen.getByRole('button', { name: 'הוספה' })).toBeEnabled()
  })

  it('bulk-approves every unvouched-for finding, pending or already landed', async () => {
    // What the owner went looking for and did not find: his photo's rows were
    // books already in the library but still on the `auto` rung, each with
    // its own Approve — the POC's "approve all auto" covered exactly those.
    const server = processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      unchanged: [
        outcome({ kind: 'unchanged', reason: 'same_location', book_key: 'k1',
                  existing_book: fakeBook('bk1', { status: 'auto' }),
                  claim: claim({ id: 'c1', capture_id: 'cap1', title: 'A' }) }),
        outcome({ kind: 'unchanged', reason: 'same_location', book_key: 'k2',
                  existing_book: fakeBook('bk2', { status: 'approved' }),
                  claim: claim({ id: 'c2', capture_id: 'cap1', title: 'B' }) }),
      ],
      needs_decision: [
        outcome({ kind: 'needs_decision', reason: 'new_book_unconfirmed',
                  claim: claim({ id: 'c3', capture_id: 'cap1', title: 'C',
                                 tier: 'auto' }) }),
        // A REVIEW-tier guess is NOT swept up — the POC's rule, and a bulk
        // click is not where you accept the engine's low-confidence reads.
        outcome({ kind: 'needs_decision', reason: 'new_book_unconfirmed',
                  claim: claim({ id: 'c4', capture_id: 'cap1', title: 'D',
                                 tier: 'review' }) }),
      ],
    })
    await openWorkspace()

    // 1 auto-rung book + 1 pending AUTO finding. Not the approved book, not
    // the review-tier guess.
    const bulk = await screen.findByRole(
      'button', { name: '\u05d0\u05d9\u05e9\u05d5\u05e8 \u05db\u05dc \u05d4\u05d6\u05d9\u05d4\u05d5\u05d9\u05d9\u05dd \u05d4\u05d0\u05d5\u05d8\u05d5\u05de\u05d8\u05d9\u05d9\u05dd (2)' })
    await userEvent.click(bulk)

    await waitFor(() => {
      expect(server.calls.some((c) => c.includes('/books/bk1/approve'))).toBe(true)
      const body = server.bodies.find(
        (b) => (b as { answers?: { claim_id: string }[] }).answers?.length)
      const answers = (body as { answers: { claim_id: string }[] }).answers
      expect(answers.map((a) => a.claim_id)).toEqual(['c3'])
    })
    expect(server.calls.some((c) => c.includes('/books/bk2/approve'))).toBe(false)
  })

  it('marks a hand-typed book as vouched for, not as something nobody confirmed', async () => {
    processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      unchanged: [outcome({
        kind: 'unchanged', reason: 'same_location', book_key: 'k1',
        existing_book: fakeBook('bk1', { title: '\u05d4\u05d5\u05e7\u05dc\u05d3', status: 'manual' }),
        claim: claim({ id: 'c1', capture_id: 'cap1', title: '\u05d4\u05d5\u05e7\u05dc\u05d3',
                       tier: 'manual' }),
      })],
    })
    await openWorkspace()

    const row = (await screen.findByText('\u05d4\u05d5\u05e7\u05dc\u05d3')).closest('.rrow') as HTMLElement
    // `manual` is STRONGER than approved (the ladder), so the badge that says
    // "a human vouched for this" has to fire for it too.
    expect(within(row).getByText('\u05d0\u05d5\u05e9\u05e8')).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: '\u05d0\u05d9\u05e9\u05d5\u05e8 \u05d4\u05e1\u05e4\u05e8' }))
      .not.toBeInTheDocument()
  })

  it('splits one finding into volumes, named in the chosen style', async () => {
    const server = processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      needs_decision: [outcome({
        kind: 'needs_decision', reason: 'new_book_unconfirmed', book_key: 'k1',
        claim: claim({ id: 'c1', capture_id: 'cap1', title: '\u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea',
                       author: '\u05d8\u05d5\u05dc\u05e7\u05d9\u05df', tier: 'auto' }),
      })],
    })
    await openWorkspace()
    await screen.findByText('\u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea')

    await userEvent.click(screen.getByRole('button', { name: '\u05e4\u05d9\u05e6\u05d5\u05dc' }))
    await userEvent.selectOptions(screen.getByLabelText('\u05db\u05de\u05d4 \u05db\u05e8\u05db\u05d9\u05dd'), '3')
    // The preview is the control's justification: the mark is a choice about
    // what is printed on the owner's own books.
    expect(screen.getByText(
      '\u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea \u05d0 \u00b7 \u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea \u05d1 \u00b7 \u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea \u05d2')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('\u05e1\u05d9\u05de\u05d5\u05df'), 'roman')
    expect(screen.getByText(
      '\u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea I \u00b7 \u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea II \u00b7 \u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea III')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '\u05e6\u05e8\u05d5 \u05db\u05e8\u05db\u05d9\u05dd' }))

    await waitFor(() => {
      // Part 1 answers the finding itself (confirm-as-corrected); parts 2..N
      // are hand-added findings on the same read.
      const confirm = server.bodies.find(
        (b) => (b as { answers?: { title?: string }[] }).answers?.[0]?.title)
      expect((confirm as { answers: { title: string }[] }).answers[0]!.title)
        .toBe('\u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea I')
      const added = server.bodies.filter(
        (b) => 'title' in (b ?? {}) && !('answers' in (b ?? {})))
      expect(added.map((b) => (b as { title: string }).title))
        .toEqual(['\u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea II', '\u05e9\u05e8 \u05d4\u05d8\u05d1\u05e2\u05d5\u05ea III'])
      // The author rides along — the volumes are by the same person.
      expect((added[0] as { author: string }).author).toBe('\u05d8\u05d5\u05dc\u05e7\u05d9\u05df')
    }, { timeout: 3000 })
  })

  it('completes the author against the library instead of retyping it', async () => {
    const server = processedPhoto(settled())
    server.authorsFor = () => ['\u05d3\u05d5\u05d3 \u05d2\u05e8\u05d5\u05e1\u05de\u05df']
    await openWorkspace()
    await screen.findByText('\u05de\u05dc\u05db\u05d9 \u05d4\u05db\u05d5\u05e4\u05e8\u05d9\u05dd')

    await userEvent.click(screen.getByRole(
      'button', { name: '+ \u05d4\u05d5\u05e1\u05e4\u05ea \u05e1\u05e4\u05e8 \u05e9\u05d4\u05de\u05e0\u05d5\u05e2 \u05e4\u05e1\u05e4\u05e1' }))
    await userEvent.type(screen.getByLabelText('\u05de\u05d7\u05d1\u05e8'), '\u05d2\u05e8\u05d5\u05e1')

    const hint = await screen.findByRole(
      'button', { name: '\u05d3\u05d5\u05d3 \u05d2\u05e8\u05d5\u05e1\u05de\u05df' }, { timeout: 2000 })
    await userEvent.click(hint)
    expect(screen.getByLabelText('\u05de\u05d7\u05d1\u05e8')).toHaveValue('\u05d3\u05d5\u05d3 \u05d2\u05e8\u05d5\u05e1\u05de\u05df')
  })

  it('lists a split volume directly under the part it came from', async () => {
    // Not at the bottom of the photo, which is where the bucket order alone
    // would put it (owner, 2026-08-09).
    processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      unchanged: [
        outcome({ kind: 'unchanged', reason: 'same_location', book_key: 'k1',
                  existing_book: fakeBook('bk1', { title: 'First' }),
                  claim: claim({ id: 'c1', capture_id: 'cap1', title: 'First',
                                 spine_id: 'sp1' }) }),
        outcome({ kind: 'unchanged', reason: 'same_location', book_key: 'k2',
                  existing_book: fakeBook('bk2', { title: 'Second' }),
                  claim: claim({ id: 'c2', capture_id: 'cap1', title: 'Second',
                                 spine_id: 'sp2' }) }),
        // Two parts of sp1, arriving last and out of order — ~m10 must not
        // sort before ~m2 either.
        outcome({ kind: 'unchanged', reason: 'same_location', book_key: 'k3',
                  existing_book: fakeBook('bk3', { title: 'PartTen' }),
                  claim: claim({ id: 'c3', capture_id: 'cap1', title: 'PartTen',
                                 spine_id: 'sp1~m10' }) }),
        outcome({ kind: 'unchanged', reason: 'same_location', book_key: 'k4',
                  existing_book: fakeBook('bk4', { title: 'PartTwo' }),
                  claim: claim({ id: 'c4', capture_id: 'cap1', title: 'PartTwo',
                                 spine_id: 'sp1~m2' }) }),
      ],
    })
    await openWorkspace()
    await screen.findByText('First')

    const titles = [...document.querySelectorAll('.workspace .rrow .t')]
      .map((e) => e.textContent)
    expect(titles).toEqual(['First', 'PartTwo', 'PartTen', 'Second'])
  })

  it('closes the author suggestions once one is taken', async () => {
    const server = processedPhoto(settled())
    // The server keeps answering with a near-miss even after the exact name
    // is in the field — filtering the exact match alone would leave it.
    server.authorsFor = () => ['\u05d3\u05d5\u05d3 \u05d2\u05e8\u05d5\u05e1\u05de\u05df', '\u05d3\u05d5\u05d9\u05d3 \u05d2\u05e8\u05d5\u05e1\u05de\u05df']
    await openWorkspace()
    await screen.findByText('\u05de\u05dc\u05db\u05d9 \u05d4\u05db\u05d5\u05e4\u05e8\u05d9\u05dd')

    await userEvent.click(screen.getByRole(
      'button', { name: '+ \u05d4\u05d5\u05e1\u05e4\u05ea \u05e1\u05e4\u05e8 \u05e9\u05d4\u05de\u05e0\u05d5\u05e2 \u05e4\u05e1\u05e4\u05e1' }))
    await userEvent.type(screen.getByLabelText('\u05de\u05d7\u05d1\u05e8'), '\u05d2\u05e8\u05d5\u05e1')
    await userEvent.click(await screen.findByRole(
      'button', { name: '\u05d3\u05d5\u05d3 \u05d2\u05e8\u05d5\u05e1\u05de\u05df' }, { timeout: 2000 }))

    expect(screen.getByLabelText('\u05de\u05d7\u05d1\u05e8')).toHaveValue('\u05d3\u05d5\u05d3 \u05d2\u05e8\u05d5\u05e1\u05de\u05df')
    // No leftovers, not even the other name that still matches.
    //
    // Waited THROUGH the debounce, not polled: `waitFor` passes on its first
    // tick — the list is empty the instant the chip is clicked — so it would
    // go green against a version that re-opens the suggestions 250ms later,
    // which is exactly the bug. Found by mutation testing.
    await new Promise((r) => { setTimeout(r, 700) })
    expect(screen.queryByRole('button', { name: '\u05d3\u05d5\u05d9\u05d3 \u05d2\u05e8\u05d5\u05e1\u05de\u05df' }))
      .not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '\u05d3\u05d5\u05d3 \u05d2\u05e8\u05d5\u05e1\u05de\u05df' }))
      .not.toBeInTheDocument()
  })

  it('offers Split as a link beside "try a better match", not as a button', async () => {
    processedPhoto(settled())
    await openWorkspace()
    const row = (await screen.findByText('\u05de\u05dc\u05db\u05d9 \u05d4\u05db\u05d5\u05e4\u05e8\u05d9\u05dd'))
      .closest('.rrow') as HTMLElement

    const split = within(row).getByRole('button', { name: '\u05e4\u05d9\u05e6\u05d5\u05dc' })
    // A link, like the panel-opening control next to it — the three coloured
    // buttons COMMIT something, and this only opens a panel.
    expect(split).toHaveClass('linkish')
    expect(split.closest('.acts')).toBeNull()
    // One word on screen; the rest in the tooltip.
    expect(split).toHaveAttribute('title', '\u05e4\u05d9\u05e6\u05d5\u05dc \u05dc\u05db\u05e8\u05db\u05d9\u05dd')
  })

  it('counts removals in the findings summary', async () => {
    // The owner's report: remove a book and the summary still said "1
    // awaiting approval" and mentioned the removal nowhere.
    processedPhoto({
      ...emptyDiff('sh1', 1, 'rd1'),
      rejected: [outcome({
        kind: 'rejected', reason: 'rejected', book_key: 'k1',
        claim: claim({ id: 'c1', capture_id: 'cap1', title: 'הוסר' }),
      })],
    })
    await openWorkspace()

    expect(await screen.findByText(/1 הוסרו/)).toBeInTheDocument()
    expect(screen.queryByText(/ממתינים לאישור/)).not.toBeInTheDocument()
  })

  it('shows a run by how many findings it has, never by a count that can go stale', async () => {
    // The run row used to render P2.8's archived snapshot, which cannot know
    // about a removal made after it was taken — so it kept claiming "1
    // awaiting approval" for a finding that was gone.
    processedPhoto(settled())
    await openWorkspace()

    const runRow = document.querySelector('.runrow') as HTMLElement
    expect(within(runRow).getByText(/ממצאים/)).toBeInTheDocument()
    expect(within(runRow).queryByText(/ממתינים לאישור/)).not.toBeInTheDocument()
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
