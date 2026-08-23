import { useI18n } from '../../lib/i18n'
import { mapText } from '../text'
/**
 * The bookcase, front-on — the SECOND geometry (MAP_PLAN §3.2).
 *
 * Sections stacked as they are built, each divided into columns across and
 * levels down, one cell per shelf. A case built of a low base with a taller
 * unit standing on it is two sections — one piece of furniture on the plan,
 * two grids here (owner, 2026-08-16).
 *
 * ⚠ Sections are stored BOTTOM-FIRST and drawn TOP-FIRST, because furniture
 * stacks upwards and a screen draws downwards. `sectionsTopDown` is the only
 * place that reversal happens.
 *
 * Pinned LTR like the plan and for the same reason: a piece of furniture must
 * not mirror when the UI language changes. *Which physical end column 1 is*
 * stays open — `UI_PLAN` §8 and MAP_PLAN §7 Q3 — so the header says "col 1"
 * and claims nothing more.
 */

import type { Bookcase, Section } from '../core/model'
import { MAX_DEPTH, columnCount, isGap, sectionsTopDown, shelfAt, shelvesDifferingFromDefaultDepth, shelvesInColumns } from '../core/model'
import { nothingBound } from '../cost'
import { whyNotGap } from '../limits'
import type { Selection } from './types'

type Props = {
  bc: Bookcase
  selection: Selection
  onSelectShelf: (sectionId: string, col: number, level: number, add: boolean) => void
  /** Switch the marked cells off, or a single hole back on (MAP_PLAN §3.10a). */
  onGaps: (sectionId: string, cells: { col: number; level: number }[], gap: boolean) => void
  onColumnLevels: (sectionId: string, col: number, levels: number) => void
  onColumnCount: (sectionId: string, count: number) => void
  onDefaultLevels: (sectionId: string, n: number) => void
  onDefaultDepth: (sectionId: string, n: number) => void
  onApplyDefaultLevels: (sectionId: string) => void
  onApplyDefaultDepth: (sectionId: string) => void
  onAddSection: (where: 'top' | 'bottom') => void
  onRemoveSection: (sectionId: string) => void
}

export function Elevation(props: Props) {
  const T = mapText(useI18n().lang)
  const { bc } = props
  const many = bc.sections.length > 1
  return (
    <div className="elevation" dir="ltr">
      {many && (
        <button
          type="button"
          className="section-add"
          onClick={() => props.onAddSection('top')}
          aria-label={T.add_section_top}
        >
          {T.add_section_top_long}
        </button>
      )}

      {sectionsTopDown(bc).map((sec) => (
        <SectionBlock key={sec.id} {...props} sec={sec} many={many} />
      ))}

      <button
        type="button"
        className="section-add"
        onClick={() => props.onAddSection(many ? 'bottom' : 'top')}
        aria-label={many ? T.add_section_under : T.split_sections}
      >
        {many ? T.add_section_under_long : T.split_sections_long}
      </button>
    </div>
  )
}

