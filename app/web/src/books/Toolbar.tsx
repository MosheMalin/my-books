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
import { useEffect, useState } from 'react'
import { exportUrl } from '../api/client'
import { useI18n } from '../lib/i18n'
import type { SortKey } from '../lib/books'
import type { View } from './Feed'

/** Long enough that a Hebrew word is finished, short enough to feel live. */
const SEARCH_DEBOUNCE_MS = 200

export interface ToolbarProps {
  q: string
  sort: SortKey
  sortApplies: boolean
  view: View
  onSearch: (q: string) => void
  onSort: (sort: SortKey) => void
  onView: (view: View) => void
  onAdd: () => void
}

export function Toolbar({
  q,
  sort,
  sortApplies,
  view,
  onSearch,
  onSort,
  onView,
  onAdd,
}: ToolbarProps) {
  const { t } = useI18n()
  // The input is uncontrolled-by-the-store on purpose: typing must never wait
  // for a round trip. `draft` is the keystrokes, `q` is what the server knows.
  const [draft, setDraft] = useState(q)

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

      <label className="sortwrap">
        <span className="visually-hidden">{t.sort}</span>
        <select
          value={sortApplies ? sort : 'relevance'}
          disabled={!sortApplies}
          // Ignored by the server while searching — relevance IS the order —
          // so the control says so rather than pretending it still applies.
          title={sortApplies ? t.sort : t.sort_ignored}
          onChange={(e) => onSort(e.target.value as SortKey)}
        >
          {!sortApplies && <option value="relevance">{t.sort_relevance}</option>}
          <option value="title">{t.sort_title}</option>
          <option value="author">{t.sort_author}</option>
          <option value="recently_added">{t.sort_recent}</option>
        </select>
      </label>

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
