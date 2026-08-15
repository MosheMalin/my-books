/**
 * The bookcase, front-on — the SECOND geometry (MAP_PLAN §3.2).
 *
 * Columns across, levels down, one cell per shelf. Pinned LTR like the plan
 * and for the same reason: a piece of furniture must not mirror when the UI
 * language changes. *Which physical end column 1 is* stays open — `UI_PLAN`
 * §8 and MAP_PLAN §7 Q3 — so the header says "col 1" and claims nothing more.
 */

import type { Bookcase } from '../core/model'
import { columnCount, shelfAt } from '../core/model'
import type { Selection } from './types'

type Props = {
  bc: Bookcase
  selection: Selection
  onSelectShelf: (col: number, level: number) => void
  onColumnLevels: (col: number, levels: number) => void
  onColumnCount: (count: number) => void
}

export function Elevation({ bc, selection, onSelectShelf, onColumnLevels, onColumnCount }: Props) {
  const cols = columnCount(bc)
  const selected = selection.shelf?.caseId === bc.id ? selection.shelf : null

  return (
    <div className="elevation" dir="ltr">
      <div className="elevation-grid" style={{ gridTemplateColumns: `repeat(${cols}, minmax(48px, 1fr))` }}>
        {Array.from({ length: cols }, (_, col) => (
          <div className="elev-col" key={col}>
            <div className="elev-col-head">col {col + 1}</div>
            {Array.from({ length: bc.columnLevels[col] ?? 0 }, (_, level) => {
              const shelf = shelfAt(bc, col, level)
              const isSel = selected?.col === col && selected.level === level
              const override = shelf ? shelf.depth !== bc.defaultDepth : false
              return (
                <button
                  key={level}
                  type="button"
                  className={`elev-cell${isSel ? ' selected' : ''}${override ? ' override' : ''}`}
                  aria-label={`shelf, column ${col + 1}, level ${level + 1}`}
                  aria-pressed={isSel}
                  onClick={() => onSelectShelf(col, level)}
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
                aria-label={`remove a level from column ${col + 1}`}
                disabled={(bc.columnLevels[col] ?? 1) <= 1}
                onClick={() => onColumnLevels(col, (bc.columnLevels[col] ?? 1) - 1)}
              >
                −
              </button>
              <button
                type="button"
                aria-label={`add a level to column ${col + 1}`}
                onClick={() => onColumnLevels(col, (bc.columnLevels[col] ?? 1) + 1)}
              >
                +
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className="elevation-cols">
        <button
          type="button"
          aria-label="remove the last column"
          disabled={cols <= 1}
          onClick={() => onColumnCount(cols - 1)}
        >
          − column
        </button>
        <button type="button" aria-label="add a column" onClick={() => onColumnCount(cols + 1)}>
          + column
        </button>
      </div>
    </div>
  )
}