function SectionBlock({
  bc,
  sec,
  many,
  selection,
  ...props
}: Props & { sec: Section; many: boolean }) {
  const T = mapText(useI18n().lang)
  const cols = columnCount(sec)
  // The cells marked in THIS section. A set, since P6.3.2b: a television is
  // a rectangle of cells and the owner marks them before pressing delete.
  const marked = selection.cells.filter(
    (c) => c.caseId === bc.id && c.sectionId === sec.id)
  const blocked = marked.length > 0 ? whyNotGap(sec, marked) : null
  const index = bc.sections.findIndex((s) => s.id === sec.id)
  // Numbered BOTTOM-UP, because that is how the thing was built: section 1
  // stands on the floor.
  const label = T.section_n(index + 1)
  const where =
    index === 0 ? T.section_on_floor : index === bc.sections.length - 1 ? T.section_on_top : ''
  // Accessible names print the section only when there IS more than one — the
  // same "only what discriminates" rule the shelf address follows. Uniqueness
  // is not at risk: with one section there is nothing to collide with.
  const addr = many ? `${label}, ` : ''
  const differing = shelvesDifferingFromDefaultDepth(sec)

  return (
    <section className="elev-section">
      {many && (
        <header className="section-head">
          <span className="section-name">
            {label}
            <span className="section-where">{where}</span>
          </span>
          <button
            type="button"
            className="danger"
            aria-label={T.remove_section(label)}
            title={T.remove_section_title(label, sec.shelves.length)}
            onClick={() => {
              // ⚠ Asked only when something stands here. Every slot of an
              // untouched section holds nothing, and a dialog in front of a
              // gesture that destroys nothing is what teaches people to click
              // through the ones that do (owner, drawing with it).
              if (nothingBound(sec.shelves)
                  || confirm(T.remove_section_confirm(label, sec.shelves.length))) {
                props.onRemoveSection(sec.id)
              }
            }}
          >
            ✕
          </button>
        </header>
      )}

      {/* ABSENT until cells are marked, not disabled — the house rule. It is
          the only destructive control in the elevation that acts on a set, so
          it says how many, and it never mentions the bookcase: deleting cells
          does not delete furniture (owner, 2026-08-22). */}
      {marked.length > 0 && (
        <div className="elev-marked" role="group" aria-label={T.marked_cells(marked.length)}>
          <span className="note">{T.marked_cells(marked.length)}</span>
          {/* ⚠ The reason INSTEAD of the button, not a disabled button beside
              it. The server refuses these with a 409 in English, after the
              press; MapScreen's rule is that a refusal the screen could have
              stated belongs before it. The 409 remains the backstop for what
              another tab did — and for a NAMED empty cell, which the document
              cannot see. */}
          {blocked ? (
            <span className="note warn" role="status">{T.cells_not_empty(blocked.cells)}</span>
          ) : (
            <button
              type="button"
              className="danger"
              aria-label={T.make_space(marked.length)}
              title={T.make_space_title}
              onClick={() =>
                props.onGaps(sec.id, marked.map((c) => ({ col: c.col, level: c.level })), true)}
            >
              {T.make_space(marked.length)}
            </button>
          )}
        </div>
      )}

      {/* The scroll lives HERE, around one section's columns — not around the
          whole panel (owner, 2026-08-16). A wide bookcase should slide its own
          columns; it should not drag the name box and the depth rule sideways
          with them. */}
      <div className="elev-scroll">
        <div
          className="elevation-grid"
          style={{ gridTemplateColumns: `repeat(${cols}, minmax(44px, 1fr))` }}
        >
        {Array.from({ length: cols }, (_, col) => (
          <div className="elev-col" key={col}>
            <div className="elev-col-head">{T.col_head(col + 1)}</div>
            {Array.from({ length: sec.columnLevels[col] ?? 0 }, (_, level) => {
              const shelf = shelfAt(sec, col, level)
              const gap = isGap(sec, col, level)
              const isSel = marked.some((c) => c.col === col && c.level === level)
              const override = shelf ? shelf.depth !== sec.defaultDepth : false
              // ⚠ A hole is still a BUTTON, and it is the only way back: the
              // owner's own words, *"user should be able to click on a
              // 'missing' cell and make it a real shelf again"*. It says what
              // it will do, not what it is, because "gap" names a state and
              // an accessible name has to name an action.
              if (gap) {
                return (
                  <button
                    key={level}
                    type="button"
                    className="elev-cell gap"
                    aria-label={T.restore_cell(addr, col + 1, level + 1)}
                    title={T.restore_cell_title}
                    onClick={() => props.onGaps(sec.id, [{ col, level }], false)}
                  >
                    <span className="elev-level">{level + 1}</span>
                  </button>
                )
              }
              return (
                <button
                  key={level}
                  type="button"
                  className={`elev-cell${isSel ? ' selected' : ''}${override ? ' override' : ''}`}
                  aria-label={T.shelf_at(addr, col + 1, level + 1)}
                  aria-pressed={isSel}
                  // Ctrl/Shift adds to the marked set — the same modifier the
                  // plan already uses to select several rooms, so the gesture
                  // is learned once.
                  onClick={(e) =>
                    props.onSelectShelf(sec.id, col, level, e.ctrlKey || e.metaKey || e.shiftKey)}
                >
                  <span className="elev-level">{level + 1}</span>
                  {shelf && shelf.depth > 1 && (
                    <span className="elev-depth" title={T.rows_deep(shelf.depth)}>
                      ×{shelf.depth}
                    </span>
                  )}
                  {shelf && shelf.photos > 0 && <span className="elev-photos">{shelf.photos}📷</span>}
                </button>
              )
            })}
            <div className="elev-col-foot">
              <button
                type="button"
                aria-label={T.remove_level(addr, col + 1)}
                disabled={(sec.columnLevels[col] ?? 1) <= 1}
                onClick={() => props.onColumnLevels(sec.id, col, (sec.columnLevels[col] ?? 1) - 1)}
              >
                −
              </button>
              <button
                type="button"
                aria-label={T.add_level(addr, col + 1)}
                onClick={() => props.onColumnLevels(sec.id, col, (sec.columnLevels[col] ?? 1) + 1)}
              >
                +
              </button>
            </div>
            </div>
          ))}
        </div>
      </div>

      <div className="elevation-cols">
        <button
          type="button"
          aria-label={many ? T.remove_column_of(label) : T.remove_column}
          disabled={cols <= 1}
          onClick={() => {
            // The slots in the column about to go — how many, and whether
            // any of them holds a photograph or a book.
            const going = sec.shelves.filter((s) => s.col >= cols - 1)
            const losing = shelvesInColumns(sec, cols - 1)
            if (!nothingBound(going) && !confirm(T.remove_column_confirm(losing)))
              return
            props.onColumnCount(sec.id, cols - 1)
          }}
        >
          − {T.column}
        </button>
        <button
          type="button"
          aria-label={many ? T.add_column_of(label) : T.add_column}
          onClick={() => props.onColumnCount(sec.id, cols + 1)}
        >
          + {T.column}
        </button>
      </div>

      <div className="section-defaults">
        <label>
          <span>{T.new_levels}</span>
          <input
            type="number"
            min={1}
            max={12}
            value={sec.defaultLevels}
            aria-label={many ? T.default_levels_of(label) : T.default_levels}
            onChange={(e) => props.onDefaultLevels(sec.id, Number(e.target.value))}
          />
        </label>
        <button
          type="button"
          aria-label={many ? T.apply_levels_of(label) : T.apply_levels}
          onClick={() => props.onApplyDefaultLevels(sec.id)}
        >
          {T.apply}
        </button>
        <label>
          <span>{T.new_depth}</span>
          <input
            type="number"
            min={1}
            max={MAX_DEPTH}
            value={sec.defaultDepth}
            aria-label={many ? T.default_depth_of(label) : T.default_depth}
            onChange={(e) => props.onDefaultDepth(sec.id, Number(e.target.value))}
          />
        </label>
      </div>

      {differing > 0 && (
        <p className="rule">
          {T.depth_kept(differing, label)}
          <button
            type="button"
            aria-label={many ? T.apply_depth_of(label) : T.apply_depth}
            onClick={() => props.onApplyDefaultDepth(sec.id)}
          >
            {T.apply_to_all(sec.shelves.length)}
          </button>
        </p>
      )}
    </section>
  )
}
