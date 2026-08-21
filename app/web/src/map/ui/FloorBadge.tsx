import { useI18n } from '../../lib/i18n'
import { mapText } from '../text'
/**
 * The storey, in the corner of the board.
 *
 * It used to be a select, a text box and two buttons on the control line
 * (owner, 2026-08-16: *"Floor is still taking too much in the control line…
 * name of the floor can be on the top corner of the board"*). Everything
 * floor-shaped now lives here: the name is the label, and the menu behind it
 * switches, adds, renames and removes.
 *
 * It is an HTML overlay rather than something drawn on the plan, which is what
 * makes it **immune to zoom and pan** — a label that shrinks when you zoom out
 * is a label you cannot read exactly when you need it.
 */

import { useEffect, useRef, useState } from 'react'

import type { Floor } from '../core/model'
import { Menu } from './Menu'

/**
 * The SITE segment, and why it is here rather than in the toolbar.
 *
 * A site is the property — "home", "the parents' place" — and the floors below
 * it are its storeys (§3.9), so "which site" and "which storey" are one
 * question asked twice. They belong to the same corner of the board.
 *
 * ⚠ It renders NOTHING until a second site exists, the way the library
 * switcher stays a plain label until a second library does. A household with
 * one home never learns the word: adding the second site is a row in the Plan
 * menu, and the segment appears with it.
 */
type SiteProps = {
  sites: { id: string; name: string }[]
  siteId: string
  onSite: (id: string) => void
  onRenameSite: (id: string, name: string) => void
  onRemoveSite: (id: string) => void
}

type Props = {
  site: SiteProps
  floors: Floor[]
  floorId: string
  allFloors: boolean
  onFloor: (id: string) => void
  onAllFloors: (on: boolean) => void
  onAdd: () => void
  onRename: (id: string, name: string) => void
  onRemove: () => void
}

