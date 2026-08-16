/**
 * The toolbar: four menus, four icons, and the storey.
 *
 * It used to be fifteen buttons on one line (owner, 2026-08-16: *"way too many
 * buttons on the control line"*). The rule that shrank it: **a command lives
 * in a menu; only the tools get a permanent button**, because a tool is what
 * you switch between while drawing and everything else is something you do
 * once. The icons carry tooltips rather than labels for the same reason.
 */

import { useRef } from 'react'

import type { Floor, Underlay } from '../core/model'
import { Menu } from './Menu'
import type { Theme, Tool } from './types'

type Props = {
  tool: Tool
  theme: Theme
  floors: Floor[]
  floorId: string
  ghosts: boolean
  allFloors: boolean
  saved: 'saving' | 'saved' | 'failed'
  underlay: Underlay | null
  canUndo: boolean
  canRedo: boolean
  canPaste: boolean
  selectedCount: number
  onTool: (t: Tool) => void
  onTheme: (t: Theme) => void
  onFloor: (id: string) => void
  onAddFloor: () => void
  onRenameFloor: (id: string, name: string) => void
  onRemoveFloor: () => void
  onGhosts: (on: boolean) => void
  onAllFloors: (on: boolean) => void
  onUndo: () => void
  onRedo: () => void
  onFit: () => void
  onZoom: (factor: number) => void
  onCopy: () => void
  onPaste: () => void
  onDelete: () => void
  onExport: () => void
  onImport: (file: File) => void
  onUnderlay: (file: File) => void
  onUnderlayChange: (patch: Partial<Underlay>) => void
  onUnderlayClear: () => void
  onClear: () => void
}

/** The four tools, as icons. `auto` is the arrow and it is the default: it
 *  guesses from where you press, and the other two are how you overrule it. */
const TOOLS: { tool: Tool; icon: string; label: string; hint: string }[] = [
  {
    tool: 'auto',
    icon: '➤',
    label: 'Arrow',
    hint: 'Arrow (1) — guesses from where you press: a room’s border moves it, inside a room draws a bookcase, outside every room draws a room. Ctrl+drag selects several.',
  },
  {
    tool: 'room',
    icon: '▭',
    label: 'Draw room',
    hint: 'Draw room (2) — always draws a room, wherever you start.',
  },
  {
    tool: 'case',
    icon: '▬',
    label: 'Draw bookcase',
    hint: 'Draw bookcase (3) — always draws a bookcase, wherever you start.',
  },
  { tool: 'pan', icon: '✋', label: 'Pan', hint: 'Pan (4) — slide the plan. So do the middle button and two fingers.' },
]

const SAVED_TEXT = {
  saving: 'saving…',
  saved: 'saved here',
  failed: 'NOT saved — use File ▸ Save to file',
} as const

