/**
 * The control the owner asked to be shared, and the two rules that make it
 * worth sharing. Both were reversed and watched to fail before being written
 * down here.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import { createI18n } from './i18n'
import { SortControl, type SortOption } from './SortControl'
import { userEvent } from './testing/user'

const { I18nProvider } = createI18n(
  { he: { sort: 'מיון' }, en: { sort: 'Sort' } },
  { storageKey: 'test.lang' },
)

const OPTIONS: readonly SortOption[] = [
  { value: 'title', label: 'כותרת' },
  { value: 'author', label: 'מחבר' },
  // A date key's natural direction is newest-first. Declared beside the label,
  // which is the whole point of putting it on the option.
  { value: 'recently_added', label: 'נוספו לאחרונה', naturalAscending: false },
]

const wrap = (node: ReactNode) => render(<I18nProvider>{node}</I18nProvider>)

describe('SortControl', () => {
  it('resets the direction to the new key’s natural one', async () => {
    const onChange = vi.fn()
    wrap(
      <SortControl value="title" ascending options={OPTIONS} onChange={onChange} label="מיון" />,
    )

    await userEvent.selectOptions(screen.getByRole('combobox'), 'recently_added')

    // ⚠ Not just `('recently_added', anything)`. Carrying the old ascending
    // over is the bug — "recently added, oldest first" is an ordering nobody
    // chooses — and an assertion on the key alone passes with it intact.
    expect(onChange).toHaveBeenCalledWith('recently_added', false)
  })

  it('keeps ascending for a text key', async () => {
    const onChange = vi.fn()
    wrap(
      <SortControl
        value="recently_added"
        ascending={false}
        options={OPTIONS}
        onChange={onChange}
        label="מיון"
      />,
    )

    await userEvent.selectOptions(screen.getByRole('combobox'), 'author')

    expect(onChange).toHaveBeenCalledWith('author', true)
  })

  it('toggles the direction without changing the key', async () => {
    const onChange = vi.fn()
    wrap(
      <SortControl value="title" ascending options={OPTIONS} onChange={onChange} label="מיון" />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'סדר עולה' }))

    expect(onChange).toHaveBeenCalledWith('title', false)
  })

  it('names the direction it would switch FROM, in the active language', () => {
    wrap(
      <SortControl
        value="title"
        ascending={false}
        options={OPTIONS}
        onChange={vi.fn()}
        label="מיון"
      />,
    )

    expect(screen.getByRole('button', { name: 'סדר יורד' })).toBeInTheDocument()
  })

  it('goes inert with its REASON on the control, not merely greyed', async () => {
    const onChange = vi.fn()
    wrap(
      <SortControl
        value="title"
        ascending
        options={OPTIONS}
        onChange={onChange}
        label="מיון"
        disabled
        disabledReason="בחיפוש התוצאות מסודרות לפי רלוונטיות"
        inertOption={{ value: 'relevance', label: 'רלוונטיות' }}
      />,
    )

    const select = screen.getByRole('combobox')
    expect(select).toBeDisabled()
    // The box says what the ordering ACTUALLY is, rather than a key the
    // server is ignoring.
    expect(select).toHaveValue('relevance')
    expect(select).toHaveAttribute('title', 'בחיפוש התוצאות מסודרות לפי רלוונטיות')

    const direction = screen.getByRole('button')
    expect(direction).toBeDisabled()
    expect(direction).toHaveAttribute('title', 'בחיפוש התוצאות מסודרות לפי רלוונטיות')

    await userEvent.click(direction)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('draws the direction INSIDE the box, at its inline-start edge', () => {
    const { container } = wrap(
      <SortControl value="title" ascending options={OPTIONS} onChange={vi.fn()} label="מיון" />,
    )

    // Structural, because jsdom computes no cascade: the button must be a
    // child of the same wrapper the select is in, or the CSS that overlays it
    // (`.sortdir { position: absolute; inset-inline-start }`) has nothing to
    // position against and the two read as two separate controls.
    const wrapper = container.querySelector('.sortwrap')
    expect(wrapper?.querySelector('button.sortdir')).toBeTruthy()
    expect(wrapper?.querySelector('select')).toBeTruthy()
  })
})
