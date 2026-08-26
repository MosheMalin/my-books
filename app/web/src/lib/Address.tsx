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
import { planHash } from './route'

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
  /**
   * Append *show it on the drawing* (P6.5c).
   *
   * ⚠ Offered only when there IS an address — a link to a plan that cannot
   * point at anything is a door onto a shrug. And it is the half that makes
   * an address usable at all on a real library: measured on the owner's,
   * **every one of the 11 bookcases is unnamed**, so «סלון · כוננית ללא
   * שם · עמודה 2» cannot tell two cases in one room apart. A highlighted
   * cell on the drawing can.
   */
  onMap?: boolean
}

/** One piece of the address. `typed` marks a name the OWNER wrote, which is
 *  the only thing that needs `rtl-safe` — our own words are already in the
 *  UI's direction. */
interface Segment {
  key: string
  text: string
  typed: boolean
}

function addressSegments(
  where: ShelfWhere,
  t: ReturnType<typeof useI18n>['t'],
): Segment[] {
  const at = where.address
  if (!at) return []
  const out: Segment[] = []
  if (where.site) out.push({ key: 'site', text: where.site, typed: true })
  // ⚠ A room with no name still gets a segment, by the SAME argument the
  // bookcase below carries — and the asymmetry was measured: 20 of the
  // owner's 152 addressed shelves stand on bookcases attached to no room at
  // all, and printed «כוננית ללא שם · עמודה 1 · גובה 4», which
  // identifies nothing in a two-storey house. Omitting the case says the room
  // has one bookcase; omitting the room says the building has one room.
  out.push(at.place
    ? { key: 'place', text: at.place, typed: true }
    : { key: 'place', text: t.where_room_unnamed, typed: false })
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

export function Address({ where, note = true, onMap = false }: AddressProps) {
  const { t } = useI18n()
  const parts = addressSegments(where, t)
  if (parts.length === 0)
    return (
      <>
        <p className="tiny muted whereline">{t.where_nowhere}</p>
        {/* ⚠ The state that needs an ACTION was the one state with no
            control on it, while the state that needs none had one. Measured
            on the owner's library: every one of the 22 books that stand on a
            shelf stand on the ONE shelf that is not on the drawing, so this
            sentence — not the address — is what this feature actually shows
            today. The remedy exists (the plan's empty-cell picker lists every
            shelf standing nowhere) and nothing named it, so a household
            member reading *not on the map yet* had no way to learn that the
            answer is one tab away. */}
        {onMap && (
          <a className="linkish" href={planHash()}>
            {t.where_put_on_map}
          </a>
        )}
      </>
    )

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
      {onMap && (
        <a className="linkish" href={planHash(where.shelf_id)}>
          {t.where_show_on_map}
        </a>
      )}
    </>
  )
}