export function Toolbar(props: Props) {
  const importRef = useRef<HTMLInputElement | null>(null)
  const underlayRef = useRef<HTMLInputElement | null>(null)
  const nothingSelected = props.selectedCount === 0
  const onlyFloor = props.floors.length <= 1

  return (
    <header className="toolbar">
      <div className="group icons" role="radiogroup" aria-label="tool">
        {TOOLS.map((t) => (
          <button
            key={t.tool}
            type="button"
            role="radio"
            aria-checked={props.tool === t.tool}
            aria-label={t.label}
            className={`icon${props.tool === t.tool ? ' on' : ''}`}
            title={t.hint}
            onClick={() => props.onTool(t.tool)}
          >
            {t.icon}
          </button>
        ))}
      </div>

      <div className="group">
        <Menu
          label="File"
          items={[
            { label: 'Save to file…', onSelect: props.onExport },
            { label: 'Open file…', onSelect: () => importRef.current?.click() },
            { label: 'Clear the plan', danger: true, onSelect: props.onClear },
          ]}
        />
        <Menu
          label="Edit"
          items={[
            { label: 'Undo', shortcut: 'Ctrl+Z', disabled: !props.canUndo, onSelect: props.onUndo },
            { label: 'Redo', shortcut: 'Ctrl+Y', disabled: !props.canRedo, onSelect: props.onRedo },
            { label: 'Copy', shortcut: 'Ctrl+C', disabled: nothingSelected, onSelect: props.onCopy },
            { label: 'Paste', shortcut: 'Ctrl+V', disabled: !props.canPaste, onSelect: props.onPaste },
            {
              label: props.selectedCount > 1 ? `Delete ${props.selectedCount}` : 'Delete',
              shortcut: 'Del',
              disabled: nothingSelected,
              danger: true,
              onSelect: props.onDelete,
            },
          ]}
        />
        <Menu
          label="View"
          items={[
            { label: 'Zoom in', shortcut: '+', onSelect: () => props.onZoom(1.25) },
            { label: 'Zoom out', shortcut: '−', onSelect: () => props.onZoom(1 / 1.25) },
            { label: 'Show all', onSelect: props.onFit },
            {
              label: 'Every floor at once',
              checked: props.allFloors,
              disabled: onlyFloor,
              onSelect: () => props.onAllFloors(!props.allFloors),
            },
            {
              label: 'Ghost the other floors',
              checked: props.ghosts,
              disabled: onlyFloor,
              onSelect: () => props.onGhosts(!props.ghosts),
            },
            {
              label: props.theme === 'dark' ? 'White background' : 'Black background',
              onSelect: () => props.onTheme(props.theme === 'dark' ? 'light' : 'dark'),
            },
          ]}
        />
        <Menu
          label="Apartment"
          items={[
            { label: 'Draw a room', shortcut: '2', onSelect: () => props.onTool('room') },
            { label: 'Draw a bookcase', shortcut: '3', onSelect: () => props.onTool('case') },
            { label: 'Add a floor', onSelect: props.onAddFloor },
            {
              label: 'Remove this floor',
              disabled: onlyFloor,
              danger: true,
              onSelect: props.onRemoveFloor,
            },
            { label: 'Trace a sketch…', onSelect: () => underlayRef.current?.click() },
          ]}
        />
      </div>

      <div className="group floors">
        <select
          className="rtl-safe"
          aria-label="which floor is shown"
          value={props.floorId}
          onChange={(e) => props.onFloor(e.target.value)}
          disabled={props.allFloors}
        >
          {props.floors.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <input
          className="rtl-safe floor-name"
          aria-label="rename this floor"
          value={props.floors.find((f) => f.id === props.floorId)?.name ?? ''}
          onChange={(e) => props.onRenameFloor(props.floorId, e.target.value)}
        />
      </div>

      {props.underlay && (
        <div className="group">
          <label className="slider">
            <span>fade</span>
            <input
              type="range"
              min={5}
              max={100}
              value={Math.round(props.underlay.opacity * 100)}
              aria-label="underlay opacity"
              onChange={(e) => props.onUnderlayChange({ opacity: Number(e.target.value) / 100 })}
            />
          </label>
          <label className="slider">
            <span>size</span>
            <input
              type="range"
              min={10}
              max={200}
              value={Math.round(props.underlay.scale)}
              aria-label="underlay size"
              onChange={(e) => props.onUnderlayChange({ scale: Number(e.target.value) })}
            />
          </label>
          <button type="button" onClick={props.onUnderlayClear} aria-label="remove the underlay">
            ✕
          </button>
        </div>
      )}

      <div className="group right">
        <span
          className={`saved saved-${props.saved}`}
          role="status"
          title="Every change is written to this browser's storage immediately. Clearing site data loses it — File ▸ Save to file is the copy that survives."
        >
          {SAVED_TEXT[props.saved]}
        </span>
      </div>

      <input
        ref={importRef}
        type="file"
        accept="application/json,.json"
        hidden
        aria-label="open a plan file"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) props.onImport(f)
          e.target.value = ''
        }}
      />
      <input
        ref={underlayRef}
        type="file"
        accept="image/*"
        hidden
        aria-label="upload a floor plan to trace"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) props.onUnderlay(f)
          e.target.value = ''
        }}
      />
    </header>
  )
}
