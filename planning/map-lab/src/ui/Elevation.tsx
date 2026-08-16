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
import { MAX_DEPTH, columnCount, sectionsTopDown, shelfAt, shelvesDifferingFromDefaultDepth, shelvesInColumns } from '../core/model'
import type { Selection } from './types'

type Props = {
  bc: Bookcase
  selection: Selection
  onSelectShelf: (sectionId: string, col: number, level: number) => void
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
  const { bc } = props
  const many = bc.sections.length > 1
  return (
    <div className="elevation" dir="ltr">
      {many && (
        <button
          type="button"
          className="section-add"
          onClick={() => props.onAddSection('top')}
          aria-label="add a section on top"
        >
          ＋ another section on top
        </button>
      )}

      {sectionsTopDown(bc).map((sec) => (
        <SectionBlock key={sec.id} {...props} sec={sec} many={many} />
      ))}

      <button
        type="button"
        className="section-add"
        onClick={() => props.onAddSection(many ? 'bottom' : 'top')}
        aria-label={many ? 'add a section underneath' : 'split this bookcase into sections'}
      >
        {many ? '＋ another section underneath' : '＋ a second section on top (a unit standing on this one)'}
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
  const cols = columnCount(sec)
  const selected = selection.shelf?.caseId === bc.id && selection.shelf.sectionId === sec.id
    ? selection.shelf
    : null
  const index = bc.sections.findIndex((s) => s.id === sec.id)
  // Numbered BOTTOM-UP, because that is how the thing was built: section 1
  // stands on the floor.
  const label = `Section ${index + 1}`
  const where =
    index === 0 ? ' · on the floor' : index === bc.sections.length - 1 ? ' · on top' : ''
  // Accessible names print the section only when there IS more than one — the
  // same "only what discriminates" rule the shelf address follows. Uniqueness
  // is not at risk: with one section there is nothing to collide with.
  const addr = many ? `${label.toLowerCase()}, ` : ''
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
            aria-label={`remove ${label.toLowerCase()}`}
            title={`Remove ${label.toLowerCase()} and its ${sec.shelves.length} shelves`}
            onClick={() => {
              if (confirm(`Remove ${label.toLowerCase()} and its ${sec.shelves.length} shelves?`)) {
                props.onRemoveSection(sec.id)
              }
            }}
          >
            ✕
          </button>
        </header>
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
            <div className="elev-col-head">col {col + 1}</div>
            {Array.from({ length: sec.columnLevels[col] ?? 0 }, (_, level) => {
              const shelf = shelfAt(sec, col, level)
              const isSel = selected?.col === col && selected.level === level
              const override = shelf ? shelf.depth !== sec.defaultDepth : false
              return (
                <button
                  key={level}
                  type="button"
                  className={`elev-cell${isSel ? ' selected' : ''}${override ? ' override' : ''}`}
                  aria-label={`shelf, ${addr}column ${col + 1}, level ${level + 1}`}
                  aria-pressed={isSel}
                  onClick={() => props.onSelectShelf(sec.id, col, level)}
                >
                  <span className="elev-level">{level + 1}</span>
                  {shelf && shelf.depth > 1 && (
                    <span className="elev-depth" title={`${shelf.depth} rows front-to-back`}>
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
                aria-label={`remove a level from ${addr}column ${col + 1}`}
                disabled={(sec.columnLevels[col] ?? 1) <= 1}
                onClick={() => props.onColumnLevels(sec.id, col, (sec.columnLevels[col] ?? 1) - 1)}
              >
                −
              </button>
              <button
                type="button"
                aria-label={`add a level to ${addr}column ${col + 1}`}
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
          aria-label={many ? `remove the last column of ${label.toLowerCase()}` : 'remove the last column'}
          disabled={cols <= 1}
          onClick={() => {
            const losing = shelvesInColumns(sec, cols - 1)
            if (losing > 0 && !confirm(`Remove the last column and its ${losing} shelves?`)) return
            props.onColumnCount(sec.id, cols - 1)
          }}
        >
          − column
        </button>
        <button
          type="button"
          aria-label={many ? `add a column to ${label.toLowerCase()}` : 'add a column'}
          onClick={() => props.onColumnCount(sec.id, cols + 1)}
        >
          + column
        </button>
      </div>

      <div className="section-defaults">
        <label>
          <span>new levels</span>
          <input
            type="number"
            min={1}
            max={12}
            value={sec.defaultLevels}
            aria-label={many ? `default levels per column, ${label.toLowerCase()}` : 'default levels per column'}
            onChange={(e) => props.onDefaultLevels(sec.id, Number(e.target.value))}
          />
        </label>
        <button
          type="button"
          aria-label={many ? `apply the level default to every column of ${label.toLowerCase()}` : 'apply the level default to every column'}
          onClick={() => props.onApplyDefaultLevels(sec.id)}
        >
          apply
        </button>
        <label>
          <span>new depth</span>
          <input
            type="number"
            min={1}
            max={MAX_DEPTH}
            value={sec.defaultDepth}
            aria-label={many ? `default depth, ${label.toLowerCase()}` : 'default depth'}
            onChange={(e) => props.onDefaultDepth(sec.id, Number(e.target.value))}
          />
        </label>
      </div>

      {differing > 0 && (
        <p className="rule">
          <strong>{differing}</strong> existing{' '}
          {differing === 1 ? 'shelf keeps its own depth' : 'shelves keep their own depth'} in{' '}
          {label.toLowerCase()}. Changing the default never reaches back into
          them — that would delete the location of every book standing in a back
          row.
          <button
            type="button"
            aria-label={many ? `apply the depth default to every shelf of ${label.toLowerCase()}` : 'apply the depth default to every shelf'}
            onClick={() => props.onApplyDefaultDepth(sec.id)}
          >
            Apply to all {sec.shelves.length} shelves
          </button>
        </p>
      )}
    </section>
  )
}
