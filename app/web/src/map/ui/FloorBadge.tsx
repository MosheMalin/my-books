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
    <div className="floor-badge" dir="auto">
      {editing ? (
        <input
          ref={inputRef}
          className="rtl-safe"
          aria-label="floor name"
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
          title={props.allFloors ? undefined : 'Double-click to rename this floor'}
        >
          {props.allFloors ? 'All floors' : current?.name || 'Floor'}
        </span>
      )}

      <Menu
        label=""
        items={[
          ...props.floors.map((f) => ({
            label: f.name || 'Floor',
            checked: !props.allFloors && f.id === props.floorId,
            onSelect: () => {
              props.onAllFloors(false)
              props.onFloor(f.id)
            },
          })),
          {
            label: 'All floors, side by side',
            checked: props.allFloors,
            disabled: props.floors.length <= 1,
            onSelect: () => props.onAllFloors(!props.allFloors),
          },
          { label: 'Add a floor', onSelect: props.onAdd },
          {
            label: 'Rename this floor',
            disabled: props.allFloors,
            onSelect: () => setEditing(true),
          },
          {
            label: 'Remove this floor',
            disabled: props.floors.length <= 1 || props.allFloors,
            danger: true,
            onSelect: props.onRemove,
          },
        ]}
      />
    </div>
  )
}
