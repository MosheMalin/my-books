/**
 * The elevation grid, where a cell has to say what it is.
 *
 * Everything else about this component is exercised through `Inspector`,
 * which renders it. What lives here is the one question the grid answers on
 * its own: given a cell, what does it look like and what does it announce.
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { I18nProvider } from '../../lib/i18n'
import { mapText } from '../text'
import { newBookcase } from '../core/model'
import type { Bookcase } from '../core/model'
import { Elevation } from './Elevation'
import { EMPTY } from './types'

const HE = mapText('he')

describe('a cell the server says is EMPTY (P6.4c)', () => {
  it('is named for what it is, not for a shelf that is not there', () => {
    // ⚠ Measured at 375x812 right after a real unbind: the free cell and its
    // occupied neighbour had identical markup and identical computed
    // background, border, colour and opacity — and on the owner's library
    // every addressed shelf holds zero books and zero photographs, so the
    // badges that might have differed do not exist. The grid changed by ZERO
    // pixels for the gesture just made, and the accessible name still said
    // "מדף". The gap branch one `if` above does the opposite, for this
    // reason.
    const bc: Bookcase = {
      ...newBookcase('c1', 'ארון', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 1),
      sections: [{
        id: 's1', columnLevels: [2], gaps: [],
        defaultLevels: 2, defaultDepth: 1,
        shelves: [
          { col: 0, level: 0, depth: 1, photos: 0, books: 0, id: 'sh-1' },
          { col: 0, level: 1, depth: 1, photos: 0, books: 0, free: true },
        ],
      }],
    }
    render(
      <I18nProvider>
        <Elevation
          bc={bc}
          selection={EMPTY}
          onSelectShelf={() => {}}
          onGaps={() => {}}
          onColumnLevels={() => {}}
          onColumnCount={() => {}}
          onDefaultLevels={() => {}}
          onDefaultDepth={() => {}}
          onApplyDefaultLevels={() => {}}
          onApplyDefaultDepth={() => {}}
          onAddSection={() => {}}
          onRemoveSection={() => {}}
        />
      </I18nProvider>,
    )

    const free = screen.getByRole('button', { name: HE.empty_cell('', 1, 2) })
    const taken = screen.getByRole('button', { name: HE.shelf_at('', 1, 1) })
    expect(free.className).toContain('empty')
    expect(taken.className).not.toContain('empty')
  })
})