export function FloorBadge(props: Props) {
  const T = mapText(useI18n().lang)
  const [editing, setEditing] = useState(false)
  /**
   * ⚠ The site's name is a DRAFT while it is being typed, and the floor's is
   * not — and that asymmetry is the point.
   *
   * A floor lives in the document, so each keystroke rides the diff and
   * nothing remounts. A site is not in the document: telling the server
   * per keystroke re-derived the whole editor, which unmounted this component
   * and took the box with it. A review measured the box gone after ONE
   * character, six PATCHes each built from the stale name plus one letter, and
   * the rest of the word going to the board's key handler — where Backspace
   * deletes what is selected. `null` means "not renaming"; a string is what
   * the owner has typed so far.
   */
  const [siteDraft, setSiteDraft] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const siteRef = useRef<HTMLInputElement | null>(null)
  const current = props.floors.find((f) => f.id === props.floorId)
  const here = props.site.sites.find((s) => s.id === props.site.siteId)

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [editing])

  useEffect(() => {
    if (siteDraft !== null) {
      siteRef.current?.focus()
      siteRef.current?.select()
    }
    // Only when the box APPEARS: re-selecting on every keystroke would put the
    // caret back at the start of what is being typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteDraft !== null])

  /** One PATCH, at the end, and only if it says something new. */
  const commitSite = () => {
    const name = (siteDraft ?? '').trim()
    if (name && name !== here?.name) props.site.onRenameSite(props.site.siteId, name)
    setSiteDraft(null)
  }

  return (
    /* ⚠ No `dir="auto"` on the CONTAINER. `inset-inline-start` resolves
       against the element's OWN direction, and `auto` takes that from the
       first strong character of the floor's NAME — so in an English UI a
       storey called "קומת קרקע" put the badge at x=814 (the right edge of a
       929px canvas) and renaming it to "Ground" moved it to x=10, with no
       other change. Direction per STRING, alignment per CONTAINER: the name
       span carries `.rtl-safe`, which is the whole of what the text needs. */
    <div className="floor-badge">
      {props.site.sites.length > 1 && (
        <>
          {/* ⚠ The box REPLACES the name, the way the floor's does. Rendered
              beside it, the site's box appeared immediately before the FLOOR's
              name and read as the floor's — measured at review. */}
          {siteDraft !== null ? (
            <input
              ref={siteRef}
              className="rtl-safe"
              aria-label={T.site_name}
              value={siteDraft}
              onChange={(e) => setSiteDraft(e.target.value)}
              onKeyDown={(e) => {
                // Escape ABANDONS, Enter commits — the box holds a draft now,
                // so for the first time there is a difference between them.
                if (e.key === 'Escape') setSiteDraft(null)
                else if (e.key === 'Enter') commitSite()
              }}
              onBlur={commitSite}
            />
          ) : (
            <span className="site-name rtl-safe">
              {here?.name || T.site}
            </span>
          )}
          <Menu
            label=""
            title={T.site_menu}
            items={[
              ...props.site.sites.map((s) => ({
                label: s.name || T.site,
                checked: s.id === props.site.siteId,
                onSelect: () => props.site.onSite(s.id),
              })),
              {
                label: T.rename_site(here?.name || T.site),
                onSelect: () => setSiteDraft(here?.name ?? ''),
              },
              {
                label: T.remove_site(here?.name || T.site),
                danger: true,
                onSelect: () => props.site.onRemoveSite(props.site.siteId),
              },
            ]}
          />
          <span className="badge-sep" aria-hidden="true">·</span>
        </>
      )}
      {editing ? (
        <input
          ref={inputRef}
          className="rtl-safe"
          aria-label={T.floor_name}
          value={current?.name ?? ''}
          onChange={(e) => props.onRename(props.floorId, e.target.value)}
          // Enter and Escape both put you back on the board — a name box that
          // holds the keyboard is a name box you have to click your way out of.
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === 'Escape') setEditing(false)
          }}
          onBlur={() => setEditing(false)}
        />
      ) : (
        <span
          className="floor-name rtl-safe"
          onDoubleClick={() => !props.allFloors && setEditing(true)}
          title={props.allFloors ? undefined : T.rename_floor_hint}
        >
          {props.allFloors ? T.all_floors : current?.name || T.floor}
        </span>
      )}

      {/* ⚠ The menu is a bare chevron, so it needs a name of its own: with an
          empty label `Menu` falls back to `title`, and neither was set — the
          only control on the board announced nothing at all. */}
      <Menu
        label=""
        title={T.floor_menu}
        items={[
          ...props.floors.map((f) => ({
            label: f.name || T.floor,
            checked: !props.allFloors && f.id === props.floorId,
            onSelect: () => {
              props.onAllFloors(false)
              props.onFloor(f.id)
            },
          })),
          // ⚠ ABSENT with one storey, not greyed. A household that never
          // adds a floor — most of them — met three permanently-dead rows
          // with no reason given, which is what the "absent, not disabled"
          // rule exists to prevent. Worse, the sentence that WOULD explain
          // the disabled *remove* (`one_floor_at_least`) is only reachable by
          // calling it, so it was live in the source and dead on screen.
          ...(props.floors.length > 1
            ? [{
                label: T.all_floors_long,
                checked: props.allFloors,
                onSelect: () => props.onAllFloors(!props.allFloors),
              }]
            : []),
          { label: T.add_floor, onSelect: props.onAdd },
          {
            // Named for THIS floor: two controls announcing the same
            // accessible name collide, and last time the colliding pair
            // included rename — the one that writes (CLAUDE.md).
            label: T.rename_floor(current?.name || T.floor),
            disabled: props.allFloors,
            onSelect: () => setEditing(true),
          },
          ...(props.floors.length > 1
            ? [{
                label: T.remove_floor(current?.name || T.floor),
                disabled: props.allFloors,
                danger: true,
                onSelect: props.onRemove,
              }]
            : []),
        ]}
      />
    </div>
  )
}
