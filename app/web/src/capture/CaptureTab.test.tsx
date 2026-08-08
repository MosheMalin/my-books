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
import { claim, emptyDiff, fakeCaptureServer, outcome } from './captureHarness'

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

  it('offers "add a row behind" even on a single-row shelf (§5.7)', async () => {
    fakeCaptureServer()
    const { container } = renderCapture()
    await dropOnePhoto(container)
    await screen.findByText('לא משויך')

    // Depth_count is 1 here — the affordance must still be on screen, not
    // gated behind the shelf already being stacked.
    const addRow = screen.getByText('+ הוספת שורה מאחור')
    expect(addRow).toBeInTheDocument()

    await userEvent.click(addRow)
    // Growing the shelf to 2 rows surfaces the depth picker the mock only
    // shows once a shelf IS stacked.
    await waitFor(() => expect(screen.getByText('שורה 1')).toBeInTheDocument())
    expect(screen.getByText('שורה 2')).toBeInTheDocument()
  })

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

  it('confirming a REVIEW-tier new-book claim clears it from needs_decision', async () => {
    const server = fakeCaptureServer()
    const c1 = claim({ id: 'c1', title: 'ספר חדש', tier: 'review', score: 62 })
    let answered = false
    server.diffFor = (_readId, answers) => {
      if (answers.some((a) => a.claim_id === 'c1' && a.kind === 'confirm')) answered = true
      return answered
        ? { ...emptyDiff('sh1', 1, 'rd1'),
            added: [outcome({ kind: 'added', reason: 'new_book_auto', claim: c1 })] }
        : { ...emptyDiff('sh1', 1, 'rd1'),
            needs_decision: [outcome({
              kind: 'needs_decision', reason: 'review_tier_new_book', claim: c1,
            })] }
    }
    await startRun()
    await screen.findByText('ספר חדש')
    expect(screen.getByText('טעון אישור')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '✓' }))

    await waitFor(() => expect(screen.getByText('חדש')).toBeInTheDocument())
    expect(screen.queryByText('טעון אישור')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '✓' })).not.toBeInTheDocument()
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

  it('why? reveals ranked alternatives with their rejection reason, and none are one-click acceptable', async () => {
    const server = fakeCaptureServer()
    const diff = {
      ...emptyDiff('sh1', 1, 'rd1'),
      added: [outcome({
        kind: 'added', reason: 'new_book_auto',
        claim: claim({
          id: 'c1', title: 'מלכי הכופרים', tier: 'auto', score: 91,
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

    await userEvent.click(screen.getByRole('button', { name: 'למה?' }))

    expect(await screen.findByText('ספינות מן המערב')).toBeInTheDocument()
    expect(screen.getByText('title similarity 40 < 47')).toBeInTheDocument()
    // "alternatives" is display-only (UI_PLAN's "one-click acceptable" was
    // deliberately left out — no domain op exists to re-point a claim at a
    // different candidate) — so a runner-up's own row carries no button.
    const altRow = screen.getByText('ספינות מן המערב').closest('tr')!
    expect(within(altRow).queryByRole('button')).not.toBeInTheDocument()
  })

  it('the "open the shelf" chip navigates to the shelf-detail route (P2.8)', async () => {
    const server = fakeCaptureServer()
    server.diffFor = (readId) => emptyDiff('sh1', 1, readId)
    globalThis.location.hash = ''
    await startRun()

    const shelfId = server.shelves[0]!.id
    await userEvent.click(screen.getByRole('button', { name: 'פתחו את המדף →' }))

    expect(globalThis.location.hash).toBe(`#/map/${shelfId}`)
    globalThis.location.hash = ''
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
