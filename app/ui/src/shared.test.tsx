/**
 * The rest of the shared surface: the status ladder, the date drift that was
 * settled, the async race guard, the hash primitive, and the language machinery.
 *
 * Each of these is here because BOTH apps depend on it. A test in one app's
 * ring would leave the other free to regress.
 */
import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useLayoutEffect, type ReactNode } from 'react'

import { createI18n } from './i18n'
import { formatDate, formatDateTime, formatNumber, libraryName } from './format'
import { backOr, navigateHash, useHash } from './hash'
import { StatusBadge, vouchedFor } from './StatusBadge'
import { ErrorBox, Loading } from './states'
import { useAsync } from './useAsync'
import { userEvent } from './testing/user'

const { I18nProvider, useI18n } = createI18n(
  { he: { hello: 'שלום' }, en: { hello: 'Hello' } },
  { storageKey: 'test.ui.lang' },
)

const wrap = ({ children }: { children: ReactNode }) => <I18nProvider>{children}</I18nProvider>

describe('the status ladder', () => {
  it('draws manual as manual — it OUTRANKS approved', () => {
    render(<StatusBadge status="manual" />, { wrapper: wrap })
    // The product shipped a badge that fired only on the literal `approved`
    // rung, so the one record a human had typed looked unconfirmed.
    expect(screen.getByText('ידני')).toBeInTheDocument()
  })

  it('counts everything off the auto rung as vouched for', () => {
    expect(vouchedFor('auto')).toBe(false)
    expect(vouchedFor('approved')).toBe(true)
    expect(vouchedFor('manual')).toBe(true)
  })

  it('shows an unknown status verbatim rather than as the rung below it', () => {
    render(<StatusBadge status="retracted" />, { wrapper: wrap })
    expect(screen.getByText('retracted')).toBeInTheDocument()
  })
})

describe('formatting', () => {
  it('returns an empty string for absent AND unparseable dates', () => {
    // ⚠ The settled half of a real drift: the product returned the raw ISO
    // string here, the console returned ''. One of them put a machine
    // timestamp in a reading surface.
    expect(formatDate(null, 'he')).toBe('')
    expect(formatDate(undefined, 'he')).toBe('')
    expect(formatDate('not-a-date', 'he')).toBe('')
    expect(formatDateTime('not-a-date', 'en')).toBe('')
  })

  it('formats a real date in both locales', () => {
    expect(formatDate('2026-08-10T09:00:00Z', 'en')).toMatch(/2026/)
    expect(formatNumber(1234, 'en')).toBe('1,234')
  })

  it('gives a blank library label a word, because v12 backfilled blanks', () => {
    expect(libraryName('   ', 'ללא שם')).toBe('ללא שם')
    expect(libraryName(null, 'ללא שם')).toBe('ללא שם')
    expect(libraryName('ספריית ההורים', 'ללא שם')).toBe('ספריית ההורים')
  })
})

describe('useAsync', () => {
  it('DROPS a response whose request has been superseded', async () => {
    // The load-bearing guard. Without it the slow first answer lands last and
    // repaints rows the user has already filtered away — or, across a library
    // switch, one tenant's books under another's name.
    let releaseSlow: (v: string) => void = () => {}
    const slow = new Promise<string>((resolve) => { releaseSlow = resolve })

    const { result, rerender } = renderHook(
      ({ key }: { key: string }) =>
        useAsync(() => (key === 'first' ? slow : Promise.resolve('second')), [key]),
      { initialProps: { key: 'first' } },
    )

    rerender({ key: 'second' })
    await waitFor(() => expect(result.current.data).toBe('second'))

    await act(async () => { releaseSlow('first'); await slow })
    expect(result.current.data).toBe('second')
  })

  it('reports an error and can be retried', async () => {
    let attempts = 0
    const { result } = renderHook(() =>
      useAsync(() => {
        attempts += 1
        return attempts === 1 ? Promise.reject(new Error('409 boom')) : Promise.resolve('ok')
      }, []),
    )

    await waitFor(() => expect(result.current.error).toBe('409 boom'))
    act(() => result.current.reload())
    await waitFor(() => expect(result.current.data).toBe('ok'))
  })

  it('does not report an abort as a failure', async () => {
    /**
     * ⚠⚠ This test took THREE goes, and the two failures are worth more than
     * the test.
     *
     * v1 called `unmount()` and then asserted — `result.current` is a frozen
     * pre-unmount snapshot no later `setState` can reach, so it passed with
     * the whole `catch` branch deleted. A review proved it.
     *
     * v2 superseded the request and asserted the error stayed clear. Also
     * green with the guard deleted — and THAT one is the interesting result,
     * because it says something true about the hook: **when the hook aborts a
     * request itself, the request-id guard has already returned.** Cleanup
     * aborts, the next effect increments `seq`, and by the time the rejection
     * reaches the handler `id !== seq.current`. The AbortError branch is
     * unreachable on that path.
     *
     * So the branch is for the abort the hook did NOT cause: a request that
     * rejects with `AbortError` while it is still the CURRENT one — a caller
     * that passes its own signal, a fetch timeout, a browser cancelling on
     * navigation. That is what this constructs, and what a deleted guard now
     * fails on. The two guards are redundant by design ("what else enforces
     * this?"), and each covers a case the other does not.
     */
    const { result } = renderHook(() =>
      useAsync(() => Promise.reject(new DOMException('aborted', 'AbortError')), []),
    )

    await act(async () => { await Promise.resolve() })

    // An abort is not a failure. Without the guard the console — where every
    // screen is a `useAsync` — swaps its table for an error box reading
    // literally "aborted".
    expect(result.current.error).toBeUndefined()
  })
})

