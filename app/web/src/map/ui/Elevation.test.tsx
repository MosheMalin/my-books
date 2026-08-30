/**
 * The elevation grid, where a cell has to say what it is.
 *
 * Everything else about this component is exercised through `Inspector`,
 * which renders it. What lives here is the one question the grid answers on
 * its own: given a cell, what does it look like and what does it announce.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { I18nProvider } from '../../lib/i18n'
import { mapText } from '../text'
import { newBookcase } from '../core/model'
import type { Bookcase } from '../core/model'
import { Elevation, type ElevationProps } from './Elevation'
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
          onMoveSection={() => {}}
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

describe('reordering a stack of sections (P6.7a)', () => {
  /** Two sections, ids naming their ORDINAL: `s1` stands on the floor. */
  const stacked = (): Bookcase => ({
    ...newBookcase('c1', 'מרכזית', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 1),
    sections: [
      { id: 's1', columnLevels: [1], gaps: [], defaultLevels: 1,
        defaultDepth: 1, shelves: [] },
      { id: 's2', columnLevels: [1], gaps: [], defaultLevels: 1,
        defaultDepth: 1, shelves: [] },
    ],
  })

  const draw = (bc: Bookcase, onMoveSection: ElevationProps['onMoveSection']) =>
    render(
      <I18nProvider>
        <Elevation
          bc={bc}
          selection={EMPTY}
          onSelectShelf={() => {}}
          onMoveSection={onMoveSection}
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

  it('sends UP for the section drawn LOWEST, because up means the ceiling', async () => {
    // ⚠ The whole trap in one assertion. This grid draws top-first
    // (`sectionsTopDown`) and the model stores bottom-first, so the arrow
    // pointing up on screen belongs to the section at INDEX 0 — the one on
    // the floor — and it must send 'up'. Reversing either end reads as
    // "the arrows are backwards" and swaps the wrong pair on a real
    // bookcase.
    const moved = vi.fn()
    draw(stacked(), moved)

    const up = screen.getByRole('button',
      { name: HE.move_section_up(HE.section_n(1)) })
    const down = screen.getByRole('button',
      { name: HE.move_section_down(HE.section_n(2)) })
    // "Lowest" is a real claim, not a comment: section 1 stands on the floor,
    // so this grid must draw it AFTER section 2. DOCUMENT_POSITION_PRECEDING
    // says the ▼ of section 2 comes first.
    expect(up.compareDocumentPosition(down)
      & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()

    await userEvent.click(up)
    expect(moved).toHaveBeenCalledWith('s1', 'up')

    await userEvent.click(down)
    expect(moved).toHaveBeenCalledWith('s2', 'down')
  })

  it('absents the arrow at each end of the stack rather than disabling it', () => {
    // The house rule, and here it is also what keeps the server's 409 out of
    // the owner's way: there is nothing above the top section, and a
    // disabled button would invite the press that earns the refusal.
    draw(stacked(), vi.fn())
    expect(screen.queryByRole('button',
      { name: HE.move_section_up(HE.section_n(2)) })).toBeNull()
    expect(screen.queryByRole('button',
      { name: HE.move_section_down(HE.section_n(1)) })).toBeNull()
  })

  it('offers no arrows at all to a bookcase built of one section', () => {
    // Nothing to reorder, and the header they live in is itself absent —
    // a plain bookcase never says the word "section" anywhere.
    const bc = stacked()
    draw({ ...bc, sections: [bc.sections[0]!] }, vi.fn())
    expect(screen.queryByRole('button',
      { name: HE.move_section_up(HE.section_n(1)) })).toBeNull()
    expect(screen.queryByRole('button',
      { name: HE.move_section_down(HE.section_n(1)) })).toBeNull()
  })
})

describe('proposing a shape from one photograph (P6.6, P6.7g)', () => {
  /**
   * The owner, having photographed a bookcase: *"it got the number of shelves
   * right, but missed a column (actually — I do not see that it takes
   * column)."* It did not take one: the band detector answers about
   * horizontal lines, and the proposal had no column field at all.
   */
  const twoCols = (): Bookcase => ({
    ...newBookcase('c1', '', { x: 0, y: 0, w: 4, h: 1 }, 'S', null, 'f1', 1),
    sections: [{
      id: 's1', columnLevels: [3, 3], gaps: [], defaultLevels: 3,
      defaultDepth: 1, shelves: [],
    }],
  })

  const draw = (said: { levels: number; columns: number },
                onColumnCount = vi.fn(), onDefaultLevels = vi.fn()) => {
    render(
      <I18nProvider>
        <Elevation
          bc={twoCols()}
          selection={EMPTY}
          onSelectShelf={() => {}}
          onMoveSection={() => {}}
          onGaps={() => {}}
          onColumnLevels={() => {}}
          onColumnCount={onColumnCount}
          onDefaultLevels={onDefaultLevels}
          onProposeLevels={async () => said}
          onDefaultDepth={() => {}}
          onApplyDefaultLevels={() => {}}
          onApplyDefaultDepth={() => {}}
          onAddSection={() => {}}
          onRemoveSection={() => {}}
        />
      </I18nProvider>,
    )
    return { onColumnCount, onDefaultLevels }
  }

  const photo = () =>
    new File([new Uint8Array([1])], 'case.jpg', { type: 'image/jpeg' })

  it('says BOTH axes, and offers the column count as a press of its own',
     async () => {
    // ⚠ Offered, never applied. Levels fill a creation-time DEFAULT and touch
    // no existing shelf (§3.3); a column count IS the shape, so applying one
    // creates or destroys real slots — and §3.14 says only a ✓ binds.
    const { onColumnCount, onDefaultLevels } = draw({ levels: 6, columns: 4 })

    await userEvent.upload(
      screen.getByLabelText(HE.propose_levels), photo())

    expect(await screen.findByText(HE.proposed_shape(6, 4))).toBeInTheDocument()
    expect(onDefaultLevels).toHaveBeenCalledWith('s1', 6)
    expect(onColumnCount).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: HE.apply_columns(4) }))
    expect(onColumnCount).toHaveBeenCalledWith('s1', 4)
  })

  it('never offers a count that would REMOVE columns', async () => {
    // Shrinking destroys slots and the books standing in them. The column
    // control two rows up is where that happens, because it is the one that
    // says what it costs — so this reports the number and stops.
    const { onColumnCount } = draw({ levels: 5, columns: 1 })

    await userEvent.upload(screen.getByLabelText(HE.propose_levels), photo())

    expect(await screen.findByText(HE.proposed_shape(5, 1))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: HE.apply_columns(1) })).toBeNull()
    expect(onColumnCount).not.toHaveBeenCalled()
  })

  it('reads one-and-one as a photo of a single shelf, not as a failure',
     async () => {
    // The commonest picture in this library: all ten of the owner's full-size
    // photographs answer 1 band and 1 column. Without this sentence the
    // feature reads as broken on the input it meets most.
    draw({ levels: 1, columns: 1 })

    await userEvent.upload(screen.getByLabelText(HE.propose_levels), photo())

    const said = await screen.findByText(HE.proposed_shape(1, 1))
    expect(said.textContent).toContain('מדף אחד')
    expect(said.textContent).toContain('עמודה אחת')
    expect(said.textContent).toContain('צלמו את כל הכוננית')
  })
})

