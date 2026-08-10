/**
 * The sticky toolbar: search, sort, list/grid, add, export.
 *
 * Search is SERVER-side now. The mock carried its own miniature `normalize()`
 * and filtered an in-memory array; here `?q=` reaches a matcher that strips
 * nikud, folds final letters, deletes in-word geresh, tolerates a leading
 * ה/ו/ב/ל/מ/ש/כ and ranks by relevance — measured P@1 1.00 on 24 real queries
 * (fixtures/search/README.md). Re-implementing any of that here would mean two
 * normalizers, and two normalizers drift.
 */
import { useEffect, useMemo, useState } from 'react'
import { SortControl, type SortOption } from '@booksnap/ui'
import { exportUrl } from '../api/client'
import { useI18n } from '../lib/i18n'
import { naturalAscending, type SortKey } from '../lib/books'
import type { View } from './Feed'

/** Long enough that a Hebrew word is finished, short enough to feel live. */
const SEARCH_DEBOUNCE_MS = 200

export interface ToolbarProps {
  q: string
  sort: SortKey
  ascending: boolean
  sortApplies: boolean
  view: View
  onSearch: (q: string) => void
  onSort: (sort: SortKey) => void
  onAscending: (ascending: boolean) => void
  onView: (view: View) => void
  onAdd: () => void
}

export function Toolbar({
  q,
  sort,
  ascending,
  sortApplies,
  view,
  onSearch,
  onSort,
  onAscending,
  onView,
  onAdd,
}: ToolbarProps) {
  const { t } = useI18n()
  // The input is uncontrolled-by-the-store on purpose: typing must never wait
  // for a round trip. `draft` is the keystrokes, `q` is what the server knows.
  const [draft, setDraft] = useState(q)

  // Each option carries the direction its key MEANS — A–Z for text, newest
  // first for a date — from the store's own rule, so there is one definition
  // of it rather than a second list of exceptions here.
  const options = useMemo<readonly SortOption[]>(
    () =>
      ([
        ['title', t.sort_title],
        ['author', t.sort_author],
        ['recently_added', t.sort_recent],
      ] as const).map(([value, label]) => ({
        value,
        label,
        naturalAscending: naturalAscending(value),
      })),
    [t],
  )

  useEffect(() => setDraft(q), [q])

  useEffect(() => {
    if (draft === q) return
    const timer = setTimeout(() => onSearch(draft), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [draft, q, onSearch])

  return (
    <div className="toolbar">
      <div className="searchwrap">
        <span className="mag" aria-hidden="true">⌕</span>
        <input
          type="search"
          value={draft}
          placeholder={t.search}
          aria-label={t.search}
          className="rtl-safe"
          onChange={(e) => setDraft(e.target.value)}
        />
      </div>

      {/* The control itself is `@booksnap/ui`'s now — the console had
          re-invented it as a bare select with a ↑/↓ button beside it, and lost
          both of the rules that make this one work (the direction INSIDE the
          box, and the reset on a key change). What stays here is what only
          this app knows: which keys it can sort by, and why the control goes
          inert while a search is running. */}
      <SortControl
        value={sort}
        ascending={ascending}
        options={options}
        label={t.sort}
        disabled={!sortApplies}
        // Ignored by the server while searching — relevance IS the order — so
        // the control says so rather than pretending it still applies.
        disabledReason={t.sort_ignored}
        inertOption={{ value: 'relevance', label: t.sort_relevance }}
        // ⚠ `else`, not a second call — and the reason is NOT "it would fire a
        // second query". It would not: `setQuery` short-circuits when the
        // values match, and React batches both updates in one handler. (The
        // first version of this comment said that, and a review corrected it;
        // the correction matters because a wrong reason is what makes the next
        // reader delete the guard.)
        //
        // The real reason is the INERT case. While a search is running the
        // control is disabled and shows `relevance`, so `value` here is still
        // the last real key: calling `onAscending` unconditionally would push
        // a direction for an ordering the server is ignoring. The books store
        // already resets direction on a key change (`setQuery`'s own
        // `naturalAscending`, which other paths change sort through too), so
        // letting it be the one that applies the reset is redundant
        // enforcement on purpose — "what else enforces this?", answered.
        onChange={(value, asc) => {
          if (value !== sort) onSort(value as SortKey)
          else onAscending(asc)
        }}
      />

      <div className="seg" role="group" aria-label={`${t.view_list} / ${t.view_grid}`}>
        <button
          type="button"
          className={view === 'list' ? 'on' : ''}
          aria-pressed={view === 'list'}
          onClick={() => onView('list')}
        >
          {t.view_list}
        </button>
        <button
          type="button"
          className={view === 'grid' ? 'on' : ''}
          aria-pressed={view === 'grid'}
          onClick={() => onView('grid')}
        >
          {t.view_grid}
        </button>
      </div>

      <span className="spacer" />

      {/* Plain links, not fetches: letting the browser handle
          Content-Disposition is what makes "Save as…" work. */}
      <a className="btn ghost" href={exportUrl('csv')} download>
        {t.export_csv}
      </a>
      <a className="btn ghost" href={exportUrl('json')} download>
        {t.export_json}
      </a>

      <button type="button" className="btn primary" onClick={onAdd}>
        {t.add_book}
      </button>
    </div>
  )
}