describe('the hash primitive', () => {
  it('reads the hash that was current when it rendered', () => {
    globalThis.location.hash = '#/books'
    const { result } = renderHook(() => useHash())
    expect(result.current).toBe('#/books')
  })

  it('catches a hash set BETWEEN its render and its effect', () => {
    /**
     * ⚠ This is the case the mount read exists for, and the first version of
     * this test did not create it — it set the hash before rendering, which
     * the lazy `useState` initializer already picks up. It passed with the
     * mount read deleted. A review proved it, and it matters more than usual
     * because the mount read is NEW: neither app's previous router had it.
     *
     * The real race, constructed here with a sibling: effects run in tree
     * order, so a component mounted BEFORE the one holding this hook can
     * change the hash after the hook has rendered (its initializer already
     * read the old value) but before the hook's own effect attaches the
     * listener. The `hashchange` that fires has nobody listening, so without
     * the mount read the screen stays on the old route forever.
     */
    globalThis.location.hash = '#/library'

    function Redirects() {
      useLayoutEffect(() => { globalThis.location.hash = '#/capture' }, [])
      return null
    }
    function Reads() {
      return <span data-testid="hash">{useHash()}</span>
    }

    render(<><Redirects /><Reads /></>)

    expect(screen.getByTestId('hash')).toHaveTextContent('#/capture')
  })

  it('follows a navigation', async () => {
    const { result } = renderHook(() => useHash())
    await act(async () => { navigateHash('#/users') })
    await waitFor(() => expect(result.current).toBe('#/users'))
  })

  it('falls back when there is no history to go back to', () => {
    const back = vi.spyOn(globalThis.history, 'back').mockImplementation(() => {})
    vi.spyOn(globalThis.history, 'length', 'get').mockReturnValue(1)
    backOr('#/library')
    expect(back).not.toHaveBeenCalled()
    expect(globalThis.location.hash).toBe('#/library')
    vi.restoreAllMocks()
  })
})

describe('i18n', () => {
  function Probe() {
    const { t, ui, lang, dir, toggleLang } = useI18n()
    return (
      <button type="button" onClick={toggleLang}>
        {`${t.hello}|${ui.loading}|${lang}|${dir}`}
      </button>
    )
  }

  it('serves the app’s table and the shared one from one provider', () => {
    render(<Probe />, { wrapper: wrap })
    expect(screen.getByRole('button')).toHaveTextContent('שלום|טוען…|he|rtl')
  })

  it('mirrors the document and remembers the choice', async () => {
    render(<Probe />, { wrapper: wrap })
    await userEvent.click(screen.getByRole('button'))

    expect(screen.getByRole('button')).toHaveTextContent('Hello|Loading…|en|ltr')
    // The whole layout mirrors off these two attributes (UI_PLAN §7.1).
    expect(document.documentElement.dir).toBe('ltr')
    expect(document.documentElement.lang).toBe('en')
    expect(globalThis.localStorage.getItem('test.ui.lang')).toBe('en')
  })

  it('refuses to render a shared control outside a provider', () => {
    // A control that silently rendered without strings would ship blank
    // labels. Loud is the only honest option.
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Loading />)).toThrow(/I18nProvider/)
    quiet.mockRestore()
  })
})

describe('the shared states', () => {
  it('shows the server’s own sentence, and offers a retry only when one is given', async () => {
    const onRetry = vi.fn()
    const { rerender } = render(<ErrorBox message="לא ניתן למחוק ספרייה" onRetry={onRetry} />, {
      wrapper: wrap,
    })
    expect(screen.getByText('לא ניתן למחוק ספרייה')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'נסו שוב' }))
    expect(onRetry).toHaveBeenCalled()

    rerender(<I18nProvider><ErrorBox message="" /></I18nProvider>)
    expect(screen.getByText('אין חיבור לשרת')).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
  })
})
