/**
 * The toolbar.
 *
 * Every tool is a VERB and says what it draws (owner, 2026-08-16: *"hard to
 * understand from the command bars what to do — what is the meaning of the
 * numbers?"*). The keyboard shortcuts still exist; they live in the tooltip,
 * because a bare "1" next to a button is a puzzle, not a hint.
 */

import { useRef } from 'react'

import type { Underlay } from '../core/model'
import { Menu } from './Menu'
import type { Theme, Tool } from './types'

type Props = {
  tool: Tool
  theme: Theme
  saved: 'saving' | 'saved' | 'failed'
  underlay: Underlay | null
  canUndo: boolean
  canRedo: boolean
  canPaste: boolean
  selectedCount: number
  onTool: (t: Tool) => void
  onTheme: (t: Theme) => void
  onUndo: () => void
  onRedo: () => void
  onFit: () => void
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

const TOOLS: { tool: Tool; label: string; hint: string; key: string }[] = [
  {
    tool: 'select',
    label: 'Move & edit',
    hint: 'Drag a room or a bookcase to move it. Drag a handle to resize. Ctrl+click adds to the selection; drag empty space to select several.',
    key: '1',
  },
  {
    tool: 'room',
    label: 'Draw room',
    hint: 'Drag a rectangle. Its edges snap to the grid, and to any room already drawn — so rooms attach.',
    key: '2',
  },
  {
    tool: 'case',
    label: 'Draw bookcase',
    hint: 'Drag a rectangle inside a room. It snaps flush to the wall, and the books face into the room.',
    key: '3',
  },
  {
    tool: 'pan',
    label: 'Pan',
    hint: 'Slide the plan. Nothing else moves the view: the middle mouse button and two fingers do the same.',
    key: '4',
  },
]

const SAVED_TEXT = {
  saving: 'saving…',
  saved: 'saved in this browser',
  failed: 'NOT saved — use Save to file',
} as const

export function Toolbar(props: Props) {
  const importRef = useRef<HTMLInputElement | null>(null)
  const underlayRef = useRef<HTMLInputElement | null>(null)
  const nothingSelected = props.selectedCount === 0

  return (
    <header className="toolbar">
      <div className="brand">
        <strong>map lab</strong>
        <span className="tag">P6.0</span>
      </div>

      <div className="group tools" role="radiogroup" aria-label="tool">
        {TOOLS.map((t) => (
          <button
            key={t.tool}
            type="button"
            role="radio"
            aria-checked={props.tool === t.tool}
            className={props.tool === t.tool ? 'on' : ''}
            title={`${t.hint}  (key ${t.key})`}
            onClick={() => props.onTool(t.tool)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* All five edit commands live here now that every one of them has a
          working shortcut — five toolbar slots returned to the canvas. */}
      <div className="group">
        <Menu
          label="Edit"
          items={[
            { label: 'Undo', shortcut: 'Ctrl+Z', disabled: !props.canUndo, onSelect: props.onUndo },
            {
              label: 'Redo',
              shortcut: 'Ctrl+Y',
              disabled: !props.canRedo,
              onSelect: props.onRedo,
            },
            {
              label: 'Copy',
              shortcut: 'Ctrl+C',
              disabled: nothingSelected,
              onSelect: props.onCopy,
            },
            {
              label: 'Paste',
              shortcut: 'Ctrl+V',
              disabled: !props.canPaste,
              onSelect: props.onPaste,
            },
            {
              label: props.selectedCount > 1 ? `Delete ${props.selectedCount}` : 'Delete',
              shortcut: 'Del',
              disabled: nothingSelected,
              danger: true,
              onSelect: props.onDelete,
            },
          ]}
        />
      </div>

      <div className="group">
        <button
          type="button"
          onClick={props.onFit}
          title="Zoom and centre so the whole plan is on screen. This is how you get back when you have zoomed or panned somewhere unfamiliar."
        >
          Show all
        </button>
        <button
          type="button"
          aria-label={
            props.theme === 'dark' ? 'switch to a white background' : 'switch to a black background'
          }
          title="Black or white background"
          onClick={() => props.onTheme(props.theme === 'dark' ? 'light' : 'dark')}
        >
          {props.theme === 'dark' ? 'White bg' : 'Black bg'}
        </button>
      </div>

      <div className="group">
        <button
          type="button"
          onClick={() => underlayRef.current?.click()}
          title="Put a photo of a floor plan behind the canvas and draw over it"
        >
          Trace a sketch…
        </button>
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
        {props.underlay && (
          <>
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
          </>
        )}
      </div>

      <div className="group right">
        <span
          className={`saved saved-${props.saved}`}
          role="status"
          title="Every change is written to this browser's storage immediately. Clearing site data loses it — Save to file is the copy that survives."
        >
          {SAVED_TEXT[props.saved]}
        </span>
        <button type="button" onClick={props.onExport} title="Download the plan as a JSON file">
          Save to file
        </button>
        <button type="button" onClick={() => importRef.current?.click()}>
          Open file
        </button>
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
        <button type="button" className="danger" onClick={props.onClear}>
          Clear
        </button>
      </div>
    </header>
  )
}
