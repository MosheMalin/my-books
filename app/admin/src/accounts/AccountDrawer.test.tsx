/**
 * The drawer's merge helper, on its own.
 *
 * ⚠ The screen-level tests exercise the merge through two fixtures with real
 * dates, and they cannot reach the one branch that matters most: an UNDATED
 * row. `ImageDTO.captured_at` is genuinely nullable — `t.img_undated` exists
 * for it — and no fixture in a drawer preview has a null, so the rule was
 * argued at length in a docstring and pinned by nothing. Reversing it (undated
 * FIRST) left the whole ring green.
 *
 * It is a pure function of its inputs, so a unit test is the honest shape;
 * adding a null-dated row to the shared world would have changed what four
 * unrelated screens render in order to test one comparison.
 */
import { describe, expect, it } from 'vitest'

import { newestFirst } from './AccountDrawer'

const at = (r: { d: string | null }) => r.d

describe('newestFirst', () => {
  it('orders newest first', () => {
    const rows = [{ d: '2026-01-01' }, { d: '2026-03-01' }, { d: '2026-02-01' }]
    expect(newestFirst(rows, at).map((r) => r.d))
      .toEqual(['2026-03-01', '2026-02-01', '2026-01-01'])
  })

  /**
   * ⚠⚠ Undated rows sort LAST. `null` means the field was never recorded, and
   * letting "unknown" win a "most recent" list would put the oldest imports at
   * the top of every customer's drawer — the rows least likely to be what an
   * operator opened the drawer to see.
   */
  it('puts undated rows last, never first', () => {
    const rows = [{ d: null }, { d: '2026-01-01' }, { d: null }, { d: '2026-03-01' }]
    expect(newestFirst(rows, at).map((r) => r.d))
      .toEqual(['2026-03-01', '2026-01-01', null, null])
  })

  it('does not mutate its input', () => {
    const rows = [{ d: '2026-01-01' }, { d: '2026-03-01' }]
    newestFirst(rows, at)
    expect(rows.map((r) => r.d)).toEqual(['2026-01-01', '2026-03-01'])
  })

  /**
   * ⚠ Ties keep their arrival order, and the SERVER breaks them on `id DESC`
   * — so a page whose rows share a timestamp can be ordered differently here
   * than the server would order it. Stated rather than fixed: the drawer shows
   * five rows of a preview, the server's own note names the case that produces
   * ties (a phone uploading a burst under one timestamp), and inventing a
   * second tiebreak in the client would be a second ordering rule to drift.
   */
  it('leaves equal timestamps in the order they arrived', () => {
    const rows = [{ d: '2026-01-01', id: 'a' }, { d: '2026-01-01', id: 'b' }]
    expect(newestFirst(rows, (r) => r.d).map((r) => r.id)).toEqual(['a', 'b'])
  })
})
