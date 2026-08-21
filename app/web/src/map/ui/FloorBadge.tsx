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

type Props = {
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
  const inputRef = useRef<HTMLInputElement | null>(null)
  const current = props.floors.find((f) => f.id === props.floorId)

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [editing])

  return (
    /* ⚠ No `dir="auto"` on the CONTAINER. `inset-inline-start` resolves
       against the element's OWN direction, and `auto` takes that from the
       first strong character of the floor's NAME — so in an English UI a
       storey called "קומת קרקע" put the badge at x=814 (the right edge of a
       929px canvas) and renaming it to "Ground" moved it to x=10, with no
       other change. Direction per STRING, alignment per CONTAINER: the name
       span carries `.rtl-safe`, which is the whole of what the text needs. */
    <div className="floor-badge">
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
