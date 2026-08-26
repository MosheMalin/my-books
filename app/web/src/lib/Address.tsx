/**
 * "Where is it" — ONE renderer, wherever the question is asked (P6.5b).
 *
 * VISION §7 requires the catalogue to answer *"given a book, where is it —
 * including which row front-to-back"*, and UI_PLAN §1.1 fixes the vocabulary:
 * **column** across, **level** down, **depth** back, three axes that never
 * share a word. The rule about which parts appear at all is NOT here — it is
 * one function on the server (`app.domain.place.address_parts`), because a
 * client that decided it locally would be the second copy and the two would
 * disagree the first time somebody added a section.
 *
 * ⚠ **Segments, never one string.** The room and the bookcase are names the
 * owner typed; the rest is our vocabulary. `unicode-bidi: plaintext` resolves
 * a paragraph from its first strong character, so `סלון · Ikea Billy · עמודה
 * 2` as a single element flips at the first Latin letter and prints the parts
 * in the wrong order — the failure this repo has now met on a shelf name, a
 * site name and a library name. Each segment is its own element, each
 * resolving its own direction, which is the fix that has held every time.
 *
 * ⚠ The address does NOT begin with the site. §3.7 settles that a Site is a
 * grouping and never part of an address; it is rendered here as a leading
 * piece of CONTEXT, present only when the household has more than one, which
 * is §3.9's rule for the map's own site segment.
 */
import { Fragment } from 'react'

import { useAsync } from '@booksnap/ui'

import type { ShelfWhere } from '../api/client'
import { getShelfWhere } from '../api/client'
import { useI18n } from './i18n'

/**
 * Ask the server where a shelf stands. ONE fetch shape for every surface that
 * asks — the book surface asks per copy, the shelf screen asks for itself.
 *
 * A null `shelfId` resolves to null WITHOUT a request: an unshelved copy is a
 * legitimate state, not a lookup that failed, and the two must not print the
 * same sentence.
 */
export function useShelfWhere(shelfId: string | null, depth?: number) {
  return useAsync(
    (signal) => (shelfId === null
      ? Promise.resolve(null)
      : getShelfWhere(shelfId, depth, { signal })),
    [shelfId, depth],
  )
}

export interface AddressProps {
  where: ShelfWhere
  /** Renders the §5.7 note under the line when the copy stands behind the
   *  front row. Off on a list row, where one line is the whole budget. */
  note?: boolean
}

/** One piece of the address. `typed` marks a name the OWNER wrote, which is
 *  the only thing that needs `rtl-safe` — our own words are already in the
 *  UI's direction. */
interface Segment {
  key: string
  text: string
  typed: boolean
}

export function addressSegments(
  where: ShelfWhere,
  t: ReturnType<typeof useI18n>['t'],
): Segment[] {
  const at = where.address
  if (!at) return []
  const out: Segment[] = []
  if (where.site) out.push({ key: 'site', text: where.site, typed: true })
  if (at.place) out.push({ key: 'place', text: at.place, typed: true })
  // An unnamed case still gets a segment: without one the line reads
  // "סלון · עמודה 2", which says the room has exactly one bookcase — and
  // that is a claim, not an omission. Naming a case is optional exactly as
  // naming a shelf is, so the empty state has to be sayable.
  out.push(at.bookcase
    ? { key: 'case', text: at.bookcase, typed: true }
    : { key: 'case', text: t.where_case_unnamed, typed: false })
  if (at.section !== null && at.section !== undefined)
    out.push({ key: 'section', text: t.where_section(at.section), typed: false })
  if (at.column !== null && at.column !== undefined)
    out.push({ key: 'col', text: t.where_col(at.column), typed: false })
  out.push({ key: 'level', text: t.where_level(at.level), typed: false })
  if (at.depth !== null && at.depth !== undefined)
    out.push({ key: 'depth', text: t.depth_n(at.depth), typed: false })
  return out
}

export function Address({ where, note = true }: AddressProps) {
  const { t } = useI18n()
  const parts = addressSegments(where, t)
  if (parts.length === 0)
    return <p className="tiny muted whereline">{t.where_nowhere}</p>

  const behind = note && where.address?.depth != null && where.address.depth > 1

  return (
    <>
      <p className="whereline">
        {/* ⚠ The separator TRAILS its segment and is glued to it. Measured
            at 375x812 on the owner's library, with it leading instead: a
            four-part address wrapped after «עמודה 2» and the second line
            began «· גובה 2» — a dot at the start of a line reads as a
            bullet, i.e. as a list, which is the one thing an address is not.
            `nowrap` on the pair is what keeps them together. */}
        {parts.map((part, i) => (
          <Fragment key={part.key}>
            <span className="addr-seg">
              <span className={part.typed ? 'rtl-safe' : undefined}>
                {part.text}
              </span>
              {i < parts.length - 1
                && <span className="sep" aria-hidden="true"> ·</span>}
            </span>
            {/* ⚠ The break opportunity, OUTSIDE the nowrap unit. Without a
                space between the spans there is no breakable point at all, so
                the line cannot wrap: measured at 375x812, a four-part address
                overflowed its 187px column and pushed the whole document to
                393px. With the space here, a wrap lands after a separator and
                the next line begins with a word. */}
            {i < parts.length - 1 && ' '}
          </Fragment>
        ))}
      </p>
      {behind && <p className="tiny muted">{t.where_behind}</p>}
    </>
  )
}
